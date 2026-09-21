from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from klen_clone.operational import OperationalAuditEvent, OperationalFiscalPeriod, OperationalStockPosition, initialize_operational_database, make_operational_engine
from klen_clone.procurement_matching import OperationalSupplierInvoice, OperationalSupplierInvoiceLine
from klen_clone.purchase_returns import OperationalPurchaseReturnPostingRehearsal, OperationalPurchaseReturnReservation, OperationalPurchaseReturnWorkflowEvent, create_purchase_return, purchase_return_control_counts, rehearse_purchase_return_posting, replace_purchase_return, transition_purchase_return


def return_session(tmp_path):
    engine=make_operational_engine(f"sqlite:///{tmp_path/'purchase-return.db'}"); initialize_operational_database(engine); session=Session(engine)
    session.add(OperationalFiscalPeriod(period_key="2026-09",starts_on=date(2026,9,1),ends_on=date(2026,9,30),status="open",rehearsal_enabled=True,approval_reference="test",configured_by="controller"))
    session.add(OperationalStockPosition(location_code="SHJ",sku="SKU-1",canonical_uom="piece",quantity_on_hand=Decimal("20"),quantity_reserved=Decimal("0"),average_unit_cost=Decimal("7"),availability_enabled=True,source_status="test_reconciled"))
    invoice=OperationalSupplierInvoice(invoice_key="invoice-1",supplier_invoice_no="SUPINV-1",purchase_order_id=1,supplier_code="SUP-1",location_code="SHJ",invoice_date=date(2026,9,8),due_date=date(2026,10,8),currency_code="AED",subtotal=Decimal("80"),tax_amount=Decimal("4"),total_amount=Decimal("84"),status="posted",match_status="passed",match_summary="POSTED",posting_enabled=False,created_by="invoice-maker",decided_by="invoice-approver",decision_note="test",revision=4,state_changed_by="posting-user")
    session.add(invoice); session.flush(); session.add(OperationalSupplierInvoiceLine(invoice_id=invoice.id,purchase_order_line_id=1,sku="SKU-1",quantity=Decimal("10"),unit_price=Decimal("8"),tax_rate=Decimal("5"),net_amount=Decimal("80"),tax_amount=Decimal("4"),gross_amount=Decimal("84")))
    session.commit(); return session


def line(quantity="4",supplier="3",writeoff="1",reason="Damaged before dispatch",source="10",price="8"):
    return {"sku":"SKU-1","product_name_snapshot":"Product One","source_received_quantity":Decimal(source),"quantity":Decimal(quantity),"supplier_return_quantity":Decimal(supplier),"internal_writeoff_quantity":Decimal(writeoff),"uom":"Piece","canonical_uom":"piece","factor_to_base_snapshot":Decimal("1"),"unit_price":Decimal(price),"tax_rate":Decimal("5"),"unit_cost_snapshot":Decimal("6"),"disposition_reason":reason}


def create(session,lines=None):
    return create_purchase_return(session,supplier_code="SUP-1",supplier_name_snapshot="Supplier One",location_code="SHJ",source_reference_type="purchase_invoice",source_reference_key="SUPINV-1",return_date=date(2026,9,9),reason_code="quality",notes=None,actor="maker",lines=lines or [line()])


def test_purchase_return_reserves_stock_creates_debit_note_and_balances(tmp_path):
    session=return_session(tmp_path); document=create(session)
    assert document.subtotal==Decimal("24.00") and document.tax_amount==Decimal("1.20")
    document=transition_purchase_return(session,document,expected_revision=1,action="submit",actor="maker")
    assert session.scalar(select(OperationalStockPosition)).quantity_reserved==4
    with pytest.raises(PermissionError,match="Maker-checker"): transition_purchase_return(session,document,expected_revision=2,action="approve",actor="maker")
    session.rollback(); document=transition_purchase_return(session,document,expected_revision=2,action="approve",actor="approver")
    assert document.debit_note.debit_note_no.startswith("DN-") and document.debit_note.total_amount==Decimal("25.20")
    plan=rehearse_purchase_return_posting(session,document,actor="approver")
    assert plan["posting_enabled"] is False and plan["debit"]==plan["credit"]==Decimal("32.20")
    assert plan["movements"][0]["quantity_base"]==-4 and plan["supplier_return_cost"]==Decimal("21.00") and plan["writeoff_cost"]==Decimal("7.00") and plan["purchase_return_variance"]==Decimal("3.00")
    assert plan["supplier_invoice_no"]=="SUPINV-1" and plan["journal"][0]["account_code"]=="2100"
    assert rehearse_purchase_return_posting(session,document,actor="approver")["idempotent_replay"] is True
    assert session.scalar(select(func.count(OperationalPurchaseReturnPostingRehearsal.id)))==1
    assert purchase_return_control_counts(session)=={"returns":1,"debit_notes":1,"active_reservations":1,"posted":0}
    assert session.scalar(select(func.count(OperationalPurchaseReturnWorkflowEvent.id)))==2 and session.scalar(select(func.count(OperationalAuditEvent.id)))==4


def test_quantity_and_disposition_validation_fail_closed(tmp_path):
    session=return_session(tmp_path)
    with pytest.raises(ValueError,match="cannot exceed"): create(session,[line(quantity="11",supplier="10",writeoff="1")])
    session.rollback()
    with pytest.raises(ValueError,match="conserve quantity"): create(session,[line(quantity="4",supplier="2",writeoff="1")])
    session.rollback()
    with pytest.raises(ValueError,match="disposition reason"): create(session,[line(reason=None)])


def test_cancel_releases_stock_and_cumulative_source_cap_is_enforced(tmp_path):
    session=return_session(tmp_path); first=create(session,[line(quantity="6",supplier="6",writeoff="0",reason=None)])
    first=transition_purchase_return(session,first,expected_revision=1,action="submit",actor="maker")
    second=create(session,[line(quantity="5",supplier="5",writeoff="0",reason=None)])
    with pytest.raises(ValueError,match="remaining source quantity"): transition_purchase_return(session,second,expected_revision=1,action="submit",actor="maker")
    session.rollback(); first=transition_purchase_return(session,first,expected_revision=2,action="cancel",actor="maker")
    assert session.scalar(select(OperationalStockPosition)).quantity_reserved==0
    assert session.scalar(select(OperationalPurchaseReturnReservation)).status=="released"


def test_edit_revision_and_locked_period_controls(tmp_path):
    session=return_session(tmp_path); document=create(session)
    document=replace_purchase_return(session,document,expected_revision=1,supplier_code="SUP-1",supplier_name_snapshot="Supplier One",location_code="SHJ",source_reference_type="purchase_invoice",source_reference_key="SUPINV-1",return_date=date(2026,9,9),reason_code="wrong_item",notes="Reviewed",actor="maker",lines=[line(quantity="3",supplier="3",writeoff="0",reason=None)])
    assert document.revision==2 and document.source_reference_key=="SUPINV-1"
    with pytest.raises(ValueError,match="revision conflict"): replace_purchase_return(session,document,expected_revision=1,supplier_code="SUP-1",supplier_name_snapshot="Supplier One",location_code="SHJ",source_reference_type="purchase_invoice",source_reference_key="SUPINV-1",return_date=date(2026,9,9),reason_code="wrong_item",notes=None,actor="maker",lines=[line()])
    session.rollback(); document=transition_purchase_return(session,document,expected_revision=2,action="submit",actor="maker"); document=transition_purchase_return(session,document,expected_revision=3,action="approve",actor="approver")
    session.scalar(select(OperationalFiscalPeriod)).status="locked"; session.commit()
    with pytest.raises(ValueError,match="open rehearsal-enabled"): rehearse_purchase_return_posting(session,document,actor="approver")
