from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from klen_clone.operational import OperationalAuditEvent, OperationalFiscalPeriod, initialize_operational_database, make_operational_engine
from klen_clone.sales_returns import (
    OperationalSalesCreditNote, OperationalSalesReturnWorkflowEvent, create_sales_return,
    replace_sales_return, rehearse_sales_return_posting, sales_return_control_counts,
    transition_sales_return,
)


def return_session(tmp_path):
    engine=make_operational_engine(f"sqlite:///{tmp_path/'sales-return.db'}"); initialize_operational_database(engine)
    session=Session(engine); session.add(OperationalFiscalPeriod(period_key="2026-09",starts_on=date(2026,9,1),
        ends_on=date(2026,9,30),status="open",rehearsal_enabled=True,approval_reference="test",configured_by="controller")); session.commit(); return session


def line(restock="2",writeoff="1",reason="Damaged seal"):
    return {"sku":"SKU-1","product_name_snapshot":"Product One","quantity":Decimal("3"),
        "restock_quantity":Decimal(restock),"writeoff_quantity":Decimal(writeoff),"uom":"Piece",
        "canonical_uom":"piece","factor_to_base_snapshot":Decimal("1"),"unit_price":Decimal("10"),
        "tax_rate":Decimal("5"),"unit_cost_snapshot":Decimal("6"),"disposition_reason":reason}


def create(session,lines=None):
    return create_sales_return(session,customer_code="CUS-1",customer_name_snapshot="Customer One",location_code="SHJ",
        original_invoice_reference="INV-100",return_date=date(2026,9,9),reason_code="customer_return",notes=None,
        actor="maker",lines=lines or [line()])


def test_approval_creates_linked_credit_note_and_balanced_rehearsal(tmp_path):
    session=return_session(tmp_path); document=create(session)
    assert document.subtotal==Decimal("30.00") and document.tax_amount==Decimal("1.50") and document.total_amount==Decimal("31.50")
    document=transition_sales_return(session,document,expected_revision=1,action="submit",actor="maker")
    with pytest.raises(PermissionError,match="Maker-checker"):
        transition_sales_return(session,document,expected_revision=2,action="approve",actor="maker")
    session.rollback(); document=transition_sales_return(session,document,expected_revision=2,action="approve",actor="approver")
    assert document.credit_note.credit_note_no.startswith("CN-") and document.credit_note.total_amount==Decimal("31.50")
    plan=rehearse_sales_return_posting(session,document,actor="approver")
    assert plan["posting_enabled"] is False and plan["debit"]==plan["credit"]==Decimal("49.50")
    assert plan["movements"][0]["quantity_base"]==2 and plan["restock_cost"]==Decimal("12.00") and plan["writeoff_cost"]==Decimal("6.00")
    assert {row["account"] for row in plan["journal"]}=={"Sales Returns","Output VAT","Accounts Receivable","Inventory","Returned Goods Write-off","Cost of Goods Sold"}
    assert sales_return_control_counts(session)=={"returns":1,"credit_notes":1,"posted":0}
    assert session.scalar(select(func.count(OperationalSalesReturnWorkflowEvent.id)))==2
    assert session.scalar(select(func.count(OperationalAuditEvent.id)))==4


def test_disposition_conservation_and_reason_fail_closed(tmp_path):
    session=return_session(tmp_path)
    with pytest.raises(ValueError,match="conserve quantity"): create(session,[line(restock="1",writeoff="1")])
    session.rollback()
    with pytest.raises(ValueError,match="disposition reason"): create(session,[line(reason=None)])


def test_draft_edit_is_revision_protected_and_submitted_return_is_locked(tmp_path):
    session=return_session(tmp_path); document=create(session)
    document=replace_sales_return(session,document,expected_revision=1,customer_code="CUS-1",customer_name_snapshot="Customer One",
        location_code="SHJ",original_invoice_reference="INV-101",return_date=date(2026,9,9),reason_code="quality",
        notes="Checked",actor="maker",lines=[line(restock="3",writeoff="0",reason=None)])
    assert document.revision==2 and document.original_invoice_reference=="INV-101"
    with pytest.raises(ValueError,match="revision conflict"):
        replace_sales_return(session,document,expected_revision=1,customer_code="CUS-1",customer_name_snapshot="Customer One",
            location_code="SHJ",original_invoice_reference="INV-101",return_date=date(2026,9,9),reason_code="quality",
            notes=None,actor="maker",lines=[line()])
    session.rollback(); document=transition_sales_return(session,document,expected_revision=2,action="submit",actor="maker")
    with pytest.raises(ValueError,match="Only draft-state"):
        replace_sales_return(session,document,expected_revision=3,customer_code="CUS-1",customer_name_snapshot="Customer One",
            location_code="SHJ",original_invoice_reference="INV-101",return_date=date(2026,9,9),reason_code="quality",
            notes=None,actor="maker",lines=[line()])


def test_locked_period_blocks_rehearsal(tmp_path):
    session=return_session(tmp_path); document=create(session,[line(restock="3",writeoff="0",reason=None)])
    document=transition_sales_return(session,document,expected_revision=1,action="submit",actor="maker")
    document=transition_sales_return(session,document,expected_revision=2,action="approve",actor="approver")
    session.scalar(select(OperationalFiscalPeriod)).status="locked"; session.commit()
    with pytest.raises(ValueError,match="open rehearsal-enabled"): rehearse_sales_return_posting(session,document,actor="approver")
