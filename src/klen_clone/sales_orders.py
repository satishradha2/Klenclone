from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .operational import MONEY, OperationalAuditEvent, OperationalBase, utc_now
from .country_catalog import quotation_money_quantum


class OperationalSalesQuotation(OperationalBase):
    __tablename__ = "operational_sales_quotations"
    __table_args__ = (
        CheckConstraint("status IN ('draft','submitted','approved','rejected','cancelled','accepted','converted')", name="ck_sales_quotation_status"),
        CheckConstraint("posting_enabled = false", name="ck_sales_quotation_no_posting"),
        CheckConstraint("subtotal >= 0 AND discount_amount >= 0 AND tax_amount >= 0 AND total_amount >= 0", name="ck_sales_quotation_totals"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quotation_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    quotation_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    customer_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    customer_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    quotation_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    valid_until: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    currency_code: Mapped[str] = mapped_column(String(3), default="AED", nullable=False)
    customer_country_code: Mapped[str | None] = mapped_column(String(2))
    fx_rate_key: Mapped[str | None] = mapped_column(String(36))
    aed_per_unit_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    aed_total_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    trade_decision_key: Mapped[str | None] = mapped_column(String(36))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(19, 3), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(19, 3), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(19, 3), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(19, 3), nullable=False)
    payment_terms: Mapped[str | None] = mapped_column(String(500))
    delivery_terms: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    customer_price_group: Mapped[str | None] = mapped_column(String(80))
    price_list_key: Mapped[str | None] = mapped_column(String(36))
    promotion_key: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False, index=True)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    approval_note: Mapped[str | None] = mapped_column(Text)
    acceptance_reference: Mapped[str | None] = mapped_column(String(300))
    accepted_by: Mapped[str | None] = mapped_column(String(200))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    state_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    state_changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    lines: Mapped[list["OperationalSalesQuotationLine"]] = relationship(
        back_populates="quotation", cascade="all, delete-orphan", order_by="OperationalSalesQuotationLine.line_no")
    order: Mapped["OperationalSalesOrder | None"] = relationship(back_populates="quotation", uselist=False)


class OperationalSalesQuotationLine(OperationalBase):
    __tablename__ = "operational_sales_quotation_lines"
    __table_args__ = (
        UniqueConstraint("quotation_id", "line_no", name="uq_sales_quotation_line"),
        CheckConstraint("quantity > 0 AND factor_to_base_snapshot > 0 AND quantity_base > 0", name="ck_sales_quotation_quantity"),
        CheckConstraint("unit_price >= 0 AND tax_rate >= 0 AND tax_rate <= 100", name="ck_sales_quotation_price_tax"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quotation_id: Mapped[int] = mapped_column(ForeignKey("operational_sales_quotations.id", ondelete="CASCADE"), nullable=False, index=True)
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
    net_amount: Mapped[Decimal] = mapped_column(Numeric(19, 3), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(19, 3), nullable=False, default=Decimal("0"))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(19, 3), nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(19, 3), nullable=False)
    quotation: Mapped[OperationalSalesQuotation] = relationship(back_populates="lines")


class OperationalSalesOrder(OperationalBase):
    __tablename__ = "operational_sales_orders"
    __table_args__ = (
        UniqueConstraint("quotation_id", name="uq_sales_order_quotation"),
        CheckConstraint("status IN ('confirmed','cancelled')", name="ck_sales_order_status"),
        CheckConstraint("posting_enabled = false", name="ck_sales_order_no_posting"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    order_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    quotation_id: Mapped[int] = mapped_column(ForeignKey("operational_sales_quotations.id"), nullable=False, index=True)
    customer_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    customer_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    requested_delivery_date: Mapped[date | None] = mapped_column(Date)
    currency_code: Mapped[str] = mapped_column(String(3), default="AED", nullable=False)
    customer_country_code: Mapped[str | None] = mapped_column(String(2))
    fx_rate_key: Mapped[str | None] = mapped_column(String(36))
    aed_per_unit_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    aed_total_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    order_release_key: Mapped[str | None] = mapped_column(String(36))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(19, 3), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(19, 3), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(19, 3), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(19, 3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="confirmed", nullable=False, index=True)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    quotation: Mapped[OperationalSalesQuotation] = relationship(back_populates="order")
    lines: Mapped[list["OperationalSalesOrderLine"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OperationalSalesOrderLine.line_no")


class OperationalSalesOrderLine(OperationalBase):
    __tablename__ = "operational_sales_order_lines"
    __table_args__ = (UniqueConstraint("order_id", "line_no", name="uq_sales_order_line"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("operational_sales_orders.id", ondelete="CASCADE"), nullable=False, index=True)
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
    net_amount: Mapped[Decimal] = mapped_column(Numeric(19, 3), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(19, 3), nullable=False, default=Decimal("0"))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(19, 3), nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(19, 3), nullable=False)
    order: Mapped[OperationalSalesOrder] = relationship(back_populates="lines")


class OperationalSalesQuotationWorkflowEvent(OperationalBase):
    __tablename__ = "operational_sales_quotation_workflow_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    quotation_id: Mapped[int] = mapped_column(ForeignKey("operational_sales_quotations.id"), nullable=False, index=True)
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


def _replace_lines(document: OperationalSalesQuotation, lines: list[dict]) -> None:
    if not lines:
        raise ValueError("At least one quotation line is required")
    skus = [str(row["sku"]).strip().casefold() for row in lines]
    if len(skus) != len(set(skus)):
        raise ValueError("Each product may appear only once in a quotation")
    document.lines.clear()
    allowed = {"sku", "product_name_snapshot", "quantity", "uom", "canonical_uom",
               "factor_to_base_snapshot", "quantity_base", "unit_price", "tax_rate",
               "net_amount", "tax_amount", "gross_amount"}
    for number, row in enumerate(lines, 1):
        document.lines.append(OperationalSalesQuotationLine(
            line_no=number, **{key: value for key, value in row.items() if key in allowed}))


def _set_totals(document: OperationalSalesQuotation) -> None:
    # Allocate header discount to taxable lines in minor units. The final
    # pennies go to the largest fractional remainders, then stable line order.
    # This keeps every copied order/invoice line reconcilable to its header.
    from .operational import calculate_line
    quantum = quotation_money_quantum(document.currency_code)
    for line in document.lines:
        expected_net, expected_tax, expected_gross = calculate_line(
            Decimal(line.quantity), Decimal(line.unit_price), Decimal(line.tax_rate), quantum)
        if (Decimal(line.net_amount) != expected_net or Decimal(line.tax_amount) != expected_tax
                or Decimal(line.gross_amount) != expected_gross):
            raise ValueError(f"Quotation line {line.line_no} amounts do not match quantity, price and tax rate")
    document.subtotal = sum((Decimal(line.net_amount) for line in document.lines), Decimal("0.00"))
    discount = Decimal(document.discount_amount)
    if not discount.is_finite() or discount < 0 or discount != discount.quantize(quantum):
        raise ValueError("Quotation discount must match the currency's minor-unit precision")
    if discount > document.subtotal:
        raise ValueError("Quotation discount cannot exceed the subtotal")
    if document.subtotal:
        exact = [discount * Decimal(line.net_amount) / document.subtotal for line in document.lines]
        allocations = [value.quantize(quantum, rounding=ROUND_DOWN) for value in exact]
        remaining = int((discount - sum(allocations)) / quantum)
        ranked = sorted(range(len(exact)), key=lambda i: (-(exact[i] - allocations[i]), document.lines[i].line_no))
        for index in ranked[:remaining]:
            allocations[index] += quantum
    else:
        allocations = [Decimal("0").quantize(quantum) for _ in document.lines]
    for line, allocation in zip(document.lines, allocations):
        line.discount_amount = allocation
        taxable = Decimal(line.net_amount) - allocation
        line.tax_amount = (taxable * Decimal(line.tax_rate) / Decimal("100")).quantize(
            quantum, rounding=ROUND_HALF_UP)
        line.gross_amount = taxable + line.tax_amount
    document.tax_amount = sum((Decimal(line.tax_amount) for line in document.lines), Decimal("0.00"))
    document.total_amount = sum((Decimal(line.gross_amount) for line in document.lines), Decimal("0.00"))


def assert_allocated_sales_totals(document) -> None:
    """Prevent legacy or malformed discounts from leaking into downstream documents."""
    if (any(Decimal(line.gross_amount) != Decimal(line.net_amount) - Decimal(line.discount_amount or 0)
            + Decimal(line.tax_amount) for line in document.lines)
            or sum((Decimal(line.discount_amount or 0) for line in document.lines), Decimal("0.00"))
            != Decimal(document.discount_amount)
            or sum((Decimal(line.tax_amount) for line in document.lines), Decimal("0.00"))
            != Decimal(document.tax_amount)
            or sum((Decimal(line.gross_amount) for line in document.lines), Decimal("0.00"))
            != Decimal(document.total_amount)):
        raise ValueError("Sales document line discount, tax and gross amounts do not reconcile; review the legacy quotation before conversion or invoicing")


def _quotation_controls(session: Session, *, customer_code: str, customer_country_code: str | None,
                        currency_code: str, quotation_date: date, lines: list[dict],
                        trade_decision_key: str | None, price_list_key: str | None,
                        discount_amount: Decimal) -> dict:
    from .country_catalog import country_code as normalize_country, currency_code as normalize_currency
    from .fx_controls import approved_fx_rate
    from .operational_masters import OperationalPartyMaster
    from .quote_trade_controls import approved_trade_decision
    country = normalize_country(customer_country_code) if customer_country_code else "AE"
    currency = normalize_currency(currency_code)
    master = session.scalar(select(OperationalPartyMaster).where(
        OperationalPartyMaster.party_code == customer_code,
        OperationalPartyMaster.party_kind.in_(("customer", "both"))))
    if master and master.country_code and normalize_country(master.country_code) != country:
        raise ValueError("Quotation destination must match the controlled customer master")
    if master and master.preferred_currency_code and normalize_currency(master.preferred_currency_code) != currency:
        raise ValueError("Quotation currency must match the controlled customer's preferred currency")
    if country == "AE":
        if currency != "AED" or trade_decision_key:
            raise ValueError("UAE customer quotations remain AED-only without a trade decision")
        return {"customer_country_code": "AE", "currency_code": "AED", "fx_rate_key": None,
                "aed_per_unit_snapshot": Decimal("1"), "trade_decision_key": None}
    quotation_money_quantum(currency)
    if not price_list_key:
        raise ValueError("Cross-border quotations require an approved currency-specific price list")
    if not trade_decision_key:
        raise ValueError("Cross-border quotations require an independently approved provisional trade decision")
    approved_trade_decision(session, decision_key=trade_decision_key, customer_code=customer_code,
        destination_country_code=country, currency_code=currency, quotation_date=quotation_date, lines=lines)
    fx = approved_fx_rate(session, currency, quotation_date) if currency != "AED" else None
    if currency != "AED" and not fx:
        raise ValueError("An approved commercial FX reference for this currency and exact quotation date is required")
    return {"customer_country_code": country, "currency_code": currency,
            "fx_rate_key": fx.rate_key if fx else None,
            "aed_per_unit_snapshot": fx.aed_per_unit if fx else Decimal("1"),
            "trade_decision_key": trade_decision_key}


def create_sales_quotation(session: Session, *, customer_code: str, customer_name_snapshot: str,
                           location_code: str, quotation_date: date, valid_until: date,
                           discount_amount: Decimal, payment_terms: str | None,
                           delivery_terms: str | None, notes: str | None, actor: str,
                           lines: list[dict], promotion_code: str | None = None,
                           pricing: dict | None = None, customer_country_code: str | None = None,
                           currency_code: str = "AED", trade_decision_key: str | None = None) -> OperationalSalesQuotation:
    if valid_until < quotation_date:
        raise ValueError("Quotation valid-until date cannot be earlier than its quotation date")
    from .commercial_pricing import enforce_quotation_pricing
    enforced_pricing = enforce_quotation_pricing(
        session, customer_code=customer_code, quotation_date=quotation_date, lines=lines,
        discount_amount=discount_amount, promotion_code=promotion_code, currency_code=currency_code)
    if pricing is not None and any(pricing.get(key) != enforced_pricing.get(key)
                                   for key in ("customer_group", "price_list_key", "promotion_key")):
        raise ValueError("Quotation pricing decision is stale or does not match current approved controls")
    pricing = enforced_pricing
    controls = _quotation_controls(session, customer_code=customer_code, customer_country_code=customer_country_code,
        currency_code=currency_code, quotation_date=quotation_date, lines=lines,
        trade_decision_key=trade_decision_key, price_list_key=pricing.get("price_list_key"),
        discount_amount=discount_amount)
    key = str(uuid.uuid4())
    document = OperationalSalesQuotation(
        quotation_key=key, quotation_no=f"SQ-{quotation_date:%Y%m%d}-{key[:8].upper()}",
        customer_code=customer_code, customer_name_snapshot=customer_name_snapshot,
        location_code=location_code, quotation_date=quotation_date, valid_until=valid_until, **controls,
        subtotal=0, discount_amount=discount_amount, tax_amount=0, total_amount=0,
        payment_terms=payment_terms, delivery_terms=delivery_terms, notes=notes,
        customer_price_group=(pricing or {}).get("customer_group"), price_list_key=(pricing or {}).get("price_list_key"),
        promotion_key=(pricing or {}).get("promotion_key"),
        status="draft", posting_enabled=False, created_by=actor, state_changed_by=actor)
    _replace_lines(document, lines); _set_totals(document)
    document.aed_total_snapshot = (document.total_amount * document.aed_per_unit_snapshot).quantize(MONEY, rounding=ROUND_HALF_UP)
    session.add(document); session.flush()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="sales_quotation.created",
        actor=actor, resource_key=key, detail=f"{document.quotation_no}; {len(lines)} lines; posting disabled"))
    session.commit(); return document


def replace_sales_quotation(session: Session, document: OperationalSalesQuotation, *, expected_revision: int,
                            customer_code: str, customer_name_snapshot: str, location_code: str,
                            quotation_date: date, valid_until: date, discount_amount: Decimal,
                            payment_terms: str | None, delivery_terms: str | None,
                            notes: str | None, actor: str, lines: list[dict],
                            promotion_code: str | None = None,
                            pricing: dict | None = None, customer_country_code: str | None = None,
                            currency_code: str = "AED", trade_decision_key: str | None = None) -> OperationalSalesQuotation:
    if document.status not in {"draft", "rejected"}:
        raise ValueError("Only draft or rejected quotations can be revised")
    if document.revision != expected_revision:
        raise ValueError(f"Sales quotation revision conflict; current revision is {document.revision}")
    if valid_until < quotation_date:
        raise ValueError("Quotation valid-until date cannot be earlier than its quotation date")
    from .commercial_pricing import enforce_quotation_pricing
    enforced_pricing = enforce_quotation_pricing(
        session, customer_code=customer_code, quotation_date=quotation_date, lines=lines,
        discount_amount=discount_amount, promotion_code=promotion_code, currency_code=currency_code)
    if pricing is not None and any(pricing.get(key) != enforced_pricing.get(key)
                                   for key in ("customer_group", "price_list_key", "promotion_key")):
        raise ValueError("Quotation pricing decision is stale or does not match current approved controls")
    pricing = enforced_pricing
    controls = _quotation_controls(session, customer_code=customer_code, customer_country_code=customer_country_code,
        currency_code=currency_code, quotation_date=quotation_date, lines=lines,
        trade_decision_key=trade_decision_key, price_list_key=pricing.get("price_list_key"),
        discount_amount=discount_amount)
    for field, value in controls.items():
        setattr(document, field, value)
    document.customer_code=customer_code; document.customer_name_snapshot=customer_name_snapshot
    document.location_code=location_code; document.quotation_date=quotation_date; document.valid_until=valid_until
    document.discount_amount=discount_amount; document.payment_terms=payment_terms
    document.delivery_terms=delivery_terms; document.notes=notes; document.status="draft"
    document.customer_price_group=(pricing or {}).get("customer_group"); document.price_list_key=(pricing or {}).get("price_list_key"); document.promotion_key=(pricing or {}).get("promotion_key")
    document.approved_by=None; document.approval_note=None; document.revision += 1
    document.state_changed_at=utc_now(); document.state_changed_by=actor
    document.lines.clear(); session.flush(); _replace_lines(document, lines); _set_totals(document)
    document.aed_total_snapshot = (document.total_amount * document.aed_per_unit_snapshot).quantize(MONEY, rounding=ROUND_HALF_UP)
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="sales_quotation.revised",
        actor=actor, resource_key=document.quotation_key, detail=f"{document.quotation_no}; revision {document.revision}"))
    session.commit(); return document


def transition_sales_quotation(session: Session, document: OperationalSalesQuotation, *, expected_revision: int,
                               action: str, actor: str, note: str | None = None) -> OperationalSalesQuotation:
    transitions = {("draft", "submit"): "submitted", ("rejected", "submit"): "submitted",
                   ("draft", "cancel"): "cancelled", ("rejected", "cancel"): "cancelled",
                   ("submitted", "cancel"): "cancelled", ("submitted", "approve"): "approved",
                   ("submitted", "reject"): "rejected"}
    if document.revision != expected_revision:
        raise ValueError(f"Sales quotation revision conflict; current revision is {document.revision}")
    target = transitions.get((document.status, action))
    if not target:
        raise ValueError(f"Action {action} is not allowed from {document.status}")
    if action in {"approve", "reject"} and document.created_by == actor:
        raise PermissionError("Maker-checker control prevents the creator from deciding this sales quotation")
    if action in {"approve", "reject"} and not (note or "").strip():
        raise ValueError("An approval decision reason is required")
    previous=document.status; document.status=target; document.revision += 1
    document.state_changed_at=utc_now(); document.state_changed_by=actor
    if action == "approve": document.approved_by=actor; document.approval_note=note.strip()
    if action == "reject": document.approved_by=None; document.approval_note=note.strip()
    session.add(OperationalSalesQuotationWorkflowEvent(event_key=str(uuid.uuid4()), quotation_id=document.id,
        from_status=previous, to_status=target, actor=actor, note=(note or "").strip() or None))
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"sales_quotation.{action}",
        actor=actor, resource_key=document.quotation_key, detail=f"{previous}->{target}; revision {document.revision}"))
    session.commit(); return document


def accept_sales_quotation(session: Session, document: OperationalSalesQuotation, *, expected_revision: int,
                           actor: str, acceptance_reference: str, accepted_on: date | None = None) -> OperationalSalesQuotation:
    if document.revision != expected_revision:
        raise ValueError(f"Sales quotation revision conflict; current revision is {document.revision}")
    if document.status != "approved":
        raise ValueError("Only an approved quotation can record customer acceptance")
    if (accepted_on or date.today()) > document.valid_until:
        raise ValueError("This quotation has expired and cannot be accepted")
    if not acceptance_reference.strip():
        raise ValueError("Customer acceptance reference is required")
    previous=document.status; document.status="accepted"; document.revision += 1
    document.acceptance_reference=acceptance_reference.strip(); document.accepted_by=actor
    document.accepted_at=utc_now(); document.state_changed_at=utc_now(); document.state_changed_by=actor
    session.add(OperationalSalesQuotationWorkflowEvent(event_key=str(uuid.uuid4()), quotation_id=document.id,
        from_status=previous, to_status="accepted", actor=actor, note=document.acceptance_reference))
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="sales_quotation.accepted",
        actor=actor, resource_key=document.quotation_key, detail=document.acceptance_reference))
    session.commit(); return document


def convert_sales_quotation(session: Session, document: OperationalSalesQuotation, *, expected_revision: int,
                            actor: str, requested_delivery_date: date | None = None,
                            conversion_note: str = "Converted after customer acceptance") -> OperationalSalesOrder:
    existing = session.scalar(select(OperationalSalesOrder).where(OperationalSalesOrder.quotation_id == document.id))
    if existing:
        return existing
    if document.revision != expected_revision:
        raise ValueError(f"Sales quotation revision conflict; current revision is {document.revision}")
    if document.status != "accepted":
        raise ValueError("Only a customer-accepted quotation can be converted to a sales order")
    assert_allocated_sales_totals(document)
    from .credit_management import (OperationalCustomerCreditProfile,
                                    assert_customer_credit_allows_order,
                                    consume_credit_override, customer_credit_block)
    foreign = document.customer_country_code not in (None, "AE")
    release = None
    if foreign:
        from .cross_border_order_controls import approved_order_release
        release = approved_order_release(session, document)
        profile = session.scalar(select(OperationalCustomerCreditProfile).where(
            OperationalCustomerCreditProfile.party_code == document.customer_code).with_for_update())
        if not profile:
            raise ValueError("Cross-border order requires an approved AED customer credit profile")
        block = customer_credit_block(session, document.customer_code,
                                      order_amount=document.aed_total_snapshot, as_of=date.today())
        if block:
            raise ValueError(f"Cross-border AED credit commitment blocked: {block['block_reason']}; order-specific credit overrides are not yet supported")
        credit_override = None
    else:
        session.scalar(select(OperationalCustomerCreditProfile).where(
            OperationalCustomerCreditProfile.party_code == document.customer_code).with_for_update())
        credit_override = assert_customer_credit_allows_order(
            session, party_code=document.customer_code,
            order_amount=document.total_amount, as_of=date.today(),
            quotation_key=document.quotation_key,
        )
    key=str(uuid.uuid4())
    order=OperationalSalesOrder(order_key=key, order_no=f"SO-{date.today():%Y%m%d}-{key[:8].upper()}",
        quotation_id=document.id, customer_code=document.customer_code,
        customer_name_snapshot=document.customer_name_snapshot, location_code=document.location_code,
        requested_delivery_date=requested_delivery_date, currency_code=document.currency_code,
        customer_country_code=document.customer_country_code,
        fx_rate_key=document.fx_rate_key, aed_per_unit_snapshot=document.aed_per_unit_snapshot,
        aed_total_snapshot=document.aed_total_snapshot, order_release_key=release.release_key if release else None,
        subtotal=document.subtotal, discount_amount=document.discount_amount,
        tax_amount=document.tax_amount, total_amount=document.total_amount,
        status="confirmed", posting_enabled=False, created_by=actor)
    for line in document.lines:
        order.lines.append(OperationalSalesOrderLine(line_no=line.line_no, sku=line.sku,
            product_name_snapshot=line.product_name_snapshot, quantity=line.quantity, uom=line.uom,
            canonical_uom=line.canonical_uom, factor_to_base_snapshot=line.factor_to_base_snapshot,
            quantity_base=line.quantity_base, unit_price=line.unit_price, tax_rate=line.tax_rate,
            net_amount=line.net_amount, discount_amount=line.discount_amount,
            tax_amount=line.tax_amount, gross_amount=line.gross_amount))
    document.status="converted"; document.revision += 1; document.state_changed_at=utc_now(); document.state_changed_by=actor
    session.add(order); session.flush()
    if release:
        release.status="consumed"; release.revision += 1; release.consumed_by=actor
        release.consumed_at=utc_now(); release.sales_order_key=order.order_key
    if credit_override:
        consume_credit_override(session, credit_override, actor=actor,
                                sales_order_key=order.order_key)
    session.add(OperationalSalesQuotationWorkflowEvent(event_key=str(uuid.uuid4()), quotation_id=document.id,
        from_status="accepted", to_status="converted", actor=actor,
        note=f"{order.order_no}; {conversion_note.strip()}"))
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="sales_order.created",
        actor=actor, resource_key=order.order_key,
        detail=f"{order.order_no} from {document.quotation_no}; {conversion_note.strip()}; no reservation; posting disabled"))
    session.commit(); return order


def list_sales_quotations(session: Session, *, allowed_locations: tuple[str, ...] = ("*",), limit: int = 100):
    query=select(OperationalSalesQuotation)
    if "*" not in allowed_locations: query=query.where(OperationalSalesQuotation.location_code.in_(allowed_locations))
    return list(session.scalars(query.order_by(OperationalSalesQuotation.created_at.desc()).limit(limit)))


def list_sales_orders(session: Session, *, allowed_locations: tuple[str, ...] = ("*",), limit: int = 100):
    query=select(OperationalSalesOrder)
    if "*" not in allowed_locations: query=query.where(OperationalSalesOrder.location_code.in_(allowed_locations))
    return list(session.scalars(query.order_by(OperationalSalesOrder.created_at.desc()).limit(limit)))


def sales_order_control_counts(session: Session) -> dict:
    return {
        "quotation_count": len(list(session.scalars(select(OperationalSalesQuotation.id)))),
        "sales_order_count": len(list(session.scalars(select(OperationalSalesOrder.id)))),
        "posting_enabled": False,
        "stock_reservation_enabled": False,
    }
