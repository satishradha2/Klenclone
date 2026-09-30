"""No-stock, invoice-line-based customer pricing corrections."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .customer_invoices import OperationalCustomerInvoice, OperationalCustomerInvoiceLine
from .operational import MONEY, OperationalAuditEvent, OperationalBase, OperationalFiscalPeriod, utc_now
from .sales_returns import (OperationalSalesReturn, OperationalSalesReturnLine,
    target_invoice_evidence_hash, target_return_settlement_split)


class OperationalCustomerPriceCredit(OperationalBase):
    __tablename__ = "operational_customer_price_credits"
    __table_args__ = (
        CheckConstraint("status IN ('draft','submitted','approved','cancelled','posted','reversed')",
                        name="ck_customer_price_credit_status"),
        CheckConstraint("quantity > 0 AND corrected_unit_net >= 0 AND net_credit > 0 AND vat_credit >= 0",
                        name="ck_customer_price_credit_amount"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    credit_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    credit_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("operational_customer_invoices.id"), nullable=False, index=True)
    invoice_line_id: Mapped[int] = mapped_column(ForeignKey("operational_customer_invoice_lines.id"), nullable=False)
    invoice_evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False)
    credit_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    corrected_unit_net: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    net_credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    vat_credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    state_changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    state_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    invoice: Mapped[OperationalCustomerInvoice] = relationship(foreign_keys=[invoice_id])
    invoice_line: Mapped[OperationalCustomerInvoiceLine] = relationship(foreign_keys=[invoice_line_id])


def _cents(value) -> Decimal:
    return Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def _reprice(line: OperationalCustomerInvoiceLine, quantity: Decimal,
             corrected_unit_net: Decimal) -> tuple[Decimal, Decimal]:
    original_qty = Decimal(line.quantity)
    taxable = Decimal(line.net_amount) - Decimal(line.discount_amount)
    if (quantity <= 0 or quantity > original_qty or corrected_unit_net < 0
            or not quantity.is_finite() or not corrected_unit_net.is_finite()):
        raise ValueError("Correction quantity and effective unit price are invalid")
    original_portion = _cents(taxable * quantity / original_qty)
    corrected_portion = _cents(corrected_unit_net * quantity)
    net = original_portion - corrected_portion
    if net <= 0:
        raise ValueError("Corrected effective price must be below the invoiced effective price")
    original_vat_portion = _cents(Decimal(line.tax_amount) * quantity / original_qty)
    vat = min(_cents(net * Decimal(line.tax_rate) / Decimal("100")), original_vat_portion)
    return net, vat


def _validate_credit(session: Session, credit: OperationalCustomerPriceCredit,
                     *, include_submitted: bool) -> tuple[OperationalCustomerInvoice, Decimal, Decimal]:
    from .payments import OperationalPayment, OperationalPaymentAllocationClaim
    from .posting_integration import OperationalIntegratedPostingBatch

    invoice = session.scalar(select(OperationalCustomerInvoice).where(
        OperationalCustomerInvoice.id == credit.invoice_id).with_for_update())
    if (invoice is None or invoice.status != "posted" or invoice.currency_code != "AED"
            or invoice.customer_code != credit.customer_code or invoice.location_code != credit.location_code
            or credit.credit_date < invoice.invoice_date
            or target_invoice_evidence_hash(invoice) != credit.invoice_evidence_hash):
        raise ValueError("A posted unchanged AED invoice is required for the pricing correction")
    original_batch = session.scalar(select(OperationalIntegratedPostingBatch.id).where(
        OperationalIntegratedPostingBatch.resource_type == "customer_invoice",
        OperationalIntegratedPostingBatch.resource_key == invoice.invoice_key,
        OperationalIntegratedPostingBatch.batch_kind == "posting",
        OperationalIntegratedPostingBatch.status == "posted"))
    if original_batch is None:
        raise ValueError("Original customer invoice posting is required")
    line = session.get(OperationalCustomerInvoiceLine, credit.invoice_line_id)
    if line is None or line.invoice_id != invoice.id:
        raise ValueError("Pricing correction must reference an original invoice line")
    net, vat = _reprice(line, Decimal(credit.quantity), Decimal(credit.corrected_unit_net))
    if net != Decimal(credit.net_credit) or vat != Decimal(credit.vat_credit) or net + vat != Decimal(credit.total_amount):
        raise ValueError("Pricing correction calculation changed")
    statuses = ("submitted", "approved", "posted") if include_submitted else ("approved", "posted")
    return_credit = Decimal(session.scalar(select(func.coalesce(func.sum(
        OperationalSalesReturn.total_amount), 0)).where(
        OperationalSalesReturn.original_invoice_target_key == invoice.invoice_key,
        OperationalSalesReturn.status.in_(statuses))) or 0)
    other_credit = Decimal(session.scalar(select(func.coalesce(func.sum(
        OperationalCustomerPriceCredit.total_amount), 0)).where(
        OperationalCustomerPriceCredit.invoice_id == invoice.id,
        OperationalCustomerPriceCredit.id != credit.id,
        OperationalCustomerPriceCredit.status.in_(statuses))) or 0)
    if return_credit + other_credit + credit.total_amount > Decimal(invoice.total_amount):
        raise ValueError("Cumulative credits exceed the original invoice")
    same_line_credit = Decimal(session.scalar(select(func.coalesce(func.sum(
        OperationalCustomerPriceCredit.total_amount), 0)).where(
        OperationalCustomerPriceCredit.invoice_line_id == line.id,
        OperationalCustomerPriceCredit.id != credit.id,
        OperationalCustomerPriceCredit.status.in_(statuses))) or 0)
    if same_line_credit > 0:
        raise ValueError("This invoice line already has an active pricing correction")
    if same_line_credit + credit.total_amount > Decimal(line.gross_amount):
        raise ValueError("Pricing corrections exceed the original invoice line")
    physical_return = session.scalar(select(OperationalSalesReturnLine.id).join(
        OperationalSalesReturn).where(
        OperationalSalesReturn.original_invoice_target_key == invoice.invoice_key,
        OperationalSalesReturn.status.in_(statuses),
        OperationalSalesReturnLine.sku == line.sku))
    if physical_return:
        raise ValueError("Pricing correction and physical return cannot overlap the same invoice SKU")
    pending_receipt = session.scalar(select(OperationalPaymentAllocationClaim.id).join(OperationalPayment).where(
        OperationalPayment.party_code == invoice.customer_code,
        OperationalPayment.payment_type == "customer_receipt",
        OperationalPaymentAllocationClaim.source_type == "invoice",
        OperationalPaymentAllocationClaim.source_reference_key == invoice.invoice_no,
        OperationalPaymentAllocationClaim.status == "active",
        OperationalPayment.status.in_(("submitted", "approved"))))
    if pending_receipt:
        raise ValueError("Pending customer receipts must post or cancel before pricing-credit posting")
    received = Decimal(session.scalar(select(func.coalesce(func.sum(
        OperationalPaymentAllocationClaim.amount), 0)).join(OperationalPayment).where(
        OperationalPayment.party_code == invoice.customer_code,
        OperationalPayment.payment_type == "customer_receipt",
        OperationalPaymentAllocationClaim.source_type == "invoice",
        OperationalPaymentAllocationClaim.source_reference_key == invoice.invoice_no,
        OperationalPaymentAllocationClaim.status == "consumed",
        OperationalPayment.status == "posted")) or 0)
    return invoice, return_credit + other_credit, received


def create_price_credit(session: Session, *, invoice: OperationalCustomerInvoice, line_no: int,
                        credit_date: date, quantity: Decimal, corrected_unit_net: Decimal,
                        reason: str, actor: str) -> OperationalCustomerPriceCredit:
    if invoice.status != "posted" or invoice.currency_code != "AED" or credit_date < invoice.invoice_date:
        raise ValueError("A posted AED invoice and later credit date are required")
    if len(reason.strip()) < 5:
        raise ValueError("A meaningful pricing-correction reason is required")
    line = next((row for row in invoice.lines if row.line_no == line_no), None)
    if line is None:
        raise ValueError("Original invoice line was not found")
    qty, unit = Decimal(quantity), Decimal(corrected_unit_net)
    if unit != unit.quantize(Decimal("0.0001")):
        raise ValueError("Corrected effective unit price supports four decimal places")
    net, vat = _reprice(line, qty, unit)
    key = str(uuid.uuid4())
    row = OperationalCustomerPriceCredit(credit_key=key, credit_no=f"PCN-{key[:8].upper()}",
        invoice_id=invoice.id, invoice_line_id=line.id,
        invoice_evidence_hash=target_invoice_evidence_hash(invoice),
        customer_code=invoice.customer_code, location_code=invoice.location_code,
        credit_date=credit_date, quantity=qty, corrected_unit_net=unit,
        net_credit=net, vat_credit=vat, total_amount=net + vat, reason=reason.strip(),
        created_by=actor, state_changed_by=actor)
    session.add(row)
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="customer_price_credit.created",
        actor=actor, resource_key=key, detail=f"{row.credit_no}; no stock movement; AED {row.total_amount}"))
    session.commit()
    return row


def transition_price_credit(session: Session, credit: OperationalCustomerPriceCredit, *,
                            expected_revision: int, action: str, actor: str,
                            note: str | None = None) -> OperationalCustomerPriceCredit:
    next_status = {("draft", "submit"): "submitted", ("draft", "cancel"): "cancelled",
                   ("submitted", "approve"): "approved", ("submitted", "cancel"): "cancelled"}.get(
                       (credit.status, action))
    if next_status is None or credit.revision != expected_revision:
        raise ValueError("Pricing-credit state or revision conflict")
    if action == "approve" and credit.created_by == actor:
        raise PermissionError("Maker-checker prevents self-approval of a pricing credit")
    if action == "approve" and len((note or "").strip()) < 5:
        raise ValueError("Independent approval reason is required")
    if action in ("submit", "approve"):
        _validate_credit(session, credit, include_submitted=True)
    credit.status, credit.revision = next_status, credit.revision + 1
    credit.state_changed_by, credit.state_changed_at = actor, utc_now()
    if action == "approve":
        credit.approved_by = actor
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()),
        event_type=f"customer_price_credit.{action}", actor=actor,
        resource_key=credit.credit_key, detail=f"{next_status}; revision {credit.revision}; no stock movement"))
    session.commit()
    return credit


def price_credit_posting_plan(session: Session, credit: OperationalCustomerPriceCredit) -> dict:
    if credit.status != "approved":
        raise ValueError("Only an independently approved pricing credit can post")
    invoice, prior_credit, received = _validate_credit(session, credit, include_submitted=True)
    pending_return = session.scalar(select(OperationalSalesReturn.id).where(
        OperationalSalesReturn.original_invoice_target_key == invoice.invoice_key,
        OperationalSalesReturn.status.in_(("submitted", "approved"))))
    pending_price_credit = session.scalar(select(OperationalCustomerPriceCredit.id).where(
        OperationalCustomerPriceCredit.invoice_id == invoice.id,
        OperationalCustomerPriceCredit.id != credit.id,
        OperationalCustomerPriceCredit.status.in_(("submitted", "approved"))))
    if pending_return or pending_price_credit:
        raise ValueError("Other pending invoice credits must post or cancel before pricing-credit posting")
    period = session.scalar(select(OperationalFiscalPeriod).where(
        OperationalFiscalPeriod.starts_on <= credit.credit_date,
        OperationalFiscalPeriod.ends_on >= credit.credit_date,
        OperationalFiscalPeriod.status == "open",
        OperationalFiscalPeriod.rehearsal_enabled.is_(True)))
    if period is None:
        raise ValueError("Pricing-credit date is outside an open fiscal period")
    split = target_return_settlement_split(invoice.total_amount, received, prior_credit, credit.total_amount)
    journal = [{"account": "4010", "debit": credit.net_credit, "credit": Decimal("0")},
               {"account": "2120", "debit": credit.vat_credit, "credit": Decimal("0")},
               {"account": "1200", "debit": Decimal("0"), "credit": split["receivable_credit"]}]
    if split["refund_payable"]:
        journal.append({"account": "2130", "debit": Decimal("0"), "credit": split["refund_payable"]})
    evidence = {"credit_key": credit.credit_key, "revision": credit.revision,
        "invoice": invoice.invoice_no, "invoice_hash": credit.invoice_evidence_hash,
        "line_no": credit.invoice_line.line_no, "quantity": str(credit.quantity),
        "corrected_unit_net": str(credit.corrected_unit_net), "net": str(credit.net_credit),
        "vat": str(credit.vat_credit), "prior_credit": str(prior_credit),
        "received": str(received), "period": period.period_key}
    fingerprint = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
    subledger = [{"entry_type": "receivable_credit", "party_code": credit.customer_code,
        "source_type": "customer_invoice", "source_reference_key": invoice.invoice_no,
        "amount": -split["receivable_credit"]}]
    if split["refund_payable"]:
        subledger.append({"entry_type": "customer_refund_payable", "party_code": credit.customer_code,
            "source_type": "customer_price_credit", "source_reference_key": credit.credit_no,
            "amount": split["refund_payable"]})
    return {"journal": journal, "subledger": subledger, "movements": [],
        "period_key": period.period_key, "posting_fingerprint": fingerprint,
        "idempotency_key": f"price-credit:{credit.credit_key}:{credit.revision}:{fingerprint[:20]}",
        "debit": credit.total_amount, "credit": credit.total_amount,
        "receivable_credit": split["receivable_credit"],
        "refund_payable": split["refund_payable"]}
