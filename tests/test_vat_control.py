from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from klen_clone.expense_management import create_expense_claim, transition_expense_claim
from klen_clone.operational import initialize_operational_database, make_operational_engine
from klen_clone.vat_control import (
    OperationalVatReturnRehearsal, create_vat_adjustment, create_vat_period,
    decide_vat_adjustment, rehearse_vat_return, transition_vat_period,
    vat_workspace_payload,
)


def vat_session(tmp_path):
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'vat-control.db'}")
    initialize_operational_database(engine)
    return Session(engine)


def eligible_expense(session):
    claim = create_expense_claim(session, claimant_type="supplier", claimant_reference="SUP-VAT",
        claimant_name="Testing VAT supplier", expense_date=date(2026, 9, 21), location_code="MAIN",
        cost_center="ADMIN", category_code="office_admin", description="Testing VAT source",
        receipt_reference="VAT-RCPT-1", tax_invoice_no="VAT-TAX-1", supplier_trn="123456789012345",
        vat_rate=Decimal("5"), net_amount=Decimal("100"), vat_amount=Decimal("5"),
        settlement_method="reimbursement", payment_account_key=None, actor="maker")
    claim = transition_expense_claim(session, claim, action="submit", expected_revision=1, actor="maker")
    return transition_expense_claim(session, claim, action="approve", expected_revision=2,
                                    actor="approver", note="Independent expense approval")


def test_vat_period_reverse_charge_approval_and_non_filing_rehearsal(tmp_path):
    session = vat_session(tmp_path)
    eligible_expense(session)
    period = create_vat_period(session, period_code="VAT-UAT-2026-09",
        starts_on=date(2026, 9, 1), ends_on=date(2026, 9, 30), due_on=date(2026, 10, 28),
        company_trn="100000000000003", actor="maker")
    adjustment = create_vat_adjustment(session, period, adjustment_type="reverse_charge",
        adjustment_date=date(2026, 9, 21), evidence_reference="UAT-RCM-1",
        reason="Testing reverse charge mechanism", taxable_amount=Decimal("100"),
        vat_amount=Decimal("5"), recovery_percent=Decimal("100"), actor="maker")
    with pytest.raises(PermissionError, match="self-approval"):
        decide_vat_adjustment(session, adjustment, action="approve", expected_revision=1,
                              actor="maker", note="Attempted self approval")
    session.rollback()
    decide_vat_adjustment(session, adjustment, action="approve", expected_revision=1,
                          actor="approver", note="Independent reverse-charge approval")
    period = transition_vat_period(session, period, action="submit", expected_revision=1,
                                   actor="maker")
    assert period.source_count == 2
    assert period.output_vat == Decimal("5.00")
    assert period.input_vat == Decimal("10.00")
    assert period.net_vat == Decimal("-5.00")
    with pytest.raises(PermissionError, match="self-approval"):
        transition_vat_period(session, period, action="approve", expected_revision=2,
                              actor="maker", note="Attempted self approval")
    session.rollback()
    period = transition_vat_period(session, period, action="approve", expected_revision=2,
        actor="approver", note="Independent VAT return approval")
    plan = rehearse_vat_return(session, period, actor="approver")
    assert plan["filing_performed"] is False and plan["posting_performed"] is False
    assert sum(Decimal(str(line["debit"])) for line in plan["journal"]) == Decimal("10.00")
    assert sum(Decimal(str(line["credit"])) for line in plan["journal"]) == Decimal("10.00")
    assert plan["return"]["filing_status"] == "not_filed_testing_rehearsal"
    assert rehearse_vat_return(session, period, actor="approver")["idempotent_replay"] is True
    assert session.scalar(select(func.count(OperationalVatReturnRehearsal.id))) == 1
    controls = vat_workspace_payload(session)["controls"]
    assert controls["approved_returns"] == 1 and controls["filings"] == 0


def test_vat_period_blocks_pending_adjustment_and_overlaps(tmp_path):
    session = vat_session(tmp_path)
    period = create_vat_period(session, period_code="VAT-UAT-2026-Q3",
        starts_on=date(2026, 7, 1), ends_on=date(2026, 9, 30), due_on=date(2026, 10, 28),
        company_trn="100000000000003", actor="maker")
    create_vat_adjustment(session, period, adjustment_type="output_increase",
        adjustment_date=date(2026, 9, 21), evidence_reference="UAT-ADJ-1",
        reason="Testing output correction", taxable_amount=Decimal("100"),
        vat_amount=Decimal("5"), recovery_percent=Decimal("100"), actor="maker")
    with pytest.raises(ValueError, match="pending VAT adjustment"):
        transition_vat_period(session, period, action="submit", expected_revision=1, actor="maker")
    with pytest.raises(ValueError, match="overlaps"):
        create_vat_period(session, period_code="VAT-UAT-OVERLAP",
            starts_on=date(2026, 9, 1), ends_on=date(2026, 9, 30), due_on=date(2026, 10, 28),
            company_trn="100000000000003", actor="maker")
