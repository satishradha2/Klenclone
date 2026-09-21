from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from klen_clone.cash_management import create_cash_account, decide_cash_account
from klen_clone.expense_management import (
    OperationalExpenseRehearsal, OperationalPettyCashRehearsal,
    create_expense_claim, create_petty_cash_advance, expense_workspace_payload,
    rehearse_expense, rehearse_petty_cash, transition_expense_claim,
    transition_petty_cash_advance,
)
from klen_clone.operational import (
    OperationalFiscalPeriod, initialize_operational_database, make_operational_engine,
)


def expense_session(tmp_path):
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'expenses.db'}")
    initialize_operational_database(engine)
    session = Session(engine)
    session.add(OperationalFiscalPeriod(period_key="2026-09", starts_on=date(2026, 9, 1),
        ends_on=date(2026, 9, 30), status="open", rehearsal_enabled=True,
        approval_reference="UAT only", configured_by="controller"))
    session.commit()
    return session


def approved_account(session, account_type="bank"):
    code = "Bank - AED" if account_type == "bank" else "Petty Cash - AED"
    row = create_cash_account(session, account_code=code, account_name=f"Approved {account_type}",
        account_type=account_type, bank_name="Test Bank" if account_type == "bank" else None,
        identifier="AE000000000000000001234" if account_type == "bank" else None,
        gl_account_code=code, location_code="MAIN", reason="Testing only account",
        actor="maker")
    return decide_cash_account(session, row, action="approve", expected_revision=1,
                               actor="approver", note="Independent test approval")


def test_expense_vat_approval_and_non_posting_rehearsal(tmp_path):
    session = expense_session(tmp_path)
    account = approved_account(session)
    claim = create_expense_claim(session, claimant_type="supplier", claimant_reference="SUP-1",
        claimant_name="Fuel Vendor", expense_date=date(2026, 9, 21), location_code="MAIN",
        cost_center="DELIVERY", category_code="fuel", description="Testing only fuel claim",
        receipt_reference="RCPT-1", tax_invoice_no="TAX-1", supplier_trn="123456789012345",
        vat_rate=Decimal("5"), net_amount=Decimal("100"), vat_amount=Decimal("5"),
        settlement_method="direct_payment", payment_account_key=account.account_key,
        actor="maker")
    assert claim.vat_status == "eligible" and claim.total_amount == Decimal("105.00")
    claim = transition_expense_claim(session, claim, action="submit", expected_revision=1,
                                     actor="maker")
    with pytest.raises(PermissionError, match="Maker-checker"):
        transition_expense_claim(session, claim, action="approve", expected_revision=2,
                                 actor="maker", note="Self approval attempt")
    session.rollback()
    claim = transition_expense_claim(session, claim, action="approve", expected_revision=2,
        actor="approver", note="Independent expense approval")
    plan = rehearse_expense(session, claim, actor="approver")
    assert plan["posting_enabled"] is False and plan["posting_performed"] is False
    assert sum(Decimal(str(line["debit"])) for line in plan["journal"]) == Decimal("105.00")
    assert sum(Decimal(str(line["credit"])) for line in plan["journal"]) == Decimal("105.00")
    assert {line["account"] for line in plan["journal"]} == {"6000", "Input VAT", "Bank - AED"}
    assert rehearse_expense(session, claim, actor="approver")["idempotent_replay"] is True
    assert session.scalar(select(func.count(OperationalExpenseRehearsal.id))) == 1


def test_expense_vat_review_blocks_submission(tmp_path):
    session = expense_session(tmp_path)
    claim = create_expense_claim(session, claimant_type="employee", claimant_reference="EMP-1",
        claimant_name="Test Employee", expense_date=date(2026, 9, 21), location_code="MAIN",
        cost_center="ADMIN", category_code="office_admin", description="Testing only office claim",
        receipt_reference="RCPT-2", tax_invoice_no=None, supplier_trn=None,
        vat_rate=Decimal("5"), net_amount=Decimal("20"), vat_amount=Decimal("1"),
        settlement_method="reimbursement", payment_account_key=None, actor="maker")
    assert claim.vat_status == "review_required"
    with pytest.raises(ValueError, match="15-digit supplier TRN"):
        transition_expense_claim(session, claim, action="submit", expected_revision=1, actor="maker")


def test_petty_cash_issue_settlement_and_rehearsals(tmp_path):
    session = expense_session(tmp_path)
    account = approved_account(session, "cash")
    advance = create_petty_cash_advance(session, recipient_reference="EMP-2",
        recipient_name="Test Custodian", location_code="MAIN", cost_center="DELIVERY",
        account_key=account.account_key, requested_on=date(2026, 9, 21),
        due_on=date(2026, 9, 25), purpose="Testing only delivery expenses",
        amount=Decimal("100"), actor="maker")
    with pytest.raises(PermissionError, match="Maker-checker"):
        transition_petty_cash_advance(session, advance, action="approve", expected_revision=1,
            actor="maker", note="Self approval attempt")
    session.rollback()
    advance = transition_petty_cash_advance(session, advance, action="approve", expected_revision=1,
        actor="approver", note="Independent advance approval")
    issue_plan = rehearse_petty_cash(session, advance, actor="approver")
    assert issue_plan["stage"] == "issue" and len(issue_plan["journal"]) == 2
    advance = transition_petty_cash_advance(session, advance, action="issue", expected_revision=2,
                                             actor="maker")
    advance = transition_petty_cash_advance(session, advance, action="settle", expected_revision=3,
        actor="maker", spent_amount=Decimal("80"), returned_amount=Decimal("20"),
        category_code="fuel", receipt_reference="PC-RCPT-1")
    settlement = rehearse_petty_cash(session, advance, actor="approver")
    assert settlement["stage"] == "settlement"
    assert sum(Decimal(str(line["debit"])) for line in settlement["journal"]) == Decimal("100.00")
    assert sum(Decimal(str(line["credit"])) for line in settlement["journal"]) == Decimal("100.00")
    assert session.scalar(select(func.count(OperationalPettyCashRehearsal.id))) == 2
    controls = expense_workspace_payload(session)["controls"]
    assert controls["open_advances"] == 0 and controls["permanent_postings"] == 0
