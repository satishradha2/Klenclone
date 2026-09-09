from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.api.data_migration import audit, post_row
from app.config import get_settings


BUSINESS_TABLES = (
    "products", "partners", "product_uom_conversions", "partner_addresses",
    "stock_movements", "customer_invoices", "supplier_invoices",
)


def count_tables(db) -> dict[str, int]:
    return {
        table: db.execute(f"SELECT count(*) count FROM {table}").fetchone()["count"]
        for table in BUSINESS_TABLES
    }


def actor(db, display_name: str, permission: str) -> dict:
    row = db.execute(
        """SELECT DISTINCT u.id,u.display_name
           FROM app_users u
           JOIN user_roles ur ON ur.user_id=u.id
           JOIN role_permissions rp ON rp.role_id=ur.role_id
           JOIN permissions p ON p.id=rp.permission_id
           WHERE u.active AND u.display_name=%s AND p.code IN (%s,'*')""",
        (display_name, permission),
    ).fetchone()
    if not row:
        raise RuntimeError(f"Required staging actor or permission is missing: {display_name} / {permission}")
    return {"id": str(row["id"]), "display_name": row["display_name"]}


def main() -> None:
    raise RuntimeError("RETRACTED: this script targeted the separate D:\\Klen+ ERP project; see docs/CROSS_PROJECT_CONTAMINATION_AUDIT_20260909.md")
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-prefix", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise RuntimeError(f"Output already exists; overwrite refused: {output}")

    settings = get_settings()
    if settings.environment.lower() == "production":
        raise RuntimeError("Staging master promotion is forbidden in production")

    with psycopg.connect(settings.database_url, row_factory=dict_row) as db:
        submitter = actor(db, "System Administrator", "migration.manage")
        approver = actor(db, "Export UAT Checker", "migration.approve")
        poster = actor(db, "System Administrator", "migration.approve")
        if submitter["id"] == approver["id"] or approver["id"] == poster["id"]:
            raise RuntimeError("Maker-checker and approver-poster separation is not satisfied")

        batches = db.execute(
            """SELECT * FROM data_import_batches
               WHERE batch_no LIKE %s ORDER BY CASE import_type
                 WHEN 'products' THEN 1 WHEN 'customers' THEN 2 WHEN 'suppliers' THEN 3 ELSE 9 END""",
            (args.batch_prefix + "%",),
        ).fetchall()
        if [row["import_type"] for row in batches] != ["products", "customers", "suppliers"]:
            raise RuntimeError("Expected exactly the products, customers and suppliers rehearsal batches")
        for batch in batches:
            if batch["status"] != "validated" or batch["error_rows"] or batch["duplicate_rows"]:
                raise RuntimeError(f"Batch is not cleanly validated: {batch['batch_no']}")
            valid = db.execute(
                "SELECT count(*) count FROM data_import_rows WHERE batch_id=%s AND validation_status='valid'",
                (batch["id"],),
            ).fetchone()["count"]
            if valid != batch["total_rows"] or valid != batch["valid_rows"]:
                raise RuntimeError(f"Validated row count mismatch: {batch['batch_no']}")

        before = count_tables(db)
        promoted = []
        with db.transaction():
            for batch in batches:
                db.execute(
                    "UPDATE data_import_batches SET status='submitted',submitted_by=%s,submitted_at=now() WHERE id=%s",
                    (submitter["id"], batch["id"]),
                )
                audit(db, submitter, "submit_staging_rehearsal", batch["id"], {"production_approval": False})
                db.execute(
                    "UPDATE data_import_batches SET status='approved',approved_by=%s,approved_at=now() WHERE id=%s",
                    (approver["id"], batch["id"]),
                )
                audit(db, approver, "approve_staging_rehearsal", batch["id"], {"production_approval": False})

                rows = db.execute(
                    "SELECT * FROM data_import_rows WHERE batch_id=%s AND validation_status='valid' ORDER BY row_no",
                    (batch["id"],),
                ).fetchall()
                count = 0
                control = Decimal(0)
                for row in rows:
                    table, target, value = post_row(db, batch["import_type"], row["normalized_data"], poster, batch["id"])
                    db.execute(
                        """UPDATE data_import_rows SET validation_status='posted',target_table=%s,
                           target_id=%s,posted_at=now() WHERE id=%s""",
                        (table, target, row["id"]),
                    )
                    count += 1
                    control += value
                source = Decimal(str((batch["source_totals"] or {}).get("row_count", 0)))
                db.execute(
                    """INSERT INTO data_import_reconciliations(batch_id,metric_code,source_value,posted_value)
                       VALUES(%s,'row_count',%s,%s)""",
                    (batch["id"], source, Decimal(count)),
                )
                db.execute(
                    """UPDATE data_import_batches SET status='posted',posted_by=%s,posted_at=now(),
                       posted_totals=%s WHERE id=%s""",
                    (poster["id"], Jsonb({"row_count": count}), batch["id"]),
                )
                audit(db, poster, "post_staging_rehearsal", batch["id"],
                      {"rows": count, "production_approval": False})
                promoted.append({
                    "batch_no": batch["batch_no"], "kind": batch["import_type"],
                    "source_rows": int(source), "posted_rows": count,
                    "difference": count - int(source),
                })

        after = count_tables(db)
        final_batches = db.execute(
            """SELECT batch_no,import_type,status,total_rows,valid_rows,error_rows,duplicate_rows,
                      (SELECT count(*) FROM data_import_rows r WHERE r.batch_id=b.id AND r.validation_status='posted') posted_rows
               FROM data_import_batches b WHERE batch_no LIKE %s ORDER BY batch_no""",
            (args.batch_prefix + "%",),
        ).fetchall()

    expected_deltas = {
        "products": 465,
        "partners": 882,
        "product_uom_conversions": 0,
        "partner_addresses": None,
        "stock_movements": 0,
        "customer_invoices": 0,
        "supplier_invoices": 0,
    }
    deltas = {table: after[table] - before[table] for table in BUSINESS_TABLES}
    control_failures = []
    for table, expected in expected_deltas.items():
        if expected is not None and deltas[table] != expected:
            control_failures.append(f"{table}: expected delta {expected}, got {deltas[table]}")
    if any(item["difference"] for item in promoted):
        control_failures.append("One or more batch row-count reconciliations differ")

    report = {
        "schema_version": 1,
        "status": "promoted_to_staging" if not control_failures else "failed_reconciliation",
        "promoted_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "environment": settings.environment,
        "batch_prefix": args.batch_prefix,
        "actors": {
            "submitter": submitter["display_name"],
            "approver": approver["display_name"],
            "poster": poster["display_name"],
            "technical_staging_only": True,
            "production_approval": False,
        },
        "promoted_batches": promoted,
        "database_batches": final_batches,
        "business_counts_before": before,
        "business_counts_after": after,
        "business_count_deltas": deltas,
        "control_failures": control_failures,
        "source_mutation": False,
        "preserved_clone_mutation": False,
        "opening_stock_posted": False,
        "opening_balances_posted": False,
        "historical_transactions_posted": False,
        "production_authorized": False,
        "later_delta_required": True,
        "qualification": "Masters were promoted only into local ERP staging. This is not business UAT or production approval.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"], "promoted_batches": promoted,
        "business_count_deltas": deltas, "control_failures": control_failures,
        "production_authorized": False, "output": str(output),
    }, indent=2))
    if control_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
