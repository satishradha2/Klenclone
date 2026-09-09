from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .operational import OperationalBase, utc_now


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


PROMOTION_GATES = (
    "final source capture checksum verified",
    "every in-scope source row is promoted or has an approved exception",
    "source and operational business totals reconcile",
    "masters retain source identity and revision history",
    "posted history is corrected only by reversal or adjustment",
    "maker-checker approval recorded before activation",
)
