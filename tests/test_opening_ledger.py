from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from klen_clone.finance_foundation import (initialize_finance_foundation,
    request_finance_approval, decide_finance_approval)
from klen_clone.opening_ledger import (OperationalOpeningLedgerPackage, create_opening_package,
    opening_package_payload, opening_reconciliation, transition_opening_package)
from klen_clone.operational import initialize_operational_database, make_operational_engine


def session_with_chart():
    engine = make_operational_engine("sqlite:///:memory:")
    initialize_operational_database(engine)
    session = Session(engine)
    initialize_finance_foundation(session)
    for code in ("1100", "1200", "1210", "1300", "2100", "2140", "3100"):
        request_finance_approval(session, actor="chart-maker", resource_type="chart_account",
            resource_key=code, note="Synthetic opening fixture")
        decide_finance_approval(session, actor="chart-checker", resource_type="chart_account",
            resource_key=code, action="approve", expected_revision=1,
            note="Synthetic opening fixture")
    return session


LINES = [
    {"account_code": "1100", "debit": "50", "credit": "0"},
    {"account_code": "1200", "debit": "100", "credit": "0"},
    {"account_code": "1210", "debit": "10", "credit": "0"},
    {"account_code": "1300", "debit": "40", "credit": "0"},
    {"account_code": "2100", "debit": "0", "credit": "80"},
    {"account_code": "2140", "debit": "0", "credit": "20"},
    {"account_code": "3100", "debit": "0", "credit": "100"},
]
PARTIES = [
    {"balance_type": "receivable", "party_code": "C1", "amount": "60"},
    {"balance_type": "receivable", "party_code": "C2", "amount": "40"},
    {"balance_type": "payable", "party_code": "S1", "amount": "80"},
    {"balance_type": "supplier_advance", "party_code": "S2", "amount": "10"},
    {"balance_type": "customer_advance", "party_code": "C3", "amount": "20"},
]


def create(session):
    return create_opening_package(session, actor="maker", cutoff_date=date(2026, 9, 30),
        source_reference="SYNTHETIC-ONLY", source_sha256="a" * 64, source_atomic=False,
        lines=LINES, party_balances=PARTIES, stock_value=Decimal("40.00"),
        stock_evidence_reference="SYNTHETIC-STOCK-VALUATION")


def test_opening_package_balanced_tied_frozen_and_nonposting():
    session = session_with_chart()
    row = create(session)
    assert row.status == "draft" and row.posting_enabled is False
    payload = opening_package_payload(row)
    assert payload["evidence"]["debit_total"] == "200.00"
    assert all(Decimal(item["difference"]) == 0 for item in payload["evidence"]["tie_outs"])
    assert payload["opening_balances_certified"] is False
    with pytest.raises(RuntimeError, match="already have a package"):
        create(session)
    transition_opening_package(session, key=row.package_key, action="submit", actor="maker",
        expected_revision=1, note="Ready for independent rehearsal review")
    with pytest.raises(PermissionError, match="maker"):
        transition_opening_package(session, key=row.package_key, action="approve", actor="MAKER",
            expected_revision=2, note="I cannot approve my package")
    with pytest.raises(RuntimeError, match="revision conflict"):
        transition_opening_package(session, key=row.package_key, action="approve", actor="checker",
            expected_revision=1, note="Independent review")
    approved = transition_opening_package(session, key=row.package_key, action="approve", actor="checker",
        expected_revision=2, note="Synthetic controls reconcile; source truth not certified")
    assert approved.status == "approved_rehearsal" and approved.posting_enabled is False
    assert session.scalar(select(OperationalOpeningLedgerPackage)).evidence_fingerprint == row.evidence_fingerprint


def test_opening_package_rejects_unbalanced_duplicate_and_control_mismatch():
    session = session_with_chart()
    args = dict(party_balances=PARTIES, stock_value="40", stock_evidence_reference="SYNTHETIC-STOCK")
    with pytest.raises(ValueError, match="not balanced"):
        opening_reconciliation(session, lines=[*LINES[:-1], {**LINES[-1], "credit": "99"}], **args)
    with pytest.raises(ValueError, match="Duplicate opening account"):
        opening_reconciliation(session, lines=[*LINES, LINES[0]], **args)
    with pytest.raises(ValueError, match="control mismatch"):
        opening_reconciliation(session, lines=LINES, party_balances=PARTIES[:-1],
            stock_value="40", stock_evidence_reference="SYNTHETIC-STOCK")
    with pytest.raises(ValueError, match="Duplicate opening party"):
        opening_reconciliation(session, lines=LINES, party_balances=[*PARTIES, PARTIES[0]],
            stock_value="40", stock_evidence_reference="SYNTHETIC-STOCK")
    with pytest.raises(ValueError, match="finite"):
        opening_reconciliation(session, lines=LINES, party_balances=PARTIES,
            stock_value="NaN", stock_evidence_reference="SYNTHETIC-STOCK")


def test_opening_package_requires_approved_chart_and_detects_changed_evidence():
    session = session_with_chart()
    from klen_clone.finance_foundation import OperationalChartAccount
    account = session.scalar(select(OperationalChartAccount).where(OperationalChartAccount.account_code == "1200"))
    account.status = "inactive"
    session.commit()
    with pytest.raises(ValueError, match="active postable"):
        create(session)
    account.status = "active"
    session.commit()
    row = create(session)
    transition_opening_package(session, key=row.package_key, action="submit", actor="maker",
        expected_revision=1, note="Synthetic")
    account.status = "inactive"
    session.commit()
    with pytest.raises(ValueError, match="active postable"):
        transition_opening_package(session, key=row.package_key, action="approve", actor="checker",
            expected_revision=2, note="Independent approval")
    account.status = "active"
    row.evidence_json = row.evidence_json.replace('"stock_value":"40.00"', '"stock_value":"41.00"')
    session.commit()
    with pytest.raises(ValueError, match="control mismatch"):
        transition_opening_package(session, key=row.package_key, action="approve", actor="checker",
            expected_revision=2, note="Independent approval")
