"""Governed settlement of posted target-ERP customer-credit liabilities."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .operational import MONEY, OperationalAuditEvent, OperationalBase, OperationalFiscalPeriod, utc_now
from .sales_returns import OperationalSalesReturn
from .customer_price_credits import OperationalCustomerPriceCredit


class OperationalCustomerRefund(OperationalBase):
    __tablename__ = "operational_customer_refunds"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_customer_refund_amount"),
        CheckConstraint("(sales_return_id IS NOT NULL AND price_credit_id IS NULL) OR "
                        "(sales_return_id IS NULL AND price_credit_id IS NOT NULL)",
                        name="ck_customer_refund_one_credit_source"),
        CheckConstraint("status IN ('draft','submitted','approved','cancelled','posted','reversed')",
                        name="ck_customer_refund_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    refund_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    refund_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    sales_return_id: Mapped[int | None] = mapped_column(ForeignKey("operational_sales_returns.id"), index=True)
    price_credit_id: Mapped[int | None] = mapped_column(ForeignKey("operational_customer_price_credits.id"), index=True)
    customer_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False)
    cash_account_code: Mapped[str] = mapped_column(String(80), nullable=False)
    refund_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    state_changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    state_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalCustomerRefundRecovery(OperationalBase):
    """Bank-confirmed repayment of a posted refund; reopens the original credit liability."""
    __tablename__ = "operational_customer_refund_recoveries"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_refund_recovery_amount"),
        CheckConstraint("status IN ('draft','submitted','approved','cancelled','posted')",
                        name="ck_refund_recovery_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recovery_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    recovery_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    refund_id: Mapped[int] = mapped_column(ForeignKey("operational_customer_refunds.id"), nullable=False, index=True)
    customer_code: Mapped[str] = mapped_column(String(80), nullable=False)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False)
    cash_account_code: Mapped[str] = mapped_column(String(80), nullable=False)
    recovery_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    state_changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    state_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


def posted_refund_liability(session: Session, source: OperationalSalesReturn | OperationalCustomerPriceCredit) -> Decimal:
    from .posting_integration import OperationalIntegratedJournalLine, OperationalIntegratedPostingBatch

    resource_type = "sales_return" if isinstance(source, OperationalSalesReturn) else "customer_price_credit"
    resource_key = source.return_key if isinstance(source, OperationalSalesReturn) else source.credit_key
    batch = session.scalar(select(OperationalIntegratedPostingBatch).where(
        OperationalIntegratedPostingBatch.resource_type == resource_type,
        OperationalIntegratedPostingBatch.resource_key == resource_key,
        OperationalIntegratedPostingBatch.batch_kind == "posting",
        OperationalIntegratedPostingBatch.status == "posted"))
    if source.status != "posted" or batch is None:
        raise ValueError("Refunds require a posted target-ERP credit note")
    return Decimal(session.scalar(select(func.coalesce(func.sum(
        OperationalIntegratedJournalLine.credit), 0)).where(
        OperationalIntegratedJournalLine.batch_id == batch.id,
        OperationalIntegratedJournalLine.account_code == "2130")) or 0)


def refund_available(session: Session, source: OperationalSalesReturn | OperationalCustomerPriceCredit,
                     *, exclude_refund_id: int | None = None) -> Decimal:
    liability = posted_refund_liability(session, source)
    source_filter = (OperationalCustomerRefund.sales_return_id == source.id if isinstance(source, OperationalSalesReturn)
                     else OperationalCustomerRefund.price_credit_id == source.id)
    query = select(func.coalesce(func.sum(OperationalCustomerRefund.amount), 0)).where(
        source_filter,
        OperationalCustomerRefund.status.in_(("submitted", "approved", "posted")))
    if exclude_refund_id is not None:
        query = query.where(OperationalCustomerRefund.id != exclude_refund_id)
    reserved = Decimal(session.scalar(query) or 0)
    recovered = Decimal(session.scalar(select(func.coalesce(func.sum(
        OperationalCustomerRefundRecovery.amount), 0)).join(
        OperationalCustomerRefund,
        OperationalCustomerRefund.id == OperationalCustomerRefundRecovery.refund_id).where(
        source_filter, OperationalCustomerRefundRecovery.status == "posted")) or 0)
    return max(Decimal("0.00"), liability - reserved + recovered)


def create_refund(session: Session, *, returned: OperationalSalesReturn | None = None,
                  price_credit: OperationalCustomerPriceCredit | None = None,
                  cash_account_code: str, refund_date: date, amount: Decimal,
                  actor: str, notes: str | None = None) -> OperationalCustomerRefund:
    if (returned is None) == (price_credit is None):
        raise ValueError("Exactly one posted credit source is required")
    if returned is not None and returned.original_invoice_origin != "target_erp":
        raise ValueError("Only target-ERP credit notes support customer refunds")
    source = returned if returned is not None else price_credit
    value = Decimal(amount)
    if value <= 0 or value != value.quantize(MONEY):
        raise ValueError("Refund amount must be positive AED cents")
    if refund_date < (returned.return_date if returned is not None else price_credit.credit_date):
        raise ValueError("Refund date cannot precede the credit note")
    if value > refund_available(session, source):
        raise ValueError("Refund exceeds the available posted credit-note liability")
    key = str(uuid.uuid4())
    row = OperationalCustomerRefund(refund_key=key, refund_no=f"RF-{key[:8].upper()}",
        sales_return_id=returned.id if returned is not None else None,
        price_credit_id=price_credit.id if price_credit is not None else None,
        customer_code=source.customer_code,
        location_code=source.location_code, cash_account_code=cash_account_code,
        refund_date=refund_date, amount=value, status="draft", created_by=actor,
        state_changed_by=actor, notes=notes)
    session.add(row)
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="customer_refund.created",
        actor=actor, resource_key=key, detail=f"{row.refund_no}; AED {value}; no cash movement"))
    session.commit()
    return row


def transition_refund(session: Session, refund: OperationalCustomerRefund, *, expected_revision: int,
                      action: str, actor: str, note: str | None = None) -> OperationalCustomerRefund:
    transitions = {("draft", "submit"): "submitted", ("draft", "cancel"): "cancelled",
                   ("submitted", "cancel"): "cancelled", ("submitted", "approve"): "approved"}
    if refund.revision != expected_revision:
        raise ValueError(f"Refund revision conflict; current revision is {refund.revision}")
    target = transitions.get((refund.status, action))
    if target is None:
        raise ValueError(f"Action {action} is not allowed from {refund.status}")
    if action == "approve" and refund.created_by == actor:
        raise PermissionError("Maker-checker control prevents the refund creator from approving")
    if action == "approve" and len((note or "").strip()) < 5:
        raise ValueError("An independent refund-approval reason is required")
    if action == "submit":
        source = (session.scalar(select(OperationalSalesReturn).where(
            OperationalSalesReturn.id == refund.sales_return_id).with_for_update())
            if refund.sales_return_id is not None else
            session.scalar(select(OperationalCustomerPriceCredit).where(
                OperationalCustomerPriceCredit.id == refund.price_credit_id).with_for_update()))
        if not source or refund.amount > refund_available(session, source, exclude_refund_id=refund.id):
            raise ValueError("Refund liability is no longer available")
    refund.status, refund.revision = target, refund.revision + 1
    refund.state_changed_by, refund.state_changed_at = actor, utc_now()
    if action == "approve":
        refund.approved_by, refund.approved_at = actor, utc_now()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"customer_refund.{action}",
        actor=actor, resource_key=refund.refund_key, detail=f"{target}; revision {refund.revision}; no cash movement"))
    session.commit()
    return refund


def refund_posting_plan(session: Session, refund: OperationalCustomerRefund) -> dict:
    from .cash_management import OperationalCashAccount, OperationalStatementLine, OperationalStatementBatch

    if refund.status != "approved":
        raise ValueError("Only an independently approved refund can be posted")
    source = (session.scalar(select(OperationalSalesReturn).where(
        OperationalSalesReturn.id == refund.sales_return_id).with_for_update())
        if refund.sales_return_id is not None else
        session.scalar(select(OperationalCustomerPriceCredit).where(
            OperationalCustomerPriceCredit.id == refund.price_credit_id).with_for_update()))
    if not source or source.customer_code != refund.customer_code:
        raise ValueError("Refund credit-note linkage is invalid")
    if refund.amount > refund_available(session, source, exclude_refund_id=refund.id):
        raise ValueError("Refund exceeds its available posted credit-note liability")
    account = session.scalar(select(OperationalCashAccount).where(
        OperationalCashAccount.account_code == refund.cash_account_code,
        OperationalCashAccount.status == "active", OperationalCashAccount.account_type == "bank"))
    if account is None or account.location_code not in (refund.location_code, "MAIN") or account.currency_code != "AED":
        raise ValueError("An active AED bank account in the refund location is required")
    line = session.scalar(select(OperationalStatementLine).join(OperationalStatementBatch).where(
        OperationalStatementLine.matched_refund_id == refund.id,
        OperationalStatementLine.status == "matched",
        OperationalStatementBatch.account_id == account.id,
        OperationalStatementBatch.status == "approved").with_for_update())
    if line is None or Decimal(line.debit_amount) != Decimal(refund.amount) or line.credit_amount != 0:
        raise ValueError("A matching imported bank debit is required before refund payout posting")
    if line.transaction_date != refund.refund_date:
        raise ValueError("Refund date must match the approved bank debit date")
    period = session.scalar(select(OperationalFiscalPeriod).where(
        OperationalFiscalPeriod.starts_on <= line.transaction_date,
        OperationalFiscalPeriod.ends_on >= line.transaction_date,
        OperationalFiscalPeriod.status == "open",
        OperationalFiscalPeriod.rehearsal_enabled.is_(True)))
    if period is None:
        raise ValueError("Refund bank date is outside an open fiscal period")
    journal = [{"account": "2130", "debit": refund.amount, "credit": Decimal("0.00")},
               {"account": account.gl_account_code, "debit": Decimal("0.00"), "credit": refund.amount}]
    subledger = [{"entry_type": "customer_refund_paid", "party_code": refund.customer_code,
                  "source_type": "customer_price_credit" if refund.price_credit_id else "sales_credit_note",
                  "source_reference_key": (source.credit_no if refund.price_credit_id else source.credit_note.credit_note_no),
                  "amount": -refund.amount}]
    evidence = {"refund_key": refund.refund_key, "revision": refund.revision,
        "credit_note": (source.credit_no if refund.price_credit_id else source.credit_note.credit_note_no),
        "amount": str(refund.amount),
        "bank_account": account.account_code, "bank_gl": account.gl_account_code,
        "statement_checksum": line.batch.source_checksum, "statement_line": line.external_id,
        "bank_date": line.transaction_date.isoformat(), "period": period.period_key}
    fingerprint = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
    return {"journal": journal, "subledger": subledger, "movements": [],
        "period_key": period.period_key, "posting_fingerprint": fingerprint,
        "idempotency_key": f"customer-refund:{refund.refund_key}:{refund.revision}:{fingerprint[:20]}",
        "bank_evidence": evidence, "debit": refund.amount, "credit": refund.amount}


def recovery_available(session: Session, refund: OperationalCustomerRefund,
                       *, exclude_recovery_id: int | None = None) -> Decimal:
    if refund.status != "posted":
        raise ValueError("Only a posted bank-confirmed refund can be recovered")
    query = select(func.coalesce(func.sum(OperationalCustomerRefundRecovery.amount), 0)).where(
        OperationalCustomerRefundRecovery.refund_id == refund.id,
        OperationalCustomerRefundRecovery.status.in_(("submitted", "approved", "posted")))
    if exclude_recovery_id is not None:
        query = query.where(OperationalCustomerRefundRecovery.id != exclude_recovery_id)
    return max(Decimal("0.00"), Decimal(refund.amount) - Decimal(session.scalar(query) or 0))


def create_recovery(session: Session, *, refund: OperationalCustomerRefund,
                    recovery_date: date, amount: Decimal, reason: str,
                    actor: str) -> OperationalCustomerRefundRecovery:
    value = Decimal(amount)
    if value <= 0 or value != value.quantize(MONEY) or value > recovery_available(session, refund):
        raise ValueError("Recovery must be positive AED cents within the unrecovered payout")
    if recovery_date < refund.refund_date or len(reason.strip()) < 5:
        raise ValueError("Recovery date and reason must follow the original payout")
    key = str(uuid.uuid4())
    row = OperationalCustomerRefundRecovery(recovery_key=key,
        recovery_no=f"RRC-{key[:8].upper()}", refund_id=refund.id,
        customer_code=refund.customer_code, location_code=refund.location_code,
        cash_account_code=refund.cash_account_code, recovery_date=recovery_date,
        amount=value, reason=reason.strip(), created_by=actor, state_changed_by=actor)
    session.add(row)
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()),
        event_type="customer_refund_recovery.created", actor=actor,
        resource_key=key, detail=f"{row.recovery_no}; refund {refund.refund_no}; no bank posting"))
    session.commit()
    return row


def transition_recovery(session: Session, recovery: OperationalCustomerRefundRecovery, *,
                        expected_revision: int, action: str, actor: str,
                        note: str | None = None) -> OperationalCustomerRefundRecovery:
    target = {("draft", "submit"): "submitted", ("draft", "cancel"): "cancelled",
              ("submitted", "approve"): "approved", ("submitted", "cancel"): "cancelled"}.get(
                  (recovery.status, action))
    if target is None or recovery.revision != expected_revision:
        raise ValueError("Recovery state or revision conflict")
    if action == "approve" and recovery.created_by == actor:
        raise PermissionError("Maker-checker prevents recovery self-approval")
    if action == "approve" and len((note or "").strip()) < 5:
        raise ValueError("Independent recovery approval reason is required")
    if action == "submit":
        refund = session.scalar(select(OperationalCustomerRefund).where(
            OperationalCustomerRefund.id == recovery.refund_id).with_for_update())
        if refund is None or recovery.amount > recovery_available(session, refund, exclude_recovery_id=recovery.id):
            raise ValueError("Original payout has insufficient recoverable balance")
    recovery.status, recovery.revision = target, recovery.revision + 1
    recovery.state_changed_by, recovery.state_changed_at = actor, utc_now()
    if action == "approve":
        recovery.approved_by = actor
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()),
        event_type=f"customer_refund_recovery.{action}", actor=actor,
        resource_key=recovery.recovery_key, detail=f"{target}; revision {recovery.revision}"))
    session.commit()
    return recovery


def recovery_posting_plan(session: Session, recovery: OperationalCustomerRefundRecovery) -> dict:
    from .cash_management import OperationalCashAccount, OperationalStatementBatch, OperationalStatementLine

    if recovery.status != "approved":
        raise ValueError("Only an independently approved recovery can post")
    refund = session.scalar(select(OperationalCustomerRefund).where(
        OperationalCustomerRefund.id == recovery.refund_id).with_for_update())
    if (refund is None or recovery.customer_code != refund.customer_code or
            recovery.amount > recovery_available(session, refund, exclude_recovery_id=recovery.id)):
        raise ValueError("Recovery exceeds the bank-confirmed original refund")
    account = session.scalar(select(OperationalCashAccount).where(
        OperationalCashAccount.account_code == recovery.cash_account_code,
        OperationalCashAccount.status == "active",
        OperationalCashAccount.account_type == "bank",
        OperationalCashAccount.currency_code == "AED"))
    if account is None or account.location_code not in (recovery.location_code, "MAIN"):
        raise ValueError("Approved AED bank account is required for recovery")
    line = session.scalar(select(OperationalStatementLine).join(OperationalStatementBatch).where(
        OperationalStatementLine.matched_recovery_id == recovery.id,
        OperationalStatementLine.status == "matched",
        OperationalStatementBatch.account_id == account.id,
        OperationalStatementBatch.status == "approved").with_for_update())
    if (line is None or Decimal(line.credit_amount) != Decimal(recovery.amount)
            or line.debit_amount != 0 or line.transaction_date != recovery.recovery_date):
        raise ValueError("An independently approved matching bank credit is required")
    period = session.scalar(select(OperationalFiscalPeriod).where(
        OperationalFiscalPeriod.starts_on <= recovery.recovery_date,
        OperationalFiscalPeriod.ends_on >= recovery.recovery_date,
        OperationalFiscalPeriod.status == "open",
        OperationalFiscalPeriod.rehearsal_enabled.is_(True)))
    if period is None:
        raise ValueError("Recovery bank date is outside an open fiscal period")
    evidence = {"recovery_key": recovery.recovery_key, "revision": recovery.revision,
        "refund_key": refund.refund_key, "amount": str(recovery.amount),
        "bank_account": account.account_code, "bank_gl": account.gl_account_code,
        "statement_checksum": line.batch.source_checksum,
        "statement_line": line.external_id, "date": recovery.recovery_date.isoformat(),
        "period": period.period_key}
    fingerprint = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
    return {"journal": [
        {"account": account.gl_account_code, "debit": recovery.amount, "credit": Decimal("0")},
        {"account": "2130", "debit": Decimal("0"), "credit": recovery.amount}],
        "subledger": [{"entry_type": "customer_refund_recovered",
            "party_code": recovery.customer_code, "source_type": "customer_refund",
            "source_reference_key": refund.refund_no, "amount": recovery.amount}],
        "movements": [], "period_key": period.period_key,
        "posting_fingerprint": fingerprint,
        "idempotency_key": f"refund-recovery:{recovery.recovery_key}:{recovery.revision}:{fingerprint[:20]}",
        "bank_evidence": evidence, "debit": recovery.amount, "credit": recovery.amount}
