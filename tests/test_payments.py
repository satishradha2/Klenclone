from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from klen_clone.operational import (OperationalAuditEvent, OperationalFiscalPeriod,
    OperationalOpeningBalanceBatch, OperationalOpeningPartyBalance,
    initialize_operational_database, make_operational_engine)
from klen_clone.payments import (
    OperationalPaymentAllocationClaim, OperationalPaymentPostingRehearsal,
    OperationalPaymentWorkflowEvent,
    create_payment, payment_control_counts, rehearse_payment_posting,
    replace_payment, transition_payment,
)


def payment_session(tmp_path):
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'payments.db'}")
    initialize_operational_database(engine)
    session = Session(engine)
    session.add(OperationalFiscalPeriod(period_key="2026-09", starts_on=date(2026, 9, 1),
        ends_on=date(2026, 9, 30), status="open", rehearsal_enabled=True,
        approval_reference="test", configured_by="controller"))
    session.commit()
    return session


def allocation(reference="INV-1", outstanding="100", amount="60", source_type="invoice"):
    return {"source_type": source_type, "source_reference_key": reference,
            "source_document_date": date(2026, 9, 1),
            "source_outstanding_snapshot": Decimal(outstanding),
            "allocation_amount": Decimal(amount)}


def create(session, *, payment_type="customer_receipt", amount="75", lines=None, actor="maker"):
    return create_payment(session, actor=actor, payment_type=payment_type,
        party_code="CUS-1" if payment_type == "customer_receipt" else "SUP-1",
        party_name_snapshot="Test Party", location_code="SHJ", payment_date=date(2026, 9, 9),
        payment_method="bank_transfer", cash_bank_account_code="Bank - AED",
        reference_no="BANK-1", amount=Decimal(amount), notes=None,
        lines=[allocation()] if lines is None else lines)


def test_customer_receipt_allocation_and_advance_rehearsal(tmp_path):
    session = payment_session(tmp_path)
    payment = create(session)
    assert payment.allocated_amount == Decimal("60.00")
    assert payment.unallocated_amount == Decimal("15.00")
    payment = transition_payment(session, payment, expected_revision=1, action="submit", actor="maker")
    with pytest.raises(PermissionError, match="Maker-checker"):
        transition_payment(session, payment, expected_revision=2, action="approve", actor="maker")
    session.rollback()
    payment = transition_payment(session, payment, expected_revision=2, action="approve", actor="approver")
    plan = rehearse_payment_posting(session, payment, actor="approver")
    assert plan["posting_enabled"] is False
    assert plan["debit"] == plan["credit"] == Decimal("75.00")
    assert {row["account"] for row in plan["journal"]} == {"Bank - AED", "Accounts Receivable", "Customer Advances"}
    assert len(plan["subledger"]) == 2
    replay = rehearse_payment_posting(session, payment, actor="approver")
    assert replay["idempotent_replay"] is True
    assert replay["posting_fingerprint"] == plan["posting_fingerprint"]
    assert session.scalar(select(func.count(OperationalPaymentPostingRehearsal.id))) == 1
    assert payment_control_counts(session) == {"payments": 1, "customer_receipts": 1,
        "supplier_payments": 0, "active_claims": 1, "rehearsals": 1, "posted": 0}
    assert session.scalar(select(func.count(OperationalPaymentWorkflowEvent.id))) == 2
    assert session.scalar(select(func.count(OperationalAuditEvent.id))) == 4


def test_supplier_payment_rehearsal_is_balanced(tmp_path):
    session = payment_session(tmp_path)
    payment = create(session, payment_type="supplier_payment", amount="100",
                     lines=[allocation("OB:10", "100", "100", "opening_balance")])
    payment = transition_payment(session, payment, expected_revision=1, action="submit", actor="maker")
    payment = transition_payment(session, payment, expected_revision=2, action="approve", actor="approver")
    plan = rehearse_payment_posting(session, payment, actor="approver")
    assert plan["debit"] == plan["credit"] == Decimal("100.00")
    assert plan["journal"] == [
        {"account": "Accounts Payable", "debit": Decimal("100.00"), "credit": Decimal("0")},
        {"account": "Bank - AED", "debit": Decimal("0"), "credit": Decimal("100.00")},
    ]


def test_cumulative_claim_prevents_overallocation_and_cancel_releases(tmp_path):
    session = payment_session(tmp_path)
    first = create(session, amount="70", lines=[allocation(outstanding="100", amount="70")])
    first = transition_payment(session, first, expected_revision=1, action="submit", actor="maker")
    second = create(session, amount="40", lines=[allocation(outstanding="100", amount="40")])
    with pytest.raises(ValueError, match="remaining outstanding"):
        transition_payment(session, second, expected_revision=1, action="submit", actor="maker")
    session.rollback()
    first = transition_payment(session, first, expected_revision=2, action="cancel", actor="maker")
    assert session.scalar(select(OperationalPaymentAllocationClaim)).status == "released"
    second = transition_payment(session, second, expected_revision=1, action="submit", actor="maker")
    assert second.status == "submitted"


def test_edit_validation_revision_and_locked_period(tmp_path):
    session = payment_session(tmp_path)
    with pytest.raises(ValueError, match="reference is required"):
        create_payment(session, actor="maker", payment_type="customer_receipt", party_code="CUS-1",
            party_name_snapshot="Customer", location_code="SHJ", payment_date=date(2026, 9, 9),
            payment_method="cheque", cash_bank_account_code="Bank", reference_no=None,
            amount=Decimal("10"), notes=None, lines=[])
    session.rollback()
    payment = create(session, amount="50", lines=[])
    payment = replace_payment(session, payment, expected_revision=1, actor="maker",
        payment_type="customer_receipt", party_code="CUS-1", party_name_snapshot="Test Party",
        location_code="SHJ", payment_date=date(2026, 9, 9), payment_method="cash",
        cash_bank_account_code="Cash", reference_no=None, amount=Decimal("25"), notes="advance", lines=[])
    assert payment.revision == 2 and payment.unallocated_amount == Decimal("25.00")
    with pytest.raises(ValueError, match="revision conflict"):
        replace_payment(session, payment, expected_revision=1, actor="maker",
            payment_type="customer_receipt", party_code="CUS-1", party_name_snapshot="Test Party",
            location_code="SHJ", payment_date=date(2026, 9, 9), payment_method="cash",
            cash_bank_account_code="Cash", reference_no=None, amount=Decimal("25"), notes=None, lines=[])
    session.rollback()
    payment = transition_payment(session, payment, expected_revision=2, action="submit", actor="maker")
    payment = transition_payment(session, payment, expected_revision=3, action="approve", actor="approver")
    session.scalar(select(OperationalFiscalPeriod)).status = "locked"
    session.commit()
    with pytest.raises(ValueError, match="open rehearsal-enabled"):
        rehearse_payment_posting(session, payment, actor="approver")


def test_duplicate_and_excess_allocations_are_rejected(tmp_path):
    session = payment_session(tmp_path)
    with pytest.raises(ValueError, match="Duplicate allocation"):
        create(session, amount="100", lines=[allocation(amount="20"), allocation(amount="30")])
    session.rollback()
    with pytest.raises(ValueError, match="cannot exceed the payment"):
        create(session, amount="50", lines=[allocation(amount="60")])


def test_invoice_and_opening_rows_share_party_control_balance(tmp_path):
    session = payment_session(tmp_path)
    batch = OperationalOpeningBalanceBatch(batch_key="b" * 64, source_capture="test",
        source_manifest_sha256="a" * 64, source_atomic=False, approval_reference="test",
        imported_by="controller", receivable_rows=1, receivable_amount=Decimal("100"),
        customer_advance_rows=0, customer_advance_amount=0, payable_rows=0,
        payable_amount=0, supplier_advance_rows=0, supplier_advance_amount=0,
        status="approved_non_atomic_nonposting")
    session.add(batch)
    session.flush()
    session.add(OperationalOpeningPartyBalance(batch_id=batch.id, party_type="customer",
        party_code="CUS-1", party_name_snapshot="Test Party", balance_type="receivable",
        amount=Decimal("100"), currency_code="AED", control_account_code="AR",
        offset_account_code="Opening", posting_enabled=False, source_status="approved"))
    session.commit()
    first = create(session, amount="70", lines=[allocation("INV-1", "100", "70")])
    transition_payment(session, first, expected_revision=1, action="submit", actor="maker")
    second = create(session, amount="40", lines=[allocation("OB:1", "100", "40", "opening_balance")])
    with pytest.raises(ValueError, match="party opening control balance"):
        transition_payment(session, second, expected_revision=1, action="submit", actor="maker")
