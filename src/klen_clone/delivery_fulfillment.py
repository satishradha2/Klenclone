from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .operational import OperationalAuditEvent, OperationalBase, OperationalStockPosition, utc_now
from .sales_orders import OperationalSalesOrder


class OperationalDeliveryFulfillment(OperationalBase):
    __tablename__ = "operational_delivery_fulfillments"
    __table_args__ = (
        UniqueConstraint("sales_order_id", name="uq_delivery_fulfillment_order"),
        CheckConstraint("status IN ('allocated','picked','dispatched','delivered','cancelled')", name="ck_delivery_fulfillment_status"),
        CheckConstraint("posting_enabled = false", name="ck_delivery_fulfillment_no_accounting_posting"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fulfillment_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    fulfillment_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    sales_order_id: Mapped[int] = mapped_column(ForeignKey("operational_sales_orders.id"), nullable=False, index=True)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="allocated", index=True)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allocation_note: Mapped[str] = mapped_column(Text, nullable=False)
    delivery_note_no: Mapped[str | None] = mapped_column(String(40), unique=True, index=True)
    vehicle_number: Mapped[str | None] = mapped_column(String(100))
    driver_name: Mapped[str | None] = mapped_column(String(200))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatched_by: Mapped[str | None] = mapped_column(String(200))
    received_by: Mapped[str | None] = mapped_column(String(200))
    pod_reference: Mapped[str | None] = mapped_column(String(300))
    pod_note: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_by: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    state_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    state_changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    sales_order: Mapped[OperationalSalesOrder] = relationship()
    lines: Mapped[list["OperationalDeliveryFulfillmentLine"]] = relationship(
        back_populates="fulfillment", cascade="all, delete-orphan",
        order_by="OperationalDeliveryFulfillmentLine.line_no")


class OperationalDeliveryFulfillmentLine(OperationalBase):
    __tablename__ = "operational_delivery_fulfillment_lines"
    __table_args__ = (
        UniqueConstraint("fulfillment_id", "line_no", name="uq_delivery_fulfillment_line"),
        CheckConstraint("ordered_quantity_base > 0", name="ck_delivery_ordered_quantity"),
        CheckConstraint("allocated_quantity_base >= 0 AND picked_quantity_base >= 0 AND dispatched_quantity_base >= 0 AND delivered_quantity_base >= 0", name="ck_delivery_quantity_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fulfillment_id: Mapped[int] = mapped_column(ForeignKey("operational_delivery_fulfillments.id", ondelete="CASCADE"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    product_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    ordered_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    uom: Mapped[str] = mapped_column(String(80), nullable=False)
    canonical_uom: Mapped[str] = mapped_column(String(80), nullable=False)
    factor_to_base_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    ordered_quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    allocated_quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    picked_quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    dispatched_quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    delivered_quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    fulfillment: Mapped[OperationalDeliveryFulfillment] = relationship(back_populates="lines")


class OperationalDeliveryReservation(OperationalBase):
    __tablename__ = "operational_delivery_reservations"
    __table_args__ = (
        UniqueConstraint("fulfillment_line_id", name="uq_delivery_reservation_line"),
        CheckConstraint("quantity_base > 0", name="ck_delivery_reservation_quantity"),
        CheckConstraint("status IN ('active','released','consumed')", name="ck_delivery_reservation_status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reservation_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    fulfillment_id: Mapped[int] = mapped_column(ForeignKey("operational_delivery_fulfillments.id"), nullable=False, index=True)
    fulfillment_line_id: Mapped[int] = mapped_column(ForeignKey("operational_delivery_fulfillment_lines.id"), nullable=False)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OperationalDeliveryStockMovement(OperationalBase):
    __tablename__ = "operational_delivery_stock_movements"
    __table_args__ = (
        UniqueConstraint("fulfillment_line_id", name="uq_delivery_stock_movement_line"),
        CheckConstraint("quantity_base > 0", name="ck_delivery_stock_movement_quantity"),
        CheckConstraint("movement_type = 'dispatch_issue'", name="ck_delivery_stock_movement_type"),
        CheckConstraint("accounting_posting_enabled = false", name="ck_delivery_stock_no_accounting_posting"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    movement_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    fulfillment_id: Mapped[int] = mapped_column(ForeignKey("operational_delivery_fulfillments.id"), nullable=False, index=True)
    fulfillment_line_id: Mapped[int] = mapped_column(ForeignKey("operational_delivery_fulfillment_lines.id"), nullable=False)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    movement_type: Mapped[str] = mapped_column(String(30), nullable=False, default="dispatch_issue")
    accounting_posting_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)


class OperationalDeliveryWorkflowEvent(OperationalBase):
    __tablename__ = "operational_delivery_workflow_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    fulfillment_id: Mapped[int] = mapped_column(ForeignKey("operational_delivery_fulfillments.id"), nullable=False, index=True)
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


def _event(session: Session, fulfillment: OperationalDeliveryFulfillment, previous: str,
           target: str, actor: str, note: str | None) -> None:
    session.add(OperationalDeliveryWorkflowEvent(event_key=str(uuid.uuid4()), fulfillment_id=fulfillment.id,
        from_status=previous, to_status=target, actor=actor, note=(note or "").strip() or None))
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"delivery.{target}",
        actor=actor, resource_key=fulfillment.fulfillment_key,
        detail=f"{fulfillment.fulfillment_no}; {previous}->{target}; revision {fulfillment.revision}; accounting posting disabled"))


def allocate_sales_order(session: Session, order: OperationalSalesOrder, *, actor: str,
                         note: str) -> OperationalDeliveryFulfillment:
    existing = session.scalar(select(OperationalDeliveryFulfillment).where(
        OperationalDeliveryFulfillment.sales_order_id == order.id))
    if existing:
        return existing
    if order.status != "confirmed":
        raise ValueError("Only a confirmed sales order can be allocated")
    if not note.strip():
        raise ValueError("An allocation reason is required")
    key=str(uuid.uuid4())
    fulfillment=OperationalDeliveryFulfillment(fulfillment_key=key,
        fulfillment_no=f"DF-{key[:8].upper()}", sales_order_id=order.id,
        location_code=order.location_code, status="allocated", posting_enabled=False,
        allocation_note=note.strip(), created_by=actor, state_changed_by=actor)
    session.add(fulfillment); session.flush()
    for number, source in enumerate(order.lines, 1):
        position=session.scalar(select(OperationalStockPosition).where(
            OperationalStockPosition.location_code == order.location_code,
            OperationalStockPosition.sku == source.sku).with_for_update())
        if not position or not position.availability_enabled:
            raise ValueError(f"Approved stock is unavailable for {source.sku} at {order.location_code}")
        if position.canonical_uom.casefold() != source.canonical_uom.casefold():
            raise ValueError(f"Stock UOM mismatch for {source.sku} at {order.location_code}")
        available=position.quantity_on_hand-position.quantity_reserved
        if available < source.quantity_base:
            raise ValueError(f"Insufficient available stock for {source.sku} at {order.location_code}: required {source.quantity_base}, available {available}")
        line=OperationalDeliveryFulfillmentLine(line_no=number, sku=source.sku,
            product_name_snapshot=source.product_name_snapshot, ordered_quantity=source.quantity,
            uom=source.uom, canonical_uom=source.canonical_uom,
            factor_to_base_snapshot=source.factor_to_base_snapshot,
            ordered_quantity_base=source.quantity_base, allocated_quantity_base=source.quantity_base,
            picked_quantity_base=0, dispatched_quantity_base=0, delivered_quantity_base=0)
        fulfillment.lines.append(line); session.flush()
        position.quantity_reserved += source.quantity_base; position.revision += 1; position.updated_at=utc_now()
        session.add(OperationalDeliveryReservation(reservation_key=str(uuid.uuid4()),
            fulfillment_id=fulfillment.id, fulfillment_line_id=line.id,
            location_code=order.location_code, sku=source.sku,
            quantity_base=source.quantity_base, status="active"))
    _event(session, fulfillment, "confirmed_order", "allocated", actor, note)
    session.commit(); return fulfillment


def transition_delivery(session: Session, fulfillment: OperationalDeliveryFulfillment, *,
                        expected_revision: int, action: str, actor: str, note: str,
                        vehicle_number: str | None = None, driver_name: str | None = None,
                        received_by: str | None = None, pod_reference: str | None = None,
                        occurred_at: datetime | None = None) -> OperationalDeliveryFulfillment:
    if fulfillment.revision != expected_revision:
        raise ValueError(f"Delivery revision conflict; current revision is {fulfillment.revision}")
    transitions={("allocated","pick"):"picked", ("allocated","cancel"):"cancelled",
                 ("picked","cancel"):"cancelled", ("picked","dispatch"):"dispatched",
                 ("dispatched","deliver"):"delivered"}
    target=transitions.get((fulfillment.status, action))
    if not target:
        raise ValueError(f"Action {action} is not allowed from {fulfillment.status}")
    if not note.strip():
        raise ValueError("A delivery workflow reason is required")
    reservations=list(session.scalars(select(OperationalDeliveryReservation).where(
        OperationalDeliveryReservation.fulfillment_id == fulfillment.id,
        OperationalDeliveryReservation.status == "active").with_for_update()))
    previous=fulfillment.status
    if action == "pick":
        if len(reservations) != len(fulfillment.lines):
            raise RuntimeError("Active delivery reservations do not match the order lines")
        for line in fulfillment.lines: line.picked_quantity_base=line.allocated_quantity_base
    elif action == "cancel":
        for reservation in reservations:
            position=session.scalar(select(OperationalStockPosition).where(
                OperationalStockPosition.location_code == reservation.location_code,
                OperationalStockPosition.sku == reservation.sku).with_for_update())
            if not position or position.quantity_reserved < reservation.quantity_base:
                raise RuntimeError(f"Delivery reservation ledger mismatch for {reservation.sku}")
            position.quantity_reserved -= reservation.quantity_base; position.revision += 1; position.updated_at=utc_now()
            reservation.status="released"; reservation.closed_at=utc_now()
    elif action == "dispatch":
        if len(reservations) != len(fulfillment.lines):
            raise RuntimeError("Active delivery reservations do not match the picked lines")
        fulfillment.delivery_note_no=f"DN-{fulfillment.fulfillment_key[:8].upper()}"
        fulfillment.vehicle_number=(vehicle_number or "").strip() or None
        fulfillment.driver_name=(driver_name or "").strip() or None
        fulfillment.dispatched_at=occurred_at or utc_now(); fulfillment.dispatched_by=actor
        by_line={row.fulfillment_line_id: row for row in reservations}
        for line in fulfillment.lines:
            reservation=by_line[line.id]
            position=session.scalar(select(OperationalStockPosition).where(
                OperationalStockPosition.location_code == reservation.location_code,
                OperationalStockPosition.sku == reservation.sku).with_for_update())
            if not position or position.quantity_reserved < reservation.quantity_base or position.quantity_on_hand < reservation.quantity_base:
                raise RuntimeError(f"Delivery stock ledger mismatch for {reservation.sku}")
            position.quantity_on_hand -= reservation.quantity_base
            position.quantity_reserved -= reservation.quantity_base
            position.revision += 1; position.updated_at=utc_now()
            reservation.status="consumed"; reservation.closed_at=utc_now()
            line.dispatched_quantity_base=line.picked_quantity_base
            session.add(OperationalDeliveryStockMovement(movement_key=str(uuid.uuid4()),
                fulfillment_id=fulfillment.id, fulfillment_line_id=line.id,
                location_code=reservation.location_code, sku=reservation.sku,
                quantity_base=reservation.quantity_base, movement_type="dispatch_issue",
                accounting_posting_enabled=False, occurred_at=fulfillment.dispatched_at, actor=actor))
    elif action == "deliver":
        if not (received_by or "").strip() or not (pod_reference or "").strip():
            raise ValueError("Receiver name and proof-of-delivery reference are required")
        fulfillment.received_by=received_by.strip(); fulfillment.pod_reference=pod_reference.strip()
        fulfillment.pod_note=note.strip(); fulfillment.delivered_at=occurred_at or utc_now(); fulfillment.delivered_by=actor
        for line in fulfillment.lines: line.delivered_quantity_base=line.dispatched_quantity_base
    fulfillment.status=target; fulfillment.revision += 1
    fulfillment.state_changed_at=utc_now(); fulfillment.state_changed_by=actor
    _event(session, fulfillment, previous, target, actor, note)
    session.commit(); return fulfillment


def list_delivery_fulfillments(session: Session, *, allowed_locations: tuple[str, ...] = ("*",), limit: int = 100):
    query=select(OperationalDeliveryFulfillment)
    if "*" not in allowed_locations: query=query.where(OperationalDeliveryFulfillment.location_code.in_(allowed_locations))
    return list(session.scalars(query.order_by(OperationalDeliveryFulfillment.created_at.desc()).limit(limit)))


def delivery_control_counts(session: Session) -> dict:
    return {"fulfillments": session.scalar(select(func.count(OperationalDeliveryFulfillment.id))) or 0,
            "active_reservations": session.scalar(select(func.count(OperationalDeliveryReservation.id)).where(
                OperationalDeliveryReservation.status == "active")) or 0,
            "dispatched": session.scalar(select(func.count(OperationalDeliveryFulfillment.id)).where(
                OperationalDeliveryFulfillment.status == "dispatched")) or 0,
            "invoice_eligible": session.scalar(select(func.count(OperationalDeliveryFulfillment.id)).where(
                OperationalDeliveryFulfillment.status == "delivered")) or 0,
            "accounting_posting_enabled": False}
