import json
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from klen_clone.auth import hash_password
from klen_clone.db import Base, make_engine
from klen_clone.erp_preview import create_app
from klen_clone.models import (
    ErpAuditEvent, ErpLocation, ErpOrganization, ErpParty, ErpProductMaster, ErpProductUom,
    RawFileManifest, RawRecord, SourceSnapshot, StgContact, StgProduct, StgProductUomProfile,
)
from klen_clone.operational import (
    OperationalAuditEvent, OperationalDraft, OperationalFiscalPeriod,
    OperationalInventoryLedgerEntry, OperationalJournalBatch, OperationalJournalLine,
    OperationalPostingProbe, OperationalReversalRequest,
    OperationalSchemaMigration, OperationalStockPosition, OperationalStockReservation,
    OperationalSubledgerEntry, OperationalWorkflowEvent, execute_posting, execute_reversal,
)


def preview_client(tmp_path) -> TestClient:
    url = f"sqlite:///{tmp_path / 'erp-preview.db'}"
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        snapshot = SourceSnapshot(
            name="preview-snapshot",
            source_system="BizModo V7.5.1",
            source_url="https://example.invalid",
            is_atomic=False,
        )
        session.add(snapshot)
        session.flush()
        manifest = RawFileManifest(
            snapshot_id=snapshot.id,
            relative_path="products.csv",
            entity_type="products",
            sha256="0" * 64,
            byte_length=1,
            media_type="text/csv",
            source_record_count=1,
        )
        session.add(manifest)
        session.flush()
        raw = RawRecord(manifest_id=manifest.id, ordinal=1, source_record_id="1", payload={"SKU": "SKU-001"})
        session.add(raw)
        session.flush()
        staged = StgProduct(snapshot_id=snapshot.id, raw_record_id=raw.id, sku="SKU-001", name="Source product")
        session.add(staged)
        session.flush()
        uom_profile = StgProductUomProfile(
            snapshot_id=snapshot.id, product_id=staged.id, sku="SKU-001",
            source_base_uom="Piece", canonical_base_uom="piece", observed_uoms=["Piece"],
            conversion_status="resolved",
        )
        session.add(uom_profile)
        session.flush()
        organization = ErpOrganization(
            snapshot_id=snapshot.id,
            source_key="company",
            legal_name="Asas General Trading LLC",
            currency_code="AED",
            timezone_name="Asia/Dubai",
            inventory_cost_method="weighted_average",
            operational_status="preview",
            posting_enabled=False,
        )
        session.add(organization)
        session.flush()
        session.add(ErpLocation(
            snapshot_id=snapshot.id, organization_id=organization.id, source_key="SHJ",
            code="SHJ", name="SHJ", operational_status="preview", posting_enabled=False,
        ))
        session.add(ErpLocation(
            snapshot_id=snapshot.id, organization_id=organization.id, source_key="DXB",
            code="DXB", name="Dubai", operational_status="preview", posting_enabled=False,
        ))
        contact = StgContact(
            snapshot_id=snapshot.id, raw_record_id=raw.id, kind="customer",
            contact_id="CO-001", business_name="Test Customer", name="Owner",
        )
        session.add(contact)
        session.flush()
        session.add(ErpParty(
            snapshot_id=snapshot.id, source_contact_id=contact.id, source_raw_record_id=raw.id,
            party_code="CO-001", party_kind="customer", legal_or_business_name="Test Customer",
            contact_name="Owner", master_status="preserved", operational_enabled=False,
        ))
        product = ErpProductMaster(
            snapshot_id=snapshot.id,
            source_product_id=staged.id,
            source_raw_record_id=raw.id,
            sku="SKU-001",
            name="Source product",
            purchase_price_evidence=2,
            selling_price_evidence=3,
            master_status="preserved",
            operational_enabled=False,
        )
        session.add(product)
        session.flush()
        session.add(ErpProductUom(
            snapshot_id=snapshot.id, source_profile_id=uom_profile.id, product_id=product.id,
            source_base_uom="Piece", canonical_base_uom="piece", factor_to_base_snapshot=1,
            conversion_status="resolved", operational_enabled=False,
        ))
        session.commit()
    return TestClient(create_app(url, "preview-snapshot"))


def seed_operational_controls(client: TestClient, quantity: str = "100") -> None:
    with client.app.state.operational_sessions() as session:
        session.add(OperationalFiscalPeriod(
            period_key="FY-OPEN", starts_on=date(2020, 1, 1), ends_on=date(2035, 12, 31),
            status="open", rehearsal_enabled=True, approval_reference="test-approval",
            configured_by="test-controller",
        ))
        session.add(OperationalStockPosition(
            location_code="SHJ", sku="SKU-001", canonical_uom="piece",
            quantity_on_hand=quantity, quantity_reserved="0", average_unit_cost="2",
            availability_enabled=True, source_status="test_reconciled",
        ))
        session.commit()


def test_preview_is_independent_read_only_and_excludes_hr_payroll(tmp_path):
    client = preview_client(tmp_path)
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["application"] == "Asas ERP"
    assert health.json()["mode"] == "independent_clone_preview"
    assert health.json()["posting_enabled"] is False
    assert health.json()["hr_payroll_enabled"] is False
    assert health.headers["x-frame-options"] == "DENY"
    assert client.post("/api/v1/products", json={}).status_code == 405


def test_preview_overview_and_product_register_use_clone_database(tmp_path):
    client = preview_client(tmp_path)
    overview = client.get("/api/v1/overview")
    assert overview.status_code == 200
    assert overview.json()["organization"] == "Asas General Trading LLC"
    assert overview.json()["counts"]["products"] == 1
    products = client.get("/api/v1/products?q=SKU-001")
    assert products.status_code == 200
    assert products.json()["total"] == 1
    assert products.json()["items"][0]["name"] == "Source product"
    assert "ASAS ERP" in client.get("/").text


def test_preview_authentication_session_csrf_and_audit(tmp_path, monkeypatch):
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_ADMIN_USERNAME", "asas-admin")
    monkeypatch.setenv("ASAS_ADMIN_PASSWORD_HASH", hash_password("temporary strong password"))
    client = preview_client(tmp_path)

    assert client.get("/api/v1/overview").status_code == 401
    assert "Sign in to Asas ERP" in client.get("/").text
    denied = client.post("/api/v1/auth/login", json={"username": "asas-admin", "password": "wrong"})
    assert denied.status_code == 401
    login = client.post("/api/v1/auth/login", json={
        "username": "asas-admin", "password": "temporary strong password",
    })
    assert login.status_code == 200
    assert login.json()["principal"]["roles"] == ["operations_administrator"]
    assert login.json()["principal"]["posting_enabled"] is False
    assert client.get("/api/v1/overview").status_code == 200
    csrf = login.json()["csrf_token"]
    locations = client.get("/api/v1/selectors/locations").json()["items"]
    assert locations == [{"code": "DXB", "name": "Dubai"}, {"code": "SHJ", "name": "SHJ"}]
    parties = client.get("/api/v1/selectors/parties?kind=customer&q=Test").json()["items"]
    assert parties == [{"party_code": "CO-001", "name": "Test Customer"}]
    products = client.get("/api/v1/selectors/products?q=SKU-001").json()["items"]
    assert products[0]["sku"] == "SKU-001"
    assert products[0]["uom"] == "Piece"
    assert products[0]["factor_to_base_snapshot"] == 1.0
    assert client.post("/api/v1/auth/logout").status_code == 403
    assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert client.get("/api/v1/overview").status_code == 401

    with Session(client.app.state.engine) as session:
        assert session.scalar(select(func.count(ErpAuditEvent.id)).where(
            ErpAuditEvent.event_type.in_(("auth.login", "auth.logout")))) == 3


def test_operational_sales_draft_is_separate_validated_and_non_posting(tmp_path, monkeypatch):
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_ADMIN_USERNAME", "asas-admin")
    monkeypatch.setenv("ASAS_ADMIN_PASSWORD_HASH", hash_password("temporary strong password"))
    operational_url = f"sqlite:///{tmp_path / 'asas-operational.db'}"
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", operational_url)
    client = preview_client(tmp_path)
    seed_operational_controls(client, quantity="3")
    login = client.post("/api/v1/auth/login", json={
        "username": "asas-admin", "password": "temporary strong password",
    })
    csrf = login.json()["csrf_token"]
    payload = {
        "document_type": "sale", "party_code": "CO-001", "location_code": "SHJ",
        "discount_amount": "0", "lines": [{"sku": "SKU-001", "quantity": "2", "uom": "Piece"}],
    }
    assert client.post("/api/v1/drafts", json=payload).status_code == 403
    created = client.post("/api/v1/drafts", json=payload, headers={"X-CSRF-Token": csrf})
    assert created.status_code == 201
    assert created.json()["status"] == "draft"
    assert created.json()["posting_enabled"] is False
    assert created.json()["subtotal"] == 6.0
    assert created.json()["tax_amount"] == 0.3
    assert created.json()["total_amount"] == 6.3
    assert created.json()["lines"][0]["canonical_uom"] == "piece"
    assert created.json()["lines"][0]["factor_to_base_snapshot"] == 1.0
    assert created.json()["lines"][0]["quantity_base"] == 2.0
    assert created.json()["revision"] == 1
    draft_register = client.get("/api/v1/drafts").json()
    assert draft_register["total"] == 1
    assert draft_register["controls"]["stock_positions"] == 1
    assert draft_register["controls"]["open_rehearsal_periods"] == 1
    assert draft_register["controls"]["permanent_journals"] == 0
    invalid = payload | {"lines": [{"sku": "NOT-FOUND", "quantity": "1", "uom": "Piece"}]}
    assert client.post("/api/v1/drafts", json=invalid, headers={"X-CSRF-Token": csrf}).status_code == 422
    wrong_uom = payload | {"lines": [{"sku": "SKU-001", "quantity": "1", "uom": "Carton"}]}
    assert client.post("/api/v1/drafts", json=wrong_uom, headers={"X-CSRF-Token": csrf}).status_code == 422

    key = created.json()["draft_key"]
    detail = client.get(f"/api/v1/drafts/{key}")
    assert detail.status_code == 200
    assert detail.json()["draft_no"] == created.json()["draft_no"]
    assert client.get(f"/draft-review.html?key={key}").status_code == 200
    edit = payload | {"expected_revision": 1, "lines": [{"sku": "SKU-001", "quantity": "3", "uom": "Piece"}]}
    edited = client.put(f"/api/v1/drafts/{key}", json=edit, headers={"X-CSRF-Token": csrf})
    assert edited.status_code == 200
    assert edited.json()["revision"] == 2
    assert edited.json()["lines"][0]["quantity_base"] == 3.0
    stale = client.put(f"/api/v1/drafts/{key}", json=edit, headers={"X-CSRF-Token": csrf})
    assert stale.status_code == 409
    submitted = client.post(f"/api/v1/drafts/{key}/submit", json={"expected_revision": 2},
                            headers={"X-CSRF-Token": csrf})
    assert submitted.status_code == 200 and submitted.json()["status"] == "submitted"
    with client.app.state.operational_sessions() as session:
        assert session.scalar(select(OperationalStockPosition)).quantity_reserved == 3
        assert session.scalar(select(OperationalStockReservation)).status == "active"
    assert client.put(f"/api/v1/drafts/{key}", json=edit | {"expected_revision": 3},
                      headers={"X-CSRF-Token": csrf}).status_code == 409
    assert client.post(f"/api/v1/drafts/{key}/approve", json={"expected_revision": 3},
                       headers={"X-CSRF-Token": csrf}).status_code == 403
    cancelled = client.post(f"/api/v1/drafts/{key}/cancel", json={"expected_revision": 3},
                            headers={"X-CSRF-Token": csrf})
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"

    with client.app.state.operational_sessions() as session:
        assert session.scalar(select(func.count(OperationalDraft.id))) == 1
        assert session.scalar(select(func.count(OperationalAuditEvent.id))) == 4
        assert session.scalar(select(func.count(OperationalWorkflowEvent.id))) == 2
        position = session.scalar(select(OperationalStockPosition))
        assert position.quantity_reserved == 0
        reservation = session.scalar(select(OperationalStockReservation))
        assert reservation.status == "released"


def test_independent_approver_and_transactional_posting_rehearsal(tmp_path, monkeypatch):
    admin_password, approver_password = "admin temporary password", "approver temporary password"
    users_file = tmp_path / "users.json"
    users_file.write_text(json.dumps({"users": [
        {"id": 1, "username": "admin", "password_hash": hash_password(admin_password),
         "roles": ["operations_administrator"],
         "permissions": ["clone.read", "draft.create", "draft.edit", "draft.submit", "draft.cancel"],
         "allowed_locations": ["SHJ"]},
        {"id": 2, "username": "approver", "password_hash": hash_password(approver_password),
         "roles": ["independent_approver"],
         "permissions": ["clone.read", "draft.approve", "posting.rehearse"],
         "allowed_locations": ["SHJ"]},
    ]}), encoding="utf-8")
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_USERS_FILE", str(users_file))
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'approval.db'}")
    client = preview_client(tmp_path)
    seed_operational_controls(client)

    admin_login = client.post("/api/v1/auth/login", json={"username": "admin", "password": admin_password}).json()
    admin_csrf = admin_login["csrf_token"]
    assert admin_login["principal"]["allowed_locations"] == ["SHJ"]
    assert client.get("/api/v1/selectors/locations").json()["items"] == [{"code": "SHJ", "name": "SHJ"}]
    payload = {"document_type": "purchase", "party_code": "CO-001", "location_code": "SHJ",
               "lines": [{"sku": "SKU-001", "quantity": "2", "uom": "Piece"}]}
    # The fixture party is a customer, proving document-type validation occurs.
    assert client.post("/api/v1/drafts", json=payload, headers={"X-CSRF-Token": admin_csrf}).status_code == 422
    payload["document_type"] = "sale"
    outside_scope = payload | {"location_code": "DXB"}
    assert client.post("/api/v1/drafts", json=outside_scope,
                       headers={"X-CSRF-Token": admin_csrf}).status_code == 403
    created = client.post("/api/v1/drafts", json=payload, headers={"X-CSRF-Token": admin_csrf}).json()
    submitted = client.post(f"/api/v1/drafts/{created['draft_key']}/submit",
                            json={"expected_revision": 1}, headers={"X-CSRF-Token": admin_csrf}).json()
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": admin_csrf})

    approver_login = client.post("/api/v1/auth/login", json={
        "username": "approver", "password": approver_password,
    }).json()
    approver_csrf = approver_login["csrf_token"]
    assert approver_login["principal"]["roles"] == ["independent_approver"]
    assert client.post("/api/v1/drafts", json=payload,
                       headers={"X-CSRF-Token": approver_csrf}).status_code == 403
    approved = client.post(f"/api/v1/drafts/{created['draft_key']}/approve",
                           json={"expected_revision": submitted["revision"]},
                           headers={"X-CSRF-Token": approver_csrf})
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    with client.app.state.operational_sessions() as session:
        period = session.scalar(select(OperationalFiscalPeriod))
        period.status = "locked"
        session.commit()
    assert client.post(f"/api/v1/drafts/{created['draft_key']}/posting-rehearsal",
                       headers={"X-CSRF-Token": approver_csrf}).status_code == 409
    with client.app.state.operational_sessions() as session:
        period = session.scalar(select(OperationalFiscalPeriod))
        period.status = "open"
        session.commit()
    rehearsal = client.post(f"/api/v1/drafts/{created['draft_key']}/posting-rehearsal",
                            headers={"X-CSRF-Token": approver_csrf})
    assert rehearsal.status_code == 200
    assert rehearsal.json()["rollback_verified"] is True
    assert rehearsal.json()["posting_performed"] is False
    assert rehearsal.json()["debit"] == rehearsal.json()["credit"] == 10.3
    assert rehearsal.json()["cost_of_goods_sold"] == 4.0
    assert rehearsal.json()["inventory"][0]["value_delta"] == -4.0
    assert len(rehearsal.json()["posting_fingerprint"]) == 64
    assert rehearsal.json()["fiscal_period"] == "FY-OPEN"
    assert rehearsal.json()["reversal"]["journal"][0]["debit"] == 4.0
    assert rehearsal.json()["reversal"]["inventory"][0]["quantity_base"] == 2.0
    assert client.post(
        f"/api/v1/drafts/{created['draft_key']}/post",
        json={"idempotency_key": rehearsal.json()["idempotency_key"]},
        headers={"X-CSRF-Token": approver_csrf},
    ).status_code == 503

    with client.app.state.operational_sessions() as session:
        assert session.scalar(select(func.count(OperationalPostingProbe.id))) == 0
        assert session.scalar(select(func.count(OperationalSchemaMigration.version))) == 11
        assert session.scalar(select(func.count(OperationalStockReservation.id))) == 1
        assert session.scalar(select(func.count(OperationalJournalBatch.id))) == 0
        assert session.scalar(select(func.count(OperationalSubledgerEntry.id))) == 0
        assert session.scalar(select(func.count(OperationalReversalRequest.id))) == 0

    with client.app.state.operational_sessions() as session:
        draft = session.scalar(select(OperationalDraft).where(
            OperationalDraft.draft_key == created["draft_key"]))
        posted = execute_posting(
            session, draft, actor="posting-controller",
            idempotency_key=rehearsal.json()["idempotency_key"],
        )
        assert posted["status"] == "posted"
        assert posted["idempotent_replay"] is False
        assert session.scalar(select(OperationalStockPosition)).quantity_on_hand == 98
        assert session.scalar(select(OperationalStockPosition)).quantity_reserved == 0
        assert session.scalar(select(OperationalStockReservation)).status == "consumed"
        assert session.scalar(select(func.count(OperationalJournalLine.id))) == 5
        assert session.scalar(select(func.count(OperationalInventoryLedgerEntry.id))) == 1
        replay = execute_posting(
            session, draft, actor="posting-controller",
            idempotency_key=rehearsal.json()["idempotency_key"],
        )
        assert replay["idempotent_replay"] is True
        batch = session.scalar(select(OperationalJournalBatch).where(
            OperationalJournalBatch.batch_key == posted["batch_key"]))
        reversed_batch = execute_reversal(
            session, batch, actor="reversal-controller", reason="test exact reversal",
        )
        assert reversed_batch["status"] == "posted"
        assert session.scalar(select(OperationalStockPosition)).quantity_on_hand == 100
        assert session.scalar(select(func.count(OperationalJournalBatch.id))) == 2
        assert session.scalar(select(func.count(OperationalReversalRequest.id))) == 1
        assert session.scalar(select(OperationalDraft).where(
            OperationalDraft.draft_key == created["draft_key"])).status == "reversed"


def test_inventory_transfer_api_enforces_scope_maker_checker_and_rehearsal(tmp_path, monkeypatch):
    admin_password, approver_password = "inventory admin password", "inventory approver password"
    users_file = tmp_path / "inventory-users.json"
    users_file.write_text(json.dumps({"users": [
        {"id": 1, "username": "inventory-maker", "password_hash": hash_password(admin_password),
         "roles": ["inventory_controller"],
         "permissions": ["clone.read", "inventory.create", "inventory.edit", "inventory.submit", "inventory.cancel"],
         "allowed_locations": ["SHJ", "DXB"]},
        {"id": 2, "username": "inventory-approver", "password_hash": hash_password(approver_password),
         "roles": ["inventory_approver"],
         "permissions": ["clone.read", "inventory.approve", "inventory.rehearse"],
         "allowed_locations": ["SHJ", "DXB"]},
    ]}), encoding="utf-8")
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_USERS_FILE", str(users_file))
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'inventory-api.db'}")
    client = preview_client(tmp_path)
    seed_operational_controls(client, quantity="10")

    maker_login = client.post("/api/v1/auth/login", json={
        "username": "inventory-maker", "password": admin_password,
    }).json()
    maker_csrf = maker_login["csrf_token"]
    payload = {
        "document_type": "transfer", "location_code": "SHJ",
        "destination_location_code": "DXB", "adjustment_direction": None,
        "reason_code": "branch_replenishment",
        "lines": [{"sku": "SKU-001", "quantity": "2", "uom": "Piece"}],
    }
    assert client.post("/api/v1/inventory-documents", json=payload).status_code == 403
    created = client.post("/api/v1/inventory-documents", json=payload,
                          headers={"X-CSRF-Token": maker_csrf})
    assert created.status_code == 201
    assert created.json()["posting_enabled"] is False
    assert created.json()["lines"][0]["quantity_base"] == 2.0
    key = created.json()["document_key"]
    edited_payload = payload | {"lines": [{"sku": "SKU-001", "quantity": "3", "uom": "Piece"}]}
    edited = client.put(f"/api/v1/inventory-documents/{key}?expected_revision=1",
                        json=edited_payload, headers={"X-CSRF-Token": maker_csrf})
    assert edited.status_code == 200
    assert edited.json()["revision"] == 2
    assert edited.json()["lines"][0]["quantity_base"] == 3.0
    assert client.put(f"/api/v1/inventory-documents/{key}?expected_revision=1",
                      json=edited_payload, headers={"X-CSRF-Token": maker_csrf}).status_code == 409
    submitted = client.post(f"/api/v1/inventory-documents/{key}/submit",
                            json={"expected_revision": 2},
                            headers={"X-CSRF-Token": maker_csrf})
    assert submitted.status_code == 200 and submitted.json()["status"] == "submitted"
    assert client.post(f"/api/v1/inventory-documents/{key}/approve",
                       json={"expected_revision": 3},
                       headers={"X-CSRF-Token": maker_csrf}).status_code == 403
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": maker_csrf})

    approver_login = client.post("/api/v1/auth/login", json={
        "username": "inventory-approver", "password": approver_password,
    }).json()
    approver_csrf = approver_login["csrf_token"]
    approved = client.post(f"/api/v1/inventory-documents/{key}/approve",
                           json={"expected_revision": 3},
                           headers={"X-CSRF-Token": approver_csrf})
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    rehearsal = client.post(f"/api/v1/inventory-documents/{key}/posting-rehearsal",
                            headers={"X-CSRF-Token": approver_csrf})
    assert rehearsal.status_code == 200
    assert rehearsal.json()["quantity_delta"] == 0.0
    assert rehearsal.json()["value_delta"] == 0.0
    assert len(rehearsal.json()["movements"]) == 2
    register = client.get("/api/v1/inventory-documents").json()
    assert register["total"] == 1
    assert register["posting_enabled"] is False
    assert register["controls"]["active_reservations"] == 1
