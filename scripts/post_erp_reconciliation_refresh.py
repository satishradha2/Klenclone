from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.api.data_migration import audit, post_opening_gl, post_row
from app.config import get_settings


EXPECTED_KINDS = [
    "opening_receivables",
    "opening_payables",
    "opening_gl",
    "opening_stock",
    "opening_stock_adjustments",
]


def actor(db, name: str, permission: str) -> dict:
    row = db.execute(
        """SELECT DISTINCT u.id,u.display_name FROM app_users u
           JOIN user_roles ur ON ur.user_id=u.id JOIN role_permissions rp ON rp.role_id=ur.role_id
           JOIN permissions p ON p.id=rp.permission_id
           WHERE u.active AND u.display_name=%s AND p.code IN (%s,'*')""",
        (name, permission),
    ).fetchone()
    if not row:
        raise RuntimeError(f"Missing staging actor: {name}")
    return {"id": str(row["id"]), "display_name": row["display_name"]}


def counts(db) -> dict[str, int]:
    names = (
        "stock_movements",
        "inventory_balances",
        "migration_inventory_exceptions",
        "customer_invoices",
        "supplier_invoices",
        "journal_entries",
        "journal_lines",
    )
    return {name: db.execute(f"SELECT count(*) count FROM {name}").fetchone()["count"] for name in names}


def inventory_total(db) -> Decimal:
    return db.execute("SELECT COALESCE(sum(qty_on_hand_base),0) total FROM inventory_balances").fetchone()["total"]


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
        raise RuntimeError("Operational refresh posting is forbidden in production")

    with psycopg.connect(settings.database_url, row_factory=dict_row) as db:
        submitter = actor(db, "System Administrator", "migration.manage")
        approver = actor(db, "Export UAT Checker", "migration.approve")
        poster = actor(db, "System Administrator", "migration.approve")
        if submitter["id"] == approver["id"] or approver["id"] == poster["id"]:
            raise RuntimeError("Staging maker-checker separation is not satisfied")

        batches = db.execute(
            """SELECT * FROM data_import_batches WHERE batch_no LIKE %s AND import_type<>'products'
               ORDER BY batch_no""",
            (args.batch_prefix + "-%",),
        ).fetchall()
        if [row["import_type"] for row in batches] != EXPECTED_KINDS:
            raise RuntimeError("Expected exactly five operational opening batches")
        if any(row["status"] != "validated" or row["error_rows"] or row["duplicate_rows"] for row in batches):
            raise RuntimeError("Every operational opening batch must be cleanly validated and unposted")

        before = counts(db)
        inventory_before = inventory_total(db)
        posted = []

        for batch in batches:
            db.execute(
                "UPDATE data_import_batches SET status='submitted',submitted_by=%s,submitted_at=now() WHERE id=%s",
                (submitter["id"], batch["id"]),
            )
            audit(db, submitter, "submit_operational_staging_refresh", batch["id"], {"production_approval": False})
            db.execute(
                "UPDATE data_import_batches SET status='approved',approved_by=%s,approved_at=now() WHERE id=%s",
                (approver["id"], batch["id"]),
            )
            audit(db, approver, "approve_operational_staging_refresh", batch["id"], {"production_approval": False})
            rows = db.execute(
                "SELECT * FROM data_import_rows WHERE batch_id=%s AND validation_status='valid' ORDER BY row_no",
                (batch["id"],),
            ).fetchall()

            control = Decimal("0")
            if batch["import_type"] == "opening_gl":
                row_count, debit, credit = post_opening_gl(db, batch["id"], rows, poster)
                if debit != credit:
                    raise RuntimeError("Opening advance journals are not balanced")
                metric = "debit"
                source = Decimal(str(batch["source_totals"]["debit"]))
                control = debit
                posted_totals = {"row_count": row_count, "debit": str(debit), "credit": str(credit)}
            else:
                for row in rows:
                    table, target, value = post_row(db, batch["import_type"], row["normalized_data"], poster, batch["id"])
                    db.execute(
                        """UPDATE data_import_rows SET validation_status='posted',target_table=%s,
                           target_id=%s,posted_at=now() WHERE id=%s""",
                        (table, target, row["id"]),
                    )
                    control += value
                metric = "quantity" if batch["import_type"] in ("opening_stock", "opening_stock_adjustments") else "amount"
                source = Decimal(str(batch["source_totals"][metric]))
                posted_totals = {"row_count": len(rows), metric: str(control)}

            if control != source:
                raise RuntimeError(f"Posting control mismatch for {batch['batch_no']}: {control} != {source}")
            db.execute(
                """INSERT INTO data_import_reconciliations(batch_id,metric_code,source_value,posted_value)
                   VALUES(%s,%s,%s,%s)""",
                (batch["id"], metric, source, control),
            )
            db.execute(
                """UPDATE data_import_batches SET status='posted',posted_by=%s,posted_at=now(),
                   posted_totals=%s WHERE id=%s""",
                (poster["id"], Jsonb(posted_totals), batch["id"]),
            )
            audit(
                db,
                poster,
                "post_operational_staging_refresh",
                batch["id"],
                {"metric": metric, "control": str(control), "production_approval": False},
            )
            posted.append(
                {
                    "batch_no": batch["batch_no"],
                    "kind": batch["import_type"],
                    "rows": len(rows),
                    "metric": metric,
                    "source": str(source),
                    "posted": str(control),
                    "difference": str(control - source),
                }
            )

        after = counts(db)
        inventory_after = inventory_total(db)
        exception_quantity = db.execute(
            """SELECT COALESCE(sum(e.source_quantity_base),0) total FROM migration_inventory_exceptions e
               JOIN data_import_batches b ON b.id=e.batch_id WHERE b.batch_no LIKE %s""",
            (args.batch_prefix + "-%",),
        ).fetchone()["total"]
        inventory_delta = inventory_after - inventory_before
        if inventory_delta != Decimal("29137.02"):
            raise RuntimeError(f"Positive inventory delta mismatch: {inventory_delta}")
        if exception_quantity != Decimal("-13.00"):
            raise RuntimeError(f"Quarantined negative quantity mismatch: {exception_quantity}")
        if inventory_delta + exception_quantity != Decimal("29124.02"):
            raise RuntimeError("Net stock does not reconcile to the sealed source control")

        db.commit()
        final_batches = db.execute(
            """SELECT batch_no,import_type,status,total_rows,valid_rows,error_rows,duplicate_rows,
               source_totals,posted_totals FROM data_import_batches WHERE batch_no LIKE %s ORDER BY batch_no""",
            (args.batch_prefix + "-%",),
        ).fetchall()

    report = {
        "schema_version": 1,
        "status": "posted_and_reconciled_operational_staging",
        "completed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "database": "operational_staging",
        "batch_prefix": args.batch_prefix,
        "posted_reconciliation": posted,
        "inventory_quantity_before": str(inventory_before),
        "inventory_quantity_after": str(inventory_after),
        "inventory_posted_delta": str(inventory_delta),
        "quarantined_negative_quantity": str(exception_quantity),
        "source_net_quantity": str(inventory_delta + exception_quantity),
        "counts_before": before,
        "counts_after": after,
        "batch_states": final_batches,
        "source_mutation": False,
        "production_mutation": False,
        "production_approval": False,
        "qualification": "The sealed opening package is posted only in operational staging and reconciles to its source controls.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
