from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .operational import OperationalAuditEvent, OperationalBase, utc_now


class OperationalSourceVerificationBatch(OperationalBase):
    """Audited approval of immutable source evidence; never an ERP posting batch."""

    __tablename__ = "operational_source_verification_batches"
    __table_args__ = (
        CheckConstraint("status IN ('verified','revoked')", name="ck_source_verification_batch_status"),
        CheckConstraint("expected_records >= 0 AND verified_records >= 0", name="ck_source_verification_batch_counts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    source_system: Mapped[str] = mapped_column(String(80), nullable=False)
    source_snapshot_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    source_manifest_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_records: Mapped[int] = mapped_column(Integer, nullable=False)
    verified_records: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="verified")
    verification_basis: Mapped[str] = mapped_column(Text, nullable=False)
    verified_by: Mapped[str] = mapped_column(String(200), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalSourceVerification(OperationalBase):
    __tablename__ = "operational_source_verifications"
    __table_args__ = (
        UniqueConstraint("source_snapshot_name", "source_raw_record_id", name="uq_source_verification_raw_record"),
        CheckConstraint("status IN ('verified','revoked')", name="ck_source_verification_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    verification_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    batch_id: Mapped[int] = mapped_column(ForeignKey("operational_source_verification_batches.id"), nullable=False, index=True)
    source_snapshot_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    source_raw_record_id: Mapped[int] = mapped_column(Integer, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source_file: Mapped[str] = mapped_column(String(500), nullable=False)
    source_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="verified", index=True)
    verified_by: Mapped[str] = mapped_column(String(200), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


def _payload_digest(payload) -> str:
    encoded = json.dumps(payload, default=str, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verify_source_records(session: Session, *, source_system: str, source_snapshot_name: str,
                          source_manifest_checksum: str, records: list[dict], actor: str,
                          verification_basis: str) -> dict:
    """Register a checksum for every immutable raw record under one explicit approval."""
    prepared = []
    seen = set()
    for record in sorted(records, key=lambda item: int(item["source_raw_record_id"])):
        raw_id = int(record["source_raw_record_id"])
        if raw_id in seen:
            raise ValueError(f"Duplicate source raw record id: {raw_id}")
        seen.add(raw_id)
        prepared.append({**record, "source_raw_record_id": raw_id,
                         "payload_sha256": _payload_digest(record["payload"])})
    evidence_checksum = hashlib.sha256("".join(
        f'{row["source_raw_record_id"]}:{row["payload_sha256"]}\n' for row in prepared
    ).encode("utf-8")).hexdigest()
    batch_key = f"SOURCE-VERIFY-{source_manifest_checksum[:12].upper()}-{evidence_checksum[:12].upper()}"
    existing = session.scalar(select(OperationalSourceVerificationBatch).where(
        OperationalSourceVerificationBatch.batch_key == batch_key))
    if existing:
        if existing.expected_records != len(prepared) or existing.verified_records != len(prepared):
            raise ValueError("Existing source-verification batch does not reconcile to the supplied evidence")
        return {"batch_key": batch_key, "status": existing.status,
                "expected_records": existing.expected_records,
                "verified_records": existing.verified_records,
                "evidence_checksum": existing.evidence_checksum, "idempotent_replay": True}
    existing_identities = session.scalar(select(func.count(OperationalSourceVerification.id)).where(
        OperationalSourceVerification.source_snapshot_name == source_snapshot_name)) or 0
    if existing_identities:
        raise ValueError("This source snapshot already has a different verification registry")
    now = utc_now()
    batch = OperationalSourceVerificationBatch(
        batch_key=batch_key, source_system=source_system, source_snapshot_name=source_snapshot_name,
        source_manifest_checksum=source_manifest_checksum, evidence_checksum=evidence_checksum,
        expected_records=len(prepared), verified_records=len(prepared), status="verified",
        verification_basis=verification_basis, verified_by=actor, verified_at=now,
    )
    session.add(batch)
    session.flush()
    session.add_all([OperationalSourceVerification(
        verification_key=str(uuid.uuid4()), batch_id=batch.id,
        source_snapshot_name=source_snapshot_name,
        source_raw_record_id=row["source_raw_record_id"], entity_type=str(row["entity_type"]),
        source_file=str(row["source_file"]), source_ordinal=int(row["source_ordinal"]),
        manifest_sha256=str(row["manifest_sha256"]), payload_sha256=row["payload_sha256"],
        status="verified", verified_by=actor, verified_at=now,
    ) for row in prepared])
    session.add(OperationalAuditEvent(
        event_key=str(uuid.uuid4()), event_type="source.verification.completed", actor=actor,
        resource_key=batch_key,
        detail=json.dumps({"source_snapshot_name": source_snapshot_name,
                           "source_manifest_checksum": source_manifest_checksum,
                           "evidence_checksum": evidence_checksum,
                           "verified_records": len(prepared)}, sort_keys=True),
    ))
    session.flush()
    return {"batch_key": batch_key, "status": batch.status,
            "expected_records": batch.expected_records, "verified_records": batch.verified_records,
            "evidence_checksum": batch.evidence_checksum, "idempotent_replay": False}


def source_verification_counts(session: Session) -> dict:
    return {
        "batches": session.scalar(select(func.count(OperationalSourceVerificationBatch.id))) or 0,
        "verified_records": session.scalar(select(func.count(OperationalSourceVerification.id)).where(
            OperationalSourceVerification.status == "verified")) or 0,
        "revoked_records": session.scalar(select(func.count(OperationalSourceVerification.id)).where(
            OperationalSourceVerification.status == "revoked")) or 0,
    }
