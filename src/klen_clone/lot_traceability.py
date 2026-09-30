"""Receipt-to-customer lot provenance in the controlled operational ERP."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .customer_invoices import OperationalCustomerInvoice, OperationalCustomerInvoiceLine
from .delivery_fulfillment import OperationalDeliveryFulfillment, OperationalDeliveryFulfillmentLine
from .goods_receipts import OperationalGoodsReceipt, OperationalGoodsReceiptLine
from .operational import OperationalAuditEvent, OperationalBase, utc_now
from .product_creation import OperationalProductDetails
from .warehouse_controls import OperationalProductRecall, OperationalProductRecallLine, OperationalQuarantineHold


class OperationalReceiptLot(OperationalBase):
    __tablename__ = "operational_receipt_lots"
    __table_args__ = (
        UniqueConstraint("receipt_line_id", name="uq_receipt_lot_line"),
        CheckConstraint("quantity_base > 0", name="ck_receipt_lot_quantity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lot_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("operational_goods_receipts.id"), nullable=False, index=True)
    receipt_line_id: Mapped[int] = mapped_column(ForeignKey("operational_goods_receipt_lines.id"), nullable=False)
    supplier_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    batch_no: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalDeliveryLotAllocation(OperationalBase):
    __tablename__ = "operational_delivery_lot_allocations"
    __table_args__ = (
        UniqueConstraint("lot_id", "fulfillment_line_id", name="uq_delivery_lot_line"),
        CheckConstraint("quantity_base > 0", name="ck_delivery_lot_quantity"),
        CheckConstraint("status IN ('active','consumed','released')", name="ck_delivery_lot_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    allocation_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    lot_id: Mapped[int] = mapped_column(ForeignKey("operational_receipt_lots.id"), nullable=False, index=True)
    fulfillment_id: Mapped[int] = mapped_column(ForeignKey("operational_delivery_fulfillments.id"), nullable=False, index=True)
    fulfillment_line_id: Mapped[int] = mapped_column(ForeignKey("operational_delivery_fulfillment_lines.id"), nullable=False, index=True)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, index=True)
    assigned_by: Mapped[str] = mapped_column(String(200), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def product_requires_lot(session: Session, sku: str) -> tuple[bool, bool]:
    row = session.scalar(select(OperationalProductDetails).where(OperationalProductDetails.sku == sku))
    if not row:
        return False, False
    details = json.loads(row.payload_json)
    return bool(details.get("track_lots")), bool(details.get("track_expiry"))


def register_accepted_receipt_lots(session: Session, receipt: OperationalGoodsReceipt) -> None:
    """Record provenance only; receipt acceptance does not post warehouse stock."""
    for line in receipt.lines:
        if line.accepted_quantity_base <= 0:
            continue
        tracked, expiry_required = product_requires_lot(session, line.sku)
        batch = (line.batch_no or "").strip().upper()
        if tracked and not batch:
            raise ValueError(f"Lot-tracked product {line.sku} requires a batch number on receipt")
        if expiry_required and not line.expiry_date:
            raise ValueError(f"Expiry-tracked product {line.sku} requires an expiry date on receipt")
        if line.expiry_date and line.expiry_date < receipt.received_on:
            raise ValueError(f"Receipt lot for {line.sku} expired before receipt date")
        if not batch:
            continue
        if session.scalar(select(OperationalReceiptLot.id).where(OperationalReceiptLot.receipt_line_id == line.id)):
            continue
        session.add(OperationalReceiptLot(
            lot_key=str(uuid.uuid4()), receipt_id=receipt.id, receipt_line_id=line.id,
            supplier_code=receipt.supplier_code, location_code=receipt.location_code,
            sku=line.sku, batch_no=batch, expiry_date=line.expiry_date,
            quantity_base=line.accepted_quantity_base,
        ))


def _blocked_lot(session: Session, lot: OperationalReceiptLot) -> str | None:
    held = session.scalar(select(OperationalQuarantineHold.id).where(
        OperationalQuarantineHold.location_code == lot.location_code,
        OperationalQuarantineHold.sku == lot.sku,
        OperationalQuarantineHold.status == "held",
    ).limit(1))
    if held:
        return "quarantined stock"
    recalled = session.scalar(select(OperationalProductRecallLine.id).join(
        OperationalProductRecall, OperationalProductRecallLine.recall_id == OperationalProductRecall.id,
    ).where(
        OperationalProductRecall.status == "active",
        OperationalProductRecall.location_code == lot.location_code,
        OperationalProductRecallLine.sku == lot.sku,
        OperationalProductRecallLine.identity_value.in_(["", lot.lot_key.upper(), lot.batch_no]),
    ).limit(1))
    return "active recall" if recalled else None


def assign_delivery_lot(session: Session, fulfillment: OperationalDeliveryFulfillment, *,
                        line_no: int, lot_key: str, quantity_base: Decimal, actor: str) -> OperationalDeliveryLotAllocation | None:
    if fulfillment.status != "allocated":
        raise ValueError("Lot assignments can be changed only before picking")
    line = next((row for row in fulfillment.lines if row.line_no == line_no), None)
    lot = session.scalar(select(OperationalReceiptLot).where(OperationalReceiptLot.lot_key == lot_key).with_for_update())
    if not line or not lot or lot.sku != line.sku or lot.location_code != fulfillment.location_code:
        raise ValueError("Receipt lot does not match the delivery line and location")
    quantity = Decimal(str(quantity_base))
    if quantity < 0:
        raise ValueError("Lot quantity cannot be negative")
    if quantity > 0:
        if lot.expiry_date and lot.expiry_date < date.today():
            raise ValueError("Expired lot cannot be allocated")
        blocker = _blocked_lot(session, lot)
        if blocker:
            raise ValueError(f"Lot cannot be allocated: {blocker}")
    existing = session.scalar(select(OperationalDeliveryLotAllocation).where(
        OperationalDeliveryLotAllocation.lot_id == lot.id,
        OperationalDeliveryLotAllocation.fulfillment_line_id == line.id,
    ).with_for_update())
    used = session.scalar(select(func.coalesce(func.sum(OperationalDeliveryLotAllocation.quantity_base), 0)).where(
        OperationalDeliveryLotAllocation.lot_id == lot.id,
        OperationalDeliveryLotAllocation.status.in_(["active", "consumed"]),
        OperationalDeliveryLotAllocation.id != (existing.id if existing else -1),
    )) or Decimal("0")
    line_used = session.scalar(select(func.coalesce(func.sum(OperationalDeliveryLotAllocation.quantity_base), 0)).where(
        OperationalDeliveryLotAllocation.fulfillment_line_id == line.id,
        OperationalDeliveryLotAllocation.status == "active",
        OperationalDeliveryLotAllocation.id != (existing.id if existing else -1),
    )) or Decimal("0")
    if quantity > lot.quantity_base - used:
        raise ValueError("Lot allocation exceeds accepted receipt quantity")
    if quantity > line.allocated_quantity_base - line_used:
        raise ValueError("Lot allocation exceeds delivery line quantity")
    if existing and existing.status == "consumed":
        raise ValueError("A dispatched lot allocation cannot be changed")
    if quantity == 0:
        if existing and existing.status == "active":
            existing.status, existing.closed_at = "released", utc_now()
        session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="delivery.lot.released",
            actor=actor, resource_key=fulfillment.fulfillment_key, detail=f"Line {line_no}; lot {lot.lot_key}"))
        session.commit()
        return existing
    if not existing:
        existing = OperationalDeliveryLotAllocation(allocation_key=str(uuid.uuid4()),
            lot_id=lot.id, fulfillment_id=fulfillment.id, fulfillment_line_id=line.id,
            quantity_base=quantity, assigned_by=actor)
        session.add(existing)
    else:
        existing.quantity_base, existing.status = quantity, "active"
        existing.assigned_by, existing.assigned_at, existing.closed_at = actor, utc_now(), None
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="delivery.lot.assigned",
        actor=actor, resource_key=fulfillment.fulfillment_key,
        detail=f"Line {line_no}; lot {lot.lot_key}; {quantity} base units"))
    session.commit()
    return existing


def validate_delivery_lots(session: Session, fulfillment: OperationalDeliveryFulfillment) -> None:
    for line in fulfillment.lines:
        assignments = list(session.scalars(select(OperationalDeliveryLotAllocation).where(
            OperationalDeliveryLotAllocation.fulfillment_line_id == line.id,
            OperationalDeliveryLotAllocation.status == "active",
        )))
        tracked, _ = product_requires_lot(session, line.sku)
        if not tracked and not assignments:
            continue
        if sum((row.quantity_base for row in assignments), Decimal("0")) != line.allocated_quantity_base:
            raise ValueError(f"Delivery line {line.line_no} requires complete lot allocation before picking or dispatch")
        for assignment in assignments:
            lot = session.get(OperationalReceiptLot, assignment.lot_id)
            if lot.expiry_date and lot.expiry_date < date.today():
                raise ValueError(f"Delivery line {line.line_no} contains an expired lot")
            blocker = _blocked_lot(session, lot)
            if blocker:
                raise ValueError(f"Delivery line {line.line_no} contains {blocker}")


def close_delivery_lots(session: Session, fulfillment: OperationalDeliveryFulfillment, action: str) -> None:
    rows = session.scalars(select(OperationalDeliveryLotAllocation).where(
        OperationalDeliveryLotAllocation.fulfillment_id == fulfillment.id,
        OperationalDeliveryLotAllocation.status == "active",
    )).all()
    for row in rows:
        row.status = "consumed" if action == "dispatch" else "released"
        row.closed_at = utc_now()


def delivery_lot_payload(session: Session, fulfillment: OperationalDeliveryFulfillment) -> dict:
    rows = session.execute(select(OperationalDeliveryLotAllocation, OperationalReceiptLot).join(
        OperationalReceiptLot, OperationalDeliveryLotAllocation.lot_id == OperationalReceiptLot.id,
    ).where(OperationalDeliveryLotAllocation.fulfillment_id == fulfillment.id)).all()
    assignments = [{"line_no": next(line.line_no for line in fulfillment.lines if line.id == allocation.fulfillment_line_id),
                    "lot_key": lot.lot_key, "batch_no": lot.batch_no,
                    "quantity_base": allocation.quantity_base, "status": allocation.status,
                    "receipt_line_id": lot.receipt_line_id}
                   for allocation, lot in rows]
    skus = {line.sku for line in fulfillment.lines}
    candidates = session.scalars(select(OperationalReceiptLot).where(
        OperationalReceiptLot.location_code == fulfillment.location_code,
        OperationalReceiptLot.sku.in_(skus),
    ).order_by(OperationalReceiptLot.created_at.desc())).all()
    return {"assignments": assignments,
            "available_lots": [{"lot_key": lot.lot_key, "sku": lot.sku, "batch_no": lot.batch_no,
                                "expiry_date": lot.expiry_date, "quantity_base": lot.quantity_base,
                                "receipt_no": session.get(OperationalGoodsReceipt, lot.receipt_id).receipt_no,
                                "blocked": _blocked_lot(session, lot)} for lot in candidates]}


def trace_lot(session: Session, lot: OperationalReceiptLot) -> dict:
    receipt = session.get(OperationalGoodsReceipt, lot.receipt_id)
    allocations = session.execute(select(OperationalDeliveryLotAllocation, OperationalDeliveryFulfillment).join(
        OperationalDeliveryFulfillment,
        OperationalDeliveryLotAllocation.fulfillment_id == OperationalDeliveryFulfillment.id,
    ).where(OperationalDeliveryLotAllocation.lot_id == lot.id)).all()
    chain = []
    for allocation, fulfillment in allocations:
        order = fulfillment.sales_order
        invoice = session.scalar(select(OperationalCustomerInvoice).where(
            OperationalCustomerInvoice.fulfillment_id == fulfillment.id))
        invoice_line = session.scalar(select(OperationalCustomerInvoiceLine.id).where(
            OperationalCustomerInvoiceLine.invoice_id == invoice.id,
            OperationalCustomerInvoiceLine.delivery_line_id == allocation.fulfillment_line_id,
        )) if invoice else None
        chain.append({"allocation_status": allocation.status, "quantity_base": allocation.quantity_base,
                      "fulfillment_key": fulfillment.fulfillment_key,
                      "delivery_note_no": fulfillment.delivery_note_no,
                      "delivery_status": fulfillment.status, "sales_order_no": order.order_no,
                      "customer_code": order.customer_code, "customer_name": order.customer_name_snapshot,
                      "invoice_no": invoice.invoice_no if invoice_line else None,
                      "invoice_status": invoice.status if invoice_line else None})
    return {"lot_key": lot.lot_key, "sku": lot.sku, "batch_no": lot.batch_no,
            "expiry_date": lot.expiry_date, "location_code": lot.location_code,
            "quantity_base": lot.quantity_base, "supplier_code": lot.supplier_code,
            "supplier_name": receipt.supplier_name_snapshot, "receipt_no": receipt.receipt_no,
            "receipt_status": receipt.status, "blocked": _blocked_lot(session, lot),
            "downstream": chain}
