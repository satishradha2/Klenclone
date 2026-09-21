from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .operational import (
    MONEY, OperationalAuditEvent, OperationalBase, OperationalFiscalPeriod,
    OperationalJournalBatch, OperationalJournalLine, OperationalStockPosition, utc_now,
)
from .vat_control import OperationalVatPeriod


class OperationalPeriodClose(OperationalBase):
    __tablename__ = "operational_period_closes"
    __table_args__ = (
        UniqueConstraint("fiscal_period_id", name="uq_period_close_fiscal_period"),
        CheckConstraint("status IN ('draft','submitted','approved','rejected','cancelled')", name="ck_period_close_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    close_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    close_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    fiscal_period_id: Mapped[int] = mapped_column(ForeignKey("operational_fiscal_periods.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    checklist_json: Mapped[str | None] = mapped_column(Text)
    snapshot_json: Mapped[str | None] = mapped_column(Text)
    source_fingerprint: Mapped[str | None] = mapped_column(String(64))
    exception_note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    decision_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    submitted_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))

    fiscal_period: Mapped[OperationalFiscalPeriod] = relationship()
    adjustments: Mapped[list["OperationalCloseAdjustment"]] = relationship(
        back_populates="period_close", cascade="all, delete-orphan", order_by="OperationalCloseAdjustment.id")


class OperationalCloseAdjustment(OperationalBase):
    __tablename__ = "operational_close_adjustments"
    __table_args__ = (
        CheckConstraint("adjustment_type IN ('accrual','prepayment','fx_revaluation','inventory_valuation')", name="ck_close_adjustment_type"),
        CheckConstraint("status IN ('pending','approved','rejected','cancelled')", name="ck_close_adjustment_status"),
        CheckConstraint("amount > 0", name="ck_close_adjustment_amount"),
        CheckConstraint("debit_account <> credit_account", name="ck_close_adjustment_accounts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    adjustment_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    adjustment_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    period_close_id: Mapped[int] = mapped_column(ForeignKey("operational_period_closes.id"), nullable=False, index=True)
    adjustment_type: Mapped[str] = mapped_column(String(30), nullable=False)
    adjustment_date: Mapped[date] = mapped_column(Date, nullable=False)
    debit_account: Mapped[str] = mapped_column(String(120), nullable=False)
    credit_account: Mapped[str] = mapped_column(String(120), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    reversal_on: Mapped[date | None] = mapped_column(Date)
    evidence_reference: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    decision_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    period_close: Mapped[OperationalPeriodClose] = relationship(back_populates="adjustments")


class OperationalPeriodCloseRehearsal(OperationalBase):
    __tablename__ = "operational_period_close_rehearsals"
    __table_args__ = (UniqueConstraint("period_close_id", "close_revision", name="uq_period_close_rehearsal_revision"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rehearsal_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    period_close_id: Mapped[int] = mapped_column(ForeignKey("operational_period_closes.id"), nullable=False, index=True)
    close_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    journal_json: Mapped[str] = mapped_column(Text, nullable=False)
    debit_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    credit_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    posting_performed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    period_lock_performed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    generated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    generated_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(MONEY, rounding=ROUND_HALF_UP)


def create_period_close(session: Session, *, fiscal_period_key: str, actor: str) -> OperationalPeriodClose:
    period = session.scalar(select(OperationalFiscalPeriod).where(OperationalFiscalPeriod.period_key == fiscal_period_key))
    if not period:
        raise ValueError("Fiscal period not found")
    if period.status != "open" or not period.rehearsal_enabled:
        raise ValueError("Fiscal period must be open and rehearsal-enabled")
    if session.scalar(select(OperationalPeriodClose).where(OperationalPeriodClose.fiscal_period_id == period.id)):
        raise ValueError("A close package already exists for this fiscal period")
    key = str(uuid.uuid4())
    row = OperationalPeriodClose(close_key=key, close_no=f"CLOSE-{period.period_key}",
        fiscal_period_id=period.id, status="draft", created_by=actor)
    session.add(row); session.flush()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="period_close.created",
        actor=actor, resource_key=row.close_key, detail=f"{row.close_no}; close rehearsal only"))
    session.commit()
    return row


def create_close_adjustment(session: Session, row: OperationalPeriodClose, *, adjustment_type: str,
                            adjustment_date: date, debit_account: str, credit_account: str,
                            amount, reversal_on: date | None, evidence_reference: str,
                            reason: str, actor: str) -> OperationalCloseAdjustment:
    if row.status != "draft":
        raise ValueError("Adjustments can only be added to a draft close package")
    if adjustment_type not in {"accrual", "prepayment", "fx_revaluation", "inventory_valuation"}:
        raise ValueError("Unsupported close adjustment type")
    if not row.fiscal_period.starts_on <= adjustment_date <= row.fiscal_period.ends_on:
        raise ValueError("Adjustment date must fall inside the fiscal period")
    if debit_account.strip().casefold() == credit_account.strip().casefold():
        raise ValueError("Debit and credit accounts must differ")
    value = _money(amount)
    if value <= 0:
        raise ValueError("Adjustment amount must be positive")
    if adjustment_type in {"accrual", "prepayment"} and (not reversal_on or reversal_on <= row.fiscal_period.ends_on):
        raise ValueError("Accrual and prepayment adjustments require a reversal date after period end")
    key = str(uuid.uuid4())
    adjustment = OperationalCloseAdjustment(adjustment_key=key,
        adjustment_no=f"CADJ-{key[:8].upper()}", period_close_id=row.id,
        adjustment_type=adjustment_type, adjustment_date=adjustment_date,
        debit_account=debit_account.strip(), credit_account=credit_account.strip(), amount=value,
        reversal_on=reversal_on, evidence_reference=evidence_reference.strip(), reason=reason.strip(),
        status="pending", created_by=actor)
    session.add(adjustment); session.flush()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="period_close.adjustment_created",
        actor=actor, resource_key=adjustment.adjustment_key,
        detail=f"{adjustment.adjustment_no}; {adjustment_type}; AED {value}; no posting"))
    session.commit()
    return adjustment


def decide_close_adjustment(session: Session, row: OperationalCloseAdjustment, *, action: str,
                            expected_revision: int, note: str, actor: str) -> OperationalCloseAdjustment:
    if row.revision != expected_revision or row.status != "pending":
        raise ValueError("Adjustment is no longer pending at the expected revision")
    if action == "cancel":
        if actor != row.created_by: raise PermissionError("Only the maker may cancel this adjustment")
        row.status = "cancelled"
    elif action in {"approve", "reject"}:
        if actor == row.created_by: raise PermissionError("Maker cannot approve their own close adjustment")
        if len(note.strip()) < 5: raise ValueError("Decision note must contain at least five characters")
        row.status, row.approved_by, row.decision_note = ("approved" if action == "approve" else "rejected"), actor, note.strip()
    else:
        raise ValueError("Unsupported adjustment action")
    row.revision += 1
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"period_close.adjustment_{action}",
        actor=actor, resource_key=row.adjustment_key, detail=f"{row.adjustment_no}; {row.status}; no posting"))
    session.commit(); return row


def _close_snapshot(session: Session, row: OperationalPeriodClose) -> tuple[list[dict], dict]:
    period = row.fiscal_period
    pending_adjustments = sum(item.status == "pending" for item in row.adjustments)
    approved_adjustments = [item for item in row.adjustments if item.status == "approved"]
    vat = session.scalar(select(OperationalVatPeriod).where(
        OperationalVatPeriod.starts_on <= period.starts_on,
        OperationalVatPeriod.ends_on >= period.ends_on,
        OperationalVatPeriod.status == "approved"))
    positions = list(session.scalars(select(OperationalStockPosition)))
    negative_positions = sum(_money(item.quantity_on_hand) < 0 for item in positions)
    inventory_value = _money(sum((Decimal(str(item.quantity_on_hand)) * Decimal(str(item.average_unit_cost)) for item in positions), Decimal("0")))
    journals = list(session.scalars(select(OperationalJournalBatch).where(
        func.date(OperationalJournalBatch.posted_at) >= period.starts_on,
        func.date(OperationalJournalBatch.posted_at) <= period.ends_on,
        OperationalJournalBatch.status == "posted")))
    imbalance = Decimal("0")
    for batch in journals:
        lines = session.scalars(select(OperationalJournalLine).where(OperationalJournalLine.batch_id == batch.id))
        imbalance += sum((_money(line.debit) - _money(line.credit) for line in lines), Decimal("0"))
    checklist = [
        {"control": "fiscal_period_open", "status": "pass", "detail": "Fiscal period is open and rehearsal-enabled"},
        {"control": "pending_close_adjustments", "status": "block" if pending_adjustments else "pass", "detail": f"{pending_adjustments} pending close adjustments"},
        {"control": "vat_return_approved", "status": "pass" if vat else "warning", "detail": vat.period_code if vat else "No approved VAT return covers the full fiscal period"},
        {"control": "inventory_negative_positions", "status": "warning" if negative_positions else "pass", "detail": f"{negative_positions} negative stock positions"},
        {"control": "permanent_journal_balance", "status": "pass" if _money(imbalance) == 0 else "block", "detail": f"AED {_money(imbalance)} difference across {len(journals)} posted batches"},
    ]
    snapshot = {"period_key": period.period_key, "starts_on": period.starts_on, "ends_on": period.ends_on,
        "approved_adjustments": len(approved_adjustments), "approved_adjustment_total": _money(sum((item.amount for item in approved_adjustments), Decimal("0"))),
        "stock_positions": len(positions), "inventory_value": inventory_value,
        "permanent_journal_batches": len(journals), "vat_period": vat.period_code if vat else None}
    return checklist, snapshot


def transition_period_close(session: Session, row: OperationalPeriodClose, *, action: str,
                            expected_revision: int, actor: str, note: str = "") -> OperationalPeriodClose:
    if row.revision != expected_revision:
        raise ValueError("Close package revision is stale")
    if action == "submit" and row.status == "draft":
        checklist, snapshot = _close_snapshot(session, row)
        if any(item["status"] == "block" for item in checklist):
            raise ValueError("Blocking close controls must be resolved before submission")
        if any(item["status"] == "warning" for item in checklist) and len(note.strip()) < 5:
            raise ValueError("Document an exception note for close warnings")
        row.checklist_json, row.snapshot_json = json.dumps(checklist, default=str, sort_keys=True), json.dumps(snapshot, default=str, sort_keys=True)
        row.source_fingerprint = hashlib.sha256((row.checklist_json + row.snapshot_json).encode()).hexdigest()
        row.exception_note, row.status, row.submitted_at = note.strip() or None, "submitted", utc_now()
    elif action in {"approve", "reject"} and row.status == "submitted":
        if actor == row.created_by: raise PermissionError("Maker cannot approve their own period close")
        if len(note.strip()) < 5: raise ValueError("Decision note must contain at least five characters")
        row.status, row.approved_by, row.decision_note = ("approved" if action == "approve" else "rejected"), actor, note.strip()
        row.approved_at = utc_now() if action == "approve" else None
    elif action == "cancel" and row.status == "draft":
        if actor != row.created_by: raise PermissionError("Only the maker may cancel this close package")
        row.status = "cancelled"
    else:
        raise ValueError("Invalid close package transition")
    row.revision += 1
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"period_close.{action}",
        actor=actor, resource_key=row.close_key, detail=f"{row.close_no}; {row.status}; period remains unlocked"))
    session.commit(); return row


def rehearse_period_close(session: Session, row: OperationalPeriodClose, *, actor: str) -> dict:
    if row.status != "approved" or not row.source_fingerprint:
        raise ValueError("Only an approved frozen close package can be rehearsed")
    existing = session.scalar(select(OperationalPeriodCloseRehearsal).where(
        OperationalPeriodCloseRehearsal.period_close_id == row.id,
        OperationalPeriodCloseRehearsal.close_revision == row.revision))
    if existing: return close_rehearsal_payload(existing, idempotent_replay=True)
    journal = []
    for item in row.adjustments:
        if item.status == "approved":
            journal.extend([{"adjustment_no": item.adjustment_no, "account": item.debit_account, "debit": str(_money(item.amount)), "credit": "0.00"},
                            {"adjustment_no": item.adjustment_no, "account": item.credit_account, "debit": "0.00", "credit": str(_money(item.amount))}])
    debit = _money(sum((Decimal(line["debit"]) for line in journal), Decimal("0")))
    credit = _money(sum((Decimal(line["credit"]) for line in journal), Decimal("0")))
    if debit != credit: raise ValueError("Close rehearsal journal is not balanced")
    rehearsal = OperationalPeriodCloseRehearsal(rehearsal_key=str(uuid.uuid4()),
        period_close_id=row.id, close_revision=row.revision, source_fingerprint=row.source_fingerprint,
        journal_json=json.dumps(journal, sort_keys=True), debit_total=debit, credit_total=credit,
        posting_enabled=False, posting_performed=False, period_lock_performed=False, generated_by=actor)
    session.add(rehearsal)
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="period_close.rehearsed",
        actor=actor, resource_key=row.close_key,
        detail=f"{row.close_no}; balanced AED {debit}; no posting; no period lock"))
    session.commit(); return close_rehearsal_payload(rehearsal)


def close_rehearsal_payload(row: OperationalPeriodCloseRehearsal, *, idempotent_replay: bool = False) -> dict:
    return {"rehearsal_key": row.rehearsal_key, "source_fingerprint": row.source_fingerprint,
        "journal": json.loads(row.journal_json), "debit_total": row.debit_total, "credit_total": row.credit_total,
        "posting_enabled": False, "posting_performed": False, "period_lock_performed": False,
        "idempotent_replay": idempotent_replay}


def close_adjustment_payload(row: OperationalCloseAdjustment) -> dict:
    return {"adjustment_key": row.adjustment_key, "adjustment_no": row.adjustment_no,
        "adjustment_type": row.adjustment_type, "adjustment_date": row.adjustment_date,
        "debit_account": row.debit_account, "credit_account": row.credit_account,
        "amount": row.amount, "reversal_on": row.reversal_on,
        "evidence_reference": row.evidence_reference, "reason": row.reason,
        "status": row.status, "created_by": row.created_by, "approved_by": row.approved_by,
        "decision_note": row.decision_note, "revision": row.revision}


def period_close_payload(session: Session, row: OperationalPeriodClose) -> dict:
    rehearsal = session.scalar(select(OperationalPeriodCloseRehearsal).where(
        OperationalPeriodCloseRehearsal.period_close_id == row.id,
        OperationalPeriodCloseRehearsal.close_revision == row.revision))
    checklist, snapshot = _close_snapshot(session, row) if row.status == "draft" else (json.loads(row.checklist_json or "[]"), json.loads(row.snapshot_json or "{}"))
    return {"close_key": row.close_key, "close_no": row.close_no,
        "period_key": row.fiscal_period.period_key, "starts_on": row.fiscal_period.starts_on,
        "ends_on": row.fiscal_period.ends_on, "status": row.status,
        "checklist": checklist, "snapshot": snapshot, "source_fingerprint": row.source_fingerprint,
        "exception_note": row.exception_note, "created_by": row.created_by,
        "approved_by": row.approved_by, "decision_note": row.decision_note,
        "revision": row.revision, "adjustments": [close_adjustment_payload(item) for item in row.adjustments],
        "rehearsal": close_rehearsal_payload(rehearsal) if rehearsal else None,
        "posting_enabled": False, "period_lock_enabled": False}


def period_close_workspace_payload(session: Session) -> dict:
    periods = list(session.scalars(select(OperationalFiscalPeriod).order_by(OperationalFiscalPeriod.starts_on.desc())))
    closes = list(session.scalars(select(OperationalPeriodClose).order_by(OperationalPeriodClose.created_at.desc())))
    return {"periods": [{"period_key": item.period_key, "starts_on": item.starts_on,
                          "ends_on": item.ends_on, "status": item.status,
                          "rehearsal_enabled": item.rehearsal_enabled} for item in periods],
        "closes": [period_close_payload(session, item) for item in closes],
        "controls": {"packages": len(closes), "awaiting_approval": sum(item.status == "submitted" for item in closes),
            "pending_adjustments": session.scalar(select(func.count(OperationalCloseAdjustment.id)).where(OperationalCloseAdjustment.status == "pending")) or 0,
            "approved": sum(item.status == "approved" for item in closes),
            "rehearsals": session.scalar(select(func.count(OperationalPeriodCloseRehearsal.id))) or 0,
            "period_locks": 0, "permanent_postings": 0}}
