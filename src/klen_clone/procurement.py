from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .operational import OperationalAuditEvent, OperationalBase, utc_now
from .operational_masters import OperationalLocationMaster, OperationalPartyMaster, OperationalProductMaster


MONEY = Decimal("0.01")
QUANTITY = Decimal("0.000001")


class OperationalPurchaseRequisition(OperationalBase):
    __tablename__ = "operational_purchase_requisitions"
    __table_args__ = (
        CheckConstraint("status IN ('draft','submitted','approved','rejected','cancelled')", name="ck_procurement_req_status"),
        CheckConstraint("posting_enabled = false", name="ck_procurement_req_no_posting"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requisition_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    requisition_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    needed_by: Mapped[date] = mapped_column(Date, nullable=False)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decision_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class OperationalPurchaseRequisitionLine(OperationalBase):
    __tablename__ = "operational_purchase_requisition_lines"
    __table_args__ = (
        UniqueConstraint("requisition_id", "line_no", name="uq_procurement_req_line"),
        CheckConstraint("quantity > 0", name="ck_procurement_req_quantity"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requisition_id: Mapped[int] = mapped_column(ForeignKey("operational_purchase_requisitions.id", ondelete="CASCADE"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    sku: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    product_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    uom: Mapped[str] = mapped_column(String(80), nullable=False)
    factor_to_base_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    specification: Mapped[str | None] = mapped_column(Text)


class OperationalRequestForQuotation(OperationalBase):
    __tablename__ = "operational_requests_for_quotation"
    __table_args__ = (CheckConstraint("status IN ('open','awarded','cancelled')", name="ck_procurement_rfq_status"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rfq_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    rfq_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    requisition_id: Mapped[int] = mapped_column(ForeignKey("operational_purchase_requisitions.id"), nullable=False, index=True)
    response_due_on: Mapped[date] = mapped_column(Date, nullable=False)
    supplier_codes: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class OperationalSupplierQuotation(OperationalBase):
    __tablename__ = "operational_supplier_quotations"
    __table_args__ = (
        UniqueConstraint("rfq_id", "supplier_code", name="uq_procurement_quote_supplier"),
        CheckConstraint("status IN ('received','awarded','not_awarded')", name="ck_procurement_quote_status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quotation_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    rfq_id: Mapped[int] = mapped_column(ForeignKey("operational_requests_for_quotation.id", ondelete="CASCADE"), nullable=False, index=True)
    supplier_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    supplier_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    supplier_reference: Mapped[str | None] = mapped_column(String(160))
    quoted_on: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="AED")
    delivery_days: Mapped[int | None] = mapped_column(Integer)
    payment_terms: Mapped[str | None] = mapped_column(String(500))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="received", index=True)
    captured_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class OperationalSupplierQuotationLine(OperationalBase):
    __tablename__ = "operational_supplier_quotation_lines"
    __table_args__ = (
        UniqueConstraint("quotation_id", "requisition_line_id", name="uq_procurement_quote_line"),
        CheckConstraint("unit_price >= 0 AND tax_rate >= 0 AND tax_rate <= 100", name="ck_procurement_quote_values"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quotation_id: Mapped[int] = mapped_column(ForeignKey("operational_supplier_quotations.id", ondelete="CASCADE"), nullable=False, index=True)
    requisition_line_id: Mapped[int] = mapped_column(ForeignKey("operational_purchase_requisition_lines.id"), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)


class OperationalPurchaseOrder(OperationalBase):
    __tablename__ = "operational_purchase_orders"
    __table_args__ = (
        CheckConstraint("status IN ('draft','submitted','approved','rejected','cancelled')", name="ck_procurement_po_status"),
        CheckConstraint("posting_enabled = false", name="ck_procurement_po_no_posting"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_order_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    purchase_order_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    quotation_id: Mapped[int] = mapped_column(ForeignKey("operational_supplier_quotations.id"), nullable=False, unique=True)
    supplier_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False)
    expected_on: Mapped[date | None] = mapped_column(Date)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decision_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class OperationalPurchaseOrderLine(OperationalBase):
    __tablename__ = "operational_purchase_order_lines"
    __table_args__ = (UniqueConstraint("purchase_order_id", "line_no", name="uq_procurement_po_line"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("operational_purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    sku: Mapped[str] = mapped_column(String(160), nullable=False)
    product_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    uom: Mapped[str] = mapped_column(String(80), nullable=False)
    factor_to_base_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)


def _key() -> str:
    return str(uuid.uuid4())


def _number(prefix: str) -> str:
    return f"{prefix}-{date.today():%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"


def _audit(session: Session, event_type: str, actor: str, resource_key: str, detail: str) -> None:
    session.add(OperationalAuditEvent(event_key=_key(), event_type=event_type, actor=actor,
                                      resource_key=resource_key, detail=detail))


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def _location_allowed(location_code: str, allowed_locations: tuple[str, ...]) -> bool:
    allowed = {code.upper() for code in allowed_locations}
    return not allowed or "*" in allowed or location_code.upper() in allowed


def _product(session: Session, sku: str) -> OperationalProductMaster:
    row = session.scalar(select(OperationalProductMaster).where(
        OperationalProductMaster.sku == sku.strip(), OperationalProductMaster.status == "active"))
    if row is None:
        raise ValueError(f"Active product {sku} was not found")
    return row


def _supplier(session: Session, code: str) -> OperationalPartyMaster:
    row = session.scalar(select(OperationalPartyMaster).where(
        OperationalPartyMaster.party_code == code.strip(), OperationalPartyMaster.status == "active"))
    if row is None or row.party_kind not in {"supplier", "both"}:
        raise ValueError(f"Active supplier {code} was not found")
    return row


def create_requisition(session: Session, *, needed_by: date, location_code: str, purpose: str,
                       lines: list[dict], actor: str) -> OperationalPurchaseRequisition:
    if needed_by < date.today():
        raise ValueError("Required-by date cannot be in the past")
    if session.scalar(select(OperationalLocationMaster.id).where(
            OperationalLocationMaster.location_code == location_code,
            OperationalLocationMaster.status == "active")) is None:
        raise ValueError("Active receiving location was not found")
    skus = [item["sku"].strip() for item in lines]
    if len(skus) != len(set(skus)):
        raise ValueError("A requisition cannot contain the same SKU more than once")
    row = OperationalPurchaseRequisition(requisition_key=_key(), requisition_no=_number("PR"),
        needed_by=needed_by, location_code=location_code, purpose=purpose.strip(), status="draft",
        posting_enabled=False, created_by=actor)
    session.add(row); session.flush()
    for index, item in enumerate(lines, 1):
        product = _product(session, item["sku"])
        quantity = Decimal(item["quantity"]).quantize(QUANTITY)
        if quantity <= 0:
            raise ValueError("Requisition quantity must be greater than zero")
        entered_uom = (item.get("uom") or product.base_uom).strip()
        if entered_uom.casefold() != product.base_uom.casefold():
            raise ValueError(f"SKU {product.sku} must use its governed base UOM {product.base_uom}")
        factor = Decimal(product.factor_to_base)
        session.add(OperationalPurchaseRequisitionLine(requisition_id=row.id, line_no=index,
            sku=product.sku, product_name_snapshot=product.name, quantity=quantity,
            uom=product.base_uom, factor_to_base_snapshot=factor,
            quantity_base=(quantity * factor).quantize(QUANTITY), specification=item.get("specification")))
    _audit(session, "procurement.requisition.created", actor, row.requisition_key, row.purpose)
    session.commit(); return row


def transition_requisition(session: Session, *, requisition_key: str, action: str,
                           expected_revision: int, note: str, actor: str,
                           allowed_locations: tuple[str, ...] = ("*",)) -> OperationalPurchaseRequisition:
    row = session.scalar(select(OperationalPurchaseRequisition).where(
        OperationalPurchaseRequisition.requisition_key == requisition_key).with_for_update())
    if row is None: raise ValueError("Purchase requisition was not found")
    if not _location_allowed(row.location_code, allowed_locations):
        raise ValueError("Purchase requisition was not found in the user's location scope")
    if row.revision != expected_revision: raise ValueError(f"Requisition revision conflict; current revision is {row.revision}")
    transitions = {("draft", "submit"): "submitted", ("rejected", "submit"): "submitted",
                   ("submitted", "approve"): "approved", ("submitted", "reject"): "rejected",
                   ("draft", "cancel"): "cancelled", ("rejected", "cancel"): "cancelled"}
    target = transitions.get((row.status, action))
    if target is None: raise ValueError(f"Cannot {action} a {row.status} requisition")
    if action in {"approve", "reject"} and row.created_by == actor:
        raise ValueError("The requisition maker cannot approve or reject the same requisition")
    row.status = target; row.revision += 1
    if action in {"approve", "reject"}:
        row.decided_by = actor; row.decision_note = note.strip()
    _audit(session, f"procurement.requisition.{action}", actor, row.requisition_key, note.strip())
    session.commit(); return row


def create_rfq(session: Session, *, requisition_key: str, response_due_on: date,
               supplier_codes: list[str], actor: str,
               allowed_locations: tuple[str, ...] = ("*",)) -> OperationalRequestForQuotation:
    req = session.scalar(select(OperationalPurchaseRequisition).where(
        OperationalPurchaseRequisition.requisition_key == requisition_key))
    if req is None or req.status != "approved": raise ValueError("An approved requisition is required")
    if not _location_allowed(req.location_code, allowed_locations):
        raise ValueError("Approved requisition was not found in the user's location scope")
    if response_due_on < date.today(): raise ValueError("RFQ response date cannot be in the past")
    suppliers = list(dict.fromkeys(code.strip() for code in supplier_codes if code.strip()))
    if len(suppliers) < 2: raise ValueError("An RFQ requires at least two suppliers")
    for code in suppliers: _supplier(session, code)
    if session.scalar(select(OperationalRequestForQuotation.id).where(
            OperationalRequestForQuotation.requisition_id == req.id,
            OperationalRequestForQuotation.status != "cancelled")):
        raise ValueError("This requisition already has an active RFQ")
    row = OperationalRequestForQuotation(rfq_key=_key(), rfq_no=_number("RFQ"), requisition_id=req.id,
        response_due_on=response_due_on, supplier_codes=json.dumps(suppliers), status="open", created_by=actor)
    session.add(row); _audit(session, "procurement.rfq.created", actor, row.rfq_key, ",".join(suppliers))
    session.commit(); return row


def capture_quote(session: Session, *, rfq_key: str, supplier_code: str, supplier_reference: str | None,
                  quoted_on: date, valid_until: date | None, currency_code: str, delivery_days: int | None,
                  payment_terms: str | None, lines: list[dict], actor: str,
                  allowed_locations: tuple[str, ...] = ("*",)) -> OperationalSupplierQuotation:
    rfq = session.scalar(select(OperationalRequestForQuotation).where(OperationalRequestForQuotation.rfq_key == rfq_key))
    if rfq is None or rfq.status != "open": raise ValueError("An open RFQ is required")
    req = session.get(OperationalPurchaseRequisition, rfq.requisition_id)
    if not _location_allowed(req.location_code, allowed_locations):
        raise ValueError("Open RFQ was not found in the user's location scope")
    supplier_code = supplier_code.strip()
    if supplier_code not in json.loads(rfq.supplier_codes): raise ValueError("Supplier is not invited to this RFQ")
    supplier = _supplier(session, supplier_code)
    if currency_code.upper() != "AED": raise ValueError("Only AED quotations are enabled until exchange-rate controls are configured")
    if quoted_on > date.today():
        raise ValueError("Quotation date cannot be in the future")
    if valid_until is not None and valid_until < quoted_on:
        raise ValueError("Quotation validity date cannot be before the quotation date")
    req_lines = {row.sku: row for row in session.scalars(select(OperationalPurchaseRequisitionLine).where(
        OperationalPurchaseRequisitionLine.requisition_id == rfq.requisition_id))}
    supplied = {item["sku"] for item in lines}
    if len(supplied) != len(lines):
        raise ValueError("Quotation contains a duplicate SKU")
    if supplied != set(req_lines): raise ValueError("Quotation must price every requisition SKU exactly once")
    quote = OperationalSupplierQuotation(quotation_key=_key(), rfq_id=rfq.id,
        supplier_code=supplier.party_code, supplier_name_snapshot=supplier.legal_or_business_name,
        supplier_reference=supplier_reference, quoted_on=quoted_on, valid_until=valid_until,
        currency_code="AED", delivery_days=delivery_days, payment_terms=payment_terms,
        subtotal=0, tax_amount=0, total_amount=0, status="received", captured_by=actor)
    session.add(quote); session.flush()
    subtotal = tax = Decimal("0")
    for item in lines:
        req_line = req_lines[item["sku"]]; unit_price = Decimal(item["unit_price"])
        tax_rate = Decimal(item.get("tax_rate", 5)); net = _money(req_line.quantity * unit_price)
        tax_amount = _money(net * tax_rate / Decimal("100")); gross = net + tax_amount
        session.add(OperationalSupplierQuotationLine(quotation_id=quote.id, requisition_line_id=req_line.id,
            quantity=req_line.quantity, unit_price=unit_price, tax_rate=tax_rate,
            net_amount=net, tax_amount=tax_amount, gross_amount=gross))
        subtotal += net; tax += tax_amount
    quote.subtotal = _money(subtotal); quote.tax_amount = _money(tax); quote.total_amount = quote.subtotal + quote.tax_amount
    _audit(session, "procurement.quotation.captured", actor, quote.quotation_key, supplier.party_code)
    session.commit(); return quote


def award_quote(session: Session, *, rfq_key: str, quotation_key: str, expected_revision: int,
                expected_on: date | None, note: str, actor: str,
                allowed_locations: tuple[str, ...] = ("*",)) -> OperationalPurchaseOrder:
    rfq = session.scalar(select(OperationalRequestForQuotation).where(
        OperationalRequestForQuotation.rfq_key == rfq_key).with_for_update())
    if rfq is None or rfq.status != "open": raise ValueError("An open RFQ is required")
    if rfq.revision != expected_revision: raise ValueError(f"RFQ revision conflict; current revision is {rfq.revision}")
    quote = session.scalar(select(OperationalSupplierQuotation).where(
        OperationalSupplierQuotation.quotation_key == quotation_key,
        OperationalSupplierQuotation.rfq_id == rfq.id))
    if quote is None or quote.status != "received": raise ValueError("A received quotation for this RFQ is required")
    req = session.get(OperationalPurchaseRequisition, rfq.requisition_id)
    if not _location_allowed(req.location_code, allowed_locations):
        raise ValueError("Open RFQ was not found in the user's location scope")
    if expected_on is not None and expected_on < date.today():
        raise ValueError("Expected delivery date cannot be in the past")
    req_lines = {row.id: row for row in session.scalars(select(OperationalPurchaseRequisitionLine).where(
        OperationalPurchaseRequisitionLine.requisition_id == req.id))}
    quote_lines = list(session.scalars(select(OperationalSupplierQuotationLine).where(
        OperationalSupplierQuotationLine.quotation_id == quote.id)))
    po = OperationalPurchaseOrder(purchase_order_key=_key(), purchase_order_no=_number("PO"),
        quotation_id=quote.id, supplier_code=quote.supplier_code, location_code=req.location_code,
        expected_on=expected_on, currency_code=quote.currency_code, subtotal=quote.subtotal,
        tax_amount=quote.tax_amount, total_amount=quote.total_amount, status="draft",
        posting_enabled=False, created_by=actor)
    session.add(po); session.flush()
    for index, qline in enumerate(quote_lines, 1):
        line = req_lines[qline.requisition_line_id]
        session.add(OperationalPurchaseOrderLine(purchase_order_id=po.id, line_no=index,
            sku=line.sku, product_name_snapshot=line.product_name_snapshot, quantity=qline.quantity,
            uom=line.uom, factor_to_base_snapshot=line.factor_to_base_snapshot,
            quantity_base=line.quantity_base, unit_price=qline.unit_price, tax_rate=qline.tax_rate,
            net_amount=qline.net_amount, tax_amount=qline.tax_amount, gross_amount=qline.gross_amount))
    for candidate in session.scalars(select(OperationalSupplierQuotation).where(
            OperationalSupplierQuotation.rfq_id == rfq.id)):
        candidate.status = "awarded" if candidate.id == quote.id else "not_awarded"
    rfq.status = "awarded"; rfq.revision += 1
    _audit(session, "procurement.rfq.awarded", actor, rfq.rfq_key, note.strip())
    _audit(session, "procurement.purchase_order.created", actor, po.purchase_order_key, quote.supplier_code)
    session.commit(); return po


def transition_purchase_order(session: Session, *, purchase_order_key: str, action: str,
                              expected_revision: int, note: str, actor: str,
                              allowed_locations: tuple[str, ...] = ("*",)) -> OperationalPurchaseOrder:
    row = session.scalar(select(OperationalPurchaseOrder).where(
        OperationalPurchaseOrder.purchase_order_key == purchase_order_key).with_for_update())
    if row is None: raise ValueError("Purchase order was not found")
    if not _location_allowed(row.location_code, allowed_locations):
        raise ValueError("Purchase order was not found in the user's location scope")
    if row.revision != expected_revision: raise ValueError(f"Purchase-order revision conflict; current revision is {row.revision}")
    transitions = {("draft", "submit"): "submitted", ("rejected", "submit"): "submitted",
                   ("submitted", "approve"): "approved", ("submitted", "reject"): "rejected",
                   ("draft", "cancel"): "cancelled", ("rejected", "cancel"): "cancelled"}
    target = transitions.get((row.status, action))
    if target is None: raise ValueError(f"Cannot {action} a {row.status} purchase order")
    if action in {"approve", "reject"} and row.created_by == actor:
        raise ValueError("The purchase-order maker cannot approve or reject the same order")
    row.status = target; row.revision += 1
    if action in {"approve", "reject"}: row.decided_by = actor; row.decision_note = note.strip()
    _audit(session, f"procurement.purchase_order.{action}", actor, row.purchase_order_key, note.strip())
    session.commit(); return row


def procurement_payload(session: Session, *, allowed_locations: tuple[str, ...] = ("*",)) -> dict:
    requisition_query = select(OperationalPurchaseRequisition)
    allowed = {code.upper() for code in allowed_locations}
    if allowed and "*" not in allowed:
        requisition_query = requisition_query.where(OperationalPurchaseRequisition.location_code.in_(allowed))
    requisitions = list(session.scalars(requisition_query.order_by(OperationalPurchaseRequisition.created_at.desc())))
    req_lines = list(session.scalars(select(OperationalPurchaseRequisitionLine).order_by(OperationalPurchaseRequisitionLine.requisition_id, OperationalPurchaseRequisitionLine.line_no)))
    requisition_ids = {row.id for row in requisitions}
    rfqs = list(session.scalars(select(OperationalRequestForQuotation).where(
        OperationalRequestForQuotation.requisition_id.in_(requisition_ids)
    ).order_by(OperationalRequestForQuotation.created_at.desc()))) if requisition_ids else []
    rfq_ids = {row.id for row in rfqs}
    quotes = list(session.scalars(select(OperationalSupplierQuotation).where(
        OperationalSupplierQuotation.rfq_id.in_(rfq_ids)
    ).order_by(OperationalSupplierQuotation.created_at.desc()))) if rfq_ids else []
    quotation_ids = {row.id for row in quotes}
    quote_lines = list(session.scalars(select(OperationalSupplierQuotationLine).where(
        OperationalSupplierQuotationLine.quotation_id.in_(quotation_ids)
    ))) if quotation_ids else []
    order_query = select(OperationalPurchaseOrder)
    if allowed and "*" not in allowed:
        order_query = order_query.where(OperationalPurchaseOrder.location_code.in_(allowed))
    orders = list(session.scalars(order_query.order_by(OperationalPurchaseOrder.created_at.desc())))
    po_lines = list(session.scalars(select(OperationalPurchaseOrderLine).order_by(OperationalPurchaseOrderLine.purchase_order_id, OperationalPurchaseOrderLine.line_no)))
    req_by_id = {row.id: row for row in requisitions}; rfq_by_id = {row.id: row for row in rfqs}
    req_line_by_id = {row.id: row for row in req_lines}
    quotes_by_rfq: dict[int, list[OperationalSupplierQuotation]] = {}
    for row in quotes: quotes_by_rfq.setdefault(row.rfq_id, []).append(row)
    lines_by_quote: dict[int, list[OperationalSupplierQuotationLine]] = {}
    for row in quote_lines: lines_by_quote.setdefault(row.quotation_id, []).append(row)
    comparison = []
    for rfq in rfqs:
        candidates: dict[str, list[dict]] = {}
        for quote in quotes_by_rfq.get(rfq.id, []):
            for line in lines_by_quote.get(quote.id, []):
                req_line = req_line_by_id[line.requisition_line_id]
                candidates.setdefault(req_line.sku, []).append({"quotation_key": quote.quotation_key,
                    "supplier_code": quote.supplier_code, "supplier_name": quote.supplier_name_snapshot,
                    "unit_price": line.unit_price, "gross_amount": line.gross_amount,
                    "delivery_days": quote.delivery_days})
        for sku, values in candidates.items():
            lowest = min(value["unit_price"] for value in values)
            comparison.append({"rfq_key": rfq.rfq_key, "sku": sku,
                "product_name": next(item.product_name_snapshot for item in req_lines if item.sku == sku and item.requisition_id == rfq.requisition_id),
                "quotes": [{**value, "lowest": value["unit_price"] == lowest} for value in values]})
    return {
        "controls": {"requisitions": len(requisitions), "submitted_requisitions": sum(r.status == "submitted" for r in requisitions),
                     "open_rfqs": sum(r.status == "open" for r in rfqs), "quotes": len(quotes),
                     "submitted_orders": sum(r.status == "submitted" for r in orders),
                     "approved_orders": sum(r.status == "approved" for r in orders), "posting_enabled": False},
        "requisitions": [{"requisition_key": row.requisition_key, "requisition_no": row.requisition_no,
            "needed_by": row.needed_by, "location_code": row.location_code, "purpose": row.purpose,
            "status": row.status, "created_by": row.created_by, "revision": row.revision,
            "lines": [{"sku": line.sku, "product_name": line.product_name_snapshot,
                "quantity": line.quantity, "uom": line.uom, "quantity_base": line.quantity_base,
                "specification": line.specification} for line in req_lines if line.requisition_id == row.id]} for row in requisitions],
        "rfqs": [{"rfq_key": row.rfq_key, "rfq_no": row.rfq_no,
            "requisition_key": req_by_id[row.requisition_id].requisition_key,
            "requisition_no": req_by_id[row.requisition_id].requisition_no,
            "response_due_on": row.response_due_on, "supplier_codes": json.loads(row.supplier_codes),
            "status": row.status, "created_by": row.created_by, "revision": row.revision,
            "quotes": [{"quotation_key": quote.quotation_key, "supplier_code": quote.supplier_code,
                "supplier_name": quote.supplier_name_snapshot, "supplier_reference": quote.supplier_reference,
                "quoted_on": quote.quoted_on, "valid_until": quote.valid_until,
                "delivery_days": quote.delivery_days, "payment_terms": quote.payment_terms,
                "subtotal": quote.subtotal, "tax_amount": quote.tax_amount,
                "total_amount": quote.total_amount, "status": quote.status} for quote in quotes_by_rfq.get(row.id, [])]} for row in rfqs],
        "comparison": comparison,
        "purchase_orders": [{"purchase_order_key": row.purchase_order_key,
            "purchase_order_no": row.purchase_order_no, "supplier_code": row.supplier_code,
            "location_code": row.location_code, "expected_on": row.expected_on,
            "currency_code": row.currency_code, "subtotal": row.subtotal,
            "tax_amount": row.tax_amount, "total_amount": row.total_amount, "status": row.status,
            "created_by": row.created_by, "decided_by": row.decided_by, "revision": row.revision,
            "lines": [{"sku": line.sku, "product_name": line.product_name_snapshot,
                "quantity": line.quantity, "uom": line.uom, "quantity_base": line.quantity_base,
                "unit_price": line.unit_price, "tax_rate": line.tax_rate,
                "gross_amount": line.gross_amount} for line in po_lines if line.purchase_order_id == row.id]} for row in orders],
        "currency_policy": {"enabled": ["AED"], "foreign_currency": "blocked_pending_exchange_rate_controls"},
        "source_protection": {"bizmodo_mutated": False, "historical_purchases_changed": False},
    }
