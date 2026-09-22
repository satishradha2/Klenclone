import json
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from klen_clone.auth import hash_password
from klen_clone.db import Base, make_engine
from klen_clone.erp_preview import create_app, navigation_access
from klen_clone.data_reviews import OperationalDataReview, start_review, transition_review
from klen_clone.models import (
    ErpAuditEvent, ErpLocation, ErpOrganization, ErpParty, ErpProductMaster, ErpProductUom,
    ErpTransactionDocument,
    RawFileManifest, RawRecord, SourceSnapshot, StgContact, StgProduct, StgProductUomProfile,
)
from klen_clone.operational import (
    OperationalAuditEvent, OperationalDraft, OperationalFinancialMigrationException,
    OperationalFiscalPeriod, OperationalOpeningBalanceBatch,
    OperationalInventoryLedgerEntry, OperationalJournalBatch, OperationalJournalLine,
    OperationalPostingProbe, OperationalReversalRequest,
    OperationalSchemaMigration, OperationalStockPosition, OperationalStockReservation,
    OperationalSubledgerEntry, OperationalWorkflowEvent, execute_posting, execute_reversal,
)
from klen_clone.operational_masters import OperationalLocationMaster, OperationalPartyMaster, OperationalProductMaster
from klen_clone.posting_integration import (
    OperationalIntegratedJournalLine, OperationalIntegratedPostingBatch,
    OperationalIntegratedStockEntry, execute_integrated_posting, execute_integrated_reversal,
)
from klen_clone.enterprise_setup import (
    OperationalBranch, OperationalCompanyProfile, OperationalFinancePolicy,
    OperationalVan, OperationalWarehouse, transition_operating_unit,
)
from klen_clone.access_control import OperationalRoleAssignment, OperationalUser
from klen_clone.finance_foundation import OperationalChartAccount, OperationalFinanceApproval
from klen_clone.finance_reconciliation import (
    OperationalFinanceReconciliationReview, initialize_finance_reconciliation,
)
from klen_clone.finance_ledger import OperationalGeneralJournal
from klen_clone.hrm import (
    OperationalHrmAttendance, OperationalHrmEmployee, OperationalHrmImportBatch, OperationalHrmShift,
)
from klen_clone.hrm_operations import (
    OperationalHrmAttendanceCorrection, OperationalHrmDepartment,
    OperationalHrmEmployeeProfile, OperationalHrmLeaveRequest,
)
from klen_clone.procurement import OperationalPurchaseOrder, OperationalSupplierQuotation
from klen_clone.cash_management import create_cash_account, decide_cash_account


def preview_client(tmp_path, *, include_hrm: bool = False) -> TestClient:
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
        for source_id, source_kind, document_no in (
            (1, "sale", "SALE-001"),
            (2, "sale_return", "SRETURN-001"),
            (3, "purchase", "PURCHASE-001"),
            (4, "purchase_return", "PRETURN-001"),
        ):
            session.add(ErpTransactionDocument(
                snapshot_id=snapshot.id, source_kind=source_kind, source_id=source_id,
                source_raw_record_id=raw.id, document_no=document_no,
                occurred_at=datetime(2026, 1, source_id), total_amount=source_id,
                paid_amount=0, due_amount=source_id, migration_status="preserved",
                operational_enabled=False, posting_enabled=False,
            ))
        if include_hrm:
            hrm_sources = {
                "users.csv": ("user", [
                    {"Username": "employee.one", "Name": "Employee One", "Role": "Sales", "Email": "one@example.invalid"},
                    {"Username": "employee.two", "Name": "Employee Two", "Role": "Operations", "Email": "two@example.invalid"},
                ]),
                "hrm_attendance_2026.csv": ("attendance", [
                    {"Date": "04/15/2026", "Employee": "Employee One",
                     "Clock In": "04/15/2026 09:38captured location", "Clock Out": "04/15/2026 18:09captured location",
                     "Work Duration": "8h 31m", "IP Address": "not displayed", "Shift": "Flexi"},
                    {"Date": "04/16/2026", "Employee": "Employee Two",
                     "Clock In": "04/16/2026 09:00", "Clock Out": "04/16/2026 17:00",
                     "Work Duration": "8h", "IP Address": "not displayed", "Shift": "Flexi"},
                ]),
                "hrm_shifts.csv": ("shift", [
                    {"Name": "Flexi", "Shift Type": "Flexible shift", "Start time": "", "End time": "", "Holiday": ""},
                ]),
            }
            for relative_path, (entity_type, payloads) in hrm_sources.items():
                hrm_manifest = RawFileManifest(
                    snapshot_id=snapshot.id, relative_path=relative_path, entity_type=entity_type,
                    sha256=(relative_path.encode().hex() + "0" * 64)[:64], byte_length=1,
                    media_type="text/csv", source_record_count=len(payloads),
                )
                session.add(hrm_manifest)
                session.flush()
                for ordinal, payload in enumerate(payloads, 1):
                    session.add(RawRecord(manifest_id=hrm_manifest.id, ordinal=ordinal, payload=payload))
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


def test_preview_is_independent_read_only_with_hrm_enabled_and_payroll_excluded(tmp_path):
    client = preview_client(tmp_path)
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["application"] == "Asas ERP"
    assert health.json()["mode"] == "independent_clone_preview"
    assert health.json()["posting_enabled"] is False
    assert health.json()["hrm_enabled"] is False
    assert health.json()["payroll_enabled"] is False
    assert "hr_payroll_enabled" not in health.json()
    assert health.headers["x-frame-options"] == "DENY"
    rejected = client.post("/api/v1/products", json={})
    assert rejected.status_code == 405
    assert rejected.headers["x-content-type-options"] == "nosniff"
    assert rejected.headers["x-request-id"]


def test_navigation_policy_is_server_owned_and_mutation_middleware_allows_controlled_workflows(tmp_path, monkeypatch):
    password = "navigation policy test password"
    users_file = tmp_path / "navigation-users.json"
    users_file.write_text(json.dumps({"users": [{
        "id": 1, "username": "quality-user", "password_hash": hash_password(password),
        "roles": ["quality_controller"],
        "permissions": ["clone.read", "quarantine.manage", "price_list.manage"],
        "allowed_locations": ["SHJ"],
    }]}), encoding="utf-8")
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_USERS_FILE", str(users_file))
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'operational.db'}")
    client = preview_client(tmp_path)
    login = client.post("/api/v1/auth/login", json={"username": "quality-user", "password": password})
    assert login.status_code == 200
    principal = login.json()["principal"]
    assert principal["navigation"]["policy_version"] == "2026-09-21"
    assert "warehouse-controls" not in principal["navigation"]["denied_routes"]
    assert "sales-orders" not in principal["navigation"]["denied_routes"]
    assert {"pos", "van-sales", "hrm"}.issubset(principal["navigation"]["denied_routes"])
    headers = {"X-CSRF-Token": login.json()["csrf_token"]}
    assert client.get("/api/v1/warehouse-controls").status_code == 200
    invalid_hold = client.post("/api/v1/warehouse-controls/quarantine-holds", headers=headers, json={})
    assert invalid_hold.status_code == 422
    assert invalid_hold.status_code != 405
    group = client.post("/api/v1/commercial-pricing/groups", headers=headers,
                        json={"group_code": "QA", "name": "Quality controlled"})
    assert group.status_code == 201
    assert group.json()["group_code"] == "QA"


def test_warehouse_traceability_api_enforces_identity_scope_and_maker_checker(tmp_path, monkeypatch):
    password = "warehouse traceability test password"
    users_file = tmp_path / "warehouse-traceability-users.json"
    users_file.write_text(json.dumps({"users": [{
        "id": 1, "username": "trace-user", "password_hash": hash_password(password),
        "roles": ["inventory_controller"],
        "permissions": ["clone.read", "barcode.manage", "serial.manage", "warehouse.scan",
                        "quarantine.manage"],
        "allowed_locations": ["SHJ"],
    }]}), encoding="utf-8")
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_USERS_FILE", str(users_file))
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'operational.db'}")
    client = preview_client(tmp_path)
    seed_operational_controls(client, "2")
    login = client.post("/api/v1/auth/login", json={"username": "trace-user", "password": password})
    assert login.status_code == 200
    headers = {"X-CSRF-Token": login.json()["csrf_token"]}

    barcode = client.post("/api/v1/warehouse-controls/barcodes", headers=headers, json={
        "barcode_value": "BC-SHJ-001", "sku": "SKU-001", "location_code": "SHJ",
        "factor_to_base": "1",
    })
    assert barcode.status_code == 201
    assert barcode.json()["barcode_value"] == "BC-SHJ-001"
    serial = client.post("/api/v1/warehouse-controls/serials", headers=headers, json={
        "serial_number": "SN-SHJ-001", "sku": "SKU-001", "location_code": "SHJ",
    })
    assert serial.status_code == 201
    serial_key = serial.json()["serial_key"]
    scan = client.post("/api/v1/warehouse-controls/scans", headers=headers, json={
        "scanned_value": "SN-SHJ-001", "location_code": "SHJ",
    })
    assert scan.status_code == 201
    assert scan.json()["outcome"] == "matched"

    quarantine = client.post(
        f"/api/v1/warehouse-controls/serials/{serial_key}/quarantine", headers=headers,
        json={"expected_revision": 1, "note": "Damaged packaging under quality review"},
    )
    assert quarantine.status_code == 200
    assert quarantine.json()["status"] == "quarantined"
    self_release = client.post(
        f"/api/v1/warehouse-controls/serials/{serial_key}/release", headers=headers,
        json={"expected_revision": 2, "note": "Attempted release by the same operator"},
    )
    assert self_release.status_code == 403
    wrong_location = client.post("/api/v1/warehouse-controls/serials", headers=headers, json={
        "serial_number": "SN-DXB-001", "sku": "SKU-001", "location_code": "DXB",
    })
    assert wrong_location.status_code == 404

    payload = client.get("/api/v1/warehouse-controls").json()
    assert payload["controls"]["active_barcodes"] == 1
    assert payload["controls"]["tracked_serials"] == 1
    assert payload["serial_units"][0]["status"] == "quarantined"
    approval_items = client.get("/api/v1/my-workspace").json()["items"]
    serial_approval = next(item for item in approval_items if item["resource_key"] == serial_key)
    assert serial_approval["workflow"] == "Serial quarantine release"
    assert serial_approval["action_eligible"] is False
    assert serial_approval["eligibility_reason"] == "independent_approver_required"


def test_navigation_policy_denies_restricted_workspaces_without_matching_permission():
    denied = navigation_access({"clone.read"})["denied_routes"]
    assert {"users-roles", "warehouse-controls", "sales-orders", "reviews",
            "chart-of-accounts", "ageing", "customer-statements", "accounting"}.issubset(denied)
    assert "overview" not in denied
    router = (Path(__file__).parents[1] / "src" / "klen_clone" / "static" / "erp.js").read_text(encoding="utf-8")
    assert "s.principal.navigation?.denied_routes" in router
    assert "deniedRoutes.has(active)" in router
    assert "restrictedLinks" not in router


def test_finance_workspace_read_guards_match_navigation_permissions(tmp_path, monkeypatch):
    password = "finance navigation test password"
    users_file = tmp_path / "finance-navigation-users.json"
    users_file.write_text(json.dumps({"users": [{
        "id": 1, "username": "finance-workspace-user", "password_hash": hash_password(password),
        "roles": ["custom_finance_workspace"],
        "permissions": ["finance.reconciliation.prepare", "journal.prepare", "credit.limit.prepare"],
        "allowed_locations": ["*"],
    }]}), encoding="utf-8")
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_USERS_FILE", str(users_file))
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'operational.db'}")
    client = preview_client(tmp_path)
    login = client.post("/api/v1/auth/login", json={"username": "finance-workspace-user", "password": password})
    assert login.status_code == 200
    denied = set(login.json()["principal"]["navigation"]["denied_routes"])
    assert {"accounting", "general-ledger", "credit-control"}.isdisjoint(denied)
    assert client.get("/api/v1/accounting").status_code == 200
    assert client.get("/api/v1/finance/reconciliation").status_code == 200
    assert client.get("/api/v1/general-ledger").status_code == 200
    assert client.get("/api/v1/credit-control").status_code == 200


def test_financial_report_reader_navigation_matches_read_endpoints(tmp_path, monkeypatch):
    password = "financial report reader password"
    users_file = tmp_path / "financial-report-reader-users.json"
    users_file.write_text(json.dumps({"users": [{
        "id": 1, "username": "financial-report-reader", "password_hash": hash_password(password),
        "roles": ["custom_financial_report_reader"],
        "permissions": ["financial_report.read"],
        "allowed_locations": ["*"],
    }]}), encoding="utf-8")
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_USERS_FILE", str(users_file))
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'operational.db'}")
    client = preview_client(tmp_path)
    login = client.post("/api/v1/auth/login", json={"username": "financial-report-reader", "password": password})
    assert login.status_code == 200
    denied = set(login.json()["principal"]["navigation"]["denied_routes"])
    assert {"chart-of-accounts", "financial-statements", "ageing", "customer-statements",
            "credit-control", "accounting", "general-ledger"}.isdisjoint(denied)
    assert client.get("/api/v1/finance/foundation").status_code == 200
    assert client.get("/api/v1/accounting").status_code == 200
    assert client.get("/api/v1/reports/ageing?ledger_kind=receivable").status_code == 200
    assert client.get("/api/v1/general-ledger").status_code == 200


def test_my_workspace_filters_approvals_by_permission_location_and_maker(tmp_path, monkeypatch):
    password = "approval workspace test password"
    users_file = tmp_path / "approval-workspace-users.json"
    users_file.write_text(json.dumps({"users": [{
        "id": 1, "username": "draft-approver", "password_hash": hash_password(password),
        "roles": ["custom_draft_approver"], "permissions": ["draft.approve"],
        "allowed_locations": ["SHJ"],
    }]}), encoding="utf-8")
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_USERS_FILE", str(users_file))
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'operational.db'}")
    client = preview_client(tmp_path)
    with client.app.state.operational_sessions() as session:
        for key, location, creator in (("visible-other", "SHJ", "sales-maker"),
                                       ("visible-own", "SHJ", "draft-approver"),
                                       ("hidden-location", "DXB", "sales-maker")):
            session.add(OperationalDraft(
                draft_key=key, draft_no=f"D-{key}", document_type="sale", party_code="CO-1",
                party_name_snapshot="Approval customer", location_code=location, currency_code="AED",
                subtotal=10, discount_amount=0, tax_amount=0, total_amount=10,
                status="submitted", posting_enabled=False, created_by=creator,
                state_changed_by=creator,
            ))
        session.commit()
    login = client.post("/api/v1/auth/login", json={"username": "draft-approver", "password": password})
    assert login.status_code == 200
    response = client.get("/api/v1/my-workspace")
    assert response.status_code == 200
    payload = response.json()
    assert payload["controls"]["visible_pending"] == 2
    assert payload["controls"]["actionable"] == 1
    assert payload["controls"]["self_submitted"] == 1
    assert {item["resource_key"] for item in payload["items"]} == {"visible-other", "visible-own"}
    own = next(item for item in payload["items"] if item["resource_key"] == "visible-own")
    assert own["action_eligible"] is False
    assert own["eligibility_reason"] == "independent_approver_required"
    assert all(item["route"] == "drafts" and item["posting_enabled"] is False
               for item in payload["items"])


def test_my_workspace_is_registered_in_shell_and_requires_authentication(tmp_path, monkeypatch):
    password = "workspace authentication test password"
    users_file = tmp_path / "workspace-auth-users.json"
    users_file.write_text(json.dumps({"users": [{
        "id": 1, "username": "workspace-reader", "password_hash": hash_password(password),
        "roles": ["workspace_reader"], "permissions": ["clone.read"],
        "allowed_locations": ["SHJ"],
    }]}), encoding="utf-8")
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_USERS_FILE", str(users_file))
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'operational.db'}")
    client = preview_client(tmp_path)
    assert client.get("/api/v1/my-workspace").status_code == 401
    shell = (Path(__file__).parents[1] / "src" / "klen_clone" / "static" / "erp.html").read_text(encoding="utf-8")
    router = (Path(__file__).parents[1] / "src" / "klen_clone" / "static" / "erp.js").read_text(encoding="utf-8")
    assert 'data-route="my-workspace"' in shell
    assert "async function myWorkspace()" in router
    assert "api('/my-workspace')" in router
    assert "else if(active==='my-workspace')await myWorkspace()" in router


def test_record_inspector_and_attention_center_are_centralized_read_only_surfaces():
    static_root = Path(__file__).parents[1] / "src" / "klen_clone" / "static"
    shell = (static_root / "erp.html").read_text(encoding="utf-8")
    components = (static_root / "workspace-components.js").read_text(encoding="utf-8")
    inspector = (static_root / "workspace-inspector.js").read_text(encoding="utf-8")

    assert 'id="attention-trigger"' in shell
    assert 'id="attention-center"' in shell
    assert 'id="record-inspector"' in shell
    assert "/static/workspace-inspector.css?v=" in shell
    assert "/static/workspace-inspector.js?v=" in shell
    assert "inspectable-row" in components
    assert "fetch('/api/v1/my-workspace'" in inspector
    assert "tr.inspectable-row" in inspector
    assert "method: 'POST'" not in inspector
    assert 'method: "POST"' not in inspector
    assert "method: 'PUT'" not in inspector
    assert 'method: "PUT"' not in inspector
    assert "method: 'PATCH'" not in inspector
    assert 'method: "PATCH"' not in inspector
    assert "method: 'DELETE'" not in inspector
    assert 'method: "DELETE"' not in inspector
    assert "X-CSRF-Token" not in inspector


def test_hrm_test_workspace_promotes_sealed_evidence_without_payroll(tmp_path, monkeypatch):
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'operational.db'}")
    client = preview_client(tmp_path, include_hrm=True)
    response = client.get("/api/v1/hrm")
    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["controls"]["employee_count"] == 2
    assert payload["controls"]["attendance_count"] == 2
    assert payload["controls"]["shift_count"] == 1
    assert payload["operations"]["controls"]["department_count"] == 5
    assert payload["operations"]["controls"]["profile_count"] == 2
    assert payload["operations"]["payroll"] == {"included": False, "record_count": 0}
    assert payload["payroll"] == {
        "included": False, "record_count": 0,
        "reason": "Payroll is outside the confirmed ERP scope and is never imported into this workspace.",
    }
    assert payload["privacy"]["ip_addresses_displayed"] is False
    assert payload["attendance"][1]["clock_in"] == "04/15/2026 09:38"
    assert "captured location" not in json.dumps(payload)
    with client.app.state.operational_sessions() as session:
        assert session.scalar(select(func.count(OperationalHrmImportBatch.id))) == 1
        assert session.scalar(select(func.count(OperationalHrmEmployee.id))) == 2
        assert session.scalar(select(func.count(OperationalHrmAttendance.id))) == 2
        assert session.scalar(select(func.count(OperationalHrmShift.id))) == 1
        assert session.scalar(select(func.count(OperationalHrmDepartment.id))) == 5
        assert session.scalar(select(func.count(OperationalHrmEmployeeProfile.id))) == 2
        assert session.get(OperationalSchemaMigration, "0021") is not None
        assert session.get(OperationalSchemaMigration, "0022") is not None


def test_hrm_operational_workflows_apply_maker_checker_without_mutating_source(tmp_path, monkeypatch):
    maker_password, manager_password, employee_password = (
        "hr maker test password", "hr manager test password", "employee self service password",
    )
    users_file = tmp_path / "hrm-workflow-users.json"
    users_file.write_text(json.dumps({"users": [
        {"id": 1, "username": "hr-maker", "password_hash": hash_password(maker_password),
         "roles": ["hr_officer"],
         "permissions": ["clone.read", "hrm.read", "hrm.employee.prepare", "leave.prepare", "attendance.prepare"],
         "allowed_locations": ["*"]},
        {"id": 2, "username": "hr-manager", "password_hash": hash_password(manager_password),
         "roles": ["hr_manager"],
         "permissions": ["clone.read", "hrm.read", "hrm.manage", "hrm.employee.approve", "leave.approve", "attendance.approve", "shift.manage"],
         "allowed_locations": ["*"]},
        {"id": 3, "username": "employee.one", "password_hash": hash_password(employee_password),
         "roles": ["employee_self_service"],
         "permissions": ["hrm.self.read", "leave.self.create", "attendance.self.create"],
         "allowed_locations": ["*"]},
    ]}), encoding="utf-8")
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_USERS_FILE", str(users_file))
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'operational.db'}")
    client = preview_client(tmp_path, include_hrm=True)

    maker_login = client.post("/api/v1/auth/login", json={"username": "hr-maker", "password": maker_password})
    maker_csrf = maker_login.json()["csrf_token"]
    workspace = client.get("/api/v1/hrm").json()
    employee_key = workspace["employees"][0]["employee_key"]
    attendance_id = workspace["attendance"][0]["id"]
    source_clock_in = workspace["attendance"][0]["clock_in"]

    leave = client.post("/api/v1/hrm/leave-requests", headers={"X-CSRF-Token": maker_csrf}, json={
        "employee_key": employee_key, "leave_type": "Annual", "starts_on": "2026-10-01",
        "ends_on": "2026-10-02", "reason": "Planned annual leave request",
    })
    assert leave.status_code == 201
    leave_row = leave.json()["operations"]["leave_requests"][0]
    correction = client.post("/api/v1/hrm/attendance-corrections", headers={"X-CSRF-Token": maker_csrf}, json={
        "attendance_id": attendance_id, "corrected_clock_in": "04/16/2026 09:05",
        "corrected_clock_out": None, "corrected_duration_minutes": None,
        "reason": "Clock-in evidence requires correction",
    })
    assert correction.status_code == 201
    correction_row = correction.json()["operations"]["attendance_corrections"][0]
    profile = workspace["operations"]["profiles"][0]
    employee_change = client.post("/api/v1/hrm/employee-changes", headers={"X-CSRF-Token": maker_csrf}, json={
        "employee_key": employee_key, "employee_no": profile["employee_no"],
        "department_code": profile["department_code"], "designation_code": profile["designation_code"],
        "join_date": "2026-01-01", "employment_status": "active",
        "note": "Complete employee lifecycle profile",
    })
    assert employee_change.status_code == 201
    changed_profile = next(row for row in employee_change.json()["operations"]["profiles"]
                           if row["employee_key"] == employee_key)

    manager_login = client.post("/api/v1/auth/login", json={"username": "hr-manager", "password": manager_password})
    manager_csrf = manager_login.json()["csrf_token"]
    approved_leave = client.post(
        f"/api/v1/hrm/leave-requests/{leave_row['leave_key']}/approve",
        headers={"X-CSRF-Token": manager_csrf},
        json={"expected_revision": leave_row["revision"], "note": "Coverage confirmed by HR manager"},
    )
    assert approved_leave.status_code == 200
    approved_correction = client.post(
        f"/api/v1/hrm/attendance-corrections/{correction_row['correction_key']}/approve",
        headers={"X-CSRF-Token": manager_csrf},
        json={"expected_revision": correction_row["revision"], "note": "Evidence independently reviewed"},
    )
    assert approved_correction.status_code == 200
    approved_employee = client.post(
        f"/api/v1/hrm/employee-changes/{changed_profile['profile_key']}/approve",
        headers={"X-CSRF-Token": manager_csrf},
        json={"expected_revision": changed_profile["revision"], "note": "Employee profile independently reviewed"},
    )
    assert approved_employee.status_code == 200
    assert client.post("/api/v1/hrm/departments", headers={"X-CSRF-Token": manager_csrf}, json={
        "code": "QA", "name": "Quality Assurance",
    }).status_code == 201
    assert client.post("/api/v1/hrm/designations", headers={"X-CSRF-Token": manager_csrf}, json={
        "code": "QA_LEAD", "name": "QA Lead", "department_code": "QA",
    }).status_code == 201
    assert client.post("/api/v1/hrm/holidays", headers={"X-CSRF-Token": manager_csrf}, json={
        "holiday_date": "2026-12-02", "name": "National Day", "department_code": None,
    }).status_code == 201
    assert client.post("/api/v1/hrm/shifts", headers={"X-CSRF-Token": manager_csrf}, json={
        "name": "Night Test", "shift_type": "Fixed shift", "start_time": "20:00", "end_time": "05:00",
    }).status_code == 201
    assignment = client.post("/api/v1/hrm/shift-assignments", headers={"X-CSRF-Token": manager_csrf}, json={
        "employee_key": employee_key, "shift_name": "Night Test", "effective_from": "2026-10-01",
        "effective_to": None,
    })
    assert assignment.status_code == 201
    assert assignment.json()["operations"]["controls"]["active_shift_assignments"] == 1
    assert client.get("/api/v1/hrm").json()["attendance"][0]["clock_in"] == source_clock_in

    employee_login = client.post("/api/v1/auth/login", json={
        "username": "employee.one", "password": employee_password,
    })
    employee_csrf = employee_login.json()["csrf_token"]
    assert client.get("/api/v1/hrm").status_code == 403
    self_service = client.get("/api/v1/hrm/self-service")
    assert self_service.status_code == 200
    assert [row["username"] for row in self_service.json()["employees"]] == ["employee.one"]
    other_employee_key = next(row["employee_key"] for row in workspace["employees"]
                              if row["username"] == "employee.two")
    forbidden = client.post("/api/v1/hrm/leave-requests", headers={"X-CSRF-Token": employee_csrf}, json={
        "employee_key": other_employee_key, "leave_type": "Annual", "starts_on": "2026-11-01",
        "ends_on": "2026-11-01", "reason": "Must not target another employee",
    })
    assert forbidden.status_code == 403
    with client.app.state.operational_sessions() as session:
        assert session.scalar(select(OperationalHrmLeaveRequest.status)) == "approved"
        assert session.scalar(select(OperationalHrmAttendanceCorrection.status)) == "approved"


def test_hrm_workspace_requires_hr_permission(tmp_path, monkeypatch):
    admin_password, finance_password = "admin hrm password", "finance only password"
    users_file = tmp_path / "hrm-users.json"
    users_file.write_text(json.dumps({"users": [
        {"id": 1, "username": "asas-admin", "password_hash": hash_password(admin_password),
         "roles": ["operations_administrator"], "permissions": ["clone.read", "enterprise.setup"],
         "allowed_locations": ["*"]},
        {"id": 2, "username": "finance-approver", "password_hash": hash_password(finance_password),
         "roles": ["finance_approver"], "permissions": ["clone.read", "finance.chart.approve"],
         "allowed_locations": ["*"]},
    ]}), encoding="utf-8")
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_USERS_FILE", str(users_file))
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'operational.db'}")
    client = preview_client(tmp_path, include_hrm=True)

    finance_login = client.post("/api/v1/auth/login", json={
        "username": "finance-approver", "password": finance_password,
    })
    assert finance_login.status_code == 200
    denied = client.get("/api/v1/hrm")
    assert denied.status_code == 403

    admin_login = client.post("/api/v1/auth/login", json={
        "username": "asas-admin", "password": admin_password,
    })
    assert admin_login.status_code == 200
    assert "hrm.read" in admin_login.json()["principal"]["permissions"]
    assert client.get("/api/v1/hrm").status_code == 200


def test_procurement_requisition_rfq_quote_comparison_and_po_approval(tmp_path, monkeypatch):
    passwords = {"requester": "requester test password", "buyer": "buyer test password",
                 "manager": "manager test password", "dxb-reader": "dxb reader test password",
                 "receiver": "receiver test password", "ap-maker": "ap maker test password",
                 "invoice-approver": "invoice approver test password"}
    users_file = tmp_path / "procurement-users.json"
    users_file.write_text(json.dumps({"users": [
        {"id": 1, "username": "requester", "password_hash": hash_password(passwords["requester"]),
         "roles": ["procurement_requester"], "permissions": ["purchase.requisition.create"], "allowed_locations": ["*"]},
        {"id": 2, "username": "buyer", "password_hash": hash_password(passwords["buyer"]),
         "roles": ["buyer"], "permissions": ["rfq.create", "supplier_quote.manage", "purchase_order.prepare"], "allowed_locations": ["*"]},
        {"id": 3, "username": "manager", "password_hash": hash_password(passwords["manager"]),
         "roles": ["procurement_manager"], "permissions": ["purchase.requisition.approve", "purchase_order.approve", "goods_receipt.accept"], "allowed_locations": ["*"]},
        {"id": 4, "username": "dxb-reader", "password_hash": hash_password(passwords["dxb-reader"]),
         "roles": ["procurement_requester"], "permissions": ["purchase.requisition.create"], "allowed_locations": ["DXB"]},
        {"id": 5, "username": "receiver", "password_hash": hash_password(passwords["receiver"]),
         "roles": ["goods_receipt_clerk"], "permissions": ["goods_receipt.create", "goods_receipt.submit"], "allowed_locations": ["SHJ"]},
        {"id": 6, "username": "ap-maker", "password_hash": hash_password(passwords["ap-maker"]),
         "roles": ["accounts_payable"], "permissions": ["supplier_bill.prepare", "supplier_bill.rehearse", "supplier_adjustment.prepare"], "allowed_locations": ["SHJ"]},
        {"id": 7, "username": "invoice-approver", "password_hash": hash_password(passwords["invoice-approver"]),
         "roles": ["finance_approver"], "permissions": ["supplier_bill.approve", "supplier_adjustment.approve"], "allowed_locations": ["SHJ"]},
    ]}), encoding="utf-8")
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_USERS_FILE", str(users_file))
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'operational.db'}")
    client = preview_client(tmp_path)
    with client.app.state.operational_sessions() as session:
        session.add(OperationalFiscalPeriod(
            period_key="PROC-FY-OPEN", starts_on=date(2020, 1, 1), ends_on=date(2035, 12, 31),
            status="open", rehearsal_enabled=True, approval_reference="procurement-test-approval",
            configured_by="test-controller",
        ))
        session.add(OperationalLocationMaster(
            location_key="location-SHJ", location_code="SHJ", name="Sharjah", status="active",
            source_snapshot_name="test", source_checksum="b" * 64, created_by="test",
        ))
        session.add(OperationalProductMaster(
            product_key="product-SKU-001", sku="SKU-001", name="Source product",
            base_uom="Piece", canonical_base_uom="piece", factor_to_base=1,
            purchase_price=2, selling_price=3, tax_rate=5, status="active",
            source_promoted=False, source_snapshot_name="test", source_checksum="c" * 64,
            created_by="test", updated_by="test",
        ))
        for index, (code, name) in enumerate((("SUP-1", "Supplier One"), ("SUP-2", "Supplier Two")), 1):
            session.add(OperationalPartyMaster(
                party_key=f"party-{code}", party_code=code, party_kind="supplier",
                legal_or_business_name=name, address="Sharjah, UAE", tax_number=f"10000000000000{index}",
                status="active", source_promoted=False,
                source_snapshot_name="test", source_checksum="a" * 64,
                created_by="test", updated_by="test",
            ))
        session.commit()

    def login(name):
        response = client.post("/api/v1/auth/login", json={"username": name, "password": passwords[name]})
        assert response.status_code == 200
        return {"X-CSRF-Token": response.json()["csrf_token"]}

    requester_headers = login("requester")
    required = date.today() + timedelta(days=30)
    duplicate = client.post("/api/v1/procurement/requisitions", headers=requester_headers, json={
        "needed_by": required.isoformat(), "location_code": "SHJ", "purpose": "Ambiguous duplicate test",
        "lines": [{"sku": "SKU-001", "quantity": "10"}, {"sku": "SKU-001", "quantity": "5"}],
    })
    assert duplicate.status_code == 422
    assert "same SKU" in duplicate.json()["detail"]
    response = client.post("/api/v1/procurement/requisitions", headers=requester_headers, json={
        "needed_by": required.isoformat(), "location_code": "SHJ", "purpose": "Restock test inventory",
        "lines": [{"sku": "SKU-001", "quantity": "10", "uom": "Piece", "specification": "Current approved specification"}],
    })
    assert response.status_code == 201, response.text
    requisition = response.json()["requisitions"][0]
    submitted = client.post(f"/api/v1/procurement/requisitions/{requisition['requisition_key']}/submit",
        headers=requester_headers, json={"expected_revision": requisition["revision"], "note": "Ready for manager review"})
    assert submitted.status_code == 200
    requisition = submitted.json()["requisitions"][0]

    manager_headers = login("manager")
    approved = client.post(f"/api/v1/procurement/requisitions/{requisition['requisition_key']}/approve",
        headers=manager_headers, json={"expected_revision": requisition["revision"], "note": "Business need independently approved"})
    assert approved.status_code == 200
    requisition = approved.json()["requisitions"][0]

    buyer_headers = login("buyer")
    rfq_response = client.post("/api/v1/procurement/rfqs", headers=buyer_headers, json={
        "requisition_key": requisition["requisition_key"],
        "response_due_on": (date.today() + timedelta(days=7)).isoformat(),
        "supplier_codes": ["SUP-1", "SUP-2"],
    })
    assert rfq_response.status_code == 201
    rfq = rfq_response.json()["rfqs"][0]
    invalid_validity = client.post(f"/api/v1/procurement/rfqs/{rfq['rfq_key']}/quotations",
        headers=buyer_headers, json={"supplier_code": "SUP-1", "quoted_on": date.today().isoformat(),
            "valid_until": (date.today() - timedelta(days=1)).isoformat(), "currency_code": "AED",
            "lines": [{"sku": "SKU-001", "unit_price": "10.00", "tax_rate": "5"}]})
    assert invalid_validity.status_code == 422
    assert "validity date" in invalid_validity.json()["detail"]
    quote_keys = {}
    for code, price in (("SUP-1", "10.00"), ("SUP-2", "8.00")):
        quoted = client.post(f"/api/v1/procurement/rfqs/{rfq['rfq_key']}/quotations",
            headers=buyer_headers, json={"supplier_code": code, "supplier_reference": f"Q-{code}",
                "quoted_on": date.today().isoformat(), "valid_until": required.isoformat(), "currency_code": "AED",
                "delivery_days": 5, "payment_terms": "30 days",
                "lines": [{"sku": "SKU-001", "unit_price": price, "tax_rate": "5"}]})
        assert quoted.status_code == 201
        quote_keys[code] = next(row["quotation_key"] for row in quoted.json()["rfqs"][0]["quotes"]
                                if row["supplier_code"] == code)
    comparison = quoted.json()["comparison"][0]
    assert next(row for row in comparison["quotes"] if row["supplier_code"] == "SUP-2")["lowest"] is True

    current_rfq = quoted.json()["rfqs"][0]
    awarded = client.post(f"/api/v1/procurement/rfqs/{rfq['rfq_key']}/award", headers=buyer_headers, json={
        "quotation_key": quote_keys["SUP-2"], "expected_revision": current_rfq["revision"],
        "expected_on": required.isoformat(), "note": "Lowest compliant AED quotation selected",
    })
    assert awarded.status_code == 201
    order = awarded.json()["purchase_orders"][0]
    assert order["supplier_code"] == "SUP-2"
    submitted_order = client.post(f"/api/v1/procurement/purchase-orders/{order['purchase_order_key']}/submit",
        headers=buyer_headers, json={"expected_revision": order["revision"], "note": "Purchase order ready for approval"})
    assert submitted_order.status_code == 200
    order = submitted_order.json()["purchase_orders"][0]
    manager_headers = login("manager")
    approved_order = client.post(f"/api/v1/procurement/purchase-orders/{order['purchase_order_key']}/approve",
        headers=manager_headers, json={"expected_revision": order["revision"], "note": "Commercial comparison independently approved"})
    assert approved_order.status_code == 200
    assert approved_order.json()["purchase_orders"][0]["status"] == "approved"
    assert approved_order.json()["controls"]["posting_enabled"] is False

    receiver_headers = login("receiver")
    receipt_response = client.post("/api/v1/goods-receipts", headers=receiver_headers, json={
        "supplier_code": "SUP-2", "location_code": "SHJ",
        "purchase_reference": order["purchase_order_no"], "supplier_delivery_note": "DN-TEST-1",
        "received_on": date.today().isoformat(), "notes": "Received against approved PO",
        "lines": [{"sku": "SKU-001", "ordered_quantity": "10", "received_quantity": "10",
            "accepted_quantity": "10", "rejected_quantity": "0", "uom": "Piece",
            "unit_cost": "8.00", "batch_no": None, "expiry_date": None, "rejection_reason": None}],
    })
    assert receipt_response.status_code == 201, receipt_response.text
    receipt = receipt_response.json()
    receipt_submitted = client.post(f"/api/v1/goods-receipts/{receipt['receipt_key']}/submit",
        headers=receiver_headers, json={"expected_revision": receipt["revision"], "note": "Ready for inspection"})
    assert receipt_submitted.status_code == 200
    manager_headers = login("manager")
    receipt_accepted = client.post(f"/api/v1/goods-receipts/{receipt['receipt_key']}/accept",
        headers=manager_headers, json={"expected_revision": receipt_submitted.json()["revision"],
                                      "note": "Quantity and condition accepted"})
    assert receipt_accepted.status_code == 200

    ap_headers = login("ap-maker")
    invoice_response = client.post("/api/v1/procurement/supplier-invoices", headers=ap_headers, json={
        "purchase_order_key": order["purchase_order_key"], "supplier_invoice_no": "SUP2-INV-001",
        "invoice_date": date.today().isoformat(), "due_date": required.isoformat(), "currency_code": "AED",
        "document_type": "tax_invoice", "supply_date": date.today().isoformat(),
        "supplier_name": "Supplier Two", "supplier_address": "Sharjah, UAE",
        "supplier_trn": "100000000000002", "recipient_name": "Asas General Trading LLC",
        "recipient_address": "Sharjah, UAE", "recipient_trn": "100000000000003",
        "lines": [{"sku": "SKU-001", "quantity": "10", "unit_price": "8.00", "tax_rate": "5"}],
    })
    assert invoice_response.status_code == 201, invoice_response.text
    invoice = invoice_response.json()["supplier_invoices"][0]
    matched_response = client.post(f"/api/v1/procurement/supplier-invoices/{invoice['invoice_key']}/match",
                                   headers=ap_headers)
    assert matched_response.status_code == 200
    invoice = matched_response.json()["supplier_invoices"][0]
    assert invoice["match_status"] == "passed" and invoice["status"] == "matched"
    approver_headers = login("invoice-approver")
    invoice_approved = client.post(
        f"/api/v1/procurement/supplier-invoices/{invoice['invoice_key']}/approve",
        headers=approver_headers,
        json={"expected_revision": invoice["revision"], "note": "PO, accepted receipt and invoice matched"})
    assert invoice_approved.status_code == 200
    assert invoice_approved.json()["supplier_invoices"][0]["status"] == "approved"
    assert invoice_approved.json()["supplier_invoices"][0]["posting_enabled"] is False
    assert invoice_approved.json()["supplier_invoices"][0]["tax_document"]["validation_status"] == "passed"
    ap_headers = login("ap-maker")
    rehearsal = client.post(
        f"/api/v1/procurement/supplier-invoices/{invoice['invoice_key']}/posting-rehearsal",
        headers=ap_headers)
    assert rehearsal.status_code == 200, rehearsal.text
    assert rehearsal.json()["debit"] == rehearsal.json()["credit"] == 84.0
    assert rehearsal.json()["posting_enabled"] is False
    assert len(rehearsal.json()["reversal_plan"]) == 3
    assert client.post(
        f"/api/v1/posting/supplier_invoice/{invoice['invoice_key']}",
        headers=ap_headers, json={"idempotency_key": rehearsal.json()["idempotency_key"]},
    ).status_code == 503

    adjustment_response = client.post("/api/v1/procurement/supplier-adjustments", headers=ap_headers, json={
        "invoice_key": invoice["invoice_key"], "adjustment_type": "credit_note",
        "supplier_reference": "SUP2-CN-001", "adjustment_date": date.today().isoformat(),
        "reason": "Two units returned after receipt inspection",
        "lines": [{"sku": "SKU-001", "quantity": "2", "unit_price": "8.00", "tax_rate": "5"}],
    })
    assert adjustment_response.status_code == 201, adjustment_response.text
    adjustment = adjustment_response.json()["supplier_adjustments"][0]
    adjustment_submitted = client.post(
        f"/api/v1/procurement/supplier-adjustments/{adjustment['adjustment_key']}/submit",
        headers=ap_headers, json={"expected_revision": 1, "note": "Supplier credit ready for review"})
    assert adjustment_submitted.status_code == 200
    approver_headers = login("invoice-approver")
    adjustment = adjustment_submitted.json()["supplier_adjustments"][0]
    adjustment_approved = client.post(
        f"/api/v1/procurement/supplier-adjustments/{adjustment['adjustment_key']}/approve",
        headers=approver_headers,
        json={"expected_revision": adjustment["revision"], "note": "Credit note independently approved"})
    assert adjustment_approved.status_code == 200
    assert adjustment_approved.json()["supplier_adjustments"][0]["status"] == "approved"
    assert adjustment_approved.json()["supplier_adjustments"][0]["posting_enabled"] is False
    ap_headers = login("ap-maker")
    adjustment_rehearsal = client.post(
        f"/api/v1/procurement/supplier-adjustments/{adjustment['adjustment_key']}/posting-rehearsal",
        headers=ap_headers)
    assert adjustment_rehearsal.status_code == 409
    assert "original supplier invoice must be posted" in adjustment_rehearsal.json()["detail"]
    assert client.post(
        f"/api/v1/posting/supplier_adjustment/{adjustment['adjustment_key']}",
        headers=ap_headers, json={"idempotency_key": "supplier-adjustment-disabled-test"},
    ).status_code == 503
    login("dxb-reader")
    scoped = client.get("/api/v1/procurement")
    assert scoped.status_code == 200
    assert scoped.json()["controls"] == {
        "requisitions": 0, "submitted_requisitions": 0, "open_rfqs": 0, "quotes": 0,
        "submitted_orders": 0, "approved_orders": 0, "posting_enabled": False,
        "supplier_invoices": 0, "invoice_match_exceptions": 0, "approved_supplier_invoices": 0,
            "tax_document_exceptions": 0, "invoice_posting_rehearsals": 0,
                "posted_supplier_invoices": 0,
                "supplier_adjustments": 0, "pending_supplier_adjustments": 0,
                "adjustment_posting_rehearsals": 0, "posted_supplier_adjustments": 0,
    }
    with client.app.state.operational_sessions() as session:
        assert session.scalar(select(func.count(OperationalSupplierQuotation.id))) == 2
        assert session.scalar(select(func.count(OperationalPurchaseOrder.id))) == 1


def test_enterprise_setup_is_seeded_in_operational_database_only(tmp_path, monkeypatch):
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'operational.db'}")
    client = preview_client(tmp_path)
    response = client.get("/api/v1/setup/enterprise")
    assert response.status_code == 200
    payload = response.json()
    assert payload["configured"] is True
    assert payload["company"]["accounting_framework"] == "full_ifrs"
    assert payload["company"]["status"] == "setup_pending"
    assert [(row["code"], row["name"], row["status"], row["is_primary"]) for row in payload["branches"]] == [
        ("MAIN", "Main branch", "planned", True)
    ]
    assert {row["code"] for row in payload["vans"]} == {"DXB", "RAK", "SHJ"}
    assert {row["type"] for row in payload["warehouses"]} == {"available", "returns", "quarantine", "in_transit"}
    assert payload["finance_policies"]["inventory_costing"]["method"] == "FIFO"
    finance = client.get("/api/v1/finance/foundation")
    assert finance.status_code == 200
    assert finance.json()["accounting_framework"] == "full_ifrs"
    assert len(finance.json()["accounts"]) >= 20
    assert finance.json()["posting_enabled"] is False
    with client.app.state.operational_sessions() as operational:
        assert operational.scalar(select(func.count(OperationalCompanyProfile.id))) == 1
        assert operational.scalar(select(func.count(OperationalBranch.id))) == 1
        assert operational.scalar(select(func.count(OperationalWarehouse.id))) == 4
        assert operational.scalar(select(func.count(OperationalVan.id))) == 3
        assert operational.scalar(select(func.count(OperationalFinancePolicy.id))) == 5


def test_enterprise_setup_changes_require_authenticated_administrator(tmp_path, monkeypatch):
    password = "temporary strong password"
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'operational.db'}")
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_ADMIN_USERNAME", "asas-admin")
    monkeypatch.setenv("ASAS_ADMIN_PASSWORD_HASH", hash_password(password))
    client = preview_client(tmp_path)
    assert client.post("/api/v1/setup/enterprise/branches", json={"branch_code": "AUH", "name": "Abu Dhabi"}).status_code == 401
    login = client.post("/api/v1/auth/login", json={"username": "asas-admin", "password": password}).json()
    headers = {"X-CSRF-Token": login["csrf_token"]}
    company = client.patch("/api/v1/setup/enterprise/company", json={
        "registered_address": "Configured later by administrator",
    }, headers=headers)
    assert company.status_code == 200
    created = client.post("/api/v1/setup/enterprise/branches", json={
        "branch_code": "AUH", "name": "Abu Dhabi branch",
    }, headers=headers)
    assert created.status_code == 201
    assert {row["code"] for row in created.json()["branches"]} == {"MAIN", "AUH"}
    assert next(row for row in created.json()["branches"] if row["code"] == "AUH")["status"] == "pending_approval"


def test_operating_unit_activation_requires_independent_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'operational.db'}")
    client = preview_client(tmp_path)
    with client.app.state.operational_sessions() as operational:
        requested = transition_operating_unit(operational, actor="maker", unit_kind="branch", unit_code="MAIN",
                                              action="request_activation", expected_revision=1,
                                              note="Ready for independent activation review")
        main = next(row for row in requested["branches"] if row["code"] == "MAIN")
        assert main["status"] == "pending_approval"
        try:
            transition_operating_unit(operational, actor="maker", unit_kind="branch", unit_code="MAIN",
                                      action="approve", expected_revision=2, note="Attempted self approval")
        except ValueError as exc:
            assert "cannot approve" in str(exc)
        else:
            raise AssertionError("Maker should not approve their own request")
        approved = transition_operating_unit(operational, actor="controller", unit_kind="branch", unit_code="MAIN",
                                             action="approve", expected_revision=2, note="Branch controls approved")
    assert next(row for row in approved["branches"] if row["code"] == "MAIN")["status"] == "active"


def test_users_can_receive_multiple_scoped_roles_with_segregation_controls(tmp_path, monkeypatch):
    password = "temporary strong password"
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'operational.db'}")
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_ADMIN_USERNAME", "asas-admin")
    monkeypatch.setenv("ASAS_ADMIN_PASSWORD_HASH", hash_password(password))
    client = preview_client(tmp_path)
    login = client.post("/api/v1/auth/login", json={"username": "asas-admin", "password": password}).json()
    headers = {"X-CSRF-Token": login["csrf_token"]}

    initial = client.get("/api/v1/access-control")
    assert initial.status_code == 200
    assert initial.json()["controls"]["role_count"] == len(initial.json()["roles"])
    assert {"hr_manager", "hr_officer", "employee_self_service"}.issubset(
        {row["code"] for row in initial.json()["roles"]}
    )
    assert initial.json()["controls"]["passwords_stored_here"] is False
    assert initial.json()["users"][0]["identity_ready"] is True
    assert initial.json()["users"][0]["assignments"][0]["role_code"] == "administrator"
    session_payload = client.get("/api/v1/auth/session").json()["principal"]
    assert "administrator" in session_payload["roles"]
    assert "user.manage" in session_payload["permissions"]

    created = client.post("/api/v1/access-control/users", headers=headers, json={
        "login_name": "purchase.manager", "display_name": "Purchase Manager",
    })
    assert created.status_code == 201
    target = next(row for row in created.json()["users"] if row["login_name"] == "purchase.manager")
    assert target["status"] == "pending_provisioning"
    user_key = target["user_key"]

    for role in ("buyer", "goods_receipt_clerk"):
        assigned = client.post(f"/api/v1/access-control/users/{user_key}/assignments", headers=headers, json={
            "role_code": role, "company_code": "ASAS", "branch_code": "MAIN",
            "effective_from": "2026-01-01",
        })
        assert assigned.status_code == 201
    target = next(row for row in assigned.json()["users"] if row["user_key"] == user_key)
    assert {row["role_code"] for row in target["assignments"]} == {"buyer", "goods_receipt_clerk"}

    maker = client.post(f"/api/v1/access-control/users/{user_key}/assignments", headers=headers, json={
        "role_code": "finance_maker", "company_code": "ASAS", "effective_from": "2026-01-01",
    })
    assert maker.status_code == 201
    conflict = client.post(f"/api/v1/access-control/users/{user_key}/assignments", headers=headers, json={
        "role_code": "finance_approver", "company_code": "ASAS", "effective_from": "2026-01-01",
        "approval_limit_aed": "10000",
    })
    assert conflict.status_code == 422
    assert "cannot overlap" in conflict.json()["detail"]
    assert client.patch(f"/api/v1/access-control/users/{user_key}/status", headers=headers,
                        json={"status": "active"}).status_code == 422
    with client.app.state.operational_sessions() as session:
        assert session.scalar(select(func.count(OperationalUser.id))) == 2
        assert session.scalar(select(func.count(OperationalRoleAssignment.id))) == 4


def test_finance_approval_queue_requires_independent_revision_checked_decision(tmp_path, monkeypatch):
    maker_password, approver_password = "maker temporary password", "approver temporary password"
    users_file = tmp_path / "finance-users.json"
    users_file.write_text(json.dumps({"users": [
        {"id": 1, "username": "finance-maker", "password_hash": hash_password(maker_password),
         "roles": ["finance_maker"],
         "permissions": ["clone.read", "finance.chart.prepare", "finance.mapping.prepare", "finance.chart.approve"],
         "allowed_locations": ["SHJ"]},
        {"id": 2, "username": "finance-approver", "password_hash": hash_password(approver_password),
         "roles": ["finance_approver"],
         "permissions": ["clone.read", "finance.chart.approve", "finance.mapping.approve"],
         "allowed_locations": ["SHJ"]},
    ]}), encoding="utf-8")
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_USERS_FILE", str(users_file))
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'finance.db'}")
    client = preview_client(tmp_path)

    maker = client.post("/api/v1/auth/login", json={
        "username": "finance-maker", "password": maker_password,
    }).json()
    maker_headers = {"X-CSRF-Token": maker["csrf_token"]}
    request_url = "/api/v1/finance/approvals/chart_account/1100/request"
    assert client.post(request_url, json={"note": "Ready for finance review"}).status_code == 403
    requested = client.post(request_url, headers=maker_headers,
                            json={"note": "Ready for finance review"})
    assert requested.status_code == 200
    account = next(row for row in requested.json()["accounts"] if row["code"] == "1100")
    assert account["status"] == "draft"
    assert account["approval"]["status"] == "pending"
    assert account["approval"]["revision"] == 1
    self_decision = client.post(
        "/api/v1/finance/approvals/chart_account/1100/approve", headers=maker_headers,
        json={"expected_revision": 1, "note": "Attempted self approval"},
    )
    assert self_decision.status_code == 403

    approver = client.post("/api/v1/auth/login", json={
        "username": "finance-approver", "password": approver_password,
    }).json()
    approver_headers = {"X-CSRF-Token": approver["csrf_token"]}
    stale = client.post(
        "/api/v1/finance/approvals/chart_account/1100/approve", headers=approver_headers,
        json={"expected_revision": 9, "note": "Stale approval attempt"},
    )
    assert stale.status_code == 409
    approved = client.post(
        "/api/v1/finance/approvals/chart_account/1100/approve", headers=approver_headers,
        json={"expected_revision": 1, "note": "Account control reviewed"},
    )
    assert approved.status_code == 200
    account = next(row for row in approved.json()["accounts"] if row["code"] == "1100")
    assert account["status"] == "active"
    assert account["approval"]["status"] == "approved"
    assert account["approval"]["revision"] == 2
    with client.app.state.operational_sessions() as session:
        assert session.scalar(select(func.count(OperationalChartAccount.id)).where(
            OperationalChartAccount.status == "active")) == 1
        assert session.scalar(select(func.count(OperationalFinanceApproval.id))) == 1
        assert session.scalar(select(func.count(OperationalAuditEvent.id)).where(
            OperationalAuditEvent.event_type.like("finance.approval_%"))) == 2


def test_finance_reconciliation_plan_is_independent_and_does_not_clear_source_variance(tmp_path, monkeypatch):
    maker_password, approver_password = "maker reconciliation password", "approver reconciliation password"
    users_file = tmp_path / "reconciliation-users.json"
    users_file.write_text(json.dumps({"users": [
        {"id": 1, "username": "finance-maker", "password_hash": hash_password(maker_password),
         "roles": ["finance_maker"],
         "permissions": ["clone.read", "financial_report.read", "finance.reconciliation.prepare"],
         "allowed_locations": ["*"]},
        {"id": 2, "username": "finance-approver", "password_hash": hash_password(approver_password),
         "roles": ["finance_approver"],
         "permissions": ["clone.read", "financial_report.read", "finance.reconciliation.approve"],
         "allowed_locations": ["*"]},
    ]}), encoding="utf-8")
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_USERS_FILE", str(users_file))
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'reconciliation.db'}")
    client = preview_client(tmp_path)
    with client.app.state.operational_sessions() as session:
        batch = OperationalOpeningBalanceBatch(
            batch_key="b" * 64, source_capture="test-capture", source_manifest_sha256="c" * 64,
            source_atomic=False, approval_reference="test-only", imported_by="test",
            receivable_rows=1, receivable_amount="100", customer_advance_rows=0,
            customer_advance_amount="0", payable_rows=1, payable_amount="90",
            supplier_advance_rows=0, supplier_advance_amount="0",
            status="approved_test_nonposting",
        )
        session.add(batch)
        session.flush()
        session.add(OperationalFinancialMigrationException(
            batch_id=batch.id, control_name="customer_header_due", authoritative_amount="100",
            comparison_amount="98", variance_amount="2",
            reason="Non-atomic test evidence requires final-sync review", status="open",
        ))
        session.commit()
        initialize_finance_reconciliation(session, snapshot_name="preview-snapshot", trial_balance={
            "rows": 2, "debit": "110", "credit": "100", "difference": "10",
        })

    maker = client.post("/api/v1/auth/login", json={
        "username": "finance-maker", "password": maker_password,
    }).json()
    maker_headers = {"X-CSRF-Token": maker["csrf_token"]}
    reviews = client.get("/api/v1/finance/reconciliation").json()["reviews"]
    assert len(reviews) == 2
    exception_review = next(row for row in reviews if row["control_type"] == "opening_balance_exception")
    assert exception_review["cause_analysis"]["confidence"] == "requires final-sync investigation"
    assert "customers_current.csv" in exception_review["cause_analysis"]["evidence_sources"]
    trial_review = next(row for row in reviews if row["control_type"] == "trial_balance")
    assert trial_review["cause_analysis"]["confidence"] == "partially explained"
    assert "AED 26,685.11" in trial_review["cause_analysis"]["summary"]
    assert "AED 41,042.55" in trial_review["cause_analysis"]["summary"]
    assert len(trial_review["cause_analysis"]["supporting_facts"]) == 4
    request_url = f"/api/v1/finance/reconciliation/{exception_review['review_key']}/request"
    requested = client.post(request_url, headers=maker_headers, json={
        "resolution_type": "recheck_final_sync",
        "note": "Recheck this variance against the final fresh BizModo sync",
    })
    assert requested.status_code == 200
    pending = next(row for row in requested.json()["reviews"] if row["review_key"] == exception_review["review_key"])
    assert pending["status"] == "pending" and pending["revision"] == 2
    self_decision = client.post(
        f"/api/v1/finance/reconciliation/{exception_review['review_key']}/approve",
        headers=maker_headers, json={"expected_revision": 2, "note": "Maker cannot approve"},
    )
    assert self_decision.status_code == 403

    approver = client.post("/api/v1/auth/login", json={
        "username": "finance-approver", "password": approver_password,
    }).json()
    approved = client.post(
        f"/api/v1/finance/reconciliation/{exception_review['review_key']}/approve",
        headers={"X-CSRF-Token": approver["csrf_token"]},
        json={"expected_revision": 2, "note": "Plan reviewed for test data only"},
    )
    assert approved.status_code == 200
    result = next(row for row in approved.json()["reviews"] if row["review_key"] == exception_review["review_key"])
    assert result["status"] == "approved" and result["posting_enabled"] is False
    with client.app.state.operational_sessions() as session:
        assert session.scalar(select(OperationalFinancialMigrationException.status)) == "open"
        assert session.scalar(select(func.count(OperationalFinanceReconciliationReview.id))) == 2
        assert session.scalar(select(func.count(OperationalAuditEvent.id)).where(
            OperationalAuditEvent.event_type.like("finance.reconciliation_%"))) == 3


def test_general_journal_is_balanced_approved_and_never_posted(tmp_path, monkeypatch):
    maker_password, approver_password = "journal maker password", "journal approver password"
    users_file = tmp_path / "journal-users.json"
    users_file.write_text(json.dumps({"users": [
        {"id": 1, "username": "journal-maker", "password_hash": hash_password(maker_password),
         "roles": ["finance_maker"],
         "permissions": ["clone.read", "financial_report.read", "journal.prepare"],
         "allowed_locations": ["*"]},
        {"id": 2, "username": "journal-approver", "password_hash": hash_password(approver_password),
         "roles": ["finance_approver"],
         "permissions": ["clone.read", "financial_report.read", "journal.approve"],
         "allowed_locations": ["*"]},
    ]}), encoding="utf-8")
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_USERS_FILE", str(users_file))
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'journal.db'}")
    client = preview_client(tmp_path)
    with client.app.state.operational_sessions() as session:
        for account in session.scalars(select(OperationalChartAccount)):
            account.status = "active"
        session.commit()

    maker = client.post("/api/v1/auth/login", json={
        "username": "journal-maker", "password": maker_password,
    }).json()
    maker_headers = {"X-CSRF-Token": maker["csrf_token"]}
    unbalanced = client.post("/api/v1/general-ledger/journals", headers=maker_headers, json={
        "journal_date": "2026-09-15", "branch_code": "MAIN",
        "description": "Rejected unbalanced test journal",
        "lines": [
            {"account_code": "1100", "debit": "100", "credit": "0"},
            {"account_code": "3000", "debit": "0", "credit": "99"},
        ],
    })
    assert unbalanced.status_code == 422
    created = client.post("/api/v1/general-ledger/journals", headers=maker_headers, json={
        "journal_date": "2026-09-15", "branch_code": "MAIN", "reference": "TEST-EQUITY",
        "description": "Balanced test-only capital journal",
        "lines": [
            {"account_code": "1100", "description": "Test cash", "debit": "100", "credit": "0"},
            {"account_code": "3000", "description": "Test capital", "debit": "0", "credit": "100"},
        ],
    })
    assert created.status_code == 201
    journal = created.json()["journals"][0]
    assert journal["status"] == "draft" and journal["posting_enabled"] is False
    assert created.json()["trial_balance"]["debit"] == 0
    requested = client.post(
        f"/api/v1/general-ledger/journals/{journal['journal_key']}/request",
        headers=maker_headers,
        json={"expected_revision": 1, "note": "Ready for independent test review"},
    )
    assert requested.status_code == 200
    pending = requested.json()["journals"][0]
    assert pending["status"] == "pending" and pending["revision"] == 2
    self_approval = client.post(
        f"/api/v1/general-ledger/journals/{journal['journal_key']}/approve",
        headers=maker_headers,
        json={"expected_revision": 2, "note": "Maker cannot approve this journal"},
    )
    assert self_approval.status_code == 403

    approver = client.post("/api/v1/auth/login", json={
        "username": "journal-approver", "password": approver_password,
    }).json()
    approved = client.post(
        f"/api/v1/general-ledger/journals/{journal['journal_key']}/approve",
        headers={"X-CSRF-Token": approver["csrf_token"]},
        json={"expected_revision": 2, "note": "Approved for test projection only"},
    )
    assert approved.status_code == 200
    payload = approved.json()
    assert payload["journals"][0]["status"] == "approved"
    assert payload["trial_balance"]["debit"] == payload["trial_balance"]["credit"] == 100
    assert payload["trial_balance"]["difference"] == 0
    assert payload["statement_of_financial_position"]["difference"] == 0
    assert payload["controls"]["permanent_journal_batches"] == 0
    with client.app.state.operational_sessions() as session:
        assert session.scalar(select(func.count(OperationalGeneralJournal.id))) == 1
        assert session.scalar(select(func.count(OperationalJournalBatch.id))) == 0


def test_preview_overview_and_product_register_use_clone_database(tmp_path):
    client = preview_client(tmp_path)
    overview = client.get("/api/v1/overview")
    assert overview.status_code == 200
    assert overview.json()["organization"] == "Asas General Trading LLC"
    assert overview.json()["counts"]["products"] == 1
    sales = client.get("/api/v1/sales").json()
    purchases = client.get("/api/v1/purchases").json()
    assert sales["total"] == overview.json()["counts"]["sales"] == 1
    assert purchases["total"] == overview.json()["counts"]["purchases"] == 1
    assert {row["source_kind"] for row in sales["items"]} == {"sale"}
    assert {row["source_kind"] for row in purchases["items"]} == {"purchase"}
    products = client.get("/api/v1/products?q=SKU-001")
    assert products.status_code == 200
    assert products.json()["total"] == 1
    assert products.json()["items"][0]["name"] == "Source product"
    page = client.get("/").text
    assert "ASAS ERP" in page
    assert "#general-ledger" in page and "/static/general-ledger.js" in page
    assert "/static/glossary.js" in page and "/static/glossary.css" in page
    assert "/static/table-pagination.js" in page and "/static/pagination.css" in page
    glossary = client.get("/static/glossary.js")
    assert glossary.status_code == 200
    assert "PROVISIONAL_OVERLAY" in glossary.text
    paginator = client.get("/static/table-pagination.js")
    assert paginator.status_code == 200 and "pageSize = 25" in paginator.text


def test_promoted_product_can_be_edited_and_deactivated_with_revision_control(tmp_path, monkeypatch):
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_ADMIN_USERNAME", "asas-admin")
    monkeypatch.setenv("ASAS_ADMIN_PASSWORD_HASH", hash_password("temporary strong password"))
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'masters.db'}")
    client = preview_client(tmp_path)
    with client.app.state.operational_sessions() as session:
        session.add(OperationalProductMaster(product_key="product-1", sku="SKU-001", name="Promoted product",
            base_uom="Piece", canonical_base_uom="piece", factor_to_base=1, purchase_price=2,
            selling_price=3, tax_rate=5, status="active", source_promoted=True,
            source_snapshot_name="preview-snapshot", source_checksum="a" * 64,
            created_by="migration", updated_by="migration"))
        session.commit()
    login = client.post("/api/v1/auth/login", json={"username": "asas-admin", "password": "temporary strong password"}).json()
    headers = {"X-CSRF-Token": login["csrf_token"]}
    listed = client.get("/api/v1/products?q=SKU-001").json()["items"][0]
    assert listed["name"] == "Promoted product" and listed["revision"] == 1
    updated = client.patch("/api/v1/master-data/products/SKU-001", headers=headers, json={
        "expected_revision": 1, "name": "Updated product", "category_name": "Cleaning",
        "brand_name": None, "purchase_price": "2.50", "selling_price": "4.00", "tax_rate": "5",
    })
    assert updated.status_code == 200 and updated.json()["revision"] == 2
    stale = client.post("/api/v1/master-data/products/SKU-001/deactivate", headers=headers,
                        json={"expected_revision": 1})
    assert stale.status_code == 409
    inactive = client.post("/api/v1/master-data/products/SKU-001/deactivate", headers=headers,
                           json={"expected_revision": 2, "note": "Stopped"})
    assert inactive.status_code == 200 and inactive.json()["master_status"] == "inactive"
    blocked_draft = client.post("/api/v1/drafts", headers=headers, json={
        "document_type": "sale", "party_code": "CO-001", "location_code": "SHJ",
        "discount_amount": "0", "lines": [{"sku": "SKU-001", "quantity": "1",
            "uom": "Piece", "unit_price": "4.00", "tax_rate": "5"}],
    })
    assert blocked_draft.status_code == 422
    assert "inactive in the operational master" in blocked_draft.json()["detail"]


def test_operational_product_register_exposes_every_record_through_pagination(tmp_path, monkeypatch):
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'paged-masters.db'}")
    client = preview_client(tmp_path)
    with client.app.state.operational_sessions() as session:
        session.add_all([OperationalProductMaster(
            product_key=f"product-{index}", sku=f"SKU-{index:03d}", name=f"Product {index:03d}",
            base_uom="Piece", canonical_base_uom="piece", factor_to_base=1,
            purchase_price=2, selling_price=3, tax_rate=5, status="active",
            source_promoted=True, source_snapshot_name="preview-snapshot",
            source_checksum=f"{index:064x}", created_by="migration", updated_by="migration",
        ) for index in range(55)])
        session.commit()
    first = client.get("/api/v1/products?limit=25&offset=0").json()
    middle = client.get("/api/v1/products?limit=25&offset=25").json()
    last = client.get("/api/v1/products?limit=25&offset=50").json()
    assert first["total"] == middle["total"] == last["total"] == 55
    assert len(first["items"]) == len(middle["items"]) == 25
    assert len(last["items"]) == 5
    assert {row["sku"] for row in first["items"]}.isdisjoint(
        {row["sku"] for row in middle["items"]})


def test_review_queue_open_filter_excludes_verified_history(tmp_path, monkeypatch):
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'review-filter.db'}")
    client = preview_client(tmp_path)
    with client.app.state.operational_sessions() as session:
        verified = start_review(session, entity_type="sale", source_record_key="INV-VERIFIED",
                                source_status="captured", original_payload={"document_no": "INV-VERIFIED"},
                                actor="test-reviewer")
        transition_review(session, verified, action="verify", expected_revision=verified.revision,
                          actor="test-reviewer", rationale="Matched source evidence")
        corrected = start_review(session, entity_type="purchase", source_record_key="PO-CORRECTED",
                                 source_status="captured", original_payload={"document_no": "PO-CORRECTED"},
                                 actor="test-reviewer")
        transition_review(session, corrected, action="correct", expected_revision=corrected.revision,
                          actor="test-reviewer", rationale="Corrected from source document",
                          corrected_payload={"document_no": "PO-CORRECTED", "total_amount": "10.00"})
        session.commit()

    open_queue = client.get("/api/v1/data-reviews?status=open").json()
    verified_history = client.get("/api/v1/data-reviews?status=verified").json()
    assert open_queue["total"] == 1
    assert open_queue["items"][0]["status"] == "corrected"
    assert verified_history["total"] == 1
    assert verified_history["items"][0]["status"] == "verified"


def test_promoted_party_can_be_edited_and_reactivated_with_audit(tmp_path, monkeypatch):
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_ADMIN_USERNAME", "asas-admin")
    monkeypatch.setenv("ASAS_ADMIN_PASSWORD_HASH", hash_password("temporary strong password"))
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'party-masters.db'}")
    client = preview_client(tmp_path)
    with client.app.state.operational_sessions() as session:
        session.add(OperationalPartyMaster(
            party_key="party-1", party_code="CO-001", party_kind="customer",
            legal_or_business_name="Promoted customer", status="inactive", source_promoted=True,
            source_snapshot_name="preview-snapshot", source_checksum="b" * 64,
            created_by="migration", updated_by="migration",
        ))
        session.commit()
    login = client.post("/api/v1/auth/login", json={
        "username": "asas-admin", "password": "temporary strong password",
    }).json()
    headers = {"X-CSRF-Token": login["csrf_token"]}
    listed = client.get("/api/v1/customers?q=CO-001").json()["items"][0]
    assert listed["email"] is None and listed["revision"] == 1
    updated = client.patch("/api/v1/master-data/parties/CO-001", headers=headers, json={
        "expected_revision": 1, "legal_or_business_name": "Updated customer",
        "contact_name": "Buyer", "email": "buyer@example.com", "mobile": "0500000000",
        "address": "Dubai", "tax_number": "TRN-001",
    })
    assert updated.status_code == 200 and updated.json()["revision"] == 2
    active = client.post("/api/v1/master-data/parties/CO-001/reactivate", headers=headers,
                         json={"expected_revision": 2, "note": "Approved for trading"})
    assert active.status_code == 200 and active.json()["master_status"] == "active"
    with client.app.state.operational_sessions() as session:
        assert session.scalar(select(func.count(OperationalAuditEvent.id)).where(
            OperationalAuditEvent.resource_key == "party-1")) == 2


def test_preview_authentication_session_csrf_and_audit(tmp_path, monkeypatch):
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_ADMIN_USERNAME", "asas-admin")
    monkeypatch.setenv("ASAS_ADMIN_PASSWORD_HASH", hash_password("temporary strong password"))
    client = preview_client(tmp_path)

    assert client.get("/api/v1/overview").status_code == 401
    login_page = client.get("/").text
    assert "Welcome back" in login_page
    assert "Controlled staging" in login_page
    assert "Source protected" in login_page
    assert "/static/asas-login.css?v=20260922-modern-1" in login_page
    denied = client.post("/api/v1/auth/login", json={"username": "asas-admin", "password": "wrong"})
    assert denied.status_code == 401
    login = client.post("/api/v1/auth/login", json={
        "username": "asas-admin", "password": "temporary strong password",
    })
    assert login.status_code == 200
    assert login.json()["principal"]["roles"] == ["operations_administrator"]
    assert login.json()["principal"]["posting_enabled"] is False
    assert client.get("/api/v1/overview").status_code == 200
    deployment = client.get("/api/v1/deployment/readiness")
    assert deployment.status_code == 200
    assert deployment.json()["production_ready"] is False
    assert deployment.json()["gates"]["hrm_included"] is True
    assert deployment.json()["gates"]["payroll_excluded"] is True
    assert "hr_payroll_excluded" not in deployment.json()["gates"]
    completion = client.get("/api/v1/completion-audit")
    assert completion.status_code == 200
    assert completion.json()["assessment"] == "incomplete"
    assert completion.json()["summary"]["route_regressions"] == 0
    assert completion.json()["scope"]["hrm_included"] is True
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
    with client.app.state.operational_sessions() as session:
        session.add(OperationalProductMaster(
            product_key="product-plural-uom", sku="SKU-001", name="Source product",
            base_uom="Pieces", canonical_base_uom="pieces", factor_to_base=1,
            purchase_price=2, selling_price=3, tax_rate=5, status="active",
            source_promoted=True, source_snapshot_name="preview-snapshot",
            source_checksum="d" * 64, created_by="migration", updated_by="migration",
        ))
        session.commit()
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
        assert session.scalar(select(func.count(OperationalAuditEvent.id)).where(
            OperationalAuditEvent.event_type.like("draft.%"))) == 4
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
        assert session.get(OperationalSchemaMigration, "0049") is not None
        assert session.scalar(select(func.count(OperationalStockReservation.id))) == 1
        assert session.scalar(select(func.count(OperationalJournalBatch.id))) == 0
        assert session.scalar(select(func.count(OperationalSubledgerEntry.id))) == 0
        assert session.scalar(select(func.count(OperationalReversalRequest.id))) == 0

    with client.app.state.operational_sessions() as session:
        draft = session.scalar(select(OperationalDraft).where(
            OperationalDraft.draft_key == created["draft_key"]))
        posted = execute_integrated_posting(
            session, resource_type="sales_invoice", resource_key=draft.draft_key,
            actor="posting-controller",
            idempotency_key=rehearsal.json()["idempotency_key"],
        )
        assert posted["status"] == "posted"
        assert posted["idempotent_replay"] is False
        assert session.scalar(select(OperationalStockPosition)).quantity_on_hand == 98
        assert session.scalar(select(OperationalStockPosition)).quantity_reserved == 0
        assert session.scalar(select(OperationalStockReservation)).status == "consumed"
        assert session.scalar(select(func.count(OperationalIntegratedJournalLine.id))) == 5
        assert session.scalar(select(func.count(OperationalIntegratedStockEntry.id))) == 1
        replay = execute_integrated_posting(
            session, resource_type="sales_invoice", resource_key=draft.draft_key,
            actor="posting-controller",
            idempotency_key=rehearsal.json()["idempotency_key"],
        )
        assert replay["idempotent_replay"] is True
        batch = session.scalar(select(OperationalIntegratedPostingBatch).where(
            OperationalIntegratedPostingBatch.batch_key == posted["batch_key"]))
        reversed_batch = execute_integrated_reversal(
            session, batch, actor="reversal-controller", reason="test exact reversal",
        )
        assert reversed_batch["status"] == "posted"
        assert session.scalar(select(OperationalStockPosition)).quantity_on_hand == 100
        assert session.scalar(select(func.count(OperationalIntegratedPostingBatch.id))) == 2
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


def test_customer_advance_receipt_api_is_permission_protected_and_nonposting(tmp_path, monkeypatch):
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_ADMIN_USERNAME", "asas-admin")
    monkeypatch.setenv("ASAS_ADMIN_PASSWORD_HASH", hash_password("temporary strong password"))
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'payments-api.db'}")
    client = preview_client(tmp_path)
    seed_operational_controls(client)
    login = client.post("/api/v1/auth/login", json={
        "username": "asas-admin", "password": "temporary strong password",
    }).json()
    csrf = login["csrf_token"]
    payload = {"payment_type": "customer_receipt", "party_code": "CO-001",
        "location_code": "SHJ", "payment_date": "2026-09-09", "payment_method": "cash",
        "cash_bank_account_code": "Cash - SHJ", "amount": "125.50", "allocations": []}
    assert client.post("/api/v1/payments", json=payload).status_code == 403
    created = client.post("/api/v1/payments", json=payload,
                          headers={"X-CSRF-Token": csrf})
    assert created.status_code == 201
    assert created.json()["allocated_amount"] == 0.0
    assert created.json()["unallocated_amount"] == 125.5
    submitted = client.post(f"/api/v1/payments/{created.json()['payment_key']}/submit",
        json={"expected_revision": 1}, headers={"X-CSRF-Token": csrf})
    assert submitted.status_code == 200 and submitted.json()["status"] == "submitted"
    register = client.get("/api/v1/payments").json()
    assert register["total"] == 1 and register["controls"]["posted"] == 0
    ageing = client.get("/api/v1/reports/ageing?ledger_kind=receivable&as_of=2026-09-09")
    assert ageing.status_code == 200
    assert ageing.json()["age_basis"] == "invoice_date"
    assert ageing.json()["due_date_available"] is False
    statement = client.get(
        "/api/v1/reports/customer-statement?party_code=CO-001&as_of=2026-09-09"
    )
    assert statement.status_code == 200
    assert statement.json()["pending_receipts"] == 125.5
    assert statement.json()["posting_enabled"] is False
    accounting = client.get("/api/v1/accounting").json()
    assert accounting["accounting_summary"]["source_evidence_only"] is True


def test_ageing_rejects_partial_location_scope_for_companywide_opening_balances(tmp_path, monkeypatch):
    password = "finance temporary password"
    users_file = tmp_path / "finance-users.json"
    users_file.write_text(json.dumps({"users": [{"id": 1, "username": "finance",
        "password_hash": hash_password(password), "roles": ["finance_reader"],
        "permissions": ["clone.read", "financial_report.read"], "allowed_locations": ["SHJ"]}]}),
        encoding="utf-8")
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_USERS_FILE", str(users_file))
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'ageing-scope.db'}")
    client = preview_client(tmp_path)
    login = client.post("/api/v1/auth/login", json={"username": "finance", "password": password})
    assert login.status_code == 200
    response = client.get("/api/v1/reports/ageing?ledger_kind=receivable")
    assert response.status_code == 403
    assert "Company-wide location scope" in response.json()["detail"]


def test_sales_return_form_binds_fields_without_named_form_properties():
    script = (Path(__file__).parents[1] / "src" / "klen_clone" / "static" / "erp.js").read_text(
        encoding="utf-8"
    )
    sales_return_block = script[script.index("async function salesReturns()"):
                                script.index("async function reviewAction")]
    assert "form.customer_code" not in sales_return_block
    assert "form.original_invoice_reference" not in sales_return_block
    assert "const field=name=>form.querySelector" in sales_return_block
    assert "await loadCustomers(customerField.value);await loadInvoices()" in sales_return_block
    html = (Path(__file__).parents[1] / "src" / "klen_clone" / "static" / "erp.html").read_text(
        encoding="utf-8"
    )
    assert "/static/erp.js?v=" in html


def test_sales_invoice_workspace_uses_stable_field_bindings_and_atomic_controls():
    script = (Path(__file__).parents[1] / "src" / "klen_clone" / "static" / "erp.js").read_text(
        encoding="utf-8"
    )
    block = script[script.index("async function draftWorkspace()"):
                   script.index("function inventoryLine()")]
    assert "form.document_type" not in block
    assert "form.party_code" not in block
    assert "const lineBody=document.querySelector('#draft-lines'),products=new Map(),field=name=>" in block
    assert "/api/v1/integrated-posting-batches/" in block
    assert "Sales-invoice posting atomically updates" in block
    assert "await draftWorkspace();document.querySelector('#workflow-result').textContent=message" in block


def test_payment_workspace_defines_its_workflow_request_helper():
    script = (Path(__file__).parents[1] / "src" / "klen_clone" / "static" / "payments.js").read_text(
        encoding="utf-8"
    )
    assert "async function paymentMutation" in script
    assert "await paymentMutation(`/api/v1/payments/" in script
    assert "await mutate(`/api/v1/payments/" not in script


def test_customer_statement_and_invoice_settlement_workspaces_are_wired():
    static = Path(__file__).parents[1] / "src" / "klen_clone" / "static"
    reports = (static / "financial-reports.js").read_text(encoding="utf-8")
    invoices = (static / "customer-invoices.js").read_text(encoding="utf-8")
    shell = (static / "erp.html").read_text(encoding="utf-8")
    router = (static / "erp.js").read_text(encoding="utf-8")
    assert "async function customerStatementsWorkspace" in reports
    assert "/reports/customer-statement" in reports
    assert "settlement_status" in invoices and "outstanding_amount" in invoices
    assert 'data-route="customer-statements"' in shell
    assert "customerStatementsWorkspace" in router


def test_credit_control_workspace_is_wired_with_controlled_workflows():
    static = Path(__file__).parents[1] / "src" / "klen_clone" / "static"
    credit = (static / "credit-control.js").read_text(encoding="utf-8")
    shell = (static / "erp.html").read_text(encoding="utf-8")
    router = (static / "erp.js").read_text(encoding="utf-8")
    assert "async function creditControlWorkspace" in credit
    assert "/api/v1/credit-control/limit-requests" in credit
    assert "/api/v1/credit-control/collections" in credit
    assert "/api/v1/credit-control/overrides" in credit
    assert "/api/v1/credit-control/dunning" in credit
    assert "one-time credit override" in credit
    assert "Dunning is sequential" in credit
    assert '<option value="${esc(x.party_code)}">${esc(x.party_name)}</option>' in credit
    assert 'data-route="credit-control"' in shell
    assert "/static/credit-control.js?v=" in shell
    assert "creditControlWorkspace" in router


def test_bank_and_cash_workspace_is_wired_with_reconciliation_controls():
    static = Path(__file__).parents[1] / "src" / "klen_clone" / "static"
    cash = (static / "cash-management.js").read_text(encoding="utf-8")
    shell = (static / "erp.html").read_text(encoding="utf-8")
    router = (static / "erp.js").read_text(encoding="utf-8")
    assert "async function cashManagementWorkspace" in cash
    assert "/api/v1/cash-management/accounts" in cash
    assert "/api/v1/cash-management/statements" in cash
    assert "Every stage" not in cash
    assert "duplicate checksum protected" in cash
    assert "cash-account-note" in cash
    assert "statement-decision-note" in cash
    assert "statement-exception-reason" in cash
    assert "prompt(" not in cash
    assert 'data-route="cash-management"' in shell
    assert "/static/cash-management.js?v=" in shell
    assert "cashManagementWorkspace" in router


def test_cash_account_api_requires_independent_approval(tmp_path, monkeypatch):
    maker_password = "cash maker temporary password"
    approver_password = "cash approver temporary password"
    users_file = tmp_path / "cash-users.json"
    users_file.write_text(json.dumps({"users": [
        {"id": 1, "username": "cash-maker", "password_hash": hash_password(maker_password),
         "roles": ["treasury"],
         "permissions": ["clone.read", "cash.account.prepare", "bank.statement.import", "bank.reconcile.prepare"],
         "allowed_locations": ["*"]},
        {"id": 2, "username": "cash-approver", "password_hash": hash_password(approver_password),
         "roles": ["finance_approver"],
         "permissions": ["clone.read", "cash.account.approve", "bank.reconcile.approve", "bank.reconcile.rehearse"],
         "allowed_locations": ["*"]},
    ]}), encoding="utf-8")
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_USERS_FILE", str(users_file))
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'cash-api.db'}")
    client = preview_client(tmp_path)
    maker = client.post("/api/v1/auth/login", json={
        "username": "cash-maker", "password": maker_password}).json()
    payload = {"account_code": "Bank - AED", "account_name": "Primary AED account",
        "account_type": "bank", "bank_name": "Test Bank", "identifier": "AE001234",
        "gl_account_code": "Bank - AED", "location_code": "MAIN",
        "reason": "Controlled account API test"}
    assert client.post("/api/v1/cash-management/accounts", json=payload).status_code == 403
    created = client.post("/api/v1/cash-management/accounts", json=payload,
        headers={"X-CSRF-Token": maker["csrf_token"]})
    assert created.status_code == 201 and created.json()["status"] == "pending"
    key = created.json()["account_key"]
    self_decision = client.post(f"/api/v1/cash-management/accounts/{key}/approve",
        json={"expected_revision": 1, "note": "Attempted self approval"},
        headers={"X-CSRF-Token": maker["csrf_token"]})
    assert self_decision.status_code == 403
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": maker["csrf_token"]})
    approver = client.post("/api/v1/auth/login", json={
        "username": "cash-approver", "password": approver_password}).json()
    approved = client.post(f"/api/v1/cash-management/accounts/{key}/approve",
        json={"expected_revision": 1, "note": "Independent approval completed"},
        headers={"X-CSRF-Token": approver["csrf_token"]})
    assert approved.status_code == 200 and approved.json()["status"] == "active"
    workspace = client.get("/api/v1/cash-management").json()
    assert workspace["controls"]["active_accounts"] == 1
    assert workspace["posting_enabled"] is False


def test_expense_and_petty_cash_workspace_is_wired():
    static = Path(__file__).parents[1] / "src" / "klen_clone" / "static"
    expense = (static / "expenses.js").read_text(encoding="utf-8")
    shell = (static / "erp.html").read_text(encoding="utf-8")
    router = (static / "erp.js").read_text(encoding="utf-8")
    assert "async function expensesWorkspace" in expense
    assert "/api/v1/expense-management/claims" in expense
    assert "/api/v1/expense-management/petty-cash" in expense
    assert "expense-decision-note" in expense
    assert "petty-decision-note" in expense
    assert "Verified non-posting rehearsal" in expense
    assert "prompt(" not in expense
    assert 'data-route="expenses"' in shell
    assert "/static/expenses.js?v=" in shell
    assert "expensesWorkspace" in router


def test_expense_api_requires_independent_approval_and_never_posts(tmp_path, monkeypatch):
    maker_password, approver_password = "expense maker password", "expense approver password"
    users_file = tmp_path / "expense-users.json"
    users_file.write_text(json.dumps({"users": [
        {"id": 1, "username": "expense-maker", "password_hash": hash_password(maker_password),
         "roles": ["operations_administrator"], "permissions": ["clone.read"],
         "allowed_locations": ["*"]},
        {"id": 2, "username": "expense-approver", "password_hash": hash_password(approver_password),
         "roles": ["independent_approver"], "permissions": ["clone.read"],
         "allowed_locations": ["*"]},
    ]}), encoding="utf-8")
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_USERS_FILE", str(users_file))
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'expense-api.db'}")
    client = preview_client(tmp_path)
    with client.app.state.operational_sessions() as session:
        account = create_cash_account(session, account_code="Bank - AED", account_name="API test bank",
            account_type="bank", bank_name="Test Bank", identifier="AE001234",
            gl_account_code="Bank - AED", location_code="MAIN", reason="Expense API testing",
            actor="bank-maker")
        decide_cash_account(session, account, action="approve", expected_revision=1,
                            actor="bank-approver", note="Independent bank approval")
        session.add(OperationalFiscalPeriod(period_key="2026-09", starts_on=date(2026, 9, 1),
            ends_on=date(2026, 9, 30), status="open", rehearsal_enabled=True,
            approval_reference="Expense UAT", configured_by="controller"))
        session.commit()
        account_key = account.account_key
    maker = client.post("/api/v1/auth/login", json={
        "username": "expense-maker", "password": maker_password}).json()
    payload = {"claimant_type": "supplier", "claimant_reference": "SUP-1",
        "claimant_name": "Fuel Vendor", "expense_date": "2026-09-21",
        "location_code": "MAIN", "cost_center": "DELIVERY", "category_code": "fuel",
        "description": "Controlled expense API test", "receipt_reference": "RCPT-API-1",
        "tax_invoice_no": "TAX-API-1", "supplier_trn": "123456789012345",
        "vat_rate": "5", "net_amount": "100", "vat_amount": "5",
        "settlement_method": "direct_payment", "payment_account_key": account_key}
    created = client.post("/api/v1/expense-management/claims", json=payload,
        headers={"X-CSRF-Token": maker["csrf_token"]})
    assert created.status_code == 201 and created.json()["status"] == "draft", created.text
    claim_key = created.json()["claim_key"]
    submitted = client.post(f"/api/v1/expense-management/claims/{claim_key}/actions/submit",
        json={"expected_revision": 1}, headers={"X-CSRF-Token": maker["csrf_token"]})
    assert submitted.status_code == 200 and submitted.json()["status"] == "submitted"
    assert client.post(f"/api/v1/expense-management/claims/{claim_key}/actions/approve",
        json={"expected_revision": 2, "note": "Attempted self approval"},
        headers={"X-CSRF-Token": maker["csrf_token"]}).status_code == 403
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": maker["csrf_token"]})
    approver = client.post("/api/v1/auth/login", json={
        "username": "expense-approver", "password": approver_password}).json()
    approved = client.post(f"/api/v1/expense-management/claims/{claim_key}/actions/approve",
        json={"expected_revision": 2, "note": "Independent expense approval"},
        headers={"X-CSRF-Token": approver["csrf_token"]})
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    rehearsal = client.post(f"/api/v1/expense-management/claims/{claim_key}/rehearsal",
        headers={"X-CSRF-Token": approver["csrf_token"]})
    assert rehearsal.status_code == 200
    assert rehearsal.json()["posting_enabled"] is False
    assert rehearsal.json()["posting_performed"] is False


def test_credit_limit_request_is_an_authorized_operational_mutation(tmp_path, monkeypatch):
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_ADMIN_USERNAME", "asas-admin")
    monkeypatch.setenv("ASAS_ADMIN_PASSWORD_HASH", hash_password("temporary strong password"))
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'credit-api.db'}")
    client = preview_client(tmp_path)
    login = client.post("/api/v1/auth/login", json={
        "username": "asas-admin", "password": "temporary strong password",
    }).json()
    response = client.post("/api/v1/credit-control/limit-requests", json={
        "party_code": "CO-001", "proposed_limit": "500.00",
        "proposed_terms_days": 30, "reason": "Controlled API test limit",
    }, headers={"X-CSRF-Token": login["csrf_token"]})
    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert response.json()["proposed_limit"] == 500.0


def test_fixed_asset_api_uses_deployed_independent_approver_role(tmp_path, monkeypatch):
    maker_password, approver_password = "asset maker password", "asset approver password"
    users_file = tmp_path / "asset-users.json"
    users_file.write_text(json.dumps({"users": [
        {"id": 1, "username": "asset-maker", "password_hash": hash_password(maker_password),
         "roles": ["operations_administrator"], "permissions": ["clone.read"],
         "allowed_locations": ["*"]},
        {"id": 2, "username": "asset-approver", "password_hash": hash_password(approver_password),
         "roles": ["independent_approver"], "permissions": ["clone.read"],
         "allowed_locations": ["*"]},
    ]}), encoding="utf-8")
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_USERS_FILE", str(users_file))
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'asset-api.db'}")
    client = preview_client(tmp_path)
    with client.app.state.operational_sessions() as session:
        session.add(OperationalFiscalPeriod(period_key="2026-09", starts_on=date(2026, 9, 1),
            ends_on=date(2026, 9, 30), status="open", rehearsal_enabled=True,
            approval_reference="Asset API UAT", configured_by="controller"))
        session.commit()
    maker = client.post("/api/v1/auth/login", json={
        "username": "asset-maker", "password": maker_password}).json()
    created = client.post("/api/v1/fixed-assets", json={
        "asset_name": "Testing API laptop", "category_code": "computer_equipment",
        "supplier_reference": "SUP-TEST", "acquisition_reference": "UAT-ASSET-API-1",
        "acquisition_date": "2026-09-21", "available_for_use_date": "2026-09-21",
        "location_code": "MAIN", "cost_center": "ADMIN", "custodian": "Test User",
        "serial_number": "UAT-SERIAL", "useful_life_months": 36,
        "cost_amount": "3600", "residual_value": "0",
    }, headers={"X-CSRF-Token": maker["csrf_token"]})
    assert created.status_code == 201, created.text
    asset_key = created.json()["asset_key"]
    submitted = client.post(f"/api/v1/fixed-assets/{asset_key}/actions/submit",
        json={"expected_revision": 1}, headers={"X-CSRF-Token": maker["csrf_token"]})
    assert submitted.status_code == 200 and submitted.json()["status"] == "submitted"
    assert client.post(f"/api/v1/fixed-assets/{asset_key}/actions/approve",
        json={"expected_revision": 2, "note": "Attempted self approval"},
        headers={"X-CSRF-Token": maker["csrf_token"]}).status_code == 403
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": maker["csrf_token"]})
    approver = client.post("/api/v1/auth/login", json={
        "username": "asset-approver", "password": approver_password}).json()
    approved = client.post(f"/api/v1/fixed-assets/{asset_key}/actions/approve",
        json={"expected_revision": 2, "note": "Independent capitalization approval"},
        headers={"X-CSRF-Token": approver["csrf_token"]})
    assert approved.status_code == 200 and approved.json()["status"] == "active"
    assert len(approved.json()["schedule"]) == 36
    rehearsal = client.post(f"/api/v1/fixed-assets/{asset_key}/rehearsal",
        json={"stage": "capitalization", "as_of_date": "2026-09-21"},
        headers={"X-CSRF-Token": approver["csrf_token"]})
    assert rehearsal.status_code == 200
    assert rehearsal.json()["posting_enabled"] is False
    assert rehearsal.json()["posting_performed"] is False


def test_fixed_asset_workspace_assets_are_wired_into_shell():
    static_root = Path(__file__).parents[1] / "src" / "klen_clone" / "static"
    asset = (static_root / "fixed-assets.js").read_text(encoding="utf-8")
    shell = (static_root / "erp.html").read_text(encoding="utf-8")
    router = (static_root / "erp.js").read_text(encoding="utf-8")
    assert "/api/v1/fixed-assets" in asset
    assert "asset-decision-note" in asset and "asset-disposal-note" in asset
    assert "can=p=>currentPermissions.has(p)" in asset and "const mutate=" in asset
    assert "posting disabled" in asset
    assert "prompt(" not in asset
    assert 'data-route="fixed-assets"' in shell
    assert "/static/fixed-assets.js?v=" in shell
    assert "fixedAssetsWorkspace" in router


def test_vat_control_api_uses_independent_approval_and_non_filing_rehearsal(tmp_path, monkeypatch):
    maker_password, approver_password = "vat maker password", "vat approver password"
    users_file = tmp_path / "vat-users.json"
    users_file.write_text(json.dumps({"users": [
        {"id": 1, "username": "vat-maker", "password_hash": hash_password(maker_password),
         "roles": ["operations_administrator"], "permissions": ["clone.read"],
         "allowed_locations": ["*"]},
        {"id": 2, "username": "vat-approver", "password_hash": hash_password(approver_password),
         "roles": ["independent_approver"], "permissions": ["clone.read"],
         "allowed_locations": ["*"]},
    ]}), encoding="utf-8")
    monkeypatch.setenv("ASAS_AUTH_ENABLED", "true")
    monkeypatch.setenv("ASAS_USERS_FILE", str(users_file))
    monkeypatch.setenv("ASAS_OPERATIONAL_DATABASE_URL", f"sqlite:///{tmp_path / 'vat-api.db'}")
    client = preview_client(tmp_path)
    maker = client.post("/api/v1/auth/login", json={
        "username": "vat-maker", "password": maker_password}).json()
    created = client.post("/api/v1/vat-control/periods", json={
        "period_code": "VAT-UAT-2026-09", "starts_on": "2026-09-01",
        "ends_on": "2026-09-30", "due_on": "2026-10-28",
        "company_trn": "100000000000003",
    }, headers={"X-CSRF-Token": maker["csrf_token"]})
    assert created.status_code == 201, created.text
    period_key = created.json()["period_key"]
    adjustment = client.post(f"/api/v1/vat-control/periods/{period_key}/adjustments", json={
        "adjustment_type": "reverse_charge", "adjustment_date": "2026-09-21",
        "evidence_reference": "UAT-RC-API-1", "reason": "Controlled API reverse charge test",
        "taxable_amount": "100.00", "vat_amount": "5.00", "recovery_percent": "100",
    }, headers={"X-CSRF-Token": maker["csrf_token"]})
    assert adjustment.status_code == 201, adjustment.text
    adjustment_key = adjustment.json()["adjustment_key"]
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": maker["csrf_token"]})
    approver = client.post("/api/v1/auth/login", json={
        "username": "vat-approver", "password": approver_password}).json()
    approved_adjustment = client.post(
        f"/api/v1/vat-control/adjustments/{adjustment_key}/approve",
        json={"expected_revision": 1, "note": "Independent reverse charge approval"},
        headers={"X-CSRF-Token": approver["csrf_token"]})
    assert approved_adjustment.status_code == 200
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": approver["csrf_token"]})
    maker = client.post("/api/v1/auth/login", json={
        "username": "vat-maker", "password": maker_password}).json()
    submitted = client.post(f"/api/v1/vat-control/periods/{period_key}/actions/submit",
        json={"expected_revision": 1}, headers={"X-CSRF-Token": maker["csrf_token"]})
    assert submitted.status_code == 200 and submitted.json()["status"] == "submitted"
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": maker["csrf_token"]})
    approver = client.post("/api/v1/auth/login", json={
        "username": "vat-approver", "password": approver_password}).json()
    approved = client.post(f"/api/v1/vat-control/periods/{period_key}/actions/approve",
        json={"expected_revision": 2, "note": "Independent VAT return approval"},
        headers={"X-CSRF-Token": approver["csrf_token"]})
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    rehearsal = client.post(f"/api/v1/vat-control/periods/{period_key}/rehearsal",
        headers={"X-CSRF-Token": approver["csrf_token"]})
    assert rehearsal.status_code == 200
    assert rehearsal.json()["posting_performed"] is False
    assert rehearsal.json()["filing_performed"] is False


def test_vat_control_workspace_assets_are_wired_into_shell():
    static_root = Path(__file__).parents[1] / "src" / "klen_clone" / "static"
    asset = (static_root / "vat-control.js").read_text(encoding="utf-8")
    shell = (static_root / "erp.html").read_text(encoding="utf-8")
    router = (static_root / "erp.js").read_text(encoding="utf-8")
    assert "/api/v1/vat-control" in asset
    assert "vat-period-note" in asset and "vat-adjustment-note" in asset
    assert "can=p=>currentPermissions.has(p)" in asset and "const mutate=" in asset
    assert "No filing" in asset and "prompt(" not in asset
    assert 'data-route="vat-control"' in shell
    assert "/static/vat-control.js?v=" in shell
    assert "vatControlWorkspace" in router


def test_period_close_workspace_assets_are_wired_into_shell():
    static_root = Path(__file__).parents[1] / "src" / "klen_clone" / "static"
    asset = (static_root / "period-close.js").read_text(encoding="utf-8")
    shell = (static_root / "erp.html").read_text(encoding="utf-8")
    router = (static_root / "erp.js").read_text(encoding="utf-8")
    assert "/api/v1/period-close" in asset
    assert "close-note" in asset and "close-adj-note" in asset
    assert "const mutate=" in asset and "prompt(" not in asset
    assert "No permanent posting" in asset
    assert 'data-route="period-close"' in shell
    assert "/static/period-close.js?v=" in shell
    assert "periodCloseWorkspace" in router


def test_close_reporting_workspace_and_exports_are_wired_into_shell():
    static_root = Path(__file__).parents[1] / "src" / "klen_clone" / "static"
    asset = (static_root / "close-reporting.js").read_text(encoding="utf-8")
    shell = (static_root / "erp.html").read_text(encoding="utf-8")
    router = (static_root / "erp.js").read_text(encoding="utf-8")
    assert "/api/v1/close-reporting" in asset
    assert "Download Excel" in asset and "Download PDF" in asset
    assert "report-note" in asset and "const mutate=" in asset
    assert "prompt(" not in asset
    assert 'data-route="financial-statements"' in shell
    assert "/static/close-reporting.js?v=" in shell
    assert "closeReportingWorkspace" in router


def test_audit_compliance_workspace_and_exports_are_wired_into_shell():
    static_root = Path(__file__).parents[1] / "src" / "klen_clone" / "static"
    asset = (static_root / "audit-compliance.js").read_text(encoding="utf-8")
    shell = (static_root / "erp.html").read_text(encoding="utf-8")
    router = (static_root / "erp.js").read_text(encoding="utf-8")
    assert "/api/v1/audit-compliance" in asset
    assert "Download audit workbook" in asset and "Download signed manifest" in asset
    assert "audit-note" in asset and "const mutate=" in asset
    assert "prompt(" not in asset
    assert 'data-route="audit-compliance"' in shell
    assert "/static/audit-compliance.js?v=" in shell
    assert "auditComplianceWorkspace" in router


def test_cutover_rehearsal_workspace_and_exports_are_wired_into_shell():
    static_root = Path(__file__).parents[1] / "src" / "klen_clone" / "static"
    asset = (static_root / "cutover-rehearsal.js").read_text(encoding="utf-8")
    shell = (static_root / "erp.html").read_text(encoding="utf-8")
    router = (static_root / "erp.js").read_text(encoding="utf-8")
    assert "/api/v1/cutover-rehearsal" in asset
    assert "Download reset plan" in asset and "Download manifest" in asset
    assert "Preview only · no purge · no import" in asset
    assert 'data-route="cutover-rehearsal"' in shell
    assert "/static/cutover-rehearsal.js?v=" in shell
    assert "cutoverRehearsalWorkspace" in router
