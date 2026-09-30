"""Database-owned category and unit choices for the governed product editor."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .operational import OperationalAuditEvent, OperationalBase, utc_now
from .operational_masters import OperationalProductMaster
from .warehouse_controls import OperationalProductUomConversion


class OperationalProductCategory(OperationalBase):
    __tablename__ = "operational_product_categories"
    __table_args__ = (UniqueConstraint("normalized_name", name="uq_product_category_normalized"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalUomMaster(OperationalBase):
    __tablename__ = "operational_uom_masters"
    __table_args__ = (UniqueConstraint("normalized_name", name="uq_operational_uom_normalized"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


def normalize_master_name(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


def _insert_missing(session: Session, model, values: list[str], *, actor: str) -> int:
    known = set(session.scalars(select(model.normalized_name)).all())
    inserted = 0
    for raw in sorted(values, key=lambda value: (normalize_master_name(value), value)):
        name = " ".join(raw.strip().split())
        normalized = normalize_master_name(name)
        if not normalized or normalized in known:
            continue
        if model is OperationalProductCategory:
            session.add(model(category_key=str(uuid.uuid4()), name=name,
                              normalized_name=normalized, created_by=actor))
        else:
            session.add(model(unit_key=str(uuid.uuid4()), name=name,
                              normalized_name=normalized, created_by=actor))
        known.add(normalized)
        inserted += 1
    return inserted


def backfill_product_taxonomy(session: Session, *, actor: str = "operational-migration") -> dict[str, int]:
    """Copy existing target-master labels once; never query BizModo or invent choices."""
    products = session.scalars(select(OperationalProductMaster)).all()
    conversions = session.scalars(select(OperationalProductUomConversion)).all()
    categories = _insert_missing(session, OperationalProductCategory,
        [row.category_name or "Uncategorised" for row in products], actor=actor)
    units = _insert_missing(session, OperationalUomMaster,
        [row.base_uom for row in products] + [row.uom for row in conversions], actor=actor)
    return {"categories": categories, "units": units}


def create_product_taxonomy_value(session: Session, kind: str, name: str, *, actor: str):
    model = {"category": OperationalProductCategory, "uom": OperationalUomMaster}.get(kind)
    if model is None:
        raise ValueError("Unknown product master type")
    clean = " ".join(name.strip().split())
    limit = 200 if kind == "category" else 80
    if not clean or len(clean) > limit:
        raise ValueError(f"{kind.title()} name must be 1–{limit} characters")
    normalized = normalize_master_name(clean)
    if session.scalar(select(model.id).where(model.normalized_name == normalized)):
        raise ValueError(f"{kind.title()} already exists")
    if kind == "category":
        row = model(category_key=str(uuid.uuid4()), name=clean,
                    normalized_name=normalized, created_by=actor)
    else:
        row = model(unit_key=str(uuid.uuid4()), name=clean,
                    normalized_name=normalized, created_by=actor)
    session.add(row)
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"master.product_{kind}.created",
        actor=actor, resource_key=(row.category_key if kind == "category" else row.unit_key),
        detail=f"Created {kind} {clean} for the controlled product dropdown"))
    session.commit()
    return row


def active_product_taxonomy(session: Session) -> dict[str, list[str]]:
    return {
        "categories": list(session.scalars(select(OperationalProductCategory.name).order_by(OperationalProductCategory.name))),
        "units": list(session.scalars(select(OperationalUomMaster.name).order_by(OperationalUomMaster.name))),
    }


def validate_product_taxonomy(session: Session, category: str, units: list[str]) -> None:
    choices = active_product_taxonomy(session)
    categories = {normalize_master_name(value) for value in choices["categories"]}
    allowed_units = {normalize_master_name(value) for value in choices["units"]}
    if normalize_master_name(category) not in categories:
        raise ValueError("Choose a saved product category from Master setup")
    for unit in units:
        if normalize_master_name(unit) not in allowed_units:
            raise ValueError(f"Unit {unit!r} is not saved in Product master setup")


def saved_master_name(session: Session, kind: str, value: str) -> str:
    model = OperationalProductCategory if kind == "category" else OperationalUomMaster
    return session.scalar(select(model.name).where(model.normalized_name == normalize_master_name(value))) or value
