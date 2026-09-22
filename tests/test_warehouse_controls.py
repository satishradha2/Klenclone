from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from klen_clone.operational import OperationalStockPosition, initialize_operational_database, make_operational_engine
from klen_clone.operational_masters import OperationalProductMaster
from klen_clone.warehouse_controls import (
    OperationalWarehouseTask,
    create_cycle_count, create_product_recall, create_quarantine_hold, record_warehouse_scan,
    register_barcode, register_serial, release_quarantine_hold,
    register_product_uom, transition_cycle_count, transition_product_recall,
    transition_serial, transition_warehouse_task, warehouse_control_payload,
)


def add_product(session, sku="SKU-1"):
    session.add(OperationalProductMaster(
        product_key=f"P-{sku}", sku=sku, name="Test product", base_uom="piece",
        canonical_base_uom="piece", factor_to_base=1, purchase_price=2,
        selling_price=4, tax_rate=5, status="active", source_promoted=False,
        source_snapshot_name="test", source_checksum="a" * 64,
        created_by="test", updated_by="test"))


def test_cycle_count_and_quarantine_require_independent_decisions(tmp_path):
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'warehouse.db'}")
    initialize_operational_database(engine)
    with Session(engine) as session:
        session.add(OperationalStockPosition(location_code="MAIN", sku="SKU-1", canonical_uom="piece", quantity_on_hand=Decimal("10"), quantity_reserved=Decimal("0"), average_unit_cost=Decimal("2"), availability_enabled=True, source_status="test"))
        session.commit()
        count = create_cycle_count(session, location_code="MAIN", actor="maker", notes="Monthly count", lines=[{"sku": "SKU-1", "counted_quantity_base": "8"}])
        assert count.lines[0].expected_quantity_base == 10
        assert count.lines[0].counted_quantity_base == 8
        count = transition_cycle_count(session, count, action="submit", expected_revision=1, actor="maker")
        with pytest.raises(PermissionError):
            transition_cycle_count(session, count, action="approve", expected_revision=2, actor="maker")
        session.rollback()
        count = transition_cycle_count(session, count, action="approve", expected_revision=2, actor="approver")
        assert count.status == "approved"
        hold = create_quarantine_hold(session, location_code="MAIN", sku="SKU-1", quantity_base="3", reason="Damaged packaging", actor="maker")
        assert session.scalar(select(OperationalStockPosition).where(
            OperationalStockPosition.location_code == "MAIN", OperationalStockPosition.sku == "SKU-1")).quantity_reserved == 3
        with pytest.raises(PermissionError):
            release_quarantine_hold(session, hold, expected_revision=1, actor="maker", note="Not allowed")
        session.rollback()
        hold = release_quarantine_hold(session, hold, expected_revision=1, actor="approver", note="Inspection complete")
        assert hold.status == "released"
        position = session.scalar(select(OperationalStockPosition).where(
            OperationalStockPosition.location_code == "MAIN", OperationalStockPosition.sku == "SKU-1"))
        assert position.quantity_on_hand == 10
        assert position.quantity_reserved == 0


def test_barcode_and_serial_traceability_rejects_collisions_and_wrong_locations(tmp_path):
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'traceability.db'}")
    initialize_operational_database(engine)
    with Session(engine) as session:
        add_product(session)
        session.add_all([
            OperationalStockPosition(location_code="MAIN", sku="SKU-1", canonical_uom="piece",
                quantity_on_hand=Decimal("2"), quantity_reserved=Decimal("0"),
                average_unit_cost=Decimal("2"), availability_enabled=True, source_status="test"),
            OperationalStockPosition(location_code="SHJ", sku="SKU-1", canonical_uom="piece",
                quantity_on_hand=Decimal("1"), quantity_reserved=Decimal("0"),
                average_unit_cost=Decimal("2"), availability_enabled=True, source_status="test"),
        ])
        session.commit()
        barcode = register_barcode(session, barcode_value="629000000001", sku="SKU-1",
                                   location_code="MAIN", uom="piece", actor="controller")
        assert barcode.barcode_value == "629000000001"
        with pytest.raises(ValueError, match="immutable barcode"):
            register_barcode(session, barcode_value="629000000001", sku="SKU-1",
                             location_code="MAIN", uom="piece", actor="controller")
        session.rollback()
        with pytest.raises(ValueError, match="collides"):
            register_serial(session, serial_number="629000000001", sku="SKU-1",
                            location_code="MAIN", actor="controller")
        session.rollback()
        serial = register_serial(session, serial_number="SERIAL-0001", sku="SKU-1",
                                 location_code="MAIN", actor="controller")
        assert serial.status == "available"
        matched = record_warehouse_scan(session, scanned_value="SERIAL-0001",
                                        location_code="MAIN", actor="scanner")
        assert matched.outcome == "matched"
        wrong_location = record_warehouse_scan(session, scanned_value="SERIAL-0001",
                                               location_code="SHJ", actor="scanner")
        assert wrong_location.outcome == "rejected"
        unknown = record_warehouse_scan(session, scanned_value="UNKNOWN-0001",
                                        location_code="MAIN", actor="scanner")
        assert unknown.outcome == "rejected"
        serial = transition_serial(session, serial, action="quarantine", expected_revision=1,
                                   actor="quality-maker", note="Inspection required")
        blocked = record_warehouse_scan(session, scanned_value="SERIAL-0001",
                                        location_code="MAIN", actor="scanner")
        assert blocked.outcome == "blocked"
        with pytest.raises(PermissionError):
            transition_serial(session, serial, action="release", expected_revision=2,
                              actor="quality-maker", note="Self release blocked")
        session.rollback()
        serial = transition_serial(session, serial, action="release", expected_revision=2,
                                   actor="quality-approver", note="Inspection passed")
        assert serial.status == "available"
        scoped = warehouse_control_payload(session, allowed_locations=("MAIN",))
        assert len(scoped["barcodes"]) == 1
        assert len(scoped["serial_units"]) == 1
        assert len(scoped["recent_scans"]) == 3
        assert scoped["controls"]["blocked_scans"] == 2


def test_serial_registration_cannot_exceed_controlled_on_hand(tmp_path):
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'serial-capacity.db'}")
    initialize_operational_database(engine)
    with Session(engine) as session:
        session.add(OperationalStockPosition(location_code="MAIN", sku="SKU-1", canonical_uom="piece",
            quantity_on_hand=Decimal("1"), quantity_reserved=Decimal("0"),
            average_unit_cost=Decimal("2"), availability_enabled=True, source_status="test"))
        session.commit()
        register_serial(session, serial_number="SERIAL-0001", sku="SKU-1",
                        location_code="MAIN", actor="controller")
        with pytest.raises(ValueError, match="exceed controlled on-hand"):
            register_serial(session, serial_number="SERIAL-0002", sku="SKU-1",
                            location_code="MAIN", actor="controller")


def test_governed_uom_barcode_recall_and_task_execution(tmp_path):
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'recall.db'}")
    initialize_operational_database(engine)
    with Session(engine) as session:
        add_product(session)
        session.add(OperationalStockPosition(location_code="MAIN", sku="SKU-1", canonical_uom="piece",
            quantity_on_hand=Decimal("24"), quantity_reserved=Decimal("0"), average_unit_cost=Decimal("2"),
            availability_enabled=True, source_status="test"))
        session.commit()
        conversion = register_product_uom(session, sku="SKU-1", uom="carton", factor_to_base="12",
            pack_level="outer", allow_purchase=True, allow_sale=True,
            is_default_purchase=False, is_default_sale=False, actor="master-maker")
        barcode = register_barcode(session, barcode_value=None, sku="SKU-1", uom="carton",
            location_code="MAIN", actor="master-maker")
        assert len(barcode.barcode_value) == 13
        assert barcode.barcode_value.startswith("23")
        assert barcode.factor_to_base == 12
        assert conversion.barcode_value == barcode.barcode_value
        with pytest.raises(ValueError, match="not an approved conversion"):
            register_barcode(session, barcode_value=None, sku="SKU-1", uom="case",
                location_code="MAIN", actor="master-maker")
        session.rollback()
        recall = create_product_recall(session, location_code="MAIN", severity="high",
            reason="Supplier safety notification", actor="quality-maker",
            lines=[{"sku": "SKU-1", "quantity_base": "12", "identity_value": barcode.barcode_value}])
        recall = transition_product_recall(session, recall, action="submit", expected_revision=1,
            actor="quality-maker", note="Ready for independent activation")
        with pytest.raises(PermissionError):
            transition_product_recall(session, recall, action="activate", expected_revision=2,
                actor="quality-maker", note="Self activation")
        session.rollback()
        recall = transition_product_recall(session, recall, action="activate", expected_revision=2,
            actor="quality-approver", note="Recall notice verified")
        scan = record_warehouse_scan(session, scanned_value=barcode.barcode_value,
            location_code="MAIN", actor="scanner")
        assert scan.outcome == "blocked"
        payload = warehouse_control_payload(session, allowed_locations=("MAIN",))
        assert payload["controls"]["active_recalls"] == 1
        assert payload["controls"]["open_tasks"] == 1
        task = session.scalar(select(OperationalWarehouseTask))
        task = transition_warehouse_task(session, task, action="start", expected_revision=1, actor="picker")
        with pytest.raises(ValueError, match="Completion evidence"):
            transition_warehouse_task(session, task, action="complete", expected_revision=2, actor="picker", evidence="no")
        session.rollback()
        task = transition_warehouse_task(session, task, action="complete", expected_revision=2,
            actor="picker", evidence="Isolated in cage Q-01; scan trail retained")
        assert task.status == "completed"
