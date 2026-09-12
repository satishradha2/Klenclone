from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .operational import OperationalAuditEvent, OperationalBase, utc_now


class OperationalPromotionBatch(OperationalBase):
    """Controlled bridge from immutable clone evidence to operational ERP records."""

    __tablename__ = "operational_promotion_batches"
    __table_args__ = (
        CheckConstraint("status IN ('planned','validated','approved','executed','rolled_back')", name="ck_promotion_batch_status"),
        CheckConstraint("posting_enabled = false", name="ck_promotion_batch_no_posting"),
        CheckConstraint("expected_records >= 0 AND mapped_records >= 0 AND exception_records >= 0", name="ck_promotion_batch_counts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source_system: Mapped[str] = mapped_column(String(80), nullable=False)
    source_snapshot_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    source_manifest_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="planned", nullable=False, index=True)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expected_records: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mapped_records: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    exception_records: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OperationalSourceLineage(OperationalBase):
    __tablename__ = "operational_source_lineage"
    __table_args__ = (
        UniqueConstraint("source_snapshot_name", "entity_type", "source_record_key", name="uq_operational_source_identity"),
        UniqueConstraint("operational_table", "operational_record_key", name="uq_operational_promoted_identity"),
        CheckConstraint("promotion_status IN ('planned','promoted','exception')", name="ck_source_lineage_promotion_status"),
        CheckConstraint("lifecycle_status IN ('active','inactive','voided','historical')", name="ck_source_lineage_lifecycle_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("operational_promotion_batches.id"), nullable=False, index=True)
    source_system: Mapped[str] = mapped_column(String(80), nullable=False)
    source_snapshot_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_record_key: Mapped[str] = mapped_column(String(200), nullable=False)
    source_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    operational_table: Mapped[str] = mapped_column(String(120), nullable=False)
    operational_record_key: Mapped[str] = mapped_column(String(200), nullable=False)
    promoted_checksum: Mapped[str | None] = mapped_column(String(64))
    promotion_status: Mapped[str] = mapped_column(String(20), nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(20), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OperationalPromotionException(OperationalBase):
    __tablename__ = "operational_promotion_exceptions"
    __table_args__ = (
        UniqueConstraint("batch_id", "entity_type", "source_record_key", name="uq_promotion_exception_source"),
        CheckConstraint("status IN ('open','resolved','waived')", name="ck_promotion_exception_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("operational_promotion_batches.id"), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_record_key: Mapped[str] = mapped_column(String(200), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    resolved_by: Mapped[str | None] = mapped_column(String(200))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def lifecycle_actions(record_class: str, status: str, *, referenced: bool = True,
                      source_promoted: bool = True) -> tuple[str, ...]:
    """Return actions allowed by the enterprise record-lifecycle policy."""
    if record_class == "master":
        if status == "active":
            actions = ["edit", "deactivate"]
            if not referenced and not source_promoted:
                actions.append("delete")
            return tuple(actions)
        if status == "inactive":
            return ("reactivate", "edit")
    if record_class == "transaction":
        if status == "draft":
            return ("edit", "cancel", "delete")
        if status in {"submitted", "approved"}:
            return ("cancel",)
        if status == "posted":
            return ("reverse",)
        if status in {"reversed", "cancelled", "historical"}:
            return ("view",)
    raise ValueError(f"Unsupported lifecycle policy state: {record_class}/{status}")


def promotion_control_counts(session: Session) -> dict:
    return {
        "batches": session.scalar(select(func.count(OperationalPromotionBatch.id))) or 0,
        "mapped_records": session.scalar(select(func.count(OperationalSourceLineage.id)).where(
            OperationalSourceLineage.promotion_status == "promoted")) or 0,
        "open_exceptions": session.scalar(select(func.count(OperationalPromotionException.id)).where(
            OperationalPromotionException.status == "open")) or 0,
    }


def plan_historical_promotion(session: Session, *, source_system: str, source_snapshot_name: str,
                              source_manifest_checksum: str, expected_records: int,
                              exceptions: list[dict], actor: str) -> dict:
    """Create an idempotent, non-posting batch and quarantine every known exception."""
    normalized = sorted(({"source_exception_id": int(item["source_exception_id"]),
                          "source_kind": str(item["source_kind"]),
                          "reason_code": str(item["reason_code"]),
                          "detail": item["detail"]} for item in exceptions),
                        key=lambda item: item["source_exception_id"])
    exception_checksum = hashlib.sha256(json.dumps(
        normalized, default=str, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    batch_key = f"HISTORY-{source_manifest_checksum[:12].upper()}-{exception_checksum[:12].upper()}"
    existing = session.scalar(select(OperationalPromotionBatch).where(
        OperationalPromotionBatch.batch_key == batch_key))
    if existing:
        return {"batch_key": existing.batch_key, "status": existing.status,
                "expected_records": existing.expected_records, "mapped_records": existing.mapped_records,
                "exception_records": existing.exception_records, "posting_enabled": False,
                "idempotent_replay": True}
    batch = OperationalPromotionBatch(
        batch_key=batch_key, source_system=source_system, source_snapshot_name=source_snapshot_name,
        source_manifest_checksum=source_manifest_checksum, status="planned", posting_enabled=False,
        expected_records=expected_records, mapped_records=0, exception_records=len(normalized),
        created_by=actor,
    )
    session.add(batch)
    session.flush()
    session.add_all([OperationalPromotionException(
        batch_id=batch.id, entity_type=item["source_kind"],
        source_record_key=f'exception:{item["source_exception_id"]}',
        reason_code=item["reason_code"], detail=json.dumps(item["detail"], default=str, sort_keys=True),
        status="open",
    ) for item in normalized])
    session.add(OperationalAuditEvent(
        event_key=str(uuid.uuid4()), event_type="promotion.planned", actor=actor,
        resource_key=batch_key,
        detail=json.dumps({"expected_records": expected_records,
                           "exception_records": len(normalized),
                           "exception_checksum": exception_checksum,
                           "posting_enabled": False}, sort_keys=True),
    ))
    session.flush()
    return {"batch_key": batch.batch_key, "status": batch.status,
            "expected_records": batch.expected_records, "mapped_records": batch.mapped_records,
            "exception_records": batch.exception_records, "posting_enabled": False,
            "idempotent_replay": False}


def resolve_promotion_exception(session: Session, *, batch_key: str, source_exception_id: int,
                                actor: str, resolution_code: str, evidence: dict) -> dict:
    """Resolve one operational quarantine item without changing its source evidence.

    Resolution is allowed only with a structured evidence payload. The original exception
    detail remains immutable; the decision and an evidence checksum are written to the
    operational audit trail. This function never maps, promotes, or posts a source row.
    """
    if not actor.strip():
        raise ValueError("actor is required")
    if not resolution_code.strip():
        raise ValueError("resolution_code is required")
    if not isinstance(evidence, dict) or not evidence:
        raise ValueError("structured resolution evidence is required")

    batch = session.scalar(select(OperationalPromotionBatch).where(
        OperationalPromotionBatch.batch_key == batch_key))
    if batch is None:
        raise ValueError("promotion batch not found")
    source_record_key = f"exception:{int(source_exception_id)}"
    exception = session.scalar(select(OperationalPromotionException).where(
        OperationalPromotionException.batch_id == batch.id,
        OperationalPromotionException.source_record_key == source_record_key,
    ))
    if exception is None:
        raise ValueError("promotion exception not found")
    if exception.status == "resolved":
        return {"batch_key": batch_key, "source_record_key": source_record_key,
                "status": "resolved", "posting_enabled": False, "idempotent_replay": True}
    if exception.status != "open":
        raise ValueError(f"promotion exception is {exception.status}")

    normalized_evidence = json.loads(json.dumps(evidence, default=str, sort_keys=True))
    evidence_checksum = hashlib.sha256(json.dumps(
        normalized_evidence, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    exception.status = "resolved"
    exception.resolved_by = actor.strip()
    exception.resolved_at = utc_now()
    session.add(OperationalAuditEvent(
        event_key=str(uuid.uuid4()), event_type="promotion.exception.resolved",
        actor=actor.strip(), resource_key=source_record_key,
        detail=json.dumps({
            "batch_key": batch_key,
            "reason_code": exception.reason_code,
            "resolution_code": resolution_code.strip(),
            "evidence": normalized_evidence,
            "evidence_checksum": evidence_checksum,
            "source_exception_modified": False,
            "mapping_performed": False,
            "posting_enabled": False,
        }, sort_keys=True),
    ))
    session.flush()
    return {"batch_key": batch_key, "source_record_key": source_record_key,
            "status": "resolved", "resolution_code": resolution_code.strip(),
            "evidence_checksum": evidence_checksum, "posting_enabled": False,
            "idempotent_replay": False}


PROMOTION_GATES = (
    "final source capture checksum verified",
    "every in-scope source row is promoted or has an approved exception",
    "source and operational business totals reconcile",
    "masters retain source identity and revision history",
    "posted history is corrected only by reversal or adjustment",
    "maker-checker approval recorded before activation",
)
