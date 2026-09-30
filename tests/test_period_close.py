from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from klen_clone.operational import OperationalFiscalPeriod, initialize_operational_database, make_operational_engine
from klen_clone.period_close import (
    create_close_adjustment, create_period_close, decide_close_adjustment,
    period_close_payload, rehearse_period_close, transition_period_close,
)
from klen_clone.posting_integration import OperationalIntegratedJournalLine, OperationalIntegratedPostingBatch


def session_value():
    engine = make_operational_engine("sqlite:///:memory:")
    initialize_operational_database(engine)
    session = Session(engine)
    session.add(OperationalFiscalPeriod(period_key="2026-09", starts_on=date(2026, 9, 1),
        ends_on=date(2026, 9, 30), status="open", rehearsal_enabled=True,
        approval_reference="close test", configured_by="controller"))
    session.commit()
    return session


def test_period_close_maker_checker_and_balanced_rehearsal():
    session = session_value()
    close = create_period_close(session, fiscal_period_key="2026-09", actor="maker")
    adjustment = create_close_adjustment(session, close, adjustment_type="accrual",
        adjustment_date=date(2026, 9, 30), debit_account="Utilities expense",
        credit_account="Accrued liabilities", amount="125.50", reversal_on=date(2026, 10, 1),
        evidence_reference="UAT-ACCRUAL-1", reason="September utility accrual", actor="maker")
    with pytest.raises(PermissionError):
        decide_close_adjustment(session, adjustment, action="approve", expected_revision=1,
            note="Self approval", actor="maker")
    session.rollback()
    decide_close_adjustment(session, adjustment, action="approve", expected_revision=1,
        note="Independent adjustment approval", actor="checker")
    submitted = transition_period_close(session, close, action="submit", expected_revision=1,
        actor="maker", note="VAT warning accepted for isolated close test")
    assert submitted.status == "submitted" and submitted.source_fingerprint
    with pytest.raises(PermissionError):
        transition_period_close(session, close, action="approve", expected_revision=2,
            actor="maker", note="Self approval blocked")
    session.rollback()
    transition_period_close(session, close, action="approve", expected_revision=2,
        actor="checker", note="Independent close approval")
    result = rehearse_period_close(session, close, actor="checker")
    assert result["debit_total"] == Decimal("125.50")
    assert result["credit_total"] == Decimal("125.50")
    assert result["posting_performed"] is False
    assert result["period_lock_performed"] is False
    assert close.fiscal_period.status == "open"
    assert rehearse_period_close(session, close, actor="checker")["idempotent_replay"] is True


def test_close_submission_blocks_pending_adjustment_and_requires_warning_note():
    session = session_value()
    close = create_period_close(session, fiscal_period_key="2026-09", actor="maker")
    create_close_adjustment(session, close, adjustment_type="fx_revaluation",
        adjustment_date=date(2026, 9, 30), debit_account="FX loss", credit_account="Trade payables",
        amount="10", reversal_on=None, evidence_reference="FX-RATE-1",
        reason="Closing exchange rate", actor="maker")
    with pytest.raises(ValueError, match="Blocking"):
        transition_period_close(session, close, action="submit", expected_revision=1, actor="maker")
    session.rollback()
    adjustment = close.adjustments[0]
    decide_close_adjustment(session, adjustment, action="reject", expected_revision=1,
        note="Unsupported exchange evidence", actor="checker")
    with pytest.raises(ValueError, match="exception note"):
        transition_period_close(session, close, action="submit", expected_revision=1, actor="maker")
    session.rollback()
    payload = period_close_payload(session, close)
    assert any(item["control"] == "vat_return_approved" and item["status"] == "warning"
               for item in payload["checklist"])


def test_close_blocks_unbalanced_integrated_journal_in_its_fiscal_period():
    session = session_value()
    close = create_period_close(session, fiscal_period_key="2026-09", actor="maker")
    for index, period_key in enumerate(("2026-09", "2026-10"), start=1):
        batch = OperationalIntegratedPostingBatch(
            batch_key=f"test-batch-{index}", idempotency_key=f"close-test-{index}",
            resource_type="customer_refund_recovery", resource_key=f"test-recovery-{index}",
            resource_revision=2, posting_sequence=1, batch_kind="posting",
            posting_fingerprint=f"test-fingerprint-{index}", fiscal_period_key=period_key,
            status="posted", posted_by="test")
        session.add(batch)
        session.flush()
        session.add(OperationalIntegratedJournalLine(batch_id=batch.id, line_no=1,
            account_code="1110", debit=Decimal("2.00"), credit=Decimal("0.00")))
    session.commit()
    payload = period_close_payload(session, close)
    assert payload["snapshot"]["integrated_journal_batches"] == 1
    assert payload["snapshot"]["permanent_journal_batches"] == 1
    balance = next(item for item in payload["checklist"] if item["control"] == "permanent_journal_balance")
    assert balance["status"] == "block" and "AED 2.00" in balance["detail"]
    with pytest.raises(ValueError, match="Blocking close controls"):
        transition_period_close(session, close, action="submit", expected_revision=1,
            actor="maker", note="Isolated integrated journal test")
