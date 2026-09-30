"""Order/lot-bound approval for a foreign physical dispatch, not a VAT decision."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .cross_border_delivery_readiness import approved_readiness, order_fingerprint
from .delivery_fulfillment import OperationalDeliveryFulfillment
from .lot_traceability import OperationalDeliveryLotAllocation, validate_delivery_lots
from .operational import OperationalAuditEvent, OperationalBase, utc_now


class OperationalCrossBorderDispatchRelease(OperationalBase):
    __tablename__ = "operational_cross_border_dispatch_releases"
    __table_args__ = (CheckConstraint("status IN ('pending','approved','rejected','consumed')",
                                     name="ck_cross_border_dispatch_release_status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    fulfillment_id: Mapped[int] = mapped_column(ForeignKey("operational_delivery_fulfillments.id"), nullable=False, index=True)
    fulfillment_key: Mapped[str] = mapped_column(String(36), nullable=False)
    fulfillment_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    destination_country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    carrier_name: Mapped[str] = mapped_column(String(200), nullable=False)
    transport_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    packing_list_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    customs_declaration_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    destination_consignment_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    valid_until: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    consumed_by: Mapped[str | None] = mapped_column(String(200))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def fulfillment_fingerprint(session: Session, fulfillment: OperationalDeliveryFulfillment) -> str:
    order = fulfillment.sales_order
    lines = [[line.line_no, line.sku, line.allocated_quantity_base, line.picked_quantity_base]
             for line in fulfillment.lines]
    assignments = session.scalars(select(OperationalDeliveryLotAllocation).where(
        OperationalDeliveryLotAllocation.fulfillment_id == fulfillment.id,
        OperationalDeliveryLotAllocation.status == "active").order_by(
            OperationalDeliveryLotAllocation.fulfillment_line_id,
            OperationalDeliveryLotAllocation.lot_id)).all()
    lots = [[row.fulfillment_line_id, row.lot_id, row.quantity_base] for row in assignments]
    encoded = json.dumps([order_fingerprint(order), fulfillment.fulfillment_key,
        fulfillment.status, fulfillment.revision, lines, lots],
        default=lambda value: format(value.normalize(), "f") if isinstance(value, Decimal) else value,
        separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _check_picked(session: Session, fulfillment: OperationalDeliveryFulfillment) -> None:
    if fulfillment.status != "picked" or fulfillment.sales_order.customer_country_code in (None, "AE"):
        raise ValueError("A picked cross-border fulfillment is required")
    approved_readiness(session, fulfillment.sales_order)
    validate_delivery_lots(session, fulfillment)


def dispatch_release_payload(row: OperationalCrossBorderDispatchRelease) -> dict:
    return {"release_key": row.release_key, "fulfillment_key": row.fulfillment_key,
            "destination_country_code": row.destination_country_code,
            "carrier_name": row.carrier_name, "transport_reference": row.transport_reference,
            "packing_list_reference": row.packing_list_reference,
            "customs_declaration_reference": row.customs_declaration_reference,
            "destination_consignment_reference": row.destination_consignment_reference,
            "valid_until": row.valid_until, "status": row.status, "revision": row.revision,
            "created_by": row.created_by, "decided_by": row.decided_by,
            "decision_note": row.decision_note, "consumed_by": row.consumed_by,
            "physical_dispatch_only": True, "invoice_tax_final": False, "accounting_posting_enabled": False}


def prepare_dispatch_release(session: Session, fulfillment: OperationalDeliveryFulfillment, *,
                             carrier_name: str, transport_reference: str,
                             packing_list_reference: str, customs_declaration_reference: str,
                             destination_consignment_reference: str, valid_until: date,
                             actor: str) -> OperationalCrossBorderDispatchRelease:
    _check_picked(session, fulfillment)
    if valid_until < date.today():
        raise ValueError("Dispatch release expiry must be current")
    values = (carrier_name, transport_reference, packing_list_reference,
              customs_declaration_reference, destination_consignment_reference)
    if any(len(value.strip()) < 5 for value in values):
        raise ValueError("Carrier and all shipment/clearance references require five characters")
    active = session.scalar(select(OperationalCrossBorderDispatchRelease.id).where(
        OperationalCrossBorderDispatchRelease.fulfillment_id == fulfillment.id,
        ((OperationalCrossBorderDispatchRelease.status == "pending") |
         ((OperationalCrossBorderDispatchRelease.status == "approved") &
          (OperationalCrossBorderDispatchRelease.valid_until >= date.today())))))
    if active:
        raise ValueError("This fulfillment already has an active dispatch release")
    row = OperationalCrossBorderDispatchRelease(release_key=str(uuid.uuid4()),
        fulfillment_id=fulfillment.id, fulfillment_key=fulfillment.fulfillment_key,
        fulfillment_fingerprint=fulfillment_fingerprint(session, fulfillment),
        destination_country_code=fulfillment.sales_order.customer_country_code,
        carrier_name=carrier_name.strip(), transport_reference=transport_reference.strip(),
        packing_list_reference=packing_list_reference.strip(),
        customs_declaration_reference=customs_declaration_reference.strip(),
        destination_consignment_reference=destination_consignment_reference.strip(),
        valid_until=valid_until, created_by=actor)
    session.add(row)
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="trade_dispatch.prepared",
        actor=actor, resource_key=row.release_key,
        detail=f"{fulfillment.fulfillment_no}; physical dispatch only; invoice tax held"))
    session.commit()
    return row


def decide_dispatch_release(session: Session, row: OperationalCrossBorderDispatchRelease, *,
                            expected_revision: int, action: str, note: str,
                            actor: str) -> OperationalCrossBorderDispatchRelease:
    if row.status != "pending" or action not in ("approve", "reject"):
        raise ValueError("Only pending dispatch releases can be reviewed")
    if row.revision != expected_revision:
        raise ValueError(f"Dispatch release revision conflict; current revision is {row.revision}")
    fulfillment = session.get(OperationalDeliveryFulfillment, row.fulfillment_id)
    _check_picked(session, fulfillment)
    if row.fulfillment_fingerprint != fulfillment_fingerprint(session, fulfillment) or row.valid_until < date.today():
        raise ValueError("Dispatch release expired or the picked fulfillment changed")
    order = fulfillment.sales_order
    if actor in (row.created_by, fulfillment.created_by, order.created_by, order.quotation.created_by):
        raise PermissionError("Independent reviewer cannot be the shipment, fulfillment, order or quotation maker")
    if len(note.strip()) < 5:
        raise ValueError("An independent review note is required")
    row.status = "approved" if action == "approve" else "rejected"
    row.revision += 1; row.decided_by = actor; row.decided_at = utc_now(); row.decision_note = note.strip()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"trade_dispatch.{action}",
        actor=actor, resource_key=row.release_key,
        detail=f"{fulfillment.fulfillment_no}; physical dispatch only; no tax-final invoice"))
    session.commit()
    return row


def consume_dispatch_release(session: Session, fulfillment: OperationalDeliveryFulfillment, *, actor: str) -> None:
    _check_picked(session, fulfillment)
    row = session.scalar(select(OperationalCrossBorderDispatchRelease).where(
        OperationalCrossBorderDispatchRelease.fulfillment_id == fulfillment.id,
        OperationalCrossBorderDispatchRelease.status == "approved").order_by(
            OperationalCrossBorderDispatchRelease.created_at.desc()).with_for_update())
    if not row or row.valid_until < date.today() or row.fulfillment_fingerprint != fulfillment_fingerprint(session, fulfillment):
        raise ValueError("A current, independently approved shipment/clearance dispatch release is required")
    row.status = "consumed"; row.revision += 1; row.consumed_by = actor; row.consumed_at = utc_now()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="trade_dispatch.consumed",
        actor=actor, resource_key=row.release_key,
        detail=f"{fulfillment.fulfillment_no}; foreign stock issue authorized; invoice tax still held"))
