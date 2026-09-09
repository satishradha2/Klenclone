from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from klen_clone.goods_receipts import (
    OperationalGoodsReceiptWorkflowEvent,
    create_goods_receipt,
    goods_receipt_control_counts,
    rehearse_goods_receipt_posting,
    replace_goods_receipt,
    transition_goods_receipt,
)
from klen_clone.operational import OperationalAuditEvent, OperationalFiscalPeriod, initialize_operational_database, make_operational_engine


def receipt_session(tmp_path) -> Session:
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'goods-receipts.db'}")
    initialize_operational_database(engine)
    session = Session(engine)
    session.add(OperationalFiscalPeriod(period_key="2026-09", starts_on=date(2026, 9, 1),
                ends_on=date(2026, 9, 30), status="open", rehearsal_enabled=True,
                approval_reference="test", configured_by="controller"))
    session.commit()
    return session


def line(*, accepted="8", rejected="2", reason="Damaged cartons") -> dict:
    return {"sku": "SKU-1", "product_name_snapshot": "Product One",
            "ordered_quantity": Decimal("10"), "received_quantity": Decimal("10"),
            "accepted_quantity": Decimal(accepted), "rejected_quantity": Decimal(rejected),
            "uom": "Piece", "canonical_uom": "piece", "factor_to_base_snapshot": Decimal("1"),
            "unit_cost_snapshot": Decimal("7.65"), "batch_no": "B-202609",
            "expiry_date": date(2027, 9, 30), "rejection_reason": reason}


def create(session, lines=None):
    return create_goods_receipt(session, supplier_code="SUP-1", supplier_name_snapshot="Supplier One",
        location_code="SHJ", purchase_reference="PO-1", supplier_delivery_note="DN-1",
        received_on=date(2026, 9, 9), notes=None, actor="maker", lines=lines or [line()])


def test_partial_receipt_preserves_traceability_and_rehearses_only_accepted_stock(tmp_path):
    session = receipt_session(tmp_path)
    receipt = create(session)
    assert receipt.lines[0].accepted_quantity_base == 8
    assert receipt.lines[0].accepted_value == Decimal("61.20")
    assert receipt.lines[0].batch_no == "B-202609"
    assert receipt.lines[0].expiry_date == date(2027, 9, 30)
    receipt = transition_goods_receipt(session, receipt, expected_revision=1, action="submit", actor="maker")
    with pytest.raises(PermissionError, match="Maker-checker"):
        transition_goods_receipt(session, receipt, expected_revision=2, action="accept", actor="maker")
    session.rollback()
    receipt = transition_goods_receipt(session, receipt, expected_revision=2, action="accept", actor="approver")
    plan = rehearse_goods_receipt_posting(session, receipt, actor="approver")
    assert plan["posting_enabled"] is False
    assert plan["movements"][0]["quantity_base"] == 8
    assert plan["debit"] == plan["credit"] == Decimal("61.20")
    assert {entry["account"] for entry in plan["journal"]} == {"Inventory", "GRNI"}
    assert goods_receipt_control_counts(session) == {"receipts": 1, "accepted": 1, "posting_batches": 0}
    assert session.scalar(select(func.count(OperationalGoodsReceiptWorkflowEvent.id))) == 2
    assert session.scalar(select(func.count(OperationalAuditEvent.id))) == 4


def test_receipt_validation_requires_conservation_and_rejection_reason(tmp_path):
    session = receipt_session(tmp_path)
    with pytest.raises(ValueError, match="conserve quantity"):
        create(session, [line(accepted="7", rejected="2")])
    session.rollback()
    with pytest.raises(ValueError, match="rejection reason"):
        create(session, [line(reason=None)])


def test_draft_edit_revision_and_state_controls(tmp_path):
    session = receipt_session(tmp_path)
    receipt = create(session)
    receipt = replace_goods_receipt(session, receipt, expected_revision=1, supplier_code="SUP-1",
        supplier_name_snapshot="Supplier One", location_code="SHJ", purchase_reference="PO-2",
        supplier_delivery_note="DN-2", received_on=date(2026, 9, 9), notes="Inspected",
        actor="maker", lines=[line(accepted="10", rejected="0", reason=None)])
    assert receipt.revision == 2 and receipt.purchase_reference == "PO-2"
    with pytest.raises(ValueError, match="revision conflict"):
        replace_goods_receipt(session, receipt, expected_revision=1, supplier_code="SUP-1",
            supplier_name_snapshot="Supplier One", location_code="SHJ", purchase_reference=None,
            supplier_delivery_note=None, received_on=date(2026, 9, 9), notes=None,
            actor="maker", lines=[line()])
    session.rollback()
    receipt = transition_goods_receipt(session, receipt, expected_revision=2, action="submit", actor="maker")
    with pytest.raises(ValueError, match="Only draft-state"):
        replace_goods_receipt(session, receipt, expected_revision=3, supplier_code="SUP-1",
            supplier_name_snapshot="Supplier One", location_code="SHJ", purchase_reference=None,
            supplier_delivery_note=None, received_on=date(2026, 9, 9), notes=None,
            actor="maker", lines=[line()])


def test_full_rejection_and_closed_period_controls(tmp_path):
    session = receipt_session(tmp_path)
    receipt = create(session, [line(accepted="0", rejected="10")])
    receipt = transition_goods_receipt(session, receipt, expected_revision=1, action="submit", actor="maker")
    receipt = transition_goods_receipt(session, receipt, expected_revision=2, action="reject", actor="approver")
    assert receipt.status == "rejected"
    with pytest.raises(ValueError, match="Only an accepted"):
        rehearse_goods_receipt_posting(session, receipt, actor="approver")
    accepted = create(session, [line(accepted="10", rejected="0", reason=None)])
    accepted = transition_goods_receipt(session, accepted, expected_revision=1, action="submit", actor="maker")
    accepted = transition_goods_receipt(session, accepted, expected_revision=2, action="accept", actor="approver")
    session.scalar(select(OperationalFiscalPeriod)).status = "locked"
    session.commit()
    with pytest.raises(ValueError, match="open rehearsal-enabled"):
        rehearse_goods_receipt_posting(session, accepted, actor="approver")
