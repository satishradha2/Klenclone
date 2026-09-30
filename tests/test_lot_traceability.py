from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from klen_clone.customer_invoices import create_customer_invoice
from klen_clone.delivery_fulfillment import allocate_sales_order, transition_delivery
from klen_clone.goods_receipts import create_goods_receipt, transition_goods_receipt
from klen_clone.lot_traceability import (
    OperationalDeliveryLotAllocation, OperationalReceiptLot, assign_delivery_lot,
    trace_lot,
)
from klen_clone.operational import OperationalStockPosition, initialize_operational_database, make_operational_engine
from klen_clone.product_creation import OperationalProductDetails
from klen_clone.sales_orders import (
    accept_sales_quotation, convert_sales_quotation, create_sales_quotation,
    transition_sales_quotation,
)
from klen_clone.warehouse_controls import (
    create_product_recall, create_quarantine_hold, transition_product_recall,
)


@pytest.fixture()
def session():
    engine = make_operational_engine("sqlite:///:memory:")
    initialize_operational_database(engine)
    with Session(engine) as value:
        value.add(OperationalProductDetails(sku="LOT-SKU", payload_json='{"track_lots":true,"track_expiry":true}', duplicate_key="lot-test"))
        value.add(OperationalStockPosition(location_code="MAIN", sku="LOT-SKU", canonical_uom="piece",
            quantity_on_hand=Decimal("10"), quantity_reserved=Decimal("0"), average_unit_cost=Decimal("4"),
            revision=1, source_batch_key="test", source_status="operational", availability_enabled=True))
        value.commit()
        yield value
    engine.dispose()


def receipt(session, batch: str | None, qty="3"):
    row = create_goods_receipt(session, supplier_code="SUP-LOT", supplier_name_snapshot="Lot Supplier",
        location_code="MAIN", purchase_reference="PO-LOT", supplier_delivery_note="SDN-LOT",
        received_on=date.today(), notes=None, actor="buyer", lines=[{
            "sku": "LOT-SKU", "product_name_snapshot": "Tracked Product",
            "ordered_quantity": Decimal(qty), "received_quantity": Decimal(qty),
            "accepted_quantity": Decimal(qty), "rejected_quantity": Decimal("0"),
            "uom": "Pieces", "canonical_uom": "piece", "factor_to_base_snapshot": Decimal("1"),
            "unit_cost_snapshot": Decimal("4"), "batch_no": batch,
            "expiry_date": date.today() + timedelta(days=180), "rejection_reason": None,
        }])
    row = transition_goods_receipt(session, row, expected_revision=1, action="submit", actor="buyer")
    return row


def accepted_lot(session, batch="BATCH-A", qty="3"):
    row = receipt(session, batch, qty)
    transition_goods_receipt(session, row, expected_revision=2, action="accept", actor="checker")
    return session.scalar(select(OperationalReceiptLot).where(OperationalReceiptLot.receipt_id == row.id))


def delivery(session):
    quote = create_sales_quotation(session, customer_code="C-LOT", customer_name_snapshot="Affected Customer",
        location_code="MAIN", quotation_date=date.today(), valid_until=date.today()+timedelta(days=10),
        discount_amount=Decimal("0"), payment_terms=None, delivery_terms=None, notes=None,
        actor="sales", lines=[{"sku":"LOT-SKU", "product_name_snapshot":"Tracked Product",
            "quantity":Decimal("2"), "uom":"Pieces", "canonical_uom":"piece",
            "factor_to_base_snapshot":Decimal("1"), "quantity_base":Decimal("2"),
            "unit_price":Decimal("10"), "tax_rate":Decimal("5"), "net_amount":Decimal("20"),
            "tax_amount":Decimal("1"), "gross_amount":Decimal("21")}])
    quote = transition_sales_quotation(session, quote, expected_revision=1, action="submit", actor="sales")
    quote = transition_sales_quotation(session, quote, expected_revision=2, action="approve", actor="approver", note="Approved")
    quote = accept_sales_quotation(session, quote, expected_revision=3, actor="sales", acceptance_reference="Email")
    order = convert_sales_quotation(session, quote, expected_revision=4, actor="sales")
    return allocate_sales_order(session, order, actor="warehouse", note="Allocate tracked stock")


def test_receipt_requires_lot_for_tracked_product(session):
    row = receipt(session, None)
    with pytest.raises(ValueError, match="requires a batch number"):
        transition_goods_receipt(session, row, expected_revision=2, action="accept", actor="checker")
    session.rollback()
    assert session.get(type(row), row.id).status == "submitted"
    assert session.scalar(select(OperationalReceiptLot)) is None


def test_lot_provenance_through_invoice_and_customer(session):
    lot_a = accepted_lot(session, "BATCH-A", "1")
    lot_b = accepted_lot(session, "BATCH-B", "1")
    fulfillment = delivery(session)
    with pytest.raises(ValueError, match="complete lot allocation"):
        transition_delivery(session, fulfillment, expected_revision=1, action="pick", actor="picker", note="Pick stock")
    session.rollback()
    assign_delivery_lot(session, fulfillment, line_no=1, lot_key=lot_a.lot_key, quantity_base=Decimal("1"), actor="picker")
    with pytest.raises(ValueError, match="complete lot allocation"):
        transition_delivery(session, fulfillment, expected_revision=1, action="pick", actor="picker", note="Pick stock")
    session.rollback()
    assign_delivery_lot(session, fulfillment, line_no=1, lot_key=lot_b.lot_key, quantity_base=Decimal("1"), actor="picker")
    fulfillment = transition_delivery(session, fulfillment, expected_revision=1, action="pick", actor="picker", note="Picked two lots")
    fulfillment = transition_delivery(session, fulfillment, expected_revision=2, action="dispatch", actor="dispatcher", note="Dispatched two lots")
    fulfillment = transition_delivery(session, fulfillment, expected_revision=3, action="deliver", actor="pod", note="POD signed", received_by="Customer", pod_reference="POD-LOT")
    invoice_day = fulfillment.delivered_at.date()
    invoice = create_customer_invoice(session, fulfillment, actor="finance", invoice_date=invoice_day,
        due_date=invoice_day + timedelta(days=30))
    traced = trace_lot(session, lot_a)
    assert traced["supplier_code"] == "SUP-LOT"
    assert traced["downstream"][0]["delivery_note_no"] == fulfillment.delivery_note_no
    assert traced["downstream"][0]["customer_code"] == "C-LOT"
    assert traced["downstream"][0]["invoice_no"] == invoice.invoice_no
    assert traced["downstream"][0]["allocation_status"] == "consumed"


def test_lot_overallocation_quarantine_and_cancel_release(session):
    lot = accepted_lot(session, "BATCH-C", "2")
    fulfillment = delivery(session)
    with pytest.raises(ValueError, match="exceeds accepted"):
        assign_delivery_lot(session, fulfillment, line_no=1, lot_key=lot.lot_key,
            quantity_base=Decimal("3"), actor="picker")
    session.rollback()
    assign_delivery_lot(session, fulfillment, line_no=1, lot_key=lot.lot_key,
        quantity_base=Decimal("2"), actor="picker")
    create_quarantine_hold(session, location_code="MAIN", sku="LOT-SKU", quantity_base=Decimal("1"),
        reason="Suspect stock", actor="quality")
    with pytest.raises(ValueError, match="quarantined"):
        transition_delivery(session, fulfillment, expected_revision=1, action="pick", actor="picker", note="Pick stock")
    session.rollback()
    transition_delivery(session, fulfillment, expected_revision=1, action="cancel", actor="warehouse", note="Cancel held stock")
    assert session.scalar(select(OperationalDeliveryLotAllocation.status)) == "released"


def test_active_lot_recall_blocks_pick_and_release_remains_possible(session):
    lot = accepted_lot(session, "BATCH-RECALL", "2")
    fulfillment = delivery(session)
    assign_delivery_lot(session, fulfillment, line_no=1, lot_key=lot.lot_key,
        quantity_base=Decimal("2"), actor="picker")
    recall = create_product_recall(session, location_code="MAIN", reason="Supplier notified of defect",
        severity="high", lines=[{"sku":"LOT-SKU", "identity_value":lot.lot_key,
                                 "quantity_base":Decimal("2")}], actor="quality")
    recall = transition_product_recall(session, recall, action="submit", expected_revision=1,
        actor="quality", note="Escalated affected lot")
    transition_product_recall(session, recall, action="activate", expected_revision=2,
        actor="checker", note="Verified supplier notice")
    with pytest.raises(ValueError, match="active recall"):
        transition_delivery(session, fulfillment, expected_revision=1, action="pick",
            actor="picker", note="Attempt to pick recalled lot")
    session.rollback()
    assign_delivery_lot(session, fulfillment, line_no=1, lot_key=lot.lot_key,
        quantity_base=Decimal("0"), actor="picker")
    assert session.scalar(select(OperationalDeliveryLotAllocation.status)) == "released"
