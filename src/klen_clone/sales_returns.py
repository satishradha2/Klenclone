from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .operational import MONEY, OperationalAuditEvent, OperationalBase, OperationalFiscalPeriod, utc_now


class OperationalSalesReturn(OperationalBase):
    __tablename__ = "operational_sales_returns"
    __table_args__ = (
        CheckConstraint("status IN ('draft','submitted','approved','cancelled','posted','reversed')", name="ck_sales_return_status"),
        CheckConstraint("posting_enabled = false", name="ck_sales_return_no_posting"),
        CheckConstraint("subtotal >= 0 AND tax_amount >= 0 AND total_amount >= 0", name="ck_sales_return_totals"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    return_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    return_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    customer_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    customer_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    original_invoice_reference: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    original_invoice_origin: Mapped[str] = mapped_column(String(24), nullable=False, default="bizmodo_clone")
    original_invoice_target_key: Mapped[str | None] = mapped_column(String(36), index=True)
    original_invoice_source_record_id: Mapped[int] = mapped_column(Integer, nullable=False)
    original_invoice_total_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    original_invoice_evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    return_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), default="AED", nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False, index=True)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    state_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    state_changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    lines: Mapped[list["OperationalSalesReturnLine"]] = relationship(
        back_populates="sales_return", cascade="all, delete-orphan", order_by="OperationalSalesReturnLine.line_no")
    credit_note: Mapped["OperationalSalesCreditNote | None"] = relationship(
        back_populates="sales_return", cascade="all, delete-orphan", uselist=False)


class OperationalSalesReturnLine(OperationalBase):
    __tablename__ = "operational_sales_return_lines"
    __table_args__ = (
        UniqueConstraint("sales_return_id", "line_no", name="uq_sales_return_line"),
        CheckConstraint("quantity > 0 AND factor_to_base_snapshot > 0 AND quantity_base > 0", name="ck_sales_return_quantity"),
        CheckConstraint("restock_quantity >= 0 AND writeoff_quantity >= 0 AND restock_quantity + writeoff_quantity = quantity", name="ck_sales_return_disposition"),
        CheckConstraint("unit_price >= 0 AND tax_rate >= 0 AND tax_rate <= 100", name="ck_sales_return_price_tax"),
        CheckConstraint("unit_cost_snapshot >= 0", name="ck_sales_return_cost"),
        CheckConstraint("original_invoice_quantity_snapshot > 0 AND original_invoice_unit_price_snapshot >= 0", name="ck_sales_return_invoice_snapshot"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sales_return_id: Mapped[int] = mapped_column(ForeignKey("operational_sales_returns.id", ondelete="CASCADE"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    product_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    restock_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    writeoff_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    uom: Mapped[str] = mapped_column(String(80), nullable=False)
    canonical_uom: Mapped[str] = mapped_column(String(80), nullable=False)
    factor_to_base_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    unit_cost_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    original_invoice_quantity_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    original_invoice_unit_price_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    disposition_reason: Mapped[str | None] = mapped_column(String(500))
    sales_return: Mapped[OperationalSalesReturn] = relationship(back_populates="lines")


class OperationalSalesCreditNote(OperationalBase):
    __tablename__ = "operational_sales_credit_notes"
    __table_args__ = (
        UniqueConstraint("sales_return_id", name="uq_credit_note_sales_return"),
        CheckConstraint("status IN ('approved','posted','reversed')", name="ck_sales_credit_note_status"),
        CheckConstraint("posting_enabled = false", name="ck_sales_credit_note_no_posting"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    credit_note_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    credit_note_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    sales_return_id: Mapped[int] = mapped_column(ForeignKey("operational_sales_returns.id"), nullable=False, index=True)
    customer_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    original_invoice_reference: Mapped[str] = mapped_column(String(160), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approved_by: Mapped[str] = mapped_column(String(200), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    sales_return: Mapped[OperationalSalesReturn] = relationship(back_populates="credit_note")


class OperationalSalesReturnPostingRehearsal(OperationalBase):
    __tablename__ = "operational_sales_return_posting_rehearsals"
    __table_args__ = (
        UniqueConstraint("sales_return_id", "return_revision", name="uq_sales_return_rehearsal_revision"),
        CheckConstraint("status = 'balanced_non_posting'", name="ck_sales_return_rehearsal_status"),
        CheckConstraint("posting_enabled = false", name="ck_sales_return_rehearsal_no_posting"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rehearsal_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    sales_return_id: Mapped[int] = mapped_column(ForeignKey("operational_sales_returns.id"), nullable=False, index=True)
    return_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    original_invoice_reference: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    original_invoice_evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    period_key: Mapped[str] = mapped_column(String(40), nullable=False)
    posting_fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    journal_json: Mapped[str] = mapped_column(Text, nullable=False)
    movements_json: Mapped[str] = mapped_column(Text, nullable=False)
    reversal_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="balanced_non_posting")
    posting_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    generated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalSalesReturnWorkflowEvent(OperationalBase):
    __tablename__ = "operational_sales_return_workflow_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    sales_return_id: Mapped[int] = mapped_column(ForeignKey("operational_sales_returns.id"), nullable=False, index=True)
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


def _normalise_line(raw: dict) -> dict:
    quantity = Decimal(str(raw["quantity"])); restock = Decimal(str(raw["restock_quantity"])); writeoff = Decimal(str(raw["writeoff_quantity"]))
    factor = Decimal(str(raw["factor_to_base_snapshot"])); price = Decimal(str(raw["unit_price"])); tax_rate = Decimal(str(raw["tax_rate"])); cost = Decimal(str(raw["unit_cost_snapshot"])); invoice_quantity = Decimal(str(raw["original_invoice_quantity_snapshot"])); invoice_price = Decimal(str(raw["original_invoice_unit_price_snapshot"]))
    if quantity <= 0 or restock < 0 or writeoff < 0 or restock + writeoff != quantity:
        raise ValueError("Return disposition must conserve quantity: restock plus write-off must equal returned quantity")
    if factor <= 0 or price < 0 or cost < 0 or tax_rate < 0 or tax_rate > 100:
        raise ValueError("Return factor must be positive and price, cost and tax must be valid")
    if invoice_quantity <= 0 or quantity > invoice_quantity or invoice_price < 0 or price != invoice_price:
        raise ValueError("Return quantity and price must be covered by the original customer invoice line")
    if writeoff > 0 and not (raw.get("disposition_reason") or "").strip():
        raise ValueError("A disposition reason is required for written-off returned quantity")
    net = (quantity * price).quantize(MONEY, rounding=ROUND_HALF_UP)
    tax = (net * tax_rate / Decimal("100")).quantize(MONEY, rounding=ROUND_HALF_UP)
    row = {key: value for key, value in raw.items() if key not in ("credit_net_amount", "credit_tax_amount")}
    if "credit_net_amount" in raw or "credit_tax_amount" in raw:
        credited_net = Decimal(str(raw["credit_net_amount"]))
        credited_tax = Decimal(str(raw["credit_tax_amount"]))
        if any(not amount.is_finite() or amount < 0 or amount != amount.quantize(MONEY)
               for amount in (credited_net, credited_tax)):
            raise ValueError("Target invoice credit amounts must be non-negative AED cents")
        net, tax = credited_net, credited_tax
    return dict(row, quantity=quantity, restock_quantity=restock, writeoff_quantity=writeoff,
                factor_to_base_snapshot=factor, quantity_base=quantity * factor, unit_price=price,
                tax_rate=tax_rate, net_amount=net, tax_amount=tax, gross_amount=net + tax,
                unit_cost_snapshot=cost, original_invoice_quantity_snapshot=invoice_quantity,
                original_invoice_unit_price_snapshot=invoice_price,
                disposition_reason=(raw.get("disposition_reason") or "").strip() or None)


def target_invoice_evidence_hash(invoice) -> str:
    """Fingerprint the approved target invoice facts used to price a return."""
    source = {"invoice_key": invoice.invoice_key, "invoice_no": invoice.invoice_no,
              "customer_code": invoice.customer_code, "location_code": invoice.location_code,
              "currency_code": invoice.currency_code, "total_amount": str(invoice.total_amount),
              "lines": [{"line_no": line.line_no, "sku": line.sku, "quantity": str(line.quantity),
                         "unit_price": str(line.unit_price), "net_amount": str(line.net_amount),
                         "discount_amount": str(line.discount_amount),
                         "tax_amount": str(line.tax_amount), "gross_amount": str(line.gross_amount)}
                        for line in invoice.lines]}
    return hashlib.sha256(json.dumps(source, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def target_return_credit(invoice_line, prior_quantity: Decimal, return_quantity: Decimal) -> tuple[Decimal, Decimal]:
    """Cumulative allocation ensures the last return uses every remaining net/VAT cent."""
    sold = Decimal(invoice_line.quantity)
    prior, returned = Decimal(prior_quantity), Decimal(return_quantity)
    if sold <= 0 or prior < 0 or returned <= 0 or prior + returned > sold:
        raise ValueError("Target return quantity exceeds the remaining invoiced quantity")
    taxable = Decimal(invoice_line.net_amount) - Decimal(invoice_line.discount_amount)
    tax = Decimal(invoice_line.tax_amount)
    def allocated(total: Decimal, qty: Decimal) -> Decimal:
        return (total * qty / sold).quantize(MONEY, rounding=ROUND_HALF_UP)
    return (allocated(taxable, prior + returned) - allocated(taxable, prior),
            allocated(tax, prior + returned) - allocated(tax, prior))


def target_invoice_dispatch_movement(session: Session, invoice, invoice_line):
    """Return the costed physical issue behind exactly one target invoice line."""
    from .customer_invoices import invoice_dispatch_valuation
    from .delivery_fulfillment import OperationalDeliveryStockMovement
    invoice_dispatch_valuation(session, invoice)
    movement = session.scalar(select(OperationalDeliveryStockMovement).where(
        OperationalDeliveryStockMovement.fulfillment_id == invoice.fulfillment_id,
        OperationalDeliveryStockMovement.fulfillment_line_id == invoice_line.delivery_line_id).with_for_update())
    if movement is None or Decimal(movement.quantity_base) != Decimal(invoice_line.quantity_base):
        raise ValueError(f"Original dispatch issue is unavailable for {invoice_line.sku}")
    return movement


def target_return_cost(issue_value: Decimal, original_quantity_base: Decimal,
                       prior_quantity_base: Decimal, return_quantity_base: Decimal) -> Decimal:
    """Allocate the original issue cents cumulatively across partial returns."""
    total = Decimal(issue_value)
    original = Decimal(original_quantity_base)
    prior = Decimal(prior_quantity_base)
    returned = Decimal(return_quantity_base)
    if total < 0 or original <= 0 or prior < 0 or returned <= 0 or prior + returned > original:
        raise ValueError("Return cost quantity exceeds the original dispatch issue")
    def allocated(quantity: Decimal) -> Decimal:
        return (total * quantity / original).quantize(MONEY, rounding=ROUND_HALF_UP)
    return allocated(prior + returned) - allocated(prior)


def target_return_settlement_split(invoice_total: Decimal, receipt_amount: Decimal,
                                   prior_credit: Decimal, return_credit: Decimal) -> dict:
    """Allocate a credit first to unpaid AR, then to a refund liability; never disburse cash here."""
    total, received, prior, credit = map(Decimal, (
        invoice_total, receipt_amount, prior_credit, return_credit))
    if any(value < 0 or value != value.quantize(MONEY)
           for value in (total, received, prior, credit)):
        raise ValueError("Invoice, receipt and credit amounts must be non-negative AED cents")
    if received > total or prior + credit > total:
        raise ValueError("Customer receipts or credits exceed the original invoice total")
    unpaid = max(Decimal("0.00"), total - received - prior)
    receivable_credit = min(unpaid, credit)
    return {"receipt_amount": received, "prior_credit": prior,
            "receivable_credit": receivable_credit,
            "refund_payable": credit - receivable_credit}


def target_invoice_credit_total(session: Session, invoice_key: str, *,
                                include_submitted: bool = False,
                                as_of: date | None = None) -> Decimal:
    from .customer_price_credits import OperationalCustomerPriceCredit
    from .customer_invoices import OperationalCustomerInvoice
    statuses = ("submitted", "approved", "posted") if include_submitted else ("approved", "posted")
    query = select(func.coalesce(func.sum(OperationalSalesReturn.total_amount), 0)).where(
        OperationalSalesReturn.original_invoice_origin == "target_erp",
        OperationalSalesReturn.original_invoice_target_key == invoice_key,
        OperationalSalesReturn.status.in_(statuses))
    if as_of is not None:
        query = query.where(OperationalSalesReturn.return_date <= as_of)
    returned = Decimal(session.scalar(query) or 0)
    price_query = select(func.coalesce(func.sum(OperationalCustomerPriceCredit.total_amount), 0)).join(
        OperationalCustomerInvoice,
        OperationalCustomerInvoice.id == OperationalCustomerPriceCredit.invoice_id).where(
        OperationalCustomerInvoice.invoice_key == invoice_key,
        OperationalCustomerPriceCredit.status.in_(statuses))
    if as_of is not None:
        price_query = price_query.where(OperationalCustomerPriceCredit.credit_date <= as_of)
    return (returned + Decimal(session.scalar(price_query) or 0)).quantize(MONEY, rounding=ROUND_HALF_UP)


def _replace_lines(document: OperationalSalesReturn, lines: list[dict]) -> None:
    document.lines.clear()
    for number, source in enumerate(lines, 1):
        row = _normalise_line(source)
        document.lines.append(OperationalSalesReturnLine(line_no=number, **row))


def _set_totals(document: OperationalSalesReturn) -> None:
    document.subtotal = sum((line.net_amount for line in document.lines), Decimal("0.00"))
    document.tax_amount = sum((line.tax_amount for line in document.lines), Decimal("0.00"))
    document.total_amount = document.subtotal + document.tax_amount


def _validate_invoice_origin(origin: str, target_key: str | None, source_record_id: int,
                             evidence_hash: str) -> None:
    if len(evidence_hash) != 64:
        raise ValueError("Original invoice evidence hash is required")
    if origin == "target_erp":
        if not target_key or source_record_id != 0:
            raise ValueError("Target return requires an ERP invoice key and no BizModo source record")
    elif origin == "bizmodo_clone":
        if target_key is not None or source_record_id <= 0:
            raise ValueError("BizModo return requires a positive immutable source record ID")
    else:
        raise ValueError("Original invoice origin must be target_erp or bizmodo_clone")


def create_sales_return(session: Session, *, customer_code: str, customer_name_snapshot: str,
                        location_code: str, original_invoice_reference: str, return_date: date,
                        reason_code: str, notes: str | None, actor: str, lines: list[dict],
                        original_invoice_source_record_id: int,
                        original_invoice_total_snapshot: Decimal,
                        original_invoice_evidence_hash: str,
                        original_invoice_origin: str = "bizmodo_clone",
                        original_invoice_target_key: str | None = None) -> OperationalSalesReturn:
    if not original_invoice_reference.strip(): raise ValueError("Original sales invoice reference is required")
    if not lines: raise ValueError("At least one sales return line is required")
    _validate_invoice_origin(original_invoice_origin, original_invoice_target_key,
                             original_invoice_source_record_id, original_invoice_evidence_hash)
    key = str(uuid.uuid4())
    document = OperationalSalesReturn(return_key=key, return_no=f"SR-{key[:8].upper()}",
        customer_code=customer_code, customer_name_snapshot=customer_name_snapshot,
        location_code=location_code, original_invoice_reference=original_invoice_reference.strip(),
        original_invoice_origin=original_invoice_origin,
        original_invoice_target_key=original_invoice_target_key,
        original_invoice_source_record_id=original_invoice_source_record_id,
        original_invoice_total_snapshot=original_invoice_total_snapshot,
        original_invoice_evidence_hash=original_invoice_evidence_hash,
        return_date=return_date, reason_code=reason_code, subtotal=0, tax_amount=0, total_amount=0,
        status="draft", posting_enabled=False, notes=notes, created_by=actor, state_changed_by=actor)
    _replace_lines(document, lines); _set_totals(document)
    session.add(document); session.flush()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="sales_return.created", actor=actor,
        resource_key=document.return_key, detail=f"{document.return_no}; {len(lines)} lines; posting disabled"))
    session.commit(); return document


def replace_sales_return(session: Session, document: OperationalSalesReturn, *, expected_revision: int,
                         customer_code: str, customer_name_snapshot: str, location_code: str,
                         original_invoice_reference: str, return_date: date, reason_code: str,
                         notes: str | None, actor: str, lines: list[dict],
                         original_invoice_source_record_id: int,
                         original_invoice_total_snapshot: Decimal,
                         original_invoice_evidence_hash: str,
                         original_invoice_origin: str = "bizmodo_clone",
                         original_invoice_target_key: str | None = None) -> OperationalSalesReturn:
    if document.status != "draft": raise ValueError("Only draft-state sales returns can be edited")
    if document.revision != expected_revision: raise ValueError(f"Sales return revision conflict; current revision is {document.revision}")
    if not original_invoice_reference.strip() or not lines: raise ValueError("Invoice reference and at least one return line are required")
    _validate_invoice_origin(original_invoice_origin, original_invoice_target_key,
                             original_invoice_source_record_id, original_invoice_evidence_hash)
    document.customer_code=customer_code; document.customer_name_snapshot=customer_name_snapshot; document.location_code=location_code
    document.original_invoice_reference=original_invoice_reference.strip(); document.return_date=return_date; document.reason_code=reason_code; document.notes=notes
    document.original_invoice_source_record_id=original_invoice_source_record_id; document.original_invoice_total_snapshot=original_invoice_total_snapshot; document.original_invoice_evidence_hash=original_invoice_evidence_hash
    document.original_invoice_origin=original_invoice_origin; document.original_invoice_target_key=original_invoice_target_key
    document.revision += 1; document.state_changed_at=utc_now(); document.state_changed_by=actor
    document.lines.clear(); session.flush(); _replace_lines(document, lines); _set_totals(document)
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="sales_return.edited", actor=actor,
        resource_key=document.return_key, detail=f"{document.return_no}; revision {document.revision}; posting disabled"))
    session.commit(); return document


def list_sales_returns(session: Session, *, allowed_locations: tuple[str, ...] = ("*",), limit: int = 100) -> list[OperationalSalesReturn]:
    query = select(OperationalSalesReturn)
    if "*" not in allowed_locations: query = query.where(OperationalSalesReturn.location_code.in_(allowed_locations))
    return list(session.scalars(query.order_by(OperationalSalesReturn.created_at.desc()).limit(limit)))


def transition_sales_return(session: Session, document: OperationalSalesReturn, *, expected_revision: int,
                            action: str, actor: str, note: str | None = None) -> OperationalSalesReturn:
    transitions={("draft","submit"):"submitted",("draft","cancel"):"cancelled",("submitted","cancel"):"cancelled",("submitted","approve"):"approved"}
    if document.revision != expected_revision: raise ValueError(f"Sales return revision conflict; current revision is {document.revision}")
    target=transitions.get((document.status,action))
    if not target: raise ValueError(f"Action {action} is not allowed from {document.status}")
    if action=="approve" and document.created_by==actor: raise PermissionError("Maker-checker control prevents the creator from approving this sales return")
    if action == "submit":
        if document.original_invoice_origin == "target_erp":
            if document.reason_code == "pricing_correction":
                raise ValueError("Pricing-only credits need a separate governed adjustment workflow")
            from .customer_invoices import OperationalCustomerInvoice
            from .payments import OperationalPayment, OperationalPaymentAllocationClaim
            invoice = session.scalar(select(OperationalCustomerInvoice).where(
                OperationalCustomerInvoice.invoice_key == document.original_invoice_target_key).with_for_update())
            if (not invoice or invoice.status not in ("approved", "posted") or invoice.invoice_no != document.original_invoice_reference
                    or invoice.customer_code != document.customer_code or invoice.location_code != document.location_code
                    or invoice.currency_code != "AED" or document.return_date < invoice.invoice_date
                    or target_invoice_evidence_hash(invoice) != document.original_invoice_evidence_hash):
                raise ValueError("Approved target invoice evidence changed or does not match the return")
            receipt_amount = session.scalar(select(func.coalesce(func.sum(
                OperationalPaymentAllocationClaim.amount), 0)).join(OperationalPayment).where(
                    OperationalPayment.party_code == document.customer_code,
                    OperationalPayment.payment_type == "customer_receipt",
                    OperationalPaymentAllocationClaim.source_type == "invoice",
                    OperationalPaymentAllocationClaim.source_reference_key == invoice.invoice_no,
                    OperationalPaymentAllocationClaim.status.in_(("active", "consumed")))) or Decimal("0")
            prior_credit = session.scalar(select(func.coalesce(func.sum(OperationalSalesReturn.total_amount), 0)).where(
                OperationalSalesReturn.original_invoice_target_key == invoice.invoice_key,
                OperationalSalesReturn.id != document.id,
                OperationalSalesReturn.status.in_(("submitted", "approved", "posted")))) or Decimal("0")
            from .customer_price_credits import OperationalCustomerPriceCredit
            prior_credit += Decimal(session.scalar(select(func.coalesce(func.sum(
                OperationalCustomerPriceCredit.total_amount), 0)).where(
                OperationalCustomerPriceCredit.invoice_id == invoice.id,
                OperationalCustomerPriceCredit.status.in_(("submitted", "approved", "posted")))) or 0)
            seen_skus = set()
            for line in document.lines:
                if line.sku in seen_skus:
                    raise ValueError(f"Duplicate target return SKU {line.sku} is not allowed")
                seen_skus.add(line.sku)
                matching = [source for source in invoice.lines if source.sku == line.sku]
                if len(matching) != 1 or line.uom.casefold() != matching[0].uom.casefold():
                    raise ValueError(f"Unique target invoice line and UOM evidence is required for {line.sku}")
                source_line = matching[0]
                overlap_credit = session.scalar(select(OperationalCustomerPriceCredit.id).where(
                    OperationalCustomerPriceCredit.invoice_id == invoice.id,
                    OperationalCustomerPriceCredit.invoice_line_id == source_line.id,
                    OperationalCustomerPriceCredit.status.in_(("submitted", "approved", "posted"))))
                if overlap_credit:
                    raise ValueError(f"A pricing-only credit already covers invoice SKU {line.sku}")
                movement = target_invoice_dispatch_movement(session, invoice, source_line)
                if (line.canonical_uom.casefold() != source_line.canonical_uom.casefold()
                        or Decimal(line.factor_to_base_snapshot) != Decimal(source_line.factor_to_base_snapshot)
                        or Decimal(line.unit_cost_snapshot) != Decimal(movement.unit_cost_snapshot)
                        or Decimal(line.unit_price) != Decimal(source_line.unit_price)
                        or Decimal(line.tax_rate) != Decimal(source_line.tax_rate)):
                    raise ValueError(f"Target return issue-cost, UOM or price evidence changed for {line.sku}")
                previous = session.scalar(select(func.coalesce(func.sum(OperationalSalesReturnLine.quantity), 0)).join(
                    OperationalSalesReturn).where(
                        OperationalSalesReturn.original_invoice_target_key == invoice.invoice_key,
                        OperationalSalesReturn.id != document.id,
                        OperationalSalesReturn.status.in_(("submitted", "approved", "posted")),
                        OperationalSalesReturnLine.sku == line.sku)) or Decimal("0")
                expected_net, expected_tax = target_return_credit(source_line, previous, line.quantity)
                if (line.net_amount != expected_net or line.tax_amount != expected_tax
                        or line.gross_amount != expected_net + expected_tax):
                    raise ValueError("Target return pricing is stale; revise the draft before submission")
            target_return_settlement_split(invoice.total_amount, receipt_amount,
                                           prior_credit, document.total_amount)
        prior_total = session.scalar(select(func.coalesce(func.sum(OperationalSalesReturn.total_amount), 0)).where(
            OperationalSalesReturn.customer_code == document.customer_code,
            OperationalSalesReturn.original_invoice_reference == document.original_invoice_reference,
            OperationalSalesReturn.id != document.id,
            OperationalSalesReturn.status.in_(("submitted", "approved", "posted")))) or Decimal("0")
        if prior_total + document.total_amount > document.original_invoice_total_snapshot:
            raise ValueError("Cumulative customer credits exceed the original invoice total")
        for line in document.lines:
            prior_quantity = session.scalar(select(func.coalesce(func.sum(OperationalSalesReturnLine.quantity), 0)).join(
                OperationalSalesReturn).where(
                    OperationalSalesReturn.customer_code == document.customer_code,
                    OperationalSalesReturn.original_invoice_reference == document.original_invoice_reference,
                    OperationalSalesReturn.id != document.id,
                    OperationalSalesReturn.status.in_(("submitted", "approved", "posted")),
                    OperationalSalesReturnLine.sku == line.sku)) or Decimal("0")
            if prior_quantity + line.quantity > line.original_invoice_quantity_snapshot:
                raise ValueError(f"Cumulative returned quantity exceeds the original invoice quantity for {line.sku}")
    prior=document.status; document.status=target; document.revision+=1; document.state_changed_at=utc_now(); document.state_changed_by=actor
    if action=="approve":
        key=str(uuid.uuid4()); document.credit_note=OperationalSalesCreditNote(credit_note_key=key,
            credit_note_no=f"CN-{key[:8].upper()}", customer_code=document.customer_code,
            original_invoice_reference=document.original_invoice_reference, subtotal=document.subtotal,
            tax_amount=document.tax_amount, total_amount=document.total_amount, status="approved",
            posting_enabled=False, approved_by=actor)
    session.add(OperationalSalesReturnWorkflowEvent(event_key=str(uuid.uuid4()), sales_return_id=document.id,
        from_status=prior,to_status=target,actor=actor,note=note))
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()),event_type=f"sales_return.{action}",actor=actor,
        resource_key=document.return_key,detail=f"{prior} to {target}; revision {document.revision}; posting disabled"))
    session.commit(); return document


def _sales_return_rehearsal_payload(rehearsal: OperationalSalesReturnPostingRehearsal,
                                    document: OperationalSalesReturn,
                                    *, idempotent_replay: bool = False) -> dict:
    journal = json.loads(rehearsal.journal_json)
    movements = json.loads(rehearsal.movements_json)
    for line in journal:
        line["debit"], line["credit"] = Decimal(str(line["debit"])), Decimal(str(line["credit"]))
    for movement in movements:
        for field in ("quantity_base", "unit_cost", "value_delta"):
            movement[field] = Decimal(str(movement[field]))
    restock_cost = sum((line["debit"] for line in journal if line["account_code"] == "1300"), Decimal("0"))
    writeoff_cost = sum((line["debit"] for line in journal if line["account_code"] == "5120"), Decimal("0"))
    receivable_credit = sum((line["credit"] for line in journal if line["account_code"] == "1200"), Decimal("0"))
    refund_payable = sum((line["credit"] for line in journal if line["account_code"] == "2130"), Decimal("0"))
    debit = sum((line["debit"] for line in journal), Decimal("0"))
    credit = sum((line["credit"] for line in journal), Decimal("0"))
    return {"rehearsal_key": rehearsal.rehearsal_key, "return_key": document.return_key,
        "return_no": document.return_no, "credit_note_no": document.credit_note.credit_note_no,
        "original_invoice_reference": document.original_invoice_reference,
        "original_invoice_evidence_hash": rehearsal.original_invoice_evidence_hash,
        "period_key": rehearsal.period_key, "status": rehearsal.status, "journal": journal,
        "movements": movements, "reversal_plan": json.loads(rehearsal.reversal_json),
        "restock_cost": restock_cost, "writeoff_cost": writeoff_cost,
        "receivable_credit": receivable_credit, "refund_payable": refund_payable,
        "debit": debit, "credit": credit, "posting_fingerprint": rehearsal.posting_fingerprint,
        "idempotency_key": f"sales-return:{document.return_key}:{document.revision}:{rehearsal.posting_fingerprint[:20]}",
        "idempotent_replay": idempotent_replay, "posting_enabled": False}


def target_return_posting_evidence(session: Session, document: OperationalSalesReturn) -> dict:
    """Validate original posted invoice, unpaid credit capacity and issue-cost allocation."""
    from .customer_invoices import OperationalCustomerInvoice
    from .payments import OperationalPayment, OperationalPaymentAllocationClaim
    from .posting_integration import OperationalIntegratedPostingBatch

    invoice = session.scalar(select(OperationalCustomerInvoice).where(
        OperationalCustomerInvoice.invoice_key == document.original_invoice_target_key).with_for_update())
    if (invoice is None or invoice.status != "posted" or invoice.invoice_no != document.original_invoice_reference
            or invoice.customer_code != document.customer_code or invoice.location_code != document.location_code
            or invoice.currency_code != "AED" or document.return_date < invoice.invoice_date
            or Decimal(invoice.total_amount) != Decimal(document.original_invoice_total_snapshot)
            or target_invoice_evidence_hash(invoice) != document.original_invoice_evidence_hash):
        raise ValueError("Target ERP return posting is held until the original invoice is posted with unchanged evidence")
    original_batch = session.scalar(select(OperationalIntegratedPostingBatch).where(
        OperationalIntegratedPostingBatch.resource_type == "customer_invoice",
        OperationalIntegratedPostingBatch.resource_key == invoice.invoice_key,
        OperationalIntegratedPostingBatch.batch_kind == "posting",
        OperationalIntegratedPostingBatch.status == "posted").with_for_update())
    if original_batch is None:
        raise ValueError("Target ERP return posting requires the active original invoice accounting batch")
    if document.reason_code == "pricing_correction":
        raise ValueError("Pricing-only credits need a separate governed adjustment workflow")
    others = list(session.scalars(select(OperationalSalesReturn).where(
        OperationalSalesReturn.original_invoice_origin == "target_erp",
        OperationalSalesReturn.original_invoice_target_key == invoice.invoice_key,
        OperationalSalesReturn.id != document.id,
        OperationalSalesReturn.status.in_(("submitted", "approved", "posted"))).order_by(
        OperationalSalesReturn.id).with_for_update()))
    if any(row.id < document.id and row.status != "posted" for row in others):
        raise ValueError("Earlier target returns must be posted or cancelled before this return")
    if any(row.id > document.id and row.status == "posted" for row in others):
        raise ValueError("A later posted target return prevents out-of-order posting")
    from .customer_price_credits import OperationalCustomerPriceCredit
    pending_price_credit = session.scalar(select(OperationalCustomerPriceCredit.id).where(
        OperationalCustomerPriceCredit.invoice_id == invoice.id,
        OperationalCustomerPriceCredit.status.in_(("submitted", "approved"))))
    if pending_price_credit:
        raise ValueError("Pending pricing-only credits must post or cancel before return posting")
    prior_returns = [row for row in others if row.id < document.id and row.status == "posted"]
    pending_receipt = session.scalar(select(OperationalPaymentAllocationClaim.id).join(
        OperationalPayment).where(
        OperationalPayment.party_code == invoice.customer_code,
        OperationalPayment.payment_type == "customer_receipt",
        OperationalPaymentAllocationClaim.source_type == "invoice",
        OperationalPaymentAllocationClaim.source_reference_key == invoice.invoice_no,
        OperationalPaymentAllocationClaim.status == "active",
        OperationalPayment.status.in_(("submitted", "approved"))))
    if pending_receipt:
        raise ValueError("Pending customer receipt allocations must post or cancel before return posting")
    receipt_amount = Decimal(session.scalar(select(func.coalesce(func.sum(
        OperationalPaymentAllocationClaim.amount), 0)).join(OperationalPayment).where(
        OperationalPayment.party_code == invoice.customer_code,
        OperationalPayment.payment_type == "customer_receipt",
        OperationalPaymentAllocationClaim.source_type == "invoice",
        OperationalPaymentAllocationClaim.source_reference_key == invoice.invoice_no,
        OperationalPaymentAllocationClaim.status == "consumed",
        OperationalPayment.status == "posted")) or 0)
    from .customer_price_credits import OperationalCustomerPriceCredit
    prior_credit = sum((Decimal(row.total_amount) for row in prior_returns), Decimal("0"))
    prior_credit += Decimal(session.scalar(select(func.coalesce(func.sum(
        OperationalCustomerPriceCredit.total_amount), 0)).where(
        OperationalCustomerPriceCredit.invoice_id == invoice.id,
        OperationalCustomerPriceCredit.status == "posted")) or 0)
    settlement = target_return_settlement_split(invoice.total_amount, receipt_amount,
        prior_credit, document.total_amount)
    evidence = []
    seen_skus: set[str] = set()
    for line in document.lines:
        if line.sku in seen_skus:
            raise ValueError(f"Duplicate target return SKU {line.sku} is not allowed")
        seen_skus.add(line.sku)
        matching = [row for row in invoice.lines if row.sku == line.sku]
        if len(matching) != 1:
            raise ValueError(f"A unique original target invoice line is required for {line.sku}")
        source_line = matching[0]
        overlap_credit = session.scalar(select(OperationalCustomerPriceCredit.id).where(
            OperationalCustomerPriceCredit.invoice_id == invoice.id,
            OperationalCustomerPriceCredit.invoice_line_id == source_line.id,
            OperationalCustomerPriceCredit.status.in_(("submitted", "approved", "posted"))))
        if overlap_credit:
            raise ValueError(f"A pricing-only credit already covers invoice SKU {line.sku}")
        issue = target_invoice_dispatch_movement(session, invoice, source_line)
        if (line.uom.casefold() != source_line.uom.casefold()
                or line.canonical_uom.casefold() != source_line.canonical_uom.casefold()
                or Decimal(line.factor_to_base_snapshot) != Decimal(source_line.factor_to_base_snapshot)
                or Decimal(line.unit_cost_snapshot) != Decimal(issue.unit_cost_snapshot)
                or Decimal(line.unit_price) != Decimal(source_line.unit_price)
                or Decimal(line.tax_rate) != Decimal(source_line.tax_rate)
                or Decimal(line.quantity_base) != Decimal(line.quantity) * Decimal(source_line.factor_to_base_snapshot)):
            raise ValueError(f"Target return cost, quantity, UOM or price evidence changed for {line.sku}")
        prior_quantity = sum((Decimal(prior_line.quantity) for prior in prior_returns
                              for prior_line in prior.lines if prior_line.sku == line.sku), Decimal("0"))
        net, vat = target_return_credit(source_line, prior_quantity, Decimal(line.quantity))
        if (Decimal(line.net_amount) != net or Decimal(line.tax_amount) != vat
                or Decimal(line.gross_amount) != net + vat):
            raise ValueError("Target return pricing is stale; reconcile the earlier return sequence")
        factor = Decimal(source_line.factor_to_base_snapshot)
        return_cost = target_return_cost(Decimal(issue.issue_value_snapshot),
            Decimal(source_line.quantity_base), prior_quantity * factor, Decimal(line.quantity_base))
        restock_base = Decimal(line.restock_quantity) * factor
        restock_cost = (return_cost * restock_base / Decimal(line.quantity_base)).quantize(
            MONEY, rounding=ROUND_HALF_UP)
        writeoff_cost = return_cost - restock_cost
        evidence.append({"line_no": line.line_no, "sku": line.sku,
            "issue_movement_key": issue.movement_key,
            "issue_value_snapshot": str(issue.issue_value_snapshot),
            "original_invoice_batch": original_batch.batch_key,
            "prior_quantity": str(prior_quantity),
            "return_cost": return_cost, "restock_cost": restock_cost,
            "writeoff_cost": writeoff_cost})
    return {"lines": evidence, "settlement": settlement}


def validate_target_return_rehearsal(session: Session, document: OperationalSalesReturn,
                                     rehearsal: OperationalSalesReturnPostingRehearsal) -> None:
    """Recheck live invoice, receipts, return sequence and original-cost fingerprint under locks."""
    evidence = target_return_posting_evidence(session, document)
    source = json.dumps({
        "return_key": document.return_key, "revision": document.revision,
        "original_invoice_reference": document.original_invoice_reference,
        "original_invoice_evidence_hash": document.original_invoice_evidence_hash,
        "period_key": rehearsal.period_key,
        "journal": json.loads(rehearsal.journal_json),
        "movements": json.loads(rehearsal.movements_json),
        "reversal": json.loads(rehearsal.reversal_json),
        "target_issue_evidence": evidence,
    }, default=str, sort_keys=True, separators=(",", ":"))
    if hashlib.sha256(source.encode()).hexdigest() != rehearsal.posting_fingerprint:
        raise ValueError("Target return posting evidence changed after rehearsal")


def rehearse_sales_return_posting(session: Session, document: OperationalSalesReturn, *, actor: str) -> dict:
    if document.status != "approved" or not document.credit_note:
        raise ValueError("Only an approved sales return with a credit note can be rehearsed")
    target_evidence = (target_return_posting_evidence(session, document)
                       if document.original_invoice_origin == "target_erp" else None)
    if (document.original_invoice_origin != "target_erp"
            and (document.original_invoice_source_record_id <= 0
                 or len(document.original_invoice_evidence_hash) != 64
                 or document.original_invoice_total_snapshot <= 0)):
        raise ValueError("Verified original customer-invoice evidence is required before posting rehearsal")
    period = session.scalar(select(OperationalFiscalPeriod).where(
        OperationalFiscalPeriod.starts_on <= document.return_date,
        OperationalFiscalPeriod.ends_on >= document.return_date,
        OperationalFiscalPeriod.status == "open", OperationalFiscalPeriod.rehearsal_enabled.is_(True)))
    if not period:
        raise ValueError("Return date is not in an open rehearsal-enabled fiscal period")
    target_by_line = {row["line_no"]: row for row in target_evidence["lines"]} if target_evidence else {}
    restock_cost = (sum((row["restock_cost"] for row in target_evidence["lines"]), Decimal("0"))
                    if target_evidence is not None else
                    sum(((line.restock_quantity * line.factor_to_base_snapshot * line.unit_cost_snapshot)
                         .quantize(MONEY, rounding=ROUND_HALF_UP) for line in document.lines), Decimal("0")))
    writeoff_cost = (sum((row["writeoff_cost"] for row in target_evidence["lines"]), Decimal("0"))
                     if target_evidence is not None else
                     sum(((line.writeoff_quantity * line.factor_to_base_snapshot * line.unit_cost_snapshot)
                          .quantize(MONEY, rounding=ROUND_HALF_UP) for line in document.lines), Decimal("0")))
    total_cost = restock_cost + writeoff_cost
    receivable_credit = (target_evidence["settlement"]["receivable_credit"] if target_evidence
                         else document.total_amount)
    refund_payable = (target_evidence["settlement"]["refund_payable"] if target_evidence
                      else Decimal("0.00"))
    journal = [
        {"account_code": "4010", "account": "Sales returns and discounts", "debit": document.subtotal, "credit": Decimal("0")},
        {"account_code": "2120", "account": "Output VAT payable", "debit": document.tax_amount, "credit": Decimal("0")},
        {"account_code": "1200", "account": "Trade receivables", "debit": Decimal("0"), "credit": receivable_credit},
        {"account_code": "1300", "account": "Inventory", "debit": restock_cost, "credit": Decimal("0")},
        {"account_code": "5120", "account": "Inventory write-off", "debit": writeoff_cost, "credit": Decimal("0")},
        {"account_code": "5000", "account": "Cost of goods sold", "debit": Decimal("0"), "credit": total_cost},
    ]
    if refund_payable:
        journal.append({"account_code": "2130", "account": "Customer refunds payable",
                        "debit": Decimal("0"), "credit": refund_payable})
    movements = [{"line_no": line.line_no, "location": document.location_code, "sku": line.sku,
        "quantity_base": line.restock_quantity * line.factor_to_base_snapshot,
        "canonical_uom": line.canonical_uom, "unit_cost": line.unit_cost_snapshot,
        "value_delta": (target_by_line[line.line_no]["restock_cost"] if target_evidence is not None else
            (line.restock_quantity * line.factor_to_base_snapshot * line.unit_cost_snapshot)
            .quantize(MONEY, rounding=ROUND_HALF_UP))} for line in document.lines if line.restock_quantity > 0]
    debit = sum((row["debit"] for row in journal), Decimal("0"))
    credit = sum((row["credit"] for row in journal), Decimal("0"))
    if debit != credit:
        raise RuntimeError("Sales return posting rehearsal is not balanced")
    reversal = {"journal": [{**line, "debit": line["credit"], "credit": line["debit"]}
        for line in reversed(journal)], "movements": [{**line, "quantity_base": -line["quantity_base"],
        "value_delta": -line["value_delta"]} for line in reversed(movements)]}
    fingerprint_source = {"return_key": document.return_key, "revision": document.revision,
        "original_invoice_reference": document.original_invoice_reference,
        "original_invoice_evidence_hash": document.original_invoice_evidence_hash,
        "period_key": period.period_key, "journal": journal, "movements": movements,
        "reversal": reversal}
    if target_evidence is not None:
        fingerprint_source["target_issue_evidence"] = target_evidence
    source = json.dumps(fingerprint_source, default=str, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(source.encode()).hexdigest()
    existing = session.scalar(select(OperationalSalesReturnPostingRehearsal).where(
        OperationalSalesReturnPostingRehearsal.sales_return_id == document.id,
        OperationalSalesReturnPostingRehearsal.return_revision == document.revision))
    if existing:
        if (existing.original_invoice_evidence_hash != document.original_invoice_evidence_hash
                or existing.posting_fingerprint != fingerprint):
            raise ValueError("Original invoice or return issue-cost evidence changed after the sales-return rehearsal")
        return _sales_return_rehearsal_payload(existing, document, idempotent_replay=True)
    rehearsal = OperationalSalesReturnPostingRehearsal(rehearsal_key=str(uuid.uuid4()),
        sales_return_id=document.id, return_revision=document.revision,
        original_invoice_reference=document.original_invoice_reference,
        original_invoice_evidence_hash=document.original_invoice_evidence_hash,
        period_key=period.period_key, posting_fingerprint=fingerprint,
        journal_json=json.dumps(journal, default=str, sort_keys=True),
        movements_json=json.dumps(movements, default=str, sort_keys=True),
        reversal_json=json.dumps(reversal, default=str, sort_keys=True),
        status="balanced_non_posting", posting_enabled=False, generated_by=actor)
    session.add(rehearsal)
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()),
        event_type="sales_return.posting_rehearsed", actor=actor,
        resource_key=document.return_key,
        detail=f"AED {debit}; invoice {document.original_invoice_reference}; {len(movements)} restock movements; fingerprint {fingerprint}; no posting"))
    session.commit()
    return _sales_return_rehearsal_payload(rehearsal, document)


def sales_return_control_counts(session: Session) -> dict:
    from .posting_integration import OperationalIntegratedJournalLine, OperationalIntegratedPostingBatch
    liability = session.execute(select(
        func.coalesce(func.sum(OperationalIntegratedJournalLine.credit), 0),
        func.coalesce(func.sum(OperationalIntegratedJournalLine.debit), 0)).join(
        OperationalIntegratedPostingBatch,
        OperationalIntegratedPostingBatch.id == OperationalIntegratedJournalLine.batch_id).where(
        OperationalIntegratedJournalLine.account_code == "2130",
        OperationalIntegratedPostingBatch.resource_type.in_((
            "sales_return", "customer_price_credit", "customer_refund",
            "customer_refund_recovery")),
        OperationalIntegratedPostingBatch.status.in_(("posted", "reversed")))).one()
    refund_payable = Decimal(liability[0]) - Decimal(liability[1])
    return {"returns":session.scalar(select(func.count(OperationalSalesReturn.id))) or 0,
            "credit_notes":session.scalar(select(func.count(OperationalSalesCreditNote.id))) or 0,
            "posted":session.scalar(select(func.count(OperationalSalesCreditNote.id)).where(OperationalSalesCreditNote.status=="posted")) or 0,
            "refund_payable": refund_payable}
