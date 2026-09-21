from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import (CheckConstraint, Date, DateTime, ForeignKey, Integer,
                        Numeric, String, Text, UniqueConstraint, func, select)
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .operational import MONEY, OperationalAuditEvent, OperationalBase, utc_now
from .payments import OperationalPayment


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)


class OperationalCashAccount(OperationalBase):
    __tablename__ = "operational_cash_accounts"
    __table_args__ = (
        UniqueConstraint("account_code", name="uq_cash_account_code"),
        CheckConstraint("account_type IN ('bank','cash')", name="ck_cash_account_type"),
        CheckConstraint("status IN ('pending','active','rejected','inactive')", name="ck_cash_account_status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    account_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    account_name: Mapped[str] = mapped_column(String(200), nullable=False)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)
    bank_name: Mapped[str | None] = mapped_column(String(200))
    identifier_last4: Mapped[str | None] = mapped_column(String(4))
    currency_code: Mapped[str] = mapped_column(String(3), default="AED", nullable=False)
    gl_account_code: Mapped[str] = mapped_column(String(80), nullable=False)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class OperationalStatementBatch(OperationalBase):
    __tablename__ = "operational_statement_batches"
    __table_args__ = (
        UniqueConstraint("account_id", "statement_reference", name="uq_statement_account_reference"),
        UniqueConstraint("source_checksum", name="uq_statement_source_checksum"),
        CheckConstraint("status IN ('draft','submitted','approved','rejected')", name="ck_statement_status"),
        CheckConstraint("statement_end >= statement_start", name="ck_statement_dates"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("operational_cash_accounts.id"), nullable=False, index=True)
    statement_reference: Mapped[str] = mapped_column(String(160), nullable=False)
    statement_start: Mapped[date] = mapped_column(Date, nullable=False)
    statement_end: Mapped[date] = mapped_column(Date, nullable=False)
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    closing_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_debits: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_credits: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    source_file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    state_changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    state_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    approval_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    account: Mapped[OperationalCashAccount] = relationship()
    lines: Mapped[list["OperationalStatementLine"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan", order_by="OperationalStatementLine.line_no")


class OperationalStatementLine(OperationalBase):
    __tablename__ = "operational_statement_lines"
    __table_args__ = (
        UniqueConstraint("batch_id", "line_no", name="uq_statement_line_no"),
        UniqueConstraint("batch_id", "external_id", name="uq_statement_external_id"),
        CheckConstraint("debit_amount >= 0 AND credit_amount >= 0 AND ((debit_amount > 0 AND credit_amount = 0) OR (credit_amount > 0 AND debit_amount = 0))", name="ck_statement_line_amount"),
        CheckConstraint("status IN ('unmatched','matched','exception')", name="ck_statement_line_status"),
        CheckConstraint("exception_category IS NULL OR exception_category IN ('bank_fee','bank_interest','timing_difference','bank_error','other')", name="ck_statement_exception_category"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("operational_statement_batches.id", ondelete="CASCADE"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    external_id: Mapped[str] = mapped_column(String(160), nullable=False)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    value_date: Mapped[date | None] = mapped_column(Date)
    reference: Mapped[str | None] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    debit_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    credit_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="unmatched", nullable=False)
    suggested_payment_id: Mapped[int | None] = mapped_column(ForeignKey("operational_payments.id"))
    matched_payment_id: Mapped[int | None] = mapped_column(ForeignKey("operational_payments.id"))
    match_basis: Mapped[str | None] = mapped_column(String(100))
    exception_category: Mapped[str | None] = mapped_column(String(30))
    exception_reason: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[str | None] = mapped_column(String(200))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    batch: Mapped[OperationalStatementBatch] = relationship(back_populates="lines")
    suggested_payment: Mapped[OperationalPayment | None] = relationship(foreign_keys=[suggested_payment_id])
    matched_payment: Mapped[OperationalPayment | None] = relationship(foreign_keys=[matched_payment_id])


class OperationalReconciliationRehearsal(OperationalBase):
    __tablename__ = "operational_reconciliation_rehearsals"
    __table_args__ = (
        UniqueConstraint("batch_id", "batch_revision", name="uq_reconciliation_rehearsal_revision"),
        CheckConstraint("posting_enabled = false", name="ck_reconciliation_rehearsal_no_posting"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rehearsal_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    batch_id: Mapped[int] = mapped_column(ForeignKey("operational_statement_batches.id"), nullable=False, index=True)
    batch_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    generated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


def cash_account_payload(row: OperationalCashAccount) -> dict:
    return {
        "account_key": row.account_key, "account_code": row.account_code,
        "account_name": row.account_name, "account_type": row.account_type,
        "bank_name": row.bank_name, "identifier_last4": row.identifier_last4,
        "currency_code": row.currency_code, "gl_account_code": row.gl_account_code,
        "location_code": row.location_code, "status": row.status,
        "reason": row.reason, "created_by": row.created_by, "created_at": row.created_at,
        "decided_by": row.decided_by, "decided_at": row.decided_at,
        "decision_note": row.decision_note, "revision": row.revision,
    }


def create_cash_account(session: Session, *, account_code: str, account_name: str,
                        account_type: str, bank_name: str | None,
                        identifier: str | None, gl_account_code: str,
                        location_code: str, reason: str, actor: str) -> OperationalCashAccount:
    code = account_code.strip()
    name = account_name.strip()
    reason = reason.strip()
    if account_type not in {"bank", "cash"}:
        raise ValueError("Account type must be bank or cash")
    if not code or not name or not gl_account_code.strip() or not location_code.strip() or len(reason) < 5:
        raise ValueError("Account code, name, GL account, location and reason are required")
    if session.scalar(select(OperationalCashAccount.id).where(
            func.lower(OperationalCashAccount.account_code) == code.casefold())):
        raise ValueError("Cash/bank account code already exists")
    compact = re.sub(r"[^A-Za-z0-9]", "", identifier or "")
    if account_type == "bank" and identifier and len(compact) < 4:
        raise ValueError("Bank identifier must contain at least four characters")
    row = OperationalCashAccount(
        account_key=str(uuid.uuid4()), account_code=code, account_name=name,
        account_type=account_type, bank_name=(bank_name or "").strip() or None,
        identifier_last4=compact[-4:] or None, currency_code="AED",
        gl_account_code=gl_account_code.strip(), location_code=location_code.strip().upper(),
        status="pending", reason=reason, created_by=actor,
    )
    session.add(row)
    session.flush()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="cash_account.requested",
        actor=actor, resource_key=row.account_key, detail=f"{code}; {account_type}; AED; pending approval"))
    session.commit()
    return row


def decide_cash_account(session: Session, row: OperationalCashAccount, *, action: str,
                        expected_revision: int, actor: str, note: str) -> OperationalCashAccount:
    if row.status != "pending" or action not in {"approve", "reject"}:
        raise ValueError("Only a pending cash/bank account can be approved or rejected")
    if row.revision != expected_revision:
        raise ValueError(f"Account revision conflict; current revision is {row.revision}")
    if row.created_by == actor:
        raise PermissionError("Maker-checker control prevents the requester from deciding this account")
    if len(note.strip()) < 5:
        raise ValueError("A decision note is required")
    row.status = "active" if action == "approve" else "rejected"
    row.decided_by, row.decided_at, row.decision_note = actor, utc_now(), note.strip()
    row.revision += 1
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"cash_account.{action}",
        actor=actor, resource_key=row.account_key, detail=f"{row.account_code}; {row.status}; revision {row.revision}"))
    session.commit()
    return row


def _payment_amount_for_line(line: OperationalStatementLine) -> tuple[str, Decimal]:
    if line.credit_amount > 0:
        return "customer_receipt", _money(line.credit_amount)
    return "supplier_payment", _money(line.debit_amount)


def _suggest_payment(session: Session, account: OperationalCashAccount,
                     line: OperationalStatementLine) -> OperationalPayment | None:
    payment_type, amount = _payment_amount_for_line(line)
    used_ids = select(OperationalStatementLine.matched_payment_id).where(
        OperationalStatementLine.matched_payment_id.is_not(None))
    query = select(OperationalPayment).where(
        OperationalPayment.payment_type == payment_type,
        OperationalPayment.amount == amount,
        OperationalPayment.payment_date == line.transaction_date,
        OperationalPayment.cash_bank_account_code == account.account_code,
        OperationalPayment.status == "approved",
        OperationalPayment.id.not_in(used_ids),
    )
    candidates = list(session.scalars(query.order_by(OperationalPayment.id)))
    if len(candidates) == 1:
        return candidates[0]
    reference = (line.reference or "").strip().casefold()
    if reference:
        exact = [row for row in candidates if (row.reference_no or "").strip().casefold() == reference]
        if len(exact) == 1:
            return exact[0]
    return None


def create_statement_batch(session: Session, *, account: OperationalCashAccount,
                           statement_reference: str, statement_start: date, statement_end: date,
                           opening_balance, closing_balance, source_file_name: str,
                           actor: str, lines: list[dict]) -> OperationalStatementBatch:
    if account.status != "active" or account.account_type != "bank":
        raise ValueError("Statements can be imported only for an approved bank account")
    if statement_end < statement_start or not lines:
        raise ValueError("A valid statement period and at least one line are required")
    external_ids: set[str] = set()
    prepared: list[dict] = []
    for number, raw in enumerate(lines, 1):
        external_id = str(raw["external_id"]).strip()
        debit, credit = _money(raw.get("debit_amount", 0)), _money(raw.get("credit_amount", 0))
        tx_date = raw["transaction_date"]
        if not external_id or external_id.casefold() in external_ids:
            raise ValueError("Every statement line requires a unique external id")
        if tx_date < statement_start or tx_date > statement_end:
            raise ValueError(f"Statement line {external_id} is outside the statement period")
        if (debit > 0) == (credit > 0):
            raise ValueError(f"Statement line {external_id} must contain either a debit or a credit")
        external_ids.add(external_id.casefold())
        prepared.append({"line_no": number, "external_id": external_id,
            "transaction_date": tx_date, "value_date": raw.get("value_date"),
            "reference": (raw.get("reference") or "").strip() or None,
            "description": str(raw.get("description") or "").strip() or "Bank statement transaction",
            "debit_amount": debit, "credit_amount": credit, "status": "unmatched"})
    opening, closing = _money(opening_balance), _money(closing_balance)
    debits = sum((row["debit_amount"] for row in prepared), Decimal("0.00"))
    credits = sum((row["credit_amount"] for row in prepared), Decimal("0.00"))
    if _money(opening + credits - debits) != closing:
        raise ValueError("Statement opening plus credits minus debits does not equal closing balance")
    checksum_source = json.dumps({"account": account.account_code, "reference": statement_reference.strip(),
        "start": statement_start, "end": statement_end, "opening": opening, "closing": closing,
        "lines": prepared}, default=str, sort_keys=True, separators=(",", ":"))
    checksum = hashlib.sha256(checksum_source.encode()).hexdigest()
    if session.scalar(select(OperationalStatementBatch.id).where(
            (OperationalStatementBatch.source_checksum == checksum) |
            ((OperationalStatementBatch.account_id == account.id) &
             (OperationalStatementBatch.statement_reference == statement_reference.strip())))):
        raise ValueError("This statement file or account reference has already been imported")
    batch = OperationalStatementBatch(batch_key=str(uuid.uuid4()), account_id=account.id,
        statement_reference=statement_reference.strip(), statement_start=statement_start,
        statement_end=statement_end, opening_balance=opening, closing_balance=closing,
        total_debits=debits, total_credits=credits, source_file_name=source_file_name.strip(),
        source_checksum=checksum, status="draft", created_by=actor, state_changed_by=actor)
    for raw in prepared:
        batch.lines.append(OperationalStatementLine(**raw))
    session.add(batch)
    session.flush()
    for line in batch.lines:
        suggestion = _suggest_payment(session, account, line)
        if suggestion:
            line.suggested_payment_id = suggestion.id
            line.match_basis = "exact approved payment: account + direction + amount + date"
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="bank_statement.imported",
        actor=actor, resource_key=batch.batch_key,
        detail=f"{account.account_code}; {len(prepared)} lines; balanced; checksum {checksum}; no posting"))
    session.commit()
    return batch


def match_statement_line(session: Session, batch: OperationalStatementBatch,
                         line: OperationalStatementLine, payment: OperationalPayment,
                         *, actor: str) -> OperationalStatementLine:
    if batch.status != "draft" or line.status != "unmatched":
        raise ValueError("Only an unmatched line in a draft statement can be matched")
    expected_type, expected_amount = _payment_amount_for_line(line)
    if payment.status != "approved" or payment.payment_type != expected_type:
        raise ValueError("The payment direction or approval state does not match the statement line")
    if payment.cash_bank_account_code != batch.account.account_code or _money(payment.amount) != expected_amount:
        raise ValueError("The payment account or amount does not match the statement line")
    duplicate = session.scalar(select(OperationalStatementLine.id).where(
        OperationalStatementLine.matched_payment_id == payment.id,
        OperationalStatementLine.id != line.id))
    if duplicate:
        raise ValueError("This receipt/payment is already matched to another statement line")
    line.status, line.matched_payment_id = "matched", payment.id
    line.match_basis = "confirmed payment match"
    line.resolved_by, line.resolved_at = actor, utc_now()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="bank_statement.line_matched",
        actor=actor, resource_key=batch.batch_key,
        detail=f"line {line.line_no}; {payment.payment_no}; AED {expected_amount}"))
    session.commit()
    return line


def explain_statement_line(session: Session, batch: OperationalStatementBatch,
                           line: OperationalStatementLine, *, category: str,
                           reason: str, actor: str) -> OperationalStatementLine:
    if batch.status != "draft" or line.status != "unmatched":
        raise ValueError("Only an unmatched line in a draft statement can be explained")
    if category not in {"bank_fee", "bank_interest", "timing_difference", "bank_error", "other"}:
        raise ValueError("Statement exception category is invalid")
    if len(reason.strip()) < 5:
        raise ValueError("A clear exception reason is required")
    line.status, line.exception_category, line.exception_reason = "exception", category, reason.strip()
    line.resolved_by, line.resolved_at = actor, utc_now()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="bank_statement.line_explained",
        actor=actor, resource_key=batch.batch_key, detail=f"line {line.line_no}; {category}; no posting"))
    session.commit()
    return line


def transition_statement_batch(session: Session, batch: OperationalStatementBatch, *, action: str,
                               expected_revision: int, actor: str, note: str | None = None) -> OperationalStatementBatch:
    transitions = {("draft", "submit"): "submitted", ("submitted", "approve"): "approved",
                   ("submitted", "reject"): "rejected"}
    if batch.revision != expected_revision:
        raise ValueError(f"Statement revision conflict; current revision is {batch.revision}")
    target = transitions.get((batch.status, action))
    if not target:
        raise ValueError(f"Action {action} is not allowed from {batch.status}")
    if action == "submit" and any(line.status == "unmatched" for line in batch.lines):
        raise ValueError("Every statement line must be matched or explained before submission")
    if action in {"approve", "reject"} and batch.created_by == actor:
        raise PermissionError("Maker-checker control prevents the importer from deciding this reconciliation")
    if action in {"approve", "reject"} and len((note or "").strip()) < 5:
        raise ValueError("A reconciliation decision note is required")
    batch.status = target
    batch.revision += 1
    batch.state_changed_by, batch.state_changed_at = actor, utc_now()
    if action in {"approve", "reject"}:
        batch.approved_by, batch.approval_note = actor, note.strip()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"bank_reconciliation.{action}",
        actor=actor, resource_key=batch.batch_key,
        detail=f"{batch.statement_reference}; {target}; revision {batch.revision}; no posting"))
    session.commit()
    return batch


def rehearse_reconciliation(session: Session, batch: OperationalStatementBatch, *, actor: str) -> dict:
    if batch.status != "approved":
        raise ValueError("Only an approved reconciliation can be rehearsed")
    existing = session.scalar(select(OperationalReconciliationRehearsal).where(
        OperationalReconciliationRehearsal.batch_id == batch.id,
        OperationalReconciliationRehearsal.batch_revision == batch.revision))
    if existing:
        result = json.loads(existing.result_json)
        result["idempotent_replay"] = True
        return result
    adjustment_journal = []
    for line in batch.lines:
        if line.exception_category == "bank_fee":
            adjustment_journal.extend([
                {"account": "Bank Charges", "debit": str(line.debit_amount), "credit": "0.00", "statement_line": line.line_no},
                {"account": batch.account.gl_account_code, "debit": "0.00", "credit": str(line.debit_amount), "statement_line": line.line_no},
            ])
        elif line.exception_category == "bank_interest":
            adjustment_journal.extend([
                {"account": batch.account.gl_account_code, "debit": str(line.credit_amount), "credit": "0.00", "statement_line": line.line_no},
                {"account": "Interest Income", "debit": "0.00", "credit": str(line.credit_amount), "statement_line": line.line_no},
            ])
    result = {"batch_key": batch.batch_key, "statement_reference": batch.statement_reference,
        "account_code": batch.account.account_code, "opening_balance": str(batch.opening_balance),
        "closing_balance": str(batch.closing_balance), "total_debits": str(batch.total_debits),
        "total_credits": str(batch.total_credits),
        "matched_lines": sum(line.status == "matched" for line in batch.lines),
        "exception_lines": sum(line.status == "exception" for line in batch.lines),
        "adjustment_journal": adjustment_journal, "posting_enabled": False,
        "posting_performed": False, "idempotent_replay": False}
    source = json.dumps(result, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(source.encode()).hexdigest()
    result["fingerprint"] = fingerprint
    rehearsal = OperationalReconciliationRehearsal(rehearsal_key=str(uuid.uuid4()),
        batch_id=batch.id, batch_revision=batch.revision, fingerprint=fingerprint,
        result_json=json.dumps(result, sort_keys=True), posting_enabled=False, generated_by=actor)
    session.add(rehearsal)
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="bank_reconciliation.rehearsed",
        actor=actor, resource_key=batch.batch_key,
        detail=f"{len(batch.lines)} lines; {len(adjustment_journal)} proposed journal lines; no posting"))
    session.commit()
    return result


def statement_payload(session: Session, batch: OperationalStatementBatch) -> dict:
    rehearsal = session.scalar(select(OperationalReconciliationRehearsal).where(
        OperationalReconciliationRehearsal.batch_id == batch.id).order_by(
            OperationalReconciliationRehearsal.generated_at.desc()))
    return {"batch_key": batch.batch_key, "account_key": batch.account.account_key,
        "account_code": batch.account.account_code, "account_name": batch.account.account_name,
        "statement_reference": batch.statement_reference, "statement_start": batch.statement_start,
        "statement_end": batch.statement_end, "opening_balance": batch.opening_balance,
        "closing_balance": batch.closing_balance, "total_debits": batch.total_debits,
        "total_credits": batch.total_credits, "source_file_name": batch.source_file_name,
        "source_checksum": batch.source_checksum, "status": batch.status,
        "created_by": batch.created_by, "approved_by": batch.approved_by,
        "approval_note": batch.approval_note, "revision": batch.revision,
        "rehearsal": json.loads(rehearsal.result_json) if rehearsal else None,
        "lines": [{"line_no": line.line_no, "external_id": line.external_id,
            "transaction_date": line.transaction_date, "value_date": line.value_date,
            "reference": line.reference, "description": line.description,
            "debit_amount": line.debit_amount, "credit_amount": line.credit_amount,
            "status": line.status, "suggested_payment_key": line.suggested_payment.payment_key if line.suggested_payment else None,
            "suggested_payment_no": line.suggested_payment.payment_no if line.suggested_payment else None,
            "matched_payment_key": line.matched_payment.payment_key if line.matched_payment else None,
            "matched_payment_no": line.matched_payment.payment_no if line.matched_payment else None,
            "match_basis": line.match_basis, "exception_category": line.exception_category,
            "exception_reason": line.exception_reason, "resolved_by": line.resolved_by}
            for line in batch.lines]}


def cash_management_payload(session: Session) -> dict:
    accounts = list(session.scalars(select(OperationalCashAccount).order_by(
        OperationalCashAccount.account_code)))
    batches = list(session.scalars(select(OperationalStatementBatch).order_by(
        OperationalStatementBatch.created_at.desc())))
    return {"posting_enabled": False,
        "accounts": [cash_account_payload(row) for row in accounts],
        "statements": [statement_payload(session, row) for row in batches],
        "controls": {"accounts": len(accounts),
            "active_accounts": sum(row.status == "active" for row in accounts),
            "pending_accounts": sum(row.status == "pending" for row in accounts),
            "statement_batches": len(batches),
            "pending_reconciliations": sum(row.status == "submitted" for row in batches),
            "unmatched_lines": session.scalar(select(func.count(OperationalStatementLine.id)).where(
                OperationalStatementLine.status == "unmatched")) or 0,
            "approved_reconciliations": sum(row.status == "approved" for row in batches)}}
