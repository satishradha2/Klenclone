"""Non-posting, quotation-bound release for a cross-border commercial order.

This authorizes order recording only. Fulfillment, invoice tax, and settlement
remain separately held until their own controls are implemented and approved.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .operational import OperationalAuditEvent, OperationalBase, utc_now
from .operational_masters import OperationalPartyMaster
from .quote_trade_controls import OperationalQuoteTradeDecision
from .sales_orders import OperationalSalesQuotation


class OperationalCrossBorderOrderRelease(OperationalBase):
    __tablename__ = "operational_cross_border_order_releases"
    __table_args__ = (CheckConstraint("status IN ('pending','approved','rejected','consumed')", name="ck_cross_border_order_release_status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    release_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    quotation_id: Mapped[int] = mapped_column(ForeignKey("operational_sales_quotations.id"), nullable=False, index=True)
    quotation_key: Mapped[str] = mapped_column(String(36), nullable=False)
    quotation_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    quotation_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    trade_decision_key: Mapped[str] = mapped_column(String(36), nullable=False)
    fx_rate_key: Mapped[str | None] = mapped_column(String(36))
    aed_total_snapshot: Mapped[str] = mapped_column(String(40), nullable=False)
    order_tax_review_basis: Mapped[str] = mapped_column(Text, nullable=False)
    fulfillment_evidence_required: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    valid_until: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    consumed_by: Mapped[str | None] = mapped_column(String(200))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sales_order_key: Mapped[str | None] = mapped_column(String(36))


def quotation_fingerprint(quotation: OperationalSalesQuotation) -> str:
    fields = [quotation.quotation_key, quotation.revision, quotation.customer_code,
              quotation.customer_country_code, quotation.location_code, quotation.currency_code,
              quotation.quotation_date, quotation.valid_until, quotation.trade_decision_key,
              quotation.fx_rate_key, quotation.aed_per_unit_snapshot, quotation.aed_total_snapshot,
              quotation.subtotal, quotation.discount_amount, quotation.tax_amount,
              quotation.total_amount, quotation.customer_price_group, quotation.price_list_key,
              quotation.promotion_key, quotation.payment_terms, quotation.delivery_terms,
              quotation.notes, quotation.acceptance_reference]
    lines = [[line.line_no, line.sku, line.quantity, line.uom, line.canonical_uom,
              line.factor_to_base_snapshot, line.quantity_base, line.unit_price,
              line.tax_rate, line.net_amount, line.discount_amount, line.tax_amount,
              line.gross_amount] for line in quotation.lines]
    def canonical(value):
        if isinstance(value, Decimal):
            return format(value.normalize(), "f")
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        raise TypeError(f"Unsupported quotation snapshot value: {type(value)!r}")
    encoded = json.dumps([fields, lines], default=canonical, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _assert_foreign_quote(session: Session, quotation: OperationalSalesQuotation) -> None:
    if quotation.status != "accepted" or quotation.customer_country_code in (None, "AE"):
        raise ValueError("An accepted cross-border quotation is required")
    if quotation.valid_until < date.today():
        raise ValueError("The accepted quotation has expired")
    master = session.scalar(select(OperationalPartyMaster).where(
        OperationalPartyMaster.party_code == quotation.customer_code,
        OperationalPartyMaster.party_kind.in_(("customer", "both"))))
    if (not master or master.status != "active" or
            master.country_code != quotation.customer_country_code or
            master.preferred_currency_code != quotation.currency_code):
        raise ValueError("The active customer master must still match the accepted destination and currency")
    trade = session.scalar(select(OperationalQuoteTradeDecision).where(
        OperationalQuoteTradeDecision.decision_key == quotation.trade_decision_key))
    if not trade or trade.status != "approved" or trade.customer_code != quotation.customer_code or trade.destination_country_code != quotation.customer_country_code or trade.currency_code != quotation.currency_code:
        raise ValueError("The approved quotation trade decision is missing or no longer matches")
    if quotation.aed_total_snapshot is None or quotation.aed_per_unit_snapshot is None:
        raise ValueError("A controlled AED credit valuation snapshot is required")
    if quotation.currency_code != "AED" and not quotation.fx_rate_key:
        raise ValueError("An approved FX snapshot is required")


def order_release_payload(row: OperationalCrossBorderOrderRelease) -> dict:
    return {"release_key": row.release_key, "quotation_key": row.quotation_key,
            "quotation_revision": row.quotation_revision, "customer_country_code": row.customer_country_code,
            "currency_code": row.currency_code, "aed_total_snapshot": row.aed_total_snapshot,
            "order_tax_review_basis": row.order_tax_review_basis,
            "fulfillment_evidence_required": row.fulfillment_evidence_required,
            "evidence_reference": row.evidence_reference, "valid_until": row.valid_until,
            "status": row.status, "revision": row.revision, "created_by": row.created_by,
            "created_at": row.created_at, "decided_by": row.decided_by,
            "decided_at": row.decided_at, "decision_note": row.decision_note,
            "sales_order_key": row.sales_order_key, "fulfillment_released": False,
            "invoice_tax_final": False, "posting_enabled": False}


def prepare_order_release(session: Session, quotation: OperationalSalesQuotation, *,
                          expected_revision: int, order_tax_review_basis: str,
                          fulfillment_evidence_required: str, evidence_reference: str,
                          valid_until: date, actor: str) -> OperationalCrossBorderOrderRelease:
    _assert_foreign_quote(session, quotation)
    if quotation.revision != expected_revision:
        raise ValueError(f"Sales quotation revision conflict; current revision is {quotation.revision}")
    if valid_until < date.today() or valid_until > quotation.valid_until:
        raise ValueError("Order release expiry must be current and within quotation validity")
    if any(len(value.strip()) < 5 for value in (order_tax_review_basis, fulfillment_evidence_required, evidence_reference)):
        raise ValueError("Tax review, fulfillment evidence and reference each require at least five characters")
    active = session.scalar(select(OperationalCrossBorderOrderRelease.id).where(
        OperationalCrossBorderOrderRelease.quotation_id == quotation.id,
        OperationalCrossBorderOrderRelease.status.in_(("pending", "approved"))))
    if active:
        raise ValueError("This quotation already has an active order release")
    row = OperationalCrossBorderOrderRelease(release_key=str(uuid.uuid4()), quotation_id=quotation.id,
        quotation_key=quotation.quotation_key, quotation_revision=quotation.revision,
        quotation_fingerprint=quotation_fingerprint(quotation),
        customer_country_code=quotation.customer_country_code, currency_code=quotation.currency_code,
        trade_decision_key=quotation.trade_decision_key, fx_rate_key=quotation.fx_rate_key,
        aed_total_snapshot=str(quotation.aed_total_snapshot),
        order_tax_review_basis=order_tax_review_basis.strip(),
        fulfillment_evidence_required=fulfillment_evidence_required.strip(),
        evidence_reference=evidence_reference.strip(), valid_until=valid_until, created_by=actor)
    session.add(row); session.flush()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="trade_order.prepared",
        actor=actor, resource_key=row.release_key,
        detail=f"{quotation.quotation_no}; {quotation.customer_country_code}; order only; no fulfillment or posting"))
    session.commit()
    return row


def decide_order_release(session: Session, row: OperationalCrossBorderOrderRelease, *,
                         expected_revision: int, action: str, note: str,
                         actor: str) -> OperationalCrossBorderOrderRelease:
    if row.status != "pending" or action not in ("approve", "reject"):
        raise ValueError("Only pending order releases can be reviewed")
    if row.revision != expected_revision:
        raise ValueError(f"Order release revision conflict; current revision is {row.revision}")
    quotation = session.get(OperationalSalesQuotation, row.quotation_id)
    _assert_foreign_quote(session, quotation)
    if row.quotation_revision != quotation.revision or row.quotation_fingerprint != quotation_fingerprint(quotation):
        raise ValueError("Quotation changed after order release preparation")
    if row.valid_until < date.today():
        raise ValueError("Order release has expired")
    if actor in (row.created_by, quotation.created_by):
        raise PermissionError("Independent order reviewer cannot be the release maker or quotation maker")
    if len(note.strip()) < 5:
        raise ValueError("An independent review note is required")
    row.status = "approved" if action == "approve" else "rejected"
    row.revision += 1; row.decided_by = actor; row.decided_at = utc_now(); row.decision_note = note.strip()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"trade_order.{action}",
        actor=actor, resource_key=row.release_key,
        detail=f"{quotation.quotation_no}; order-stage only; fulfillment and invoice held"))
    session.commit()
    return row


def approved_order_release(session: Session, quotation: OperationalSalesQuotation) -> OperationalCrossBorderOrderRelease:
    _assert_foreign_quote(session, quotation)
    row = session.scalar(select(OperationalCrossBorderOrderRelease).where(
        OperationalCrossBorderOrderRelease.quotation_id == quotation.id,
        OperationalCrossBorderOrderRelease.status == "approved").with_for_update())
    if not row or row.valid_until < date.today():
        raise ValueError("A current, independently approved cross-border order release is required")
    if row.quotation_revision != quotation.revision or row.quotation_fingerprint != quotation_fingerprint(quotation):
        raise ValueError("Order release no longer matches the accepted quotation snapshot")
    return row
