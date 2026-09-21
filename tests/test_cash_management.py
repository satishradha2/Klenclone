from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from klen_clone.cash_management import (
    OperationalReconciliationRehearsal, OperationalStatementLine,
    cash_management_payload, create_cash_account, create_statement_batch,
    decide_cash_account, explain_statement_line, match_statement_line,
    rehearse_reconciliation, transition_statement_batch,
)
from klen_clone.operational import initialize_operational_database, make_operational_engine
from klen_clone.payments import create_payment, transition_payment


def cash_session(tmp_path):
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'cash-management.db'}")
    initialize_operational_database(engine)
    return Session(engine)


def approved_account(session):
    account = create_cash_account(session, account_code="Bank - AED",
        account_name="Primary AED current account", account_type="bank",
        bank_name="Test Bank", identifier="AE000000000000000001234",
        gl_account_code="Bank - AED", location_code="MAIN",
        reason="Controlled test account", actor="maker")
    with pytest.raises(PermissionError, match="Maker-checker"):
        decide_cash_account(session, account, action="approve", expected_revision=1,
                            actor="maker", note="Self approval attempt")
    session.rollback()
    return decide_cash_account(session, account, action="approve", expected_revision=1,
                               actor="approver", note="Independent account approval")


def approved_receipt(session, *, amount="100", reference="BANK-100"):
    payment = create_payment(session, actor="receipt-maker", payment_type="customer_receipt",
        party_code="CUS-1", party_name_snapshot="Customer One", location_code="MAIN",
        payment_date=date(2026, 9, 19), payment_method="bank_transfer",
        cash_bank_account_code="Bank - AED", reference_no=reference,
        amount=Decimal(amount), notes=None, lines=[])
    payment = transition_payment(session, payment, expected_revision=1,
                                 action="submit", actor="receipt-maker")
    return transition_payment(session, payment, expected_revision=2,
                              action="approve", actor="receipt-approver")


def statement_lines():
    return [
        {"external_id": "ST-1", "transaction_date": date(2026, 9, 19),
         "value_date": date(2026, 9, 19), "reference": "BANK-100",
         "description": "Customer receipt", "debit_amount": Decimal("0"),
         "credit_amount": Decimal("100")},
        {"external_id": "ST-2", "transaction_date": date(2026, 9, 19),
         "value_date": date(2026, 9, 19), "reference": "FEE-1",
         "description": "Monthly bank fee", "debit_amount": Decimal("10"),
         "credit_amount": Decimal("0")},
    ]


def test_bank_statement_matching_exception_approval_and_rehearsal(tmp_path):
    session = cash_session(tmp_path)
    account = approved_account(session)
    assert account.status == "active" and account.identifier_last4 == "1234"
    payment = approved_receipt(session)
    batch = create_statement_batch(session, account=account,
        statement_reference="SEP-2026", statement_start=date(2026, 9, 1),
        statement_end=date(2026, 9, 30), opening_balance=Decimal("1000"),
        closing_balance=Decimal("1090"), source_file_name="sep-2026.csv",
        actor="maker", lines=statement_lines())
    assert batch.lines[0].suggested_payment_id == payment.id
    assert batch.source_checksum and batch.status == "draft"
    match_statement_line(session, batch, batch.lines[0], payment, actor="maker")
    explain_statement_line(session, batch, batch.lines[1], category="bank_fee",
                           reason="Monthly fee needs controlled expense journal", actor="maker")
    batch = transition_statement_batch(session, batch, action="submit",
        expected_revision=1, actor="maker")
    with pytest.raises(PermissionError, match="Maker-checker"):
        transition_statement_batch(session, batch, action="approve",
            expected_revision=2, actor="maker", note="Self approval attempt")
    session.rollback()
    batch = transition_statement_batch(session, batch, action="approve",
        expected_revision=2, actor="approver", note="Statement independently reviewed")
    plan = rehearse_reconciliation(session, batch, actor="approver")
    assert plan["posting_enabled"] is False and plan["posting_performed"] is False
    assert plan["matched_lines"] == 1 and plan["exception_lines"] == 1
    assert len(plan["adjustment_journal"]) == 2
    assert {line["account"] for line in plan["adjustment_journal"]} == {"Bank Charges", "Bank - AED"}
    assert rehearse_reconciliation(session, batch, actor="approver")["idempotent_replay"] is True
    assert session.scalar(select(func.count(OperationalReconciliationRehearsal.id))) == 1
    controls = cash_management_payload(session)["controls"]
    assert controls["active_accounts"] == 1
    assert controls["unmatched_lines"] == 0
    assert controls["approved_reconciliations"] == 1


def test_unbalanced_and_unresolved_statements_are_blocked(tmp_path):
    session = cash_session(tmp_path)
    account = approved_account(session)
    with pytest.raises(ValueError, match="does not equal closing"):
        create_statement_batch(session, account=account,
            statement_reference="BAD", statement_start=date(2026, 9, 1),
            statement_end=date(2026, 9, 30), opening_balance=Decimal("1000"),
            closing_balance=Decimal("999"), source_file_name="bad.csv",
            actor="maker", lines=statement_lines())
    session.rollback()
    batch = create_statement_batch(session, account=account,
        statement_reference="OPEN", statement_start=date(2026, 9, 1),
        statement_end=date(2026, 9, 30), opening_balance=Decimal("1000"),
        closing_balance=Decimal("1090"), source_file_name="open.csv",
        actor="maker", lines=statement_lines())
    with pytest.raises(ValueError, match="matched or explained"):
        transition_statement_batch(session, batch, action="submit",
            expected_revision=1, actor="maker")


def test_payment_cannot_be_matched_twice(tmp_path):
    session = cash_session(tmp_path)
    account = approved_account(session)
    payment = approved_receipt(session)
    first = create_statement_batch(session, account=account,
        statement_reference="FIRST", statement_start=date(2026, 9, 19),
        statement_end=date(2026, 9, 19), opening_balance=Decimal("0"),
        closing_balance=Decimal("100"), source_file_name="first.csv", actor="maker",
        lines=[statement_lines()[0]])
    match_statement_line(session, first, first.lines[0], payment, actor="maker")
    second_line = statement_lines()[0] | {"external_id": "ST-SECOND"}
    second = create_statement_batch(session, account=account,
        statement_reference="SECOND", statement_start=date(2026, 9, 19),
        statement_end=date(2026, 9, 19), opening_balance=Decimal("0"),
        closing_balance=Decimal("100"), source_file_name="second.csv", actor="maker",
        lines=[second_line])
    with pytest.raises(ValueError, match="already matched"):
        match_statement_line(session, second, second.lines[0], payment, actor="maker")
