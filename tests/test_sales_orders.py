from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from klen_clone.operational import (
    OperationalAuditEvent, OperationalJournalBatch, OperationalStockReservation,
    initialize_operational_database, make_operational_engine, operational_session_factory,
)
from klen_clone.sales_orders import (
    OperationalSalesOrder, OperationalSalesQuotationWorkflowEvent,
    accept_sales_quotation, convert_sales_quotation, create_sales_quotation,
    replace_sales_quotation, transition_sales_quotation,
)


def line(sku="SKU-1", quantity="2", price="10"):
    quantity = Decimal(quantity); price = Decimal(price)
    net = quantity * price; tax = (net * Decimal("0.05")).quantize(Decimal("0.01"))
    return {"sku": sku, "product_name_snapshot": f"Product {sku}", "quantity": quantity,
            "uom": "Pieces", "canonical_uom": "piece",
            "factor_to_base_snapshot": Decimal("1"), "quantity_base": quantity,
            "unit_price": price, "tax_rate": Decimal("5"), "net_amount": net,
            "tax_amount": tax, "gross_amount": net + tax}


@pytest.fixture()
def session():
    engine = make_operational_engine("sqlite:///:memory:")
    initialize_operational_database(engine)
    with operational_session_factory(engine)() as value:
        yield value
    engine.dispose()


def make_quote(session, *, quotation_date=None, valid_until=None, actor="maker"):
    quotation_date = quotation_date or date.today()
    valid_until = valid_until or quotation_date + timedelta(days=30)
    return create_sales_quotation(session, customer_code="C-1", customer_name_snapshot="Customer One",
        location_code="MAIN", quotation_date=quotation_date, valid_until=valid_until,
        discount_amount=Decimal("1"), payment_terms="30 days", delivery_terms="Ex works",
        notes="Test-data commercial offer", actor=actor, lines=[line()])


def test_sales_quotation_requires_unique_products_and_valid_dates(session):
    with pytest.raises(ValueError, match="only once"):
        create_sales_quotation(session, customer_code="C-1", customer_name_snapshot="Customer One",
            location_code="MAIN", quotation_date=date.today(), valid_until=date.today(),
            discount_amount=Decimal("0"), payment_terms=None, delivery_terms=None, notes=None,
            actor="maker", lines=[line(), line()])
    session.rollback()
    with pytest.raises(ValueError, match="cannot be earlier"):
        make_quote(session, quotation_date=date.today(), valid_until=date.today()-timedelta(days=1))


def test_quotation_accepts_shared_master_preparation_cost_fields(session):
    prepared = line()
    prepared.update({"unit_cost_snapshot": Decimal("4.25"), "cost_amount": Decimal("8.50")})
    quote = create_sales_quotation(session, customer_code="C-1", customer_name_snapshot="Customer One",
        location_code="MAIN", quotation_date=date.today(), valid_until=date.today()+timedelta(days=7),
        discount_amount=Decimal("0"), payment_terms=None, delivery_terms=None, notes=None,
        actor="maker", lines=[prepared])
    assert quote.lines[0].sku == "SKU-1" and quote.total_amount == Decimal("21.00")


def test_revision_maker_checker_acceptance_and_idempotent_conversion(session):
    quote = make_quote(session)
    assert quote.status == "draft" and quote.total_amount == Decimal("20.00")
    quote = replace_sales_quotation(session, quote, expected_revision=1,
        customer_code="C-1", customer_name_snapshot="Customer One", location_code="MAIN",
        quotation_date=date.today(), valid_until=date.today()+timedelta(days=20),
        discount_amount=Decimal("0"), payment_terms="Cash", delivery_terms="Delivered",
        notes="Revised test quotation", actor="maker", lines=[line(quantity="3")])
    assert quote.revision == 2 and quote.total_amount == Decimal("31.50")
    quote = transition_sales_quotation(session, quote, expected_revision=2, action="submit", actor="maker")
    with pytest.raises(PermissionError, match="Maker-checker"):
        transition_sales_quotation(session, quote, expected_revision=3, action="approve",
                                   actor="maker", note="Self approval is prohibited")
    session.rollback(); quote = session.get(type(quote), quote.id)
    quote = transition_sales_quotation(session, quote, expected_revision=3, action="approve",
                                       actor="checker", note="Prices and terms reviewed")
    quote = accept_sales_quotation(session, quote, expected_revision=4, actor="maker",
                                   acceptance_reference="Customer email dated today")
    order = convert_sales_quotation(session, quote, expected_revision=5, actor="maker")
    repeated = convert_sales_quotation(session, quote, expected_revision=5, actor="maker")
    assert repeated.id == order.id
    assert order.status == "confirmed" and order.posting_enabled is False
    assert order.total_amount == quote.total_amount and order.lines[0].quantity_base == Decimal("3")
    assert session.scalar(select(func.count(OperationalSalesOrder.id))) == 1
    assert session.scalar(select(func.count(OperationalStockReservation.id))) == 0
    assert session.scalar(select(func.count(OperationalJournalBatch.id))) == 0
    assert session.scalar(select(func.count(OperationalSalesQuotationWorkflowEvent.id))) == 4
    assert session.scalar(select(func.count(OperationalAuditEvent.id)).where(
        OperationalAuditEvent.resource_key.in_((quote.quotation_key, order.order_key)))) >= 6


def test_expired_approved_quotation_cannot_be_accepted(session):
    quote = make_quote(session, quotation_date=date.today()-timedelta(days=10),
                       valid_until=date.today()-timedelta(days=1))
    quote = transition_sales_quotation(session, quote, expected_revision=1, action="submit", actor="maker")
    quote = transition_sales_quotation(session, quote, expected_revision=2, action="approve",
                                       actor="checker", note="Approved before checking expiry")
    with pytest.raises(ValueError, match="expired"):
        accept_sales_quotation(session, quote, expected_revision=3, actor="maker",
                               acceptance_reference="Late customer email")
