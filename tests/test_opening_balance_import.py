import json
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from klen_clone.opening_balance_import import import_opening_balances
from klen_clone.operational import (
    OperationalFinancialMigrationException,
    OperationalOpeningBalanceBatch,
    OperationalOpeningPartyBalance,
    initialize_operational_database,
    make_operational_engine,
)


CAPTURE = Path("source_exports/2026-09-09-reconciliation-20260909T101320Z")
STATUS = Path("var/erp_reconciliation_refreshes/20260909T101320Z/package/PACKAGE_STATUS.json")


def test_imports_checksum_bound_nonposting_opening_balances_idempotently():
    engine = make_operational_engine("sqlite:///:memory:")
    initialize_operational_database(engine)
    with Session(engine) as session:
        report = import_opening_balances(
            session, capture=CAPTURE, package_status=STATUS,
            actor="test-admin", approval_reference="test-approved")
        assert report["status"] == "imported_nonposting"
        assert report["receivables"] == {"rows": 196, "amount": Decimal("62680.16")}
        assert report["customer_advances"] == {"rows": 9, "amount": Decimal("681.86")}
        assert report["payables"] == {"rows": 53, "amount": Decimal("31665.00")}
        assert report["supplier_advances"] == {"rows": 6, "amount": Decimal("133.04")}
        assert {item["variance"] for item in report["exceptions"]} == {
            Decimal("-1892.21"), Decimal("-451.75"), Decimal("-754.71")}
        assert session.scalar(select(func.count(OperationalOpeningBalanceBatch.id))) == 1
        assert session.scalar(select(func.count(OperationalOpeningPartyBalance.id))) == 264
        assert session.scalar(select(func.count(OperationalOpeningPartyBalance.id)).where(
            OperationalOpeningPartyBalance.posting_enabled.is_(True))) == 0
        assert session.scalar(select(func.count(OperationalFinancialMigrationException.id))) == 3
        assert session.scalar(select(func.count(OperationalFinancialMigrationException.id)).where(
            OperationalFinancialMigrationException.status == "open")) == 3

        repeat = import_opening_balances(
            session, capture=CAPTURE, package_status=STATUS,
            actor="test-admin", approval_reference="test-approved")
        assert repeat["status"] == "already_imported"
        assert session.scalar(select(func.count(OperationalOpeningPartyBalance.id))) == 264
