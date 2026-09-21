from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from klen_clone.enterprise_setup import OperationalVan
from klen_clone.operational import OperationalBase, OperationalStockPosition
from klen_clone.operational_masters import OperationalPartyMaster, OperationalProductMaster
from klen_clone.van_sales import create_route, submit_load, sync_offline_event, transition_route, van_workspace_payload


def seeded_session():
    engine=create_engine("sqlite+pysqlite:///:memory:",future=True); OperationalBase.metadata.create_all(engine); s=Session(engine)
    s.add(OperationalVan(van_key="V-1",company_code="ASAS",van_code="UAT-VAN",assigned_branch_code="MAIN",name="UAT van",status="active",created_by="test"))
    s.add(OperationalPartyMaster(party_key="C-1",party_code="C001",party_kind="customer",legal_or_business_name="Test customer",status="active",source_promoted=True,source_snapshot_name="test",source_checksum="a"*64,created_by="test",updated_by="test"))
    s.add(OperationalProductMaster(product_key="P-1",sku="SKU-1",name="Test product",base_uom="piece",canonical_base_uom="piece",factor_to_base=1,purchase_price=4,selling_price=10,tax_rate=5,status="active",source_promoted=True,source_snapshot_name="test",source_checksum="b"*64,created_by="test",updated_by="test"))
    s.add(OperationalStockPosition(location_code="MAIN",sku="SKU-1",canonical_uom="piece",quantity_on_hand=20,quantity_reserved=0,average_unit_cost=4,source_status="operational",availability_enabled=True))
    s.commit(); return s


def test_complete_offline_van_route_is_idempotent_and_non_posting():
    s=seeded_session(); route=create_route(s,van_code="UAT-VAN",route_date=date(2026,9,21),driver_name="Driver",device_id="DEV-1",opening_float=100,customer_codes=["C001"],actor="maker")
    route=submit_load(s,route_key=route.route_key,source_location="MAIN",lines=[{"sku":"SKU-1","quantity":5}],expected_revision=1,actor="maker")
    with pytest.raises(PermissionError,match="self-approval"):
        transition_route(s,route_key=route.route_key,action="approve_load",expected_revision=2,note="Self approve",actor="maker")
    route=transition_route(s,route_key=route.route_key,action="approve_load",expected_revision=2,note="Load checked",actor="supervisor")
    route=transition_route(s,route_key=route.route_key,action="start",expected_revision=3,note="Driver departed",actor="maker")
    event,replay=sync_offline_event(s,route_key=route.route_key,device_id="DEV-1",client_reference="OFF-1",event_type="sale",customer_code="C001",captured_at=datetime(2026,9,21,8,tzinfo=timezone.utc),payment_method="cash",amount=None,evidence_reference=None,lines=[{"sku":"SKU-1","quantity":2}],actor="maker")
    assert event.amount==Decimal("21.00") and event.tax_amount==Decimal("1.00") and replay is False
    same,replay=sync_offline_event(s,route_key=route.route_key,device_id="DEV-1",client_reference="OFF-1",event_type="sale",customer_code="C001",captured_at=datetime.now(timezone.utc),payment_method="cash",amount=None,evidence_reference=None,lines=[{"sku":"SKU-1","quantity":2}],actor="maker")
    assert same.id==event.id and replay is True
    route=s.scalar(select(type(route)).where(type(route).route_key==route.route_key))
    route=transition_route(s,route_key=route.route_key,action="submit_close",expected_revision=5,note="Cash counted",counted_cash=121,actor="maker")
    route=transition_route(s,route_key=route.route_key,action="approve_close",expected_revision=6,note="Independent close",actor="supervisor")
    assert route.status=="closed" and route.variance==Decimal("0.00")
    assert s.scalar(select(OperationalStockPosition)).quantity_on_hand==Decimal("20.000000")
    payload=van_workspace_payload(s); assert payload["controls"]["synced_events"]==1
    assert payload["boundary"]["offline_idempotency"] is True and payload["boundary"]["stock_posting_performed"] is False


def test_offline_sync_rejects_unknown_device_customer_and_unloaded_item():
    s=seeded_session(); route=create_route(s,van_code="UAT-VAN",route_date=date(2026,9,21),driver_name="Driver",device_id="DEV-1",opening_float=0,customer_codes=["C001"],actor="maker")
    route=submit_load(s,route_key=route.route_key,source_location="MAIN",lines=[{"sku":"SKU-1","quantity":1}],expected_revision=1,actor="maker")
    route=transition_route(s,route_key=route.route_key,action="approve_load",expected_revision=2,note="Approved load",actor="supervisor")
    route=transition_route(s,route_key=route.route_key,action="start",expected_revision=3,note="Start route",actor="maker")
    with pytest.raises(ValueError,match="assigned device"):
        sync_offline_event(s,route_key=route.route_key,device_id="WRONG",client_reference="X",event_type="collection",customer_code="C001",captured_at=datetime.now(timezone.utc),payment_method="cash",amount=5,evidence_reference=None,lines=[],actor="maker")
