from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from klen_clone.hrm import OperationalHrmEmployee, OperationalHrmImportBatch
from klen_clone.hrm_lifecycle import (
    add_employee_document, create_candidate, create_lifecycle_case,
    create_workforce_request, decide_workforce_request, hrm_lifecycle_payload,
    move_candidate, transition_lifecycle_case,
)
from klen_clone.operational import OperationalBase


def seeded_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    OperationalBase.metadata.create_all(engine)
    session = Session(engine)
    batch = OperationalHrmImportBatch(batch_key="h" * 64, source_snapshot="test",
        source_digest="d" * 64, source_atomic=False, test_data=True, payroll_included=False)
    session.add(batch); session.flush()
    employee = OperationalHrmEmployee(batch_id=batch.id, source_ordinal=1,
        employee_key="EMP-1", username="employee.one", display_name="Employee One",
        role_name="Sales", status="captured_test")
    session.add(employee); session.commit()
    return session


def test_recruitment_document_and_employee_lifecycle_are_controlled_without_payroll():
    session = seeded_session()
    request = create_workforce_request(session, request_type="replacement", department_code="SALES",
        position_title="Sales Executive", headcount=1, needed_by=date(2026, 11, 1),
        justification="Approved replacement is required", actor="hr-maker")
    with pytest.raises(ValueError, match="maker cannot decide"):
        decide_workforce_request(session, request_key=request.request_key, action="approve",
            expected_revision=1, note="Self approval prohibited", actor="hr-maker")
    request = decide_workforce_request(session, request_key=request.request_key, action="approve",
        expected_revision=1, note="Headcount and need independently checked", actor="hr-manager")
    candidate = create_candidate(session, workforce_request_key=request.request_key,
        full_name="Candidate One", contact_reference="HR archive C-1", actor="hr-maker")
    for stage in ("screening", "interview", "offer", "accepted"):
        candidate = move_candidate(session, candidate_key=candidate.candidate_key, stage=stage,
            expected_revision=candidate.revision, note=f"Evidence recorded for {stage}", actor="hr-maker")
    document = add_employee_document(session, employee_key="EMP-1", document_type="visa",
        document_number="VISA-TEST-1", issued_on=date(2026, 1, 1), expires_on=date(2026, 12, 31),
        evidence_reference="sealed-test-archive/visa-1", actor="hr-maker")
    case = create_lifecycle_case(session, employee_key="EMP-1", case_type="performance",
        subject="Annual performance review", effective_on=date(2026, 12, 1),
        details="Objectives and evidence reviewed", evidence_reference="HR-PERF-1", actor="hr-maker")
    case = transition_lifecycle_case(session, case_key=case.case_key, action="approve",
        expected_revision=case.revision, note="Independent manager approval", actor="hr-manager")
    case = transition_lifecycle_case(session, case_key=case.case_key, action="complete",
        expected_revision=case.revision, note="Review completed and acknowledged", actor="hr-maker")

    payload = hrm_lifecycle_payload(session)
    assert payload["controls"]["workforce_requests"] == 1
    assert payload["candidates"][0]["stage"] == "accepted"
    assert payload["documents"][0]["document_key"] == document.document_key
    assert payload["cases"][0]["status"] == "completed"
    assert payload["payroll"] == {"included": False, "calculation_performed": False}


def test_lifecycle_rejects_invalid_candidate_jump_and_document_dates():
    session = seeded_session()
    request = create_workforce_request(session, request_type="new_position", department_code="OPS",
        position_title="Storekeeper", headcount=1, needed_by=date(2026, 10, 1),
        justification="Additional warehouse coverage", actor="maker")
    request = decide_workforce_request(session, request_key=request.request_key, action="approve",
        expected_revision=1, note="Approved staffing plan", actor="manager")
    candidate = create_candidate(session, workforce_request_key=request.request_key,
        full_name="Candidate Two", contact_reference=None, actor="maker")
    with pytest.raises(ValueError, match="cannot move"):
        move_candidate(session, candidate_key=candidate.candidate_key, stage="accepted",
            expected_revision=1, note="Invalid shortcut", actor="maker")
    with pytest.raises(ValueError, match="expiry"):
        add_employee_document(session, employee_key="EMP-1", document_type="passport",
            document_number="P-1", issued_on=date(2026, 5, 1), expires_on=date(2026, 4, 1),
            evidence_reference="archive", actor="maker")
