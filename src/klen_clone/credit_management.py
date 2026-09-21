from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric,
    String, Text, UniqueConstraint, func, select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from .operational import (
    MONEY, OperationalAuditEvent, OperationalBase, OperationalOpeningPartyBalance,
    utc_now,
)
from .payments import OperationalPayment, customer_invoice_settlement


class OperationalCustomerCreditProfile(OperationalBase):
    __tablename__ = "operational_customer_credit_profiles"
    __table_args__ = (
        UniqueConstraint("party_code", name="uq_customer_credit_profile_party"),
        CheckConstraint("credit_limit >= 0", name="ck_customer_credit_limit_nonnegative"),
        CheckConstraint("payment_terms_days BETWEEN 0 AND 3650", name="ck_customer_credit_terms"),
        CheckConstraint("status IN ('active','on_hold')", name="ck_customer_credit_status"),
        CheckConstraint("posting_enabled = false", name="ck_customer_credit_no_posting"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    party_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    party_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    hold_reason: Mapped[str | None] = mapped_column(Text)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    approved_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalCreditLimitRequest(OperationalBase):
    __tablename__ = "operational_credit_limit_requests"
    __table_args__ = (
        CheckConstraint("proposed_limit >= 0", name="ck_credit_request_limit_nonnegative"),
        CheckConstraint("proposed_terms_days BETWEEN 0 AND 3650", name="ck_credit_request_terms"),
        CheckConstraint("status IN ('pending','approved','rejected','cancelled')", name="ck_credit_request_status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    party_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    party_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    proposed_limit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    proposed_terms_days: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OperationalCollectionAction(OperationalBase):
    __tablename__ = "operational_collection_actions"
    __table_args__ = (
        CheckConstraint("action_type IN ('call','email','visit','promise_to_pay','final_notice','legal_referral')", name="ck_collection_action_type"),
        CheckConstraint("status IN ('open','completed','broken','cancelled')", name="ck_collection_action_status"),
        CheckConstraint("promise_amount IS NULL OR promise_amount > 0", name="ck_collection_promise_amount"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    party_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    party_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    invoice_no: Mapped[str | None] = mapped_column(String(80), index=True)
    action_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(30), nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    next_followup_date: Mapped[date | None] = mapped_column(Date)
    promise_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    promise_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalCreditOverrideRequest(OperationalBase):
    __tablename__ = "operational_credit_override_requests"
    __table_args__ = (
        CheckConstraint("order_amount > 0", name="ck_credit_override_order_amount"),
        CheckConstraint("exposure_snapshot >= 0 AND credit_limit_snapshot >= 0 AND projected_exposure >= 0", name="ck_credit_override_snapshots"),
        CheckConstraint("block_reason IN ('on_hold','limit_exceeded')", name="ck_credit_override_reason"),
        CheckConstraint("status IN ('pending','approved','rejected','cancelled','consumed','expired')", name="ck_credit_override_status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    quotation_id: Mapped[int] = mapped_column(ForeignKey("operational_sales_quotations.id"), nullable=False, index=True)
    quotation_key: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    quotation_no: Mapped[str] = mapped_column(String(40), nullable=False)
    party_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    party_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    order_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    exposure_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    credit_limit_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    projected_exposure: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    block_reason: Mapped[str] = mapped_column(String(30), nullable=False)
    valid_until: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_by: Mapped[str | None] = mapped_column(String(200))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sales_order_key: Mapped[str | None] = mapped_column(String(36))


class OperationalDunningRequest(OperationalBase):
    __tablename__ = "operational_dunning_requests"
    __table_args__ = (
        CheckConstraint("stage IN ('reminder_1','reminder_2','final_notice','legal_referral')", name="ck_dunning_stage"),
        CheckConstraint("exposure_snapshot >= 0 AND overdue_snapshot >= 0 AND broken_promises >= 0", name="ck_dunning_snapshots"),
        CheckConstraint("status IN ('pending','approved','rejected','cancelled','completed')", name="ck_dunning_status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    party_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    party_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    stage: Mapped[str] = mapped_column(String(30), nullable=False)
    exposure_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    overdue_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    broken_promises: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by: Mapped[str | None] = mapped_column(String(200))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(MONEY, rounding=ROUND_HALF_UP)


def customer_exposure(session: Session, party_code: str, *, as_of: date) -> dict:
    from .customer_invoices import OperationalCustomerInvoice
    from .sales_orders import OperationalSalesOrder

    opening_receivable = _money(session.scalar(select(func.coalesce(func.sum(
        OperationalOpeningPartyBalance.amount), 0)).where(
            OperationalOpeningPartyBalance.party_code == party_code,
            OperationalOpeningPartyBalance.party_type == "customer",
            OperationalOpeningPartyBalance.balance_type == "receivable")) or 0)
    opening_advance = _money(session.scalar(select(func.coalesce(func.sum(
        OperationalOpeningPartyBalance.amount), 0)).where(
            OperationalOpeningPartyBalance.party_code == party_code,
            OperationalOpeningPartyBalance.party_type == "customer",
            OperationalOpeningPartyBalance.balance_type == "customer_advance")) or 0)
    approved_invoices = list(session.scalars(select(OperationalCustomerInvoice).where(
        OperationalCustomerInvoice.customer_code == party_code,
        OperationalCustomerInvoice.status == "approved",
        OperationalCustomerInvoice.invoice_date <= as_of)))
    invoice_total = _money(sum((invoice.total_amount for invoice in approved_invoices), Decimal("0")))
    approved_receipts = _money(session.scalar(select(func.coalesce(func.sum(
        OperationalPayment.amount), 0)).where(
            OperationalPayment.party_code == party_code,
            OperationalPayment.payment_type == "customer_receipt",
            OperationalPayment.status == "approved",
            OperationalPayment.payment_date <= as_of)) or 0)
    pending_receipts = _money(session.scalar(select(func.coalesce(func.sum(
        OperationalPayment.amount), 0)).where(
            OperationalPayment.party_code == party_code,
            OperationalPayment.payment_type == "customer_receipt",
            OperationalPayment.status == "submitted",
            OperationalPayment.payment_date <= as_of)) or 0)
    exposure = _money(opening_receivable - opening_advance + invoice_total - approved_receipts)

    invoiced_orders = select(OperationalCustomerInvoice.sales_order_id)
    open_order_total = _money(session.scalar(select(func.coalesce(func.sum(
        OperationalSalesOrder.total_amount), 0)).where(
            OperationalSalesOrder.customer_code == party_code,
            OperationalSalesOrder.status == "confirmed",
            OperationalSalesOrder.id.not_in(invoiced_orders))) or 0)

    overdue = []
    overdue_total = Decimal("0.00")
    for invoice in approved_invoices:
        settlement = customer_invoice_settlement(session, invoice)
        outstanding = _money(settlement["outstanding_amount"])
        if outstanding > 0 and invoice.due_date < as_of:
            days = (as_of - invoice.due_date).days
            overdue_total += outstanding
            overdue.append({"invoice_no": invoice.invoice_no, "due_date": invoice.due_date,
                            "days_overdue": days, "outstanding_amount": outstanding,
                            "settlement_status": settlement["settlement_status"]})
    overdue.sort(key=lambda row: (-row["days_overdue"], row["invoice_no"]))
    return {
        "opening_receivable": opening_receivable, "opening_advance": opening_advance,
        "approved_invoice_total": invoice_total, "approved_receipt_total": approved_receipts,
        "pending_receipt_total": pending_receipts, "receivable_exposure": max(Decimal("0.00"), exposure),
        "open_order_commitment": open_order_total,
        "credit_exposure": max(Decimal("0.00"), _money(exposure + open_order_total)),
        "overdue_amount": _money(overdue_total), "overdue_invoices": overdue,
    }


def customer_credit_block(session: Session, party_code: str, *, order_amount, as_of: date) -> dict | None:
    profile = session.scalar(select(OperationalCustomerCreditProfile).where(
        OperationalCustomerCreditProfile.party_code == party_code))
    if not profile:
        return None
    exposure = customer_exposure(session, party_code, as_of=as_of)
    order_value = _money(order_amount)
    projected = _money(exposure["credit_exposure"] + order_value)
    if profile.status == "on_hold":
        reason = "on_hold"
    elif projected > _money(profile.credit_limit):
        reason = "limit_exceeded"
    else:
        return None
    return {"block_reason": reason, "order_amount": order_value,
            "exposure_snapshot": exposure["credit_exposure"],
            "credit_limit_snapshot": _money(profile.credit_limit),
            "projected_exposure": projected}


def credit_profile_payload(session: Session, party_code: str, party_name: str, *, as_of: date) -> dict:
    profile = session.scalar(select(OperationalCustomerCreditProfile).where(
        OperationalCustomerCreditProfile.party_code == party_code))
    exposure = customer_exposure(session, party_code, as_of=as_of)
    actions = list(session.scalars(select(OperationalCollectionAction).where(
        OperationalCollectionAction.party_code == party_code).order_by(
            OperationalCollectionAction.action_date.desc(), OperationalCollectionAction.id.desc())))
    open_actions = [row for row in actions if row.status == "open"]
    open_promises = [row for row in open_actions if row.action_type == "promise_to_pay"]
    broken_promises = [row for row in actions if row.status == "broken" and row.action_type == "promise_to_pay"]
    available = (_money(profile.credit_limit - exposure["credit_exposure"]) if profile else None)
    if not profile:
        credit_status = "not_configured"
    elif profile.status == "on_hold":
        credit_status = "on_hold"
    elif available < 0:
        credit_status = "over_limit"
    else:
        credit_status = "within_limit"
    return {
        "party_code": party_code, "party_name": party_name,
        "configured": profile is not None,
        "profile_key": profile.profile_key if profile else None,
        "credit_limit": _money(profile.credit_limit) if profile else Decimal("0.00"),
        "payment_terms_days": profile.payment_terms_days if profile else None,
        "profile_status": profile.status if profile else "not_configured",
        "credit_status": credit_status, "available_credit": available,
        "hold_reason": profile.hold_reason if profile else None,
        "profile_revision": profile.revision if profile else None,
        "next_followup_date": min((row.next_followup_date for row in open_actions if row.next_followup_date), default=None),
        "open_collection_actions": len(open_actions), "open_promises": len(open_promises),
        "broken_promises": len(broken_promises),
        **exposure,
    }


def credit_workspace_payload(session: Session, parties: list[dict], *, as_of: date) -> dict:
    from .sales_orders import OperationalSalesQuotation

    customers = [credit_profile_payload(session, row["party_code"], row["party_name"], as_of=as_of)
                 for row in parties]
    customers.sort(key=lambda row: (-row["overdue_amount"], -row["credit_exposure"], row["party_name"]))
    requests = list(session.scalars(select(OperationalCreditLimitRequest).order_by(
        OperationalCreditLimitRequest.created_at.desc()).limit(200)))
    actions = list(session.scalars(select(OperationalCollectionAction).order_by(
        OperationalCollectionAction.action_date.desc(), OperationalCollectionAction.id.desc()).limit(200)))
    overrides = list(session.scalars(select(OperationalCreditOverrideRequest).order_by(
        OperationalCreditOverrideRequest.created_at.desc()).limit(200)))
    dunning = list(session.scalars(select(OperationalDunningRequest).order_by(
        OperationalDunningRequest.created_at.desc()).limit(200)))
    blocked_quotations = []
    for quotation in session.scalars(select(OperationalSalesQuotation).where(
            OperationalSalesQuotation.status == "accepted").order_by(
            OperationalSalesQuotation.created_at.desc()).limit(200)):
        block = customer_credit_block(session, quotation.customer_code,
                                      order_amount=quotation.total_amount, as_of=as_of)
        if block:
            blocked_quotations.append({"quotation_key": quotation.quotation_key,
                "quotation_no": quotation.quotation_no, "party_code": quotation.customer_code,
                "party_name": quotation.customer_name_snapshot,
                "order_amount": _money(quotation.total_amount), **block})
    dunning_candidates = [row for row in customers if row["overdue_amount"] > 0 or row["broken_promises"] > 0]
    return {
        "as_of": as_of, "customers": customers,
        "requests": [credit_request_payload(row) for row in requests],
        "actions": [collection_action_payload(row) for row in actions],
        "override_requests": [credit_override_payload(row) for row in overrides],
        "blocked_quotations": blocked_quotations,
        "dunning_requests": [dunning_request_payload(row) for row in dunning],
        "dunning_candidates": dunning_candidates,
        "controls": {
            "configured_customers": sum(row["configured"] for row in customers),
            "on_hold": sum(row["credit_status"] == "on_hold" for row in customers),
            "over_limit": sum(row["credit_status"] == "over_limit" for row in customers),
            "overdue_customers": sum(row["overdue_amount"] > 0 for row in customers),
            "pending_limit_requests": sum(row.status == "pending" for row in requests),
            "open_collection_actions": sum(row.status == "open" for row in actions),
            "blocked_orders": len(blocked_quotations),
            "pending_overrides": sum(row.status == "pending" for row in overrides),
            "pending_dunning": sum(row.status == "pending" for row in dunning),
        },
        "posting_enabled": False,
        "overdue_scope": "approved target-ERP invoices with reliable due dates",
    }


def credit_request_payload(row: OperationalCreditLimitRequest) -> dict:
    return {"request_key": row.request_key, "party_code": row.party_code,
            "party_name": row.party_name_snapshot, "proposed_limit": _money(row.proposed_limit),
            "proposed_terms_days": row.proposed_terms_days, "reason": row.reason,
            "status": row.status, "revision": row.revision, "created_by": row.created_by,
            "created_at": row.created_at, "decided_by": row.decided_by,
            "decision_note": row.decision_note, "decided_at": row.decided_at}


def credit_override_payload(row: OperationalCreditOverrideRequest) -> dict:
    return {"request_key": row.request_key, "quotation_key": row.quotation_key,
            "quotation_no": row.quotation_no, "party_code": row.party_code,
            "party_name": row.party_name_snapshot, "order_amount": _money(row.order_amount),
            "exposure_snapshot": _money(row.exposure_snapshot),
            "credit_limit_snapshot": _money(row.credit_limit_snapshot),
            "projected_exposure": _money(row.projected_exposure),
            "block_reason": row.block_reason, "valid_until": row.valid_until,
            "reason": row.reason, "status": row.status, "revision": row.revision,
            "created_by": row.created_by, "created_at": row.created_at,
            "decided_by": row.decided_by, "decision_note": row.decision_note,
            "decided_at": row.decided_at, "consumed_by": row.consumed_by,
            "consumed_at": row.consumed_at, "sales_order_key": row.sales_order_key}


def create_credit_override_request(session: Session, quotation, *, valid_until: date,
                                   reason: str, actor: str,
                                   as_of: date) -> OperationalCreditOverrideRequest:
    if quotation.status != "accepted":
        raise ValueError("Only a customer-accepted quotation can request a credit override")
    if valid_until < as_of:
        raise ValueError("Credit override validity cannot be in the past")
    if (valid_until - as_of).days > 30:
        raise ValueError("Credit override validity cannot exceed 30 days")
    if len(reason.strip()) < 5:
        raise ValueError("A credit override reason of at least 5 characters is required")
    block = customer_credit_block(session, quotation.customer_code,
                                  order_amount=quotation.total_amount, as_of=as_of)
    if not block:
        raise ValueError("This quotation is not currently blocked by customer credit controls")
    active = session.scalar(select(OperationalCreditOverrideRequest.id).where(
        OperationalCreditOverrideRequest.quotation_id == quotation.id,
        OperationalCreditOverrideRequest.status.in_(("pending", "approved"))))
    if active:
        raise ValueError("This quotation already has an active credit override request")
    row = OperationalCreditOverrideRequest(
        request_key=str(uuid.uuid4()), quotation_id=quotation.id,
        quotation_key=quotation.quotation_key, quotation_no=quotation.quotation_no,
        party_code=quotation.customer_code,
        party_name_snapshot=quotation.customer_name_snapshot,
        valid_until=valid_until, reason=reason.strip(), status="pending", revision=1,
        created_by=actor, **block)
    session.add(row); session.flush()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()),
        event_type="credit.override_requested", actor=actor, resource_key=row.request_key,
        detail=f"{row.quotation_no}; {row.block_reason}; projected AED {row.projected_exposure}; non-posting"))
    session.commit(); return row


def transition_credit_override_request(session: Session, row: OperationalCreditOverrideRequest, *,
                                       expected_revision: int, action: str, actor: str,
                                       note: str) -> OperationalCreditOverrideRequest:
    if row.revision != expected_revision:
        raise ValueError(f"Credit override revision conflict; current revision is {row.revision}")
    if row.status != "pending" or action not in {"approve", "reject", "cancel"}:
        raise ValueError(f"Action {action} is not allowed from {row.status}")
    if action in {"approve", "reject"} and row.created_by == actor:
        raise PermissionError("Maker-checker control prevents the requester from deciding this credit override")
    if len(note.strip()) < 5:
        raise ValueError("A credit override decision reason of at least 5 characters is required")
    row.status = {"approve": "approved", "reject": "rejected", "cancel": "cancelled"}[action]
    row.revision += 1; row.decided_by = actor; row.decision_note = note.strip(); row.decided_at = utc_now()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()),
        event_type=f"credit.override_{row.status}", actor=actor, resource_key=row.request_key,
        detail=f"{row.quotation_no}; {row.block_reason}; non-posting"))
    session.commit(); return row


def approved_credit_override(session: Session, *, quotation_key: str | None,
                             party_code: str, order_amount, as_of: date) -> OperationalCreditOverrideRequest | None:
    if not quotation_key:
        return None
    row = session.scalar(select(OperationalCreditOverrideRequest).where(
        OperationalCreditOverrideRequest.quotation_key == quotation_key,
        OperationalCreditOverrideRequest.party_code == party_code,
        OperationalCreditOverrideRequest.order_amount == _money(order_amount),
        OperationalCreditOverrideRequest.status == "approved").order_by(
        OperationalCreditOverrideRequest.decided_at.desc()))
    if row and row.valid_until < as_of:
        row.status = "expired"; row.revision += 1
        session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()),
            event_type="credit.override_expired", actor="system", resource_key=row.request_key,
            detail=f"{row.quotation_no}; validity ended {row.valid_until}; non-posting"))
        session.commit(); return None
    return row


def consume_credit_override(session: Session, row: OperationalCreditOverrideRequest, *,
                            actor: str, sales_order_key: str) -> None:
    if row.status != "approved":
        raise ValueError("Credit override is no longer available")
    row.status = "consumed"; row.revision += 1; row.consumed_by = actor
    row.consumed_at = utc_now(); row.sales_order_key = sales_order_key
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()),
        event_type="credit.override_consumed", actor=actor, resource_key=row.request_key,
        detail=f"{row.quotation_no}; sales order {sales_order_key}; one-time override consumed"))


def dunning_request_payload(row: OperationalDunningRequest) -> dict:
    return {"request_key": row.request_key, "party_code": row.party_code,
            "party_name": row.party_name_snapshot, "stage": row.stage,
            "exposure_snapshot": _money(row.exposure_snapshot),
            "overdue_snapshot": _money(row.overdue_snapshot),
            "broken_promises": row.broken_promises, "reason": row.reason,
            "status": row.status, "revision": row.revision,
            "created_by": row.created_by, "created_at": row.created_at,
            "decided_by": row.decided_by, "decision_note": row.decision_note,
            "decided_at": row.decided_at, "completed_by": row.completed_by,
            "completed_at": row.completed_at}


def create_dunning_request(session: Session, *, party_code: str, party_name: str,
                           stage: str, reason: str, actor: str,
                           as_of: date) -> OperationalDunningRequest:
    stages = ("reminder_1", "reminder_2", "final_notice", "legal_referral")
    if stage not in stages or len(reason.strip()) < 5:
        raise ValueError("A valid dunning stage and reason are required")
    exposure = customer_exposure(session, party_code, as_of=as_of)
    broken = session.scalar(select(func.count(OperationalCollectionAction.id)).where(
        OperationalCollectionAction.party_code == party_code,
        OperationalCollectionAction.action_type == "promise_to_pay",
        OperationalCollectionAction.status == "broken")) or 0
    if exposure["overdue_amount"] <= 0 and broken == 0:
        raise ValueError("Dunning requires an overdue target-ERP invoice or a broken promise to pay")
    active = session.scalar(select(OperationalDunningRequest.id).where(
        OperationalDunningRequest.party_code == party_code,
        OperationalDunningRequest.status.in_(("pending", "approved"))))
    if active:
        raise ValueError("This customer already has an active dunning request")
    stage_index = stages.index(stage)
    if stage_index:
        previous = stages[stage_index - 1]
        completed = session.scalar(select(OperationalDunningRequest.id).where(
            OperationalDunningRequest.party_code == party_code,
            OperationalDunningRequest.stage == previous,
            OperationalDunningRequest.status == "completed"))
        if not completed:
            raise ValueError(f"Complete {previous.replace('_', ' ')} before requesting {stage.replace('_', ' ')}")
    row = OperationalDunningRequest(request_key=str(uuid.uuid4()), party_code=party_code,
        party_name_snapshot=party_name, stage=stage,
        exposure_snapshot=exposure["credit_exposure"], overdue_snapshot=exposure["overdue_amount"],
        broken_promises=int(broken), reason=reason.strip(), status="pending", revision=1,
        created_by=actor)
    session.add(row); session.flush()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()),
        event_type="collection.dunning_requested", actor=actor, resource_key=row.request_key,
        detail=f"{party_code}; {stage}; overdue AED {row.overdue_snapshot}; broken promises {broken}; non-posting"))
    session.commit(); return row


def transition_dunning_request(session: Session, row: OperationalDunningRequest, *,
                               expected_revision: int, action: str, actor: str,
                               note: str) -> OperationalDunningRequest:
    if row.revision != expected_revision:
        raise ValueError(f"Dunning revision conflict; current revision is {row.revision}")
    allowed = ((row.status == "pending" and action in {"approve", "reject", "cancel"}) or
               (row.status == "approved" and action == "complete"))
    if not allowed:
        raise ValueError(f"Action {action} is not allowed from {row.status}")
    if action in {"approve", "reject"} and row.created_by == actor:
        raise PermissionError("Maker-checker control prevents the requester from deciding this dunning action")
    if len(note.strip()) < 5:
        raise ValueError("A dunning decision reason of at least 5 characters is required")
    target = {"approve": "approved", "reject": "rejected", "cancel": "cancelled",
              "complete": "completed"}[action]
    row.status = target; row.revision += 1
    if action == "complete":
        row.completed_by = actor; row.completed_at = utc_now()
    else:
        row.decided_by = actor; row.decision_note = note.strip(); row.decided_at = utc_now()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()),
        event_type=f"collection.dunning_{target}", actor=actor, resource_key=row.request_key,
        detail=f"{row.party_code}; {row.stage}; {note.strip()}; non-posting"))
    session.commit(); return row


def create_credit_limit_request(session: Session, *, party_code: str, party_name: str,
                                proposed_limit, proposed_terms_days: int, reason: str,
                                actor: str) -> OperationalCreditLimitRequest:
    if _money(proposed_limit) < 0 or proposed_terms_days < 0 or proposed_terms_days > 3650:
        raise ValueError("Credit limit and payment terms are invalid")
    if len(reason.strip()) < 5:
        raise ValueError("A credit-limit reason of at least 5 characters is required")
    if session.scalar(select(OperationalCreditLimitRequest.id).where(
            OperationalCreditLimitRequest.party_code == party_code,
            OperationalCreditLimitRequest.status == "pending")):
        raise ValueError("This customer already has a pending credit-limit request")
    row = OperationalCreditLimitRequest(
        request_key=str(uuid.uuid4()), party_code=party_code,
        party_name_snapshot=party_name, proposed_limit=_money(proposed_limit),
        proposed_terms_days=proposed_terms_days, reason=reason.strip(),
        status="pending", revision=1, created_by=actor)
    session.add(row); session.flush()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="credit.limit_requested",
        actor=actor, resource_key=row.request_key,
        detail=f"{party_code}; AED {row.proposed_limit}; {proposed_terms_days} days; pending approval; non-posting"))
    session.commit(); return row


def transition_credit_limit_request(session: Session, row: OperationalCreditLimitRequest, *,
                                    expected_revision: int, action: str, actor: str,
                                    note: str) -> OperationalCreditLimitRequest:
    if row.revision != expected_revision:
        raise ValueError(f"Credit request revision conflict; current revision is {row.revision}")
    if row.status != "pending" or action not in {"approve", "reject", "cancel"}:
        raise ValueError(f"Action {action} is not allowed from {row.status}")
    if action in {"approve", "reject"} and row.created_by == actor:
        raise PermissionError("Maker-checker control prevents the requester from deciding this credit limit")
    if len(note.strip()) < 5:
        raise ValueError("A decision reason of at least 5 characters is required")
    if action == "approve":
        profile = session.scalar(select(OperationalCustomerCreditProfile).where(
            OperationalCustomerCreditProfile.party_code == row.party_code).with_for_update())
        if profile:
            profile.credit_limit = row.proposed_limit
            profile.payment_terms_days = row.proposed_terms_days
            profile.revision += 1; profile.updated_by = actor; profile.updated_at = utc_now()
            profile.approved_by = actor
        else:
            profile = OperationalCustomerCreditProfile(
                profile_key=str(uuid.uuid4()), party_code=row.party_code,
                party_name_snapshot=row.party_name_snapshot, credit_limit=row.proposed_limit,
                payment_terms_days=row.proposed_terms_days, status="active",
                posting_enabled=False, revision=1, created_by=row.created_by,
                approved_by=actor, updated_by=actor)
            session.add(profile)
    row.status = {"approve": "approved", "reject": "rejected", "cancel": "cancelled"}[action]
    row.revision += 1; row.decided_by = actor; row.decision_note = note.strip(); row.decided_at = utc_now()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"credit.limit_{row.status}",
        actor=actor, resource_key=row.request_key,
        detail=f"{row.party_code}; AED {row.proposed_limit}; {row.proposed_terms_days} days; non-posting"))
    session.commit(); return row


def set_credit_hold(session: Session, profile: OperationalCustomerCreditProfile, *,
                    expected_revision: int, action: str, reason: str, actor: str) -> OperationalCustomerCreditProfile:
    if profile.revision != expected_revision:
        raise ValueError(f"Credit profile revision conflict; current revision is {profile.revision}")
    target = {("active", "hold"): "on_hold", ("on_hold", "release"): "active"}.get((profile.status, action))
    if not target:
        raise ValueError(f"Action {action} is not allowed from {profile.status}")
    if len(reason.strip()) < 5:
        raise ValueError("A hold or release reason of at least 5 characters is required")
    profile.status = target; profile.hold_reason = reason.strip() if target == "on_hold" else None
    profile.revision += 1; profile.updated_by = actor; profile.updated_at = utc_now()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"credit.{action}",
        actor=actor, resource_key=profile.profile_key,
        detail=f"{profile.party_code}; {reason.strip()}; non-posting"))
    session.commit(); return profile


def collection_action_payload(row: OperationalCollectionAction) -> dict:
    return {"action_key": row.action_key, "party_code": row.party_code,
            "party_name": row.party_name_snapshot, "invoice_no": row.invoice_no,
            "action_date": row.action_date, "action_type": row.action_type,
            "outcome": row.outcome, "next_followup_date": row.next_followup_date,
            "promise_amount": _money(row.promise_amount) if row.promise_amount is not None else None,
            "promise_date": row.promise_date, "status": row.status,
            "revision": row.revision, "created_by": row.created_by,
            "created_at": row.created_at, "updated_by": row.updated_by,
            "updated_at": row.updated_at}


def create_collection_action(session: Session, *, party_code: str, party_name: str,
                             invoice_no: str | None, action_date: date, action_type: str,
                             outcome: str, next_followup_date: date | None,
                             promise_amount, promise_date: date | None,
                             actor: str) -> OperationalCollectionAction:
    allowed = {"call", "email", "visit", "promise_to_pay", "final_notice", "legal_referral"}
    if action_type not in allowed or len(outcome.strip()) < 3:
        raise ValueError("Collection action and outcome are required")
    amount = _money(promise_amount) if promise_amount not in (None, "") else None
    if action_type == "promise_to_pay" and (not amount or amount <= 0 or not promise_date):
        raise ValueError("Promise amount and promise date are required")
    if next_followup_date and next_followup_date < action_date:
        raise ValueError("Next follow-up date cannot be before the action date")
    row = OperationalCollectionAction(
        action_key=str(uuid.uuid4()), party_code=party_code,
        party_name_snapshot=party_name, invoice_no=(invoice_no or "").strip() or None,
        action_date=action_date, action_type=action_type, outcome=outcome.strip(),
        next_followup_date=next_followup_date, promise_amount=amount,
        promise_date=promise_date, status="open", revision=1,
        created_by=actor, updated_by=actor)
    session.add(row); session.flush()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="collection.action_created",
        actor=actor, resource_key=row.action_key,
        detail=f"{party_code}; {action_type}; next {next_followup_date}; non-posting"))
    session.commit(); return row


def transition_collection_action(session: Session, row: OperationalCollectionAction, *,
                                 expected_revision: int, action: str, actor: str) -> OperationalCollectionAction:
    target = {"complete": "completed", "break": "broken", "cancel": "cancelled"}.get(action)
    if row.revision != expected_revision:
        raise ValueError(f"Collection action revision conflict; current revision is {row.revision}")
    if row.status != "open" or not target:
        raise ValueError(f"Action {action} is not allowed from {row.status}")
    row.status = target; row.revision += 1; row.updated_by = actor; row.updated_at = utc_now()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"collection.{target}",
        actor=actor, resource_key=row.action_key, detail=f"{row.party_code}; non-posting"))
    session.commit(); return row


def assert_customer_credit_allows_order(session: Session, *, party_code: str,
                                        order_amount, as_of: date,
                                        quotation_key: str | None = None) -> OperationalCreditOverrideRequest | None:
    block = customer_credit_block(session, party_code, order_amount=order_amount, as_of=as_of)
    if not block:
        return None
    override = approved_credit_override(session, quotation_key=quotation_key,
        party_code=party_code, order_amount=order_amount, as_of=as_of)
    if override:
        return override
    if block["block_reason"] == "on_hold":
        raise ValueError("Customer is on credit hold; an approved quotation-specific credit override is required")
    raise ValueError(
        f"Customer credit limit exceeded: projected AED {block['projected_exposure']} versus limit AED {block['credit_limit_snapshot']}; an approved quotation-specific override is required"
    )
