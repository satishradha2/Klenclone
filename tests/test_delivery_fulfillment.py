from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from klen_clone.delivery_fulfillment import (
    OperationalDeliveryReservation, OperationalDeliveryStockMovement,
    OperationalDeliveryWorkflowEvent, allocate_sales_order, transition_delivery,
)
from klen_clone.operational import (
    OperationalJournalBatch, OperationalStockPosition, initialize_operational_database,
    make_operational_engine, operational_session_factory,
)
from klen_clone.sales_orders import (
    accept_sales_quotation, convert_sales_quotation, create_sales_quotation,
    transition_sales_quotation,
)


@pytest.fixture()
def session():
    engine=make_operational_engine("sqlite:///:memory:"); initialize_operational_database(engine)
    with operational_session_factory(engine)() as value: yield value
    engine.dispose()


def sales_order(session, *, sku="SKU-1", quantity="2"):
    qty=Decimal(quantity); price=Decimal("10"); net=qty*price; tax=net*Decimal("0.05")
    quote=create_sales_quotation(session, customer_code="C-1", customer_name_snapshot="Customer One",
        location_code="MAIN", quotation_date=date.today(), valid_until=date.today()+timedelta(days=10),
        discount_amount=Decimal("0"), payment_terms=None, delivery_terms=None, notes=None,
        actor="maker", lines=[{"sku":sku,"product_name_snapshot":"Product One","quantity":qty,
        "uom":"Pieces","canonical_uom":"piece","factor_to_base_snapshot":Decimal("1"),
        "quantity_base":qty,"unit_price":price,"tax_rate":Decimal("5"),"net_amount":net,
        "tax_amount":tax,"gross_amount":net+tax}])
    quote=transition_sales_quotation(session, quote, expected_revision=1, action="submit", actor="maker")
    quote=transition_sales_quotation(session, quote, expected_revision=2, action="approve", actor="checker", note="Commercial review passed")
    quote=accept_sales_quotation(session, quote, expected_revision=3, actor="maker", acceptance_reference="Customer email")
    return convert_sales_quotation(session, quote, expected_revision=4, actor="maker")


def stock(session, quantity="10"):
    row=OperationalStockPosition(location_code="MAIN", sku="SKU-1", canonical_uom="piece",
        quantity_on_hand=Decimal(quantity), quantity_reserved=Decimal("0"), average_unit_cost=Decimal("4"),
        revision=1, source_batch_key="test", source_status="operational", availability_enabled=True)
    session.add(row); session.commit(); return row


def test_delivery_allocation_pick_dispatch_and_pod_make_order_invoice_eligible(session):
    order=sales_order(session); position=stock(session)
    delivery=allocate_sales_order(session, order, actor="warehouse", note="Allocate for accepted customer order")
    assert delivery.status == "allocated" and position.quantity_reserved == Decimal("2")
    assert allocate_sales_order(session, order, actor="warehouse", note="Retry") == delivery
    delivery=transition_delivery(session, delivery, expected_revision=1, action="pick",
        actor="picker", note="Picked and checked quantities")
    assert delivery.lines[0].picked_quantity_base == Decimal("2")
    delivery=transition_delivery(session, delivery, expected_revision=2, action="dispatch",
        actor="dispatcher", note="Loaded and released from warehouse", vehicle_number="TEST-01", driver_name="Test Driver")
    session.refresh(position)
    assert delivery.delivery_note_no.startswith("DN-")
    assert position.quantity_on_hand == Decimal("8") and position.quantity_reserved == Decimal("0")
    assert session.scalar(select(func.count(OperationalDeliveryStockMovement.id))) == 1
    assert session.scalar(select(OperationalDeliveryReservation.status)) == "consumed"
    delivery=transition_delivery(session, delivery, expected_revision=3, action="deliver",
        actor="pod-checker", note="Signed POD checked", received_by="Customer Receiver", pod_reference="POD-TEST-001")
    assert delivery.status == "delivered" and delivery.revision == 4
    assert delivery.lines[0].delivered_quantity_base == Decimal("2")
    assert session.scalar(select(func.count(OperationalDeliveryWorkflowEvent.id))) == 4
    assert session.scalar(select(func.count(OperationalJournalBatch.id))) == 0


def test_delivery_cancel_releases_stock_and_dispatch_cannot_be_cancelled(session):
    order=sales_order(session); position=stock(session)
    delivery=allocate_sales_order(session, order, actor="warehouse", note="Allocate test order")
    delivery=transition_delivery(session, delivery, expected_revision=1, action="pick",
        actor="picker", note="Picked test order")
    delivery=transition_delivery(session, delivery, expected_revision=2, action="cancel",
        actor="warehouse", note="Customer cancelled before dispatch")
    session.refresh(position)
    assert delivery.status == "cancelled" and position.quantity_reserved == Decimal("0")
    assert session.scalar(select(OperationalDeliveryReservation.status)) == "released"
    with pytest.raises(ValueError, match="not allowed"):
        transition_delivery(session, delivery, expected_revision=3, action="dispatch",
                            actor="dispatcher", note="Should fail")


def test_delivery_allocation_rejects_unavailable_stock(session):
    order=sales_order(session, quantity="3"); stock(session, quantity="2")
    with pytest.raises(ValueError, match="Insufficient available stock"):
        allocate_sales_order(session, order, actor="warehouse", note="Over allocation test")
    session.rollback()
    assert session.scalar(select(func.count(OperationalDeliveryReservation.id))) == 0
