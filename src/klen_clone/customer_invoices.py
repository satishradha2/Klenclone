from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric,
    String, Text, UniqueConstraint, func, select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .delivery_fulfillment import OperationalDeliveryFulfillment
from .operational import MONEY, OperationalAuditEvent, OperationalBase, OperationalFiscalPeriod, utc_now
from .sales_orders import OperationalSalesOrder


class OperationalCustomerInvoice(OperationalBase):
    __tablename__ = "operational_customer_invoices"
    __table_args__ = (
        UniqueConstraint("fulfillment_id", name="uq_customer_invoice_fulfillment"),
        CheckConstraint("status IN ('draft','submitted','approved','rejected','cancelled')", name="ck_customer_invoice_status"),
        CheckConstraint("posting_enabled = false", name="ck_customer_invoice_no_posting"),
        CheckConstraint("subtotal >= 0 AND discount_amount >= 0 AND tax_amount >= 0 AND total_amount >= 0", name="ck_customer_invoice_totals"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    invoice_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    fulfillment_id: Mapped[int] = mapped_column(ForeignKey("operational_delivery_fulfillments.id"), nullable=False, index=True)
    sales_order_id: Mapped[int] = mapped_column(ForeignKey("operational_sales_orders.id"), nullable=False, index=True)
    sales_order_no_snapshot: Mapped[str] = mapped_column(String(40), nullable=False)
    delivery_note_no_snapshot: Mapped[str] = mapped_column(String(40), nullable=False)
    pod_reference_snapshot: Mapped[str] = mapped_column(String(300), nullable=False)
    customer_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    customer_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="AED")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    approval_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    state_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    state_changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    fulfillment: Mapped[OperationalDeliveryFulfillment] = relationship()
    sales_order: Mapped[OperationalSalesOrder] = relationship()
    lines: Mapped[list["OperationalCustomerInvoiceLine"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan",
        order_by="OperationalCustomerInvoiceLine.line_no")


class OperationalCustomerInvoiceLine(OperationalBase):
    __tablename__ = "operational_customer_invoice_lines"
    __table_args__ = (
        UniqueConstraint("invoice_id", "line_no", name="uq_customer_invoice_line"),
        UniqueConstraint("delivery_line_id", name="uq_customer_invoice_delivery_line"),
        CheckConstraint("quantity > 0 AND quantity_base > 0 AND factor_to_base_snapshot > 0", name="ck_customer_invoice_quantity"),
        CheckConstraint("unit_price >= 0 AND tax_rate >= 0 AND tax_rate <= 100", name="ck_customer_invoice_price_tax"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("operational_customer_invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    delivery_line_id: Mapped[int] = mapped_column(ForeignKey("operational_delivery_fulfillment_lines.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    product_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    uom: Mapped[str] = mapped_column(String(80), nullable=False)
    canonical_uom: Mapped[str] = mapped_column(String(80), nullable=False)
    factor_to_base_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    invoice: Mapped[OperationalCustomerInvoice] = relationship(back_populates="lines")


class OperationalCustomerInvoiceWorkflowEvent(OperationalBase):
    __tablename__ = "operational_customer_invoice_workflow_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("operational_customer_invoices.id"), nullable=False, index=True)
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalCustomerInvoicePostingRehearsal(OperationalBase):
    __tablename__ = "operational_customer_invoice_posting_rehearsals"
    __table_args__ = (
        UniqueConstraint("invoice_id", "invoice_revision", name="uq_customer_invoice_rehearsal_revision"),
        CheckConstraint("status = 'verified'", name="ck_customer_invoice_rehearsal_status"),
        CheckConstraint("posting_enabled = false", name="ck_customer_invoice_rehearsal_no_posting"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rehearsal_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("operational_customer_invoices.id"), nullable=False, index=True)
    invoice_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    period_key: Mapped[str] = mapped_column(String(20), nullable=False)
    posting_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    journal_json: Mapped[str] = mapped_column(Text, nullable=False)
    reversal_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="verified")
    posting_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    generated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(MONEY, rounding=ROUND_HALF_UP)


def create_customer_invoice(
    session: Session, fulfillment: OperationalDeliveryFulfillment, *, actor: str,
    invoice_date: date, due_date: date, notes: str | None = None,
) -> OperationalCustomerInvoice:
    existing = session.scalar(select(OperationalCustomerInvoice).where(
        OperationalCustomerInvoice.fulfillment_id == fulfillment.id))
    if existing:
        return existing
    if fulfillment.status != "delivered" or not fulfillment.delivered_at:
        raise ValueError("Only a delivered order can be invoiced")
    if not fulfillment.delivery_note_no or not fulfillment.pod_reference or not fulfillment.received_by:
        raise ValueError("Delivery note and proof of delivery are required before invoicing")
    if invoice_date < fulfillment.delivered_at.date():
        raise ValueError("Invoice date cannot be earlier than the proof-of-delivery date")
    if due_date < invoice_date:
        raise ValueError("Invoice due date cannot be earlier than its invoice date")
    order = fulfillment.sales_order
    order_lines = {line.line_no: line for line in order.lines}
    if len(order_lines) != len(fulfillment.lines):
        raise ValueError("Delivered lines do not match the source sales order")
    key = str(uuid.uuid4())
    invoice = OperationalCustomerInvoice(
        invoice_key=key, invoice_no=f"SI-{invoice_date:%Y%m%d}-{key[:8].upper()}",
        fulfillment_id=fulfillment.id, sales_order_id=order.id,
        sales_order_no_snapshot=order.order_no,
        delivery_note_no_snapshot=fulfillment.delivery_note_no,
        pod_reference_snapshot=fulfillment.pod_reference,
        customer_code=order.customer_code,
        customer_name_snapshot=order.customer_name_snapshot,
        location_code=order.location_code, invoice_date=invoice_date, due_date=due_date,
        currency_code=order.currency_code, subtotal=order.subtotal,
        discount_amount=order.discount_amount, tax_amount=order.tax_amount,
        total_amount=order.total_amount, status="draft", posting_enabled=False,
        notes=(notes or "").strip() or None, created_by=actor, state_changed_by=actor,
    )
    for delivered in fulfillment.lines:
        source = order_lines.get(delivered.line_no)
        if not source or Decimal(delivered.delivered_quantity_base) != Decimal(source.quantity_base):
            raise ValueError(f"Delivered quantity does not fully cover order line {delivered.line_no}")
        invoice.lines.append(OperationalCustomerInvoiceLine(
            delivery_line_id=delivered.id, line_no=source.line_no, sku=source.sku,
            product_name_snapshot=source.product_name_snapshot, quantity=source.quantity,
            uom=source.uom, canonical_uom=source.canonical_uom,
            factor_to_base_snapshot=source.factor_to_base_snapshot,
            quantity_base=source.quantity_base, unit_price=source.unit_price,
            tax_rate=source.tax_rate, net_amount=source.net_amount,
            tax_amount=source.tax_amount, gross_amount=source.gross_amount,
        ))
    session.add(invoice); session.flush()
    session.add(OperationalAuditEvent(
        event_key=str(uuid.uuid4()), event_type="customer_invoice.created", actor=actor,
        resource_key=invoice.invoice_key,
        detail=f"{invoice.invoice_no}; {order.order_no}; {fulfillment.delivery_note_no}; POD {fulfillment.pod_reference}; immutable delivered quantities; posting disabled",
    ))
    session.commit()
    return invoice


def transition_customer_invoice(
    session: Session, invoice: OperationalCustomerInvoice, *, expected_revision: int,
    action: str, actor: str, note: str | None = None,
) -> OperationalCustomerInvoice:
    transitions = {
        ("draft", "submit"): "submitted", ("rejected", "submit"): "submitted",
        ("draft", "cancel"): "cancelled", ("rejected", "cancel"): "cancelled",
        ("submitted", "cancel"): "cancelled", ("submitted", "approve"): "approved",
        ("submitted", "reject"): "rejected",
    }
    if invoice.revision != expected_revision:
        raise ValueError(f"Customer invoice revision conflict; current revision is {invoice.revision}")
    target = transitions.get((invoice.status, action))
    if not target:
        raise ValueError(f"Action {action} is not allowed from {invoice.status}")
    if action in {"approve", "reject"}:
        if invoice.created_by == actor:
            raise PermissionError("Maker-checker control prevents the creator from deciding this customer invoice")
        if not (note or "").strip():
            raise ValueError("An invoice approval decision reason is required")
    previous = invoice.status
    invoice.status = target; invoice.revision += 1
    invoice.state_changed_at = utc_now(); invoice.state_changed_by = actor
    if action == "approve":
        invoice.approved_by = actor; invoice.approval_note = note.strip()
    elif action == "reject":
        invoice.approved_by = None; invoice.approval_note = note.strip()
    session.add(OperationalCustomerInvoiceWorkflowEvent(
        event_key=str(uuid.uuid4()), invoice_id=invoice.id, from_status=previous,
        to_status=target, actor=actor, note=(note or "").strip() or None))
    session.add(OperationalAuditEvent(
        event_key=str(uuid.uuid4()), event_type=f"customer_invoice.{action}", actor=actor,
        resource_key=invoice.invoice_key, detail=f"{previous}->{target}; revision {invoice.revision}; posting disabled"))
    session.commit()
    return invoice


def customer_invoice_rehearsal_payload(
    row: OperationalCustomerInvoicePostingRehearsal,
    invoice: OperationalCustomerInvoice, *, idempotent_replay: bool = False,
) -> dict:
    journal = json.loads(row.journal_json)
    reversal = json.loads(row.reversal_json)
    for line in journal + reversal["journal"]:
        line["debit"] = _money(line["debit"]); line["credit"] = _money(line["credit"])
    debit = sum((line["debit"] for line in journal), Decimal("0.00"))
    credit = sum((line["credit"] for line in journal), Decimal("0.00"))
    return {
        "rehearsal_key": row.rehearsal_key, "invoice_key": invoice.invoice_key,
        "invoice_no": invoice.invoice_no, "invoice_revision": row.invoice_revision,
        "period_key": row.period_key, "posting_fingerprint": row.posting_fingerprint,
        "journal": journal, "reversal": reversal, "debit": debit, "credit": credit,
        "inventory_movements": [], "stock_issue_source": invoice.delivery_note_no_snapshot,
        "posting_performed": False, "posting_enabled": False,
        "idempotent_replay": idempotent_replay,
    }


def rehearse_customer_invoice(
    session: Session, invoice: OperationalCustomerInvoice, *, actor: str,
) -> dict:
    if invoice.status != "approved":
        raise ValueError("Only an approved customer invoice can enter posting rehearsal")
    period = session.scalar(select(OperationalFiscalPeriod).where(
        OperationalFiscalPeriod.starts_on <= invoice.invoice_date,
        OperationalFiscalPeriod.ends_on >= invoice.invoice_date).with_for_update())
    if not period or period.status != "open" or not period.rehearsal_enabled:
        raise ValueError(f"Fiscal period is not open for rehearsal on {invoice.invoice_date.isoformat()}")
    existing = session.scalar(select(OperationalCustomerInvoicePostingRehearsal).where(
        OperationalCustomerInvoicePostingRehearsal.invoice_id == invoice.id,
        OperationalCustomerInvoicePostingRehearsal.invoice_revision == invoice.revision))
    if existing:
        return customer_invoice_rehearsal_payload(existing, invoice, idempotent_replay=True)
    revenue = _money(invoice.subtotal - invoice.discount_amount)
    journal = [
        {"account": "Trade receivables", "account_code": "1200", "debit": str(_money(invoice.total_amount)), "credit": "0"},
        {"account": "Sales revenue", "account_code": "4000", "debit": "0", "credit": str(revenue)},
        {"account": "Output VAT payable", "account_code": "2120", "debit": "0", "credit": str(_money(invoice.tax_amount))},
    ]
    debit = sum((_money(line["debit"]) for line in journal), Decimal("0.00"))
    credit = sum((_money(line["credit"]) for line in journal), Decimal("0.00"))
    if debit != credit:
        raise RuntimeError(f"Customer invoice rehearsal is not balanced: debit {debit}, credit {credit}")
    reversal = {"journal": [{**line, "debit": line["credit"], "credit": line["debit"]}
                            for line in reversed(journal)], "inventory_movements": []}
    fingerprint_source = json.dumps({
        "invoice_key": invoice.invoice_key, "revision": invoice.revision,
        "period_key": period.period_key, "journal": journal,
        "delivery_note": invoice.delivery_note_no_snapshot,
        "pod_reference": invoice.pod_reference_snapshot,
    }, sort_keys=True, separators=(",", ":"))
    row = OperationalCustomerInvoicePostingRehearsal(
        rehearsal_key=str(uuid.uuid4()), invoice_id=invoice.id,
        invoice_revision=invoice.revision, period_key=period.period_key,
        posting_fingerprint=hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest(),
        journal_json=json.dumps(journal, sort_keys=True),
        reversal_json=json.dumps(reversal, sort_keys=True), status="verified",
        posting_enabled=False, generated_by=actor)
    session.add(row)
    session.add(OperationalAuditEvent(
        event_key=str(uuid.uuid4()), event_type="customer_invoice.posting_rehearsed",
        actor=actor, resource_key=invoice.invoice_key,
        detail=f"balanced {debit}; AR/revenue/VAT only; stock already issued by {invoice.delivery_note_no_snapshot}; non-posting rehearsal"))
    session.commit()
    return customer_invoice_rehearsal_payload(row, invoice)


def list_customer_invoices(session: Session, *, allowed_locations: tuple[str, ...] = ("*",), limit: int = 100):
    query = select(OperationalCustomerInvoice)
    if "*" not in allowed_locations:
        query = query.where(OperationalCustomerInvoice.location_code.in_(allowed_locations))
    return list(session.scalars(query.order_by(OperationalCustomerInvoice.created_at.desc()).limit(limit)))


def customer_invoice_control_counts(session: Session) -> dict:
    return {
        "invoices": session.scalar(select(func.count(OperationalCustomerInvoice.id))) or 0,
        "awaiting_approval": session.scalar(select(func.count(OperationalCustomerInvoice.id)).where(
            OperationalCustomerInvoice.status == "submitted")) or 0,
        "approved": session.scalar(select(func.count(OperationalCustomerInvoice.id)).where(
            OperationalCustomerInvoice.status == "approved")) or 0,
        "rehearsals": session.scalar(select(func.count(OperationalCustomerInvoicePostingRehearsal.id))) or 0,
        "posting_enabled": False,
    }
