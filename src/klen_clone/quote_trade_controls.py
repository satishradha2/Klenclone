"""Reviewer-owned provisional tax/trade decisions for non-posting export quotations.

This is a quotation assumption only. It is not proof of export, a VAT invoice
decision, customs clearance, or authority to create an international order.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import CheckConstraint, Date, DateTime, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .country_catalog import country_code as normalize_country_code, currency_code as normalize_currency_code
from .operational import OperationalAuditEvent, OperationalBase, utc_now


class OperationalQuoteTradeDecision(OperationalBase):
    __tablename__ = "operational_quote_trade_decisions"
    __table_args__ = (CheckConstraint("status IN ('pending','approved','rejected')", name="ck_quote_trade_status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    customer_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    destination_country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    quotation_date: Mapped[date] = mapped_column(Date, nullable=False)
    line_tax_rates_json: Mapped[str] = mapped_column(Text, nullable=False)
    provisional_tax_basis: Mapped[str] = mapped_column(Text, nullable=False)
    trade_terms: Mapped[str] = mapped_column(String(300), nullable=False)
    evidence_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)


def _rates(values: list[dict]) -> dict[str, str]:
    if not values:
        raise ValueError("At least one SKU tax assumption is required")
    rates = {}
    for item in values:
        sku = str(item.get("sku", "")).strip()
        if not sku or sku.casefold() in {key.casefold() for key in rates}:
            raise ValueError("Every SKU tax assumption must be unique and nonempty")
        try:
            rate = Decimal(str(item.get("tax_rate", "")))
        except InvalidOperation as exc:
            raise ValueError("Each provisional tax rate must be numeric") from exc
        if not rate.is_finite() or rate < 0 or rate > 100 or rate.as_tuple().exponent < -4:
            raise ValueError("Each provisional tax rate must be 0–100 with at most four decimals")
        rates[sku] = str(rate)
    return rates


def trade_decision_payload(row: OperationalQuoteTradeDecision) -> dict:
    return {
        "decision_key": row.decision_key, "customer_code": row.customer_code,
        "destination_country_code": row.destination_country_code,
        "currency_code": row.currency_code, "quotation_date": row.quotation_date,
        "line_tax_rates": json.loads(row.line_tax_rates_json),
        "provisional_tax_basis": row.provisional_tax_basis,
        "trade_terms": row.trade_terms, "evidence_reference": row.evidence_reference,
        "status": row.status, "revision": row.revision,
        "created_by": row.created_by, "created_at": row.created_at,
        "decided_by": row.decided_by, "decided_at": row.decided_at,
        "decision_note": row.decision_note,
        "invoice_tax_final": False, "export_evidence_complete": False,
    }


def prepare_trade_decision(session: Session, *, customer_code: str, destination_country_code: str,
                           currency_code: str, quotation_date: date, line_tax_rates: list[dict],
                           provisional_tax_basis: str, trade_terms: str,
                           evidence_reference: str, actor: str) -> OperationalQuoteTradeDecision:
    destination = normalize_country_code(destination_country_code)
    currency = normalize_currency_code(currency_code)
    if destination == "AE":
        raise ValueError("This control is for non-UAE destination quotations")
    customer = customer_code.strip()
    if not customer or not provisional_tax_basis.strip() or not trade_terms.strip() or not evidence_reference.strip():
        raise ValueError("Customer, provisional tax basis, trade terms and evidence reference are required")
    if quotation_date > date.today():
        raise ValueError("Future quotation dates are not permitted for trade decisions")
    rates = _rates(line_tax_rates)
    row = OperationalQuoteTradeDecision(decision_key=str(uuid.uuid4()), customer_code=customer,
        destination_country_code=destination, currency_code=currency,
        quotation_date=quotation_date, line_tax_rates_json=json.dumps(rates, sort_keys=True),
        provisional_tax_basis=provisional_tax_basis.strip(), trade_terms=trade_terms.strip(),
        evidence_reference=evidence_reference.strip(), created_by=actor)
    session.add(row)
    session.flush()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="trade_quote.prepared",
        actor=actor, resource_key=row.decision_key,
        detail=f"{customer}; {destination}; {currency}; provisional quotation tax; no posting"))
    session.commit()
    return row


def decide_trade_decision(session: Session, row: OperationalQuoteTradeDecision, *, action: str,
                          expected_revision: int, note: str, actor: str) -> OperationalQuoteTradeDecision:
    if row.status != "pending" or action not in {"approve", "reject"}:
        raise ValueError("Only pending trade decisions can be approved or rejected")
    if row.revision != expected_revision:
        raise ValueError(f"Trade decision revision conflict; current revision is {row.revision}")
    if row.created_by == actor:
        raise PermissionError("Maker-checker control prevents self-approval")
    if len(note.strip()) < 5:
        raise ValueError("An independent review note is required")
    row.status = "approved" if action == "approve" else "rejected"
    row.revision += 1
    row.decided_by, row.decided_at, row.decision_note = actor, utc_now(), note.strip()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"trade_quote.{action}",
        actor=actor, resource_key=row.decision_key,
        detail=f"{row.customer_code}; {row.destination_country_code}; revision {row.revision}"))
    session.commit()
    return row


def approved_trade_decision(session: Session, *, decision_key: str, customer_code: str,
                            destination_country_code: str, currency_code: str,
                            quotation_date: date, lines: list[dict]) -> OperationalQuoteTradeDecision:
    row = session.scalar(select(OperationalQuoteTradeDecision).where(
        OperationalQuoteTradeDecision.decision_key == decision_key,
        OperationalQuoteTradeDecision.status == "approved"))
    if not row or row.customer_code != customer_code or row.destination_country_code != destination_country_code or row.currency_code != currency_code or row.quotation_date != quotation_date:
        raise ValueError("An approved trade decision matching customer, destination, currency and quotation date is required")
    expected = json.loads(row.line_tax_rates_json)
    actual = {str(line["sku"]): str(Decimal(str(line["tax_rate"]))) for line in lines}
    if len(actual) != len(lines):
        raise ValueError("Each quotation SKU must be unique")
    if {sku: Decimal(rate) for sku, rate in expected.items()} != {sku: Decimal(rate) for sku, rate in actual.items()}:
        raise ValueError("Quotation SKUs and provisional tax rates must match the approved trade decision")
    return row
