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
    return dict(raw, quantity=quantity, restock_quantity=restock, writeoff_quantity=writeoff,
                factor_to_base_snapshot=factor, quantity_base=quantity * factor, unit_price=price,
                tax_rate=tax_rate, net_amount=net, tax_amount=tax, gross_amount=net + tax,
                unit_cost_snapshot=cost, original_invoice_quantity_snapshot=invoice_quantity,
                original_invoice_unit_price_snapshot=invoice_price,
                disposition_reason=(raw.get("disposition_reason") or "").strip() or None)


def _replace_lines(document: OperationalSalesReturn, lines: list[dict]) -> None:
    document.lines.clear()
    for number, source in enumerate(lines, 1):
        row = _normalise_line(source)
        document.lines.append(OperationalSalesReturnLine(line_no=number, **row))


def _set_totals(document: OperationalSalesReturn) -> None:
    document.subtotal = sum((line.net_amount for line in document.lines), Decimal("0.00"))
    document.tax_amount = sum((line.tax_amount for line in document.lines), Decimal("0.00"))
    document.total_amount = document.subtotal + document.tax_amount


def create_sales_return(session: Session, *, customer_code: str, customer_name_snapshot: str,
                        location_code: str, original_invoice_reference: str, return_date: date,
                        reason_code: str, notes: str | None, actor: str, lines: list[dict],
                        original_invoice_source_record_id: int,
                        original_invoice_total_snapshot: Decimal,
                        original_invoice_evidence_hash: str) -> OperationalSalesReturn:
    if not original_invoice_reference.strip(): raise ValueError("Original sales invoice reference is required")
    if not lines: raise ValueError("At least one sales return line is required")
    key = str(uuid.uuid4())
    document = OperationalSalesReturn(return_key=key, return_no=f"SR-{key[:8].upper()}",
        customer_code=customer_code, customer_name_snapshot=customer_name_snapshot,
        location_code=location_code, original_invoice_reference=original_invoice_reference.strip(),
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
                         original_invoice_evidence_hash: str) -> OperationalSalesReturn:
    if document.status != "draft": raise ValueError("Only draft-state sales returns can be edited")
    if document.revision != expected_revision: raise ValueError(f"Sales return revision conflict; current revision is {document.revision}")
    if not original_invoice_reference.strip() or not lines: raise ValueError("Invoice reference and at least one return line are required")
    document.customer_code=customer_code; document.customer_name_snapshot=customer_name_snapshot; document.location_code=location_code
    document.original_invoice_reference=original_invoice_reference.strip(); document.return_date=return_date; document.reason_code=reason_code; document.notes=notes
    document.original_invoice_source_record_id=original_invoice_source_record_id; document.original_invoice_total_snapshot=original_invoice_total_snapshot; document.original_invoice_evidence_hash=original_invoice_evidence_hash
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
    restock_cost = sum(((line.restock_quantity * line.factor_to_base_snapshot * line.unit_cost_snapshot)
                        .quantize(MONEY, rounding=ROUND_HALF_UP) for line in document.lines), Decimal("0"))
    writeoff_cost = sum(((line.writeoff_quantity * line.factor_to_base_snapshot * line.unit_cost_snapshot)
                         .quantize(MONEY, rounding=ROUND_HALF_UP) for line in document.lines), Decimal("0"))
    debit = sum((line["debit"] for line in journal), Decimal("0"))
    credit = sum((line["credit"] for line in journal), Decimal("0"))
    return {"rehearsal_key": rehearsal.rehearsal_key, "return_key": document.return_key,
        "return_no": document.return_no, "credit_note_no": document.credit_note.credit_note_no,
        "original_invoice_reference": document.original_invoice_reference,
        "original_invoice_evidence_hash": rehearsal.original_invoice_evidence_hash,
        "period_key": rehearsal.period_key, "status": rehearsal.status, "journal": journal,
        "movements": movements, "reversal_plan": json.loads(rehearsal.reversal_json),
        "restock_cost": restock_cost, "writeoff_cost": writeoff_cost,
        "debit": debit, "credit": credit, "posting_fingerprint": rehearsal.posting_fingerprint,
        "idempotency_key": f"sales-return:{document.return_key}:{document.revision}:{rehearsal.posting_fingerprint[:20]}",
        "idempotent_replay": idempotent_replay, "posting_enabled": False}


def rehearse_sales_return_posting(session: Session, document: OperationalSalesReturn, *, actor: str) -> dict:
    if document.status != "approved" or not document.credit_note:
        raise ValueError("Only an approved sales return with a credit note can be rehearsed")
    if (document.original_invoice_source_record_id <= 0
            or len(document.original_invoice_evidence_hash) != 64
            or document.original_invoice_total_snapshot <= 0):
        raise ValueError("Verified original customer-invoice evidence is required before posting rehearsal")
    period = session.scalar(select(OperationalFiscalPeriod).where(
        OperationalFiscalPeriod.starts_on <= document.return_date,
        OperationalFiscalPeriod.ends_on >= document.return_date,
        OperationalFiscalPeriod.status == "open", OperationalFiscalPeriod.rehearsal_enabled.is_(True)))
    if not period:
        raise ValueError("Return date is not in an open rehearsal-enabled fiscal period")
    existing = session.scalar(select(OperationalSalesReturnPostingRehearsal).where(
        OperationalSalesReturnPostingRehearsal.sales_return_id == document.id,
        OperationalSalesReturnPostingRehearsal.return_revision == document.revision))
    if existing:
        if existing.original_invoice_evidence_hash != document.original_invoice_evidence_hash:
            raise ValueError("Original customer-invoice evidence changed after the sales-return rehearsal")
        return _sales_return_rehearsal_payload(existing, document, idempotent_replay=True)
    restock_cost = sum(((line.restock_quantity * line.factor_to_base_snapshot * line.unit_cost_snapshot)
                        .quantize(MONEY, rounding=ROUND_HALF_UP) for line in document.lines), Decimal("0"))
    writeoff_cost = sum(((line.writeoff_quantity * line.factor_to_base_snapshot * line.unit_cost_snapshot)
                         .quantize(MONEY, rounding=ROUND_HALF_UP) for line in document.lines), Decimal("0"))
    total_cost = restock_cost + writeoff_cost
    journal = [
        {"account_code": "4010", "account": "Sales returns and discounts", "debit": document.subtotal, "credit": Decimal("0")},
        {"account_code": "2120", "account": "Output VAT payable", "debit": document.tax_amount, "credit": Decimal("0")},
        {"account_code": "1200", "account": "Trade receivables", "debit": Decimal("0"), "credit": document.total_amount},
        {"account_code": "1300", "account": "Inventory", "debit": restock_cost, "credit": Decimal("0")},
        {"account_code": "5120", "account": "Inventory write-off", "debit": writeoff_cost, "credit": Decimal("0")},
        {"account_code": "5000", "account": "Cost of goods sold", "debit": Decimal("0"), "credit": total_cost},
    ]
    movements = [{"line_no": line.line_no, "location": document.location_code, "sku": line.sku,
        "quantity_base": line.restock_quantity * line.factor_to_base_snapshot,
        "canonical_uom": line.canonical_uom, "unit_cost": line.unit_cost_snapshot,
        "value_delta": (line.restock_quantity * line.factor_to_base_snapshot * line.unit_cost_snapshot)
            .quantize(MONEY, rounding=ROUND_HALF_UP)} for line in document.lines if line.restock_quantity > 0]
    debit = sum((row["debit"] for row in journal), Decimal("0"))
    credit = sum((row["credit"] for row in journal), Decimal("0"))
    if debit != credit:
        raise RuntimeError("Sales return posting rehearsal is not balanced")
    reversal = {"journal": [{**line, "debit": line["credit"], "credit": line["debit"]}
        for line in reversed(journal)], "movements": [{**line, "quantity_base": -line["quantity_base"],
        "value_delta": -line["value_delta"]} for line in reversed(movements)]}
    source = json.dumps({"return_key": document.return_key, "revision": document.revision,
        "original_invoice_reference": document.original_invoice_reference,
        "original_invoice_evidence_hash": document.original_invoice_evidence_hash,
        "period_key": period.period_key, "journal": journal, "movements": movements,
        "reversal": reversal}, default=str, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(source.encode()).hexdigest()
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
    return {"returns":session.scalar(select(func.count(OperationalSalesReturn.id))) or 0,
            "credit_notes":session.scalar(select(func.count(OperationalSalesCreditNote.id))) or 0,
            "posted":session.scalar(select(func.count(OperationalSalesCreditNote.id)).where(OperationalSalesCreditNote.status=="posted")) or 0}
