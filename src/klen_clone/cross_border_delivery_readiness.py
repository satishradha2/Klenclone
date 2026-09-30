"""Independent, order-bound readiness for foreign stock reservation and picking.

This does not authorize dispatch, export VAT treatment, invoicing or posting.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .cross_border_order_controls import OperationalCrossBorderOrderRelease
from .operational import OperationalAuditEvent, OperationalBase, utc_now
from .sales_orders import OperationalSalesOrder


class OperationalCrossBorderDeliveryReadiness(OperationalBase):
    __tablename__ = "operational_cross_border_delivery_readiness"
    __table_args__ = (CheckConstraint("status IN ('pending','approved','rejected')",
                                     name="ck_cross_border_delivery_readiness_status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    readiness_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    sales_order_id: Mapped[int] = mapped_column(ForeignKey("operational_sales_orders.id"), nullable=False, index=True)
    order_key: Mapped[str] = mapped_column(String(36), nullable=False)
    order_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    order_release_key: Mapped[str] = mapped_column(String(36), nullable=False)
    destination_country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    transport_plan: Mapped[str] = mapped_column(Text, nullable=False)
    customs_evidence_plan: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    valid_until: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)


def order_fingerprint(order: OperationalSalesOrder) -> str:
    fields = [order.order_key, order.order_release_key, order.status, order.customer_code,
              order.customer_country_code, order.location_code, order.currency_code,
              order.aed_total_snapshot, order.total_amount, order.requested_delivery_date]
    lines = [[line.line_no, line.sku, line.quantity_base, line.canonical_uom]
             for line in order.lines]
    encoded = json.dumps([fields, lines], default=lambda value: (
        format(value.normalize(), "f") if isinstance(value, Decimal) else value.isoformat()
    ), separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _check_order(session: Session, order: OperationalSalesOrder) -> OperationalCrossBorderOrderRelease:
    if order.status != "confirmed" or order.customer_country_code in (None, "AE"):
        raise ValueError("A confirmed cross-border sales order is required")
    release = session.scalar(select(OperationalCrossBorderOrderRelease).where(
        OperationalCrossBorderOrderRelease.release_key == order.order_release_key))
    if not release or release.status != "consumed" or release.sales_order_key != order.order_key:
        raise ValueError("The order must have a consumed, approved cross-border order release")
    if release.customer_country_code != order.customer_country_code or release.currency_code != order.currency_code:
        raise ValueError("Order and approved trade release no longer match")
    return release


def readiness_payload(row: OperationalCrossBorderDeliveryReadiness) -> dict:
    return {"readiness_key": row.readiness_key, "order_key": row.order_key,
            "destination_country_code": row.destination_country_code,
            "transport_plan": row.transport_plan, "customs_evidence_plan": row.customs_evidence_plan,
            "evidence_reference": row.evidence_reference, "valid_until": row.valid_until,
            "status": row.status, "revision": row.revision, "created_by": row.created_by,
            "decided_by": row.decided_by, "decision_note": row.decision_note,
            "allocation_and_pick_only": True, "dispatch_released": False,
            "invoice_tax_final": False, "posting_enabled": False}


def prepare_readiness(session: Session, order: OperationalSalesOrder, *, transport_plan: str,
                      customs_evidence_plan: str, evidence_reference: str,
                      valid_until: date, actor: str) -> OperationalCrossBorderDeliveryReadiness:
    release = _check_order(session, order)
    if valid_until < date.today():
        raise ValueError("Readiness expiry must be current")
    if any(len(value.strip()) < 5 for value in (transport_plan, customs_evidence_plan, evidence_reference)):
        raise ValueError("Transport plan, customs evidence plan and reference require five characters")
    active = session.scalar(select(OperationalCrossBorderDeliveryReadiness.id).where(
        OperationalCrossBorderDeliveryReadiness.sales_order_id == order.id,
        ((OperationalCrossBorderDeliveryReadiness.status == "pending") |
         ((OperationalCrossBorderDeliveryReadiness.status == "approved") &
          (OperationalCrossBorderDeliveryReadiness.valid_until >= date.today())))))
    if active:
        raise ValueError("This order already has active delivery readiness")
    row = OperationalCrossBorderDeliveryReadiness(readiness_key=str(uuid.uuid4()),
        sales_order_id=order.id, order_key=order.order_key, order_fingerprint=order_fingerprint(order),
        order_release_key=release.release_key, destination_country_code=order.customer_country_code,
        transport_plan=transport_plan.strip(), customs_evidence_plan=customs_evidence_plan.strip(),
        evidence_reference=evidence_reference.strip(), valid_until=valid_until, created_by=actor)
    session.add(row)
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="trade_delivery.prepared",
        actor=actor, resource_key=row.readiness_key,
        detail=f"{order.order_no}; allocation and pick only; dispatch and invoice held"))
    session.commit()
    return row


def decide_readiness(session: Session, row: OperationalCrossBorderDeliveryReadiness, *,
                     expected_revision: int, action: str, note: str,
                     actor: str) -> OperationalCrossBorderDeliveryReadiness:
    if row.status != "pending" or action not in ("approve", "reject"):
        raise ValueError("Only pending readiness may be reviewed")
    if row.revision != expected_revision:
        raise ValueError(f"Readiness revision conflict; current revision is {row.revision}")
    order = session.get(OperationalSalesOrder, row.sales_order_id)
    _check_order(session, order)
    if order_fingerprint(order) != row.order_fingerprint or row.valid_until < date.today():
        raise ValueError("Readiness is expired or the order changed")
    if actor in (row.created_by, order.created_by, order.quotation.created_by):
        raise PermissionError("Independent reviewer cannot be the readiness, order or quotation maker")
    if len(note.strip()) < 5:
        raise ValueError("An independent review note is required")
    row.status = "approved" if action == "approve" else "rejected"
    row.revision += 1; row.decided_by = actor; row.decided_at = utc_now(); row.decision_note = note.strip()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"trade_delivery.{action}",
        actor=actor, resource_key=row.readiness_key,
        detail=f"{order.order_no}; stock reservation and pick only; no dispatch or invoice"))
    session.commit()
    return row


def approved_readiness(session: Session, order: OperationalSalesOrder) -> OperationalCrossBorderDeliveryReadiness:
    _check_order(session, order)
    row = session.scalar(select(OperationalCrossBorderDeliveryReadiness).where(
        OperationalCrossBorderDeliveryReadiness.sales_order_id == order.id,
        OperationalCrossBorderDeliveryReadiness.status == "approved").order_by(
            OperationalCrossBorderDeliveryReadiness.created_at.desc()).with_for_update())
    if not row or row.valid_until < date.today() or row.order_fingerprint != order_fingerprint(order):
        raise ValueError("A current, independently approved delivery readiness is required")
    return row
