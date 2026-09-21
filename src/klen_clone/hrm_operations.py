from __future__ import annotations

import json
import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .hrm import OperationalHrmEmployee, OperationalHrmImportBatch, OperationalHrmShift
from .operational import OperationalAuditEvent, OperationalBase, utc_now


class OperationalHrmDepartment(OperationalBase):
    __tablename__ = "operational_hrm_departments"
    __table_args__ = (UniqueConstraint("code", name="uq_hrm_department_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    department_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalHrmDesignation(OperationalBase):
    __tablename__ = "operational_hrm_designations"
    __table_args__ = (UniqueConstraint("code", name="uq_hrm_designation_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    designation_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    department_id: Mapped[int] = mapped_column(ForeignKey("operational_hrm_departments.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalHrmEmployeeProfile(OperationalBase):
    __tablename__ = "operational_hrm_employee_profiles"
    __table_args__ = (
        UniqueConstraint("employee_id", name="uq_hrm_profile_employee"),
        UniqueConstraint("employee_no", name="uq_hrm_profile_number"),
        CheckConstraint("employment_status IN ('active','on_leave','inactive','separated')", name="ck_hrm_employment_status"),
        CheckConstraint("approval_status IN ('active','pending','rejected')", name="ck_hrm_profile_approval"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("operational_hrm_employees.id"), nullable=False, index=True)
    employee_no: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("operational_hrm_departments.id"), index=True)
    designation_id: Mapped[int | None] = mapped_column(ForeignKey("operational_hrm_designations.id"), index=True)
    join_date: Mapped[date | None] = mapped_column(Date)
    employment_status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    approval_status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    pending_payload: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[str | None] = mapped_column(String(200))
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decision_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalHrmLeaveRequest(OperationalBase):
    __tablename__ = "operational_hrm_leave_requests"
    __table_args__ = (CheckConstraint("status IN ('pending','approved','rejected','cancelled')", name="ck_hrm_leave_status"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    leave_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("operational_hrm_employees.id"), nullable=False, index=True)
    leave_type: Mapped[str] = mapped_column(String(60), nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    requested_by: Mapped[str] = mapped_column(String(200), nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decision_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalHrmAttendanceCorrection(OperationalBase):
    __tablename__ = "operational_hrm_attendance_corrections"
    __table_args__ = (
        CheckConstraint("status IN ('pending','approved','rejected','cancelled')", name="ck_hrm_correction_status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    correction_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    attendance_id: Mapped[int] = mapped_column(ForeignKey("operational_hrm_attendance.id"), nullable=False, index=True)
    corrected_clock_in: Mapped[str | None] = mapped_column(String(40))
    corrected_clock_out: Mapped[str | None] = mapped_column(String(40))
    corrected_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    requested_by: Mapped[str] = mapped_column(String(200), nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decision_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalHrmHoliday(OperationalBase):
    __tablename__ = "operational_hrm_holidays"
    __table_args__ = (UniqueConstraint("holiday_date", "department_id", name="uq_hrm_holiday_scope"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    holiday_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("operational_hrm_departments.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)


class OperationalHrmShiftAssignment(OperationalBase):
    __tablename__ = "operational_hrm_shift_assignments"
    __table_args__ = (CheckConstraint("status IN ('active','inactive')", name="ck_hrm_shift_assignment_status"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assignment_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("operational_hrm_employees.id"), nullable=False, index=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("operational_hrm_shifts.id"), nullable=False, index=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)


DEPARTMENT_SEEDS = (
    ("ADMIN", "Administration"), ("FIN", "Finance & Accounts"),
    ("SALES", "Sales"), ("OPS", "Inventory & Logistics"), ("HR", "Human Resources"),
)


def _key() -> str:
    return str(uuid.uuid4())


def _audit(session: Session, event_type: str, actor: str, resource_key: str, detail: str) -> None:
    session.add(OperationalAuditEvent(event_key=_key(), event_type=event_type, actor=actor,
                                      resource_key=resource_key, detail=detail))


def _department_for_role(role: str | None) -> str:
    value = (role or "").casefold()
    if "account" in value or "finance" in value:
        return "FIN"
    if "sales" in value:
        return "SALES"
    if any(word in value for word in ("stock", "transfer", "warehouse", "logistic")):
        return "OPS"
    if "human" in value or value == "hr":
        return "HR"
    return "ADMIN"


def _code(value: str) -> str:
    clean = "".join(character if character.isalnum() else "_" for character in value.upper()).strip("_")
    return clean[:60] or "GENERAL"


def initialize_hrm_operations(session: Session, batch: OperationalHrmImportBatch | None) -> None:
    if batch is None:
        return
    departments = {}
    for code, name in DEPARTMENT_SEEDS:
        row = session.scalar(select(OperationalHrmDepartment).where(OperationalHrmDepartment.code == code))
        if row is None:
            row = OperationalHrmDepartment(department_key=_key(), code=code, name=name,
                                           status="active", revision=1, created_by="hrm_foundation")
            session.add(row); session.flush()
        departments[code] = row
    employees = list(session.scalars(select(OperationalHrmEmployee).where(
        OperationalHrmEmployee.batch_id == batch.id).order_by(OperationalHrmEmployee.id)))
    designations = {}
    for employee in employees:
        name = employee.role_name or "General Employee"
        code = _code(name)
        designation = session.scalar(select(OperationalHrmDesignation).where(OperationalHrmDesignation.code == code))
        if designation is None:
            department = departments[_department_for_role(employee.role_name)]
            designation = OperationalHrmDesignation(
                designation_key=_key(), code=code, name=name, department_id=department.id,
                status="active", revision=1, created_by="hrm_foundation",
            )
            session.add(designation); session.flush()
        designations[code] = designation
        if session.scalar(select(OperationalHrmEmployeeProfile).where(
            OperationalHrmEmployeeProfile.employee_id == employee.id)) is None:
            session.add(OperationalHrmEmployeeProfile(
                profile_key=_key(), employee_id=employee.id,
                employee_no=(employee.username or f"EMP-{employee.id:04d}").upper()[:60],
                department_id=designation.department_id, designation_id=designation.id,
                employment_status="active", approval_status="active", revision=1,
            ))
    session.commit()


def _employee(session: Session, employee_key: str) -> OperationalHrmEmployee:
    row = session.scalar(select(OperationalHrmEmployee).where(OperationalHrmEmployee.employee_key == employee_key))
    if row is None:
        raise ValueError("HRM employee not found")
    return row


def _department(session: Session, code: str | None) -> OperationalHrmDepartment | None:
    if not code:
        return None
    row = session.scalar(select(OperationalHrmDepartment).where(
        OperationalHrmDepartment.code == code, OperationalHrmDepartment.status == "active"))
    if row is None:
        raise ValueError("Active HRM department not found")
    return row


def _designation(session: Session, code: str | None) -> OperationalHrmDesignation | None:
    if not code:
        return None
    row = session.scalar(select(OperationalHrmDesignation).where(
        OperationalHrmDesignation.code == code, OperationalHrmDesignation.status == "active"))
    if row is None:
        raise ValueError("Active HRM designation not found")
    return row


def _shift(session: Session, name: str) -> OperationalHrmShift:
    row = session.scalar(select(OperationalHrmShift).where(OperationalHrmShift.name == name))
    if row is None:
        raise ValueError("HRM shift not found")
    return row


def create_department(session: Session, *, code: str, name: str, actor: str) -> OperationalHrmDepartment:
    normalized = _code(code)
    if session.scalar(select(OperationalHrmDepartment.id).where(OperationalHrmDepartment.code == normalized)):
        raise ValueError("Department code already exists")
    row = OperationalHrmDepartment(department_key=_key(), code=normalized, name=name.strip(),
                                   status="active", revision=1, created_by=actor)
    session.add(row); _audit(session, "hrm.department.created", actor, row.department_key, normalized)
    session.commit(); return row


def create_designation(session: Session, *, code: str, name: str, department_code: str,
                       actor: str) -> OperationalHrmDesignation:
    normalized = _code(code)
    if session.scalar(select(OperationalHrmDesignation.id).where(OperationalHrmDesignation.code == normalized)):
        raise ValueError("Designation code already exists")
    department = _department(session, department_code)
    row = OperationalHrmDesignation(designation_key=_key(), code=normalized, name=name.strip(),
        department_id=department.id, status="active", revision=1, created_by=actor)
    session.add(row); _audit(session, "hrm.designation.created", actor, row.designation_key, normalized)
    session.commit(); return row


def request_employee_change(session: Session, *, employee_key: str, employee_no: str,
                            department_code: str | None, designation_code: str | None,
                            join_date: date | None, employment_status: str, note: str,
                            actor: str) -> OperationalHrmEmployeeProfile:
    employee = _employee(session, employee_key)
    profile = session.scalar(select(OperationalHrmEmployeeProfile).where(
        OperationalHrmEmployeeProfile.employee_id == employee.id).with_for_update())
    if profile is None:
        raise ValueError("HRM employee profile not initialized")
    if profile.approval_status == "pending":
        raise ValueError("An employee change is already awaiting approval")
    department = _department(session, department_code)
    designation = _designation(session, designation_code)
    if designation and department and designation.department_id != department.id:
        raise ValueError("Designation does not belong to the selected department")
    payload = {"employee_no": employee_no.strip().upper(), "department_id": department.id if department else None,
               "designation_id": designation.id if designation else None,
               "join_date": join_date.isoformat() if join_date else None,
               "employment_status": employment_status, "note": note.strip()}
    profile.pending_payload = json.dumps(payload); profile.approval_status = "pending"
    profile.requested_by = actor; profile.decided_by = None; profile.decision_note = None
    profile.revision += 1; profile.updated_at = utc_now()
    _audit(session, "hrm.employee.change_requested", actor, profile.profile_key, note.strip())
    session.commit(); return profile


def decide_employee_change(session: Session, *, profile_key: str, action: str,
                           expected_revision: int, note: str, actor: str) -> OperationalHrmEmployeeProfile:
    profile = session.scalar(select(OperationalHrmEmployeeProfile).where(
        OperationalHrmEmployeeProfile.profile_key == profile_key).with_for_update())
    if profile is None: raise ValueError("HRM employee profile not found")
    if profile.revision != expected_revision: raise ValueError(f"Employee profile revision conflict; current revision is {profile.revision}")
    if profile.approval_status != "pending": raise ValueError("Employee profile is not awaiting approval")
    if profile.requested_by == actor: raise ValueError("The employee-change maker cannot approve or reject the same request")
    if action == "approve":
        payload = json.loads(profile.pending_payload or "{}")
        profile.employee_no = payload["employee_no"]; profile.department_id = payload.get("department_id")
        profile.designation_id = payload.get("designation_id")
        profile.join_date = date.fromisoformat(payload["join_date"]) if payload.get("join_date") else None
        profile.employment_status = payload["employment_status"]; profile.approval_status = "active"
    elif action == "reject":
        profile.approval_status = "rejected"
    else: raise ValueError("Unsupported employee decision")
    profile.pending_payload = None; profile.decided_by = actor; profile.decision_note = note.strip()
    profile.revision += 1; profile.updated_at = utc_now()
    _audit(session, f"hrm.employee.change_{action}d", actor, profile.profile_key, note.strip())
    session.commit(); return profile


def create_leave_request(session: Session, *, employee_key: str, leave_type: str,
                         starts_on: date, ends_on: date, reason: str, actor: str) -> OperationalHrmLeaveRequest:
    if ends_on < starts_on: raise ValueError("Leave end date cannot be before start date")
    employee = _employee(session, employee_key)
    overlap = session.scalar(select(OperationalHrmLeaveRequest.id).where(
        OperationalHrmLeaveRequest.employee_id == employee.id,
        OperationalHrmLeaveRequest.status.in_(("pending", "approved")),
        OperationalHrmLeaveRequest.starts_on <= ends_on,
        OperationalHrmLeaveRequest.ends_on >= starts_on,
    ))
    if overlap: raise ValueError("An overlapping leave request already exists")
    row = OperationalHrmLeaveRequest(leave_key=_key(), employee_id=employee.id, leave_type=leave_type,
        starts_on=starts_on, ends_on=ends_on, reason=reason.strip(), status="pending", requested_by=actor)
    session.add(row); _audit(session, "hrm.leave.requested", actor, row.leave_key, reason.strip())
    session.commit(); return row


def decide_leave(session: Session, *, leave_key: str, action: str, expected_revision: int,
                 note: str, actor: str) -> OperationalHrmLeaveRequest:
    row = session.scalar(select(OperationalHrmLeaveRequest).where(
        OperationalHrmLeaveRequest.leave_key == leave_key).with_for_update())
    if row is None: raise ValueError("Leave request not found")
    if row.revision != expected_revision: raise ValueError(f"Leave revision conflict; current revision is {row.revision}")
    if row.status != "pending": raise ValueError("Leave request is not awaiting approval")
    if row.requested_by == actor: raise ValueError("The leave-request maker cannot decide the same request")
    if action not in {"approve", "reject"}: raise ValueError("Unsupported leave decision")
    row.status = "approved" if action == "approve" else "rejected"
    row.decided_by = actor; row.decision_note = note.strip(); row.revision += 1
    _audit(session, f"hrm.leave.{action}d", actor, row.leave_key, note.strip())
    session.commit(); return row


def create_attendance_correction(session: Session, *, attendance_id: int,
                                 corrected_clock_in: str | None, corrected_clock_out: str | None,
                                 corrected_duration_minutes: int | None, reason: str,
                                 actor: str) -> OperationalHrmAttendanceCorrection:
    from .hrm import OperationalHrmAttendance
    if session.get(OperationalHrmAttendance, attendance_id) is None: raise ValueError("Attendance record not found")
    if not any((corrected_clock_in, corrected_clock_out, corrected_duration_minutes is not None)):
        raise ValueError("At least one corrected attendance value is required")
    pending = session.scalar(select(OperationalHrmAttendanceCorrection.id).where(
        OperationalHrmAttendanceCorrection.attendance_id == attendance_id,
        OperationalHrmAttendanceCorrection.status == "pending"))
    if pending: raise ValueError("An attendance correction is already pending")
    row = OperationalHrmAttendanceCorrection(correction_key=_key(), attendance_id=attendance_id,
        corrected_clock_in=corrected_clock_in, corrected_clock_out=corrected_clock_out,
        corrected_duration_minutes=corrected_duration_minutes, reason=reason.strip(),
        status="pending", requested_by=actor)
    session.add(row); _audit(session, "hrm.attendance.correction_requested", actor, row.correction_key, reason.strip())
    session.commit(); return row


def decide_attendance_correction(session: Session, *, correction_key: str, action: str,
                                 expected_revision: int, note: str, actor: str) -> OperationalHrmAttendanceCorrection:
    row = session.scalar(select(OperationalHrmAttendanceCorrection).where(
        OperationalHrmAttendanceCorrection.correction_key == correction_key).with_for_update())
    if row is None: raise ValueError("Attendance correction not found")
    if row.revision != expected_revision: raise ValueError(f"Attendance correction revision conflict; current revision is {row.revision}")
    if row.status != "pending": raise ValueError("Attendance correction is not awaiting approval")
    if row.requested_by == actor: raise ValueError("The attendance-correction maker cannot decide the same request")
    if action not in {"approve", "reject"}: raise ValueError("Unsupported attendance decision")
    row.status = "approved" if action == "approve" else "rejected"
    row.decided_by = actor; row.decision_note = note.strip(); row.revision += 1
    _audit(session, f"hrm.attendance.correction_{action}d", actor, row.correction_key, note.strip())
    session.commit(); return row


def create_holiday(session: Session, *, holiday_date: date, name: str,
                   department_code: str | None, actor: str) -> OperationalHrmHoliday:
    department = _department(session, department_code)
    existing = session.scalar(select(OperationalHrmHoliday.id).where(
        OperationalHrmHoliday.holiday_date == holiday_date,
        OperationalHrmHoliday.department_id == (department.id if department else None)))
    if existing: raise ValueError("A holiday already exists for this date and scope")
    row = OperationalHrmHoliday(holiday_key=_key(), holiday_date=holiday_date, name=name.strip(),
        department_id=department.id if department else None, status="active", revision=1, created_by=actor)
    session.add(row); _audit(session, "hrm.holiday.created", actor, row.holiday_key, name.strip())
    session.commit(); return row


def create_shift(session: Session, *, name: str, shift_type: str,
                 start_time: str | None, end_time: str | None, actor: str) -> OperationalHrmShift:
    if session.scalar(select(OperationalHrmShift.id).where(func.lower(OperationalHrmShift.name) == name.strip().lower())):
        raise ValueError("Shift name already exists")
    batch = session.scalar(select(OperationalHrmImportBatch).order_by(OperationalHrmImportBatch.id.desc()))
    if batch is None: raise ValueError("HRM import batch is not initialized")
    minimum = session.scalar(select(func.min(OperationalHrmShift.source_ordinal)).where(
        OperationalHrmShift.batch_id == batch.id))
    ordinal = min(int(minimum or 0), 0) - 1
    row = OperationalHrmShift(batch_id=batch.id, source_ordinal=ordinal, name=name.strip(),
        shift_type=shift_type.strip(), start_time=start_time, end_time=end_time, holiday=None)
    session.add(row); session.flush()
    _audit(session, "hrm.shift.created", actor, f"hrm-shift:{row.id}", name.strip())
    session.commit(); return row


def assign_shift(session: Session, *, employee_key: str, shift_name: str,
                 effective_from: date, effective_to: date | None, actor: str) -> OperationalHrmShiftAssignment:
    if effective_to and effective_to < effective_from: raise ValueError("Shift assignment end date cannot be before start date")
    employee = _employee(session, employee_key); shift = _shift(session, shift_name)
    for current in session.scalars(select(OperationalHrmShiftAssignment).where(
        OperationalHrmShiftAssignment.employee_id == employee.id,
        OperationalHrmShiftAssignment.status == "active")):
        current.status = "inactive"; current.revision += 1
    row = OperationalHrmShiftAssignment(assignment_key=_key(), employee_id=employee.id,
        shift_id=shift.id, effective_from=effective_from, effective_to=effective_to,
        status="active", revision=1, created_by=actor)
    session.add(row); _audit(session, "hrm.shift.assigned", actor, row.assignment_key, shift_name)
    session.commit(); return row


def hrm_operations_payload(session: Session, *, principal_username: str | None = None) -> dict:
    departments = list(session.scalars(select(OperationalHrmDepartment).order_by(OperationalHrmDepartment.code)))
    designations = list(session.scalars(select(OperationalHrmDesignation).order_by(OperationalHrmDesignation.name)))
    employees = {row.id: row for row in session.scalars(select(OperationalHrmEmployee))}
    shifts = {row.id: row for row in session.scalars(select(OperationalHrmShift))}
    profiles = list(session.scalars(select(OperationalHrmEmployeeProfile).order_by(OperationalHrmEmployeeProfile.employee_no)))
    leaves = list(session.scalars(select(OperationalHrmLeaveRequest).order_by(OperationalHrmLeaveRequest.created_at.desc())))
    corrections = list(session.scalars(select(OperationalHrmAttendanceCorrection).order_by(OperationalHrmAttendanceCorrection.created_at.desc())))
    holidays = list(session.scalars(select(OperationalHrmHoliday).order_by(OperationalHrmHoliday.holiday_date)))
    assignments = list(session.scalars(select(OperationalHrmShiftAssignment).order_by(OperationalHrmShiftAssignment.effective_from.desc())))
    department_by_id = {row.id: row for row in departments}; designation_by_id = {row.id: row for row in designations}
    own_employee = next((row for row in employees.values() if (row.username or "").casefold() == (principal_username or "").casefold()), None)
    return {
        "controls": {"department_count": len(departments), "designation_count": len(designations),
                     "profile_count": len(profiles), "pending_employee_changes": sum(row.approval_status == "pending" for row in profiles),
                     "pending_leave_requests": sum(row.status == "pending" for row in leaves),
                     "pending_attendance_corrections": sum(row.status == "pending" for row in corrections),
                     "holiday_count": sum(row.status == "active" for row in holidays),
                     "active_shift_assignments": sum(row.status == "active" for row in assignments)},
        "departments": [{"code": row.code, "name": row.name, "status": row.status, "revision": row.revision} for row in departments],
        "designations": [{"code": row.code, "name": row.name, "department_code": department_by_id[row.department_id].code,
                          "status": row.status, "revision": row.revision} for row in designations],
        "profiles": [{"profile_key": row.profile_key, "employee_key": employees[row.employee_id].employee_key,
                      "display_name": employees[row.employee_id].display_name, "employee_no": row.employee_no,
                      "department_code": department_by_id.get(row.department_id).code if row.department_id in department_by_id else None,
                      "designation_code": designation_by_id.get(row.designation_id).code if row.designation_id in designation_by_id else None,
                      "join_date": row.join_date, "employment_status": row.employment_status,
                      "approval_status": row.approval_status, "requested_by": row.requested_by,
                      "revision": row.revision} for row in profiles],
        "leave_requests": [{"leave_key": row.leave_key, "employee_key": employees[row.employee_id].employee_key,
                            "employee_name": employees[row.employee_id].display_name, "leave_type": row.leave_type,
                            "starts_on": row.starts_on, "ends_on": row.ends_on, "days": (row.ends_on-row.starts_on).days+1,
                            "reason": row.reason, "status": row.status, "requested_by": row.requested_by,
                            "decided_by": row.decided_by, "revision": row.revision} for row in leaves],
        "attendance_corrections": [{"correction_key": row.correction_key, "attendance_id": row.attendance_id,
                                    "corrected_clock_in": row.corrected_clock_in, "corrected_clock_out": row.corrected_clock_out,
                                    "corrected_duration_minutes": row.corrected_duration_minutes, "reason": row.reason,
                                    "status": row.status, "requested_by": row.requested_by,
                                    "decided_by": row.decided_by, "revision": row.revision} for row in corrections],
        "holidays": [{"holiday_key": row.holiday_key, "holiday_date": row.holiday_date, "name": row.name,
                      "department_code": department_by_id.get(row.department_id).code if row.department_id in department_by_id else None,
                      "status": row.status, "revision": row.revision} for row in holidays],
        "shift_assignments": [{"assignment_key": row.assignment_key,
                               "employee_key": employees[row.employee_id].employee_key,
                               "employee_name": employees[row.employee_id].display_name,
                               "shift_name": shifts[row.shift_id].name, "effective_from": row.effective_from,
                               "effective_to": row.effective_to, "status": row.status,
                               "revision": row.revision} for row in assignments],
        "self_service": {"matched": own_employee is not None,
                         "employee_key": own_employee.employee_key if own_employee else None,
                         "employee_name": own_employee.display_name if own_employee else None,
                         "leave_requests": [row.leave_key for row in leaves if own_employee and row.employee_id == own_employee.id]},
        "payroll": {"included": False, "record_count": 0},
    }
