from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .hrm import OperationalHrmEmployee
from .operational import OperationalAuditEvent, OperationalBase, utc_now


class OperationalHrmWorkforceRequest(OperationalBase):
    __tablename__ = "operational_hrm_workforce_requests"
    __table_args__ = (CheckConstraint("status IN ('submitted','approved','rejected')", name="ck_hrm_workforce_status"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    request_no: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    request_type: Mapped[str] = mapped_column(String(30), nullable=False)
    department_code: Mapped[str] = mapped_column(String(40), nullable=False)
    position_title: Mapped[str] = mapped_column(String(200), nullable=False)
    headcount: Mapped[int] = mapped_column(Integer, nullable=False)
    needed_by: Mapped[date] = mapped_column(Date, nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="submitted", nullable=False, index=True)
    requested_by: Mapped[str] = mapped_column(String(200), nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decision_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalHrmCandidate(OperationalBase):
    __tablename__ = "operational_hrm_candidates"
    __table_args__ = (CheckConstraint("stage IN ('applied','screening','interview','offer','accepted','rejected')", name="ck_hrm_candidate_stage"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    candidate_no: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    workforce_request_id: Mapped[int] = mapped_column(ForeignKey("operational_hrm_workforce_requests.id"), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(300), nullable=False)
    contact_reference: Mapped[str | None] = mapped_column(String(300))
    stage: Mapped[str] = mapped_column(String(20), default="applied", nullable=False, index=True)
    assessment_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalHrmEmployeeDocument(OperationalBase):
    __tablename__ = "operational_hrm_employee_documents"
    __table_args__ = (CheckConstraint("status IN ('active','verified','expired','superseded')", name="ck_hrm_document_status"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("operational_hrm_employees.id"), nullable=False, index=True)
    document_type: Mapped[str] = mapped_column(String(60), nullable=False)
    document_number: Mapped[str] = mapped_column(String(160), nullable=False)
    issued_on: Mapped[date | None] = mapped_column(Date)
    expires_on: Mapped[date | None] = mapped_column(Date, index=True)
    evidence_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalHrmLifecycleCase(OperationalBase):
    __tablename__ = "operational_hrm_lifecycle_cases"
    __table_args__ = (
        CheckConstraint("case_type IN ('onboarding','performance','training','disciplinary','separation','end_of_service')", name="ck_hrm_lifecycle_type"),
        CheckConstraint("status IN ('submitted','approved','rejected','completed')", name="ck_hrm_lifecycle_status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    case_no: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("operational_hrm_employees.id"), nullable=False, index=True)
    case_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    effective_on: Mapped[date] = mapped_column(Date, nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_reference: Mapped[str | None] = mapped_column(String(500))
    outcome: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="submitted", nullable=False, index=True)
    requested_by: Mapped[str] = mapped_column(String(200), nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decision_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


def _key() -> str:
    return str(uuid.uuid4())


def _audit(session: Session, event: str, actor: str, key: str, detail: str) -> None:
    session.add(OperationalAuditEvent(event_key=_key(), event_type=event, actor=actor,
        resource_key=key, detail=detail))


def _employee(session: Session, employee_key: str) -> OperationalHrmEmployee:
    row = session.scalar(select(OperationalHrmEmployee).where(OperationalHrmEmployee.employee_key == employee_key))
    if row is None:
        raise ValueError("HRM employee not found")
    return row


def create_workforce_request(session: Session, *, request_type: str, department_code: str,
                             position_title: str, headcount: int, needed_by: date,
                             justification: str, actor: str):
    key = _key()
    row = OperationalHrmWorkforceRequest(request_key=key, request_no=f"HR-REQ-{key[:8].upper()}",
        request_type=request_type, department_code=department_code.strip().upper(),
        position_title=position_title.strip(), headcount=headcount, needed_by=needed_by,
        justification=justification.strip(), status="submitted", requested_by=actor)
    session.add(row); _audit(session, "hrm.workforce.submitted", actor, key, row.position_title)
    session.commit(); return row


def decide_workforce_request(session: Session, *, request_key: str, action: str,
                             expected_revision: int, note: str, actor: str):
    row = session.scalar(select(OperationalHrmWorkforceRequest).where(
        OperationalHrmWorkforceRequest.request_key == request_key).with_for_update())
    if not row: raise ValueError("Workforce request not found")
    if row.revision != expected_revision: raise ValueError("Workforce request revision is stale")
    if row.status != "submitted" or action not in {"approve", "reject"}: raise ValueError("Invalid workforce decision")
    if row.requested_by == actor: raise ValueError("Workforce-request maker cannot decide the same request")
    row.status = "approved" if action == "approve" else "rejected"; row.decided_by = actor
    row.decision_note = note.strip(); row.revision += 1
    _audit(session, f"hrm.workforce.{action}d", actor, row.request_key, note.strip())
    session.commit(); return row


def create_candidate(session: Session, *, workforce_request_key: str, full_name: str,
                     contact_reference: str | None, actor: str):
    request = session.scalar(select(OperationalHrmWorkforceRequest).where(
        OperationalHrmWorkforceRequest.request_key == workforce_request_key))
    if not request or request.status != "approved": raise ValueError("Candidate requires an approved workforce request")
    key = _key(); row = OperationalHrmCandidate(candidate_key=key,
        candidate_no=f"HR-CAN-{key[:8].upper()}", workforce_request_id=request.id,
        full_name=full_name.strip(), contact_reference=(contact_reference or "").strip() or None,
        stage="applied", created_by=actor, updated_by=actor)
    session.add(row); _audit(session, "hrm.candidate.created", actor, key, row.full_name)
    session.commit(); return row


def move_candidate(session: Session, *, candidate_key: str, stage: str, expected_revision: int,
                   note: str, actor: str):
    row = session.scalar(select(OperationalHrmCandidate).where(
        OperationalHrmCandidate.candidate_key == candidate_key).with_for_update())
    if not row: raise ValueError("Candidate not found")
    if row.revision != expected_revision: raise ValueError("Candidate revision is stale")
    allowed = {"applied": {"screening", "rejected"}, "screening": {"interview", "rejected"},
        "interview": {"offer", "rejected"}, "offer": {"accepted", "rejected"}}
    if stage not in allowed.get(row.stage, set()): raise ValueError(f"Candidate cannot move from {row.stage} to {stage}")
    row.stage = stage; row.assessment_note = note.strip(); row.updated_by = actor; row.revision += 1
    _audit(session, "hrm.candidate.stage_changed", actor, row.candidate_key, f"{stage}; {note.strip()}")
    session.commit(); return row


def add_employee_document(session: Session, *, employee_key: str, document_type: str,
                          document_number: str, issued_on: date | None, expires_on: date | None,
                          evidence_reference: str, actor: str):
    if issued_on and expires_on and expires_on < issued_on: raise ValueError("Document expiry cannot precede issue date")
    employee = _employee(session, employee_key); key = _key()
    row = OperationalHrmEmployeeDocument(document_key=key, employee_id=employee.id,
        document_type=document_type, document_number=document_number.strip(), issued_on=issued_on,
        expires_on=expires_on, evidence_reference=evidence_reference.strip(), status="active", created_by=actor)
    session.add(row); _audit(session, "hrm.document.registered", actor, key, document_type)
    session.commit(); return row


def create_lifecycle_case(session: Session, *, employee_key: str, case_type: str, subject: str,
                          effective_on: date, details: str, evidence_reference: str | None, actor: str):
    employee = _employee(session, employee_key); key = _key()
    row = OperationalHrmLifecycleCase(case_key=key, case_no=f"HR-{case_type[:3].upper()}-{key[:8].upper()}",
        employee_id=employee.id, case_type=case_type, subject=subject.strip(), effective_on=effective_on,
        details=details.strip(), evidence_reference=(evidence_reference or "").strip() or None,
        status="submitted", requested_by=actor)
    session.add(row); _audit(session, "hrm.lifecycle.submitted", actor, key, case_type)
    session.commit(); return row


def transition_lifecycle_case(session: Session, *, case_key: str, action: str,
                              expected_revision: int, note: str, actor: str):
    row = session.scalar(select(OperationalHrmLifecycleCase).where(
        OperationalHrmLifecycleCase.case_key == case_key).with_for_update())
    if not row: raise ValueError("HRM lifecycle case not found")
    if row.revision != expected_revision: raise ValueError("HRM lifecycle case revision is stale")
    if action in {"approve", "reject"} and row.status == "submitted":
        if row.requested_by == actor: raise ValueError("Lifecycle-case maker cannot decide the same case")
        row.status = "approved" if action == "approve" else "rejected"
        row.decided_by = actor; row.decision_note = note.strip()
    elif action == "complete" and row.status == "approved":
        row.status = "completed"; row.outcome = note.strip()
    else: raise ValueError("Invalid HRM lifecycle transition")
    row.revision += 1; _audit(session, f"hrm.lifecycle.{action}d", actor, row.case_key, note.strip())
    session.commit(); return row


def hrm_lifecycle_payload(session: Session) -> dict:
    employees = {row.id: row for row in session.scalars(select(OperationalHrmEmployee))}
    requests = list(session.scalars(select(OperationalHrmWorkforceRequest).order_by(OperationalHrmWorkforceRequest.created_at.desc())))
    candidates = list(session.scalars(select(OperationalHrmCandidate).order_by(OperationalHrmCandidate.created_at.desc())))
    documents = list(session.scalars(select(OperationalHrmEmployeeDocument).order_by(OperationalHrmEmployeeDocument.created_at.desc())))
    cases = list(session.scalars(select(OperationalHrmLifecycleCase).order_by(OperationalHrmLifecycleCase.created_at.desc())))
    today = date.today()
    return {"controls": {"workforce_requests": len(requests), "candidates": len(candidates),
        "employee_documents": len(documents), "expiring_documents": sum(bool(x.expires_on and 0 <= (x.expires_on-today).days <= 90) for x in documents),
        "lifecycle_cases": len(cases), "pending_approvals": sum(x.status == "submitted" for x in requests) + sum(x.status == "submitted" for x in cases)},
        "workforce_requests": [{"request_key": x.request_key, "request_no": x.request_no, "request_type": x.request_type,
            "department_code": x.department_code, "position_title": x.position_title, "headcount": x.headcount,
            "needed_by": x.needed_by, "justification": x.justification, "status": x.status,
            "requested_by": x.requested_by, "revision": x.revision} for x in requests],
        "candidates": [{"candidate_key": x.candidate_key, "candidate_no": x.candidate_no,
            "workforce_request_key": next(r.request_key for r in requests if r.id == x.workforce_request_id),
            "full_name": x.full_name, "contact_reference": x.contact_reference, "stage": x.stage,
            "assessment_note": x.assessment_note, "revision": x.revision} for x in candidates],
        "documents": [{"document_key": x.document_key, "employee_key": employees[x.employee_id].employee_key,
            "employee_name": employees[x.employee_id].display_name, "document_type": x.document_type,
            "document_number": x.document_number, "issued_on": x.issued_on, "expires_on": x.expires_on,
            "evidence_reference": x.evidence_reference, "status": "expired" if x.expires_on and x.expires_on < today else x.status,
            "revision": x.revision} for x in documents],
        "cases": [{"case_key": x.case_key, "case_no": x.case_no, "employee_key": employees[x.employee_id].employee_key,
            "employee_name": employees[x.employee_id].display_name, "case_type": x.case_type, "subject": x.subject,
            "effective_on": x.effective_on, "details": x.details, "evidence_reference": x.evidence_reference,
            "outcome": x.outcome, "status": x.status, "requested_by": x.requested_by,
            "revision": x.revision} for x in cases],
        "payroll": {"included": False, "calculation_performed": False}}
