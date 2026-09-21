from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .cash_management import OperationalCashAccount
from .operational import MONEY, OperationalAuditEvent, OperationalBase, OperationalFiscalPeriod, utc_now


EXPENSE_CATEGORIES = {
    "cogs": ("Cost of Goods Sold (COGS)", "5000"),
    "cost_of_sales": ("Cost of sales", "5000"),
    "fuel": ("Fuel (Petrol)", "6000"),
    "bank_charges": ("Bank charges", "6300"),
    "office_admin": ("Office and administration", "6100"),
    "travel": ("Travel and conveyance", "6000"),
}


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)


class OperationalExpenseClaim(OperationalBase):
    __tablename__ = "operational_expense_claims"
    __table_args__ = (
        UniqueConstraint("claim_no", name="uq_expense_claim_no"),
        CheckConstraint("claimant_type IN ('employee','supplier','company')", name="ck_expense_claimant_type"),
        CheckConstraint("settlement_method IN ('reimbursement','direct_payment','petty_cash')", name="ck_expense_settlement_method"),
        CheckConstraint("vat_status IN ('eligible','nonrecoverable','review_required')", name="ck_expense_vat_status"),
        CheckConstraint("status IN ('draft','submitted','approved','rejected','cancelled')", name="ck_expense_status"),
        CheckConstraint("net_amount >= 0 AND vat_amount >= 0 AND total_amount > 0", name="ck_expense_amounts"),
        CheckConstraint("posting_enabled = false", name="ck_expense_no_posting"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    claim_no: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    claimant_type: Mapped[str] = mapped_column(String(20), nullable=False)
    claimant_reference: Mapped[str | None] = mapped_column(String(80), index=True)
    claimant_name: Mapped[str] = mapped_column(String(200), nullable=False)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    cost_center: Mapped[str] = mapped_column(String(80), nullable=False)
    category_code: Mapped[str] = mapped_column(String(80), nullable=False)
    category_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    gl_account_code_snapshot: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    receipt_reference: Mapped[str] = mapped_column(String(200), nullable=False)
    tax_invoice_no: Mapped[str | None] = mapped_column(String(160))
    supplier_trn: Mapped[str | None] = mapped_column(String(15))
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    vat_status: Mapped[str] = mapped_column(String(30), nullable=False)
    settlement_method: Mapped[str] = mapped_column(String(30), nullable=False)
    payment_account_id: Mapped[int | None] = mapped_column(ForeignKey("operational_cash_accounts.id"))
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    state_changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    state_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    decision_note: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payment_account: Mapped[OperationalCashAccount | None] = relationship()


class OperationalExpenseRehearsal(OperationalBase):
    __tablename__ = "operational_expense_rehearsals"
    __table_args__ = (
        UniqueConstraint("claim_id", "claim_revision", name="uq_expense_rehearsal_revision"),
        CheckConstraint("posting_enabled = false", name="ck_expense_rehearsal_no_posting"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rehearsal_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    claim_id: Mapped[int] = mapped_column(ForeignKey("operational_expense_claims.id"), nullable=False, index=True)
    claim_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    period_key: Mapped[str] = mapped_column(String(20), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    journal_json: Mapped[str] = mapped_column(Text, nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    generated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalPettyCashAdvance(OperationalBase):
    __tablename__ = "operational_petty_cash_advances"
    __table_args__ = (
        UniqueConstraint("advance_no", name="uq_petty_advance_no"),
        CheckConstraint("status IN ('pending','approved','rejected','issued','settled','cancelled')", name="ck_petty_advance_status"),
        CheckConstraint("amount > 0 AND spent_amount >= 0 AND returned_amount >= 0", name="ck_petty_advance_amounts"),
        CheckConstraint("posting_enabled = false", name="ck_petty_advance_no_posting"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    advance_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    advance_no: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    recipient_reference: Mapped[str | None] = mapped_column(String(80))
    recipient_name: Mapped[str] = mapped_column(String(200), nullable=False)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    cost_center: Mapped[str] = mapped_column(String(80), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("operational_cash_accounts.id"), nullable=False)
    requested_on: Mapped[date] = mapped_column(Date, nullable=False)
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    purpose: Mapped[str] = mapped_column(String(500), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    spent_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    returned_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    settlement_category_code: Mapped[str | None] = mapped_column(String(80))
    settlement_receipt_reference: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    state_changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    state_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    decision_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    account: Mapped[OperationalCashAccount] = relationship()


class OperationalPettyCashRehearsal(OperationalBase):
    __tablename__ = "operational_petty_cash_rehearsals"
    __table_args__ = (
        UniqueConstraint("advance_id", "advance_revision", name="uq_petty_rehearsal_revision"),
        CheckConstraint("posting_enabled = false", name="ck_petty_rehearsal_no_posting"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rehearsal_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    advance_id: Mapped[int] = mapped_column(ForeignKey("operational_petty_cash_advances.id"), nullable=False, index=True)
    advance_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    journal_json: Mapped[str] = mapped_column(Text, nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    generated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


def expense_categories_payload() -> list[dict]:
    return [{"category_code": code, "category_name": name, "gl_account_code": gl}
            for code, (name, gl) in EXPENSE_CATEGORIES.items()]


def _vat_state(net: Decimal, vat: Decimal, rate: Decimal, tax_invoice_no: str | None, supplier_trn: str | None) -> str:
    if rate not in {Decimal("0"), Decimal("5")}:
        raise ValueError("Expense VAT rate must be 0% or the UAE standard rate of 5%")
    expected = _money(net * rate / Decimal("100"))
    if expected != vat:
        raise ValueError(f"VAT amount must equal AED {expected} for the selected rate")
    if vat == 0:
        return "nonrecoverable"
    if not (tax_invoice_no or "").strip() or not re.fullmatch(r"\d{15}", (supplier_trn or "").strip()):
        return "review_required"
    return "eligible"


def create_expense_claim(session: Session, *, claimant_type: str, claimant_reference: str | None,
                         claimant_name: str, expense_date: date, location_code: str,
                         cost_center: str, category_code: str, description: str,
                         receipt_reference: str, tax_invoice_no: str | None,
                         supplier_trn: str | None, vat_rate, net_amount, vat_amount,
                         settlement_method: str, payment_account_key: str | None,
                         actor: str) -> OperationalExpenseClaim:
    if claimant_type not in {"employee", "supplier", "company"}:
        raise ValueError("Claimant type is invalid")
    if settlement_method not in {"reimbursement", "direct_payment", "petty_cash"}:
        raise ValueError("Settlement method is invalid")
    if category_code not in EXPENSE_CATEGORIES:
        raise ValueError("Expense category is not approved")
    if not claimant_name.strip() or not description.strip() or not receipt_reference.strip() or not cost_center.strip():
        raise ValueError("Claimant, description, receipt reference and cost centre are required")
    net, vat, rate = _money(net_amount), _money(vat_amount), Decimal(str(vat_rate))
    if net < 0 or net + vat <= 0:
        raise ValueError("Expense amounts must be positive")
    vat_status = _vat_state(net, vat, rate, tax_invoice_no, supplier_trn)
    account = None
    if payment_account_key:
        account = session.scalar(select(OperationalCashAccount).where(
            OperationalCashAccount.account_key == payment_account_key))
        if not account or account.status != "active":
            raise ValueError("Settlement account must be an approved bank or cash account")
        if account.location_code != location_code.strip().upper():
            raise ValueError("Settlement account location must match the expense location")
    if settlement_method in {"direct_payment", "petty_cash"} and not account:
        raise ValueError("Direct and petty-cash expenses require an approved settlement account")
    key = str(uuid.uuid4())
    category_name, gl_code = EXPENSE_CATEGORIES[category_code]
    row = OperationalExpenseClaim(
        claim_key=key, claim_no=f"EXP-{key[:8].upper()}", claimant_type=claimant_type,
        claimant_reference=(claimant_reference or "").strip() or None,
        claimant_name=claimant_name.strip(), expense_date=expense_date,
        location_code=location_code.strip().upper(), cost_center=cost_center.strip().upper(),
        category_code=category_code, category_name_snapshot=category_name,
        gl_account_code_snapshot=gl_code, description=description.strip(),
        receipt_reference=receipt_reference.strip(), tax_invoice_no=(tax_invoice_no or "").strip() or None,
        supplier_trn=(supplier_trn or "").strip() or None, vat_rate=rate,
        net_amount=net, vat_amount=vat, total_amount=_money(net + vat), vat_status=vat_status,
        settlement_method=settlement_method, payment_account_id=account.id if account else None,
        status="draft", created_by=actor, state_changed_by=actor, posting_enabled=False)
    session.add(row)
    session.flush()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="expense.created",
        actor=actor, resource_key=row.claim_key,
        detail=f"{row.claim_no}; AED {row.total_amount}; {vat_status}; posting disabled"))
    session.commit()
    return row


def transition_expense_claim(session: Session, row: OperationalExpenseClaim, *, action: str,
                             expected_revision: int, actor: str, note: str | None = None) -> OperationalExpenseClaim:
    transitions = {("draft", "submit"): "submitted", ("draft", "cancel"): "cancelled",
                   ("submitted", "approve"): "approved", ("submitted", "reject"): "rejected"}
    if row.revision != expected_revision:
        raise ValueError(f"Expense revision conflict; current revision is {row.revision}")
    target = transitions.get((row.status, action))
    if not target:
        raise ValueError(f"Action {action} is not allowed from {row.status}")
    if action == "submit" and row.vat_status == "review_required":
        raise ValueError("VAT evidence requires a tax invoice number and 15-digit supplier TRN before submission")
    if action in {"approve", "reject"}:
        if row.created_by == actor:
            raise PermissionError("Maker-checker control prevents the creator from deciding this expense")
        if len((note or "").strip()) < 5:
            raise ValueError("An expense decision note is required")
        row.approved_by = actor if action == "approve" else None
        row.decision_note = note.strip()
    prior = row.status
    row.status, row.revision = target, row.revision + 1
    row.state_changed_by, row.state_changed_at = actor, utc_now()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"expense.{action}",
        actor=actor, resource_key=row.claim_key,
        detail=f"{prior} to {target}; revision {row.revision}; posting disabled"))
    session.commit()
    return row


def rehearse_expense(session: Session, row: OperationalExpenseClaim, *, actor: str) -> dict:
    if row.status != "approved":
        raise ValueError("Only an approved expense can be rehearsed")
    period = session.scalar(select(OperationalFiscalPeriod).where(
        OperationalFiscalPeriod.starts_on <= row.expense_date,
        OperationalFiscalPeriod.ends_on >= row.expense_date,
        OperationalFiscalPeriod.status == "open", OperationalFiscalPeriod.rehearsal_enabled.is_(True)))
    if not period:
        raise ValueError("Expense date is not in an open rehearsal-enabled fiscal period")
    existing = session.scalar(select(OperationalExpenseRehearsal).where(
        OperationalExpenseRehearsal.claim_id == row.id,
        OperationalExpenseRehearsal.claim_revision == row.revision))
    if existing:
        return expense_rehearsal_payload(existing, idempotent_replay=True)
    credit_account = row.payment_account.account_code if row.payment_account else "Employee Reimbursements Payable"
    journal = [{"account": row.gl_account_code_snapshot, "debit": row.net_amount, "credit": Decimal("0.00")}]
    if row.vat_amount:
        journal.append({"account": "Input VAT", "debit": row.vat_amount, "credit": Decimal("0.00")})
    journal.append({"account": credit_account, "debit": Decimal("0.00"), "credit": row.total_amount})
    debit = _money(sum((line["debit"] for line in journal), Decimal("0")))
    credit = _money(sum((line["credit"] for line in journal), Decimal("0")))
    if debit != credit:
        raise RuntimeError("Expense rehearsal is not balanced")
    source = json.dumps({"claim": row.claim_key, "revision": row.revision, "journal": journal},
                        default=str, sort_keys=True, separators=(",", ":"))
    rehearsal = OperationalExpenseRehearsal(rehearsal_key=str(uuid.uuid4()), claim_id=row.id,
        claim_revision=row.revision, period_key=period.period_key,
        fingerprint=hashlib.sha256(source.encode()).hexdigest(),
        journal_json=json.dumps(journal, default=str, sort_keys=True), posting_enabled=False,
        generated_by=actor)
    session.add(rehearsal)
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="expense.rehearsed",
        actor=actor, resource_key=row.claim_key,
        detail=f"AED {debit}; {len(journal)} lines; no posting"))
    session.commit()
    return expense_rehearsal_payload(rehearsal)


def expense_rehearsal_payload(row: OperationalExpenseRehearsal, *, idempotent_replay: bool = False) -> dict:
    return {"rehearsal_key": row.rehearsal_key, "period_key": row.period_key,
            "fingerprint": row.fingerprint, "journal": json.loads(row.journal_json),
            "posting_enabled": False, "posting_performed": False,
            "idempotent_replay": idempotent_replay}


def create_petty_cash_advance(session: Session, *, recipient_reference: str | None,
                              recipient_name: str, location_code: str, cost_center: str,
                              account_key: str, requested_on: date, due_on: date,
                              purpose: str, amount, actor: str) -> OperationalPettyCashAdvance:
    if not recipient_name.strip() or not purpose.strip() or not cost_center.strip():
        raise ValueError("Recipient, purpose and cost centre are required")
    if due_on < requested_on:
        raise ValueError("Petty-cash settlement due date cannot precede the request date")
    account = session.scalar(select(OperationalCashAccount).where(
        OperationalCashAccount.account_key == account_key))
    if not account or account.status != "active" or account.account_type != "cash":
        raise ValueError("Petty-cash advances require an approved cash account")
    if account.location_code != location_code.strip().upper():
        raise ValueError("Petty-cash account location must match the advance location")
    value = _money(amount)
    if value <= 0:
        raise ValueError("Petty-cash advance amount must be positive")
    key = str(uuid.uuid4())
    row = OperationalPettyCashAdvance(advance_key=key, advance_no=f"PCA-{key[:8].upper()}",
        recipient_reference=(recipient_reference or "").strip() or None,
        recipient_name=recipient_name.strip(), location_code=location_code.strip().upper(),
        cost_center=cost_center.strip().upper(), account_id=account.id,
        requested_on=requested_on, due_on=due_on, purpose=purpose.strip(), amount=value,
        spent_amount=Decimal("0"), returned_amount=Decimal("0"), status="pending",
        created_by=actor, state_changed_by=actor, posting_enabled=False)
    session.add(row)
    session.flush()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="petty_cash.requested",
        actor=actor, resource_key=row.advance_key, detail=f"{row.advance_no}; AED {value}; pending approval"))
    session.commit()
    return row


def transition_petty_cash_advance(session: Session, row: OperationalPettyCashAdvance, *,
                                  action: str, expected_revision: int, actor: str,
                                  note: str | None = None, spent_amount=None,
                                  returned_amount=None, category_code: str | None = None,
                                  receipt_reference: str | None = None) -> OperationalPettyCashAdvance:
    if row.revision != expected_revision:
        raise ValueError(f"Petty-cash revision conflict; current revision is {row.revision}")
    if action in {"approve", "reject"}:
        if row.status != "pending":
            raise ValueError("Only a pending petty-cash advance can be decided")
        if row.created_by == actor:
            raise PermissionError("Maker-checker control prevents the requester from deciding this advance")
        if len((note or "").strip()) < 5:
            raise ValueError("A petty-cash decision note is required")
        row.status = "approved" if action == "approve" else "rejected"
        row.approved_by = actor if action == "approve" else None
        row.decision_note = note.strip()
    elif action == "issue":
        if row.status != "approved":
            raise ValueError("Only an approved petty-cash advance can be issued")
        row.status = "issued"
    elif action == "settle":
        if row.status != "issued":
            raise ValueError("Only an issued petty-cash advance can be settled")
        spent, returned = _money(spent_amount), _money(returned_amount)
        if spent < 0 or returned < 0 or _money(spent + returned) != row.amount:
            raise ValueError("Spent plus returned petty cash must equal the issued amount")
        if spent and (category_code not in EXPENSE_CATEGORIES or not (receipt_reference or "").strip()):
            raise ValueError("Spent petty cash requires an approved category and receipt reference")
        row.spent_amount, row.returned_amount = spent, returned
        row.settlement_category_code = category_code if spent else None
        row.settlement_receipt_reference = (receipt_reference or "").strip() or None
        row.status = "settled"
    elif action == "cancel" and row.status == "pending":
        row.status = "cancelled"
    else:
        raise ValueError(f"Action {action} is not allowed from {row.status}")
    row.revision += 1
    row.state_changed_by, row.state_changed_at = actor, utc_now()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"petty_cash.{action}",
        actor=actor, resource_key=row.advance_key,
        detail=f"{row.advance_no}; {row.status}; revision {row.revision}; no posting"))
    session.commit()
    return row


def rehearse_petty_cash(session: Session, row: OperationalPettyCashAdvance, *, actor: str) -> dict:
    if row.status not in {"approved", "issued", "settled"}:
        raise ValueError("Only an approved, issued or settled advance can be rehearsed")
    existing = session.scalar(select(OperationalPettyCashRehearsal).where(
        OperationalPettyCashRehearsal.advance_id == row.id,
        OperationalPettyCashRehearsal.advance_revision == row.revision))
    if existing:
        return petty_rehearsal_payload(existing, idempotent_replay=True)
    if row.status == "settled":
        journal = []
        if row.spent_amount:
            gl = EXPENSE_CATEGORIES[row.settlement_category_code][1]
            journal.append({"account": gl, "debit": row.spent_amount, "credit": Decimal("0")})
        if row.returned_amount:
            journal.append({"account": row.account.account_code, "debit": row.returned_amount, "credit": Decimal("0")})
        journal.append({"account": "Employee Advances", "debit": Decimal("0"), "credit": row.amount})
        stage = "settlement"
    else:
        journal = [{"account": "Employee Advances", "debit": row.amount, "credit": Decimal("0")},
                   {"account": row.account.account_code, "debit": Decimal("0"), "credit": row.amount}]
        stage = "issue"
    debit = _money(sum((line["debit"] for line in journal), Decimal("0")))
    credit = _money(sum((line["credit"] for line in journal), Decimal("0")))
    if debit != credit:
        raise RuntimeError("Petty-cash rehearsal is not balanced")
    source = json.dumps({"advance": row.advance_key, "revision": row.revision, "stage": stage, "journal": journal},
                        default=str, sort_keys=True, separators=(",", ":"))
    rehearsal = OperationalPettyCashRehearsal(rehearsal_key=str(uuid.uuid4()), advance_id=row.id,
        advance_revision=row.revision, stage=stage, fingerprint=hashlib.sha256(source.encode()).hexdigest(),
        journal_json=json.dumps(journal, default=str, sort_keys=True), posting_enabled=False,
        generated_by=actor)
    session.add(rehearsal)
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="petty_cash.rehearsed",
        actor=actor, resource_key=row.advance_key, detail=f"{stage}; AED {debit}; no posting"))
    session.commit()
    return petty_rehearsal_payload(rehearsal)


def petty_rehearsal_payload(row: OperationalPettyCashRehearsal, *, idempotent_replay: bool = False) -> dict:
    return {"rehearsal_key": row.rehearsal_key, "stage": row.stage, "fingerprint": row.fingerprint,
            "journal": json.loads(row.journal_json), "posting_enabled": False,
            "posting_performed": False, "idempotent_replay": idempotent_replay}


def expense_claim_payload(session: Session, row: OperationalExpenseClaim) -> dict:
    rehearsal = session.scalar(select(OperationalExpenseRehearsal).where(
        OperationalExpenseRehearsal.claim_id == row.id,
        OperationalExpenseRehearsal.claim_revision == row.revision))
    return {"claim_key": row.claim_key, "claim_no": row.claim_no,
        "claimant_type": row.claimant_type, "claimant_reference": row.claimant_reference,
        "claimant_name": row.claimant_name, "expense_date": row.expense_date,
        "location_code": row.location_code, "cost_center": row.cost_center,
        "category_code": row.category_code, "category_name": row.category_name_snapshot,
        "gl_account_code": row.gl_account_code_snapshot, "description": row.description,
        "receipt_reference": row.receipt_reference, "tax_invoice_no": row.tax_invoice_no,
        "supplier_trn": row.supplier_trn, "vat_rate": row.vat_rate,
        "net_amount": row.net_amount, "vat_amount": row.vat_amount,
        "total_amount": row.total_amount, "vat_status": row.vat_status,
        "settlement_method": row.settlement_method,
        "payment_account_name": row.payment_account.account_name if row.payment_account else None,
        "status": row.status, "created_by": row.created_by, "approved_by": row.approved_by,
        "decision_note": row.decision_note, "revision": row.revision,
        "rehearsal": expense_rehearsal_payload(rehearsal) if rehearsal else None,
        "posting_enabled": False}


def petty_advance_payload(session: Session, row: OperationalPettyCashAdvance) -> dict:
    rehearsals = list(session.scalars(select(OperationalPettyCashRehearsal).where(
        OperationalPettyCashRehearsal.advance_id == row.id).order_by(OperationalPettyCashRehearsal.id)))
    return {"advance_key": row.advance_key, "advance_no": row.advance_no,
        "recipient_reference": row.recipient_reference, "recipient_name": row.recipient_name,
        "location_code": row.location_code, "cost_center": row.cost_center,
        "account_name": row.account.account_name, "account_code": row.account.account_code,
        "requested_on": row.requested_on, "due_on": row.due_on, "purpose": row.purpose,
        "amount": row.amount, "spent_amount": row.spent_amount, "returned_amount": row.returned_amount,
        "settlement_category_code": row.settlement_category_code,
        "settlement_receipt_reference": row.settlement_receipt_reference,
        "status": row.status, "created_by": row.created_by, "approved_by": row.approved_by,
        "decision_note": row.decision_note, "revision": row.revision,
        "rehearsals": [petty_rehearsal_payload(item) for item in rehearsals],
        "posting_enabled": False}


def expense_workspace_payload(session: Session) -> dict:
    claims = list(session.scalars(select(OperationalExpenseClaim).order_by(OperationalExpenseClaim.created_at.desc())))
    advances = list(session.scalars(select(OperationalPettyCashAdvance).order_by(OperationalPettyCashAdvance.created_at.desc())))
    accounts = list(session.scalars(select(OperationalCashAccount).where(
        OperationalCashAccount.status == "active").order_by(OperationalCashAccount.account_name)))
    return {"categories": expense_categories_payload(),
        "accounts": [{"account_key": row.account_key, "account_code": row.account_code,
                      "account_name": row.account_name, "account_type": row.account_type,
                      "location_code": row.location_code} for row in accounts],
        "claims": [expense_claim_payload(session, row) for row in claims],
        "advances": [petty_advance_payload(session, row) for row in advances],
        "controls": {"claims": len(claims),
            "pending_claims": sum(row.status == "submitted" for row in claims),
            "vat_reviews": sum(row.vat_status == "review_required" for row in claims),
            "open_advances": sum(row.status in {"pending", "approved", "issued"} for row in advances),
            "overdue_advances": sum(row.status == "issued" and row.due_on < date.today() for row in advances),
            "rehearsals": (session.scalar(select(func.count(OperationalExpenseRehearsal.id))) or 0) +
                          (session.scalar(select(func.count(OperationalPettyCashRehearsal.id))) or 0),
            "permanent_postings": 0}}
