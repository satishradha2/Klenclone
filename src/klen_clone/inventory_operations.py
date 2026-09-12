from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .operational import (
    MONEY,
    OperationalAuditEvent,
    OperationalBase,
    OperationalFiscalPeriod,
    OperationalStockPosition,
    utc_now,
)


class OperationalInventoryDocument(OperationalBase):
    __tablename__ = "operational_inventory_documents"
    __table_args__ = (
        CheckConstraint("document_type IN ('transfer','adjustment')", name="ck_inventory_document_type"),
        CheckConstraint(
            "status IN ('draft','submitted','approved','cancelled','posted','reversed')",
            name="ck_inventory_document_status",
        ),
        CheckConstraint("posting_enabled = false", name="ck_inventory_document_no_posting"),
        CheckConstraint(
            "(document_type = 'transfer' AND destination_location_code IS NOT NULL "
            "AND destination_location_code <> location_code AND adjustment_direction IS NULL) OR "
            "(document_type = 'adjustment' AND destination_location_code IS NULL "
            "AND adjustment_direction IN ('increase','decrease'))",
            name="ck_inventory_document_shape",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    document_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    document_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    destination_location_code: Mapped[str | None] = mapped_column(String(80), index=True)
    adjustment_direction: Mapped[str | None] = mapped_column(String(20))
    reason_code: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False, index=True)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    state_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    state_changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    lines: Mapped[list["OperationalInventoryDocumentLine"]] = relationship(
        back_populates="document", cascade="all, delete-orphan",
        order_by="OperationalInventoryDocumentLine.line_no",
    )


class OperationalInventoryDocumentLine(OperationalBase):
    __tablename__ = "operational_inventory_document_lines"
    __table_args__ = (
        UniqueConstraint("document_id", "line_no", name="uq_inventory_document_line"),
        CheckConstraint("quantity > 0", name="ck_inventory_document_line_quantity"),
        CheckConstraint("quantity_base > 0", name="ck_inventory_document_line_base_quantity"),
        CheckConstraint("factor_to_base_snapshot > 0", name="ck_inventory_document_line_factor"),
        CheckConstraint("unit_cost_snapshot >= 0", name="ck_inventory_document_line_cost"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("operational_inventory_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    product_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    uom: Mapped[str] = mapped_column(String(80), nullable=False)
    canonical_uom: Mapped[str] = mapped_column(String(80), nullable=False)
    factor_to_base_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_cost_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    value_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    document: Mapped[OperationalInventoryDocument] = relationship(back_populates="lines")


class OperationalInventoryReservation(OperationalBase):
    __tablename__ = "operational_inventory_reservations"
    __table_args__ = (
        UniqueConstraint("document_line_id", name="uq_inventory_reservation_line"),
        CheckConstraint("quantity_base > 0", name="ck_inventory_reservation_quantity"),
        CheckConstraint("status IN ('active','released','consumed')", name="ck_inventory_reservation_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reservation_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    document_id: Mapped[int] = mapped_column(ForeignKey("operational_inventory_documents.id"), nullable=False, index=True)
    document_line_id: Mapped[int] = mapped_column(ForeignKey("operational_inventory_document_lines.id"), nullable=False)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OperationalInventoryWorkflowEvent(OperationalBase):
    __tablename__ = "operational_inventory_workflow_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    document_id: Mapped[int] = mapped_column(ForeignKey("operational_inventory_documents.id"), nullable=False, index=True)
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


class OperationalInventoryPostingBatch(OperationalBase):
    __tablename__ = "operational_inventory_posting_batches"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_inventory_posting_idempotency"),
        CheckConstraint("status IN ('posted','reversed')", name="ck_inventory_posting_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    document_id: Mapped[int] = mapped_column(ForeignKey("operational_inventory_documents.id"), nullable=False, index=True)
    document_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    posting_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    posted_by: Mapped[str] = mapped_column(String(200), nullable=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    reversed_by: Mapped[str | None] = mapped_column(String(200))
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversal_reason: Mapped[str | None] = mapped_column(Text)


class OperationalInventoryPostingEntry(OperationalBase):
    __tablename__ = "operational_inventory_posting_entries"
    __table_args__ = (
        UniqueConstraint("batch_id", "line_no", "leg_no", name="uq_inventory_posting_entry"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("operational_inventory_posting_batches.id"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    leg_no: Mapped[int] = mapped_column(Integer, nullable=False)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    canonical_uom: Mapped[str] = mapped_column(String(80), nullable=False)
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    value_delta: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    prior_quantity_on_hand: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    prior_quantity_reserved: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    prior_average_unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    resulting_position_revision: Mapped[int] = mapped_column(Integer, nullable=False)


def _validate_shape(document_type: str, location_code: str, destination_location_code: str | None,
                    adjustment_direction: str | None) -> None:
    if document_type == "transfer":
        if not destination_location_code or destination_location_code == location_code:
            raise ValueError("A transfer requires different source and destination locations")
        if adjustment_direction is not None:
            raise ValueError("A transfer cannot have an adjustment direction")
    elif document_type == "adjustment":
        if destination_location_code is not None or adjustment_direction not in {"increase", "decrease"}:
            raise ValueError("An adjustment requires increase/decrease direction and one location")
    else:
        raise ValueError("Inventory document type must be transfer or adjustment")


def create_inventory_document(session: Session, *, document_type: str, location_code: str,
                              destination_location_code: str | None, adjustment_direction: str | None,
                              reason_code: str, notes: str | None, actor: str,
                              lines: list[dict]) -> OperationalInventoryDocument:
    _validate_shape(document_type, location_code, destination_location_code, adjustment_direction)
    if not lines:
        raise ValueError("At least one inventory line is required")
    key = str(uuid.uuid4())
    prefix = "TR" if document_type == "transfer" else "ADJ"
    document = OperationalInventoryDocument(
        document_key=key, document_no=f"{prefix}-{key[:8].upper()}", document_type=document_type,
        location_code=location_code, destination_location_code=destination_location_code,
        adjustment_direction=adjustment_direction, reason_code=reason_code, status="draft",
        posting_enabled=False, notes=notes, created_by=actor, state_changed_by=actor,
    )
    _replace_lines(document, lines)
    session.add(document)
    session.flush()
    session.add(OperationalAuditEvent(
        event_key=str(uuid.uuid4()), event_type="inventory_document.created", actor=actor,
        resource_key=document.document_key,
        detail=f"{document.document_no}; {document_type}; {len(lines)} lines; posting disabled",
    ))
    session.commit()
    return document


def _replace_lines(document: OperationalInventoryDocument, lines: list[dict]) -> None:
    document.lines.clear()
    for number, raw in enumerate(lines, 1):
        quantity = Decimal(str(raw["quantity"]))
        factor = Decimal(str(raw["factor_to_base_snapshot"]))
        cost = Decimal(str(raw["unit_cost_snapshot"]))
        quantity_base = quantity * factor
        if quantity <= 0 or factor <= 0 or cost < 0:
            raise ValueError("Inventory quantity/factor must be positive and cost cannot be negative")
        document.lines.append(OperationalInventoryDocumentLine(
            line_no=number, sku=raw["sku"], product_name_snapshot=raw["product_name_snapshot"],
            quantity=quantity, uom=raw["uom"], canonical_uom=raw["canonical_uom"],
            factor_to_base_snapshot=factor, quantity_base=quantity_base,
            unit_cost_snapshot=cost,
            value_snapshot=(quantity_base * cost).quantize(MONEY, rounding=ROUND_HALF_UP),
        ))


def replace_inventory_document(session: Session, document: OperationalInventoryDocument, *,
                               expected_revision: int, document_type: str,
                               location_code: str, destination_location_code: str | None,
                               adjustment_direction: str | None, reason_code: str,
                               notes: str | None, actor: str,
                               lines: list[dict]) -> OperationalInventoryDocument:
    if document.status != "draft":
        raise ValueError("Only draft-state inventory documents can be edited")
    if document.revision != expected_revision:
        raise ValueError(f"Inventory document revision conflict; current revision is {document.revision}")
    _validate_shape(document_type, location_code, destination_location_code, adjustment_direction)
    if not lines:
        raise ValueError("At least one inventory line is required")
    document.document_type = document_type
    document.location_code = location_code
    document.destination_location_code = destination_location_code
    document.adjustment_direction = adjustment_direction
    document.reason_code = reason_code
    document.notes = notes
    document.revision += 1
    document.state_changed_at = utc_now()
    document.state_changed_by = actor
    # Flush orphan deletes before reusing line numbers protected by the
    # document/line unique constraint.
    document.lines.clear()
    session.flush()
    _replace_lines(document, lines)
    session.add(OperationalAuditEvent(
        event_key=str(uuid.uuid4()), event_type="inventory_document.edited", actor=actor,
        resource_key=document.document_key,
        detail=f"{document.document_no}; revision {document.revision}; {len(lines)} lines; posting disabled",
    ))
    session.commit()
    return document


def list_inventory_documents(session: Session, *, allowed_locations: tuple[str, ...] = ("*",),
                             limit: int = 100) -> list[OperationalInventoryDocument]:
    query = select(OperationalInventoryDocument)
    if "*" not in allowed_locations:
        query = query.where(OperationalInventoryDocument.location_code.in_(allowed_locations))
    return list(session.scalars(query.order_by(OperationalInventoryDocument.created_at.desc()).limit(limit)))


def _is_outgoing(document: OperationalInventoryDocument) -> bool:
    return document.document_type == "transfer" or document.adjustment_direction == "decrease"


def _reserve_outgoing(session: Session, document: OperationalInventoryDocument) -> None:
    if not _is_outgoing(document):
        return
    for line in document.lines:
        position = session.scalar(select(OperationalStockPosition).where(
            OperationalStockPosition.location_code == document.location_code,
            OperationalStockPosition.sku == line.sku,
        ).with_for_update())
        if not position or not position.availability_enabled:
            raise ValueError(f"Approved stock is unavailable for {line.sku} at {document.location_code}")
        if position.canonical_uom.casefold() != line.canonical_uom.casefold():
            raise ValueError(f"Stock UOM mismatch for {line.sku} at {document.location_code}")
        available = position.quantity_on_hand - position.quantity_reserved
        if available < line.quantity_base:
            raise ValueError(
                f"Insufficient available stock for {line.sku} at {document.location_code}: "
                f"required {line.quantity_base}, available {available}"
            )
        line.unit_cost_snapshot = position.average_unit_cost
        line.value_snapshot = (line.quantity_base * position.average_unit_cost).quantize(MONEY, rounding=ROUND_HALF_UP)
        position.quantity_reserved += line.quantity_base
        position.revision += 1
        position.updated_at = utc_now()
        session.add(OperationalInventoryReservation(
            reservation_key=str(uuid.uuid4()), document_id=document.id, document_line_id=line.id,
            location_code=document.location_code, sku=line.sku,
            quantity_base=line.quantity_base, status="active",
        ))


def _release_outgoing(session: Session, document: OperationalInventoryDocument) -> None:
    reservations = list(session.scalars(select(OperationalInventoryReservation).where(
        OperationalInventoryReservation.document_id == document.id,
        OperationalInventoryReservation.status == "active",
    ).with_for_update()))
    for reservation in reservations:
        position = session.scalar(select(OperationalStockPosition).where(
            OperationalStockPosition.location_code == reservation.location_code,
            OperationalStockPosition.sku == reservation.sku,
        ).with_for_update())
        if not position or position.quantity_reserved < reservation.quantity_base:
            raise RuntimeError(f"Inventory reservation ledger mismatch for {reservation.sku}")
        position.quantity_reserved -= reservation.quantity_base
        position.revision += 1
        position.updated_at = utc_now()
        reservation.status = "released"
        reservation.released_at = utc_now()


def transition_inventory_document(session: Session, document: OperationalInventoryDocument, *,
                                  expected_revision: int, action: str, actor: str,
                                  note: str | None = None) -> OperationalInventoryDocument:
    transitions = {
        ("draft", "submit"): "submitted", ("draft", "cancel"): "cancelled",
        ("submitted", "cancel"): "cancelled", ("submitted", "approve"): "approved",
    }
    if document.revision != expected_revision:
        raise ValueError(f"Inventory document revision conflict; current revision is {document.revision}")
    target = transitions.get((document.status, action))
    if not target:
        raise ValueError(f"Action {action} is not allowed from {document.status}")
    if action == "approve" and document.created_by == actor:
        raise PermissionError("Maker-checker control prevents the creator from approving this inventory document")
    if action == "submit":
        _reserve_outgoing(session, document)
    if action == "cancel" and document.status == "submitted":
        _release_outgoing(session, document)
    prior = document.status
    document.status, document.revision = target, document.revision + 1
    document.state_changed_at, document.state_changed_by = utc_now(), actor
    session.add(OperationalInventoryWorkflowEvent(
        event_key=str(uuid.uuid4()), document_id=document.id, from_status=prior,
        to_status=target, actor=actor, note=note,
    ))
    session.add(OperationalAuditEvent(
        event_key=str(uuid.uuid4()), event_type=f"inventory_document.{action}", actor=actor,
        resource_key=document.document_key,
        detail=f"{prior} to {target}; revision {document.revision}; posting disabled",
    ))
    session.commit()
    return document


def rehearse_inventory_posting(session: Session, document: OperationalInventoryDocument, *, actor: str) -> dict:
    if document.status != "approved":
        raise ValueError("Only an approved inventory document can enter posting rehearsal")
    period = session.scalar(select(OperationalFiscalPeriod).where(
        OperationalFiscalPeriod.starts_on <= document.created_at.date(),
        OperationalFiscalPeriod.ends_on >= document.created_at.date(),
    ))
    if not period or period.status != "open" or not period.rehearsal_enabled:
        raise ValueError("Fiscal period is not open for inventory posting rehearsal")
    if _is_outgoing(document):
        reservations = list(session.scalars(select(OperationalInventoryReservation).where(
            OperationalInventoryReservation.document_id == document.id,
            OperationalInventoryReservation.status == "active",
        )))
        reserved = {row.document_line_id: row.quantity_base for row in reservations}
        if any(reserved.get(line.id) != line.quantity_base for line in document.lines):
            raise ValueError("Active reservations do not fully cover the inventory document")
    movements: list[dict] = []
    journal: list[dict] = []
    for line in document.lines:
        value = line.value_snapshot
        if document.document_type == "transfer":
            movements.extend([
                {"line_no": line.line_no, "leg_no": 1, "location": document.location_code,
                 "sku": line.sku, "quantity_base": -line.quantity_base, "value_delta": -value,
                 "canonical_uom": line.canonical_uom, "unit_cost": line.unit_cost_snapshot},
                {"line_no": line.line_no, "leg_no": 2, "location": document.destination_location_code,
                 "sku": line.sku, "quantity_base": line.quantity_base, "value_delta": value,
                 "canonical_uom": line.canonical_uom, "unit_cost": line.unit_cost_snapshot},
            ])
        elif document.adjustment_direction == "increase":
            movements.append({"line_no": line.line_no, "leg_no": 1, "location": document.location_code,
                              "sku": line.sku, "quantity_base": line.quantity_base, "value_delta": value,
                              "canonical_uom": line.canonical_uom, "unit_cost": line.unit_cost_snapshot})
            journal.extend([{"account": "Inventory", "debit": value, "credit": Decimal("0")},
                            {"account": "Inventory Adjustment", "debit": Decimal("0"), "credit": value}])
        else:
            movements.append({"line_no": line.line_no, "leg_no": 1, "location": document.location_code,
                              "sku": line.sku, "quantity_base": -line.quantity_base, "value_delta": -value,
                              "canonical_uom": line.canonical_uom, "unit_cost": line.unit_cost_snapshot})
            journal.extend([{"account": "Inventory Adjustment", "debit": value, "credit": Decimal("0")},
                            {"account": "Inventory", "debit": Decimal("0"), "credit": value}])
    debit = sum((row["debit"] for row in journal), Decimal("0"))
    credit = sum((row["credit"] for row in journal), Decimal("0"))
    if debit != credit:
        raise RuntimeError("Inventory adjustment journal is not balanced")
    source = json.dumps({
        "document_key": document.document_key, "revision": document.revision,
        "movements": [{**row, "quantity_base": str(row["quantity_base"]),
                       "value_delta": str(row["value_delta"]), "unit_cost": str(row["unit_cost"])}
                      for row in movements],
    }, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(source.encode("utf-8")).hexdigest()
    session.add(OperationalAuditEvent(
        event_key=str(uuid.uuid4()), event_type="inventory_document.posting_rehearsed", actor=actor,
        resource_key=document.document_key,
        detail=f"{document.document_no}; {len(movements)} movement legs; fingerprint {fingerprint}; rolled back probes",
    ))
    session.commit()
    return {
        "document_key": document.document_key, "document_no": document.document_no,
        "posting_enabled": False, "period_key": period.period_key,
        "fingerprint": fingerprint, "posting_fingerprint": fingerprint,
        "idempotency_key": f"{document.document_key}:{document.revision}:{fingerprint[:16]}",
        "movements": movements, "journal": journal, "debit": debit, "credit": credit,
        "quantity_delta": sum((row["quantity_base"] for row in movements), Decimal("0")),
        "value_delta": sum((row["value_delta"] for row in movements), Decimal("0")),
    }


def inventory_control_counts(session: Session) -> dict:
    return {
        "documents": session.scalar(select(func.count(OperationalInventoryDocument.id))) or 0,
        "active_reservations": session.scalar(select(func.count(OperationalInventoryReservation.id)).where(
            OperationalInventoryReservation.status == "active")) or 0,
        "posting_batches": session.scalar(select(func.count(OperationalInventoryPostingBatch.id))) or 0,
    }
