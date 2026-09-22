"""Non-posting warehouse count and quarantine controls.

These controls deliberately create auditable operational decisions only.  Any
stock adjustment resulting from an approved count remains a separate existing
inventory-document workflow.
"""

from __future__ import annotations

import hashlib
import uuid
import re
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func, or_, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .inventory import canonical_uom
from .operational import OperationalAuditEvent, OperationalBase, OperationalStockPosition, utc_now
from .operational_masters import OperationalProductMaster


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


class OperationalProductUomConversion(OperationalBase):
    __tablename__ = "operational_product_uom_conversions"
    __table_args__ = (
        UniqueConstraint("sku", "uom", name="uq_operational_product_uom"),
        UniqueConstraint("barcode_value", name="uq_operational_product_uom_barcode"),
        CheckConstraint("factor_to_base > 0", name="ck_operational_product_uom_factor"),
        CheckConstraint("pack_level IN ('base','transaction','inner','outer','pallet')", name="ck_operational_product_pack_level"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversion_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    uom: Mapped[str] = mapped_column(String(80), nullable=False)
    canonical_uom: Mapped[str] = mapped_column(String(80), nullable=False)
    factor_to_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    pack_level: Mapped[str] = mapped_column(String(20), default="transaction", nullable=False)
    allow_purchase: Mapped[bool] = mapped_column(default=True, nullable=False)
    allow_sale: Mapped[bool] = mapped_column(default=True, nullable=False)
    is_default_purchase: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_default_sale: Mapped[bool] = mapped_column(default=False, nullable=False)
    barcode_value: Mapped[str | None] = mapped_column(String(80), index=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalProductRecall(OperationalBase):
    __tablename__ = "operational_product_recalls"
    __table_args__ = (CheckConstraint(
        "status IN ('draft','submitted','active','closed','cancelled')", name="ck_product_recall_status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recall_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    recall_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    lines: Mapped[list["OperationalProductRecallLine"]] = relationship(back_populates="recall", cascade="all, delete-orphan")


class OperationalProductRecallLine(OperationalBase):
    __tablename__ = "operational_product_recall_lines"
    __table_args__ = (UniqueConstraint("recall_id", "sku", "identity_value", name="uq_product_recall_line"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recall_id: Mapped[int] = mapped_column(ForeignKey("operational_product_recalls.id", ondelete="CASCADE"), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    identity_value: Mapped[str] = mapped_column(String(80), default="", nullable=False, index=True)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    canonical_uom: Mapped[str] = mapped_column(String(80), nullable=False)
    recall: Mapped[OperationalProductRecall] = relationship(back_populates="lines")


class OperationalWarehouseTask(OperationalBase):
    __tablename__ = "operational_warehouse_tasks"
    __table_args__ = (
        CheckConstraint("status IN ('open','in_progress','completed','cancelled')", name="ck_warehouse_task_status"),
        CheckConstraint("task_type IN ('recall_isolation','count','relabel','investigation')", name="ck_warehouse_task_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    task_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    source_recall_key: Mapped[str | None] = mapped_column(String(36), index=True)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    identity_value: Mapped[str | None] = mapped_column(String(80), index=True)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False)
    assignee: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False, index=True)
    evidence: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_by: Mapped[str | None] = mapped_column(String(200))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


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


def _ean13(seed: str, prefix: str) -> str:
    if prefix not in {"20", "21", "22", "23", "24"}:
        raise ValueError("Unsupported internal barcode prefix")
    digits = str(int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16))
    body = (prefix + digits)[:12]
    check = (10 - sum((1 if index % 2 == 0 else 3) * int(value)
                      for index, value in enumerate(body)) % 10) % 10
    return body + str(check)


def _barcode_available(session: Session, value: str) -> bool:
    return not (
        session.scalar(select(OperationalBarcodeIdentity.id).where(
            OperationalBarcodeIdentity.barcode_value == value))
        or session.scalar(select(OperationalProductUomConversion.id).where(
            OperationalProductUomConversion.barcode_value == value))
        or session.scalar(select(OperationalSerialUnit.id).where(
            OperationalSerialUnit.serial_number == value))
    )


def _generate_unique_barcode(session: Session, *, sku: str, uom: str, pack_level: str) -> str:
    prefix = {"base": "20", "transaction": "21", "inner": "22", "outer": "23", "pallet": "24"}[pack_level]
    for attempt in range(1000):
        value = _ean13(f"{sku}|{uom}|{pack_level}|{attempt}", prefix)
        if _barcode_available(session, value):
            return value
    raise RuntimeError("Unable to generate a unique internal EAN-13 barcode")


def resolve_product_uom(session: Session, *, sku: str, uom: str,
                        actor: str = "system") -> OperationalProductUomConversion:
    product = session.scalar(select(OperationalProductMaster).where(
        OperationalProductMaster.sku == sku.strip(), OperationalProductMaster.status == "active"))
    if not product:
        raise ValueError("SKU is not active in the controlled product master")
    normalized = uom.strip().casefold()
    conversion = session.scalar(select(OperationalProductUomConversion).where(
        OperationalProductUomConversion.sku == product.sku,
        func.lower(OperationalProductUomConversion.uom) == normalized,
    ))
    if conversion:
        return conversion
    normalized_canonical = canonical_uom(uom) or normalized
    product_canonical = canonical_uom(product.canonical_base_uom) or product.canonical_base_uom.casefold()
    if normalized not in {product.base_uom.casefold(), product.canonical_base_uom.casefold()} and normalized_canonical != product_canonical:
        raise ValueError(f"UOM {uom} is not an approved conversion for SKU {product.sku}")
    existing_base = session.scalar(select(OperationalProductUomConversion).where(
        OperationalProductUomConversion.sku == product.sku,
        OperationalProductUomConversion.pack_level == "base"))
    if existing_base:
        return existing_base
    conversion = OperationalProductUomConversion(
        conversion_key=str(uuid.uuid4()), sku=product.sku, uom=product.base_uom,
        canonical_uom=canonical_uom(product.canonical_base_uom) or product.canonical_base_uom,
        factor_to_base=Decimal("1"),
        pack_level="base", allow_purchase=True, allow_sale=True,
        is_default_purchase=True, is_default_sale=True, created_by=actor,
    )
    session.add(conversion)
    session.flush()
    return conversion


def register_product_uom(session: Session, *, sku: str, uom: str, factor_to_base,
                         pack_level: str, allow_purchase: bool, allow_sale: bool,
                         is_default_purchase: bool, is_default_sale: bool,
                         actor: str) -> OperationalProductUomConversion:
    if pack_level not in {"transaction", "inner", "outer", "pallet"}:
        raise ValueError("Pack level must be transaction, inner, outer or pallet")
    product = session.scalar(select(OperationalProductMaster).where(
        OperationalProductMaster.sku == sku.strip(), OperationalProductMaster.status == "active"))
    if not product:
        raise ValueError("SKU is not active in the controlled product master")
    factor = Decimal(str(factor_to_base))
    if factor <= 0:
        raise ValueError("Factor to base must be positive")
    if uom.strip().casefold() in {product.base_uom.casefold(), product.canonical_base_uom.casefold()}:
        raise ValueError("The base UOM already has an immutable factor of 1")
    if session.scalar(select(OperationalProductUomConversion.id).where(
            OperationalProductUomConversion.sku == product.sku,
            func.lower(OperationalProductUomConversion.uom) == uom.strip().casefold())):
        raise ValueError("This product UOM conversion already exists")
    if is_default_purchase:
        current = session.scalar(select(OperationalProductUomConversion.id).where(
            OperationalProductUomConversion.sku == product.sku,
            OperationalProductUomConversion.is_default_purchase.is_(True)))
        if current:
            raise ValueError("This product already has a default purchase UOM")
    if is_default_sale:
        current = session.scalar(select(OperationalProductUomConversion.id).where(
            OperationalProductUomConversion.sku == product.sku,
            OperationalProductUomConversion.is_default_sale.is_(True)))
        if current:
            raise ValueError("This product already has a default sale UOM")
    row = OperationalProductUomConversion(
        conversion_key=str(uuid.uuid4()), sku=product.sku, uom=uom.strip(),
        canonical_uom=canonical_uom(product.canonical_base_uom) or product.canonical_base_uom,
        factor_to_base=factor,
        pack_level=pack_level, allow_purchase=allow_purchase, allow_sale=allow_sale,
        is_default_purchase=is_default_purchase, is_default_sale=is_default_sale,
        created_by=actor,
    )
    session.add(row); session.flush()
    _audit(session, "master.product_uom.created", actor, row.conversion_key,
           f"{row.sku}; {row.uom}; direct factor to base {factor}; {pack_level}")
    session.commit()
    return row


def register_barcode(session: Session, *, barcode_value: str | None, sku: str, location_code: str,
                     uom: str, actor: str) -> OperationalBarcodeIdentity:
    position = _controlled_position(session, location_code, sku)
    conversion = resolve_product_uom(session, sku=sku, uom=uom, actor=actor)
    if conversion.canonical_uom.casefold() != position.canonical_uom.casefold():
        raise ValueError("Product UOM master does not match the controlled stock base UOM")
    if conversion.barcode_value:
        raise ValueError("This product UOM already has an immutable barcode")
    value = (_identity(barcode_value) if barcode_value else
             _generate_unique_barcode(session, sku=sku.strip(), uom=conversion.uom,
                                      pack_level=conversion.pack_level))
    if not _barcode_available(session, value):
        raise ValueError("Barcode is already assigned or collides with a serial identity")
    key = str(uuid.uuid4())
    row = OperationalBarcodeIdentity(
        barcode_key=key, barcode_value=value, sku=sku.strip(),
        canonical_uom=position.canonical_uom, factor_to_base=conversion.factor_to_base,
        registration_location_code=location_code.upper(), created_by=actor,
    )
    conversion.barcode_value = value
    session.add(row); session.flush()
    _audit(session, "warehouse.barcode.registered", actor, key,
           f"{value}; {row.sku}; {conversion.uom}; governed factor {conversion.factor_to_base}; non-posting identity")
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
    if sku:
        active_recall = session.scalar(select(OperationalProductRecallLine).join(
            OperationalProductRecall, OperationalProductRecall.id == OperationalProductRecallLine.recall_id
        ).where(
            OperationalProductRecall.status == "active",
            OperationalProductRecall.location_code == location,
            OperationalProductRecallLine.sku == sku,
            or_(OperationalProductRecallLine.identity_value == "",
                OperationalProductRecallLine.identity_value == value),
        ))
        if active_recall:
            outcome, detail = "blocked", "Identity is covered by an active product recall"
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


def create_product_recall(session: Session, *, location_code: str, reason: str,
                          severity: str, lines: list[dict], actor: str) -> OperationalProductRecall:
    if severity not in {"low", "medium", "high", "critical"}:
        raise ValueError("Recall severity must be low, medium, high or critical")
    if not lines:
        raise ValueError("At least one recall line is required")
    key = str(uuid.uuid4())
    recall = OperationalProductRecall(
        recall_key=key, recall_no=f"RC-{key[:8].upper()}",
        location_code=location_code.upper(), reason=reason.strip(),
        severity=severity, created_by=actor,
    )
    seen: set[tuple[str, str]] = set()
    for raw in lines:
        sku = str(raw["sku"]).strip()
        identity = str(raw.get("identity_value") or "").strip().upper()
        if (sku, identity) in seen:
            raise ValueError("Each recalled SKU and identity combination must be unique")
        seen.add((sku, identity))
        position = _controlled_position(session, recall.location_code, sku)
        quantity = Decimal(str(raw["quantity_base"]))
        if quantity <= 0 or quantity > position.quantity_on_hand:
            raise ValueError(f"Recall quantity for {sku} exceeds controlled on-hand stock")
        if identity:
            serial = session.scalar(select(OperationalSerialUnit).where(
                OperationalSerialUnit.serial_number == identity,
                OperationalSerialUnit.sku == sku,
                OperationalSerialUnit.location_code == recall.location_code))
            barcode = session.scalar(select(OperationalBarcodeIdentity).where(
                OperationalBarcodeIdentity.barcode_value == identity,
                OperationalBarcodeIdentity.sku == sku))
            if not serial and not barcode:
                raise ValueError(f"Recall identity {identity} is not registered for {sku}")
        recall.lines.append(OperationalProductRecallLine(
            sku=sku, identity_value=identity, quantity_base=quantity,
            canonical_uom=position.canonical_uom,
        ))
    session.add(recall); session.flush()
    _audit(session, "warehouse.recall.created", actor, key,
           f"{recall.recall_no}; {severity}; {len(lines)} lines; non-posting")
    session.commit()
    return recall


def transition_product_recall(session: Session, recall: OperationalProductRecall, *,
                              action: str, expected_revision: int, actor: str,
                              note: str) -> OperationalProductRecall:
    if recall.revision != expected_revision:
        raise ValueError(f"Recall revision conflict; current revision is {recall.revision}")
    target = {
        ("draft", "submit"): "submitted", ("draft", "cancel"): "cancelled",
        ("submitted", "activate"): "active", ("submitted", "cancel"): "cancelled",
        ("active", "close"): "closed",
    }.get((recall.status, action))
    if not target:
        raise ValueError(f"Recall action {action} is not allowed from {recall.status}")
    if action in {"activate", "close"} and recall.created_by == actor:
        raise PermissionError("Maker-checker control prevents the recall creator from making this decision")
    prior = recall.status
    recall.status, recall.revision = target, recall.revision + 1
    recall.decided_by, recall.decided_at, recall.decision_note = actor, utc_now(), note.strip()
    if action == "activate":
        for line in recall.lines:
            key = str(uuid.uuid4())
            session.add(OperationalWarehouseTask(
                task_key=key, task_no=f"WT-{key[:8].upper()}", task_type="recall_isolation",
                source_recall_key=recall.recall_key, location_code=recall.location_code,
                sku=line.sku, identity_value=line.identity_value or None,
                instructions=f"Locate, isolate and evidence recalled stock for {recall.recall_no}",
                priority="urgent" if recall.severity in {"high", "critical"} else "normal",
                created_by=actor,
            ))
    _audit(session, f"warehouse.recall.{action}", actor, recall.recall_key,
           f"{prior} to {target}; {note.strip()}; non-posting")
    session.commit()
    return recall


def transition_warehouse_task(session: Session, task: OperationalWarehouseTask, *,
                              action: str, expected_revision: int, actor: str,
                              evidence: str | None = None) -> OperationalWarehouseTask:
    if task.revision != expected_revision:
        raise ValueError(f"Warehouse-task revision conflict; current revision is {task.revision}")
    target = {("open", "start"): "in_progress", ("open", "cancel"): "cancelled",
              ("in_progress", "complete"): "completed",
              ("in_progress", "cancel"): "cancelled"}.get((task.status, action))
    if not target:
        raise ValueError(f"Task action {action} is not allowed from {task.status}")
    if action == "complete" and len((evidence or "").strip()) < 5:
        raise ValueError("Completion evidence of at least 5 characters is required")
    task.status, task.revision = target, task.revision + 1
    if action == "start":
        task.assignee = actor
    if action == "complete":
        task.evidence, task.completed_by, task.completed_at = evidence.strip(), actor, utc_now()
    _audit(session, f"warehouse.task.{action}", actor, task.task_key,
           f"{task.task_no}; {target}; {evidence or 'no evidence'}; non-posting")
    session.commit()
    return task


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


def product_uom_payload(row: OperationalProductUomConversion) -> dict:
    return {"conversion_key": row.conversion_key, "sku": row.sku, "uom": row.uom,
            "canonical_uom": row.canonical_uom, "factor_to_base": row.factor_to_base,
            "pack_level": row.pack_level, "allow_purchase": row.allow_purchase,
            "allow_sale": row.allow_sale, "is_default_purchase": row.is_default_purchase,
            "is_default_sale": row.is_default_sale, "barcode_value": row.barcode_value,
            "created_by": row.created_by, "created_at": row.created_at}


def recall_payload(row: OperationalProductRecall) -> dict:
    return {"recall_key": row.recall_key, "recall_no": row.recall_no,
            "location_code": row.location_code, "reason": row.reason,
            "severity": row.severity, "status": row.status,
            "created_by": row.created_by, "created_at": row.created_at,
            "decided_by": row.decided_by, "decision_note": row.decision_note,
            "revision": row.revision,
            "lines": [{"sku": line.sku, "identity_value": line.identity_value or None,
                       "quantity_base": line.quantity_base,
                       "canonical_uom": line.canonical_uom} for line in row.lines]}


def task_payload(row: OperationalWarehouseTask) -> dict:
    return {"task_key": row.task_key, "task_no": row.task_no,
            "task_type": row.task_type, "source_recall_key": row.source_recall_key,
            "location_code": row.location_code, "sku": row.sku,
            "identity_value": row.identity_value, "instructions": row.instructions,
            "priority": row.priority, "assignee": row.assignee, "status": row.status,
            "evidence": row.evidence, "created_by": row.created_by,
            "created_at": row.created_at, "completed_by": row.completed_by,
            "completed_at": row.completed_at, "revision": row.revision}


def warehouse_control_payload(session: Session, *, allowed_locations: tuple[str, ...]) -> dict:
    counts = select(OperationalCycleCountSession)
    holds = select(OperationalQuarantineHold)
    barcodes = select(OperationalBarcodeIdentity)
    serials = select(OperationalSerialUnit)
    scans = select(OperationalWarehouseScan)
    recalls = select(OperationalProductRecall)
    tasks = select(OperationalWarehouseTask)
    active_holds = select(func.count(OperationalQuarantineHold.id)).where(OperationalQuarantineHold.status == "held")
    active_barcodes = select(func.count(OperationalBarcodeIdentity.id)).where(OperationalBarcodeIdentity.status == "active")
    tracked_serials = select(func.count(OperationalSerialUnit.id)).where(OperationalSerialUnit.status != "retired")
    blocked_scans = select(func.count(OperationalWarehouseScan.id)).where(OperationalWarehouseScan.outcome != "matched")
    active_recalls = select(func.count(OperationalProductRecall.id)).where(OperationalProductRecall.status == "active")
    open_tasks = select(func.count(OperationalWarehouseTask.id)).where(
        OperationalWarehouseTask.status.in_(("open", "in_progress")))
    if "*" not in allowed_locations:
        counts = counts.where(OperationalCycleCountSession.location_code.in_(allowed_locations))
        holds = holds.where(OperationalQuarantineHold.location_code.in_(allowed_locations))
        barcodes = barcodes.where(OperationalBarcodeIdentity.registration_location_code.in_(allowed_locations))
        serials = serials.where(OperationalSerialUnit.location_code.in_(allowed_locations))
        scans = scans.where(OperationalWarehouseScan.location_code.in_(allowed_locations))
        recalls = recalls.where(OperationalProductRecall.location_code.in_(allowed_locations))
        tasks = tasks.where(OperationalWarehouseTask.location_code.in_(allowed_locations))
        active_holds = active_holds.where(OperationalQuarantineHold.location_code.in_(allowed_locations))
        active_barcodes = active_barcodes.where(OperationalBarcodeIdentity.registration_location_code.in_(allowed_locations))
        tracked_serials = tracked_serials.where(OperationalSerialUnit.location_code.in_(allowed_locations))
        blocked_scans = blocked_scans.where(OperationalWarehouseScan.location_code.in_(allowed_locations))
        active_recalls = active_recalls.where(OperationalProductRecall.location_code.in_(allowed_locations))
        open_tasks = open_tasks.where(OperationalWarehouseTask.location_code.in_(allowed_locations))
    return {"posting_enabled": False,
            "cycle_counts": [cycle_count_payload(row) for row in session.scalars(counts.order_by(OperationalCycleCountSession.created_at.desc()))],
            "quarantine_holds": [quarantine_payload(row) for row in session.scalars(holds.order_by(OperationalQuarantineHold.created_at.desc()))],
            "barcodes": [barcode_payload(row) for row in session.scalars(barcodes.order_by(OperationalBarcodeIdentity.created_at.desc()))],
            "serial_units": [serial_payload(row) for row in session.scalars(serials.order_by(OperationalSerialUnit.created_at.desc()))],
            "recent_scans": [scan_payload(row) for row in session.scalars(scans.order_by(OperationalWarehouseScan.scanned_at.desc()).limit(100))],
            "recalls": [recall_payload(row) for row in session.scalars(recalls.order_by(OperationalProductRecall.created_at.desc()))],
            "tasks": [task_payload(row) for row in session.scalars(tasks.order_by(OperationalWarehouseTask.created_at.desc()))],
            "controls": {"active_quarantine_holds": session.scalar(active_holds) or 0,
                         "active_barcodes": session.scalar(active_barcodes) or 0,
                         "tracked_serials": session.scalar(tracked_serials) or 0,
                         "blocked_scans": session.scalar(blocked_scans) or 0,
                         "active_recalls": session.scalar(active_recalls) or 0,
                         "open_tasks": session.scalar(open_tasks) or 0}}
