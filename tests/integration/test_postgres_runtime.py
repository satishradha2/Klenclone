from __future__ import annotations

from decimal import Decimal
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from klen_clone.auth import issue_token
from klen_clone.db import make_engine
from klen_clone.models import (
    ErpAuthPrincipal,
    ErpLocation,
    ErpOrganization,
    ErpSecurityLocationScope,
    ErpSecurityPermission,
    ErpSecurityRole,
    ErpSecurityRolePermission,
    ErpSecurityUser,
    ErpSecurityUserRole,
    ErpTransactionDocument,
    RawFileManifest,
    RawRecord,
    SourceSnapshot,
)
from klen_clone.web import create_app


pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif("KLEN_TEST_DATABASE_URL" not in os.environ,
                       reason="requires isolated PostgreSQL validation database"),
]
SNAPSHOT = "synthetic-postgres-validation"


def test_postgres_migration_rbac_location_and_read_only(monkeypatch):
    database_url = os.environ["KLEN_TEST_DATABASE_URL"]
    secret = os.environ["KLEN_AUTH_SECRET"]
    engine = make_engine(database_url)
    assert engine.dialect.name == "postgresql"

    with Session(engine) as session:
        assert session.scalar(text("select version_num from alembic_version")) == "20260908_0001"
        assert session.scalar(select(SourceSnapshot.id).where(SourceSnapshot.name == SNAPSHOT)) is None

        snapshot = SourceSnapshot(
            name=SNAPSHOT,
            source_system="Synthetic validation fixture",
            source_url="https://synthetic.invalid/",
            is_atomic=True,
            notes="Synthetic records only; never sourced from BizModo.",
        )
        session.add(snapshot)
        session.flush()
        manifest = RawFileManifest(
            snapshot_id=snapshot.id,
            relative_path="synthetic/runtime.json",
            entity_type="synthetic_runtime",
            sha256="a" * 64,
            byte_length=1,
            media_type="application/json",
            source_record_count=3,
        )
        session.add(manifest)
        session.flush()
        raw_user = RawRecord(manifest_id=manifest.id, ordinal=1, source_record_id="synthetic-user", payload={"synthetic": True})
        raw_doc_a = RawRecord(manifest_id=manifest.id, ordinal=2, source_record_id="synthetic-doc-a", payload={"synthetic": True})
        raw_doc_b = RawRecord(manifest_id=manifest.id, ordinal=3, source_record_id="synthetic-doc-b", payload={"synthetic": True})
        session.add_all([raw_user, raw_doc_a, raw_doc_b])
        session.flush()

        organization = ErpOrganization(
            snapshot_id=snapshot.id,
            source_key="synthetic-org",
            legal_name="Synthetic Validation Company",
            currency_code="AED",
            timezone_name="Asia/Dubai",
            inventory_cost_method="synthetic",
            operational_status="validation_only",
            posting_enabled=False,
            settings={"synthetic": True},
        )
        session.add(organization)
        session.flush()
        location_a = ErpLocation(snapshot_id=snapshot.id, organization_id=organization.id,
                                 source_key="synthetic-a", code="SYN-A", name="Synthetic A",
                                 operational_status="validation_only", posting_enabled=False)
        location_b = ErpLocation(snapshot_id=snapshot.id, organization_id=organization.id,
                                 source_key="synthetic-b", code="SYN-B", name="Synthetic B",
                                 operational_status="validation_only", posting_enabled=False)
        session.add_all([location_a, location_b])
        session.flush()

        user = ErpSecurityUser(
            snapshot_id=snapshot.id,
            source_user_id=raw_user.id,
            username="synthetic.reader",
            display_name="Synthetic Reader",
            source_role_name="synthetic_read_only",
            account_status="validation_only",
            password_material_copied=False,
            authentication_enabled=True,
            evidence={"synthetic": True},
        )
        role = ErpSecurityRole(snapshot_id=snapshot.id, role_code="synthetic_reader",
                               role_name="Synthetic Reader", migration_status="validation_only",
                               assignment_enabled=True, evidence={"synthetic": True})
        permission = ErpSecurityPermission(snapshot_id=snapshot.id, permission_code="sell.view",
                                           label="Synthetic document read", module_code="sales",
                                           mode="read", grant_enabled=True, evidence={"synthetic": True})
        session.add_all([user, role, permission])
        session.flush()
        assignment = ErpSecurityUserRole(user_id=user.id, role_id=role.id,
                                         source_observed=False, assignment_enabled=True)
        grant = ErpSecurityRolePermission(role_id=role.id, permission_id=permission.id,
                                          source_granted=False, target_granted=True)
        scope = ErpSecurityLocationScope(snapshot_id=snapshot.id, user_id=user.id,
                                         location_id=location_a.id, scope_mode="explicit",
                                         access_enabled=False, evidence={"synthetic": True})
        principal = ErpAuthPrincipal(snapshot_id=snapshot.id, security_user_id=user.id,
                                     login_name="synthetic.reader", auth_status="active",
                                     mfa_enrolled=False, authentication_enabled=True,
                                     evidence={"synthetic": True})
        session.add_all([assignment, grant, scope, principal])
        session.flush()
        session.add_all([
            ErpTransactionDocument(snapshot_id=snapshot.id, source_kind="sale", source_id=1,
                                   source_raw_record_id=raw_doc_a.id, document_no="SYN-A-001",
                                   location_id=location_a.id, total_amount=Decimal("10.00"),
                                   migration_status="validation_only", operational_enabled=False,
                                   posting_enabled=False, evidence={"synthetic": True}),
            ErpTransactionDocument(snapshot_id=snapshot.id, source_kind="sale", source_id=2,
                                   source_raw_record_id=raw_doc_b.id, document_no="SYN-B-001",
                                   location_id=location_b.id, total_amount=Decimal("20.00"),
                                   migration_status="validation_only", operational_enabled=False,
                                   posting_enabled=False, evidence={"synthetic": True}),
        ])
        session.commit()
        principal_id = principal.id
        scope_id = scope.id
        grant_id = grant.id
        location_a_id = location_a.id

    monkeypatch.setenv("KLEN_AUTH_ENABLED", "true")
    monkeypatch.setenv("KLEN_AUTH_SECRET", secret)
    monkeypatch.setenv("KLEN_PRODUCTION_MODE", "false")
    client = TestClient(create_app(database_url, SNAPSHOT))
    token = issue_token(principal_id, secret, 1800)
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/v1/secure/documents").status_code == 401
    denied_scope = client.get("/api/v1/secure/documents", headers=headers)
    assert denied_scope.status_code == 403
    assert denied_scope.json()["detail"] == "No active location scope"

    with Session(engine) as session:
        session.get(ErpSecurityLocationScope, scope_id).access_enabled = True
        session.commit()
    allowed = client.get("/api/v1/secure/documents", headers=headers)
    assert allowed.status_code == 200
    assert len(allowed.json()["items"]) == 1
    assert allowed.json()["items"][0]["location_id"] == location_a_id
    assert allowed.json()["items"][0]["document_no"] == "SYN-A-001"
    detail = client.get(f"/api/v1/secure/sales/{allowed.json()['items'][0]['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["document"]["document_no"] == "SYN-A-001"
    assert detail.json()["location_scope_enforced"] is True
    assert detail.json()["posting_enabled"] is False
    assert client.get("/api/v1/secure/sales/999999", headers=headers).status_code == 404

    with Session(engine) as session:
        session.get(ErpSecurityRolePermission, grant_id).target_granted = False
        session.commit()
    denied_permission = client.get("/api/v1/secure/documents", headers=headers)
    assert denied_permission.status_code == 403
    assert denied_permission.json()["detail"] == "Required permission is not granted"
    assert client.post("/api/v1/summary", json={}).status_code == 405
