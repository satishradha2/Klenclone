from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .customer_invoices import OperationalCustomerInvoice
from .expense_management import OperationalExpenseClaim
from .operational import MONEY, OperationalAuditEvent, OperationalBase, utc_now
from .procurement_matching import OperationalSupplierInvoice, OperationalSupplierTaxDocument
from .purchase_returns import OperationalPurchaseReturn
from .sales_returns import OperationalSalesReturn


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)


class OperationalVatPeriod(OperationalBase):
    __tablename__ = "operational_vat_periods"
    __table_args__ = (
        UniqueConstraint("period_code", name="uq_vat_period_code"),
        CheckConstraint("status IN ('draft','submitted','approved','rejected','cancelled')", name="ck_vat_period_status"),
        CheckConstraint("output_vat >= 0 AND input_vat >= 0", name="ck_vat_period_amounts"),
        CheckConstraint("posting_enabled = false", name="ck_vat_period_no_posting"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    period_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    company_trn: Mapped[str] = mapped_column(String(15), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False, index=True)
    source_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_vat: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    input_vat: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    net_vat: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    reverse_charge_output: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    reverse_charge_input: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    source_fingerprint: Mapped[str | None] = mapped_column(String(64))
    source_json: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    state_changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    state_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    decision_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    adjustments: Mapped[list["OperationalVatAdjustment"]] = relationship(
        back_populates="period", cascade="all, delete-orphan", order_by="OperationalVatAdjustment.id")


class OperationalVatAdjustment(OperationalBase):
    __tablename__ = "operational_vat_adjustments"
    __table_args__ = (
        CheckConstraint("adjustment_type IN ('output_increase','output_decrease','input_increase','input_decrease','reverse_charge')", name="ck_vat_adjustment_type"),
        CheckConstraint("status IN ('pending','approved','rejected','cancelled')", name="ck_vat_adjustment_status"),
        CheckConstraint("taxable_amount >= 0 AND vat_amount > 0", name="ck_vat_adjustment_amounts"),
        CheckConstraint("recovery_percent >= 0 AND recovery_percent <= 100", name="ck_vat_adjustment_recovery"),
        CheckConstraint("posting_enabled = false", name="ck_vat_adjustment_no_posting"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    adjustment_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    adjustment_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("operational_vat_periods.id", ondelete="CASCADE"), nullable=False, index=True)
    adjustment_type: Mapped[str] = mapped_column(String(30), nullable=False)
    adjustment_date: Mapped[date] = mapped_column(Date, nullable=False)
    evidence_reference: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    taxable_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    recovery_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=100, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    decision_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    period: Mapped[OperationalVatPeriod] = relationship(back_populates="adjustments")


class OperationalVatReturnRehearsal(OperationalBase):
    __tablename__ = "operational_vat_return_rehearsals"
    __table_args__ = (
        UniqueConstraint("period_id", "period_revision", name="uq_vat_rehearsal_period_revision"),
        CheckConstraint("posting_enabled = false", name="ck_vat_rehearsal_no_posting"),
        CheckConstraint("filing_performed = false", name="ck_vat_rehearsal_no_filing"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rehearsal_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    period_id: Mapped[int] = mapped_column(ForeignKey("operational_vat_periods.id"), nullable=False, index=True)
    period_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    journal_json: Mapped[str] = mapped_column(Text, nullable=False)
    return_json: Mapped[str] = mapped_column(Text, nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    filing_performed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    generated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


def create_vat_period(session: Session, *, period_code: str, starts_on: date, ends_on: date,
                      due_on: date, company_trn: str, actor: str) -> OperationalVatPeriod:
    if not period_code.strip() or not company_trn.isdigit() or len(company_trn) != 15:
        raise ValueError("VAT period code and a 15-digit company TRN are required")
    if ends_on < starts_on or due_on < ends_on:
        raise ValueError("VAT period and filing due dates are invalid")
    overlap = session.scalar(select(OperationalVatPeriod).where(
        OperationalVatPeriod.status.notin_({"cancelled", "rejected"}),
        OperationalVatPeriod.starts_on <= ends_on, OperationalVatPeriod.ends_on >= starts_on))
    if overlap:
        raise ValueError(f"VAT period overlaps {overlap.period_code}")
    key = str(uuid.uuid4())
    row = OperationalVatPeriod(period_key=key, period_code=period_code.strip().upper(),
        starts_on=starts_on, ends_on=ends_on, due_on=due_on, company_trn=company_trn,
        status="draft", created_by=actor, state_changed_by=actor, posting_enabled=False)
    session.add(row)
    session.flush()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="vat.period_created",
        actor=actor, resource_key=row.period_key,
        detail=f"{row.period_code}; {starts_on} to {ends_on}; non-filing"))
    session.commit()
    return row


def create_vat_adjustment(session: Session, period: OperationalVatPeriod, *,
                          adjustment_type: str, adjustment_date: date,
                          evidence_reference: str, reason: str, taxable_amount,
                          vat_amount, recovery_percent, actor: str) -> OperationalVatAdjustment:
    allowed = {"output_increase", "output_decrease", "input_increase", "input_decrease", "reverse_charge"}
    if period.status != "draft" or adjustment_type not in allowed:
        raise ValueError("VAT adjustments can only be added to a draft period")
    if not period.starts_on <= adjustment_date <= period.ends_on:
        raise ValueError("VAT adjustment date must fall inside the period")
    if len(evidence_reference.strip()) < 3 or len(reason.strip()) < 5:
        raise ValueError("VAT adjustment evidence and reason are required")
    taxable, vat, recovery = _money(taxable_amount), _money(vat_amount), Decimal(str(recovery_percent))
    if taxable < 0 or vat <= 0 or not Decimal("0") <= recovery <= Decimal("100"):
        raise ValueError("VAT adjustment amounts or recovery percentage are invalid")
    if adjustment_type == "reverse_charge" and _money(taxable * Decimal("0.05")) != vat:
        raise ValueError("Reverse-charge VAT must equal 5% of the taxable amount")
    key = str(uuid.uuid4())
    row = OperationalVatAdjustment(adjustment_key=key, adjustment_no=f"VADJ-{key[:8].upper()}",
        period_id=period.id, adjustment_type=adjustment_type, adjustment_date=adjustment_date,
        evidence_reference=evidence_reference.strip(), reason=reason.strip(),
        taxable_amount=taxable, vat_amount=vat, recovery_percent=recovery,
        status="pending", created_by=actor, posting_enabled=False)
    session.add(row)
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="vat.adjustment_created",
        actor=actor, resource_key=row.adjustment_key,
        detail=f"{row.adjustment_no}; {adjustment_type}; AED {vat}; pending approval"))
    session.commit()
    return row


def decide_vat_adjustment(session: Session, row: OperationalVatAdjustment, *, action: str,
                          expected_revision: int, actor: str, note: str) -> OperationalVatAdjustment:
    if row.revision != expected_revision:
        raise ValueError(f"VAT-adjustment revision conflict; current revision is {row.revision}")
    if row.status != "pending" or action not in {"approve", "reject", "cancel"}:
        raise ValueError("VAT adjustment action is not allowed")
    if action in {"approve", "reject"}:
        if row.created_by == actor:
            raise PermissionError("Maker-checker control prevents self-approval of a VAT adjustment")
        if len(note.strip()) < 5:
            raise ValueError("A VAT-adjustment decision note is required")
        row.approved_by = actor if action == "approve" else None
        row.decision_note = note.strip()
    row.status = {"approve": "approved", "reject": "rejected", "cancel": "cancelled"}[action]
    row.revision += 1
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"vat.adjustment_{action}",
        actor=actor, resource_key=row.adjustment_key,
        detail=f"{row.adjustment_no}; {row.status}; no posting"))
    session.commit()
    return row


def _vat_sources(session: Session, period: OperationalVatPeriod) -> list[dict]:
    rows: list[dict] = []
    for invoice in session.scalars(select(OperationalCustomerInvoice).where(
            OperationalCustomerInvoice.status == "approved",
            OperationalCustomerInvoice.invoice_date.between(period.starts_on, period.ends_on))):
        rows.append({"source_type": "customer_invoice", "reference": invoice.invoice_no,
            "date": invoice.invoice_date, "location": invoice.location_code,
            "taxable": _money(invoice.subtotal - invoice.discount_amount),
            "output_vat": _money(invoice.tax_amount), "input_vat": Decimal("0.00")})
    for returned in session.scalars(select(OperationalSalesReturn).where(
            OperationalSalesReturn.status == "approved",
            OperationalSalesReturn.return_date.between(period.starts_on, period.ends_on))):
        rows.append({"source_type": "sales_credit_note", "reference": returned.return_no,
            "date": returned.return_date, "location": returned.location_code,
            "taxable": -_money(returned.subtotal), "output_vat": -_money(returned.tax_amount),
            "input_vat": Decimal("0.00")})
    supplier_tax = {row.supplier_invoice_id: row for row in session.scalars(
        select(OperationalSupplierTaxDocument).where(OperationalSupplierTaxDocument.validation_status == "passed"))}
    for invoice in session.scalars(select(OperationalSupplierInvoice).where(
            OperationalSupplierInvoice.status == "approved",
            OperationalSupplierInvoice.invoice_date.between(period.starts_on, period.ends_on))):
        if invoice.id in supplier_tax:
            rows.append({"source_type": "supplier_tax_invoice", "reference": invoice.supplier_invoice_no,
                "date": invoice.invoice_date, "location": invoice.location_code,
                "taxable": _money(invoice.subtotal), "output_vat": Decimal("0.00"),
                "input_vat": _money(invoice.tax_amount)})
    for returned in session.scalars(select(OperationalPurchaseReturn).where(
            OperationalPurchaseReturn.status == "approved",
            OperationalPurchaseReturn.return_date.between(period.starts_on, period.ends_on))):
        rows.append({"source_type": "purchase_debit_note", "reference": returned.return_no,
            "date": returned.return_date, "location": returned.location_code,
            "taxable": -_money(returned.subtotal), "output_vat": Decimal("0.00"),
            "input_vat": -_money(returned.tax_amount)})
    for claim in session.scalars(select(OperationalExpenseClaim).where(
            OperationalExpenseClaim.status == "approved", OperationalExpenseClaim.vat_status == "eligible",
            OperationalExpenseClaim.expense_date.between(period.starts_on, period.ends_on))):
        rows.append({"source_type": "expense_tax_invoice", "reference": claim.claim_no,
            "date": claim.expense_date, "location": claim.location_code,
            "taxable": _money(claim.net_amount), "output_vat": Decimal("0.00"),
            "input_vat": _money(claim.vat_amount)})
    for adjustment in period.adjustments:
        if adjustment.status != "approved":
            continue
        output = input_value = Decimal("0.00")
        if adjustment.adjustment_type == "output_increase": output = adjustment.vat_amount
        elif adjustment.adjustment_type == "output_decrease": output = -adjustment.vat_amount
        elif adjustment.adjustment_type == "input_increase": input_value = adjustment.vat_amount
        elif adjustment.adjustment_type == "input_decrease": input_value = -adjustment.vat_amount
        else:
            output = adjustment.vat_amount
            input_value = _money(adjustment.vat_amount * adjustment.recovery_percent / Decimal("100"))
        rows.append({"source_type": f"adjustment_{adjustment.adjustment_type}",
            "reference": adjustment.adjustment_no, "date": adjustment.adjustment_date,
            "location": "COMPANY", "taxable": adjustment.taxable_amount,
            "output_vat": _money(output), "input_vat": _money(input_value),
            "evidence_reference": adjustment.evidence_reference})
    return sorted(rows, key=lambda row: (row["date"], row["source_type"], row["reference"]))


def _totals(rows: list[dict]) -> dict:
    output = _money(sum((Decimal(str(row["output_vat"])) for row in rows), Decimal("0")))
    input_value = _money(sum((Decimal(str(row["input_vat"])) for row in rows), Decimal("0")))
    reverse_rows = [row for row in rows if row["source_type"] == "adjustment_reverse_charge"]
    return {"source_count": len(rows), "output_vat": output, "input_vat": input_value,
            "net_vat": _money(output - input_value),
            "reverse_charge_output": _money(sum((Decimal(str(row["output_vat"])) for row in reverse_rows), Decimal("0"))),
            "reverse_charge_input": _money(sum((Decimal(str(row["input_vat"])) for row in reverse_rows), Decimal("0")))}


def transition_vat_period(session: Session, row: OperationalVatPeriod, *, action: str,
                          expected_revision: int, actor: str, note: str | None = None) -> OperationalVatPeriod:
    if row.revision != expected_revision:
        raise ValueError(f"VAT-period revision conflict; current revision is {row.revision}")
    if action == "submit" and row.status == "draft":
        if any(item.status == "pending" for item in row.adjustments):
            raise ValueError("Resolve every pending VAT adjustment before submitting the return")
        sources = _vat_sources(session, row)
        totals = _totals(sources)
        if not sources:
            raise ValueError("VAT return cannot be submitted without source evidence")
        source_json = json.dumps(sources, default=str, sort_keys=True, separators=(",", ":"))
        row.source_json = source_json
        row.source_fingerprint = hashlib.sha256(source_json.encode()).hexdigest()
        for key, value in totals.items(): setattr(row, key, value)
        row.status = "submitted"
    elif action == "cancel" and row.status == "draft":
        row.status = "cancelled"
    elif action in {"approve", "reject"} and row.status == "submitted":
        if row.created_by == actor:
            raise PermissionError("Maker-checker control prevents self-approval of a VAT return")
        if len((note or "").strip()) < 5:
            raise ValueError("A VAT-return decision note is required")
        row.status = "approved" if action == "approve" else "rejected"
        row.approved_by = actor if action == "approve" else None
        row.decision_note = note.strip()
    else:
        raise ValueError(f"VAT-period action {action} is not allowed from {row.status}")
    row.revision += 1
    row.state_changed_by, row.state_changed_at = actor, utc_now()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"vat.period_{action}",
        actor=actor, resource_key=row.period_key,
        detail=f"{row.period_code}; {row.status}; revision {row.revision}; non-filing"))
    session.commit()
    return row


def rehearse_vat_return(session: Session, row: OperationalVatPeriod, *, actor: str) -> dict:
    if row.status != "approved" or not row.source_fingerprint:
        raise ValueError("Only an approved frozen VAT return can be rehearsed")
    existing = session.scalar(select(OperationalVatReturnRehearsal).where(
        OperationalVatReturnRehearsal.period_id == row.id,
        OperationalVatReturnRehearsal.period_revision == row.revision))
    if existing:
        return vat_rehearsal_payload(existing, idempotent_replay=True)
    output, input_value, net = _money(row.output_vat), _money(row.input_vat), _money(row.net_vat)
    journal = []
    if output:
        journal.append({"account": "Output VAT Payable", "debit": output, "credit": Decimal("0")})
    if input_value:
        journal.append({"account": "Input VAT Recoverable", "debit": Decimal("0"), "credit": input_value})
    if net > 0:
        journal.append({"account": "FTA VAT Payable", "debit": Decimal("0"), "credit": net})
    elif net < 0:
        journal.append({"account": "FTA VAT Receivable", "debit": -net, "credit": Decimal("0")})
    debit = _money(sum((line["debit"] for line in journal), Decimal("0")))
    credit = _money(sum((line["credit"] for line in journal), Decimal("0")))
    if debit != credit:
        raise RuntimeError("VAT-return rehearsal is not balanced")
    return_payload = {"period_code": row.period_code, "company_trn": row.company_trn,
        "starts_on": row.starts_on, "ends_on": row.ends_on, "due_on": row.due_on,
        "source_count": row.source_count, "output_vat": output, "input_vat": input_value,
        "net_vat": net, "reverse_charge_output": row.reverse_charge_output,
        "reverse_charge_input": row.reverse_charge_input,
        "filing_status": "not_filed_testing_rehearsal"}
    rehearsal = OperationalVatReturnRehearsal(rehearsal_key=str(uuid.uuid4()), period_id=row.id,
        period_revision=row.revision, source_fingerprint=row.source_fingerprint,
        journal_json=json.dumps(journal, default=str, sort_keys=True),
        return_json=json.dumps(return_payload, default=str, sort_keys=True),
        posting_enabled=False, filing_performed=False, generated_by=actor)
    session.add(rehearsal)
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="vat.return_rehearsed",
        actor=actor, resource_key=row.period_key,
        detail=f"{row.period_code}; net AED {net}; no posting; no filing"))
    session.commit()
    return vat_rehearsal_payload(rehearsal)


def vat_rehearsal_payload(row: OperationalVatReturnRehearsal, *, idempotent_replay: bool = False) -> dict:
    return {"rehearsal_key": row.rehearsal_key, "source_fingerprint": row.source_fingerprint,
            "journal": json.loads(row.journal_json), "return": json.loads(row.return_json),
            "posting_enabled": False, "posting_performed": False, "filing_performed": False,
            "idempotent_replay": idempotent_replay}


def adjustment_payload(row: OperationalVatAdjustment) -> dict:
    return {"adjustment_key": row.adjustment_key, "adjustment_no": row.adjustment_no,
        "adjustment_type": row.adjustment_type, "adjustment_date": row.adjustment_date,
        "evidence_reference": row.evidence_reference, "reason": row.reason,
        "taxable_amount": row.taxable_amount, "vat_amount": row.vat_amount,
        "recovery_percent": row.recovery_percent, "status": row.status,
        "created_by": row.created_by, "approved_by": row.approved_by,
        "decision_note": row.decision_note, "revision": row.revision, "posting_enabled": False}


def vat_period_payload(session: Session, row: OperationalVatPeriod) -> dict:
    rehearsal = session.scalar(select(OperationalVatReturnRehearsal).where(
        OperationalVatReturnRehearsal.period_id == row.id,
        OperationalVatReturnRehearsal.period_revision == row.revision))
    live_sources = _vat_sources(session, row) if row.status == "draft" else json.loads(row.source_json or "[]")
    live_totals = _totals(live_sources)
    return {"period_key": row.period_key, "period_code": row.period_code,
        "starts_on": row.starts_on, "ends_on": row.ends_on, "due_on": row.due_on,
        "company_trn": row.company_trn, "status": row.status,
        "source_count": live_totals["source_count"] if row.status == "draft" else row.source_count,
        "output_vat": live_totals["output_vat"] if row.status == "draft" else row.output_vat,
        "input_vat": live_totals["input_vat"] if row.status == "draft" else row.input_vat,
        "net_vat": live_totals["net_vat"] if row.status == "draft" else row.net_vat,
        "reverse_charge_output": live_totals["reverse_charge_output"] if row.status == "draft" else row.reverse_charge_output,
        "reverse_charge_input": live_totals["reverse_charge_input"] if row.status == "draft" else row.reverse_charge_input,
        "source_fingerprint": row.source_fingerprint, "sources": live_sources,
        "adjustments": [adjustment_payload(item) for item in row.adjustments],
        "created_by": row.created_by, "approved_by": row.approved_by,
        "decision_note": row.decision_note, "revision": row.revision,
        "rehearsal": vat_rehearsal_payload(rehearsal) if rehearsal else None,
        "posting_enabled": False, "filing_enabled": False}


def vat_workspace_payload(session: Session) -> dict:
    periods = list(session.scalars(select(OperationalVatPeriod).order_by(OperationalVatPeriod.starts_on.desc())))
    return {"periods": [vat_period_payload(session, row) for row in periods],
            "controls": {"periods": len(periods),
                "pending_returns": sum(row.status == "submitted" for row in periods),
                "pending_adjustments": session.scalar(select(func.count(OperationalVatAdjustment.id)).where(
                    OperationalVatAdjustment.status == "pending")) or 0,
                "approved_returns": sum(row.status == "approved" for row in periods),
                "rehearsals": session.scalar(select(func.count(OperationalVatReturnRehearsal.id))) or 0,
                "filings": 0, "permanent_postings": 0}}
