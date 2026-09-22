from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from klen_clone.operational import OperationalStockPosition, initialize_operational_database, make_operational_engine
from klen_clone.warehouse_controls import (
    create_cycle_count, create_quarantine_hold, record_warehouse_scan,
    register_barcode, register_serial, release_quarantine_hold,
    transition_cycle_count, transition_serial, warehouse_control_payload,
)


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
                                   location_code="MAIN", factor_to_base="1", actor="controller")
        assert barcode.barcode_value == "629000000001"
        with pytest.raises(ValueError, match="already assigned"):
            register_barcode(session, barcode_value="629000000001", sku="SKU-1",
                             location_code="MAIN", factor_to_base="1", actor="controller")
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
