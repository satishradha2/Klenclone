from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from klen_clone.inventory_operations import (
    OperationalInventoryDocument,
    OperationalInventoryReservation,
    OperationalInventoryWorkflowEvent,
    create_inventory_document,
    inventory_control_counts,
    rehearse_inventory_posting,
    replace_inventory_document,
    transition_inventory_document,
)
from klen_clone.operational import (
    OperationalAuditEvent,
    OperationalFiscalPeriod,
    OperationalStockPosition,
    initialize_operational_database,
    make_operational_engine,
)


def inventory_session(tmp_path) -> Session:
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'inventory-operations.db'}")
    initialize_operational_database(engine)
    session = Session(engine)
    session.add_all([
        OperationalFiscalPeriod(
            period_key="2026-09", starts_on=date(2026, 9, 1), ends_on=date(2026, 9, 30),
            status="open", rehearsal_enabled=True, approval_reference="test",
            configured_by="controller",
        ),
        OperationalStockPosition(
            location_code="SHJ", sku="SKU-1", canonical_uom="piece",
            quantity_on_hand=Decimal("20"), quantity_reserved=Decimal("0"),
            average_unit_cost=Decimal("7.65"), availability_enabled=True,
            source_status="test_reconciled",
        ),
        OperationalStockPosition(
            location_code="DXB", sku="SKU-1", canonical_uom="piece",
            quantity_on_hand=Decimal("5"), quantity_reserved=Decimal("0"),
            average_unit_cost=Decimal("8.00"), availability_enabled=True,
            source_status="test_reconciled",
        ),
    ])
    session.commit()
    return session


def line(quantity="4", cost="1") -> dict:
    return {
        "sku": "SKU-1", "product_name_snapshot": "Product One",
        "quantity": Decimal(quantity), "uom": "Piece", "canonical_uom": "piece",
        "factor_to_base_snapshot": Decimal("1"), "unit_cost_snapshot": Decimal(cost),
    }


def test_transfer_workflow_reserves_costs_and_rehearses_balanced_movement(tmp_path):
    session = inventory_session(tmp_path)
    document = create_inventory_document(
        session, document_type="transfer", location_code="SHJ", destination_location_code="DXB",
        adjustment_direction=None, reason_code="branch_replenishment", notes=None,
        actor="maker", lines=[line()],
    )
    assert document.status == "draft" and document.posting_enabled is False
    assert document.lines[0].quantity_base == 4
    document = transition_inventory_document(
        session, document, expected_revision=1, action="submit", actor="maker"
    )
    assert document.status == "submitted" and document.revision == 2
    source = session.scalar(select(OperationalStockPosition).where(
        OperationalStockPosition.location_code == "SHJ"))
    assert source.quantity_reserved == 4
    assert document.lines[0].unit_cost_snapshot == Decimal("7.65")
    with pytest.raises(PermissionError, match="Maker-checker"):
        transition_inventory_document(
            session, document, expected_revision=2, action="approve", actor="maker"
        )
    session.rollback()
    document = transition_inventory_document(
        session, document, expected_revision=2, action="approve", actor="approver"
    )
    plan = rehearse_inventory_posting(session, document, actor="approver")
    assert plan["posting_enabled"] is False
    assert plan["quantity_delta"] == 0
    assert plan["value_delta"] == 0
    assert plan["journal"] == []
    assert [row["quantity_base"] for row in plan["movements"]] == [Decimal("-4"), Decimal("4")]
    assert [row["value_delta"] for row in plan["movements"]] == [Decimal("-30.60"), Decimal("30.60")]
    assert inventory_control_counts(session) == {
        "documents": 1, "active_reservations": 1, "posting_batches": 0,
    }
    assert session.scalar(select(func.count(OperationalInventoryWorkflowEvent.id))) == 2
    assert session.scalar(select(func.count(OperationalAuditEvent.id))) == 4
    session.close()


def test_outgoing_adjustment_releases_reservation_on_cancel(tmp_path):
    session = inventory_session(tmp_path)
    document = create_inventory_document(
        session, document_type="adjustment", location_code="SHJ", destination_location_code=None,
        adjustment_direction="decrease", reason_code="damage", notes="Damaged in handling",
        actor="maker", lines=[line(quantity="3")],
    )
    document = transition_inventory_document(
        session, document, expected_revision=1, action="submit", actor="maker"
    )
    assert session.scalar(select(OperationalStockPosition).where(
        OperationalStockPosition.location_code == "SHJ")).quantity_reserved == 3
    document = transition_inventory_document(
        session, document, expected_revision=2, action="cancel", actor="maker"
    )
    assert document.status == "cancelled"
    assert session.scalar(select(OperationalStockPosition).where(
        OperationalStockPosition.location_code == "SHJ")).quantity_reserved == 0
    assert session.scalar(select(OperationalInventoryReservation)).status == "released"
    session.close()


def test_adjustment_rehearsal_balances_inventory_variance_journal(tmp_path):
    session = inventory_session(tmp_path)
    document = create_inventory_document(
        session, document_type="adjustment", location_code="SHJ", destination_location_code=None,
        adjustment_direction="increase", reason_code="cycle_count", notes=None,
        actor="maker", lines=[line(quantity="2", cost="6.92")],
    )
    document = transition_inventory_document(
        session, document, expected_revision=1, action="submit", actor="maker"
    )
    document = transition_inventory_document(
        session, document, expected_revision=2, action="approve", actor="approver"
    )
    plan = rehearse_inventory_posting(session, document, actor="approver")
    assert plan["quantity_delta"] == 2
    assert plan["value_delta"] == Decimal("13.84")
    assert plan["debit"] == plan["credit"] == Decimal("13.84")
    assert {row["account"] for row in plan["journal"]} == {"Inventory", "Inventory Adjustment"}
    session.close()


def test_inventory_shape_and_availability_controls_fail_closed(tmp_path):
    session = inventory_session(tmp_path)
    with pytest.raises(ValueError, match="different source"):
        create_inventory_document(
            session, document_type="transfer", location_code="SHJ", destination_location_code="SHJ",
            adjustment_direction=None, reason_code="transfer", notes=None, actor="maker", lines=[line()],
        )
    document = create_inventory_document(
        session, document_type="adjustment", location_code="SHJ", destination_location_code=None,
        adjustment_direction="decrease", reason_code="damage", notes=None,
        actor="maker", lines=[line(quantity="21")],
    )
    with pytest.raises(ValueError, match="Insufficient available stock"):
        transition_inventory_document(
            session, document, expected_revision=1, action="submit", actor="maker"
        )
    session.rollback()
    assert session.scalar(select(func.count(OperationalInventoryReservation.id))) == 0
    session.close()


def test_inventory_draft_edit_replaces_lines_and_rejects_stale_or_submitted_changes(tmp_path):
    session = inventory_session(tmp_path)
    document = create_inventory_document(
        session, document_type="transfer", location_code="SHJ", destination_location_code="DXB",
        adjustment_direction=None, reason_code="branch_replenishment", notes=None,
        actor="maker", lines=[line(quantity="2")],
    )
    document = replace_inventory_document(
        session, document, expected_revision=1, document_type="adjustment",
        location_code="SHJ", destination_location_code=None, adjustment_direction="increase",
        reason_code="cycle_count", notes="Counted twice", actor="maker",
        lines=[line(quantity="3", cost="6.92")],
    )
    assert document.revision == 2
    assert document.document_type == "adjustment"
    assert document.lines[0].quantity_base == 3
    assert document.lines[0].value_snapshot == Decimal("20.76")
    with pytest.raises(ValueError, match="revision conflict"):
        replace_inventory_document(
            session, document, expected_revision=1, document_type="adjustment",
            location_code="SHJ", destination_location_code=None, adjustment_direction="increase",
            reason_code="cycle_count", notes=None, actor="maker", lines=[line()],
        )
    session.rollback()
    document = transition_inventory_document(
        session, document, expected_revision=2, action="submit", actor="maker"
    )
    with pytest.raises(ValueError, match="Only draft-state"):
        replace_inventory_document(
            session, document, expected_revision=3, document_type="adjustment",
            location_code="SHJ", destination_location_code=None, adjustment_direction="increase",
            reason_code="cycle_count", notes=None, actor="maker", lines=[line()],
        )
    session.close()
