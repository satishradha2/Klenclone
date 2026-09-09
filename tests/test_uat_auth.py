from io import BytesIO
import json
from zipfile import ZipFile

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from klen_clone.auth import hash_password
from klen_clone.db import Base, make_engine
from klen_clone.models import (
    ErpAuthPrincipal,
    ErpLocation,
    ErpMigrationExceptionQueue,
    ErpOrganization,
    ErpSecurityLocationScope,
    ErpSecurityPermission,
    ErpSecurityRole,
    ErpSecurityRolePermission,
    ErpSecurityUser,
    ErpSecurityUserRole,
    RawFileManifest,
    RawRecord,
    SourceSnapshot,
)
from klen_clone.web import create_app


def build_uat_fixture(url: str) -> None:
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        snapshot = SourceSnapshot(name="synthetic-uat", source_system="Synthetic UAT",
                                  source_url="https://synthetic.invalid", is_atomic=True)
        session.add(snapshot)
        session.flush()
        manifest = RawFileManifest(snapshot_id=snapshot.id, relative_path="synthetic/user.json",
                                   entity_type="synthetic", sha256="b" * 64, byte_length=1,
                                   media_type="application/json", source_record_count=1)
        session.add(manifest)
        session.flush()
        raw = RawRecord(manifest_id=manifest.id, ordinal=1, source_record_id="uat-user",
                        payload={"synthetic": True})
        organization = ErpOrganization(snapshot_id=snapshot.id, source_key="uat-org",
                                       legal_name="Synthetic UAT Company", currency_code="AED",
                                       timezone_name="Asia/Dubai", inventory_cost_method="synthetic",
                                       operational_status="validation_only", posting_enabled=False,
                                       settings={"synthetic": True})
        session.add_all([raw, organization])
        session.flush()
        location = ErpLocation(snapshot_id=snapshot.id, organization_id=organization.id,
                               source_key="uat-location", code="UAT", name="Synthetic UAT",
                               operational_status="validation_only", posting_enabled=False)
        user = ErpSecurityUser(snapshot_id=snapshot.id, source_user_id=raw.id,
                               username="uat.reader", display_name="UAT Reader",
                               account_status="validation_only", password_material_copied=False,
                               authentication_enabled=True, evidence={"synthetic_uat": True})
        role = ErpSecurityRole(snapshot_id=snapshot.id, role_code="uat_reader",
                               role_name="UAT Reader", migration_status="validation_only",
                               assignment_enabled=True, evidence={"synthetic_uat": True})
        permission = ErpSecurityPermission(snapshot_id=snapshot.id, permission_code="customer.view",
                                           label="View customers", module_code="customer", mode="read",
                                           grant_enabled=True, evidence={"synthetic_uat": True})
        workflow_permission = ErpSecurityPermission(
            snapshot_id=snapshot.id, permission_code="accounting.view_reports",
            label="Review workflow blueprints", module_code="accounting", mode="read",
            grant_enabled=True, evidence={"synthetic_uat": True})
        session.add_all([location, user, role, permission, workflow_permission])
        session.flush()
        session.add_all([
            ErpSecurityUserRole(user_id=user.id, role_id=role.id, source_observed=False,
                                assignment_enabled=True),
            ErpSecurityRolePermission(role_id=role.id, permission_id=permission.id,
                                      source_granted=False, target_granted=True),
            ErpSecurityRolePermission(role_id=role.id, permission_id=workflow_permission.id,
                                      source_granted=False, target_granted=True),
            ErpSecurityLocationScope(snapshot_id=snapshot.id, user_id=user.id,
                                     location_id=location.id, scope_mode="explicit",
                                     access_enabled=True, evidence={"synthetic_uat": True}),
            ErpAuthPrincipal(snapshot_id=snapshot.id, security_user_id=user.id,
                             login_name="uat.reader", password_hash=hash_password("Synthetic-UAT-Only-123!"),
                             auth_status="active", mfa_enrolled=False,
                             authentication_enabled=True, evidence={"synthetic_uat": True}),
            ErpMigrationExceptionQueue(snapshot_id=snapshot.id, source_kind="synthetic_document",
                                       source_id=1, exception_code="SYNTHETIC_REVIEW",
                                       severity="critical", queue_status="open",
                                       activation_blocked=True,
                                       evidence={"relation_status": "review_required"}),
        ])
        session.commit()


def test_synthetic_uat_cookie_login_session_logout_and_read_only(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'uat.db'}"
    build_uat_fixture(url)
    monkeypatch.setenv("KLEN_AUTH_ENABLED", "true")
    monkeypatch.setenv("KLEN_UAT_AUTH_ENABLED", "true")
    monkeypatch.setenv("KLEN_AUTH_SECRET", "synthetic-uat-secret-with-at-least-32-characters")
    monkeypatch.setenv("KLEN_COOKIE_SECURE", "false")
    monkeypatch.setenv("KLEN_UAT_REVIEW_DATABASE", str(tmp_path / "reviews.db"))
    client = TestClient(create_app(url, "synthetic-uat"))

    assert client.get("/api/v1/secure/parties").status_code == 401
    rejected = client.post("/api/v1/auth/login", json={"username": "uat.reader", "password": "wrong"})
    assert rejected.status_code == 401
    login = client.post("/api/v1/auth/login", json={
        "username": "uat.reader", "password": "Synthetic-UAT-Only-123!"})
    assert login.status_code == 200
    assert login.json()["principal"]["synthetic_uat"] is True
    assert "httponly" in login.headers["set-cookie"].lower()
    assert "samesite=strict" in login.headers["set-cookie"].lower()

    current = client.get("/api/v1/auth/session")
    assert current.json()["authenticated"] is True
    assert client.get("/api/v1/secure/parties").status_code == 200
    catalog = client.get("/api/v1/secure/export-catalog")
    assert catalog.status_code == 200
    assert catalog.json()["total"] == 7
    customer_export = client.get("/api/v1/secure/exports/customers")
    assert customer_export.status_code == 200
    assert customer_export.headers["content-type"] == "application/zip"
    assert customer_export.headers["x-export-module"] == "customers"
    assert customer_export.headers["x-location-scope"] == "UAT"
    assert customer_export.headers["x-posting-enabled"] == "false"
    with ZipFile(BytesIO(customer_export.content)) as package:
        assert {"manifest.json", "reconciliation.json", "data/customers.csv",
                "data/open_discrepancies.csv", "REVIEW_INSTRUCTIONS.txt"}.issubset(package.namelist())
        manifest = json.loads(package.read("manifest.json"))
        assert manifest["required_permission"] == "customer.view"
        assert manifest["location_scope"]["codes"] == ["UAT"]
        assert manifest["sensitive_fields_redacted"] is True
        assert manifest["source_or_clone_mutated"] is False
        assert "email" in manifest["excluded_fields"]
    assert client.get("/api/v1/secure/exports/sales").status_code == 403
    review_payload = {
        "package_sha256": customer_export.headers["x-content-sha256"],
        "decision_code": "accepted_for_uat",
        "rationale": "Synthetic customer package accepted for continued UAT only.",
    }
    assert client.post("/api/v1/uat/business-reviews/customers", json=review_payload).status_code == 403
    review = client.post("/api/v1/uat/business-reviews/customers", json=review_payload,
                         headers={"X-CSRF-Token": current.json()["csrf_token"]})
    assert review.status_code == 200
    assert review.json()["production_signoff"] is False
    assert review.json()["source_or_clone_modified"] is False
    reviews = client.get("/api/v1/secure/business-reviews")
    assert reviews.status_code == 200
    assert reviews.json()["total"] == 1
    assert reviews.json()["production_signoff_enabled"] is False
    workflows = client.get("/api/v1/secure/workflows")
    assert workflows.status_code == 200
    assert workflows.json()["execution_enabled"] is False
    governance = client.get("/api/v1/secure/approval-governance")
    assert governance.status_code == 200
    assert governance.json()["approval_actions_enabled"] is False
    assert governance.json()["real_user_bindings"] == 0
    assert governance.json()["synthetic_draft_assignments"] == 0
    segregation = client.get("/api/v1/secure/segregation-controls")
    assert segregation.status_code == 200
    assert segregation.json()["enforcement_enabled"] is False
    discrepancies = client.get("/api/v1/secure/discrepancies")
    assert discrepancies.status_code == 200
    assert discrepancies.json()["total"] == 1
    exception_id = discrepancies.json()["items"][0]["id"]
    proposal_payload = {"exception_id": exception_id, "resolution_code": "request_source_evidence",
                        "proposed_value": {}, "rationale": "Synthetic UAT review proposal only."}
    assert client.post("/api/v1/uat/discrepancy-proposals", json=proposal_payload).status_code == 403
    proposal = client.post("/api/v1/uat/discrepancy-proposals", json=proposal_payload,
                           headers={"X-CSRF-Token": current.json()["csrf_token"]})
    assert proposal.status_code == 200
    assert proposal.json()["source_exception_modified"] is False
    refreshed = client.get("/api/v1/secure/discrepancies").json()
    assert refreshed["items"][0]["proposal_count"] == 1
    assert client.post("/api/v1/summary", json={}).status_code == 405

    assert client.post("/api/v1/auth/logout", json={}).status_code == 403
    logout = client.post("/api/v1/auth/logout", json={}, headers={
        "X-CSRF-Token": current.json()["csrf_token"]})
    assert logout.status_code == 200
    assert client.get("/api/v1/auth/session").json()["authenticated"] is False


def test_uat_reset_is_dry_run_and_disabled_by_default(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'disabled.db'}"
    build_uat_fixture(url)
    monkeypatch.delenv("KLEN_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("KLEN_UAT_AUTH_ENABLED", raising=False)
    client = TestClient(create_app(url, "synthetic-uat"))
    assert client.post("/api/v1/auth/reset-request", json={"username": "uat.reader"}).status_code == 405
