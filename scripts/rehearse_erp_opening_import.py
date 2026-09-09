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

from app.api.data_migration import validate_row
from app.config import get_settings


FILES = (
    ("opening_receivables", "opening_receivables.csv"),
    ("opening_payables", "opening_payables.csv"),
    ("opening_stock", "opening_stock_provisional.csv"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def verify_package(package: Path) -> list[dict[str, object]]:
    expected = {}
    for line in (package / "SHA256SUMS.txt").read_text(encoding="utf-8-sig").splitlines():
        digest, name = line.split("  ", 1)
        expected[name] = digest.upper()
    results = []
    for name, expected_digest in sorted(expected.items()):
        actual = sha256(package / name)
        results.append({"file": name, "expected": expected_digest, "actual": actual, "matched": actual == expected_digest})
    if not results or not all(row["matched"] for row in results):
        raise RuntimeError("Opening package checksum verification failed")
    return results


def read_rows(path: Path) -> list[dict[str, str | None]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [
            {key: (value.strip() or None) if value is not None else None for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]


def configure_rehearsal_locations(db, entity_id: str, mappings: dict) -> None:
    names = {"BL0001": "Asas General Trading LLC", "RAK": "RAK", "DXB": "DXB"}
    geography = {
        "BL0001": ("Sharjah", "Sharjah"),
        "RAK": ("Ras Al Khaimah", "Ras Al Khaimah"),
        "DXB": ("Dubai", "Dubai"),
    }
    for source_name, mapping in mappings.items():
        branch_code = mapping["target_branch_code"]
        branch = db.execute(
            "SELECT id FROM branches WHERE legal_entity_id=%s AND code=%s", (entity_id, branch_code),
        ).fetchone()
        if not branch:
            branch = db.execute(
                """INSERT INTO branches(legal_entity_id,code,name,country_code,emirate,city,active)
                   VALUES(%s,%s,%s,'AE',%s,%s,true) RETURNING id""",
                (entity_id, branch_code, names.get(branch_code, source_name), *geography.get(branch_code, (None, None))),
            ).fetchone()
        warehouse = db.execute(
            "SELECT id FROM warehouses WHERE branch_id=%s AND code=%s",
            (branch["id"], mapping["warehouse_code"]),
        ).fetchone()
        if not warehouse:
            warehouse = db.execute(
                "INSERT INTO warehouses(branch_id,code,name,active) VALUES(%s,%s,%s,true) RETURNING id",
                (branch["id"], mapping["warehouse_code"], f"{source_name} Warehouse"),
            ).fetchone()
        db.execute(
            """INSERT INTO warehouse_locations(warehouse_id,code,name,location_type,active)
               VALUES(%s,%s,'Storage','storage',true)
               ON CONFLICT(warehouse_id,code) DO NOTHING""",
            (warehouse["id"], mapping["location_code"]),
        )


def main() -> None:
    raise RuntimeError("RETRACTED: this script targeted the separate D:\\Klen+ ERP project; see docs/CROSS_PROJECT_CONTAMINATION_AUDIT_20260909.md")
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--database-role", choices=("isolated_rehearsal", "operational_staging"), default="isolated_rehearsal")
    args = parser.parse_args()
    package, output = args.package.resolve(), args.output.resolve()
    if output.exists():
        raise RuntimeError(f"Output already exists; overwrite refused: {output}")
    checksum_control = verify_package(package)
    package_status = json.loads((package / "PACKAGE_STATUS.json").read_text(encoding="utf-8"))
    if package_status.get("posting_enabled") is not False or package_status.get("promotion_allowed") is not False:
        raise RuntimeError("Package does not preserve non-posting controls")

    settings = get_settings()
    entity_id = settings.default_legal_entity_id
    if not entity_id:
        raise RuntimeError("DEFAULT_LEGAL_ENTITY_ID is required")
    run_tag = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    business_tables = ("stock_movements", "inventory_balances", "customer_invoices", "supplier_invoices", "journal_entries")
    results = []
    with psycopg.connect(settings.database_url, row_factory=dict_row) as db:
        before = {table: db.execute(f"SELECT count(*) count FROM {table}").fetchone()["count"] for table in business_tables}
        with db.transaction():
            configure_rehearsal_locations(
                db, entity_id, json.loads((package / "locations.json").read_text(encoding="utf-8")),
            )
            user = db.execute("SELECT id FROM app_users WHERE active ORDER BY created_at LIMIT 1").fetchone()
            if not user:
                raise RuntimeError("Rehearsal database has no active bootstrap user")
            for index, (kind, filename) in enumerate(FILES, 1):
                rows = read_rows(package / filename)
                batch = db.execute(
                    """INSERT INTO data_import_batches(
                           batch_no,legal_entity_id,import_type,file_name,file_checksum,status,total_rows,created_by
                       ) VALUES(%s,%s,%s,%s,%s,'uploaded',%s,%s) RETURNING id,batch_no""",
                    (f"ROPN-{run_tag}-{index}", entity_id, kind, filename, sha256(package / filename).lower(), len(rows), user["id"]),
                ).fetchone()
                seen, counts, sample_errors = set(), {"valid": 0, "error": 0, "duplicate": 0}, []
                source_total = Decimal("0")
                metric = "quantity" if kind == "opening_stock" else "amount"
                metric_field = "quantity_base" if kind == "opening_stock" else "amount"
                for row_number, row in enumerate(rows, 2):
                    normalized, errors, status = validate_row(db, kind, row, seen)
                    counts[status] += 1
                    source_total += Decimal(normalized.get(metric_field) or "0")
                    db.execute(
                        """INSERT INTO data_import_rows(batch_id,row_no,raw_data,normalized_data,validation_status,errors)
                           VALUES(%s,%s,%s,%s,%s,%s)""",
                        (batch["id"], row_number, Jsonb(row), Jsonb(normalized), status, Jsonb(errors)),
                    )
                    if errors and len(sample_errors) < 20:
                        sample_errors.append({"row": row_number, "errors": errors})
                totals = {"row_count": str(len(rows)), metric: str(source_total)}
                db.execute(
                    """UPDATE data_import_batches SET status='validated',valid_rows=%s,error_rows=%s,
                       duplicate_rows=%s,source_totals=%s,validated_at=now() WHERE id=%s""",
                    (counts["valid"], counts["error"], counts["duplicate"], Jsonb(totals), batch["id"]),
                )
                results.append({"kind": kind, "batch_no": batch["batch_no"], "total": len(rows), **counts, "source_totals": totals, "sample_errors": sample_errors})
        after = {table: db.execute(f"SELECT count(*) count FROM {table}").fetchone()["count"] for table in business_tables}

    failed = [row["kind"] for row in results if row["error"] or row["duplicate"]]
    report = {
        "schema_version": 1, "status": "passed_non_posting" if not failed else "failed_validation",
        "validated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "package": str(package), "database": args.database_role,
        "checksum_control": checksum_control, "validation_results": results,
        "target_business_table_counts_before": before, "target_business_table_counts_after": after,
        "target_business_tables_unchanged": before == after, "failed_kinds": failed,
        "source_mutation": False, "operational_staging_mutation": args.database_role == "operational_staging",
        "operational_staging_mutation_scope": "configuration and non-posting migration batches only" if args.database_role == "operational_staging" else "none",
        "posting_enabled": False, "promotion_allowed": False,
        "qualification": "Opening batches validate in an isolated database only; nothing was posted.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "validation_results": results, "target_business_tables_unchanged": before == after, "output": str(output)}, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
