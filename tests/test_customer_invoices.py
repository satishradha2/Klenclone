from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from klen_clone.customer_invoices import (
    OperationalCustomerInvoice, OperationalCustomerInvoicePostingRehearsal,
    OperationalCustomerInvoiceWorkflowEvent, create_customer_invoice,
    rehearse_customer_invoice, transition_customer_invoice,
)
from klen_clone.delivery_fulfillment import (
    OperationalDeliveryStockMovement, allocate_sales_order, transition_delivery,
)
from klen_clone.operational import (
    OperationalFiscalPeriod, OperationalJournalBatch, OperationalStockPosition,
    initialize_operational_database, make_operational_engine,
)
from klen_clone.payments import (
    OperationalPaymentPostingRehearsal, create_payment,
    customer_invoice_open_items, customer_invoice_settlement,
    rehearse_payment_posting, transition_payment,
)
from klen_clone.financial_reports import build_customer_statement
from klen_clone.sales_orders import (
    accept_sales_quotation, convert_sales_quotation, create_sales_quotation,
    transition_sales_quotation,
)


@pytest.fixture()
def session():
    engine = make_operational_engine("sqlite:///:memory:")
    initialize_operational_database(engine)
    with Session(engine) as value:
        value.add(OperationalFiscalPeriod(
            period_key="FY-2026", starts_on=date(2026, 1, 1), ends_on=date(2026, 12, 31),
            status="open", rehearsal_enabled=True, revision=1,
            approval_reference="customer-invoice-test", configured_by="finance"))
        value.add(OperationalStockPosition(
            location_code="MAIN", sku="SKU-1", canonical_uom="piece",
            quantity_on_hand=Decimal("10"), quantity_reserved=Decimal("0"),
            average_unit_cost=Decimal("4"), revision=1, source_batch_key="test",
            source_status="operational", availability_enabled=True))
        value.commit()
        yield value
    engine.dispose()


def delivered_order(session: Session):
    quote = create_sales_quotation(
        session, customer_code="C-1", customer_name_snapshot="Customer One",
        location_code="MAIN", quotation_date=date(2026, 9, 19),
        valid_until=date(2026, 10, 19), discount_amount=Decimal("1.00"),
        payment_terms="30 days", delivery_terms="Delivered", notes=None,
        actor="sales-maker", lines=[{
            "sku": "SKU-1", "product_name_snapshot": "Product One",
            "quantity": Decimal("2"), "uom": "Pieces", "canonical_uom": "piece",
            "factor_to_base_snapshot": Decimal("1"), "quantity_base": Decimal("2"),
            "unit_price": Decimal("10"), "tax_rate": Decimal("5"),
            "net_amount": Decimal("20"), "tax_amount": Decimal("1"),
            "gross_amount": Decimal("21"),
        }])
    quote = transition_sales_quotation(session, quote, expected_revision=1,
        action="submit", actor="sales-maker")
    quote = transition_sales_quotation(session, quote, expected_revision=2,
        action="approve", actor="sales-checker", note="Commercial approval")
    quote = accept_sales_quotation(session, quote, expected_revision=3,
        actor="sales-maker", acceptance_reference="Customer email")
    order = convert_sales_quotation(session, quote, expected_revision=4, actor="sales-maker")
    delivery = allocate_sales_order(session, order, actor="warehouse",
        note="Allocate customer order")
    delivery = transition_delivery(session, delivery, expected_revision=1, action="pick",
        actor="picker", note="Picked and checked")
    delivery = transition_delivery(session, delivery, expected_revision=2, action="dispatch",
        actor="dispatcher", note="Loaded and dispatched")
    return order, delivery


def test_invoice_requires_pod_and_copies_immutable_delivered_order(session):
    order, delivery = delivered_order(session)
    with pytest.raises(ValueError, match="delivered order"):
        create_customer_invoice(session, delivery, actor="sales-maker",
            invoice_date=date(2026, 9, 19), due_date=date(2026, 10, 19))
    delivery = transition_delivery(session, delivery, expected_revision=3, action="deliver",
        actor="pod-checker", note="Signed POD verified", received_by="Customer Receiver",
        pod_reference="POD-001")
    invoice_date = delivery.delivered_at.date()
    invoice = create_customer_invoice(session, delivery, actor="sales-maker",
        invoice_date=invoice_date, due_date=invoice_date + timedelta(days=30),
        notes="Delivery-backed test invoice")
    assert invoice.sales_order_id == order.id
    assert invoice.delivery_note_no_snapshot == delivery.delivery_note_no
    assert invoice.pod_reference_snapshot == "POD-001"
    assert invoice.customer_name_snapshot == "Customer One"
    assert invoice.total_amount == order.total_amount == Decimal("20.00")
    assert invoice.lines[0].quantity_base == delivery.lines[0].delivered_quantity_base
    assert create_customer_invoice(session, delivery, actor="sales-maker",
        invoice_date=invoice_date, due_date=invoice_date + timedelta(days=30)) is invoice
    assert session.scalar(select(func.count(OperationalCustomerInvoice.id))) == 1


def test_invoice_maker_checker_and_accounting_only_rehearsal(session):
    _, delivery = delivered_order(session)
    delivery = transition_delivery(session, delivery, expected_revision=3, action="deliver",
        actor="pod-checker", note="Signed POD verified", received_by="Customer Receiver",
        pod_reference="POD-002")
    invoice_date = delivery.delivered_at.date()
    invoice = create_customer_invoice(session, delivery, actor="sales-maker",
        invoice_date=invoice_date, due_date=invoice_date + timedelta(days=30))
    invoice = transition_customer_invoice(session, invoice, expected_revision=1,
        action="submit", actor="sales-maker", note="Ready for approval")
    with pytest.raises(PermissionError, match="Maker-checker"):
        transition_customer_invoice(session, invoice, expected_revision=2,
            action="approve", actor="sales-maker", note="Self approval")
    invoice = transition_customer_invoice(session, invoice, expected_revision=2,
        action="approve", actor="sales-manager", note="POD and totals verified")
    stock_movements_before = session.scalar(select(func.count(OperationalDeliveryStockMovement.id)))
    plan = rehearse_customer_invoice(session, invoice, actor="sales-manager")
    assert plan["debit"] == plan["credit"] == Decimal("20.00")
    assert [line["account_code"] for line in plan["journal"]] == ["1200", "4000", "2120"]
    assert plan["inventory_movements"] == []
    assert plan["stock_issue_source"] == delivery.delivery_note_no
    assert plan["posting_enabled"] is False and plan["posting_performed"] is False
    replay = rehearse_customer_invoice(session, invoice, actor="sales-manager")
    assert replay["idempotent_replay"] is True
    assert session.scalar(select(func.count(OperationalCustomerInvoicePostingRehearsal.id))) == 1
    assert session.scalar(select(func.count(OperationalDeliveryStockMovement.id))) == stock_movements_before == 1
    assert session.scalar(select(func.count(OperationalJournalBatch.id))) == 0
    assert session.scalar(select(func.count(OperationalCustomerInvoiceWorkflowEvent.id))) == 2


def test_invoice_rejects_dates_before_delivery_or_due_before_invoice(session):
    _, delivery = delivered_order(session)
    delivery = transition_delivery(session, delivery, expected_revision=3, action="deliver",
        actor="pod-checker", note="Signed POD verified", received_by="Customer Receiver",
        pod_reference="POD-003")
    delivery.delivered_at = delivery.delivered_at.replace(year=2026, month=9, day=19)
    session.commit()
    with pytest.raises(ValueError, match="earlier than the proof"):
        create_customer_invoice(session, delivery, actor="sales-maker",
            invoice_date=date(2026, 9, 18), due_date=date(2026, 10, 18))
    with pytest.raises(ValueError, match="due date"):
        create_customer_invoice(session, delivery, actor="sales-maker",
            invoice_date=date(2026, 9, 19), due_date=date(2026, 9, 18))


def test_approved_invoice_becomes_receivable_and_partial_receipt_reduces_outstanding(session):
    _, delivery = delivered_order(session)
    delivery = transition_delivery(session, delivery, expected_revision=3, action="deliver",
        actor="pod-checker", note="Signed POD verified", received_by="Customer Receiver",
        pod_reference="POD-AR-001")
    invoice_date = delivery.delivered_at.date()
    invoice = create_customer_invoice(session, delivery, actor="sales-maker",
        invoice_date=invoice_date, due_date=invoice_date + timedelta(days=30))
    invoice = transition_customer_invoice(session, invoice, expected_revision=1,
        action="submit", actor="sales-maker", note="Ready for approval")
    invoice = transition_customer_invoice(session, invoice, expected_revision=2,
        action="approve", actor="sales-manager", note="POD and totals verified")
    open_items = customer_invoice_open_items(session, "C-1")
    assert len(open_items) == 1
    assert open_items[0]["source_reference_key"] == invoice.invoice_no
    assert open_items[0]["available_outstanding"] == Decimal("20.00")
    assert open_items[0]["source_origin"] == "target_erp"

    receipt = create_payment(session, actor="ar-maker", payment_type="customer_receipt",
        party_code="C-1", party_name_snapshot="Customer One", location_code="MAIN",
        payment_date=invoice_date, payment_method="bank_transfer",
        cash_bank_account_code="Bank - AED", reference_no="BANK-AR-001",
        amount=Decimal("6.00"), notes="Partial customer receipt", lines=[{
            "source_type": "invoice", "source_reference_key": invoice.invoice_no,
            "source_document_date": invoice.invoice_date,
            "source_outstanding_snapshot": invoice.total_amount,
            "allocation_amount": Decimal("6.00"),
        }])
    receipt = transition_payment(session, receipt, expected_revision=1,
        action="submit", actor="ar-maker", note="Bank receipt matched")
    receipt = transition_payment(session, receipt, expected_revision=2,
        action="approve", actor="finance-approver", note="Receipt evidence verified")
    plan = rehearse_payment_posting(session, receipt, actor="finance-approver")
    assert plan["debit"] == plan["credit"] == Decimal("6.00")
    assert plan["posting_enabled"] is False
    assert session.scalar(select(func.count(OperationalPaymentPostingRehearsal.id))) == 1
    remaining = customer_invoice_open_items(session, "C-1")
    assert remaining[0]["available_outstanding"] == Decimal("14.00")
    assert customer_invoice_settlement(session, invoice) == {
        "settlement_status": "partially_paid",
        "paid_amount": Decimal("6.00"),
        "pending_allocation_amount": Decimal("0.00"),
        "outstanding_amount": Decimal("14.00"),
        "available_outstanding": Decimal("14.00"),
    }

    excess = create_payment(session, actor="ar-maker", payment_type="customer_receipt",
        party_code="C-1", party_name_snapshot="Customer One", location_code="MAIN",
        payment_date=invoice_date, payment_method="cash",
        cash_bank_account_code="Cash - AED", reference_no=None,
        amount=Decimal("15.00"), notes="Excess allocation test", lines=[{
            "source_type": "invoice", "source_reference_key": invoice.invoice_no,
            "source_document_date": invoice.invoice_date,
            "source_outstanding_snapshot": invoice.total_amount,
            "allocation_amount": Decimal("15.00"),
        }])
    with pytest.raises(ValueError, match="remaining outstanding"):
        transition_payment(session, excess, expected_revision=1,
            action="submit", actor="ar-maker", note="Must not over-allocate")
    session.rollback()

    final_receipt = create_payment(session, actor="ar-maker", payment_type="customer_receipt",
        party_code="C-1", party_name_snapshot="Customer One", location_code="MAIN",
        payment_date=invoice_date, payment_method="cash",
        cash_bank_account_code="Cash - AED", reference_no=None,
        amount=Decimal("14.00"), notes="Final customer receipt", lines=[{
            "source_type": "invoice", "source_reference_key": invoice.invoice_no,
            "source_document_date": invoice.invoice_date,
            "source_outstanding_snapshot": invoice.total_amount,
            "allocation_amount": Decimal("14.00"),
        }])
    final_receipt = transition_payment(session, final_receipt, expected_revision=1,
        action="submit", actor="ar-maker", note="Final allocation")
    final_receipt = transition_payment(session, final_receipt, expected_revision=2,
        action="approve", actor="finance-approver", note="Receipt verified")
    assert customer_invoice_settlement(session, invoice)["settlement_status"] == "paid"
    assert customer_invoice_settlement(session, invoice)["outstanding_amount"] == Decimal("0.00")
    assert customer_invoice_open_items(session, "C-1") == []
    statement = build_customer_statement(session, party_code="C-1",
        party_name="Customer One", as_of=invoice_date)
    assert statement["invoice_total"] == statement["receipt_total"] == Decimal("20.00")
    assert statement["closing_balance"] == Decimal("0.00")
    assert [row["entry_type"] for row in statement["entries"]] == [
        "customer_invoice", "customer_receipt", "customer_receipt"]
