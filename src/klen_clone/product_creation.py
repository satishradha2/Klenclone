"""Governed, non-posting product editor and direct-to-base unit hierarchy."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .inventory import canonical_uom
from .operational import OperationalAuditEvent, OperationalBase, utc_now
from .operational_masters import OperationalProductMaster
from .product_taxonomy import saved_master_name, validate_product_taxonomy
from .warehouse_controls import (
    OperationalBarcodeIdentity, OperationalProductUomConversion, OperationalSerialUnit,
)


class ProductSpecification(BaseModel):
    specification_type: str = Field(min_length=1, max_length=120)
    specification_value: str = Field(min_length=1, max_length=120)
    unit_label: str | None = Field(default=None, max_length=30)
    include_in_name: bool = True


class ProductConversion(BaseModel):
    uom: str = Field(min_length=1, max_length=80)
    factor_to_base: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    pack_level: str = Field(pattern="^(transaction|inner|outer|pallet)$")
    barcode: str | None = Field(default=None, max_length=80)
    allow_purchase: bool = True
    allow_sale: bool = True
    is_default_purchase: bool = False
    is_default_sale: bool = False


class ProductEditor(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=250)
    short_name: str | None = Field(default=None, max_length=160)
    description: str | None = None
    category_name: str = Field(min_length=1, max_length=200)
    brand_name: str | None = Field(default=None, max_length=200)
    product_family: str | None = Field(default=None, max_length=120)
    product_type: str | None = Field(default=None, max_length=120)
    material: str | None = Field(default=None, max_length=120)
    variant: str | None = Field(default=None, max_length=120)
    country_of_origin: str | None = Field(default=None, pattern="^[A-Z]{2}$")
    hs_code: str | None = Field(default=None, max_length=30)
    barcode: str | None = Field(default=None, max_length=80)
    barcode_format: str = Field(default="internal_ean13", pattern="^(internal_ean13|supplier|gs1)$")
    base_uom: str = Field(min_length=1, max_length=80)
    reorder_point_base: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=6)
    preferred_warehouse: str | None = Field(default=None, max_length=80)
    gross_weight_kg: Decimal | None = Field(default=None, gt=0)
    net_weight_kg: Decimal | None = Field(default=None, gt=0)
    length_cm: Decimal | None = Field(default=None, gt=0)
    width_cm: Decimal | None = Field(default=None, gt=0)
    height_cm: Decimal | None = Field(default=None, gt=0)
    volume_cbm: Decimal | None = Field(default=None, gt=0)
    measurement_verified: bool = False
    is_stock_item: bool = True
    track_lots: bool = False
    track_expiry: bool = False
    purchase_vat_rate: Decimal = Field(default=Decimal("5"), ge=0, le=100)
    sales_vat_rate: Decimal = Field(default=Decimal("5"), ge=0, le=100)
    standard_cost: Decimal = Field(default=Decimal("0"), ge=0)
    default_sales_price: Decimal = Field(default=Decimal("0"), ge=0)
    specifications: list[ProductSpecification] = Field(default_factory=list)
    uom_conversions: list[ProductConversion] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_hierarchy(self):
        units = [self.base_uom.casefold()] + [c.uom.casefold() for c in self.uom_conversions]
        if len(units) != len(set(units)):
            raise ValueError("A unit may appear only once in the product hierarchy")
        if sum(c.is_default_purchase for c in self.uom_conversions) > 1 or sum(c.is_default_sale for c in self.uom_conversions) > 1:
            raise ValueError("Only one default purchase and one default sale unit are allowed")
        if any(c.is_default_purchase and not c.allow_purchase or c.is_default_sale and not c.allow_sale for c in self.uom_conversions):
            raise ValueError("A default unit must be allowed for that transaction")
        if self.net_weight_kg is not None and self.gross_weight_kg is not None and self.net_weight_kg > self.gross_weight_kg:
            raise ValueError("Net weight cannot exceed gross weight")
        dimensions = (self.length_cm, self.width_cm, self.height_cm)
        if any(v is not None for v in dimensions) and not all(v is not None for v in dimensions):
            raise ValueError("Length, width and height must be entered together")
        if self.measurement_verified and (self.gross_weight_kg is None or self.volume_cbm is None):
            raise ValueError("Verified measurements require gross weight and volume")
        if self.track_expiry and not self.track_lots:
            raise ValueError("Expiry tracking requires lot tracking")
        codes = [v for v in [self.barcode, *(c.barcode for c in self.uom_conversions)] if v]
        if len(codes) != len(set(codes)):
            raise ValueError("Product and pack barcodes must be distinct")
        if self.barcode_format == "internal_ean13" and any(v and not valid_ean13(v) for v in codes):
            raise ValueError("Internal barcodes must be valid EAN-13 codes")
        return self


class ProductChangeRequest(OperationalBase):
    __tablename__ = "operational_product_change_requests"
    __table_args__ = (UniqueConstraint("change_key", name="uq_product_change_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    change_key: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    expected_revision: Mapped[int | None] = mapped_column(Integer)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    duplicate_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)


class OperationalProductDetails(OperationalBase):
    __tablename__ = "operational_product_details"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    duplicate_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


def duplicate_key(payload: ProductEditor) -> str:
    structure = {
        "category": payload.category_name.strip().casefold(),
        "family": (payload.product_family or "").strip().casefold(),
        "type": (payload.product_type or "").strip().casefold(),
        "material": (payload.material or "").strip().casefold(),
        "variant": (payload.variant or "").strip().casefold(),
        "base": payload.base_uom.strip().casefold(),
        "specifications": sorted((s.specification_type.strip().casefold(), s.specification_value.strip().casefold(), (s.unit_label or "").strip().casefold()) for s in payload.specifications),
        "conversions": sorted((c.uom.strip().casefold(), str(c.factor_to_base)) for c in payload.uom_conversions),
    }
    return hashlib.sha256(json.dumps(structure, sort_keys=True).encode()).hexdigest()


def ean13(seed: str, prefix: str) -> str:
    digits = str(int(hashlib.sha256(seed.encode()).hexdigest(), 16))
    body = (prefix + digits)[:12].ljust(12, "0")
    checksum = (10 - sum(int(digit) * (1 if i % 2 == 0 else 3) for i, digit in enumerate(body)) % 10) % 10
    return body + str(checksum)


def valid_ean13(value: str) -> bool:
    return len(value) == 13 and value.isdigit() and (
        sum(int(digit) * (1 if i % 2 == 0 else 3) for i, digit in enumerate(value[:12]))
        + int(value[12])) % 10 == 0


def barcode_taken(session: Session, value: str) -> bool:
    if session.scalar(select(OperationalBarcodeIdentity.id).where(OperationalBarcodeIdentity.barcode_value == value)):
        return True
    if session.scalar(select(OperationalProductUomConversion.id).where(OperationalProductUomConversion.barcode_value == value)):
        return True
    if session.scalar(select(OperationalSerialUnit.id).where(OperationalSerialUnit.serial_number == value)):
        return True
    for row in session.scalars(select(OperationalProductDetails)):
        if json.loads(row.payload_json).get("barcode") == value:
            return True
    return False


def generate_barcode(session: Session, *, sku: str, name: str, pack_level: str = "base", uom: str = "", factor: str = "1") -> str:
    prefix = {"base": "20", "transaction": "21", "inner": "22", "outer": "23", "pallet": "24"}.get(pack_level)
    if not prefix:
        raise ValueError("Invalid barcode pack role")
    for attempt in range(1000):
        value = ean13(f"{sku}|{name}|{pack_level}|{uom}|{factor}|{attempt}", prefix)
        if not barcode_taken(session, value):
            return value
    raise ValueError("Unable to generate an available EAN-13 barcode")


def product_record(session: Session, sku: str) -> dict | None:
    master = session.scalar(select(OperationalProductMaster).where(OperationalProductMaster.sku == sku))
    if not master:
        return None
    details = session.scalar(select(OperationalProductDetails).where(OperationalProductDetails.sku == sku))
    body = json.loads(details.payload_json) if details else {
        "sku": master.sku, "name": master.name, "short_name": master.name[:160],
        "category_name": master.category_name or "Uncategorised", "brand_name": master.brand_name,
        "product_type": master.product_type, "base_uom": master.base_uom,
        "is_stock_item": True, "track_lots": False, "track_expiry": False,
        "reorder_point_base": "0", "country_of_origin": "AE",
        "standard_cost": str(master.purchase_price), "default_sales_price": str(master.selling_price),
        "purchase_vat_rate": format(master.tax_rate.normalize(), "f"),
        "sales_vat_rate": format(master.tax_rate.normalize(), "f"),
        "barcode_format": "internal_ean13", "specifications": [],
    }
    conversions = session.scalars(select(OperationalProductUomConversion).where(
        OperationalProductUomConversion.sku == sku, OperationalProductUomConversion.pack_level != "base").order_by(OperationalProductUomConversion.id)).all()
    body["uom_conversions"] = [{"uom": c.uom, "factor_to_base": str(c.factor_to_base), "pack_level": c.pack_level,
        "barcode": c.barcode_value, "allow_purchase": c.allow_purchase, "allow_sale": c.allow_sale,
        "is_default_purchase": c.is_default_purchase, "is_default_sale": c.is_default_sale} for c in conversions]
    body["category_name"] = saved_master_name(session, "category", body["category_name"])
    body["base_uom"] = saved_master_name(session, "uom", body["base_uom"])
    for conversion in body["uom_conversions"]:
        conversion["uom"] = saved_master_name(session, "uom", conversion["uom"])
    return {**body, "status": master.status, "revision": master.revision, "source_promoted": master.source_promoted}


def _check_change(session: Session, payload: ProductEditor, existing_sku: str | None = None) -> None:
    key = duplicate_key(payload)
    match = session.scalar(select(OperationalProductDetails.sku).where(OperationalProductDetails.duplicate_key == key))
    if match and match != existing_sku:
        raise ValueError(f"Duplicate product structure already exists as {match}")
    pending = session.scalars(select(ProductChangeRequest).where(ProductChangeRequest.status == "pending")).all()
    for row in pending:
        if row.sku == payload.sku or (row.duplicate_key == key and row.sku != existing_sku):
            raise ValueError(f"A pending product change already exists for {row.sku}")
    for code in [payload.barcode, *(c.barcode for c in payload.uom_conversions)]:
        if code and barcode_taken(session, code):
            current = product_record(session, existing_sku) if existing_sku else None
            allowed = {current.get("barcode"), *(c["barcode"] for c in current.get("uom_conversions", []))} if current else set()
            if code not in allowed:
                raise ValueError(f"Barcode {code} is already registered")


def propose_product(session: Session, payload: ProductEditor, *, actor: str, expected_revision: int | None = None) -> ProductChangeRequest:
    validate_product_taxonomy(session, payload.category_name,
        [payload.base_uom, *(conversion.uom for conversion in payload.uom_conversions)])
    sku = payload.sku.strip()
    existing = session.scalar(select(OperationalProductMaster).where(OperationalProductMaster.sku == sku))
    if existing and expected_revision is None:
        raise ValueError("SKU already exists; open the product to propose an amendment")
    if not existing and expected_revision is not None:
        raise ValueError("Product no longer exists")
    if existing and existing.revision != expected_revision:
        raise ValueError(f"Product revision conflict; current revision is {existing.revision}")
    if existing:
        current = product_record(session, sku)
        if current.get("barcode") and payload.barcode != current["barcode"]:
            raise ValueError("Saved master barcode is immutable")
        incoming = {c.uom.casefold(): c for c in payload.uom_conversions}
        for old in current["uom_conversions"]:
            if not old["barcode"]:
                continue
            new = incoming.get(old["uom"].casefold())
            if not new or new.barcode != old["barcode"] or new.pack_level != old["pack_level"] or new.factor_to_base != Decimal(old["factor_to_base"]):
                raise ValueError("Barcoded pack unit, role and factor are immutable")
        if payload.base_uom.casefold() != existing.base_uom.casefold() and session.scalar(select(OperationalProductUomConversion.id).where(OperationalProductUomConversion.sku == sku)):
            raise ValueError("Base stock unit cannot change after conversions are registered")
    _check_change(session, payload, sku if existing else None)
    row = ProductChangeRequest(change_key=str(uuid.uuid4()), sku=sku, action="amend" if existing else "create",
        expected_revision=expected_revision, payload_json=payload.model_dump_json(), duplicate_key=duplicate_key(payload),
        created_by=actor)
    session.add(row)
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="master.product.change_requested",
        actor=actor, resource_key=row.change_key, detail=f"{row.action}; SKU {sku}; pending independent approval"))
    session.commit()
    return row


def propose_product_status(session: Session, sku: str, *, actor: str, action: str,
                           expected_revision: int, note: str) -> ProductChangeRequest:
    if action not in {"deactivate", "reactivate"}:
        raise ValueError("Unsupported product status action")
    master = session.scalar(select(OperationalProductMaster).where(OperationalProductMaster.sku == sku).with_for_update())
    if not master:
        raise ValueError("Operational product not found")
    if master.revision != expected_revision:
        raise ValueError(f"Product revision conflict; current revision is {master.revision}")
    target = "inactive" if action == "deactivate" else "active"
    if master.status == target:
        raise ValueError(f"Product is already {target}")
    if session.scalar(select(ProductChangeRequest.id).where(ProductChangeRequest.sku == sku,
                                                             ProductChangeRequest.status == "pending")):
        raise ValueError("A pending product change already exists")
    row = ProductChangeRequest(change_key=str(uuid.uuid4()), sku=sku, action=action,
        expected_revision=expected_revision, payload_json=json.dumps({"note": note}),
        duplicate_key=hashlib.sha256(f"{sku}|{action}|{expected_revision}".encode()).hexdigest(), created_by=actor)
    session.add(row)
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="master.product.status_requested",
        actor=actor, resource_key=row.change_key, detail=f"{sku}; {action}; {note}; pending independent approval"))
    session.commit()
    return row


def decide_product(session: Session, change_key: str, *, actor: str, action: str, note: str) -> ProductChangeRequest:
    row = session.scalar(select(ProductChangeRequest).where(ProductChangeRequest.change_key == change_key).with_for_update())
    if not row or row.status != "pending":
        raise ValueError("Pending product change not found")
    if actor == row.created_by:
        raise ValueError("Maker cannot approve or reject their own product change")
    if action not in {"approve", "reject"}:
        raise ValueError("Decision must be approve or reject")
    if action == "approve":
        if row.action in {"deactivate", "reactivate"}:
            master = session.scalar(select(OperationalProductMaster).where(OperationalProductMaster.sku == row.sku).with_for_update())
            if not master or master.revision != row.expected_revision:
                raise ValueError("Product changed since this status request")
            master.status = "inactive" if row.action == "deactivate" else "active"
            master.revision += 1
            master.updated_by = actor
            master.updated_at = utc_now()
            row.status, row.decided_by, row.decided_at, row.decision_note = "approved", actor, utc_now(), note
            session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="master.product.approved",
                actor=actor, resource_key=row.change_key, detail=f"SKU {row.sku}; {row.action}; {note}"))
            session.commit()
            return row
        payload = ProductEditor.model_validate_json(row.payload_json)
        validate_product_taxonomy(session, payload.category_name,
            [payload.base_uom, *(conversion.uom for conversion in payload.uom_conversions)])
        master = session.scalar(select(OperationalProductMaster).where(OperationalProductMaster.sku == row.sku).with_for_update())
        if row.action == "create" and master or row.action == "amend" and (not master or master.revision != row.expected_revision):
            raise ValueError("Product changed since this proposal; create a new revision")
        if row.action == "create":
            master = OperationalProductMaster(product_key=str(uuid.uuid4()), sku=row.sku, name=payload.name,
                base_uom=payload.base_uom, canonical_base_uom=canonical_uom(payload.base_uom) or payload.base_uom.casefold(),
                factor_to_base=Decimal("1"), status="active", source_promoted=False, source_snapshot_name="target-product-editor",
                source_checksum=row.duplicate_key, created_by=row.created_by, updated_by=actor)
            session.add(master)
        else:
            current = product_record(session, row.sku)
            if current.get("barcode") and payload.barcode != current["barcode"]:
                raise ValueError("Saved master barcode is immutable")
            old_conversions = {c["uom"].casefold(): c for c in current["uom_conversions"]}
            incoming = {c.uom.casefold(): c for c in payload.uom_conversions}
            for unit, old in old_conversions.items():
                if old["barcode"] and (unit not in incoming or incoming[unit].barcode != old["barcode"] or incoming[unit].pack_level != old["pack_level"] or incoming[unit].factor_to_base != Decimal(old["factor_to_base"])):
                    raise ValueError("Barcoded pack unit, role and factor are immutable")
        # Recheck at the approval boundary; generated candidates were never reservations.
        current_codes = set()
        if row.action == "amend":
            current = product_record(session, row.sku)
            current_codes = {current.get("barcode"), *(c["barcode"] for c in current["uom_conversions"])}
        for code in [payload.barcode, *(c.barcode for c in payload.uom_conversions)]:
            if code and code not in current_codes and barcode_taken(session, code):
                raise ValueError(f"Barcode {code} was registered by another product")
        master.name = payload.name
        master.product_type = payload.product_type
        master.category_name = payload.category_name
        master.brand_name = payload.brand_name
        master.base_uom = payload.base_uom
        master.canonical_base_uom = canonical_uom(payload.base_uom) or payload.base_uom.casefold()
        master.purchase_price = payload.standard_cost
        master.selling_price = payload.default_sales_price
        master.tax_rate = payload.sales_vat_rate
        master.updated_by = actor
        master.updated_at = utc_now()
        if row.action == "amend":
            master.revision += 1
        details = session.scalar(select(OperationalProductDetails).where(OperationalProductDetails.sku == row.sku))
        if not details:
            details = OperationalProductDetails(sku=row.sku, payload_json="{}", duplicate_key=row.duplicate_key)
            session.add(details)
        details.payload_json = payload.model_dump_json(exclude={"uom_conversions"})
        details.duplicate_key = row.duplicate_key
        old_rows = session.scalars(select(OperationalProductUomConversion).where(OperationalProductUomConversion.sku == row.sku)).all()
        old_by_unit = {c.uom.casefold(): c for c in old_rows}
        desired = {c.uom.casefold() for c in payload.uom_conversions}
        for old in old_rows:
            if old.pack_level != "base" and old.uom.casefold() not in desired:
                if old.barcode_value:
                    raise ValueError("A barcoded pack conversion cannot be removed")
                session.delete(old)
        for conversion in payload.uom_conversions:
            unit = old_by_unit.get(conversion.uom.casefold())
            if not unit:
                unit = OperationalProductUomConversion(conversion_key=str(uuid.uuid4()), sku=row.sku, uom=conversion.uom,
                    canonical_uom=master.canonical_base_uom, factor_to_base=conversion.factor_to_base,
                    pack_level=conversion.pack_level, created_by=actor)
                session.add(unit)
            unit.factor_to_base = conversion.factor_to_base
            unit.pack_level = conversion.pack_level
            unit.allow_purchase = conversion.allow_purchase
            unit.allow_sale = conversion.allow_sale
            unit.is_default_purchase = conversion.is_default_purchase
            unit.is_default_sale = conversion.is_default_sale
            unit.barcode_value = conversion.barcode
            if conversion.barcode and conversion.barcode not in current_codes:
                session.add(OperationalBarcodeIdentity(barcode_key=str(uuid.uuid4()), barcode_value=conversion.barcode,
                    sku=row.sku, canonical_uom=master.canonical_base_uom, factor_to_base=conversion.factor_to_base,
                    registration_location_code="PRODUCT-MASTER", created_by=actor))
        if payload.barcode and payload.barcode not in current_codes:
            session.add(OperationalBarcodeIdentity(barcode_key=str(uuid.uuid4()), barcode_value=payload.barcode,
                sku=row.sku, canonical_uom=master.canonical_base_uom, factor_to_base=Decimal("1"),
                registration_location_code="PRODUCT-MASTER", created_by=actor))
    row.status = "approved" if action == "approve" else "rejected"
    row.decided_by = actor
    row.decided_at = utc_now()
    row.decision_note = note
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"master.product.{row.status}",
        actor=actor, resource_key=row.change_key, detail=f"SKU {row.sku}; {note}"))
    session.commit()
    return row


def change_payload(row: ProductChangeRequest) -> dict:
    return {"change_key": row.change_key, "sku": row.sku, "action": row.action, "status": row.status,
        "created_by": row.created_by, "created_at": row.created_at, "decided_by": row.decided_by,
        "decision_note": row.decision_note, "expected_revision": row.expected_revision}
