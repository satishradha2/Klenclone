from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from klen_clone.cash_management import create_cash_account, decide_cash_account
from klen_clone.finance_foundation import (initialize_finance_foundation,
    request_finance_approval, decide_finance_approval)
from klen_clone.gl_mapping import posting_gl_preflight, require_posting_gl
from klen_clone.operational import OperationalFiscalPeriod, initialize_operational_database, make_operational_engine
from klen_clone.payments import create_payment, rehearse_payment_posting, transition_payment
from klen_clone.posting_integration import (OperationalIntegratedJournalLine,
    OperationalIntegratedPostingBatch, execute_integrated_posting)


def controlled_session():
    engine = make_operational_engine("sqlite:///:memory:")
    initialize_operational_database(engine)
    session = Session(engine)
    initialize_finance_foundation(session)
    session.add(OperationalFiscalPeriod(period_key="2026-09", starts_on=date(2026, 9, 1),
        ends_on=date(2026, 9, 30), status="open", rehearsal_enabled=True,
        approval_reference="synthetic GL mapping", configured_by="controller"))
    session.commit()
    return session


def approve_chart(session, *codes):
    for code in codes:
        request_finance_approval(session, actor="chart-maker", resource_type="chart_account",
            resource_key=code, note="Synthetic GL mapping approval")
        decide_finance_approval(session, actor="chart-checker", resource_type="chart_account",
            resource_key=code, action="approve", expected_revision=1,
            note="Independently approved for synthetic posting")


def test_gl_preflight_requires_active_chart_and_approved_bank_master():
    session = controlled_session()
    journal = [{"account": "DUMMY-BANK", "debit": Decimal("10"), "credit": Decimal("0")},
               {"account": "Accounts Receivable", "debit": Decimal("0"), "credit": Decimal("9")},
               {"account": "Customer Advances", "debit": Decimal("0"), "credit": Decimal("1")}]
    before = posting_gl_preflight(session, journal)
    assert before["ready"] is False and before["issues"]
    approve_chart(session, "1110", "1200", "2140", "1300", "2115", "5120", "4020")
    account = create_cash_account(session, account_code="DUMMY-BANK", account_name="Synthetic bank",
        account_type="bank", bank_name="Test", identifier=None, gl_account_code="1110",
        location_code="MAIN", reason="Synthetic GL mapping test", actor="bank-maker")
    decide_cash_account(session, account, action="approve", expected_revision=1,
        actor="bank-checker", note="Independent bank approval")
    result = require_posting_gl(session, journal)
    assert result["ready"] is True
    assert [line["account"] for line in result["journal"]] == ["1110", "1200", "2140"]
    assert len(result["aliases"]) == 3
    goods = require_posting_gl(session, [
        {"account": "Inventory", "debit": 8, "credit": 0},
        {"account": "GRNI", "debit": 0, "credit": 8}])
    assert [line["account"] for line in goods["journal"]] == ["1300", "2115"]
    gain = require_posting_gl(session, [
        {"account": "Inventory", "debit": 4, "credit": 0},
        {"account": "Inventory Adjustment", "debit": 0, "credit": 4}])
    assert gain["journal"][1]["account"] == "4020"
    loss = require_posting_gl(session, [
        {"account": "Inventory Adjustment", "debit": 4, "credit": 0},
        {"account": "Inventory", "debit": 0, "credit": 4}])
    assert loss["journal"][0]["account"] == "5120"
    unknown = posting_gl_preflight(session, [{"account": "Unknown suspense", "debit": 1, "credit": 0},
        {"account": "1110", "debit": 0, "credit": 1}])
    assert unknown["ready"] is False and "Unknown suspense" in unknown["issues"][0]
    approve_chart(session, "6000")
    wrong_bank = create_cash_account(session, account_code="BAD-BANK", account_name="Wrong GL bank",
        account_type="bank", bank_name="Test", identifier=None, gl_account_code="6000",
        location_code="MAIN", reason="Negative GL mapping test", actor="bank-maker")
    decide_cash_account(session, wrong_bank, action="approve", expected_revision=1,
        actor="bank-checker", note="Bank master fixture for GL preflight")
    invalid_cash = posting_gl_preflight(session, [
        {"account": "BAD-BANK", "debit": 1, "credit": 0},
        {"account": "1200", "debit": 0, "credit": 1}])
    assert invalid_cash["ready"] is False
    assert "cash-equivalent asset" in invalid_cash["issues"][0]


def test_enforced_integrated_posting_persists_chart_codes_not_payment_labels():
    session = controlled_session()
    payment = create_payment(session, actor="receipt-maker", payment_type="customer_receipt",
        party_code="CUS-1", party_name_snapshot="Synthetic customer", location_code="MAIN",
        payment_date=date(2026, 9, 9), payment_method="bank_transfer",
        cash_bank_account_code="DUMMY-BANK", reference_no="SYNTHETIC-RECEIPT",
        amount=Decimal("10"), notes=None, lines=[{
            "source_type": "invoice", "source_reference_key": "INV-1",
            "source_document_date": date(2026, 9, 1),
            "source_outstanding_snapshot": Decimal("10"),
            "allocation_amount": Decimal("10")}])
    transition_payment(session, payment, expected_revision=1, action="submit", actor="receipt-maker")
    transition_payment(session, payment, expected_revision=2, action="approve", actor="receipt-checker")
    plan = rehearse_payment_posting(session, payment, actor="receipt-checker")
    with pytest.raises(ValueError, match="GL mapping gate"):
        execute_integrated_posting(session, resource_type="payment", resource_key=payment.payment_key,
            idempotency_key=plan["idempotency_key"], actor="receipt-checker",
            enforce_approved_gl=True)
    approve_chart(session, "1110", "1200")
    account = create_cash_account(session, account_code="DUMMY-BANK", account_name="Synthetic bank",
        account_type="bank", bank_name="Test", identifier=None, gl_account_code="1110",
        location_code="MAIN", reason="Synthetic GL mapping test", actor="bank-maker")
    decide_cash_account(session, account, action="approve", expected_revision=1,
        actor="bank-checker", note="Independent bank approval")
    posted = execute_integrated_posting(session, resource_type="payment", resource_key=payment.payment_key,
        idempotency_key=plan["idempotency_key"], actor="receipt-checker",
        enforce_approved_gl=True)
    batch = session.scalar(select(OperationalIntegratedPostingBatch).where(
        OperationalIntegratedPostingBatch.batch_key == posted["batch_key"]))
    lines = list(session.scalars(select(OperationalIntegratedJournalLine).where(
        OperationalIntegratedJournalLine.batch_id == batch.id).order_by(OperationalIntegratedJournalLine.line_no)))
    assert [(line.account_code, line.debit, line.credit) for line in lines] == [
        ("1110", Decimal("10.00"), Decimal("0.00")),
        ("1200", Decimal("0.00"), Decimal("10.00"))]
