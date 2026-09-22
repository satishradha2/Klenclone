from datetime import date, timedelta
from decimal import Decimal

import pytest

from klen_clone.commercial_pricing import (
    approve_price_list, approve_promotion, assign_customer_price_group,
    create_customer_price_group, create_price_list, create_promotion,
    enforce_quotation_pricing,
)
from klen_clone.operational import initialize_operational_database, make_operational_engine, operational_session_factory


@pytest.fixture()
def session():
    engine = make_operational_engine("sqlite:///:memory:")
    initialize_operational_database(engine)
    with operational_session_factory(engine)() as value:
        yield value
    engine.dispose()


def line(price="10"):
    return {"sku": "SKU-1", "unit_price": Decimal(price), "net_amount": Decimal(price)}


def approved_list(session):
    create_customer_price_group(session, group_code="TRADE", name="Trade customers", actor="maker")
    assign_customer_price_group(session, customer_code="C-1", group_code="TRADE", actor="maker")
    row = create_price_list(session, name="Trade September", customer_group="TRADE", effective_from=date(2026, 9, 1),
        effective_to=date(2026, 9, 30), max_discount_percent=Decimal("5"), items=[{"sku": "SKU-1", "unit_price": "10"}], actor="maker")
    return approve_price_list(session, key=row.price_list_key, actor="checker")


def test_effective_price_list_and_discount_are_enforced(session):
    row = approved_list(session)
    decision = enforce_quotation_pricing(session, customer_code="C-1", quotation_date=date(2026, 9, 15), lines=[line()], discount_amount=Decimal("0.50"))
    assert decision["customer_group"] == "TRADE" and decision["price_list_key"] == row.price_list_key
    with pytest.raises(ValueError, match="does not match"):
        enforce_quotation_pricing(session, customer_code="C-1", quotation_date=date(2026, 9, 15), lines=[line("9")], discount_amount=Decimal("0"))
    with pytest.raises(ValueError, match="discount"):
        enforce_quotation_pricing(session, customer_code="C-1", quotation_date=date(2026, 9, 15), lines=[line()], discount_amount=Decimal("0.51"))
    with pytest.raises(ValueError, match="effective"):
        enforce_quotation_pricing(session, customer_code="C-1", quotation_date=date(2026, 10, 1), lines=[line()], discount_amount=Decimal("0"))


def test_price_list_and_promotion_require_independent_approval(session):
    approved_list(session)
    promotion = create_promotion(session, promotion_code="TRADE10", name="Trade offer", customer_group="TRADE", sku="SKU-1",
        discount_percent=Decimal("10"), effective_from=date(2026, 9, 1), effective_to=date(2026, 9, 30), actor="maker")
    with pytest.raises(PermissionError, match="Maker-checker"):
        approve_promotion(session, promotion_key=promotion.promotion_key, actor="maker")
    session.rollback()
    approve_promotion(session, promotion_key=promotion.promotion_key, actor="checker")
    decision = enforce_quotation_pricing(session, customer_code="C-1", quotation_date=date(2026, 9, 15), lines=[line()], discount_amount=Decimal("1"), promotion_code="TRADE10")
    assert decision["promotion_key"] == promotion.promotion_key


def test_overlapping_approved_price_lists_are_rejected(session):
    approved_list(session)
    replacement = create_price_list(session, name="Overlap", customer_group="TRADE", effective_from=date(2026, 9, 15),
        effective_to=date(2026, 10, 1), max_discount_percent=Decimal("0"), items=[{"sku": "SKU-1", "unit_price": "10"}], actor="new-maker")
    with pytest.raises(ValueError, match="overlapping"):
        approve_price_list(session, key=replacement.price_list_key, actor="checker")


def test_active_pricing_requires_every_quoted_customer_to_have_a_group(session):
    approved_list(session)
    with pytest.raises(ValueError, match="assigned to an active price group"):
        enforce_quotation_pricing(
            session, customer_code="C-UNASSIGNED", quotation_date=date(2026, 9, 15),
            lines=[line()], discount_amount=Decimal("0"))


def test_sku_promotion_limits_only_the_eligible_part_of_a_mixed_quote(session):
    create_customer_price_group(session, group_code="TRADE", name="Trade customers", actor="maker")
    assign_customer_price_group(session, customer_code="C-1", group_code="TRADE", actor="maker")
    price_list = create_price_list(
        session, name="Trade September", customer_group="TRADE",
        effective_from=date(2026, 9, 1), effective_to=date(2026, 9, 30),
        max_discount_percent=Decimal("5"),
        items=[{"sku": "SKU-1", "unit_price": "10"},
               {"sku": "SKU-2", "unit_price": "20"}], actor="maker")
    approve_price_list(session, key=price_list.price_list_key, actor="checker")
    promotion = create_promotion(
        session, promotion_code="SKU10", name="SKU one offer", customer_group="TRADE",
        sku="SKU-1", discount_percent=Decimal("10"), effective_from=date(2026, 9, 1),
        effective_to=date(2026, 9, 30), actor="maker")
    approve_promotion(session, promotion_key=promotion.promotion_key, actor="checker")
    mixed_lines = [line(), {"sku": "SKU-2", "unit_price": Decimal("20"),
                            "net_amount": Decimal("20")}]
    decision = enforce_quotation_pricing(
        session, customer_code="C-1", quotation_date=date(2026, 9, 15),
        lines=mixed_lines, discount_amount=Decimal("2.00"), promotion_code="SKU10")
    assert decision["max_discount_amount"] == Decimal("2.00")
    with pytest.raises(ValueError, match="approved limit of 2.00"):
        enforce_quotation_pricing(
            session, customer_code="C-1", quotation_date=date(2026, 9, 15),
            lines=mixed_lines, discount_amount=Decimal("2.01"), promotion_code="SKU10")


def test_sku_promotion_requires_its_product_on_the_quote(session):
    approved_list(session)
    promotion = create_promotion(
        session, promotion_code="OTHER10", name="Other SKU offer", customer_group="TRADE",
        sku="SKU-OTHER", discount_percent=Decimal("10"), effective_from=date(2026, 9, 1),
        effective_to=date(2026, 9, 30), actor="maker")
    with pytest.raises(ValueError, match="not present"):
        approve_promotion(session, promotion_key=promotion.promotion_key, actor="checker")
    session.rollback()


def test_approved_sku_promotion_requires_its_product_on_the_quote(session):
    create_customer_price_group(session, group_code="TRADE", name="Trade customers", actor="maker")
    assign_customer_price_group(session, customer_code="C-1", group_code="TRADE", actor="maker")
    price_list = create_price_list(
        session, name="Trade September", customer_group="TRADE",
        effective_from=date(2026, 9, 1), effective_to=date(2026, 9, 30),
        max_discount_percent=Decimal("5"),
        items=[{"sku": "SKU-1", "unit_price": "10"},
               {"sku": "SKU-OTHER", "unit_price": "10"}], actor="maker")
    approve_price_list(session, key=price_list.price_list_key, actor="checker")
    promotion = create_promotion(
        session, promotion_code="SKU10", name="SKU offer", customer_group="TRADE",
        sku="SKU-1", discount_percent=Decimal("10"), effective_from=date(2026, 9, 1),
        effective_to=date(2026, 9, 30), actor="maker")
    approve_promotion(session, promotion_key=promotion.promotion_key, actor="checker")
    with pytest.raises(ValueError, match="not on this quotation"):
        enforce_quotation_pricing(
            session, customer_code="C-1", quotation_date=date(2026, 9, 15),
            lines=[{"sku": "SKU-OTHER", "unit_price": Decimal("10"),
                    "net_amount": Decimal("10")}], discount_amount=Decimal("0"),
            promotion_code="SKU10")
