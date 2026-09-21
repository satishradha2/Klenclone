from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func, or_, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .goods_receipts import OperationalGoodsReceipt, OperationalGoodsReceiptLine
from .operational import OperationalAuditEvent, OperationalBase, OperationalFiscalPeriod, utc_now
from .operational_masters import OperationalPartyMaster
from .procurement import OperationalPurchaseOrder, OperationalPurchaseOrderLine


MONEY = Decimal("0.01")
QUANTITY = Decimal("0.000001")


class OperationalSupplierInvoice(OperationalBase):
    __tablename__ = "operational_supplier_invoices"
    __table_args__ = (
        UniqueConstraint("supplier_code", "supplier_invoice_no", name="uq_supplier_invoice_reference"),
        CheckConstraint("status IN ('draft','matched','exception','approved','rejected','cancelled','posted','reversed')", name="ck_supplier_invoice_status"),
        CheckConstraint("match_status IN ('pending','passed','exception')", name="ck_supplier_invoice_match_status"),
        CheckConstraint("posting_enabled = false", name="ck_supplier_invoice_no_posting"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    supplier_invoice_no: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("operational_purchase_orders.id"), nullable=False, index=True)
    supplier_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="AED")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    match_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    match_summary: Mapped[str | None] = mapped_column(Text)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decision_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    state_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    state_changed_by: Mapped[str] = mapped_column(String(200), nullable=False, default="system")


class OperationalSupplierInvoiceLine(OperationalBase):
    __tablename__ = "operational_supplier_invoice_lines"
    __table_args__ = (
        UniqueConstraint("invoice_id", "purchase_order_line_id", name="uq_supplier_invoice_po_line"),
        CheckConstraint("quantity > 0 AND unit_price >= 0", name="ck_supplier_invoice_line_values"),
        CheckConstraint("tax_rate >= 0 AND tax_rate <= 100", name="ck_supplier_invoice_tax_rate"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("operational_supplier_invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    purchase_order_line_id: Mapped[int] = mapped_column(ForeignKey("operational_purchase_order_lines.id"), nullable=False)
    sku: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)


class OperationalSupplierTaxDocument(OperationalBase):
    __tablename__ = "operational_supplier_tax_documents"
    __table_args__ = (
        UniqueConstraint("supplier_invoice_id", name="uq_supplier_tax_document_invoice"),
        CheckConstraint("document_type IN ('tax_invoice','simplified_tax_invoice','non_tax_invoice')", name="ck_supplier_tax_document_type"),
        CheckConstraint("validation_status IN ('passed','exception')", name="ck_supplier_tax_document_status"),
        CheckConstraint("posting_enabled = false", name="ck_supplier_tax_document_no_posting"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tax_document_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    supplier_invoice_id: Mapped[int] = mapped_column(ForeignKey("operational_supplier_invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    document_type: Mapped[str] = mapped_column(String(30), nullable=False)
    supply_date: Mapped[date] = mapped_column(Date, nullable=False)
    supplier_name: Mapped[str] = mapped_column(String(500), nullable=False)
    supplier_address: Mapped[str] = mapped_column(Text, nullable=False)
    supplier_trn: Mapped[str | None] = mapped_column(String(15))
    recipient_name: Mapped[str] = mapped_column(String(500), nullable=False)
    recipient_address: Mapped[str] = mapped_column(Text, nullable=False)
    recipient_trn: Mapped[str | None] = mapped_column(String(15))
    validation_status: Mapped[str] = mapped_column(String(20), nullable=False)
    validation_summary: Mapped[str] = mapped_column(Text, nullable=False)
    master_cross_check: Mapped[str] = mapped_column(String(40), nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    validated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    validated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class OperationalSupplierInvoicePostingRehearsal(OperationalBase):
    __tablename__ = "operational_supplier_invoice_posting_rehearsals"
    __table_args__ = (
        UniqueConstraint("supplier_invoice_id", "invoice_revision", name="uq_supplier_invoice_rehearsal_revision"),
        CheckConstraint("status = 'balanced_non_posting'", name="ck_supplier_invoice_rehearsal_status"),
        CheckConstraint("posting_enabled = false", name="ck_supplier_invoice_rehearsal_no_posting"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rehearsal_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    supplier_invoice_id: Mapped[int] = mapped_column(ForeignKey("operational_supplier_invoices.id"), nullable=False, index=True)
    invoice_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    period_key: Mapped[str] = mapped_column(String(40), nullable=False)
    posting_fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    journal_json: Mapped[str] = mapped_column(Text, nullable=False)
    reversal_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="balanced_non_posting")
    posting_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    generated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class OperationalMatchTolerancePolicy(OperationalBase):
    __tablename__ = "operational_match_tolerance_policies"
    __table_args__ = (
        CheckConstraint("status IN ('active','change_pending')", name="ck_match_policy_status"),
        CheckConstraint("price_tolerance_pct >= 0 AND price_tolerance_pct <= 100", name="ck_match_price_tolerance"),
        CheckConstraint("amount_tolerance >= 0", name="ck_match_amount_tolerance"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_key: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, default="three_way_default")
    price_tolerance_pct: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False, default=0)
    amount_tolerance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    pending_price_tolerance_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    pending_amount_tolerance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    requested_by: Mapped[str | None] = mapped_column(String(200))
    approved_by: Mapped[str | None] = mapped_column(String(200))
    approval_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class OperationalSupplierAdjustment(OperationalBase):
    __tablename__ = "operational_supplier_adjustments"
    __table_args__ = (
        UniqueConstraint("supplier_code", "supplier_reference", name="uq_supplier_adjustment_reference"),
        CheckConstraint("adjustment_type IN ('credit_note','debit_note')", name="ck_supplier_adjustment_type"),
        CheckConstraint("status IN ('draft','submitted','approved','rejected','cancelled','posted','reversed')", name="ck_supplier_adjustment_status"),
        CheckConstraint("accounting_treatment IN ('price_variance','freight_landed_cost','administrative_expense')", name="ck_supplier_adjustment_treatment"),
        CheckConstraint("posting_enabled = false", name="ck_supplier_adjustment_no_posting"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    adjustment_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    supplier_reference: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    supplier_invoice_id: Mapped[int] = mapped_column(ForeignKey("operational_supplier_invoices.id"), nullable=False, index=True)
    adjustment_type: Mapped[str] = mapped_column(String(20), nullable=False)
    supplier_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    adjustment_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    accounting_treatment: Mapped[str] = mapped_column(String(40), nullable=False, default="price_variance")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    posting_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decision_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    state_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    state_changed_by: Mapped[str] = mapped_column(String(200), nullable=False, default="system")


class OperationalSupplierAdjustmentLine(OperationalBase):
    __tablename__ = "operational_supplier_adjustment_lines"
    __table_args__ = (
        UniqueConstraint("adjustment_id", "supplier_invoice_line_id", name="uq_supplier_adjustment_invoice_line"),
        CheckConstraint("quantity > 0 AND unit_price >= 0", name="ck_supplier_adjustment_line_values"),
        CheckConstraint("tax_rate >= 0 AND tax_rate <= 100", name="ck_supplier_adjustment_tax_rate"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    adjustment_id: Mapped[int] = mapped_column(ForeignKey("operational_supplier_adjustments.id", ondelete="CASCADE"), nullable=False, index=True)
    supplier_invoice_line_id: Mapped[int] = mapped_column(ForeignKey("operational_supplier_invoice_lines.id"), nullable=False)
    sku: Mapped[str] = mapped_column(String(160), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)


class OperationalSupplierAdjustmentPostingRehearsal(OperationalBase):
    __tablename__ = "operational_supplier_adjustment_posting_rehearsals"
    __table_args__ = (
        UniqueConstraint("supplier_adjustment_id", "adjustment_revision", name="uq_supplier_adjustment_rehearsal_revision"),
        CheckConstraint("status = 'balanced_non_posting'", name="ck_supplier_adjustment_rehearsal_status"),
        CheckConstraint("posting_enabled = false", name="ck_supplier_adjustment_rehearsal_no_posting"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rehearsal_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    supplier_adjustment_id: Mapped[int] = mapped_column(ForeignKey("operational_supplier_adjustments.id"), nullable=False, index=True)
    adjustment_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    original_invoice_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    period_key: Mapped[str] = mapped_column(String(40), nullable=False)
    posting_fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    journal_json: Mapped[str] = mapped_column(Text, nullable=False)
    reversal_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="balanced_non_posting")
    posting_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    generated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def _audit(session: Session, event_type: str, actor: str, resource_key: str, detail: str) -> None:
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=event_type,
                                      actor=actor, resource_key=resource_key, detail=detail))


def _allowed(location_code: str, allowed_locations: tuple[str, ...]) -> bool:
    allowed = {item.upper() for item in allowed_locations}
    return not allowed or "*" in allowed or location_code.upper() in allowed


def _trn(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned if re.fullmatch(r"\d{15}", cleaned) else None


def _create_tax_document(session: Session, invoice: OperationalSupplierInvoice, *,
                         document_type: str, supply_date: date | None,
                         supplier_name: str, supplier_address: str, supplier_trn: str | None,
                         recipient_name: str, recipient_address: str, recipient_trn: str | None,
                         actor: str) -> OperationalSupplierTaxDocument:
    if document_type not in {"tax_invoice", "simplified_tax_invoice", "non_tax_invoice"}:
        raise ValueError("Unsupported supplier tax-document type")
    supply_date = supply_date or invoice.invoice_date
    failures: list[str] = []
    if not supplier_name.strip() or not supplier_address.strip():
        failures.append("supplier name and address are required")
    if not recipient_name.strip() or not recipient_address.strip():
        failures.append("recipient name and address are required")
    if supply_date > invoice.invoice_date or (invoice.invoice_date - supply_date).days > 14:
        failures.append("invoice must be issued on or within 14 days after the supply date")
    normalized_supplier_trn = _trn(supplier_trn)
    normalized_recipient_trn = _trn(recipient_trn)
    taxable = Decimal(invoice.tax_amount) > 0
    if taxable and document_type == "non_tax_invoice":
        failures.append("a document carrying VAT must be identified as a tax invoice")
    if document_type != "non_tax_invoice":
        if normalized_supplier_trn is None:
            failures.append("supplier TRN must contain exactly 15 digits")
        if normalized_recipient_trn is None:
            failures.append("registered recipient TRN must contain exactly 15 digits")
        if document_type == "simplified_tax_invoice" and Decimal(invoice.total_amount) > Decimal("10000"):
            failures.append("simplified tax invoice exceeds AED 10,000 for a VAT-registered recipient")
    elif taxable or any(Decimal(line.tax_rate) for line in session.scalars(select(
            OperationalSupplierInvoiceLine).where(OperationalSupplierInvoiceLine.invoice_id == invoice.id))):
        failures.append("non-tax invoice must have zero VAT")

    master = session.scalar(select(OperationalPartyMaster).where(
        OperationalPartyMaster.party_code == invoice.supplier_code,
        OperationalPartyMaster.party_kind.in_(("supplier", "both"))))
    master_trn = _trn(master.tax_number) if master else None
    if master_trn and normalized_supplier_trn != master_trn:
        failures.append("supplier TRN differs from the governed supplier master")
        master_cross_check = "mismatch"
    elif master_trn:
        master_cross_check = "matched"
    else:
        master_cross_check = "master_review_required"

    summary = "; ".join(failures) if failures else (
        "Required invoice identity, dates, AED totals, VAT data and TRNs validated; "
        + ("supplier master TRN matched" if master_cross_check == "matched"
           else "supplier master TRN requires final-cutover review"))
    document = OperationalSupplierTaxDocument(
        tax_document_key=str(uuid.uuid4()), supplier_invoice_id=invoice.id,
        document_type=document_type, supply_date=supply_date,
        supplier_name=supplier_name.strip(), supplier_address=supplier_address.strip(),
        supplier_trn=normalized_supplier_trn, recipient_name=recipient_name.strip(),
        recipient_address=recipient_address.strip(), recipient_trn=normalized_recipient_trn,
        validation_status="exception" if failures else "passed",
        validation_summary=summary, master_cross_check=master_cross_check,
        posting_enabled=False, validated_by=actor,
    )
    session.add(document)
    return document


def accepted_po_quantities(session: Session, purchase_order_no: str) -> dict[str, Decimal]:
    rows = session.execute(select(OperationalGoodsReceiptLine.sku, OperationalGoodsReceiptLine.accepted_quantity)
        .join(OperationalGoodsReceipt, OperationalGoodsReceipt.id == OperationalGoodsReceiptLine.receipt_id)
        .where(OperationalGoodsReceipt.purchase_reference == purchase_order_no,
               OperationalGoodsReceipt.status == "accepted")).all()
    totals: dict[str, Decimal] = {}
    for sku, quantity in rows:
        totals[sku] = totals.get(sku, Decimal("0")) + Decimal(quantity)
    return totals


def validate_po_receipt(session: Session, *, purchase_reference: str | None, supplier_code: str,
                        location_code: str, lines: list[dict], exclude_receipt_id: int | None = None) -> None:
    if not purchase_reference:
        return
    po = session.scalar(select(OperationalPurchaseOrder).where(
        OperationalPurchaseOrder.purchase_order_no == purchase_reference))
    if po is None:
        return
    if po.status != "approved":
        raise ValueError("Goods receipt requires an approved purchase order")
    if po.supplier_code != supplier_code or po.location_code != location_code:
        raise ValueError("Goods receipt supplier and location must match the purchase order")
    po_lines = {row.sku: row for row in session.scalars(select(OperationalPurchaseOrderLine).where(
        OperationalPurchaseOrderLine.purchase_order_id == po.id))}
    supplied = [item["sku"] for item in lines]
    if len(supplied) != len(set(supplied)) or not set(supplied).issubset(po_lines):
        raise ValueError("Goods receipt lines must be unique items from the purchase order")
    prior_query = select(OperationalGoodsReceiptLine.sku, OperationalGoodsReceiptLine.received_quantity).join(
        OperationalGoodsReceipt, OperationalGoodsReceipt.id == OperationalGoodsReceiptLine.receipt_id).where(
        OperationalGoodsReceipt.purchase_reference == po.purchase_order_no,
        OperationalGoodsReceipt.status.not_in(("cancelled", "rejected")))
    if exclude_receipt_id is not None:
        prior_query = prior_query.where(OperationalGoodsReceipt.id != exclude_receipt_id)
    prior: dict[str, Decimal] = {}
    for sku, quantity in session.execute(prior_query):
        prior[sku] = prior.get(sku, Decimal("0")) + Decimal(quantity)
    for item in lines:
        po_line = po_lines[item["sku"]]
        if (item["uom"].casefold() != po_line.uom.casefold()
                or Decimal(item["unit_cost_snapshot"]) != Decimal(po_line.unit_price)):
            raise ValueError(f"Goods receipt UOM and cost must match PO line {po_line.sku}")
        if prior.get(po_line.sku, Decimal("0")) + Decimal(item["received_quantity"]) > Decimal(po_line.quantity):
            raise ValueError(f"Cumulative received quantity exceeds PO quantity for {po_line.sku}")


def create_supplier_invoice(session: Session, *, purchase_order_key: str, supplier_invoice_no: str,
                            invoice_date: date, due_date: date | None, currency_code: str,
                            lines: list[dict], actor: str, document_type: str,
                            supply_date: date | None, supplier_name: str,
                            supplier_address: str, supplier_trn: str | None,
                            recipient_name: str, recipient_address: str,
                            recipient_trn: str | None,
                            allowed_locations: tuple[str, ...] = ("*",)) -> OperationalSupplierInvoice:
    po = session.scalar(select(OperationalPurchaseOrder).where(
        OperationalPurchaseOrder.purchase_order_key == purchase_order_key))
    if po is None or po.status != "approved" or not _allowed(po.location_code, allowed_locations):
        raise ValueError("Approved purchase order was not found in the user's location scope")
    supplier_invoice_no = supplier_invoice_no.strip()
    if not lines:
        raise ValueError("At least one supplier invoice line is required")
    if session.scalar(select(OperationalSupplierInvoice.id).where(
            OperationalSupplierInvoice.supplier_code == po.supplier_code,
            OperationalSupplierInvoice.supplier_invoice_no == supplier_invoice_no)):
        raise ValueError("This supplier invoice number already exists for the supplier")
    if currency_code.upper() != po.currency_code:
        raise ValueError("Supplier invoice currency must match the purchase order")
    if invoice_date > date.today() or (due_date is not None and due_date < invoice_date):
        raise ValueError("Supplier invoice dates are invalid")
    po_lines = {row.sku: row for row in session.scalars(select(OperationalPurchaseOrderLine).where(
        OperationalPurchaseOrderLine.purchase_order_id == po.id))}
    supplied = [item["sku"] for item in lines]
    if len(supplied) != len(set(supplied)) or not set(supplied).issubset(po_lines):
        raise ValueError("Supplier invoice lines must be unique purchase-order items")
    invoice = OperationalSupplierInvoice(invoice_key=str(uuid.uuid4()),
        supplier_invoice_no=supplier_invoice_no, purchase_order_id=po.id,
        supplier_code=po.supplier_code, location_code=po.location_code, invoice_date=invoice_date,
        due_date=due_date, currency_code=po.currency_code, subtotal=0, tax_amount=0,
        total_amount=0, status="draft", match_status="pending", posting_enabled=False, created_by=actor,
        state_changed_by=actor)
    session.add(invoice); session.flush()
    subtotal = tax = Decimal("0")
    for item in lines:
        po_line = po_lines[item["sku"]]
        quantity = Decimal(item["quantity"]).quantize(QUANTITY)
        unit_price = Decimal(item["unit_price"])
        tax_rate = Decimal(item.get("tax_rate", 5))
        if quantity <= 0 or unit_price < 0 or tax_rate < 0 or tax_rate > 100:
            raise ValueError(f"Supplier invoice values are invalid for {po_line.sku}")
        net = _money(quantity * unit_price)
        tax_amount = _money(net * tax_rate / Decimal("100"))
        session.add(OperationalSupplierInvoiceLine(invoice_id=invoice.id,
            purchase_order_line_id=po_line.id, sku=po_line.sku, quantity=quantity,
            unit_price=unit_price, tax_rate=tax_rate, net_amount=net,
            tax_amount=tax_amount, gross_amount=net + tax_amount))
        subtotal += net; tax += tax_amount
    invoice.subtotal = _money(subtotal); invoice.tax_amount = _money(tax)
    invoice.total_amount = invoice.subtotal + invoice.tax_amount
    tax_document = _create_tax_document(session, invoice, document_type=document_type,
        supply_date=supply_date, supplier_name=supplier_name, supplier_address=supplier_address,
        supplier_trn=supplier_trn, recipient_name=recipient_name,
        recipient_address=recipient_address, recipient_trn=recipient_trn, actor=actor)
    _audit(session, "procurement.supplier_invoice.created", actor, invoice.invoice_key,
           f"{invoice.supplier_invoice_no}; {po.purchase_order_no}; tax validation {tax_document.validation_status}; no posting")
    session.commit()
    return invoice


def match_policy(session: Session) -> OperationalMatchTolerancePolicy:
    policy = session.scalar(select(OperationalMatchTolerancePolicy).where(
        OperationalMatchTolerancePolicy.policy_key == "three_way_default"))
    if policy is None:
        policy = OperationalMatchTolerancePolicy(policy_key="three_way_default",
            price_tolerance_pct=0, amount_tolerance=0, status="active")
        session.add(policy); session.commit()
    return policy


def request_policy_change(session: Session, *, price_tolerance_pct: Decimal,
                          amount_tolerance: Decimal, expected_revision: int,
                          note: str, actor: str) -> OperationalMatchTolerancePolicy:
    policy = match_policy(session)
    if policy.revision != expected_revision:
        raise ValueError(f"Match-policy revision conflict; current revision is {policy.revision}")
    if policy.status == "change_pending":
        raise ValueError("A match-tolerance change is already pending")
    price_tolerance_pct = Decimal(price_tolerance_pct)
    amount_tolerance = _money(amount_tolerance)
    if price_tolerance_pct < 0 or price_tolerance_pct > 100 or amount_tolerance < 0:
        raise ValueError("Match tolerances must be within the permitted range")
    policy.pending_price_tolerance_pct = price_tolerance_pct
    policy.pending_amount_tolerance = amount_tolerance
    policy.status = "change_pending"; policy.requested_by = actor
    policy.approved_by = None; policy.approval_note = note.strip(); policy.revision += 1
    _audit(session, "procurement.match_policy.requested", actor, policy.policy_key,
           f"price {price_tolerance_pct}%; amount AED {amount_tolerance}; {note.strip()}")
    session.commit(); return policy


def decide_policy_change(session: Session, *, action: str, expected_revision: int,
                         note: str, actor: str) -> OperationalMatchTolerancePolicy:
    policy = match_policy(session)
    if policy.revision != expected_revision:
        raise ValueError(f"Match-policy revision conflict; current revision is {policy.revision}")
    if policy.status != "change_pending" or action not in {"approve", "reject"}:
        raise ValueError("A pending match-tolerance change is required")
    if policy.requested_by == actor:
        raise ValueError("The tolerance-policy maker cannot approve their own change")
    if action == "approve":
        policy.price_tolerance_pct = policy.pending_price_tolerance_pct
        policy.amount_tolerance = policy.pending_amount_tolerance
    policy.pending_price_tolerance_pct = None; policy.pending_amount_tolerance = None
    policy.status = "active"; policy.approved_by = actor
    policy.approval_note = note.strip(); policy.revision += 1
    _audit(session, f"procurement.match_policy.{action}", actor, policy.policy_key, note.strip())
    session.commit(); return policy


def evaluate_invoice_match(session: Session, invoice: OperationalSupplierInvoice, *, actor: str) -> dict:
    if invoice.status not in {"draft", "exception"}:
        raise ValueError("Only a draft or exception invoice can be matched")
    po = session.get(OperationalPurchaseOrder, invoice.purchase_order_id)
    po_lines = {row.id: row for row in session.scalars(select(OperationalPurchaseOrderLine).where(
        OperationalPurchaseOrderLine.purchase_order_id == po.id))}
    accepted = accepted_po_quantities(session, po.purchase_order_no)
    approved_rows = session.execute(select(OperationalSupplierInvoiceLine.sku,
        OperationalSupplierInvoiceLine.quantity).join(OperationalSupplierInvoice,
        OperationalSupplierInvoice.id == OperationalSupplierInvoiceLine.invoice_id).where(
        OperationalSupplierInvoice.purchase_order_id == po.id,
        OperationalSupplierInvoice.status == "approved")).all()
    already_invoiced: dict[str, Decimal] = {}
    for sku, quantity in approved_rows:
        already_invoiced[sku] = already_invoiced.get(sku, Decimal("0")) + Decimal(quantity)
    policy = match_policy(session)
    exceptions: list[str] = []
    tolerance_reviews: list[str] = []
    tax_document = session.scalar(select(OperationalSupplierTaxDocument).where(
        OperationalSupplierTaxDocument.supplier_invoice_id == invoice.id))
    if tax_document is None or tax_document.validation_status != "passed":
        exceptions.append("tax document: " + (
            tax_document.validation_summary if tax_document else "validation record is missing"))
    lines = list(session.scalars(select(OperationalSupplierInvoiceLine).where(
        OperationalSupplierInvoiceLine.invoice_id == invoice.id)))
    for line in lines:
        po_line = po_lines[line.purchase_order_line_id]
        available_order = Decimal(po_line.quantity) - already_invoiced.get(line.sku, Decimal("0"))
        available_receipt = accepted.get(line.sku, Decimal("0")) - already_invoiced.get(line.sku, Decimal("0"))
        if Decimal(line.quantity) > available_order:
            exceptions.append(f"{line.sku}: invoice quantity exceeds uninvoiced PO quantity")
        if Decimal(line.quantity) > available_receipt:
            exceptions.append(f"{line.sku}: invoice quantity exceeds accepted uninvoiced receipt quantity")
        price_difference = abs(Decimal(line.unit_price) - Decimal(po_line.unit_price))
        if price_difference:
            percent_difference = (price_difference / Decimal(po_line.unit_price) * Decimal("100")) if po_line.unit_price else Decimal("100")
            amount_difference = _money(price_difference * Decimal(line.quantity))
            if (percent_difference <= Decimal(policy.price_tolerance_pct)
                    or amount_difference <= Decimal(policy.amount_tolerance)):
                tolerance_reviews.append(
                    f"{line.sku}: price variance {percent_difference.quantize(Decimal('0.0001'))}% / AED {amount_difference}")
            else:
                exceptions.append(f"{line.sku}: unit price differs from PO beyond approved tolerance")
        if Decimal(line.tax_rate) != Decimal(po_line.tax_rate):
            exceptions.append(f"{line.sku}: VAT rate differs from PO")
    requires_tolerance_review = not exceptions and bool(tolerance_reviews)
    invoice.match_status = "exception" if exceptions or requires_tolerance_review else "passed"
    invoice.status = "exception" if exceptions or requires_tolerance_review else "matched"
    if exceptions:
        invoice.match_summary = "; ".join(exceptions)
    elif requires_tolerance_review:
        invoice.match_summary = "TOLERANCE_REVIEW: " + "; ".join(tolerance_reviews)
    else:
        invoice.match_summary = "PO, accepted receipt, price, quantity, VAT, supplier and currency matched"
    invoice.revision += 1
    _audit(session, "procurement.supplier_invoice.matched", actor, invoice.invoice_key,
           invoice.match_summary)
    session.commit()
    return {"passed": not exceptions and not requires_tolerance_review,
            "requires_tolerance_review": requires_tolerance_review,
            "exceptions": exceptions, "tolerance_reviews": tolerance_reviews}


def approve_invoice_tolerance(session: Session, invoice: OperationalSupplierInvoice, *,
                              expected_revision: int, note: str, actor: str) -> OperationalSupplierInvoice:
    if invoice.revision != expected_revision:
        raise ValueError(f"Supplier-invoice revision conflict; current revision is {invoice.revision}")
    if invoice.status != "exception" or not (invoice.match_summary or "").startswith("TOLERANCE_REVIEW:"):
        raise ValueError("This invoice does not have a tolerance escalation")
    if invoice.created_by == actor:
        raise ValueError("The supplier-invoice maker cannot approve its tolerance escalation")
    invoice.status = "matched"; invoice.match_status = "passed"
    invoice.match_summary = f"Tolerance escalation approved by {actor}: {note.strip()}"
    invoice.revision += 1
    _audit(session, "procurement.supplier_invoice.tolerance_approved", actor,
           invoice.invoice_key, f"{note.strip()}; no posting")
    session.commit(); return invoice


def rehearse_supplier_invoice_posting(session: Session, invoice: OperationalSupplierInvoice, *, actor: str) -> dict:
    if invoice.status != "approved" or invoice.match_status != "passed":
        raise ValueError("Only an approved, passed supplier invoice can be rehearsed")
    tax_document = session.scalar(select(OperationalSupplierTaxDocument).where(
        OperationalSupplierTaxDocument.supplier_invoice_id == invoice.id))
    if tax_document is None or tax_document.validation_status != "passed":
        raise ValueError("A passed supplier tax-document validation is required")
    period = session.scalar(select(OperationalFiscalPeriod).where(
        OperationalFiscalPeriod.starts_on <= invoice.invoice_date,
        OperationalFiscalPeriod.ends_on >= invoice.invoice_date,
        OperationalFiscalPeriod.status == "open",
        OperationalFiscalPeriod.rehearsal_enabled.is_(True),
    ))
    if period is None:
        raise ValueError("Invoice date is not in an open rehearsal-enabled fiscal period")
    existing = session.scalar(select(OperationalSupplierInvoicePostingRehearsal).where(
        OperationalSupplierInvoicePostingRehearsal.supplier_invoice_id == invoice.id,
        OperationalSupplierInvoicePostingRehearsal.invoice_revision == invoice.revision))
    if existing:
        return _rehearsal_payload(existing, invoice, idempotent_replay=True)
    journal = [
        {"account_code": "GRNI", "account": "Goods received not invoiced", "debit": invoice.subtotal, "credit": Decimal("0")},
        {"account_code": "1320", "account": "Input VAT recoverable", "debit": invoice.tax_amount, "credit": Decimal("0")},
        {"account_code": "2100", "account": "Trade payables", "debit": Decimal("0"), "credit": invoice.total_amount},
    ]
    reversal = [{**line, "debit": line["credit"], "credit": line["debit"]}
                for line in reversed(journal)]
    debit = sum((Decimal(line["debit"]) for line in journal), Decimal("0"))
    credit = sum((Decimal(line["credit"]) for line in journal), Decimal("0"))
    if debit != credit:
        raise RuntimeError("Supplier-invoice posting rehearsal is not balanced")
    source = json.dumps({"invoice_key": invoice.invoice_key, "revision": invoice.revision,
        "period_key": period.period_key, "journal": journal, "reversal": reversal},
        default=str, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(source.encode()).hexdigest()
    rehearsal = OperationalSupplierInvoicePostingRehearsal(
        rehearsal_key=str(uuid.uuid4()), supplier_invoice_id=invoice.id,
        invoice_revision=invoice.revision, period_key=period.period_key,
        posting_fingerprint=fingerprint,
        journal_json=json.dumps(journal, default=str, sort_keys=True),
        reversal_json=json.dumps(reversal, default=str, sort_keys=True),
        status="balanced_non_posting", posting_enabled=False, generated_by=actor,
    )
    session.add(rehearsal)
    _audit(session, "procurement.supplier_invoice.posting_rehearsed", actor,
           invoice.invoice_key, f"AED {debit}; fingerprint {fingerprint}; no posting")
    session.commit()
    return _rehearsal_payload(rehearsal, invoice)


def _rehearsal_payload(rehearsal: OperationalSupplierInvoicePostingRehearsal,
                       invoice: OperationalSupplierInvoice, *, idempotent_replay: bool = False) -> dict:
    journal = json.loads(rehearsal.journal_json)
    reversal = json.loads(rehearsal.reversal_json)
    return {"rehearsal_key": rehearsal.rehearsal_key, "invoice_key": invoice.invoice_key,
        "supplier_invoice_no": invoice.supplier_invoice_no, "period_key": rehearsal.period_key,
        "status": rehearsal.status, "journal": journal, "reversal_plan": reversal,
        "debit": invoice.total_amount, "credit": invoice.total_amount,
        "posting_fingerprint": rehearsal.posting_fingerprint,
        "idempotency_key": f"supplier-invoice:{invoice.invoice_key}:{invoice.revision}:{rehearsal.posting_fingerprint[:20]}",
        "idempotent_replay": idempotent_replay, "posting_enabled": False}


def decide_supplier_invoice(session: Session, invoice: OperationalSupplierInvoice, *, action: str,
                            expected_revision: int, note: str, actor: str) -> OperationalSupplierInvoice:
    if invoice.revision != expected_revision:
        raise ValueError(f"Supplier-invoice revision conflict; current revision is {invoice.revision}")
    if invoice.created_by == actor:
        raise ValueError("The supplier-invoice maker cannot approve or reject the same invoice")
    if action == "approve" and (invoice.status != "matched" or invoice.match_status != "passed"):
        raise ValueError("Only a passed three-way match can be approved")
    if action == "reject" and invoice.status not in {"matched", "exception"}:
        raise ValueError("Only a matched or exception invoice can be rejected")
    invoice.status = "approved" if action == "approve" else "rejected"
    invoice.decided_by = actor; invoice.decision_note = note.strip(); invoice.revision += 1
    _audit(session, f"procurement.supplier_invoice.{action}", actor, invoice.invoice_key,
           f"{note.strip()}; no payable or ledger posting")
    session.commit(); return invoice


def create_supplier_adjustment(session: Session, *, invoice_key: str, adjustment_type: str,
                               supplier_reference: str, adjustment_date: date, reason: str,
                               accounting_treatment: str = "price_variance", lines: list[dict], actor: str,
                               allowed_locations: tuple[str, ...] = ("*",)) -> OperationalSupplierAdjustment:
    invoice = session.scalar(select(OperationalSupplierInvoice).where(
        OperationalSupplierInvoice.invoice_key == invoice_key))
    if invoice is None or invoice.status not in {"approved", "posted"} or not _allowed(invoice.location_code, allowed_locations):
        raise ValueError("Approved or posted supplier invoice was not found in the user's location scope")
    if adjustment_type not in {"credit_note", "debit_note"} or adjustment_date > date.today():
        raise ValueError("Supplier adjustment type or date is invalid")
    if accounting_treatment not in {"price_variance", "freight_landed_cost", "administrative_expense"}:
        raise ValueError("Supplier adjustment accounting treatment is invalid")
    supplier_reference = supplier_reference.strip()
    if session.scalar(select(OperationalSupplierAdjustment.id).where(
            OperationalSupplierAdjustment.supplier_code == invoice.supplier_code,
            OperationalSupplierAdjustment.supplier_reference == supplier_reference)):
        raise ValueError("This supplier adjustment reference already exists")
    invoice_lines = {row.sku: row for row in session.scalars(select(OperationalSupplierInvoiceLine).where(
        OperationalSupplierInvoiceLine.invoice_id == invoice.id))}
    supplied = [item["sku"] for item in lines]
    if not lines or len(supplied) != len(set(supplied)) or not set(supplied).issubset(invoice_lines):
        raise ValueError("Supplier adjustment lines must be unique approved-invoice items")
    if adjustment_type == "credit_note":
        from .purchase_returns import OperationalPurchaseReturn, OperationalPurchaseReturnLine
        purchase_order = session.get(OperationalPurchaseOrder, invoice.purchase_order_id)
        receipt_refs: list[str] = []
        if purchase_order:
            for receipt in session.scalars(select(OperationalGoodsReceipt).where(
                    OperationalGoodsReceipt.purchase_reference == purchase_order.purchase_order_no,
                    OperationalGoodsReceipt.supplier_code == invoice.supplier_code)):
                receipt_refs.extend((receipt.receipt_key, receipt.receipt_no))
        source_match = (OperationalPurchaseReturn.source_reference_type == "purchase_invoice") & (
            OperationalPurchaseReturn.source_reference_key.in_((invoice.invoice_key, invoice.supplier_invoice_no)))
        if receipt_refs:
            source_match = or_(source_match,
                (OperationalPurchaseReturn.source_reference_type == "goods_receipt")
                & (OperationalPurchaseReturn.source_reference_key.in_(receipt_refs)))
        overlap = session.scalar(select(OperationalPurchaseReturnLine.id).join(OperationalPurchaseReturn).where(
            source_match,
            OperationalPurchaseReturn.status.in_(("submitted", "approved", "posted")),
            OperationalPurchaseReturnLine.sku.in_(supplied)))
        if overlap:
            raise ValueError("A purchase return already controls this invoice item; use its debit note to avoid duplicate supplier credit")
    prior_credits: dict[str, Decimal] = {}
    if adjustment_type == "credit_note":
        rows = session.execute(select(OperationalSupplierAdjustmentLine.sku,
            OperationalSupplierAdjustmentLine.quantity).join(OperationalSupplierAdjustment,
            OperationalSupplierAdjustment.id == OperationalSupplierAdjustmentLine.adjustment_id).where(
            OperationalSupplierAdjustment.supplier_invoice_id == invoice.id,
            OperationalSupplierAdjustment.adjustment_type == "credit_note",
            OperationalSupplierAdjustment.status.not_in(("rejected", "cancelled")))).all()
        for sku, quantity in rows:
            prior_credits[sku] = prior_credits.get(sku, Decimal("0")) + Decimal(quantity)
    adjustment = OperationalSupplierAdjustment(adjustment_key=str(uuid.uuid4()),
        supplier_reference=supplier_reference, supplier_invoice_id=invoice.id,
        adjustment_type=adjustment_type, supplier_code=invoice.supplier_code,
        location_code=invoice.location_code, adjustment_date=adjustment_date,
        reason=reason.strip(), accounting_treatment=accounting_treatment,
        subtotal=0, tax_amount=0, total_amount=0,
        status="draft", posting_enabled=False, created_by=actor, state_changed_by=actor)
    session.add(adjustment); session.flush()
    subtotal = tax = Decimal("0")
    for item in lines:
        source = invoice_lines[item["sku"]]
        quantity = Decimal(item["quantity"]).quantize(QUANTITY)
        unit_price = Decimal(item.get("unit_price", source.unit_price))
        tax_rate = Decimal(item.get("tax_rate", source.tax_rate))
        if quantity <= 0 or unit_price < 0 or tax_rate < 0 or tax_rate > 100:
            raise ValueError(f"Supplier adjustment values are invalid for {source.sku}")
        if (adjustment_type == "credit_note"
                and prior_credits.get(source.sku, Decimal("0")) + quantity > Decimal(source.quantity)):
            raise ValueError(f"Cumulative credit-note quantity exceeds invoice quantity for {source.sku}")
        net = _money(quantity * unit_price); tax_amount = _money(net * tax_rate / Decimal("100"))
        session.add(OperationalSupplierAdjustmentLine(adjustment_id=adjustment.id,
            supplier_invoice_line_id=source.id, sku=source.sku, quantity=quantity,
            unit_price=unit_price, tax_rate=tax_rate, net_amount=net,
            tax_amount=tax_amount, gross_amount=net + tax_amount))
        subtotal += net; tax += tax_amount
    adjustment.subtotal = _money(subtotal); adjustment.tax_amount = _money(tax)
    adjustment.total_amount = adjustment.subtotal + adjustment.tax_amount
    if adjustment_type == "credit_note":
        prior_debits = session.scalar(select(func.coalesce(func.sum(OperationalSupplierAdjustment.total_amount), 0)).where(
            OperationalSupplierAdjustment.supplier_invoice_id == invoice.id,
            OperationalSupplierAdjustment.adjustment_type == "debit_note",
            OperationalSupplierAdjustment.status.not_in(("rejected", "cancelled")))) or Decimal("0")
        prior_credit_total = session.scalar(select(func.coalesce(func.sum(OperationalSupplierAdjustment.total_amount), 0)).where(
            OperationalSupplierAdjustment.supplier_invoice_id == invoice.id,
            OperationalSupplierAdjustment.adjustment_type == "credit_note",
            OperationalSupplierAdjustment.id != adjustment.id,
            OperationalSupplierAdjustment.status.not_in(("rejected", "cancelled")))) or Decimal("0")
        if Decimal(prior_credit_total) + adjustment.total_amount > invoice.total_amount + Decimal(prior_debits):
            raise ValueError("Cumulative supplier credits cannot exceed the invoice plus controlled debit adjustments")
    _audit(session, "procurement.supplier_adjustment.created", actor, adjustment.adjustment_key,
           f"{adjustment_type}; {supplier_reference}; no posting")
    session.commit(); return adjustment


def transition_supplier_adjustment(session: Session, adjustment: OperationalSupplierAdjustment, *,
                                   action: str, expected_revision: int, note: str,
                                   actor: str) -> OperationalSupplierAdjustment:
    if adjustment.revision != expected_revision:
        raise ValueError(f"Supplier-adjustment revision conflict; current revision is {adjustment.revision}")
    transitions = {("draft", "submit"): "submitted", ("draft", "cancel"): "cancelled",
                   ("submitted", "approve"): "approved", ("submitted", "reject"): "rejected"}
    target = transitions.get((adjustment.status, action))
    if target is None:
        raise ValueError(f"Cannot {action} a {adjustment.status} supplier adjustment")
    if action in {"approve", "reject"} and adjustment.created_by == actor:
        raise ValueError("The supplier-adjustment maker cannot approve or reject the same document")
    adjustment.status = target; adjustment.revision += 1
    adjustment.state_changed_at = utc_now(); adjustment.state_changed_by = actor
    if action in {"approve", "reject"}:
        adjustment.decided_by = actor; adjustment.decision_note = note.strip()
    _audit(session, f"procurement.supplier_adjustment.{action}", actor,
           adjustment.adjustment_key, f"{note.strip()}; no posting")
    session.commit(); return adjustment


ADJUSTMENT_ACCOUNTS = {
    "price_variance": ("5110", "Purchase price variance"),
    "freight_landed_cost": ("5100", "Freight and landed cost"),
    "administrative_expense": ("6100", "Administrative expense"),
}


def rehearse_supplier_adjustment_posting(session: Session, adjustment: OperationalSupplierAdjustment, *, actor: str) -> dict:
    if adjustment.status != "approved":
        raise ValueError("Only an approved supplier adjustment can be rehearsed")
    invoice = session.get(OperationalSupplierInvoice, adjustment.supplier_invoice_id)
    if invoice is None or invoice.status != "posted":
        raise ValueError("The original supplier invoice must be posted before its adjustment")
    period = session.scalar(select(OperationalFiscalPeriod).where(
        OperationalFiscalPeriod.starts_on <= adjustment.adjustment_date,
        OperationalFiscalPeriod.ends_on >= adjustment.adjustment_date,
        OperationalFiscalPeriod.status == "open",
        OperationalFiscalPeriod.rehearsal_enabled.is_(True)))
    if period is None:
        raise ValueError("Adjustment date is not in an open rehearsal-enabled fiscal period")
    existing = session.scalar(select(OperationalSupplierAdjustmentPostingRehearsal).where(
        OperationalSupplierAdjustmentPostingRehearsal.supplier_adjustment_id == adjustment.id,
        OperationalSupplierAdjustmentPostingRehearsal.adjustment_revision == adjustment.revision))
    if existing:
        return _adjustment_rehearsal_payload(existing, adjustment, invoice, idempotent_replay=True)
    account_code, account_name = ADJUSTMENT_ACCOUNTS[adjustment.accounting_treatment]
    if adjustment.adjustment_type == "credit_note":
        journal = [
            {"account_code": "2100", "account": "Trade payables", "debit": adjustment.total_amount, "credit": Decimal("0")},
            {"account_code": "1320", "account": "Input VAT recoverable", "debit": Decimal("0"), "credit": adjustment.tax_amount},
            {"account_code": account_code, "account": account_name, "debit": Decimal("0"), "credit": adjustment.subtotal},
        ]
    else:
        journal = [
            {"account_code": account_code, "account": account_name, "debit": adjustment.subtotal, "credit": Decimal("0")},
            {"account_code": "1320", "account": "Input VAT recoverable", "debit": adjustment.tax_amount, "credit": Decimal("0")},
            {"account_code": "2100", "account": "Trade payables", "debit": Decimal("0"), "credit": adjustment.total_amount},
        ]
    reversal = [{**line, "debit": line["credit"], "credit": line["debit"]} for line in reversed(journal)]
    debit = sum((Decimal(line["debit"]) for line in journal), Decimal("0"))
    credit = sum((Decimal(line["credit"]) for line in journal), Decimal("0"))
    if debit != credit:
        raise RuntimeError("Supplier-adjustment posting rehearsal is not balanced")
    source = json.dumps({"adjustment_key": adjustment.adjustment_key, "revision": adjustment.revision,
        "invoice_key": invoice.invoice_key, "invoice_revision": invoice.revision,
        "period_key": period.period_key, "journal": journal, "reversal": reversal},
        default=str, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(source.encode()).hexdigest()
    rehearsal = OperationalSupplierAdjustmentPostingRehearsal(
        rehearsal_key=str(uuid.uuid4()), supplier_adjustment_id=adjustment.id,
        adjustment_revision=adjustment.revision, original_invoice_revision=invoice.revision,
        period_key=period.period_key, posting_fingerprint=fingerprint,
        journal_json=json.dumps(journal, default=str, sort_keys=True),
        reversal_json=json.dumps(reversal, default=str, sort_keys=True),
        status="balanced_non_posting", posting_enabled=False, generated_by=actor)
    session.add(rehearsal)
    _audit(session, "procurement.supplier_adjustment.posting_rehearsed", actor,
           adjustment.adjustment_key, f"AED {debit}; {adjustment.accounting_treatment}; fingerprint {fingerprint}; no posting")
    session.commit()
    return _adjustment_rehearsal_payload(rehearsal, adjustment, invoice)


def _adjustment_rehearsal_payload(rehearsal: OperationalSupplierAdjustmentPostingRehearsal,
                                  adjustment: OperationalSupplierAdjustment,
                                  invoice: OperationalSupplierInvoice, *, idempotent_replay: bool = False) -> dict:
    return {"rehearsal_key": rehearsal.rehearsal_key, "adjustment_key": adjustment.adjustment_key,
        "supplier_reference": adjustment.supplier_reference, "invoice_key": invoice.invoice_key,
        "supplier_invoice_no": invoice.supplier_invoice_no, "period_key": rehearsal.period_key,
        "status": rehearsal.status, "journal": json.loads(rehearsal.journal_json),
        "reversal_plan": json.loads(rehearsal.reversal_json),
        "debit": adjustment.total_amount, "credit": adjustment.total_amount,
        "posting_fingerprint": rehearsal.posting_fingerprint,
        "idempotency_key": f"supplier-adjustment:{adjustment.adjustment_key}:{adjustment.revision}:{rehearsal.posting_fingerprint[:20]}",
        "idempotent_replay": idempotent_replay, "posting_enabled": False}


def policy_payload(session: Session) -> dict:
    policy = match_policy(session)
    return {"policy_key": policy.policy_key,
        "price_tolerance_pct": policy.price_tolerance_pct,
        "amount_tolerance": policy.amount_tolerance,
        "pending_price_tolerance_pct": policy.pending_price_tolerance_pct,
        "pending_amount_tolerance": policy.pending_amount_tolerance,
        "status": policy.status, "requested_by": policy.requested_by,
        "approved_by": policy.approved_by, "approval_note": policy.approval_note,
        "revision": policy.revision}


def adjustment_payload(session: Session, *, allowed_locations: tuple[str, ...] = ("*",)) -> list[dict]:
    query = select(OperationalSupplierAdjustment)
    allowed = {item.upper() for item in allowed_locations}
    if allowed and "*" not in allowed:
        query = query.where(OperationalSupplierAdjustment.location_code.in_(allowed))
    adjustments = list(session.scalars(query.order_by(OperationalSupplierAdjustment.created_at.desc())))
    result = []
    for row in adjustments:
        invoice = session.get(OperationalSupplierInvoice, row.supplier_invoice_id)
        lines = list(session.scalars(select(OperationalSupplierAdjustmentLine).where(
            OperationalSupplierAdjustmentLine.adjustment_id == row.id)))
        rehearsal = session.scalar(select(OperationalSupplierAdjustmentPostingRehearsal).where(
            OperationalSupplierAdjustmentPostingRehearsal.supplier_adjustment_id == row.id).order_by(
                OperationalSupplierAdjustmentPostingRehearsal.generated_at.desc()))
        result.append({"adjustment_key": row.adjustment_key,
            "supplier_reference": row.supplier_reference, "invoice_key": invoice.invoice_key,
            "supplier_invoice_no": invoice.supplier_invoice_no,
            "adjustment_type": row.adjustment_type, "supplier_code": row.supplier_code,
            "location_code": row.location_code, "adjustment_date": row.adjustment_date,
            "reason": row.reason, "accounting_treatment": row.accounting_treatment,
            "subtotal": row.subtotal, "tax_amount": row.tax_amount,
            "total_amount": row.total_amount, "status": row.status,
            "invoice_status": invoice.status,
            "created_by": row.created_by, "decided_by": row.decided_by,
            "revision": row.revision, "posting_enabled": False,
            "posting_rehearsal": (_adjustment_rehearsal_payload(rehearsal, row, invoice) if rehearsal else None),
            "lines": [{"sku": line.sku, "quantity": line.quantity,
                "unit_price": line.unit_price, "tax_rate": line.tax_rate,
                "gross_amount": line.gross_amount} for line in lines]})
    return result


def invoice_payload(session: Session, *, allowed_locations: tuple[str, ...] = ("*",)) -> list[dict]:
    query = select(OperationalSupplierInvoice)
    allowed = {item.upper() for item in allowed_locations}
    if allowed and "*" not in allowed:
        query = query.where(OperationalSupplierInvoice.location_code.in_(allowed))
    invoices = list(session.scalars(query.order_by(OperationalSupplierInvoice.created_at.desc())))
    result = []
    for invoice in invoices:
        po = session.get(OperationalPurchaseOrder, invoice.purchase_order_id)
        tax_document = session.scalar(select(OperationalSupplierTaxDocument).where(
            OperationalSupplierTaxDocument.supplier_invoice_id == invoice.id))
        rehearsal = session.scalar(select(OperationalSupplierInvoicePostingRehearsal).where(
            OperationalSupplierInvoicePostingRehearsal.supplier_invoice_id == invoice.id).order_by(
                OperationalSupplierInvoicePostingRehearsal.generated_at.desc()))
        lines = list(session.scalars(select(OperationalSupplierInvoiceLine).where(
            OperationalSupplierInvoiceLine.invoice_id == invoice.id)))
        result.append({"invoice_key": invoice.invoice_key,
            "supplier_invoice_no": invoice.supplier_invoice_no,
            "purchase_order_key": po.purchase_order_key, "purchase_order_no": po.purchase_order_no,
            "supplier_code": invoice.supplier_code, "location_code": invoice.location_code,
            "invoice_date": invoice.invoice_date, "due_date": invoice.due_date,
            "currency_code": invoice.currency_code, "subtotal": invoice.subtotal,
            "tax_amount": invoice.tax_amount, "total_amount": invoice.total_amount,
            "status": invoice.status, "match_status": invoice.match_status,
            "match_summary": invoice.match_summary, "created_by": invoice.created_by,
            "decided_by": invoice.decided_by, "revision": invoice.revision,
            "posting_enabled": False,
            "tax_document": ({"document_type": tax_document.document_type,
                "supply_date": tax_document.supply_date,
                "supplier_name": tax_document.supplier_name,
                "supplier_address": tax_document.supplier_address,
                "supplier_trn": tax_document.supplier_trn,
                "recipient_name": tax_document.recipient_name,
                "recipient_address": tax_document.recipient_address,
                "recipient_trn": tax_document.recipient_trn,
                "validation_status": tax_document.validation_status,
                "validation_summary": tax_document.validation_summary,
                "master_cross_check": tax_document.master_cross_check,
                "posting_enabled": False} if tax_document else None),
            "posting_rehearsal": (_rehearsal_payload(rehearsal, invoice) if rehearsal else None),
            "lines": [{"sku": line.sku, "quantity": line.quantity,
                "unit_price": line.unit_price, "tax_rate": line.tax_rate,
                "gross_amount": line.gross_amount} for line in lines]})
    return result
