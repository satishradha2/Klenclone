from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.api.data_migration import validate_row
from app.config import get_settings


UOM_NAMES = {
    "BOX": "Box",
    "BUNDLE": "Bundle",
    "CARTON": "Carton",
    "DOZEN": "Dozen",
    "KG": "Kilogram",
    "PACK": "Pack",
    "PCS": "Pieces",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def verify_package(package: Path) -> dict:
    expected = {}
    for line in (package / "SHA256SUMS.txt").read_text(encoding="utf-8-sig").splitlines():
        digest, name = line.split("  ", 1)
        expected[name] = digest.upper()
    results = []
    for name, digest in sorted(expected.items()):
        actual = sha256(package / name)
        results.append({"file": name, "expected": digest, "actual": actual, "matched": digest == actual})
    if not results or not all(item["matched"] for item in results):
        raise RuntimeError("ERP rehearsal package checksum verification failed")
    return {"status": "pass", "files": results}


def read_rows(path: Path) -> list[dict[str, str | None]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{key: (value.strip() or None) if value is not None else None for key, value in row.items()}
                for row in csv.DictReader(handle)]


def main() -> None:
    raise RuntimeError("RETRACTED: this script targeted the separate D:\\Klen+ ERP project; see docs/CROSS_PROJECT_CONTAMINATION_AUDIT_20260909.md")
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--database-role", choices=("isolated_rehearsal", "operational_staging"),
                        default="isolated_rehearsal")
    args = parser.parse_args()
    package = args.package.resolve()
    output = args.output.resolve()
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
    validation_results = []

    with psycopg.connect(settings.database_url, row_factory=dict_row) as db:
        business_tables = ("products", "partners", "stock_movements", "customer_invoices", "supplier_invoices")
        target_counts_before = {
            table: db.execute(f"SELECT count(*) count FROM {table}").fetchone()["count"]
            for table in business_tables
        }
        with db.transaction():
            user = db.execute("SELECT id FROM app_users WHERE active ORDER BY created_at LIMIT 1").fetchone()
            if not user:
                raise RuntimeError("Rehearsal database has no active bootstrap user")
            for code in package_status["required_configuration"]["units_of_measure"]:
                db.execute(
                    """INSERT INTO units_of_measure(legal_entity_id,code,name,unit_type,decimal_places,active)
                       VALUES(%s,%s,%s,'quantity',3,true) ON CONFLICT(legal_entity_id,code) DO NOTHING""",
                    (entity_id, code, UOM_NAMES.get(code, code.title())),
                )
            for term in package_status["required_configuration"]["payment_terms"]:
                db.execute(
                    """INSERT INTO payment_terms(legal_entity_id,code,name,due_days,active)
                       VALUES(%s,%s,%s,%s,true) ON CONFLICT(legal_entity_id,code) DO NOTHING""",
                    (entity_id, term["code"], "Cash on Delivery" if term["code"] == "COD" else f"Net {term['due_days']} Days", term["due_days"]),
                )

            for index, (kind, filename) in enumerate((
                ("products", "products.csv"),
                ("customers", "customers.csv"),
                ("suppliers", "suppliers.csv"),
            ), start=1):
                rows = read_rows(package / filename)
                batch = db.execute(
                    """INSERT INTO data_import_batches(
                           batch_no,legal_entity_id,import_type,file_name,file_checksum,status,total_rows,created_by
                       ) VALUES(%s,%s,%s,%s,%s,'uploaded',%s,%s) RETURNING id,batch_no""",
                    (f"RHR-{run_tag}-{index}", entity_id, kind, filename, sha256(package / filename).lower(), len(rows), user["id"]),
                ).fetchone()
                seen = set()
                counts = {"valid": 0, "error": 0, "duplicate": 0}
                errors = []
                for row_number, row in enumerate(rows, start=2):
                    normalized, row_errors, status = validate_row(db, kind, row, seen)
                    counts[status] += 1
                    db.execute(
                        """INSERT INTO data_import_rows(
                               batch_id,row_no,raw_data,normalized_data,validation_status,errors
                           ) VALUES(%s,%s,%s,%s,%s,%s)""",
                        (batch["id"], row_number, Jsonb(row), Jsonb(normalized), status, Jsonb(row_errors)),
                    )
                    if row_errors:
                        errors.append({"row": row_number, "errors": row_errors})
                db.execute(
                    """UPDATE data_import_batches SET status='validated',valid_rows=%s,error_rows=%s,
                       duplicate_rows=%s,source_totals=%s,validated_at=now() WHERE id=%s""",
                    (counts["valid"], counts["error"], counts["duplicate"], Jsonb({"row_count": str(len(rows))}), batch["id"]),
                )
                validation_results.append({
                    "kind": kind,
                    "batch_no": batch["batch_no"],
                    "total": len(rows),
                    **counts,
                    "sample_errors": errors[:20],
                })

        target_counts_after = {
            table: db.execute(f"SELECT count(*) count FROM {table}").fetchone()["count"]
            for table in business_tables
        }
        batch_counts = db.execute(
            """SELECT import_type,status,total_rows,valid_rows,error_rows,duplicate_rows
               FROM data_import_batches ORDER BY created_at,batch_no"""
        ).fetchall()

    failed = [item["kind"] for item in validation_results if item["error"] or item["duplicate"]]
    report = {
        "schema_version": 1,
        "status": "passed_non_posting" if not failed else "failed_validation",
        "validated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "package": str(package),
        "database": args.database_role,
        "checksum_control": checksum_control,
        "validation_results": validation_results,
        "database_batches": batch_counts,
        "target_business_table_counts_before": target_counts_before,
        "target_business_table_counts_after": target_counts_after,
        "target_business_tables_unchanged": target_counts_before == target_counts_after,
        "failed_kinds": failed,
        "source_mutation": False,
        "preserved_clone_mutation": False,
        "operational_staging_mutation": args.database_role == "operational_staging",
        "operational_staging_mutation_scope": "configuration and non-posting migration batches only" if args.database_role == "operational_staging" else "none",
        "posting_enabled": False,
        "promotion_allowed": False,
        "qualification": "Only configuration required by source masters plus migration batches and validated rows were written; no business master or transaction was posted.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "validation_results": validation_results,
        "target_business_table_counts_before": target_counts_before,
        "target_business_table_counts_after": target_counts_after,
        "target_business_tables_unchanged": target_counts_before == target_counts_after,
        "posting_enabled": False,
        "promotion_allowed": False,
        "output": str(output),
    }, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
