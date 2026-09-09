from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .operational import MONEY, OperationalAuditEvent, OperationalBase, OperationalFiscalPeriod, utc_now


class OperationalGoodsReceipt(OperationalBase):
    __tablename__ = "operational_goods_receipts"
    __table_args__ = (
        CheckConstraint("status IN ('draft','submitted','accepted','rejected','cancelled','posted','reversed')", name="ck_goods_receipt_status"),
        CheckConstraint("posting_enabled = false", name="ck_goods_receipt_no_posting"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    receipt_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    supplier_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    supplier_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    purchase_reference: Mapped[str | None] = mapped_column(String(160), index=True)
    supplier_delivery_note: Mapped[str | None] = mapped_column(String(160))
    received_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False, index=True)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    state_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    state_changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    lines: Mapped[list["OperationalGoodsReceiptLine"]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan", order_by="OperationalGoodsReceiptLine.line_no"
    )


class OperationalGoodsReceiptLine(OperationalBase):
    __tablename__ = "operational_goods_receipt_lines"
    __table_args__ = (
        UniqueConstraint("receipt_id", "line_no", name="uq_goods_receipt_line"),
        CheckConstraint("ordered_quantity IS NULL OR ordered_quantity >= 0", name="ck_grn_ordered_quantity"),
        CheckConstraint("received_quantity > 0", name="ck_grn_received_quantity"),
        CheckConstraint("accepted_quantity >= 0 AND rejected_quantity >= 0", name="ck_grn_inspection_quantities"),
        CheckConstraint("accepted_quantity + rejected_quantity = received_quantity", name="ck_grn_quantity_conservation"),
        CheckConstraint("factor_to_base_snapshot > 0", name="ck_grn_factor"),
        CheckConstraint("accepted_quantity_base >= 0", name="ck_grn_accepted_base"),
        CheckConstraint("unit_cost_snapshot >= 0 AND accepted_value >= 0", name="ck_grn_value"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("operational_goods_receipts.id", ondelete="CASCADE"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    product_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    ordered_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    accepted_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    rejected_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    uom: Mapped[str] = mapped_column(String(80), nullable=False)
    canonical_uom: Mapped[str] = mapped_column(String(80), nullable=False)
    factor_to_base_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    accepted_quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_cost_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    accepted_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    batch_no: Mapped[str | None] = mapped_column(String(160), index=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, index=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500))
    receipt: Mapped[OperationalGoodsReceipt] = relationship(back_populates="lines")


class OperationalGoodsReceiptWorkflowEvent(OperationalBase):
    __tablename__ = "operational_goods_receipt_workflow_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("operational_goods_receipts.id"), nullable=False, index=True)
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


def _line_values(raw: dict) -> dict:
    ordered = Decimal(str(raw["ordered_quantity"])) if raw.get("ordered_quantity") is not None else None
    received = Decimal(str(raw["received_quantity"]))
    accepted = Decimal(str(raw["accepted_quantity"]))
    rejected = Decimal(str(raw["rejected_quantity"]))
    factor = Decimal(str(raw["factor_to_base_snapshot"]))
    cost = Decimal(str(raw["unit_cost_snapshot"]))
    reason = (raw.get("rejection_reason") or "").strip() or None
    if received <= 0 or accepted < 0 or rejected < 0 or accepted + rejected != received:
        raise ValueError("Each receipt line must conserve quantity: accepted plus rejected must equal received")
    if ordered is not None and ordered < 0:
        raise ValueError("Ordered quantity cannot be negative")
    if factor <= 0 or cost < 0:
        raise ValueError("Receipt UOM factor must be positive and cost cannot be negative")
    if rejected > 0 and not reason:
        raise ValueError("A rejection reason is required when rejected quantity is greater than zero")
    accepted_base = accepted * factor
    return dict(raw, ordered_quantity=ordered, received_quantity=received,
                accepted_quantity=accepted, rejected_quantity=rejected,
                factor_to_base_snapshot=factor, unit_cost_snapshot=cost,
                accepted_quantity_base=accepted_base,
                accepted_value=(accepted_base * cost).quantize(MONEY, rounding=ROUND_HALF_UP),
                rejection_reason=reason)


def _replace_lines(receipt: OperationalGoodsReceipt, lines: list[dict]) -> None:
    receipt.lines.clear()
    for number, source in enumerate(lines, 1):
        raw = _line_values(source)
        receipt.lines.append(OperationalGoodsReceiptLine(
            line_no=number, sku=raw["sku"], product_name_snapshot=raw["product_name_snapshot"],
            ordered_quantity=raw["ordered_quantity"], received_quantity=raw["received_quantity"],
            accepted_quantity=raw["accepted_quantity"], rejected_quantity=raw["rejected_quantity"],
            uom=raw["uom"], canonical_uom=raw["canonical_uom"],
            factor_to_base_snapshot=raw["factor_to_base_snapshot"],
            accepted_quantity_base=raw["accepted_quantity_base"], unit_cost_snapshot=raw["unit_cost_snapshot"],
            accepted_value=raw["accepted_value"], batch_no=raw.get("batch_no"),
            expiry_date=raw.get("expiry_date"), rejection_reason=raw["rejection_reason"],
        ))


def create_goods_receipt(session: Session, *, supplier_code: str, supplier_name_snapshot: str,
                         location_code: str, purchase_reference: str | None,
                         supplier_delivery_note: str | None, received_on: date,
                         notes: str | None, actor: str, lines: list[dict]) -> OperationalGoodsReceipt:
    if not lines:
        raise ValueError("At least one goods receipt line is required")
    key = str(uuid.uuid4())
    receipt = OperationalGoodsReceipt(
        receipt_key=key, receipt_no=f"GRN-{key[:8].upper()}", supplier_code=supplier_code,
        supplier_name_snapshot=supplier_name_snapshot, location_code=location_code,
        purchase_reference=purchase_reference, supplier_delivery_note=supplier_delivery_note,
        received_on=received_on, status="draft", posting_enabled=False, notes=notes,
        created_by=actor, state_changed_by=actor,
    )
    _replace_lines(receipt, lines)
    session.add(receipt)
    session.flush()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="goods_receipt.created",
                                      actor=actor, resource_key=receipt.receipt_key,
                                      detail=f"{receipt.receipt_no}; {len(lines)} lines; posting disabled"))
    session.commit()
    return receipt


def replace_goods_receipt(session: Session, receipt: OperationalGoodsReceipt, *, expected_revision: int,
                          supplier_code: str, supplier_name_snapshot: str, location_code: str,
                          purchase_reference: str | None, supplier_delivery_note: str | None,
                          received_on: date, notes: str | None, actor: str,
                          lines: list[dict]) -> OperationalGoodsReceipt:
    if receipt.status != "draft":
        raise ValueError("Only draft-state goods receipts can be edited")
    if receipt.revision != expected_revision:
        raise ValueError(f"Goods receipt revision conflict; current revision is {receipt.revision}")
    if not lines:
        raise ValueError("At least one goods receipt line is required")
    receipt.supplier_code, receipt.supplier_name_snapshot = supplier_code, supplier_name_snapshot
    receipt.location_code, receipt.purchase_reference = location_code, purchase_reference
    receipt.supplier_delivery_note, receipt.received_on = supplier_delivery_note, received_on
    receipt.notes, receipt.revision = notes, receipt.revision + 1
    receipt.state_changed_at, receipt.state_changed_by = utc_now(), actor
    receipt.lines.clear()
    session.flush()
    _replace_lines(receipt, lines)
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="goods_receipt.edited",
                                      actor=actor, resource_key=receipt.receipt_key,
                                      detail=f"{receipt.receipt_no}; revision {receipt.revision}; posting disabled"))
    session.commit()
    return receipt


def list_goods_receipts(session: Session, *, allowed_locations: tuple[str, ...] = ("*",), limit: int = 100) -> list[OperationalGoodsReceipt]:
    query = select(OperationalGoodsReceipt)
    if "*" not in allowed_locations:
        query = query.where(OperationalGoodsReceipt.location_code.in_(allowed_locations))
    return list(session.scalars(query.order_by(OperationalGoodsReceipt.created_at.desc()).limit(limit)))


def transition_goods_receipt(session: Session, receipt: OperationalGoodsReceipt, *, expected_revision: int,
                             action: str, actor: str, note: str | None = None) -> OperationalGoodsReceipt:
    transitions = {("draft", "submit"): "submitted", ("draft", "cancel"): "cancelled",
                   ("submitted", "cancel"): "cancelled", ("submitted", "accept"): "accepted",
                   ("submitted", "reject"): "rejected"}
    if receipt.revision != expected_revision:
        raise ValueError(f"Goods receipt revision conflict; current revision is {receipt.revision}")
    target = transitions.get((receipt.status, action))
    if not target:
        raise ValueError(f"Action {action} is not allowed from {receipt.status}")
    if action in {"accept", "reject"} and receipt.created_by == actor:
        raise PermissionError("Maker-checker control prevents the creator from inspecting this goods receipt")
    accepted = sum((line.accepted_quantity for line in receipt.lines), Decimal("0"))
    rejected = sum((line.rejected_quantity for line in receipt.lines), Decimal("0"))
    if action == "accept" and accepted <= 0:
        raise ValueError("An accepted goods receipt must contain accepted quantity")
    if action == "reject" and (accepted != 0 or rejected <= 0):
        raise ValueError("Reject is only valid when every received unit is rejected")
    prior = receipt.status
    receipt.status, receipt.revision = target, receipt.revision + 1
    receipt.state_changed_at, receipt.state_changed_by = utc_now(), actor
    session.add(OperationalGoodsReceiptWorkflowEvent(event_key=str(uuid.uuid4()), receipt_id=receipt.id,
                from_status=prior, to_status=target, actor=actor, note=note))
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"goods_receipt.{action}",
                actor=actor, resource_key=receipt.receipt_key,
                detail=f"{prior} to {target}; revision {receipt.revision}; posting disabled"))
    session.commit()
    return receipt


def rehearse_goods_receipt_posting(session: Session, receipt: OperationalGoodsReceipt, *, actor: str) -> dict:
    if receipt.status != "accepted":
        raise ValueError("Only an accepted goods receipt can be rehearsed")
    period = session.scalar(select(OperationalFiscalPeriod).where(
        OperationalFiscalPeriod.starts_on <= receipt.received_on,
        OperationalFiscalPeriod.ends_on >= receipt.received_on,
        OperationalFiscalPeriod.status == "open",
        OperationalFiscalPeriod.rehearsal_enabled.is_(True),
    ))
    if not period:
        raise ValueError("Receipt date is not in an open rehearsal-enabled fiscal period")
    movements = [{"line_no": line.line_no, "location_code": receipt.location_code, "sku": line.sku,
                  "canonical_uom": line.canonical_uom, "quantity_base": line.accepted_quantity_base,
                  "value_delta": line.accepted_value, "batch_no": line.batch_no,
                  "expiry_date": line.expiry_date} for line in receipt.lines if line.accepted_quantity_base > 0]
    total = sum((row["value_delta"] for row in movements), Decimal("0.00"))
    payload = {"receipt_key": receipt.receipt_key, "revision": receipt.revision,
               "period": period.period_key, "movements": movements, "total": str(total)}
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    plan = {"receipt_key": receipt.receipt_key, "receipt_no": receipt.receipt_no,
            "posting_enabled": False, "period_key": period.period_key, "movements": movements,
            "journal": [{"account": "Inventory", "debit": total, "credit": Decimal("0.00")},
                        {"account": "GRNI", "debit": Decimal("0.00"), "credit": total}],
            "debit": total, "credit": total, "posting_fingerprint": fingerprint,
            "idempotency_key": f"grn:{receipt.receipt_key}:{receipt.revision}:{fingerprint[:24]}"}
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="goods_receipt.posting_rehearsed",
                actor=actor, resource_key=receipt.receipt_key,
                detail=f"{len(movements)} accepted stock movements; AED {total}; no posting performed"))
    session.commit()
    return plan


def goods_receipt_control_counts(session: Session) -> dict:
    return {"receipts": session.scalar(select(func.count(OperationalGoodsReceipt.id))) or 0,
            "accepted": session.scalar(select(func.count(OperationalGoodsReceipt.id)).where(OperationalGoodsReceipt.status == "accepted")) or 0,
            "posting_batches": 0}
