from __future__ import annotations

import json
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .operational import OperationalAuditEvent, OperationalBase, utc_now


REVIEW_STATUSES = ("in_review", "verified", "correction_required", "corrected", "rejected", "promoted")
REVIEW_SEVERITY_SCORE = {"critical": 300, "high": 200, "medium": 100}
INCOMPLETE_TRANSACTION_BLOCKER = (
    "This capture contains a transaction header but not every line, tax, payment and stock detail. "
    "Complete the final BizModo capture and reconciliation before promotion."
)
CONTROLLED_BATCH_BLOCKER = (
    "A reviewed historical transaction must be promoted by a checksum-bound migration batch and reconciled "
    "to opening stock and balances; it cannot be posted one row at a time."
)


def transaction_review_findings(*, total_amount, paid_amount, due_amount, source_status,
                                party_present: bool, location_present: bool,
                                line_count: int, line_subtotal, high_value_threshold) -> dict | None:
    """Return conservative, business-readable reasons to inspect a captured transaction."""
    total = Decimal(str(total_amount)) if total_amount is not None else None
    paid = Decimal(str(paid_amount)) if paid_amount is not None else None
    due = Decimal(str(due_amount)) if due_amount is not None else None
    lines = Decimal(str(line_subtotal)) if line_subtotal is not None else None
    threshold = Decimal(str(high_value_threshold)) if high_value_threshold is not None else None
    status = str(source_status or "").strip().lower()
    findings: list[dict] = []

    def add(severity: str, reason: str, priority_weight: int = 0) -> None:
        findings.append({"severity": severity, "reason": reason, "priority_weight": priority_weight})

    if total is None:
        add("critical", "The document total is missing.", 100)
    elif total < 0:
        add("critical", f"The document has a negative total of AED {total:.2f}.", 100)
    if paid is not None and total is not None:
        tolerance = max(Decimal("1.00"), abs(total) * Decimal("0.05"))
        if paid > total + tolerance:
            add("critical" if total <= 0 else "high",
                f"Amount paid (AED {paid:.2f}) is greater than the document total (AED {total:.2f}).", 80)
    if due is not None and due < Decimal("-0.01"):
        severity = "high" if abs(due) >= Decimal("1.00") else "medium"
        add(severity, f"The outstanding balance is negative (AED {due:.2f}), indicating an overpayment or allocation issue.", 20)
    if "partial" in status and due is not None and due <= Decimal("0.01"):
        add("high", "The document is marked Partially Paid but has no amount outstanding.", 40)
    if not party_present:
        add("high", "No customer or supplier is linked to this document.", 60)
    if not location_present:
        add("high", "No business location is linked to this document.", 60)
    if line_count == 0:
        add("critical", "The transaction header has no captured item lines.", 90)
    elif total is not None and lines is not None:
        difference = abs(total - lines)
        material_difference = max(Decimal("10.00"), abs(total) * Decimal("0.10"))
        if difference > material_difference:
            add("high", f"The document total differs from the captured item subtotal by AED {difference:.2f}.", 70)
    if total is not None and threshold is not None and threshold > 0 and total > threshold:
        add("medium", f"The total of AED {total:.2f} is unusually high for this document type and should be confirmed.", 10)
    if not findings:
        return None
    severity = max(findings, key=lambda item: REVIEW_SEVERITY_SCORE[item["severity"]])["severity"]
    return {
        "severity": severity,
        "score": REVIEW_SEVERITY_SCORE[severity] + sum(item["priority_weight"] for item in findings),
        "reasons": [item["reason"] for item in findings],
    }


class OperationalDataReview(OperationalBase):
    """Append-only correction overlay and governed decision for immutable source evidence."""

    __tablename__ = "operational_data_reviews"
    __table_args__ = (
        UniqueConstraint("entity_type", "source_record_key", name="uq_data_review_source"),
        CheckConstraint(
            "status IN ('in_review','verified','correction_required','corrected','rejected','promoted')",
            name="ck_data_review_status",
        ),
        CheckConstraint("revision >= 1", name="ck_data_review_revision"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_record_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    source_status: Mapped[str] = mapped_column(String(80), nullable=False)
    original_payload: Mapped[str] = mapped_column(Text, nullable=False)
    supplemental_payload: Mapped[str | None] = mapped_column(Text)
    corrected_payload: Mapped[str | None] = mapped_column(Text)
    superseded_correction_payload: Mapped[str | None] = mapped_column(Text)
    source_enrichment_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="in_review", index=True)
    rationale: Mapped[str | None] = mapped_column(Text)
    promotion_eligible: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    promotion_blocker: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(200))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promoted_by: Mapped[str | None] = mapped_column(String(200))
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


def review_payload(record: OperationalDataReview, *, posting_enabled: bool = False) -> dict:
    source_payload = json.loads(record.supplemental_payload) if record.supplemental_payload else json.loads(record.original_payload)
    return {
        "review_key": record.review_key,
        "entity_type": record.entity_type,
        "source_record_key": record.source_record_key,
        "source_status": record.source_status,
        "original_payload": json.loads(record.original_payload),
        "source_payload": source_payload,
        "source_enriched": bool(record.supplemental_payload),
        "source_enrichment_note": record.source_enrichment_note,
        "corrected_payload": json.loads(record.corrected_payload) if record.corrected_payload else None,
        "status": record.status,
        "rationale": record.rationale,
        "promotion_eligible": record.promotion_eligible,
        "promotion_available": bool(record.promotion_eligible and posting_enabled and record.status == "verified"),
        "promotion_blocker": record.promotion_blocker or (
            None if posting_enabled else "Production posting is globally disabled until cutover approval."
        ),
        "revision": record.revision,
        "created_by": record.created_by,
        "reviewed_by": record.reviewed_by,
    }


def enrich_review_source(session: Session, record: OperationalDataReview, *, source_payload: dict,
                         actor: str, note: str) -> bool:
    """Attach recovered source detail without altering the immutable evidence first reviewed."""
    current = json.loads(record.supplemental_payload) if record.supplemental_payload else None
    if current == source_payload:
        return False
    original = json.loads(record.original_payload)
    if original.get("lines") or not source_payload.get("lines"):
        return False
    if record.corrected_payload:
        record.superseded_correction_payload = record.corrected_payload
        record.corrected_payload = None
    record.supplemental_payload = json.dumps(source_payload, sort_keys=True, default=str)
    record.source_enrichment_note = note
    record.promotion_blocker = CONTROLLED_BATCH_BLOCKER
    if record.status not in {"rejected", "promoted"}:
        record.status = "in_review"
    record.reviewed_by = actor
    record.reviewed_at = utc_now()
    record.revision += 1
    _audit(session, record, actor, "source-enriched")
    return True


def start_review(session: Session, *, entity_type: str, source_record_key: str, source_status: str,
                 original_payload: dict, actor: str) -> OperationalDataReview:
    existing = session.scalar(select(OperationalDataReview).where(
        OperationalDataReview.entity_type == entity_type,
        OperationalDataReview.source_record_key == source_record_key,
    ))
    if existing:
        return existing
    transaction_record = entity_type in {"sale", "purchase", "sale_return", "purchase_return"}
    provisional_transaction = source_status.lower() == "provisional_overlay" and transaction_record
    record = OperationalDataReview(
        review_key=str(uuid.uuid4()), entity_type=entity_type, source_record_key=source_record_key,
        source_status=source_status, original_payload=json.dumps(original_payload, sort_keys=True, default=str),
        status="in_review", promotion_eligible=not transaction_record,
        promotion_blocker=(INCOMPLETE_TRANSACTION_BLOCKER if provisional_transaction else
                           CONTROLLED_BATCH_BLOCKER if transaction_record else None),
        created_by=actor,
    )
    session.add(record)
    session.flush()
    _audit(session, record, actor, "started")
    return record


def transition_review(session: Session, record: OperationalDataReview, *, action: str,
                      expected_revision: int, actor: str, rationale: str | None = None,
                      corrected_payload: dict | None = None, posting_enabled: bool = False) -> OperationalDataReview:
    if record.revision != expected_revision:
        raise ValueError(f"Review revision conflict; current revision is {record.revision}")
    if action == "verify":
        if record.status not in {"in_review", "corrected"}:
            raise ValueError("Only an in-review or corrected record can be verified")
        record.status = "verified"
    elif action == "flag-incorrect":
        if record.status not in {"in_review", "corrected", "verified"}:
            raise ValueError("This review cannot be reopened for correction")
        if not rationale:
            raise ValueError("Explain what is wrong before flagging the record")
        record.status = "correction_required"
    elif action == "correct":
        if record.status not in {"in_review", "correction_required", "corrected"}:
            raise ValueError("This review is not open for correction")
        if not corrected_payload:
            raise ValueError("A corrected value is required")
        record.corrected_payload = json.dumps(corrected_payload, sort_keys=True, default=str)
        record.status = "corrected"
    elif action == "reject":
        if not rationale:
            raise ValueError("Explain why the record is rejected")
        record.status = "rejected"
    elif action == "promote":
        if record.status != "verified":
            raise ValueError("Verify the record before promotion")
        if not record.promotion_eligible:
            raise ValueError(record.promotion_blocker or "This record is not eligible for promotion")
        if not posting_enabled:
            raise ValueError("Production posting is globally disabled until cutover approval")
        record.status = "promoted"
        record.promoted_by = actor
        record.promoted_at = utc_now()
    else:
        raise ValueError("Unsupported review action")
    record.rationale = rationale or record.rationale
    record.reviewed_by = actor
    record.reviewed_at = utc_now()
    record.revision += 1
    _audit(session, record, actor, action)
    return record


def _audit(session: Session, record: OperationalDataReview, actor: str, action: str) -> None:
    session.add(OperationalAuditEvent(
        event_key=str(uuid.uuid4()), event_type=f"data.review.{action}", actor=actor,
        resource_key=record.review_key,
        detail=json.dumps({"entity_type": record.entity_type, "source_record_key": record.source_record_key,
                           "revision": record.revision}, sort_keys=True),
    ))


def review_control_counts(session: Session) -> dict:
    return {
        "total": session.scalar(select(func.count(OperationalDataReview.id))) or 0,
        "open": session.scalar(select(func.count(OperationalDataReview.id)).where(
            OperationalDataReview.status.in_(("in_review", "correction_required", "corrected")))) or 0,
        "verified": session.scalar(select(func.count(OperationalDataReview.id)).where(
            OperationalDataReview.status == "verified")) or 0,
        "blocked": session.scalar(select(func.count(OperationalDataReview.id)).where(
            OperationalDataReview.promotion_eligible.is_(False))) or 0,
    }
