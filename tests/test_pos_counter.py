from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from klen_clone.operational import OperationalBase, OperationalStockPosition
from klen_clone.operational_masters import OperationalProductMaster
from klen_clone.pos_counter import (
    OperationalPosSale, approve_close, create_till, open_shift,
    pos_workspace_payload, record_sale, submit_close,
)


def seeded_session():
    engine=create_engine("sqlite+pysqlite:///:memory:", future=True)
    OperationalBase.metadata.create_all(engine); session=Session(engine)
    session.add(OperationalProductMaster(product_key="P-1", sku="SKU-1", name="Test product",
        base_uom="piece", canonical_base_uom="piece", factor_to_base=1,
        purchase_price=Decimal("4"), selling_price=Decimal("10"), tax_rate=Decimal("5"),
        status="active", source_promoted=True, source_snapshot_name="test", source_checksum="a"*64,
        created_by="test", updated_by="test"))
    session.add(OperationalStockPosition(location_code="MAIN", sku="SKU-1", canonical_uom="piece",
        quantity_on_hand=Decimal("20"), quantity_reserved=Decimal("0"), average_unit_cost=Decimal("4"),
        availability_enabled=True, source_status="operational"))
    session.commit(); return session


def test_pos_counter_sale_and_independent_cash_close_are_non_posting():
    session=seeded_session()
    till=create_till(session, till_code="TILL-1", name="Main counter", location_code="MAIN", actor="admin")
    shift=open_shift(session, till_key=till.till_key, business_date=date(2026,9,21),
        opening_float=Decimal("100"), actor="cashier")
    sale=record_sale(session, shift_key=shift.shift_key, lines=[{"sku":"SKU-1","quantity":2}],
        payment_method="cash", amount_tendered=Decimal("25"), customer_name=None, actor="cashier")
    assert sale.total_amount == Decimal("21.00")
    assert sale.change_amount == Decimal("4.00")
    assert sale.posting_enabled is False
    position=session.scalar(select(OperationalStockPosition).where(OperationalStockPosition.sku=="SKU-1"))
    assert position.quantity_on_hand == Decimal("20")
    shift=submit_close(session, shift_key=shift.shift_key, expected_revision=2,
        counted_cash=Decimal("121"), note="Test counter cash counted", actor="cashier")
    with pytest.raises(PermissionError, match="Maker-checker"):
        approve_close(session, shift_key=shift.shift_key, expected_revision=3,
            note="Self approval must fail", actor="cashier")
    shift=approve_close(session, shift_key=shift.shift_key, expected_revision=3,
        note="Independent test close approved", actor="manager")
    assert shift.status == "closed" and shift.variance == Decimal("0.00")
    payload=pos_workspace_payload(session)
    assert payload["controls"] == {"tills":1,"open_shifts":0,"close_approvals":0,"sales":1,"posting_enabled":False}
    assert payload["boundary"]["stock_posting_performed"] is False


def test_pos_rejects_overselling_and_card_mismatch():
    session=seeded_session(); till=create_till(session,till_code="T2",name="Till 2",location_code="MAIN",actor="admin")
    shift=open_shift(session,till_key=till.till_key,business_date=date(2026,9,21),opening_float=0,actor="cashier")
    with pytest.raises(ValueError, match="Insufficient"):
        record_sale(session,shift_key=shift.shift_key,lines=[{"sku":"SKU-1","quantity":21}],
            payment_method="cash",amount_tendered=Decimal("500"),customer_name=None,actor="cashier")
    with pytest.raises(ValueError, match="Card payment"):
        record_sale(session,shift_key=shift.shift_key,lines=[{"sku":"SKU-1","quantity":1}],
            payment_method="card",amount_tendered=Decimal("11"),customer_name=None,actor="cashier")
    assert session.scalar(select(OperationalPosSale)) is None
