"""Non-posting commercial pricing controls used by customer quotations."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, Numeric, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .operational import OperationalAuditEvent, OperationalBase


class OperationalCustomerPriceGroup(OperationalBase):
    __tablename__ = "operational_customer_price_groups"
    __table_args__ = (UniqueConstraint("group_code", name="uq_customer_price_group_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)


class OperationalCustomerPriceGroupAssignment(OperationalBase):
    __tablename__ = "operational_customer_price_group_assignments"
    __table_args__ = (UniqueConstraint("customer_code", name="uq_customer_price_group_customer"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    group_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    assigned_by: Mapped[str] = mapped_column(String(200), nullable=False)


class OperationalPriceList(OperationalBase):
    __tablename__ = "operational_price_lists"
    __table_args__ = (CheckConstraint("status IN ('draft','approved','expired','superseded')", name="ck_price_list_status"), CheckConstraint("max_discount_percent >= 0 AND max_discount_percent <= 100", name="ck_price_list_discount"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    price_list_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    customer_group: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    max_discount_percent: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(200))


class OperationalPriceListItem(OperationalBase):
    __tablename__ = "operational_price_list_items"
    __table_args__ = (UniqueConstraint("price_list_id", "sku", name="uq_price_list_item_sku"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    price_list_id: Mapped[int] = mapped_column(ForeignKey("operational_price_lists.id", ondelete="CASCADE"), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)


class OperationalPromotion(OperationalBase):
    __tablename__ = "operational_commercial_promotions"
    __table_args__ = (UniqueConstraint("promotion_code", name="uq_commercial_promotion_code"), CheckConstraint("status IN ('draft','approved','expired','cancelled')", name="ck_commercial_promotion_status"), CheckConstraint("discount_percent > 0 AND discount_percent <= 100", name="ck_commercial_promotion_discount"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    promotion_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    promotion_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    customer_group: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    sku: Mapped[str | None] = mapped_column(String(100), index=True)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(200))


def _audit(session, actor, event_type, key, detail):
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=event_type, actor=actor, resource_key=key, detail=detail))


def _check_dates(effective_from, effective_to):
    if effective_to and effective_to < effective_from: raise ValueError("Effective-to date cannot be earlier than effective-from date")


def create_customer_price_group(session, *, group_code, name, actor):
    code = group_code.strip().upper()
    if not code or session.scalar(select(OperationalCustomerPriceGroup).where(OperationalCustomerPriceGroup.group_code == code)): raise ValueError("Customer price group must be unique")
    row = OperationalCustomerPriceGroup(group_code=code, name=name.strip(), created_by=actor); session.add(row); _audit(session, actor, "pricing.group.created", code, "non-posting customer price group"); session.commit(); return row


def assign_customer_price_group(session, *, customer_code, group_code, actor):
    code = group_code.strip().upper()
    if not session.scalar(select(OperationalCustomerPriceGroup).where(OperationalCustomerPriceGroup.group_code == code, OperationalCustomerPriceGroup.status == "active")): raise ValueError("Customer price group is not active")
    row = session.scalar(select(OperationalCustomerPriceGroupAssignment).where(OperationalCustomerPriceGroupAssignment.customer_code == customer_code))
    if row: row.group_code, row.assigned_by = code, actor
    else: row = OperationalCustomerPriceGroupAssignment(customer_code=customer_code, group_code=code, assigned_by=actor); session.add(row)
    _audit(session, actor, "pricing.customer_group.assigned", customer_code, f"group {code}; non-posting"); session.commit(); return row


def create_price_list(session, *, name, customer_group, effective_from, effective_to, max_discount_percent, items, actor):
    _check_dates(effective_from, effective_to); group = customer_group.strip().upper(); discount = Decimal(str(max_discount_percent))
    if not items: raise ValueError("At least one price item is required")
    if not session.scalar(select(OperationalCustomerPriceGroup.id).where(OperationalCustomerPriceGroup.group_code == group, OperationalCustomerPriceGroup.status == "active")): raise ValueError("Customer price group is not active")
    skus = [str(item["sku"]).strip() for item in items]
    if discount < 0 or discount > 100 or not all(skus) or len(skus) != len(set(skus)) or any(Decimal(str(item["unit_price"])) < 0 for item in items): raise ValueError("Invalid price-list discount, SKU, or unit price")
    key = str(uuid.uuid4()); row = OperationalPriceList(price_list_key=key, name=name.strip(), customer_group=group, effective_from=effective_from, effective_to=effective_to, max_discount_percent=discount, created_by=actor); session.add(row); session.flush()
    for item in items: session.add(OperationalPriceListItem(price_list_id=row.id, sku=str(item["sku"]).strip(), unit_price=Decimal(str(item["unit_price"]))))
    _audit(session, actor, "pricing.list.created", key, "draft commercial price list; non-posting"); session.commit(); return row


def _overlaps(left_from, left_to, right_from, right_to): return (left_to is None or right_from <= left_to) and (right_to is None or left_from <= right_to)


def approve_price_list(session, *, key, actor):
    row = session.scalar(select(OperationalPriceList).where(OperationalPriceList.price_list_key == key))
    if not row: raise ValueError("Price list not found")
    if row.created_by == actor: raise PermissionError("Maker-checker control prevents price-list self-approval")
    if row.status != "draft": raise ValueError("Price list is no longer awaiting approval")
    approved = session.scalars(select(OperationalPriceList).where(OperationalPriceList.customer_group == row.customer_group, OperationalPriceList.status == "approved")).all()
    if any(_overlaps(row.effective_from, row.effective_to, old.effective_from, old.effective_to) for old in approved): raise ValueError("Approved price lists for a customer group cannot have overlapping effective periods")
    row.status = "approved"; row.approved_by = actor; _audit(session, actor, "pricing.list.approved", key, "independent commercial approval; non-posting"); session.commit(); return row


def create_promotion(session, *, promotion_code, name, customer_group, sku, discount_percent, effective_from, effective_to, actor):
    _check_dates(effective_from, effective_to); group = customer_group.strip().upper(); code = promotion_code.strip().upper(); discount = Decimal(str(discount_percent))
    if not session.scalar(select(OperationalCustomerPriceGroup.id).where(OperationalCustomerPriceGroup.group_code == group, OperationalCustomerPriceGroup.status == "active")): raise ValueError("Customer price group is not active")
    if not code or discount <= 0 or discount > 100 or session.scalar(select(OperationalPromotion.id).where(OperationalPromotion.promotion_code == code)): raise ValueError("Invalid or duplicate promotion")
    row = OperationalPromotion(promotion_key=str(uuid.uuid4()), promotion_code=code, name=name.strip(), customer_group=group, sku=sku.strip() if sku else None, discount_percent=discount, effective_from=effective_from, effective_to=effective_to, created_by=actor); session.add(row); _audit(session, actor, "pricing.promotion.created", row.promotion_key, "draft promotion; non-posting"); session.commit(); return row


def approve_promotion(session, *, promotion_key, actor):
    row = session.scalar(select(OperationalPromotion).where(OperationalPromotion.promotion_key == promotion_key))
    if not row: raise ValueError("Promotion not found")
    if row.created_by == actor: raise PermissionError("Maker-checker control prevents promotion self-approval")
    if row.status != "draft": raise ValueError("Promotion is no longer awaiting approval")
    row.status = "approved"; row.approved_by = actor; _audit(session, actor, "pricing.promotion.approved", row.promotion_key, "independent commercial approval; non-posting"); session.commit(); return row


def enforce_quotation_pricing(session, *, customer_code, quotation_date, lines, discount_amount, promotion_code=None):
    assignment = session.scalar(select(OperationalCustomerPriceGroupAssignment).where(OperationalCustomerPriceGroupAssignment.customer_code == customer_code))
    if not assignment: return {"customer_group": None, "price_list_key": None, "promotion_key": None}
    group = assignment.group_code; lists = session.scalars(select(OperationalPriceList).where(OperationalPriceList.customer_group == group, OperationalPriceList.status == "approved", OperationalPriceList.effective_from <= quotation_date)).all(); lists = [row for row in lists if row.effective_to is None or row.effective_to >= quotation_date]
    if len(lists) != 1: raise ValueError("Customer price group requires exactly one approved effective price list")
    price_list = lists[0]; subtotal = sum((Decimal(str(line["net_amount"])) for line in lines), Decimal("0")); discount_pct = Decimal(str(discount_amount)) * Decimal("100") / subtotal if subtotal else Decimal("0")
    promotion = None
    if promotion_code:
        promotion = session.scalar(select(OperationalPromotion).where(OperationalPromotion.promotion_code == promotion_code.strip().upper(), OperationalPromotion.status == "approved", OperationalPromotion.customer_group == group, OperationalPromotion.effective_from <= quotation_date))
        if not promotion or (promotion.effective_to and promotion.effective_to < quotation_date): raise ValueError("Promotion is not approved and effective for this customer group")
        if promotion.sku and any(str(line["sku"]) != promotion.sku for line in lines): raise ValueError("Promotion applies only to its configured SKU")
    permitted = max(price_list.max_discount_percent, promotion.discount_percent if promotion else Decimal("0"))
    if discount_pct > permitted: raise ValueError("Requested discount exceeds the approved price-list or promotion limit")
    items = {item.sku: item for item in session.scalars(select(OperationalPriceListItem).where(OperationalPriceListItem.price_list_id == price_list.id)).all()}
    for line in lines:
        item = items.get(str(line["sku"]))
        if not item: raise ValueError(f"Approved price list has no price for {line['sku']}")
        if Decimal(str(line["unit_price"])) != item.unit_price: raise ValueError(f"Quotation price for {line['sku']} does not match its approved price list")
    return {"customer_group": group, "price_list_key": price_list.price_list_key, "promotion_key": promotion.promotion_key if promotion else None}
