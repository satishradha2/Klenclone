from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, Numeric, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .data_governance import OperationalPromotionBatch, OperationalSourceLineage
from .delta_overlay import DeltaOverlay
from .models import ErpLocation, ErpParty, ErpProductMaster, ErpProductUom, RawFileManifest, SourceSnapshot
from .operational import OperationalAuditEvent, OperationalBase, utc_now


class OperationalPartyMaster(OperationalBase):
    __tablename__ = "operational_party_masters"
    __table_args__ = (
        UniqueConstraint("party_code", name="uq_operational_party_code"),
        CheckConstraint("party_kind IN ('customer','supplier','both')", name="ck_operational_party_kind"),
        CheckConstraint("status IN ('active','inactive')", name="ck_operational_party_status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    party_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    party_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    party_kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    legal_or_business_name: Mapped[str] = mapped_column(String(500), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(300))
    email: Mapped[str | None] = mapped_column(String(320))
    mobile: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(Text)
    tax_number: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    source_promoted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source_snapshot_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalProductMaster(OperationalBase):
    __tablename__ = "operational_product_masters"
    __table_args__ = (
        UniqueConstraint("sku", name="uq_operational_product_sku"),
        CheckConstraint("status IN ('active','inactive')", name="ck_operational_product_status"),
        CheckConstraint("purchase_price >= 0 AND selling_price >= 0", name="ck_operational_product_prices"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    sku: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    product_type: Mapped[str | None] = mapped_column(String(80))
    category_name: Mapped[str | None] = mapped_column(String(200))
    brand_name: Mapped[str | None] = mapped_column(String(200))
    base_uom: Mapped[str] = mapped_column(String(80), nullable=False)
    canonical_base_uom: Mapped[str] = mapped_column(String(80), nullable=False)
    factor_to_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=1, nullable=False)
    purchase_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=0, nullable=False)
    selling_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=0, nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=5, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    source_promoted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source_snapshot_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalLocationMaster(OperationalBase):
    __tablename__ = "operational_location_masters"
    __table_args__ = (
        UniqueConstraint("location_code", name="uq_operational_location_code"),
        CheckConstraint("status IN ('active','inactive')", name="ck_operational_location_status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    source_snapshot_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


def _digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, default=str, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _manifest_digest(clone: Session, snapshot: SourceSnapshot, overlay: DeltaOverlay | None) -> str:
    if overlay and (overlay.capture_path / "SHA256SUMS.txt").is_file():
        return hashlib.sha256((overlay.capture_path / "SHA256SUMS.txt").read_bytes()).hexdigest()
    values = clone.scalars(select(RawFileManifest.sha256).where(
        RawFileManifest.snapshot_id == snapshot.id).order_by(RawFileManifest.relative_path)).all()
    return hashlib.sha256("".join(values).encode()).hexdigest()


def promote_operational_masters(clone: Session, operational: Session, snapshot: SourceSnapshot,
                                overlay: DeltaOverlay | None, *, actor: str) -> dict:
    manifest = _manifest_digest(clone, snapshot, overlay)
    batch_key = f"MASTER-{manifest[:24].upper()}"
    existing = operational.scalar(select(OperationalPromotionBatch).where(
        OperationalPromotionBatch.batch_key == batch_key))
    if existing:
        return {"status": existing.status, "batch_key": batch_key,
                "expected_records": existing.expected_records, "mapped_records": existing.mapped_records,
                "exception_records": existing.exception_records, "idempotent_replay": True,
                "posting_enabled": False}

    product_uoms = {row.product_id: row for row in clone.scalars(select(ErpProductUom).where(
        ErpProductUom.snapshot_id == snapshot.id)).all()}
    products = {}
    for row in clone.scalars(select(ErpProductMaster).where(ErpProductMaster.snapshot_id == snapshot.id)).all():
        uom = product_uoms.get(row.id)
        products[row.sku] = {"sku": row.sku, "name": row.name, "product_type": row.product_type,
            "category_name": row.category_name, "brand_name": row.brand_name,
            "base_uom": (uom.source_base_uom if uom else None) or "piece",
            "canonical_base_uom": (uom.canonical_base_uom if uom else None) or "piece",
            "factor_to_base": (uom.factor_to_base_snapshot if uom else 1),
            "purchase_price": row.purchase_price_evidence or 0, "selling_price": row.selling_price_evidence or 0}
    if overlay:
        for row in overlay.product_records():
            products[row["sku"]] = {"sku": row["sku"], "name": row["name"],
                "product_type": None, "category_name": row["category_name"], "brand_name": row["brand_name"],
                "base_uom": row["base_uom"] or "piece", "canonical_base_uom": (row["base_uom"] or "piece").casefold(),
                "factor_to_base": 1, "purchase_price": row["purchase_price_evidence"],
                "selling_price": row["selling_price_evidence"]}

    parties = {}
    for row in clone.scalars(select(ErpParty).where(ErpParty.snapshot_id == snapshot.id)).all():
        parties[row.party_code] = {"party_code": row.party_code, "party_kind": row.party_kind,
            "legal_or_business_name": row.legal_or_business_name, "contact_name": row.contact_name,
            "email": row.email, "mobile": row.mobile, "address": row.address, "tax_number": row.tax_number}
    if overlay:
        for kind in ("customer", "supplier"):
            for row in overlay.party_records(kind):
                current = parties.get(row["party_code"])
                party_kind = ("both" if current and current["party_kind"] != kind else kind)
                parties[row["party_code"]] = {"party_code": row["party_code"], "party_kind": party_kind,
                    "legal_or_business_name": row["legal_or_business_name"], "contact_name": row["contact_name"],
                    "email": None, "mobile": None, "address": None, "tax_number": None}

    locations = [{"location_code": row.code, "name": row.name, "address": row.address}
                 for row in clone.scalars(select(ErpLocation).where(ErpLocation.snapshot_id == snapshot.id)).all()]
    expected = len(products) + len(parties) + len(locations)
    if operational.scalar(select(OperationalProductMaster.id).limit(1)) or operational.scalar(select(OperationalPartyMaster.id).limit(1)):
        raise ValueError("Operational master tables are not empty; promotion requires an idempotent batch or explicit reconciliation")
    batch = OperationalPromotionBatch(batch_key=batch_key, source_system="BizModo V7.5.1",
        source_snapshot_name=snapshot.name, source_manifest_checksum=manifest, status="planned",
        posting_enabled=False, expected_records=expected, mapped_records=0, exception_records=0,
        created_by=actor)
    operational.add(batch); operational.flush()

    mapped = 0
    for payload in products.values():
        checksum = _digest(payload)
        record = OperationalProductMaster(product_key=str(uuid.uuid4()), **payload, tax_rate=5,
            status="active", source_promoted=True, source_snapshot_name=snapshot.name,
            source_checksum=checksum, created_by=actor, updated_by=actor)
        operational.add(record); operational.flush()
        operational.add(OperationalSourceLineage(batch_id=batch.id, source_system="BizModo V7.5.1",
            source_snapshot_name=snapshot.name, entity_type="product", source_record_key=payload["sku"],
            source_checksum=checksum, operational_table=record.__tablename__, operational_record_key=record.product_key,
            promoted_checksum=checksum, promotion_status="promoted", lifecycle_status="active", promoted_at=utc_now()))
        mapped += 1
    for payload in parties.values():
        checksum = _digest(payload)
        record = OperationalPartyMaster(party_key=str(uuid.uuid4()), **payload, status="active",
            source_promoted=True, source_snapshot_name=snapshot.name, source_checksum=checksum,
            created_by=actor, updated_by=actor)
        operational.add(record); operational.flush()
        operational.add(OperationalSourceLineage(batch_id=batch.id, source_system="BizModo V7.5.1",
            source_snapshot_name=snapshot.name, entity_type="party", source_record_key=payload["party_code"],
            source_checksum=checksum, operational_table=record.__tablename__, operational_record_key=record.party_key,
            promoted_checksum=checksum, promotion_status="promoted", lifecycle_status="active", promoted_at=utc_now()))
        mapped += 1
    for payload in locations:
        checksum = _digest(payload)
        record = OperationalLocationMaster(location_key=str(uuid.uuid4()), **payload, status="active",
            source_snapshot_name=snapshot.name, source_checksum=checksum, created_by=actor)
        operational.add(record); operational.flush()
        operational.add(OperationalSourceLineage(batch_id=batch.id, source_system="BizModo V7.5.1",
            source_snapshot_name=snapshot.name, entity_type="location", source_record_key=payload["location_code"],
            source_checksum=checksum, operational_table=record.__tablename__, operational_record_key=record.location_key,
            promoted_checksum=checksum, promotion_status="promoted", lifecycle_status="active", promoted_at=utc_now()))
        mapped += 1
    batch.mapped_records = mapped
    batch.status = "executed"
    operational.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="promotion.executed",
        actor=actor, resource_key=batch_key,
        detail=f"staging master promotion; {mapped} records; posting disabled; source immutable"))
    operational.commit()
    return {"status": "executed", "batch_key": batch_key, "expected_records": expected,
            "mapped_records": mapped, "exception_records": 0, "idempotent_replay": False,
            "posting_enabled": False}
