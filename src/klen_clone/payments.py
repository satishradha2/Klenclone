from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .operational import (MONEY, OperationalAuditEvent, OperationalBase,
                          OperationalFiscalPeriod, OperationalOpeningPartyBalance, utc_now)


class OperationalPayment(OperationalBase):
    __tablename__ = "operational_payments"
    __table_args__ = (
        CheckConstraint("payment_type IN ('customer_receipt','supplier_payment')", name="ck_payment_type"),
        CheckConstraint("payment_method IN ('cash','bank_transfer','card','cheque','other')", name="ck_payment_method"),
        CheckConstraint("status IN ('draft','submitted','approved','cancelled','posted','reversed')", name="ck_payment_status"),
        CheckConstraint("amount > 0 AND allocated_amount >= 0 AND unallocated_amount >= 0 AND allocated_amount + unallocated_amount = amount", name="ck_payment_totals"),
        CheckConstraint("posting_enabled = false", name="ck_payment_no_posting"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payment_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    payment_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    payment_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    party_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    party_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    payment_method: Mapped[str] = mapped_column(String(30), nullable=False)
    cash_bank_account_code: Mapped[str] = mapped_column(String(80), nullable=False)
    reference_no: Mapped[str | None] = mapped_column(String(160))
    currency_code: Mapped[str] = mapped_column(String(3), default="AED", nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    allocated_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    unallocated_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False, index=True)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    state_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    state_changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    allocations: Mapped[list["OperationalPaymentAllocation"]] = relationship(back_populates="payment", cascade="all, delete-orphan", order_by="OperationalPaymentAllocation.line_no")


class OperationalPaymentAllocation(OperationalBase):
    __tablename__ = "operational_payment_allocations"
    __table_args__ = (
        UniqueConstraint("payment_id", "line_no", name="uq_payment_allocation_line"),
        UniqueConstraint("payment_id", "source_type", "source_reference_key", name="uq_payment_allocation_source"),
        CheckConstraint("source_type IN ('invoice','opening_balance')", name="ck_payment_allocation_source_type"),
        CheckConstraint("source_outstanding_snapshot > 0 AND allocation_amount > 0", name="ck_payment_allocation_amounts"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("operational_payments.id", ondelete="CASCADE"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_reference_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    source_document_date: Mapped[date | None] = mapped_column(Date)
    source_outstanding_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    allocation_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    payment: Mapped[OperationalPayment] = relationship(back_populates="allocations")


class OperationalPaymentAllocationClaim(OperationalBase):
    __tablename__ = "operational_payment_allocation_claims"
    __table_args__ = (
        UniqueConstraint("payment_allocation_id", name="uq_payment_claim_allocation"),
        CheckConstraint("amount > 0", name="ck_payment_claim_amount"),
        CheckConstraint("status IN ('active','released','consumed')", name="ck_payment_claim_status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    payment_id: Mapped[int] = mapped_column(ForeignKey("operational_payments.id"), nullable=False, index=True)
    payment_allocation_id: Mapped[int] = mapped_column(ForeignKey("operational_payment_allocations.id"), nullable=False)
    party_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_reference_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OperationalPaymentWorkflowEvent(OperationalBase):
    __tablename__ = "operational_payment_workflow_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    payment_id: Mapped[int] = mapped_column(ForeignKey("operational_payments.id"), nullable=False, index=True)
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)


def _normalise_allocations(lines: list[dict], amount: Decimal) -> tuple[list[dict], Decimal]:
    seen: set[tuple[str, str]] = set()
    result = []
    for raw in lines:
        source_type = str(raw["source_type"])
        reference = str(raw["source_reference_key"]).strip()
        outstanding, allocated = _money(raw["source_outstanding_snapshot"]), _money(raw["allocation_amount"])
        if source_type not in {"invoice", "opening_balance"} or not reference:
            raise ValueError("Each allocation requires a valid invoice or opening-balance source")
        if outstanding <= 0 or allocated <= 0 or allocated > outstanding:
            raise ValueError(f"Allocation for {reference} must be positive and cannot exceed source outstanding")
        identity = (source_type, reference.casefold())
        if identity in seen:
            raise ValueError(f"Duplicate allocation source {reference}")
        seen.add(identity)
        result.append(dict(raw, source_type=source_type, source_reference_key=reference,
                           source_outstanding_snapshot=outstanding, allocation_amount=allocated))
    total = sum((row["allocation_amount"] for row in result), Decimal("0.00"))
    if total > amount:
        raise ValueError("Allocated amount cannot exceed the payment amount")
    return result, total


def _set_payment(payment: OperationalPayment, *, payment_type: str, party_code: str,
                 party_name_snapshot: str, location_code: str, payment_date: date,
                 payment_method: str, cash_bank_account_code: str, reference_no: str | None,
                 amount, notes: str | None, lines: list[dict]) -> None:
    if payment_type not in {"customer_receipt", "supplier_payment"}:
        raise ValueError("Payment type is invalid")
    if payment_method not in {"cash", "bank_transfer", "card", "cheque", "other"}:
        raise ValueError("Payment method is invalid")
    if payment_method in {"bank_transfer", "card", "cheque"} and not (reference_no or "").strip():
        raise ValueError("A payment reference is required for bank, card and cheque transactions")
    value = _money(amount)
    if value <= 0 or not cash_bank_account_code.strip():
        raise ValueError("Payment amount and cash/bank account are required")
    prepared, allocated = _normalise_allocations(lines, value)
    payment.payment_type = payment_type
    payment.party_code = party_code
    payment.party_name_snapshot = party_name_snapshot
    payment.location_code = location_code
    payment.payment_date = payment_date
    payment.payment_method = payment_method
    payment.cash_bank_account_code = cash_bank_account_code.strip()
    payment.reference_no = (reference_no or "").strip() or None
    payment.amount = value
    payment.allocated_amount = allocated
    payment.unallocated_amount = value - allocated
    payment.notes = notes
    payment.allocations.clear()
    for number, raw in enumerate(prepared, 1):
        payment.allocations.append(OperationalPaymentAllocation(line_no=number, **raw))


def create_payment(session: Session, *, actor: str, **values) -> OperationalPayment:
    key = str(uuid.uuid4())
    kind = values["payment_type"]
    payment = OperationalPayment(payment_key=key, payment_no=f"{'CR' if kind == 'customer_receipt' else 'SP'}-{key[:8].upper()}",
                                 currency_code="AED", status="draft", posting_enabled=False,
                                 created_by=actor, state_changed_by=actor, amount=0,
                                 allocated_amount=0, unallocated_amount=0,
                                 payment_type=kind, party_code="", party_name_snapshot="",
                                 location_code="", payment_date=values["payment_date"],
                                 payment_method=values["payment_method"], cash_bank_account_code="")
    _set_payment(payment, **values)
    session.add(payment)
    session.flush()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="payment.created", actor=actor,
                                      resource_key=payment.payment_key,
                                      detail=f"{payment.payment_no}; AED {payment.amount}; posting disabled"))
    session.commit()
    return payment


def replace_payment(session: Session, payment: OperationalPayment, *, expected_revision: int, actor: str, **values) -> OperationalPayment:
    if payment.status != "draft":
        raise ValueError("Only draft-state payments can be edited")
    if payment.revision != expected_revision:
        raise ValueError(f"Payment revision conflict; current revision is {payment.revision}")
    payment.allocations.clear()
    session.flush()
    _set_payment(payment, **values)
    payment.revision += 1
    payment.state_changed_at = utc_now()
    payment.state_changed_by = actor
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="payment.edited", actor=actor,
                                      resource_key=payment.payment_key,
                                      detail=f"{payment.payment_no}; revision {payment.revision}; posting disabled"))
    session.commit()
    return payment


def list_payments(session: Session, *, allowed_locations: tuple[str, ...] = ("*",), limit: int = 100) -> list[OperationalPayment]:
    query = select(OperationalPayment)
    if "*" not in allowed_locations:
        query = query.where(OperationalPayment.location_code.in_(allowed_locations))
    return list(session.scalars(query.order_by(OperationalPayment.created_at.desc()).limit(limit)))


def _claim_allocations(session: Session, payment: OperationalPayment) -> None:
    # All migration-era invoice allocations share the party's approved opening
    # control balance. This prevents invoice detail and the opening-balance row
    # from being treated as two independent pots of money.
    session.scalars(select(OperationalPaymentAllocation).join(OperationalPayment).where(
        OperationalPayment.party_code == payment.party_code,
        OperationalPayment.payment_type == payment.payment_type
    ).order_by(OperationalPaymentAllocation.id).with_for_update()).all()
    balance_type = "receivable" if payment.payment_type == "customer_receipt" else "payable"
    control_total = session.scalar(select(func.coalesce(func.sum(OperationalOpeningPartyBalance.amount), 0)).where(
        OperationalOpeningPartyBalance.party_code == payment.party_code,
        OperationalOpeningPartyBalance.balance_type == balance_type)) or Decimal("0")
    if control_total > 0:
        party_claimed = session.scalar(select(func.coalesce(func.sum(OperationalPaymentAllocationClaim.amount), 0)).join(
            OperationalPayment, OperationalPayment.id == OperationalPaymentAllocationClaim.payment_id).where(
                OperationalPayment.party_code == payment.party_code,
                OperationalPayment.payment_type == payment.payment_type,
                OperationalPaymentAllocationClaim.status == "active")) or Decimal("0")
        if party_claimed + payment.allocated_amount > control_total:
            remaining = max(Decimal("0"), control_total - party_claimed)
            raise ValueError(f"Allocation exceeds the party opening control balance: AED {remaining} remains")
    for line in sorted(payment.allocations, key=lambda row: (row.source_type, row.source_reference_key)):
        # Lock every persisted contender for this source before calculating the
        # claim total. PostgreSQL therefore serializes simultaneous submissions
        # even though the authoritative invoice remains in the immutable clone.
        session.scalars(select(OperationalPaymentAllocation).join(OperationalPayment).where(
            OperationalPayment.party_code == payment.party_code,
            OperationalPaymentAllocation.source_type == line.source_type,
            OperationalPaymentAllocation.source_reference_key == line.source_reference_key
        ).order_by(OperationalPaymentAllocation.id).with_for_update()).all()
        claimed = session.scalar(select(func.coalesce(func.sum(OperationalPaymentAllocationClaim.amount), 0)).where(
            OperationalPaymentAllocationClaim.party_code == payment.party_code,
            OperationalPaymentAllocationClaim.source_type == line.source_type,
            OperationalPaymentAllocationClaim.source_reference_key == line.source_reference_key,
            OperationalPaymentAllocationClaim.status == "active")) or Decimal("0")
        if claimed + line.allocation_amount > line.source_outstanding_snapshot:
            remaining = max(Decimal("0"), line.source_outstanding_snapshot - claimed)
            raise ValueError(f"Allocation exceeds remaining outstanding for {line.source_reference_key}: AED {remaining}")
        session.add(OperationalPaymentAllocationClaim(claim_key=str(uuid.uuid4()), payment_id=payment.id,
                    payment_allocation_id=line.id, party_code=payment.party_code, source_type=line.source_type,
                    source_reference_key=line.source_reference_key, amount=line.allocation_amount, status="active"))
    session.flush()


def _release_claims(session: Session, payment: OperationalPayment) -> None:
    for claim in session.scalars(select(OperationalPaymentAllocationClaim).where(
            OperationalPaymentAllocationClaim.payment_id == payment.id,
            OperationalPaymentAllocationClaim.status == "active").with_for_update()):
        claim.status = "released"
        claim.released_at = utc_now()


def transition_payment(session: Session, payment: OperationalPayment, *, expected_revision: int,
                       action: str, actor: str, note: str | None = None) -> OperationalPayment:
    transitions = {("draft", "submit"): "submitted", ("draft", "cancel"): "cancelled",
                   ("submitted", "cancel"): "cancelled", ("submitted", "approve"): "approved"}
    if payment.revision != expected_revision:
        raise ValueError(f"Payment revision conflict; current revision is {payment.revision}")
    target = transitions.get((payment.status, action))
    if not target:
        raise ValueError(f"Action {action} is not allowed from {payment.status}")
    if action == "approve" and payment.created_by == actor:
        raise PermissionError("Maker-checker control prevents the creator from approving this payment")
    if action == "submit":
        _claim_allocations(session, payment)
    if action == "cancel" and payment.status == "submitted":
        _release_claims(session, payment)
    prior = payment.status
    payment.status = target
    payment.revision += 1
    payment.state_changed_at = utc_now()
    payment.state_changed_by = actor
    session.add(OperationalPaymentWorkflowEvent(event_key=str(uuid.uuid4()), payment_id=payment.id,
                from_status=prior, to_status=target, actor=actor, note=note))
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"payment.{action}", actor=actor,
                resource_key=payment.payment_key, detail=f"{prior} to {target}; revision {payment.revision}; posting disabled"))
    session.commit()
    return payment


def rehearse_payment_posting(session: Session, payment: OperationalPayment, *, actor: str) -> dict:
    if payment.status != "approved":
        raise ValueError("Only an approved payment can be rehearsed")
    period = session.scalar(select(OperationalFiscalPeriod).where(
        OperationalFiscalPeriod.starts_on <= payment.payment_date,
        OperationalFiscalPeriod.ends_on >= payment.payment_date,
        OperationalFiscalPeriod.status == "open", OperationalFiscalPeriod.rehearsal_enabled.is_(True)))
    if not period:
        raise ValueError("Payment date is not in an open rehearsal-enabled fiscal period")
    claim_total = session.scalar(select(func.coalesce(func.sum(OperationalPaymentAllocationClaim.amount), 0)).where(
        OperationalPaymentAllocationClaim.payment_id == payment.id,
        OperationalPaymentAllocationClaim.status == "active")) or Decimal("0")
    if _money(claim_total) != payment.allocated_amount:
        raise ValueError("Active allocation claims do not match the approved payment")
    cash = payment.cash_bank_account_code
    if payment.payment_type == "customer_receipt":
        journal = [{"account": cash, "debit": payment.amount, "credit": Decimal("0")},
                   {"account": "Accounts Receivable", "debit": Decimal("0"), "credit": payment.allocated_amount}]
        if payment.unallocated_amount:
            journal.append({"account": "Customer Advances", "debit": Decimal("0"), "credit": payment.unallocated_amount})
        entry_type = "customer_receipt"
    else:
        journal = [{"account": "Accounts Payable", "debit": payment.allocated_amount, "credit": Decimal("0")}]
        if payment.unallocated_amount:
            journal.append({"account": "Supplier Advances", "debit": payment.unallocated_amount, "credit": Decimal("0")})
        journal.append({"account": cash, "debit": Decimal("0"), "credit": payment.amount})
        entry_type = "supplier_payment"
    journal = [row for row in journal if row["debit"] or row["credit"]]
    debit = sum((row["debit"] for row in journal), Decimal("0"))
    credit = sum((row["credit"] for row in journal), Decimal("0"))
    if debit != credit:
        raise RuntimeError("Payment posting rehearsal is not balanced")
    subledger = [{"line_no": line.line_no, "entry_type": entry_type, "party_code": payment.party_code,
                  "source_type": line.source_type, "source_reference_key": line.source_reference_key,
                  "amount": line.allocation_amount} for line in payment.allocations]
    if payment.unallocated_amount:
        subledger.append({"line_no": len(subledger) + 1,
                          "entry_type": "customer_advance" if payment.payment_type == "customer_receipt" else "supplier_advance",
                          "party_code": payment.party_code, "source_type": "advance", "source_reference_key": payment.payment_no,
                          "amount": payment.unallocated_amount})
    source = json.dumps({"payment_key": payment.payment_key, "revision": payment.revision,
                         "journal": journal, "subledger": subledger}, default=str, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(source.encode()).hexdigest()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="payment.posting_rehearsed", actor=actor,
                resource_key=payment.payment_key,
                detail=f"AED {debit}; {len(subledger)} subledger entries; fingerprint {fingerprint}; no posting"))
    session.commit()
    return {"payment_key": payment.payment_key, "payment_no": payment.payment_no, "payment_type": payment.payment_type,
            "posting_enabled": False, "period_key": period.period_key, "journal": journal, "subledger": subledger,
            "debit": debit, "credit": credit, "posting_fingerprint": fingerprint,
            "idempotency_key": f"payment:{payment.payment_key}:{payment.revision}:{fingerprint[:20]}"}


def payment_control_counts(session: Session) -> dict:
    return {"payments": session.scalar(select(func.count(OperationalPayment.id))) or 0,
            "customer_receipts": session.scalar(select(func.count(OperationalPayment.id)).where(OperationalPayment.payment_type == "customer_receipt")) or 0,
            "supplier_payments": session.scalar(select(func.count(OperationalPayment.id)).where(OperationalPayment.payment_type == "supplier_payment")) or 0,
            "active_claims": session.scalar(select(func.count(OperationalPaymentAllocationClaim.id)).where(OperationalPaymentAllocationClaim.status == "active")) or 0,
            "posted": session.scalar(select(func.count(OperationalPayment.id)).where(OperationalPayment.status == "posted")) or 0}
