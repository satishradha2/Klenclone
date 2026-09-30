"""Explicit operational schema contract for PostgreSQL deployment.

Legacy revisions through 0061 are installed by the existing initializer. The
0067 contract is stamped only by the operator-run migration command, never by
the production web process. Subsequent schema changes require a new revision.
"""

from __future__ import annotations

import hashlib
import json
from importlib import import_module

from sqlalchemy import inspect, text

from .operational import OperationalBase, initialize_operational_database


OPERATIONAL_SCHEMA_HEAD = "0067"
LEGACY_SCHEMA_HEAD = "0061"

_MODEL_MODULES = (
    "data_governance", "data_reviews", "delivery_fulfillment", "enterprise_setup",
    "access_control", "finance_foundation", "finance_ledger", "finance_reconciliation",
    "goods_receipts", "hrm", "hrm_operations", "pos_counter", "van_sales", "crm",
    "commercial_pricing", "inventory_operations", "operational_masters", "payments",
    "cash_management", "expense_management", "fixed_assets", "vat_control",
    "period_close", "close_reporting", "audit_compliance", "cutover_rehearsal",
    "procurement", "procurement_matching", "posting_integration", "purchase_returns",
    "customer_invoices", "credit_management", "sales_invoices", "sales_orders",
    "sales_returns", "customer_price_credits", "customer_refunds", "security_runtime", "source_verification", "warehouse_controls",
    "product_creation", "product_taxonomy", "lot_traceability", "party_creation",
    "fx_controls", "quote_trade_controls", "cross_border_order_controls",
    "cross_border_delivery_readiness", "cross_border_dispatch_release",
    "cross_border_invoice_tax",
)


def _model_contract() -> tuple[list[dict], str]:
    for module_name in _MODEL_MODULES:
        import_module(f".{module_name}", __package__)
    contract = [
        {
            "table": table.name,
            "columns": [
                (column.name, str(column.type), column.nullable, column.primary_key)
                for column in table.columns
            ],
        }
        for table in sorted(OperationalBase.metadata.tables.values(), key=lambda item: item.name)
    ]
    checksum = hashlib.sha256(json.dumps(contract, sort_keys=True).encode("utf-8")).hexdigest()
    return contract, checksum


def _inspect_contract(engine) -> str:
    contract, checksum = _model_contract()
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    missing_tables = [item["table"] for item in contract if item["table"] not in existing_tables]
    if missing_tables:
        raise RuntimeError(f"Operational schema is missing tables: {', '.join(missing_tables[:8])}")
    for item in contract:
        existing_columns = {column["name"]: column for column in inspector.get_columns(item["table"])}
        missing_columns = [column[0] for column in item["columns"] if column[0] not in existing_columns]
        if missing_columns:
            raise RuntimeError(
                f"Operational schema {item['table']} is missing columns: {', '.join(missing_columns)}"
            )
        for expected in OperationalBase.metadata.tables[item["table"]].columns:
            actual = existing_columns[expected.name]
            expected_type = str(expected.type.compile(dialect=engine.dialect)).upper()
            actual_type = str(actual["type"].compile(dialect=engine.dialect)).upper()
            if expected_type != actual_type:
                raise RuntimeError(
                    f"Operational schema type mismatch at {item['table']}.{expected.name}: "
                    f"expected {expected_type}, found {actual_type}"
                )
            if not expected.primary_key and expected.nullable != actual["nullable"]:
                raise RuntimeError(
                    f"Operational schema nullability mismatch at {item['table']}.{expected.name}"
                )
    if engine.dialect.name == "postgresql":
        required_checks = {
            "operational_customer_invoices": {
                "ck_customer_invoice_status": ("posted", "reversed"),
            },
            "operational_integrated_posting_batches": {
                "ck_integrated_posting_resource_type": ("customer_invoice", "customer_price_credit", "customer_refund_recovery"),
            },
            "operational_customer_refunds": {
                "ck_customer_refund_one_credit_source": ("sales_return_id", "price_credit_id"),
            },
            "operational_delivery_stock_movements": {
                "ck_delivery_stock_valuation_pair": ("unit_cost_snapshot", "issue_value_snapshot"),
            },
        }
        for table_name, checks in required_checks.items():
            actual_checks = {row["name"]: str(row.get("sqltext") or "").lower()
                             for row in inspector.get_check_constraints(table_name)}
            for name, required_terms in checks.items():
                expression = actual_checks.get(name, "")
                if not all(term in expression for term in required_terms):
                    raise RuntimeError(f"Operational schema check constraint mismatch at {table_name}.{name}")
    return checksum


def migrate_operational_database(engine) -> dict:
    """Run legacy upgrades explicitly and stamp the checked 0067 contract."""
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Explicit operational migration requires PostgreSQL")
    if inspect(engine).has_table("operational_schema_migrations"):
        with engine.connect() as connection:
            applied = connection.execute(text(
                "SELECT checksum FROM operational_schema_migrations WHERE version = :version"
            ), {"version": OPERATIONAL_SCHEMA_HEAD}).scalar_one_or_none()
        if applied is not None:
            return verify_operational_database(engine)
    initialize_operational_database(engine)
    checksum = _inspect_contract(engine)
    with engine.begin() as connection:
        legacy = connection.execute(text(
            "SELECT checksum FROM operational_schema_migrations WHERE version = :version"
        ), {"version": LEGACY_SCHEMA_HEAD}).scalar_one_or_none()
        if legacy is None:
            raise RuntimeError("Legacy operational schema revision 0061 is missing")
        connection.execute(text(
            "INSERT INTO operational_schema_migrations(version, checksum, applied_at) "
            "VALUES (:version, :checksum, CURRENT_TIMESTAMP)"
        ), {"version": OPERATIONAL_SCHEMA_HEAD, "checksum": checksum})
    return {"status": "ready", "version": OPERATIONAL_SCHEMA_HEAD, "checksum": checksum}


def verify_operational_database(engine) -> dict:
    """Read-only production preflight; never creates or alters tables."""
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Production operational storage must be PostgreSQL")
    checksum = _inspect_contract(engine)
    with engine.connect() as connection:
        applied = connection.execute(text(
            "SELECT checksum FROM operational_schema_migrations WHERE version = :version"
        ), {"version": OPERATIONAL_SCHEMA_HEAD}).scalar_one_or_none()
    if applied != checksum:
        raise RuntimeError(
            "Operational schema is not at the approved revision 0067; "
            "run the explicit migration before starting production"
        )
    return {"status": "ready", "version": OPERATIONAL_SCHEMA_HEAD, "checksum": checksum}
