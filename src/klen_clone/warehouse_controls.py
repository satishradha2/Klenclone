"""Non-posting warehouse count and quarantine controls.

These controls deliberately create auditable operational decisions only.  Any
stock adjustment resulting from an approved count remains a separate existing
inventory-document workflow.
"""

from __future__ import annotations

import uuid
import re
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .operational import OperationalAuditEvent, OperationalBase, OperationalStockPosition, utc_now


class OperationalCycleCountSession(OperationalBase):
    __tablename__ = "operational_cycle_count_sessions"
    __table_args__ = (CheckConstraint("status IN ('draft','submitted','approved','cancelled')", name="ck_cycle_count_status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    count_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    count_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    lines: Mapped[list["OperationalCycleCountLine"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class OperationalCycleCountLine(OperationalBase):
    __tablename__ = "operational_cycle_count_lines"
    __table_args__ = (UniqueConstraint("session_id", "sku", name="uq_cycle_count_session_sku"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("operational_cycle_count_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    canonical_uom: Mapped[str] = mapped_column(String(80), nullable=False)
    expected_quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    counted_quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    session: Mapped[OperationalCycleCountSession] = relationship(back_populates="lines")


class OperationalQuarantineHold(OperationalBase):
    __tablename__ = "operational_quarantine_holds"
    __table_args__ = (
        CheckConstraint("quantity_base > 0", name="ck_quarantine_hold_quantity"),
        CheckConstraint("status IN ('held','released','cancelled')", name="ck_quarantine_hold_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hold_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    hold_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    canonical_uom: Mapped[str] = mapped_column(String(80), nullable=False)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="held", nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    released_by: Mapped[str | None] = mapped_column(String(200))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    release_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class OperationalBarcodeIdentity(OperationalBase):
    __tablename__ = "operational_barcode_identities"
    __table_args__ = (
        CheckConstraint("factor_to_base > 0", name="ck_barcode_factor_positive"),
        CheckConstraint("status IN ('active','inactive')", name="ck_barcode_identity_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    barcode_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    barcode_value: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    canonical_uom: Mapped[str] = mapped_column(String(80), nullable=False)
    factor_to_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    registration_location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalSerialUnit(OperationalBase):
    __tablename__ = "operational_serial_units"
    __table_args__ = (
        CheckConstraint("status IN ('available','quarantined','retired')", name="ck_serial_unit_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    serial_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    serial_number: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    canonical_uom: Mapped[str] = mapped_column(String(80), nullable=False)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="available", nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    status_changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    status_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    status_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class OperationalWarehouseScan(OperationalBase):
    __tablename__ = "operational_warehouse_scans"
    __table_args__ = (
        CheckConstraint("identity_type IN ('barcode','serial','unknown')", name="ck_warehouse_scan_identity_type"),
        CheckConstraint("outcome IN ('matched','blocked','rejected')", name="ck_warehouse_scan_outcome"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    scanned_value: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    identity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    sku: Mapped[str | None] = mapped_column(String(100), index=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    scanned_by: Mapped[str] = mapped_column(String(200), nullable=False)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


def _audit(session: Session, event: str, actor: str, key: str, detail: str) -> None:
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=event, actor=actor, resource_key=key, detail=detail))


def _identity(value: str) -> str:
    normalized = str(value).strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]{3,79}", normalized):
        raise ValueError("Barcode and serial identities must contain 4-80 safe alphanumeric characters")
    return normalized


def _controlled_position(session: Session, location_code: str, sku: str, *, lock: bool = False) -> OperationalStockPosition:
    query = select(OperationalStockPosition).where(
        OperationalStockPosition.location_code == location_code.upper(),
        OperationalStockPosition.sku == sku.strip(),
    )
    if lock:
        query = query.with_for_update()
    position = session.scalar(query)
    if not position or not position.availability_enabled:
        raise ValueError(f"Available stock is not controlled for {sku.strip()} at {location_code.upper()}")
    return position


def register_barcode(session: Session, *, barcode_value: str, sku: str, location_code: str,
                     factor_to_base, actor: str) -> OperationalBarcodeIdentity:
    value = _identity(barcode_value)
    position = _controlled_position(session, location_code, sku)
    if session.scalar(select(OperationalBarcodeIdentity.id).where(OperationalBarcodeIdentity.barcode_value == value)):
        raise ValueError("Barcode is already assigned")
    if session.scalar(select(OperationalSerialUnit.id).where(OperationalSerialUnit.serial_number == value)):
        raise ValueError("Barcode collides with an existing serial identity")
    factor = Decimal(str(factor_to_base))
    if factor <= 0:
        raise ValueError("Barcode base-unit factor must be positive")
    key = str(uuid.uuid4())
    row = OperationalBarcodeIdentity(
        barcode_key=key, barcode_value=value, sku=sku.strip(),
        canonical_uom=position.canonical_uom, factor_to_base=factor,
        registration_location_code=location_code.upper(), created_by=actor,
    )
    session.add(row); session.flush()
    _audit(session, "warehouse.barcode.registered", actor, key,
           f"{value}; {row.sku}; factor {factor}; non-posting identity")
    session.commit()
    return row


def register_serial(session: Session, *, serial_number: str, sku: str,
                    location_code: str, actor: str) -> OperationalSerialUnit:
    value = _identity(serial_number)
    position = _controlled_position(session, location_code, sku, lock=True)
    if session.scalar(select(OperationalSerialUnit.id).where(OperationalSerialUnit.serial_number == value)):
        raise ValueError("Serial number is already registered")
    if session.scalar(select(OperationalBarcodeIdentity.id).where(OperationalBarcodeIdentity.barcode_value == value)):
        raise ValueError("Serial number collides with an existing barcode identity")
    registered = session.scalar(select(func.count(OperationalSerialUnit.id)).where(
        OperationalSerialUnit.location_code == location_code.upper(),
        OperationalSerialUnit.sku == sku.strip(),
        OperationalSerialUnit.status != "retired",
    )) or 0
    if Decimal(registered + 1) > position.quantity_on_hand:
        raise ValueError("Registered serial units exceed controlled on-hand stock")
    key = str(uuid.uuid4())
    row = OperationalSerialUnit(
        serial_key=key, serial_number=value, sku=sku.strip(),
        canonical_uom=position.canonical_uom, location_code=location_code.upper(),
        created_by=actor, status_changed_by=actor,
    )
    session.add(row); session.flush()
    _audit(session, "warehouse.serial.registered", actor, key,
           f"{value}; {row.sku}; {row.location_code}; non-posting identity")
    session.commit()
    return row


def transition_serial(session: Session, row: OperationalSerialUnit, *, action: str,
                      expected_revision: int, actor: str, note: str) -> OperationalSerialUnit:
    if row.revision != expected_revision:
        raise ValueError(f"Serial revision conflict; current revision is {row.revision}")
    target = {
        ("available", "quarantine"): "quarantined",
        ("quarantined", "release"): "available",
        ("available", "retire"): "retired",
        ("quarantined", "retire"): "retired",
    }.get((row.status, action))
    if not target:
        raise ValueError(f"Serial action {action} is not allowed from {row.status}")
    if action == "release" and row.status_changed_by == actor:
        raise PermissionError("Maker-checker control prevents the quarantine actor from releasing this serial")
    prior = row.status
    row.status, row.status_changed_by, row.status_changed_at = target, actor, utc_now()
    row.status_note, row.revision = note.strip(), row.revision + 1
    _audit(session, f"warehouse.serial.{action}", actor, row.serial_key,
           f"{row.serial_number}; {prior} to {target}; {row.status_note}; non-posting")
    session.commit()
    return row


def record_warehouse_scan(session: Session, *, scanned_value: str, location_code: str,
                          actor: str) -> OperationalWarehouseScan:
    value = _identity(scanned_value)
    location = location_code.upper()
    serial = session.scalar(select(OperationalSerialUnit).where(OperationalSerialUnit.serial_number == value))
    barcode = None if serial else session.scalar(select(OperationalBarcodeIdentity).where(
        OperationalBarcodeIdentity.barcode_value == value))
    identity_type, sku, outcome, detail = "unknown", None, "rejected", "Identity is not registered"
    if serial:
        identity_type, sku = "serial", serial.sku
        if serial.location_code != location:
            outcome, detail = "rejected", "Serial belongs to a different controlled location"
        elif serial.status != "available":
            outcome, detail = "blocked", f"Serial status is {serial.status}"
        else:
            outcome, detail = "matched", "Available serial identity matched"
    elif barcode:
        identity_type, sku = "barcode", barcode.sku
        position = session.scalar(select(OperationalStockPosition).where(
            OperationalStockPosition.location_code == location,
            OperationalStockPosition.sku == barcode.sku,
            OperationalStockPosition.availability_enabled.is_(True),
        ))
        if barcode.status != "active":
            outcome, detail = "blocked", "Barcode identity is inactive"
        elif not position:
            outcome, detail = "rejected", "Barcode SKU is not controlled at the scanned location"
        else:
            outcome, detail = "matched", f"Product barcode matched; factor to base {barcode.factor_to_base}"
    key = str(uuid.uuid4())
    row = OperationalWarehouseScan(
        scan_key=key, scanned_value=value, identity_type=identity_type,
        location_code=location, sku=sku, outcome=outcome, detail=detail, scanned_by=actor,
    )
    session.add(row)
    _audit(session, f"warehouse.scan.{outcome}", actor, key,
           f"{identity_type}; {value}; {location}; {detail}; non-posting")
    session.commit()
    return row


def create_cycle_count(session: Session, *, location_code: str, lines: list[dict], notes: str | None, actor: str) -> OperationalCycleCountSession:
    if not lines:
        raise ValueError("At least one counted SKU is required")
    key = str(uuid.uuid4())
    record = OperationalCycleCountSession(count_key=key, count_no=f"CC-{key[:8].upper()}", location_code=location_code.upper(), notes=notes, created_by=actor)
    seen: set[str] = set()
    for raw in lines:
        sku = str(raw["sku"]).strip()
        if not sku or sku in seen:
            raise ValueError("Each SKU may appear only once in a count session")
        seen.add(sku)
        position = session.scalar(select(OperationalStockPosition).where(OperationalStockPosition.location_code == record.location_code, OperationalStockPosition.sku == sku))
        if not position or not position.availability_enabled:
            raise ValueError(f"Available stock is not controlled for {sku} at {record.location_code}")
        counted = Decimal(str(raw["counted_quantity_base"]))
        if counted < 0:
            raise ValueError("Counted quantity cannot be negative")
        record.lines.append(OperationalCycleCountLine(sku=sku, canonical_uom=position.canonical_uom, expected_quantity_base=position.quantity_on_hand, counted_quantity_base=counted))
    session.add(record); session.flush()
    _audit(session, "warehouse.cycle_count.created", actor, key, f"{record.count_no}; {len(record.lines)} lines; non-posting")
    session.commit()
    return record


def transition_cycle_count(session: Session, record: OperationalCycleCountSession, *, action: str, expected_revision: int, actor: str, note: str | None = None) -> OperationalCycleCountSession:
    if record.revision != expected_revision:
        raise ValueError(f"Cycle-count revision conflict; current revision is {record.revision}")
    target = {("draft", "submit"): "submitted", ("draft", "cancel"): "cancelled", ("submitted", "cancel"): "cancelled", ("submitted", "approve"): "approved"}.get((record.status, action))
    if not target:
        raise ValueError(f"Action {action} is not allowed from {record.status}")
    if action == "approve" and record.created_by == actor:
        raise PermissionError("Maker-checker control prevents the count creator from approving it")
    prior = record.status; record.status = target; record.revision += 1
    if action == "approve": record.approved_by = actor
    _audit(session, f"warehouse.cycle_count.{action}", actor, record.count_key, f"{prior} to {target}; {note or 'no note'}; non-posting")
    session.commit()
    return record


def create_quarantine_hold(session: Session, *, location_code: str, sku: str, quantity_base, reason: str, actor: str) -> OperationalQuarantineHold:
    position = session.scalar(select(OperationalStockPosition).where(
        OperationalStockPosition.location_code == location_code.upper(),
        OperationalStockPosition.sku == sku.strip(),
    ).with_for_update())
    if not position or not position.availability_enabled:
        raise ValueError("Quarantine requires an available controlled stock position")
    quantity = Decimal(str(quantity_base))
    if quantity <= 0 or quantity > position.quantity_on_hand - position.quantity_reserved:
        raise ValueError("Quarantine quantity exceeds available stock")
    key = str(uuid.uuid4())
    hold = OperationalQuarantineHold(hold_key=key, hold_no=f"QH-{key[:8].upper()}", location_code=location_code.upper(), sku=sku.strip(), canonical_uom=position.canonical_uom, quantity_base=quantity, reason=reason.strip(), created_by=actor)
    position.quantity_reserved += quantity
    position.revision += 1
    position.updated_at = utc_now()
    session.add(hold); session.flush()
    _audit(session, "warehouse.quarantine.held", actor, key, f"{hold.hold_no}; {hold.sku}; {quantity}; non-posting hold")
    session.commit()
    return hold


def release_quarantine_hold(session: Session, hold: OperationalQuarantineHold, *, expected_revision: int, actor: str, note: str) -> OperationalQuarantineHold:
    if hold.revision != expected_revision:
        raise ValueError(f"Quarantine revision conflict; current revision is {hold.revision}")
    if hold.status != "held": raise ValueError("Only an active quarantine hold can be released")
    if hold.created_by == actor: raise PermissionError("Maker-checker control prevents the hold creator from releasing it")
    position = session.scalar(select(OperationalStockPosition).where(OperationalStockPosition.location_code == hold.location_code, OperationalStockPosition.sku == hold.sku).with_for_update())
    if not position or position.quantity_reserved < hold.quantity_base:
        raise RuntimeError("Quarantine reservation ledger mismatch")
    position.quantity_reserved -= hold.quantity_base
    position.revision += 1
    position.updated_at = utc_now()
    hold.status, hold.revision, hold.released_by, hold.released_at, hold.release_note = "released", hold.revision + 1, actor, utc_now(), note
    _audit(session, "warehouse.quarantine.released", actor, hold.hold_key, f"{hold.hold_no}; independent release; allocation released; non-posting")
    session.commit()
    return hold


def cycle_count_payload(row: OperationalCycleCountSession) -> dict:
    return {"count_key": row.count_key, "count_no": row.count_no, "location_code": row.location_code, "status": row.status, "notes": row.notes, "created_by": row.created_by, "approved_by": row.approved_by, "revision": row.revision, "lines": [{"sku": line.sku, "canonical_uom": line.canonical_uom, "expected_quantity_base": line.expected_quantity_base, "counted_quantity_base": line.counted_quantity_base, "variance_quantity_base": line.counted_quantity_base - line.expected_quantity_base} for line in row.lines]}


def quarantine_payload(row: OperationalQuarantineHold) -> dict:
    return {"hold_key": row.hold_key, "hold_no": row.hold_no, "location_code": row.location_code, "sku": row.sku, "canonical_uom": row.canonical_uom, "quantity_base": row.quantity_base, "reason": row.reason, "status": row.status, "created_by": row.created_by, "released_by": row.released_by, "release_note": row.release_note, "revision": row.revision}


def barcode_payload(row: OperationalBarcodeIdentity) -> dict:
    return {"barcode_key": row.barcode_key, "barcode_value": row.barcode_value,
            "sku": row.sku, "canonical_uom": row.canonical_uom,
            "factor_to_base": row.factor_to_base,
            "registration_location_code": row.registration_location_code,
            "status": row.status, "created_by": row.created_by,
            "created_at": row.created_at, "posting_enabled": False}


def serial_payload(row: OperationalSerialUnit) -> dict:
    return {"serial_key": row.serial_key, "serial_number": row.serial_number,
            "sku": row.sku, "canonical_uom": row.canonical_uom,
            "location_code": row.location_code, "status": row.status,
            "created_by": row.created_by, "created_at": row.created_at,
            "status_changed_by": row.status_changed_by,
            "status_changed_at": row.status_changed_at, "status_note": row.status_note,
            "revision": row.revision, "posting_enabled": False}


def scan_payload(row: OperationalWarehouseScan) -> dict:
    return {"scan_key": row.scan_key, "scanned_value": row.scanned_value,
            "identity_type": row.identity_type, "location_code": row.location_code,
            "sku": row.sku, "outcome": row.outcome, "detail": row.detail,
            "scanned_by": row.scanned_by, "scanned_at": row.scanned_at,
            "posting_enabled": False}


def warehouse_control_payload(session: Session, *, allowed_locations: tuple[str, ...]) -> dict:
    counts = select(OperationalCycleCountSession)
    holds = select(OperationalQuarantineHold)
    barcodes = select(OperationalBarcodeIdentity)
    serials = select(OperationalSerialUnit)
    scans = select(OperationalWarehouseScan)
    active_holds = select(func.count(OperationalQuarantineHold.id)).where(OperationalQuarantineHold.status == "held")
    active_barcodes = select(func.count(OperationalBarcodeIdentity.id)).where(OperationalBarcodeIdentity.status == "active")
    tracked_serials = select(func.count(OperationalSerialUnit.id)).where(OperationalSerialUnit.status != "retired")
    blocked_scans = select(func.count(OperationalWarehouseScan.id)).where(OperationalWarehouseScan.outcome != "matched")
    if "*" not in allowed_locations:
        counts = counts.where(OperationalCycleCountSession.location_code.in_(allowed_locations))
        holds = holds.where(OperationalQuarantineHold.location_code.in_(allowed_locations))
        barcodes = barcodes.where(OperationalBarcodeIdentity.registration_location_code.in_(allowed_locations))
        serials = serials.where(OperationalSerialUnit.location_code.in_(allowed_locations))
        scans = scans.where(OperationalWarehouseScan.location_code.in_(allowed_locations))
        active_holds = active_holds.where(OperationalQuarantineHold.location_code.in_(allowed_locations))
        active_barcodes = active_barcodes.where(OperationalBarcodeIdentity.registration_location_code.in_(allowed_locations))
        tracked_serials = tracked_serials.where(OperationalSerialUnit.location_code.in_(allowed_locations))
        blocked_scans = blocked_scans.where(OperationalWarehouseScan.location_code.in_(allowed_locations))
    return {"posting_enabled": False,
            "cycle_counts": [cycle_count_payload(row) for row in session.scalars(counts.order_by(OperationalCycleCountSession.created_at.desc()))],
            "quarantine_holds": [quarantine_payload(row) for row in session.scalars(holds.order_by(OperationalQuarantineHold.created_at.desc()))],
            "barcodes": [barcode_payload(row) for row in session.scalars(barcodes.order_by(OperationalBarcodeIdentity.created_at.desc()))],
            "serial_units": [serial_payload(row) for row in session.scalars(serials.order_by(OperationalSerialUnit.created_at.desc()))],
            "recent_scans": [scan_payload(row) for row in session.scalars(scans.order_by(OperationalWarehouseScan.scanned_at.desc()).limit(100))],
            "controls": {"active_quarantine_holds": session.scalar(active_holds) or 0,
                         "active_barcodes": session.scalar(active_barcodes) or 0,
                         "tracked_serials": session.scalar(tracked_serials) or 0,
                         "blocked_scans": session.scalar(blocked_scans) or 0}}
