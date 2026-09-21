from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, or_, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .models import RawFileManifest, RawRecord, SourceSnapshot
from .operational import OperationalAuditEvent, OperationalBase, utc_now


class OperationalHrmImportBatch(OperationalBase):
    __tablename__ = "operational_hrm_import_batches"
    __table_args__ = (
        UniqueConstraint("source_snapshot", name="uq_operational_hrm_snapshot"),
        CheckConstraint("payroll_included = false", name="ck_operational_hrm_no_payroll"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    source_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    source_atomic: Mapped[bool] = mapped_column(Boolean, nullable=False)
    test_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    payroll_included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalHrmEmployee(OperationalBase):
    __tablename__ = "operational_hrm_employees"
    __table_args__ = (UniqueConstraint("batch_id", "source_ordinal", name="uq_operational_hrm_employee_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("operational_hrm_import_batches.id"), nullable=False, index=True)
    source_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    employee_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(200), index=True)
    display_name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    role_name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="captured_test")


class OperationalHrmShift(OperationalBase):
    __tablename__ = "operational_hrm_shifts"
    __table_args__ = (UniqueConstraint("batch_id", "source_ordinal", name="uq_operational_hrm_shift_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("operational_hrm_import_batches.id"), nullable=False, index=True)
    source_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    shift_type: Mapped[str | None] = mapped_column(String(120))
    start_time: Mapped[str | None] = mapped_column(String(40))
    end_time: Mapped[str | None] = mapped_column(String(40))
    holiday: Mapped[str | None] = mapped_column(String(200))


class OperationalHrmAttendance(OperationalBase):
    __tablename__ = "operational_hrm_attendance"
    __table_args__ = (UniqueConstraint("batch_id", "source_ordinal", name="uq_operational_hrm_attendance_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("operational_hrm_import_batches.id"), nullable=False, index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("operational_hrm_employees.id"), index=True)
    source_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    attendance_date: Mapped[date | None] = mapped_column(Date, index=True)
    employee_name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    clock_in: Mapped[str | None] = mapped_column(String(40))
    clock_out: Mapped[str | None] = mapped_column(String(40))
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    duration_display: Mapped[str | None] = mapped_column(String(80))
    shift_name: Mapped[str | None] = mapped_column(String(200), index=True)
    quality_status: Mapped[str] = mapped_column(String(30), nullable=False)
    quality_flags: Mapped[str] = mapped_column(Text, nullable=False, default="[]")


HRM_FILES = {
    "employees": "users.csv",
    "attendance": "hrm_attendance_2026.csv",
    "shifts": "hrm_shifts.csv",
}
_CLOCK_PREFIX = re.compile(r"^(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2})")


def _clean(value) -> str | None:
    text_value = str(value or "").strip()
    return text_value or None


def _normal(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def _parse_date(value) -> date | None:
    text_value = _clean(value)
    if not text_value:
        return None
    for pattern in ("%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text_value, pattern).date()
        except ValueError:
            continue
    return None


def _clock(value) -> tuple[str | None, bool]:
    text_value = _clean(value)
    if not text_value:
        return None, False
    match = _CLOCK_PREFIX.match(text_value)
    if match:
        return match.group(1), match.group(1) != text_value
    return text_value[:40], False


def _duration_minutes(value) -> int | None:
    text_value = _clean(value)
    if not text_value:
        return None
    hours = re.search(r"(\d+)\s*h", text_value, re.IGNORECASE)
    minutes = re.search(r"(\d+)\s*m", text_value, re.IGNORECASE)
    seconds = re.search(r"(\d+)\s*s", text_value, re.IGNORECASE)
    if not any((hours, minutes, seconds)):
        return None
    total_seconds = (int(hours.group(1)) if hours else 0) * 3600
    total_seconds += (int(minutes.group(1)) if minutes else 0) * 60
    total_seconds += int(seconds.group(1)) if seconds else 0
    return total_seconds // 60


def _records(clone_session: Session, snapshot_id: int, relative_path: str) -> tuple[RawFileManifest | None, list[RawRecord]]:
    manifest = clone_session.scalar(select(RawFileManifest).where(
        RawFileManifest.snapshot_id == snapshot_id,
        RawFileManifest.relative_path == relative_path,
    ))
    if manifest is None:
        return None, []
    records = list(clone_session.scalars(select(RawRecord).where(
        RawRecord.manifest_id == manifest.id,
        RawRecord.is_presentation_row.is_(False),
    ).order_by(RawRecord.ordinal)))
    return manifest, records


def initialize_hrm_test_data(clone_session: Session, operational_session: Session,
                             snapshot: SourceSnapshot) -> OperationalHrmImportBatch | None:
    existing = operational_session.scalar(select(OperationalHrmImportBatch).where(
        OperationalHrmImportBatch.source_snapshot == snapshot.name,
    ))
    if existing is not None:
        return existing

    source = {name: _records(clone_session, snapshot.id, path) for name, path in HRM_FILES.items()}
    manifests = [manifest for manifest, _ in source.values() if manifest is not None]
    if not manifests:
        return None
    digest = hashlib.sha256("|".join(sorted(manifest.sha256 for manifest in manifests)).encode()).hexdigest()
    batch = OperationalHrmImportBatch(
        batch_key=f"hrm-{digest[:24]}", source_snapshot=snapshot.name, source_digest=digest,
        source_atomic=snapshot.is_atomic, test_data=True, payroll_included=False,
    )
    operational_session.add(batch)
    operational_session.flush()

    _, employee_rows = source["employees"]
    for raw in employee_rows:
        payload = raw.payload if isinstance(raw.payload, dict) else {}
        username = _clean(payload.get("Username"))
        display_name = _clean(payload.get("Name")) or username or f"Source employee {raw.ordinal}"
        operational_session.add(OperationalHrmEmployee(
            batch_id=batch.id, source_ordinal=raw.ordinal,
            employee_key=username or f"source-employee-{raw.ordinal}", username=username,
            display_name=display_name, role_name=_clean(payload.get("Role")),
            email=_clean(payload.get("Email")), status="captured_test",
        ))
    operational_session.flush()
    employees = list(operational_session.scalars(select(OperationalHrmEmployee).where(
        OperationalHrmEmployee.batch_id == batch.id,
    )))
    employee_lookup = {}
    for employee in employees:
        for value in (employee.display_name, employee.username):
            if _normal(value):
                employee_lookup[_normal(value)] = employee.id

    _, shift_rows = source["shifts"]
    for raw in shift_rows:
        payload = raw.payload if isinstance(raw.payload, dict) else {}
        operational_session.add(OperationalHrmShift(
            batch_id=batch.id, source_ordinal=raw.ordinal,
            name=_clean(payload.get("Name")) or f"Source shift {raw.ordinal}",
            shift_type=_clean(payload.get("Shift Type")), start_time=_clean(payload.get("Start time")),
            end_time=_clean(payload.get("End time")), holiday=_clean(payload.get("Holiday")),
        ))

    _, attendance_rows = source["attendance"]
    for raw in attendance_rows:
        payload = raw.payload if isinstance(raw.payload, dict) else {}
        employee_name = _clean(payload.get("Employee")) or "Employee not identified"
        attendance_date = _parse_date(payload.get("Date"))
        clock_in, clock_in_normalized = _clock(payload.get("Clock In"))
        clock_out, clock_out_normalized = _clock(payload.get("Clock Out"))
        duration_display = _clean(payload.get("Work Duration"))
        duration_minutes = _duration_minutes(duration_display)
        flags = []
        employee_id = employee_lookup.get(_normal(employee_name))
        if employee_id is None:
            flags.append("employee_link_unresolved")
        if attendance_date is None:
            flags.append("attendance_date_unparsed")
        if clock_in is None:
            flags.append("clock_in_missing")
        if clock_out is None:
            flags.append("clock_out_missing")
        if duration_minutes is None:
            flags.append("duration_unparsed")
        if clock_in_normalized or clock_out_normalized:
            flags.append("clock_text_normalized_for_display")
        blocking_flags = {"employee_link_unresolved", "attendance_date_unparsed", "clock_in_missing", "duration_unparsed"}
        quality_status = "review_required" if blocking_flags.intersection(flags) else ("normalized" if flags else "verified")
        operational_session.add(OperationalHrmAttendance(
            batch_id=batch.id, employee_id=employee_id, source_ordinal=raw.ordinal,
            attendance_date=attendance_date, employee_name=employee_name,
            clock_in=clock_in, clock_out=clock_out, duration_minutes=duration_minutes,
            duration_display=duration_display, shift_name=_clean(payload.get("Shift")),
            quality_status=quality_status, quality_flags=json.dumps(flags),
        ))

    operational_session.add(OperationalAuditEvent(
        event_key=f"hrm-import:{digest[:24]}", event_type="hrm.test_data_initialized",
        actor="hrm_import", resource_key=batch.batch_key,
        detail=(f"snapshot={snapshot.name}; employees={len(employee_rows)}; attendance={len(attendance_rows)}; "
                f"shifts={len(shift_rows)}; payroll excluded; source remains immutable"),
    ))
    operational_session.commit()
    return batch


def hrm_payload(session: Session, *, query: str = "", limit: int = 500, offset: int = 0) -> dict:
    batch = session.scalar(select(OperationalHrmImportBatch).order_by(
        OperationalHrmImportBatch.imported_at.desc(), OperationalHrmImportBatch.id.desc(),
    ))
    if batch is None:
        return {
            "available": False, "employees": [], "attendance": [], "shifts": [],
            "controls": {"employee_count": 0, "attendance_count": 0, "shift_count": 0},
            "payroll": {"included": False, "record_count": 0},
        }
    employee_filters = [OperationalHrmEmployee.batch_id == batch.id]
    attendance_filters = [OperationalHrmAttendance.batch_id == batch.id]
    if query.strip():
        pattern = f"%{query.strip()}%"
        employee_filters.append(or_(
            OperationalHrmEmployee.display_name.ilike(pattern),
            OperationalHrmEmployee.username.ilike(pattern),
            OperationalHrmEmployee.role_name.ilike(pattern),
        ))
        attendance_filters.append(or_(
            OperationalHrmAttendance.employee_name.ilike(pattern),
            OperationalHrmAttendance.shift_name.ilike(pattern),
        ))
    employees = list(session.scalars(select(OperationalHrmEmployee).where(
        *employee_filters).order_by(OperationalHrmEmployee.display_name)))
    attendance_total = session.scalar(select(func.count(OperationalHrmAttendance.id)).where(*attendance_filters)) or 0
    attendance = list(session.scalars(select(OperationalHrmAttendance).where(
        *attendance_filters).order_by(
        OperationalHrmAttendance.attendance_date.desc(), OperationalHrmAttendance.source_ordinal.desc(),
    ).offset(offset).limit(limit)))
    shifts = list(session.scalars(select(OperationalHrmShift).where(
        OperationalHrmShift.batch_id == batch.id).order_by(OperationalHrmShift.name)))
    aggregate = session.execute(select(
        func.count(OperationalHrmAttendance.id),
        func.min(OperationalHrmAttendance.attendance_date),
        func.max(OperationalHrmAttendance.attendance_date),
        func.coalesce(func.sum(OperationalHrmAttendance.duration_minutes), 0),
        func.count(OperationalHrmAttendance.employee_id),
    ).where(OperationalHrmAttendance.batch_id == batch.id)).one()
    quality_rows = dict(session.execute(select(
        OperationalHrmAttendance.quality_status, func.count(OperationalHrmAttendance.id),
    ).where(OperationalHrmAttendance.batch_id == batch.id).group_by(
        OperationalHrmAttendance.quality_status)).all())
    return {
        "available": True,
        "batch": {
            "batch_key": batch.batch_key, "source_snapshot": batch.source_snapshot,
            "source_digest": batch.source_digest, "source_atomic": batch.source_atomic,
            "test_data": batch.test_data, "imported_at": batch.imported_at,
        },
        "controls": {
            "employee_count": len(employees) if query.strip() else session.scalar(select(func.count(
                OperationalHrmEmployee.id)).where(OperationalHrmEmployee.batch_id == batch.id)) or 0,
            "attendance_count": aggregate[0], "filtered_attendance_count": attendance_total,
            "shift_count": len(shifts), "period_start": aggregate[1], "period_end": aggregate[2],
            "duration_minutes": aggregate[3], "linked_attendance_count": aggregate[4],
            "quality_counts": quality_rows,
        },
        "employees": [{
            "employee_key": row.employee_key, "username": row.username, "display_name": row.display_name,
            "role_name": row.role_name, "email": row.email, "status": row.status,
        } for row in employees],
        "attendance": [{
            "id": row.id, "source_ordinal": row.source_ordinal, "attendance_date": row.attendance_date,
            "employee_name": row.employee_name, "clock_in": row.clock_in, "clock_out": row.clock_out,
            "duration_minutes": row.duration_minutes, "duration_display": row.duration_display,
            "shift_name": row.shift_name, "quality_status": row.quality_status,
        } for row in attendance],
        "shifts": [{
            "name": row.name, "shift_type": row.shift_type, "start_time": row.start_time,
            "end_time": row.end_time, "holiday": row.holiday,
        } for row in shifts],
        "payroll": {
            "included": False, "record_count": 0,
            "reason": "Payroll is outside the confirmed ERP scope and is never imported into this workspace.",
        },
        "privacy": {
            "ip_addresses_displayed": False, "location_evidence_displayed": False,
            "source_actions_imported": False,
        },
    }
