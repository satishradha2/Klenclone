from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.api.data_migration import audit, post_row, validate_row
from app.config import get_settings


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def read_rows(path: Path) -> list[dict[str, str | None]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{key: (value.strip() or None) if value is not None else None for key, value in row.items()}
                for row in csv.DictReader(handle)]


def actor(db, name: str, permission: str) -> dict:
    row = db.execute(
        """SELECT DISTINCT u.id,u.display_name FROM app_users u
           JOIN user_roles ur ON ur.user_id=u.id JOIN role_permissions rp ON rp.role_id=ur.role_id
           JOIN permissions p ON p.id=rp.permission_id
           WHERE u.active AND u.display_name=%s AND p.code IN (%s,'*')""", (name, permission),
    ).fetchone()
    if not row:
        raise RuntimeError(f"Required staging actor is unavailable: {name} / {permission}")
    return {"id": str(row["id"]), "display_name": row["display_name"]}


def main() -> None:
    raise RuntimeError("RETRACTED: this script targeted the separate D:\\Klen+ ERP project; see docs/CROSS_PROJECT_CONTAMINATION_AUDIT_20260909.md")
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-prefix", required=True)
    args = parser.parse_args()
    package, output = args.package.resolve(), args.output.resolve()
    if output.exists():
        raise RuntimeError(f"Output already exists; overwrite refused: {output}")
    expected = {}
    for line in (package / "SHA256SUMS.txt").read_text(encoding="utf-8-sig").splitlines():
        digest, name = line.split("  ", 1)
        expected[name] = digest
    checksum_control = [{"file": name, "matched": sha256(package / name) == digest, "sha256": digest} for name, digest in sorted(expected.items())]
    if not checksum_control or not all(row["matched"] for row in checksum_control):
        raise RuntimeError("Package checksum verification failed")
    package_status = json.loads((package / "PACKAGE_STATUS.json").read_text(encoding="utf-8"))
    if package_status.get("posting_enabled") is not False or package_status.get("promotion_allowed") is not False:
        raise RuntimeError("Package is not sealed as non-posting")

    settings = get_settings()
    if settings.environment.lower() == "production":
        raise RuntimeError("This staging operation is forbidden in production")
    entity_id = settings.default_legal_entity_id
    definitions = (
        ("products", "products_delta.csv"),
        ("opening_receivables", "opening_receivables.csv"),
        ("opening_payables", "opening_payables.csv"),
        ("opening_gl", "opening_advances_gl.csv"),
        ("opening_stock", "opening_stock_positive.csv"),
        ("opening_stock_adjustments", "opening_stock_negative_adjustments.csv"),
    )
    with psycopg.connect(settings.database_url, row_factory=dict_row) as db:
        submitter = actor(db, "System Administrator", "migration.manage")
        approver = actor(db, "Export UAT Checker", "migration.approve")
        poster = actor(db, "System Administrator", "migration.approve")
        if submitter["id"] == approver["id"] or approver["id"] == poster["id"]:
            raise RuntimeError("Staging maker-checker separation is not satisfied")
        business_tables = ("products", "stock_movements", "inventory_balances", "customer_invoices", "supplier_invoices", "journal_entries")
        before = {name: db.execute(f"SELECT count(*) count FROM {name}").fetchone()["count"] for name in business_tables}
        results, created_batches = [], []
        for index, (kind, filename) in enumerate(definitions, 1):
            source_rows = read_rows(package / filename)
            batch = db.execute(
                """INSERT INTO data_import_batches(batch_no,legal_entity_id,import_type,file_name,file_checksum,status,total_rows,created_by)
                   VALUES(%s,%s,%s,%s,%s,'uploaded',%s,%s) RETURNING id,batch_no""",
                (f"{args.batch_prefix}-{index}", entity_id, kind, filename, sha256(package / filename).lower(), len(source_rows), submitter["id"]),
            ).fetchone()
            seen, counts, row_errors = set(), {"valid": 0, "error": 0, "duplicate": 0}, []
            totals = {"row_count": Decimal("0"), "quantity": Decimal("0"), "amount": Decimal("0"), "debit": Decimal("0"), "credit": Decimal("0")}
            for row_number, row in enumerate(source_rows, 2):
                normalized, errors, outcome = validate_row(db, kind, row, seen)
                counts[outcome] += 1
                totals["row_count"] += 1
                if kind in ("opening_stock", "opening_stock_adjustments"):
                    totals["quantity"] += Decimal(normalized.get("quantity_base") or "0")
                elif kind in ("opening_receivables", "opening_payables"):
                    totals["amount"] += Decimal(normalized.get("amount") or "0")
                elif kind == "opening_gl":
                    totals["debit"] += Decimal(normalized.get("debit") or "0")
                    totals["credit"] += Decimal(normalized.get("credit") or "0")
                db.execute(
                    "INSERT INTO data_import_rows(batch_id,row_no,raw_data,normalized_data,validation_status,errors) VALUES(%s,%s,%s,%s,%s,%s)",
                    (batch["id"], row_number, Jsonb(row), Jsonb(normalized), outcome, Jsonb(errors)),
                )
                if errors:
                    row_errors.append({"row": row_number, "errors": errors})
            source_totals = {key: str(value) for key, value in totals.items()}
            db.execute(
                """UPDATE data_import_batches SET status='validated',valid_rows=%s,error_rows=%s,
                   duplicate_rows=%s,source_totals=%s,validated_at=now() WHERE id=%s""",
                (counts["valid"], counts["error"], counts["duplicate"], Jsonb(source_totals), batch["id"]),
            )
            audit(db, submitter, "validate_staging_refresh", batch["id"], {**counts, "production_approval": False})
            if counts["error"] or counts["duplicate"]:
                raise RuntimeError(f"Staging refresh validation failed for {kind}: {row_errors[:10]}")
            created_batches.append({"id": batch["id"], "batch_no": batch["batch_no"], "kind": kind})
            results.append({"kind": kind, "batch_no": batch["batch_no"], "total": len(source_rows), **counts, "source_totals": source_totals})
            if kind == "products":
                db.execute("UPDATE data_import_batches SET status='submitted',submitted_by=%s,submitted_at=now() WHERE id=%s", (submitter["id"], batch["id"]))
                audit(db, submitter, "submit_staging_refresh", batch["id"], {"production_approval": False})
                db.execute("UPDATE data_import_batches SET status='approved',approved_by=%s,approved_at=now() WHERE id=%s", (approver["id"], batch["id"]))
                audit(db, approver, "approve_staging_refresh", batch["id"], {"production_approval": False})
                control = Decimal("0")
                for import_row in db.execute("SELECT * FROM data_import_rows WHERE batch_id=%s AND validation_status='valid' ORDER BY row_no", (batch["id"],)).fetchall():
                    table, target, value = post_row(db, kind, import_row["normalized_data"], poster, batch["id"])
                    db.execute("UPDATE data_import_rows SET validation_status='posted',target_table=%s,target_id=%s,posted_at=now() WHERE id=%s", (table, target, import_row["id"]))
                    control += value
                db.execute("INSERT INTO data_import_reconciliations(batch_id,metric_code,source_value,posted_value) VALUES(%s,'row_count',%s,%s)", (batch["id"], len(source_rows), control))
                db.execute("UPDATE data_import_batches SET status='posted',posted_by=%s,posted_at=now(),posted_totals=%s WHERE id=%s", (poster["id"], Jsonb({"row_count": len(source_rows)}), batch["id"]))
                audit(db, poster, "post_staging_refresh", batch["id"], {"rows": len(source_rows), "production_approval": False})
        db.commit()
        after = {name: db.execute(f"SELECT count(*) count FROM {name}").fetchone()["count"] for name in business_tables}
        final_batches = db.execute(
            "SELECT batch_no,import_type,status,total_rows,valid_rows,error_rows,duplicate_rows FROM data_import_batches WHERE batch_no LIKE %s ORDER BY batch_no",
            (args.batch_prefix + "-%",),
        ).fetchall()

    report = {
        "schema_version": 1, "status": "staged_non_posting", "completed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "package": str(package), "database": "operational_staging", "checksum_control": checksum_control,
        "validation_results": results, "batches": final_batches,
        "target_business_table_counts_before": before, "target_business_table_counts_after": after,
        "expected_business_mutation": {"products": len(read_rows(package / "products_delta.csv"))},
        "financial_or_stock_posting_performed": False, "source_mutation": False,
        "production_approval": False,
        "qualification": "Only the five source product masters were posted in staging. All opening finance and inventory batches remain validated and unposted.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "batches": final_batches, "before": before, "after": after, "financial_or_stock_posting_performed": False, "output": str(output)}, indent=2, default=str))


if __name__ == "__main__":
    main()
