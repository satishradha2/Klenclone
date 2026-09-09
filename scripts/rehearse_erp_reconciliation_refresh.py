from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from app.api.data_migration import post_row, validate_row
from app.config import get_settings


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def rows(path: Path) -> list[dict[str, str | None]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{key: (value.strip() or None) if value is not None else None for key, value in row.items()}
                for row in csv.DictReader(handle)]


def main() -> None:
    raise RuntimeError("RETRACTED: this script targeted the separate D:\\Klen+ ERP project; see docs/CROSS_PROJECT_CONTAMINATION_AUDIT_20260909.md")
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package, output = args.package.resolve(), args.output.resolve()
    if output.exists():
        raise RuntimeError(f"Output already exists; overwrite refused: {output}")
    expected = {}
    for line in (package / "SHA256SUMS.txt").read_text(encoding="utf-8-sig").splitlines():
        digest, name = line.split("  ", 1)
        expected[name] = digest
    checksum_control = [{"file": name, "expected": digest, "actual": sha256(package / name), "matched": digest == sha256(package / name)} for name, digest in sorted(expected.items())]
    if not checksum_control or not all(item["matched"] for item in checksum_control):
        raise RuntimeError("Package checksum verification failed")
    status = json.loads((package / "PACKAGE_STATUS.json").read_text(encoding="utf-8"))
    if status.get("posting_enabled") is not False or status.get("promotion_allowed") is not False:
        raise RuntimeError("Package is not sealed as non-posting")

    settings = get_settings()
    entity_id = settings.default_legal_entity_id
    validation = []
    with psycopg.connect(settings.database_url, row_factory=dict_row) as db:
        business_tables = ("products", "partners", "stock_movements", "inventory_balances", "customer_invoices", "supplier_invoices", "journal_entries")
        before = {name: db.execute(f"SELECT count(*) count FROM {name}").fetchone()["count"] for name in business_tables}
        user = db.execute("SELECT id FROM app_users WHERE active ORDER BY created_at LIMIT 1").fetchone()
        if not user:
            raise RuntimeError("No active rehearsal user")
        db.execute("BEGIN")
        try:
            product_rows = rows(package / "products_delta.csv")
            seen, counts, errors = set(), {"valid": 0, "error": 0, "duplicate": 0}, []
            normalized_products = []
            for number, row in enumerate(product_rows, 2):
                normalized, row_errors, outcome = validate_row(db, "products", row, seen)
                counts[outcome] += 1
                if row_errors:
                    errors.append({"row": number, "errors": row_errors})
                else:
                    normalized_products.append(normalized)
            validation.append({"kind": "products_delta", "total": len(product_rows), **counts, "sample_errors": errors[:20]})
            if errors:
                raise RuntimeError("Product delta does not validate")
            for normalized in normalized_products:
                post_row(db, "products", normalized, {"id": str(user["id"])}, uuid4())

            for kind, filename in (
                ("opening_receivables", "opening_receivables.csv"),
                ("opening_payables", "opening_payables.csv"),
                ("opening_gl", "opening_advances_gl.csv"),
                ("opening_stock", "opening_stock_positive.csv"),
            ):
                source_rows = rows(package / filename)
                seen, counts, errors = set(), {"valid": 0, "error": 0, "duplicate": 0}, []
                for number, row in enumerate(source_rows, 2):
                    _, row_errors, outcome = validate_row(db, kind, row, seen)
                    if kind == "opening_gl" and row.get("partner_code") and not db.execute(
                        "SELECT 1 FROM partners WHERE legal_entity_id=%s AND code=%s", (entity_id, row["partner_code"]),
                    ).fetchone():
                        row_errors.append("Partner does not exist")
                        outcome = "error"
                    counts[outcome] += 1
                    if row_errors:
                        errors.append({"row": number, "errors": row_errors})
                validation.append({"kind": kind, "total": len(source_rows), **counts, "sample_errors": errors[:20]})

            negative_rows = rows(package / "opening_stock_negative_adjustments.csv")
            negative_errors = []
            for number, row in enumerate(negative_rows, 2):
                errors = []
                try:
                    if Decimal(str(row.get("quantity_base"))) >= 0:
                        errors.append("quantity_base must be negative")
                except InvalidOperation:
                    errors.append("quantity_base must be numeric")
                if not db.execute("SELECT 1 FROM products WHERE legal_entity_id=%s AND sku=%s", (entity_id, row.get("sku"))).fetchone():
                    errors.append("SKU does not exist")
                if not db.execute(
                    """SELECT 1 FROM warehouse_locations l JOIN warehouses w ON w.id=l.warehouse_id
                       JOIN branches b ON b.id=w.branch_id WHERE b.legal_entity_id=%s AND w.code=%s AND l.code=%s""",
                    (entity_id, row.get("warehouse_code"), row.get("location_code")),
                ).fetchone():
                    errors.append("Warehouse/location does not exist")
                if errors:
                    negative_errors.append({"row": number, "errors": errors})
            validation.append({"kind": "opening_stock_negative_adjustments", "total": len(negative_rows), "valid": len(negative_rows) - len(negative_errors), "error": len(negative_errors), "duplicate": 0, "sample_errors": negative_errors[:20]})
        finally:
            db.rollback()
        after = {name: db.execute(f"SELECT count(*) count FROM {name}").fetchone()["count"] for name in business_tables}

    failed = [item["kind"] for item in validation if item["error"] or item["duplicate"]]
    report = {
        "schema_version": 1, "status": "passed_non_posting" if not failed else "failed_validation",
        "validated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "database": "isolated_rehearsal", "package": str(package),
        "checksum_control": checksum_control, "validation_results": validation,
        "target_business_table_counts_before": before, "target_business_table_counts_after": after,
        "target_business_tables_unchanged": before == after, "failed_kinds": failed,
        "posting_enabled": False, "promotion_allowed": False,
        "qualification": "All rows were reference-validated inside a rolled-back transaction; no business row persisted.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "validation_results": validation, "target_business_tables_unchanged": before == after, "output": str(output)}, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
