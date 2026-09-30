from __future__ import annotations

import os

import pytest
from sqlalchemy import inspect, text

from klen_clone.operational import make_operational_engine
from klen_clone.operational_migrations import (
    OPERATIONAL_SCHEMA_HEAD, migrate_operational_database, verify_operational_database,
)


pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif("KLEN_TEST_OPERATIONAL_MIGRATION_DATABASE_URL" not in os.environ,
                       reason="requires a fresh, isolated operational PostgreSQL database"),
]


def test_explicit_operational_migration_is_idempotent_and_runtime_preflight_is_read_only():
    engine = make_operational_engine(os.environ["KLEN_TEST_OPERATIONAL_MIGRATION_DATABASE_URL"])
    assert engine.dialect.name == "postgresql"
    assert "klen_operational_migration_" in engine.url.database
    assert inspect(engine).get_table_names() == []
    with pytest.raises(RuntimeError, match="missing tables"):
        verify_operational_database(engine)

    first = migrate_operational_database(engine)
    second = migrate_operational_database(engine)
    checked = verify_operational_database(engine)
    assert first == second == checked
    assert first["version"] == OPERATIONAL_SCHEMA_HEAD
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT count(*) FROM operational_schema_migrations WHERE version = :version"
        ), {"version": OPERATIONAL_SCHEMA_HEAD}).scalar_one() == 1
        assert connection.execute(text("SELECT count(*) FROM operational_journal_batches")).scalar_one() == 0

    # A revision stamp alone must not conceal physical schema drift.
    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE operational_fx_rates ALTER COLUMN currency_code TYPE VARCHAR(4)"
        ))
    try:
        with pytest.raises(RuntimeError, match="type mismatch at operational_fx_rates.currency_code"):
            verify_operational_database(engine)
    finally:
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE operational_fx_rates ALTER COLUMN currency_code TYPE VARCHAR(3)"
            ))
    assert verify_operational_database(engine) == checked

    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE operational_integrated_posting_batches "
            "DROP CONSTRAINT ck_integrated_posting_resource_type"
        ))
    try:
        with pytest.raises(RuntimeError, match="check constraint mismatch at operational_integrated_posting_batches"):
            verify_operational_database(engine)
    finally:
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE operational_integrated_posting_batches "
                "ADD CONSTRAINT ck_integrated_posting_resource_type CHECK "
                "(resource_type IN ('inventory_document','goods_receipt','sales_invoice','customer_invoice',"
                "'sales_return','customer_price_credit','customer_refund','customer_refund_recovery',"
                "'purchase_return','payment','supplier_invoice','supplier_adjustment'))"
            ))
    assert verify_operational_database(engine) == checked
