"""Non-posting, maker-checked commercial FX reference rates.

These records are not VAT exchange rates and cannot by themselves authorize a
foreign-currency transaction. Document-level FX and tax decisions are separate.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import CheckConstraint, Date, DateTime, Index, Integer, Numeric, String, Text, select, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from .country_catalog import currency_code as validate_currency_code
from .operational import OperationalAuditEvent, OperationalBase, utc_now


class OperationalFxRate(OperationalBase):
    __tablename__ = "operational_fx_rates"
    __table_args__ = (
        CheckConstraint("aed_per_unit > 0", name="ck_fx_rate_positive"),
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="ck_fx_rate_status"),
        Index("uq_fx_approved_currency_date", "currency_code", "rate_date", unique=True,
              postgresql_where=text("status = 'approved'"),
              sqlite_where=text("status = 'approved'")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rate_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    aed_per_unit: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    source_name: Mapped[str] = mapped_column(String(160), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)


def fx_rate_payload(row: OperationalFxRate) -> dict:
    return {
        "rate_key": row.rate_key, "currency_code": row.currency_code,
        "rate_date": row.rate_date, "aed_per_unit": row.aed_per_unit,
        "source_name": row.source_name, "source_reference": row.source_reference,
        "reason": row.reason, "status": row.status, "revision": row.revision,
        "created_by": row.created_by, "created_at": row.created_at,
        "decided_by": row.decided_by, "decided_at": row.decided_at,
        "decision_note": row.decision_note,
        "purpose": "commercial_reference_only",
    }


def prepare_fx_rate(session: Session, *, currency_code: str, rate_date: date,
                    aed_per_unit: Decimal, source_name: str,
                    source_reference: str, reason: str, actor: str) -> OperationalFxRate:
    code = validate_currency_code(currency_code)
    if code in {"AED", "XXX", "XTS"}:
        raise ValueError("Choose a circulating foreign currency; AED has a fixed identity rate")
    if rate_date > date.today():
        raise ValueError("Future-dated FX references are not permitted")
    rate = Decimal(str(aed_per_unit))
    if not rate.is_finite() or rate <= 0 or rate.as_tuple().exponent < -8:
        raise ValueError("AED per unit must be positive with at most eight decimal places")
    source, reference, explanation = source_name.strip(), source_reference.strip(), reason.strip()
    if not source or not reference or len(explanation) < 5:
        raise ValueError("Source name, evidence reference and business reason are required")
    row = OperationalFxRate(rate_key=str(uuid.uuid4()), currency_code=code,
        rate_date=rate_date, aed_per_unit=rate, source_name=source,
        source_reference=reference, reason=explanation, created_by=actor)
    session.add(row)
    session.flush()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="fx_rate.prepared",
        actor=actor, resource_key=row.rate_key,
        detail=f"{code}; {rate_date.isoformat()}; commercial reference; pending"))
    session.commit()
    return row


def decide_fx_rate(session: Session, row: OperationalFxRate, *, action: str,
                   expected_revision: int, note: str, actor: str) -> OperationalFxRate:
    if row.status != "pending" or action not in {"approve", "reject"}:
        raise ValueError("Only pending FX references can be decided")
    if row.revision != expected_revision:
        raise ValueError(f"FX reference revision conflict; current revision is {row.revision}")
    if row.created_by == actor:
        raise PermissionError("Maker-checker control prevents self-approval")
    if len(note.strip()) < 5:
        raise ValueError("An independent decision note is required")
    if action == "approve" and approved_fx_rate(session, row.currency_code, row.rate_date):
        raise ValueError("An approved FX reference already exists for that currency and date")
    row.status = "approved" if action == "approve" else "rejected"
    row.revision += 1
    row.decided_by, row.decided_at, row.decision_note = actor, utc_now(), note.strip()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"fx_rate.{action}",
        actor=actor, resource_key=row.rate_key,
        detail=f"{row.currency_code}; {row.rate_date.isoformat()}; revision {row.revision}"))
    session.commit()
    return row


def approved_fx_rate(session: Session, currency_code: str, rate_date: date) -> OperationalFxRate | None:
    code = validate_currency_code(currency_code)
    return session.scalar(select(OperationalFxRate).where(
        OperationalFxRate.currency_code == code,
        OperationalFxRate.rate_date == rate_date,
        OperationalFxRate.status == "approved"))


def foreign_invoice_fx_exposure(session: Session, invoice) -> dict:
    """Read-only AED reference for a held foreign draft, never a settlement rate."""
    code = validate_currency_code(invoice.currency_code)
    if code == "AED":
        return {
            "state": "aed_denominated", "currency_code": code,
            "foreign_amount": Decimal(invoice.total_amount),
            "rate_date": invoice.invoice_date, "rate_key": None,
            "aed_per_unit": Decimal("1"),
            "aed_reference_amount": Decimal(invoice.total_amount).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP),
            "source_name": None, "source_reference": None,
            "settlement_enabled": False, "posting_enabled": False,
        }
    rate = approved_fx_rate(session, code, invoice.invoice_date)
    result = {
        "state": "reference_only" if rate else "rate_missing",
        "currency_code": code,
        "foreign_amount": Decimal(invoice.total_amount),
        "rate_date": invoice.invoice_date,
        "rate_key": rate.rate_key if rate else None,
        "aed_per_unit": rate.aed_per_unit if rate else None,
        "aed_reference_amount": (
            (Decimal(invoice.total_amount) * Decimal(rate.aed_per_unit)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP) if rate else None
        ),
        "source_name": rate.source_name if rate else None,
        "source_reference": rate.source_reference if rate else None,
        "settlement_enabled": False,
        "posting_enabled": False,
    }
    return result
