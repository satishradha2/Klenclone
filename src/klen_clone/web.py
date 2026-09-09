from __future__ import annotations

import os
import hashlib
from io import BytesIO
import json
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker

from .db import make_engine
from .auth import UatSessionStore, verify_password, verify_token
from .config import RuntimeSettings
from .export_packages import EXPORT_MODULES, build_review_package
from .module_views import MODULES, build_module_workspace
from .review_store import UatReviewStore
from .models import (
    ErpApprovalPolicy, ErpApprovalRoleBinding, ErpApprovalStep, ErpAuditEvent, ErpAuthPrincipal,
    ErpCoverageGate, ErpFinancialActivationGate,
    ErpInventoryMovement, ErpJournalBlueprint, ErpLocation, ErpMigrationExceptionQueue,
    ErpOpeningBalanceQueue, ErpOrganization, ErpResidualWorkflowGate, ErpSecurityActivationGate,
    ErpRuntimeActivationGate, ErpRuntimeModule, ErpSecurityLocationScope,
    ErpSecurityPermission, ErpSecurityRole, ErpSecurityRolePermission, ErpSecurityUserRole,
    ErpSegregationRule,
    ErpSourceCoverage, ErpTransactionDocument, ErpTransactionLine, ErpTransactionPayment,
    ErpParty, ErpProductMaster, ErpProductUom,
    ErpWorkflowDefinition,
    RawFileManifest, RawRecord, SourceSnapshot,
)

DEFAULT_SNAPSHOT = "bizmodo-2026-09-08-browser"
STATIC_DIR = Path(__file__).with_name("static")
UAT_COOKIE = "klen_uat_session"


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=500)


class ResetRequest(BaseModel):
    username: str = Field(min_length=1, max_length=200)


class DiscrepancyProposalRequest(BaseModel):
    exception_id: int = Field(gt=0)
    resolution_code: str = Field(min_length=3, max_length=80)
    proposed_value: dict = Field(default_factory=dict)
    rationale: str = Field(min_length=10, max_length=2000)


class BusinessReviewDecisionRequest(BaseModel):
    package_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    decision_code: str = Field(min_length=3, max_length=80)
    rationale: str = Field(min_length=10, max_length=2000)


PROPOSAL_CODES = {
    "link_document", "link_product", "assign_location", "approve_uom_mapping",
    "approve_opening_adjustment", "match_payment", "approve_account_mapping",
    "preserve_duplicate_with_source_key", "request_source_evidence",
    "no_change_retain_block", "other_requires_review",
}
BUSINESS_REVIEW_DECISION_CODES = {
    "accepted_for_uat", "conditionally_accepted_for_uat",
    "rejected_for_uat", "evidence_requested",
}
SENSITIVE_EVIDENCE_FRAGMENTS = ("password", "token", "secret", "email", "mobile", "phone", "address", "payload")


def create_app(database_url: str | None = None, snapshot_name: str | None = None) -> FastAPI:
    engine = make_engine(database_url)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    selected_snapshot = snapshot_name or os.getenv("KLEN_SNAPSHOT", DEFAULT_SNAPSHOT)
    settings = RuntimeSettings.from_env(str(engine.url), selected_snapshot)
    settings.validate()
    app = FastAPI(
        title="Klen ERP Migration Control Center",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        description="Read-only migration assurance interface. No operational posting endpoints are exposed.",
    )
    app.state.engine = engine
    app.state.snapshot_name = selected_snapshot
    app.state.settings = settings
    app.state.uat_sessions = UatSessionStore()
    app.state.uat_review_store = UatReviewStore(settings.uat_review_database) if settings.uat_review_database else None
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def session_dependency():
        with sessions() as session:
            yield session

    def snapshot_dependency(session: Session = Depends(session_dependency)) -> SourceSnapshot:
        snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == selected_snapshot))
        if not snapshot:
            raise HTTPException(status_code=404, detail="Configured migration snapshot is not available")
        return snapshot

    def require_permission(permission_code: str):
        def dependency(request: Request, authorization: str | None = Header(None),
                       session: Session = Depends(session_dependency)):
            if not settings.auth_enabled:
                raise HTTPException(status_code=503, detail="Target authentication is not activated")
            principal_id = None
            if settings.uat_auth_enabled:
                uat_session = app.state.uat_sessions.get(request.cookies.get(UAT_COOKIE))
                if uat_session:
                    principal_id = uat_session.principal_id
            if principal_id is None and authorization and authorization.startswith("Bearer "):
                try:
                    payload = verify_token(authorization.removeprefix("Bearer "), settings.auth_secret or "")
                    principal_id = payload["sub"]
                except ValueError as exc:
                    raise HTTPException(status_code=401, detail=str(exc)) from exc
            if principal_id is None:
                raise HTTPException(status_code=401, detail="Authentication required")
            principal = session.get(ErpAuthPrincipal, principal_id)
            if not principal or not principal.authentication_enabled or principal.auth_status != "active":
                raise HTTPException(status_code=403, detail="Principal is not active")
            allowed = session.scalar(select(func.count(ErpSecurityRolePermission.id)).join(
                ErpSecurityPermission, ErpSecurityRolePermission.permission_id == ErpSecurityPermission.id).join(
                ErpSecurityUserRole, ErpSecurityRolePermission.role_id == ErpSecurityUserRole.role_id).where(
                ErpSecurityUserRole.user_id == principal.security_user_id,
                ErpSecurityUserRole.assignment_enabled.is_(True),
                ErpSecurityRolePermission.target_granted.is_(True),
                ErpSecurityPermission.grant_enabled.is_(True),
                ErpSecurityPermission.permission_code == permission_code)) or 0
            if not allowed:
                raise HTTPException(status_code=403, detail="Required permission is not granted")
            location_ids = list(session.scalars(select(ErpSecurityLocationScope.location_id).where(
                ErpSecurityLocationScope.user_id == principal.security_user_id,
                ErpSecurityLocationScope.access_enabled.is_(True),
                ErpSecurityLocationScope.location_id.is_not(None))))
            if not location_ids:
                raise HTTPException(status_code=403, detail="No active location scope")
            return {"principal": principal, "location_ids": location_ids}
        return dependency

    @app.middleware("http")
    async def read_only_and_security_headers(request: Request, call_next):
        uat_mutations = {"/api/v1/auth/login", "/api/v1/auth/logout", "/api/v1/auth/reset-request",
                         "/api/v1/uat/discrepancy-proposals"}
        permitted_uat_post = settings.uat_auth_enabled and request.method == "POST" and (
            request.url.path in uat_mutations or
            request.url.path.startswith("/api/v1/uat/business-reviews/"))
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not permitted_uat_post:
            return JSONResponse(status_code=405, content={
                "detail": "Read-only migration control center: mutating methods are disabled"
            }, headers={"Allow": "GET, HEAD, OPTIONS"})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'"
        return response

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(STATIC_DIR / "index.html")

    def uat_principal_payload(principal: ErpAuthPrincipal, session: Session) -> dict:
        roles = list(session.scalars(select(ErpSecurityRole.role_code).join(
            ErpSecurityUserRole, ErpSecurityUserRole.role_id == ErpSecurityRole.id).where(
            ErpSecurityUserRole.user_id == principal.security_user_id,
            ErpSecurityUserRole.assignment_enabled.is_(True))).all())
        permissions = list(session.scalars(select(ErpSecurityPermission.permission_code).join(
            ErpSecurityRolePermission,
            ErpSecurityRolePermission.permission_id == ErpSecurityPermission.id).join(
            ErpSecurityUserRole, ErpSecurityUserRole.role_id == ErpSecurityRolePermission.role_id).where(
            ErpSecurityUserRole.user_id == principal.security_user_id,
            ErpSecurityUserRole.assignment_enabled.is_(True),
            ErpSecurityRolePermission.target_granted.is_(True),
            ErpSecurityPermission.grant_enabled.is_(True)).distinct().order_by(
            ErpSecurityPermission.permission_code)).all())
        locations = session.execute(select(ErpLocation.id, ErpLocation.code, ErpLocation.name).join(
            ErpSecurityLocationScope, ErpSecurityLocationScope.location_id == ErpLocation.id).where(
            ErpSecurityLocationScope.user_id == principal.security_user_id,
            ErpSecurityLocationScope.access_enabled.is_(True)).order_by(ErpLocation.code)).all()
        return {"principal_id": principal.id, "login_name": principal.login_name,
                "roles": roles, "permissions": permissions,
                "locations": [dict(row._mapping) for row in locations],
                "synthetic_uat": True, "posting_enabled": False}

    @app.post("/api/v1/auth/login")
    def uat_login(payload: LoginRequest, request: Request,
                  session: Session = Depends(session_dependency)):
        if not settings.uat_auth_enabled:
            raise HTTPException(status_code=404, detail="UAT login is not enabled")
        attempt_key = f"{request.client.host if request.client else 'unknown'}:{payload.username.casefold()}"
        if not app.state.uat_sessions.allow_attempt(attempt_key):
            raise HTTPException(status_code=429, detail="Too many sign-in attempts; try again later")
        principal = session.scalar(select(ErpAuthPrincipal).where(
            ErpAuthPrincipal.snapshot_id == session.scalar(select(SourceSnapshot.id).where(
                SourceSnapshot.name == selected_snapshot)),
            func.lower(ErpAuthPrincipal.login_name) == payload.username.strip().casefold()))
        is_synthetic = bool(principal and isinstance(principal.evidence, dict)
                            and principal.evidence.get("synthetic_uat") is True)
        if not principal or not is_synthetic or not principal.password_hash or not verify_password(
                payload.password, principal.password_hash):
            raise HTTPException(status_code=401, detail="Invalid username or password")
        if not principal.authentication_enabled or principal.auth_status != "active":
            raise HTTPException(status_code=403, detail="Synthetic UAT principal is not active")
        if principal.mfa_enrolled:
            raise HTTPException(status_code=403, detail="MFA challenge is required but not configured for this UAT principal")
        app.state.uat_sessions.clear_attempts(attempt_key)
        token, uat_session = app.state.uat_sessions.create(principal.id, settings.token_ttl_seconds)
        response = JSONResponse({"authenticated": True,
                                 "expires_at": uat_session.expires_at,
                                 "csrf_token": uat_session.csrf_token,
                                 "principal": uat_principal_payload(principal, session)})
        response.set_cookie(UAT_COOKIE, token, max_age=settings.token_ttl_seconds, httponly=True,
                            secure=settings.cookie_secure, samesite="strict", path="/")
        return response

    @app.get("/api/v1/auth/session")
    def uat_session(request: Request, session: Session = Depends(session_dependency)):
        if not settings.uat_auth_enabled:
            return {"authenticated": False, "uat_enabled": False}
        active = app.state.uat_sessions.get(request.cookies.get(UAT_COOKIE))
        principal = session.get(ErpAuthPrincipal, active.principal_id) if active else None
        if not principal or not principal.authentication_enabled or principal.auth_status != "active":
            return {"authenticated": False, "uat_enabled": True}
        return {"authenticated": True, "uat_enabled": True, "expires_at": active.expires_at,
                "csrf_token": active.csrf_token, "principal": uat_principal_payload(principal, session)}

    @app.post("/api/v1/auth/logout")
    def uat_logout(request: Request):
        if not settings.uat_auth_enabled:
            raise HTTPException(status_code=404, detail="UAT login is not enabled")
        token = request.cookies.get(UAT_COOKIE)
        active = app.state.uat_sessions.get(token)
        if active and request.headers.get("x-csrf-token") != active.csrf_token:
            raise HTTPException(status_code=403, detail="CSRF validation failed")
        app.state.uat_sessions.revoke(token)
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(UAT_COOKIE, path="/", secure=settings.cookie_secure, samesite="strict")
        return response

    @app.post("/api/v1/auth/reset-request")
    def uat_reset_request(payload: ResetRequest):
        if not settings.uat_auth_enabled:
            raise HTTPException(status_code=404, detail="UAT login is not enabled")
        return {"accepted": True, "delivery_performed": False,
                "message": "Synthetic UAT reset request recorded as a dry run; no password or data was changed."}

    @app.get("/api/v1/health")
    def health(session: Session = Depends(session_dependency)):
        session.execute(text("SELECT 1"))
        snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == selected_snapshot))
        return {"status": "ok", "mode": "migration_read_only", "database": "reachable",
                "snapshot": selected_snapshot, "snapshot_found": snapshot is not None,
                "authentication_enabled": settings.auth_enabled, "uat_authentication_enabled": settings.uat_auth_enabled,
                "posting_enabled": False}

    @app.get("/api/v1/summary")
    def summary(snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency)):
        count = lambda model: session.scalar(select(func.count(model.id)).where(model.snapshot_id == snapshot.id)) or 0
        coverage_status = dict(session.execute(select(ErpSourceCoverage.coverage_status, func.count()).where(
            ErpSourceCoverage.snapshot_id == snapshot.id).group_by(ErpSourceCoverage.coverage_status)).all())
        organization_name = session.scalar(select(ErpOrganization.legal_name).where(
            ErpOrganization.snapshot_id == snapshot.id).order_by(ErpOrganization.id).limit(1))
        return {"snapshot": snapshot.name, "source_system": snapshot.source_system, "atomic": snapshot.is_atomic,
                "organization_name": organization_name or "ERP Migration Assurance",
                "mode": "migration_read_only", "raw_records": session.scalar(select(func.count(RawRecord.id)).join(
                    RawFileManifest).where(RawFileManifest.snapshot_id == snapshot.id)) or 0,
                "coverage_records": count(ErpSourceCoverage), "coverage_status": coverage_status,
                "documents": count(ErpTransactionDocument), "inventory_movements": count(ErpInventoryMovement),
                "journals": count(ErpJournalBlueprint), "opening_controls": count(ErpOpeningBalanceQueue),
                "exceptions": count(ErpMigrationExceptionQueue),
                "authentication_enabled": settings.auth_enabled, "posting_enabled": False}

    @app.get("/api/v1/coverage")
    def coverage(snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency)):
        rows = session.execute(select(
            ErpCoverageGate.source_entity, ErpCoverageGate.source_row_count,
            ErpCoverageGate.structured_count, ErpCoverageGate.residual_count,
            ErpCoverageGate.presentation_count, ErpCoverageGate.gate_status,
        ).where(ErpCoverageGate.snapshot_id == snapshot.id).order_by(ErpCoverageGate.source_entity)).all()
        return {"items": [dict(row._mapping) for row in rows], "activation_enabled": False}

    @app.get("/api/v1/gates")
    def gates(snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency)):
        groups = []
        for domain, model in (("coverage", ErpCoverageGate), ("financial", ErpFinancialActivationGate),
                              ("security", ErpSecurityActivationGate), ("workflow", ErpResidualWorkflowGate),
                              ("runtime", ErpRuntimeActivationGate)):
            code_col = model.source_entity if model is ErpCoverageGate else model.gate_code
            name_col = model.source_entity if model is ErpCoverageGate else model.gate_name
            rows = session.execute(select(code_col, name_col, model.issue_count if model is not ErpCoverageGate else model.residual_count,
                                          model.gate_status).where(model.snapshot_id == snapshot.id).order_by(code_col)).all()
            groups.extend({"domain": domain, "code": row[0], "name": row[1],
                           "issues": row[2], "status": row[3], "activation_enabled": False} for row in rows)
        return {"items": groups, "active": 0}

    @app.get("/api/v1/exceptions")
    def exceptions(snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency)):
        rows = session.execute(select(
            ErpMigrationExceptionQueue.exception_code, ErpMigrationExceptionQueue.severity,
            ErpMigrationExceptionQueue.queue_status, func.count().label("count"),
        ).where(ErpMigrationExceptionQueue.snapshot_id == snapshot.id).group_by(
            ErpMigrationExceptionQueue.exception_code, ErpMigrationExceptionQueue.severity,
            ErpMigrationExceptionQueue.queue_status).order_by(func.count().desc())).all()
        return {"items": [dict(row._mapping) for row in rows],
                "note": "Aggregated only; confidential row payloads are not exposed without authentication."}

    @app.get("/api/v1/accounting")
    def accounting(snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency)):
        journals = dict(session.execute(select(ErpJournalBlueprint.migration_status, func.count()).where(
            ErpJournalBlueprint.snapshot_id == snapshot.id).group_by(ErpJournalBlueprint.migration_status)).all())
        openings = dict(session.execute(select(ErpOpeningBalanceQueue.queue_status, func.count()).where(
            ErpOpeningBalanceQueue.snapshot_id == snapshot.id).group_by(ErpOpeningBalanceQueue.queue_status)).all())
        return {"journal_status": journals, "opening_status": openings,
                "posting_enabled": False, "activation_enabled": False}

    @app.get("/api/v1/audit-events")
    def audit_events(limit: int = Query(25, ge=1, le=100), snapshot: SourceSnapshot = Depends(snapshot_dependency),
                     session: Session = Depends(session_dependency)):
        rows = session.execute(select(ErpAuditEvent.id, ErpAuditEvent.event_key, ErpAuditEvent.event_type,
                                      ErpAuditEvent.actor_type, ErpAuditEvent.occurred_at).where(
            ErpAuditEvent.snapshot_id == snapshot.id).order_by(ErpAuditEvent.id.desc()).limit(limit)).all()
        return {"items": [dict(row._mapping) for row in rows],
                "details_redacted": True, "append_only": True}

    @app.get("/api/v1/runtime")
    def runtime(snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency)):
        modules = session.execute(select(ErpRuntimeModule.module_code, ErpRuntimeModule.module_name,
                                         ErpRuntimeModule.module_status).where(
            ErpRuntimeModule.snapshot_id == snapshot.id).order_by(ErpRuntimeModule.module_code)).all()
        principals = session.scalar(select(func.count(ErpAuthPrincipal.id)).where(
            ErpAuthPrincipal.snapshot_id == snapshot.id)) or 0
        active = session.scalar(select(func.count(ErpAuthPrincipal.id)).where(
            ErpAuthPrincipal.snapshot_id == snapshot.id, ErpAuthPrincipal.authentication_enabled.is_(True))) or 0
        return {"modules": [dict(row._mapping) for row in modules], "auth_principals": principals,
                "active_principals": active, "authentication_enabled": settings.auth_enabled,
                "production_mode": settings.production_mode, "posting_enabled": False}

    @app.get("/api/v1/modules/{module_code}")
    def module_workspace(module_code: str, snapshot: SourceSnapshot = Depends(snapshot_dependency),
                         session: Session = Depends(session_dependency)):
        if module_code not in MODULES:
            raise HTTPException(status_code=404, detail="Unknown ERP module")
        return build_module_workspace(session, snapshot, module_code)

    @app.get("/api/v1/secure/parties")
    def secure_parties(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                       q: str | None = Query(None, max_length=100),
                       context=Depends(require_permission("customer.view")),
                       snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency)):
        filters = [ErpParty.snapshot_id == snapshot.id, ErpParty.party_kind.in_(["customer", "both"])]
        if q:
            pattern = f"%{q.strip()}%"
            filters.append(or_(ErpParty.party_code.ilike(pattern),
                               ErpParty.legal_or_business_name.ilike(pattern)))
        total = session.scalar(select(func.count(ErpParty.id)).where(*filters)) or 0
        rows = session.execute(select(ErpParty.id, ErpParty.party_code, ErpParty.party_kind,
                                      ErpParty.legal_or_business_name, ErpParty.master_status).where(
            *filters).order_by(ErpParty.id).offset(offset).limit(limit)).all()
        return {"items": [dict(row._mapping) for row in rows], "total": total,
                "limit": limit, "offset": offset, "sensitive_fields_redacted": True}

    @app.get("/api/v1/secure/suppliers")
    def secure_suppliers(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                         q: str | None = Query(None, max_length=100),
                         context=Depends(require_permission("supplier.view")),
                         snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency)):
        filters = [ErpParty.snapshot_id == snapshot.id, ErpParty.party_kind.in_(["supplier", "both"])]
        if q:
            pattern = f"%{q.strip()}%"
            filters.append(or_(ErpParty.party_code.ilike(pattern),
                               ErpParty.legal_or_business_name.ilike(pattern)))
        total = session.scalar(select(func.count(ErpParty.id)).where(*filters)) or 0
        rows = session.execute(select(ErpParty.id, ErpParty.party_code, ErpParty.party_kind,
                                      ErpParty.legal_or_business_name, ErpParty.master_status).where(
            *filters).order_by(ErpParty.id).offset(offset).limit(limit)).all()
        return {"items": [dict(row._mapping) for row in rows], "total": total,
                "limit": limit, "offset": offset, "sensitive_fields_redacted": True}

    @app.get("/api/v1/secure/products")
    def secure_products(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                        q: str | None = Query(None, max_length=100),
                        context=Depends(require_permission("product.view")),
                        snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency)):
        filters = [ErpProductMaster.snapshot_id == snapshot.id]
        if q:
            pattern = f"%{q.strip()}%"
            filters.append(or_(ErpProductMaster.sku.ilike(pattern), ErpProductMaster.name.ilike(pattern)))
        uom_count = select(func.count(ErpProductUom.id)).where(
            ErpProductUom.product_id == ErpProductMaster.id).correlate(ErpProductMaster).scalar_subquery()
        total = session.scalar(select(func.count(ErpProductMaster.id)).where(*filters)) or 0
        rows = session.execute(select(ErpProductMaster.id, ErpProductMaster.sku, ErpProductMaster.name,
                                      ErpProductMaster.category_name, ErpProductMaster.brand_name,
                                      ErpProductMaster.master_status, uom_count.label("uom_profiles")).where(
            *filters).order_by(ErpProductMaster.id).offset(offset).limit(limit)).all()
        return {"items": [dict(row._mapping) for row in rows], "total": total,
                "limit": limit, "offset": offset}

    @app.get("/api/v1/secure/documents")
    def secure_documents(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                         q: str | None = Query(None, max_length=100),
                         context=Depends(require_permission("sell.view")),
                         snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency)):
        filters = [ErpTransactionDocument.snapshot_id == snapshot.id,
                   ErpTransactionDocument.location_id.in_(context["location_ids"])]
        if q:
            filters.append(ErpTransactionDocument.document_no.ilike(f"%{q.strip()}%"))
        total = session.scalar(select(func.count(ErpTransactionDocument.id)).where(*filters)) or 0
        rows = session.execute(select(ErpTransactionDocument.id, ErpTransactionDocument.source_kind,
                                      ErpTransactionDocument.document_no, ErpTransactionDocument.occurred_at,
                                      ErpTransactionDocument.location_id, ErpTransactionDocument.total_amount,
                                      ErpTransactionDocument.migration_status).where(
            *filters).order_by(
            ErpTransactionDocument.id).offset(offset).limit(limit)).all()
        return {"items": [dict(row._mapping) for row in rows], "total": total,
                "limit": limit, "offset": offset, "location_scope_enforced": True}

    def document_family_endpoint(permission_code: str, kinds: tuple[str, ...]):
        def endpoint(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                     q: str | None = Query(None, max_length=100),
                     context=Depends(require_permission(permission_code)),
                     snapshot: SourceSnapshot = Depends(snapshot_dependency),
                     session: Session = Depends(session_dependency)):
            filters = [ErpTransactionDocument.snapshot_id == snapshot.id,
                       ErpTransactionDocument.location_id.in_(context["location_ids"]),
                       ErpTransactionDocument.source_kind.in_(kinds)]
            if q:
                filters.append(ErpTransactionDocument.document_no.ilike(f"%{q.strip()}%"))
            total = session.scalar(select(func.count(ErpTransactionDocument.id)).where(*filters)) or 0
            rows = session.execute(select(
                ErpTransactionDocument.id, ErpTransactionDocument.source_kind,
                ErpTransactionDocument.document_no, ErpTransactionDocument.occurred_at,
                ErpTransactionDocument.location_id, ErpTransactionDocument.total_amount,
                ErpTransactionDocument.paid_amount, ErpTransactionDocument.due_amount,
                ErpTransactionDocument.migration_status).where(*filters).order_by(
                ErpTransactionDocument.id.desc()).offset(offset).limit(limit)).all()
            return {"items": [dict(row._mapping) for row in rows], "total": total,
                    "limit": limit, "offset": offset, "location_scope_enforced": True,
                    "posting_enabled": False}
        return endpoint

    app.add_api_route("/api/v1/secure/sales", document_family_endpoint(
        "sell.view", ("sale", "sell", "sell_return")), methods=["GET"], name="secure_sales")
    app.add_api_route("/api/v1/secure/purchases", document_family_endpoint(
        "purchase.view", ("purchase", "purchase_return")), methods=["GET"], name="secure_purchases")

    def document_detail_endpoint(permission_code: str, kinds: tuple[str, ...]):
        def endpoint(document_id: int,
                     context=Depends(require_permission(permission_code)),
                     snapshot: SourceSnapshot = Depends(snapshot_dependency),
                     session: Session = Depends(session_dependency)):
            document = session.execute(select(
                ErpTransactionDocument.id, ErpTransactionDocument.source_kind,
                ErpTransactionDocument.document_no, ErpTransactionDocument.occurred_at,
                ErpTransactionDocument.party_id, ErpTransactionDocument.location_id,
                ErpTransactionDocument.counterparty_location_id,
                ErpTransactionDocument.parent_document_id, ErpTransactionDocument.total_amount,
                ErpTransactionDocument.paid_amount, ErpTransactionDocument.due_amount,
                ErpTransactionDocument.return_due_amount, ErpTransactionDocument.source_status,
                ErpTransactionDocument.migration_status,
            ).where(ErpTransactionDocument.id == document_id,
                    ErpTransactionDocument.snapshot_id == snapshot.id,
                    ErpTransactionDocument.source_kind.in_(kinds),
                    ErpTransactionDocument.location_id.in_(context["location_ids"]))).mappings().one_or_none()
            if not document:
                raise HTTPException(status_code=404, detail="Document not found in the active location scope")
            lines = session.execute(select(
                ErpTransactionLine.id, ErpTransactionLine.source_line_no,
                ErpTransactionLine.product_id, ErpTransactionLine.entered_quantity,
                ErpTransactionLine.entered_uom, ErpTransactionLine.unit_price,
                ErpTransactionLine.subtotal, ErpTransactionLine.relation_status,
            ).where(ErpTransactionLine.snapshot_id == snapshot.id,
                    ErpTransactionLine.document_id == document_id).order_by(
                ErpTransactionLine.source_line_no, ErpTransactionLine.id)).mappings().all()
            payments = session.execute(select(
                ErpTransactionPayment.id, ErpTransactionPayment.reference_no,
                ErpTransactionPayment.paid_at, ErpTransactionPayment.method,
                ErpTransactionPayment.amount, ErpTransactionPayment.relation_status,
            ).where(ErpTransactionPayment.snapshot_id == snapshot.id,
                    ErpTransactionPayment.document_id == document_id).order_by(
                ErpTransactionPayment.paid_at, ErpTransactionPayment.id)).mappings().all()
            return {"document": dict(document), "lines": [dict(row) for row in lines],
                    "payments": [dict(row) for row in payments],
                    "line_count": len(lines), "payment_count": len(payments),
                    "location_scope_enforced": True, "posting_enabled": False,
                    "evidence_redacted": True}
        return endpoint

    app.add_api_route("/api/v1/secure/sales/{document_id}", document_detail_endpoint(
        "sell.view", ("sale", "sell", "sell_return")), methods=["GET"], name="secure_sale_detail")
    app.add_api_route("/api/v1/secure/purchases/{document_id}", document_detail_endpoint(
        "purchase.view", ("purchase", "purchase_return")), methods=["GET"], name="secure_purchase_detail")

    @app.get("/api/v1/secure/inventory")
    def secure_inventory(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                         context=Depends(require_permission("stock_report.view")),
                         snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency)):
        filters = [ErpInventoryMovement.snapshot_id == snapshot.id,
                   ErpInventoryMovement.location_id.in_(context["location_ids"])]
        total = session.scalar(select(func.count(ErpInventoryMovement.id)).where(*filters)) or 0
        rows = session.execute(select(
            ErpInventoryMovement.id, ErpInventoryMovement.movement_type,
            ErpInventoryMovement.occurred_at, ErpInventoryMovement.location_id,
            ErpInventoryMovement.product_id, ErpInventoryMovement.entered_quantity,
            ErpInventoryMovement.entered_uom, ErpInventoryMovement.quantity_base,
            ErpInventoryMovement.canonical_uom, ErpInventoryMovement.migration_status).where(
            *filters).order_by(ErpInventoryMovement.id.desc()).offset(offset).limit(limit)).all()
        return {"items": [dict(row._mapping) for row in rows], "total": total,
                "limit": limit, "offset": offset, "location_scope_enforced": True,
                "posting_enabled": False}

    @app.get("/api/v1/secure/inventory/{movement_id}")
    def secure_inventory_detail(movement_id: int,
                                context=Depends(require_permission("stock_report.view")),
                                snapshot: SourceSnapshot = Depends(snapshot_dependency),
                                session: Session = Depends(session_dependency)):
        row = session.execute(select(
            ErpInventoryMovement.id, ErpInventoryMovement.movement_type,
            ErpInventoryMovement.occurred_at, ErpInventoryMovement.location_id,
            ErpInventoryMovement.product_id, ErpProductMaster.sku, ErpProductMaster.name.label("product_name"),
            ErpInventoryMovement.document_id, ErpTransactionDocument.document_no,
            ErpInventoryMovement.entered_quantity, ErpInventoryMovement.entered_uom,
            ErpInventoryMovement.factor_to_base_snapshot, ErpInventoryMovement.quantity_base,
            ErpInventoryMovement.canonical_uom, ErpInventoryMovement.source_posting_status,
            ErpInventoryMovement.migration_status,
        ).outerjoin(ErpProductMaster, ErpProductMaster.id == ErpInventoryMovement.product_id).outerjoin(
            ErpTransactionDocument, ErpTransactionDocument.id == ErpInventoryMovement.document_id).where(
            ErpInventoryMovement.id == movement_id,
            ErpInventoryMovement.snapshot_id == snapshot.id,
            ErpInventoryMovement.location_id.in_(context["location_ids"]))).mappings().one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Inventory movement not found in the active location scope")
        return {"movement": dict(row), "location_scope_enforced": True,
                "posting_enabled": False, "evidence_redacted": True}

    @app.get("/api/v1/secure/products/{product_id}")
    def secure_product_detail(product_id: int,
                              context=Depends(require_permission("product.view")),
                              snapshot: SourceSnapshot = Depends(snapshot_dependency),
                              session: Session = Depends(session_dependency)):
        product = session.execute(select(
            ErpProductMaster.id, ErpProductMaster.sku, ErpProductMaster.name,
            ErpProductMaster.product_type, ErpProductMaster.category_name,
            ErpProductMaster.brand_name, ErpProductMaster.master_status,
        ).where(ErpProductMaster.id == product_id,
                ErpProductMaster.snapshot_id == snapshot.id)).mappings().one_or_none()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        uoms = session.execute(select(
            ErpProductUom.id, ErpProductUom.source_base_uom,
            ErpProductUom.canonical_base_uom, ErpProductUom.factor_to_base_snapshot,
            ErpProductUom.conversion_status,
        ).where(ErpProductUom.snapshot_id == snapshot.id,
                ErpProductUom.product_id == product_id).order_by(ErpProductUom.id)).mappings().all()
        return {"product": dict(product), "uom_profiles": [dict(row) for row in uoms],
                "uom_profile_count": len(uoms), "operational_enabled": False,
                "evidence_redacted": True}

    def party_detail_endpoint(permission_code: str, kinds: tuple[str, ...]):
        def endpoint(party_id: int, context=Depends(require_permission(permission_code)),
                     snapshot: SourceSnapshot = Depends(snapshot_dependency),
                     session: Session = Depends(session_dependency)):
            party = session.execute(select(
                ErpParty.id, ErpParty.party_code, ErpParty.party_kind,
                ErpParty.legal_or_business_name, ErpParty.contact_name,
                ErpParty.master_status,
            ).where(ErpParty.id == party_id, ErpParty.snapshot_id == snapshot.id,
                    ErpParty.party_kind.in_(kinds))).mappings().one_or_none()
            if not party:
                raise HTTPException(status_code=404, detail="Party not found")
            return {"party": dict(party), "contact_fields_redacted": True,
                    "operational_enabled": False}
        return endpoint

    app.add_api_route("/api/v1/secure/parties/{party_id}", party_detail_endpoint(
        "customer.view", ("customer", "both")), methods=["GET"], name="secure_party_detail")
    app.add_api_route("/api/v1/secure/suppliers/{party_id}", party_detail_endpoint(
        "supplier.view", ("supplier", "both")), methods=["GET"], name="secure_supplier_detail")

    @app.get("/api/v1/secure/accounting-summary")
    def secure_accounting_summary(context=Depends(require_permission("accounting.view_reports")),
                                  snapshot: SourceSnapshot = Depends(snapshot_dependency),
                                  session: Session = Depends(session_dependency)):
        journals = dict(session.execute(select(ErpJournalBlueprint.migration_status, func.count()).where(
            ErpJournalBlueprint.snapshot_id == snapshot.id).group_by(ErpJournalBlueprint.migration_status)).all())
        return {"journal_status": journals, "active_location_scope_required": True,
                "row_location_filter_applicable": False,
                "details_redacted": True, "posting_enabled": False}

    @app.get("/api/v1/secure/export-catalog")
    def secure_export_catalog(context=Depends(require_permission("accounting.view_reports")),
                              snapshot: SourceSnapshot = Depends(snapshot_dependency)):
        store = app.state.uat_review_store
        decisions = store.latest_business_review_decisions(snapshot.name) if store else []
        latest_by_module = {}
        for decision in decisions:
            latest_by_module.setdefault(decision["module_code"], decision)
        return {"items": [{"module": module, "required_permission": permission,
                           "package_path": f"/api/v1/secure/exports/{module}",
                           "format": "zip_csv_json", "posting_enabled": False,
                           "latest_uat_decision": (latest_by_module.get(module) or {}).get("decision_code"),
                           "latest_package_sha256": (latest_by_module.get(module) or {}).get("package_sha256")}
                          for module, permission in EXPORT_MODULES.items()],
                "total": len(EXPORT_MODULES), "location_scope_enforced_on_download": True,
                "sensitive_fields_redacted": True, "source_mutation_enabled": False}

    def export_endpoint(module: str, permission_code: str):
        def endpoint(context=Depends(require_permission(permission_code)),
                     snapshot: SourceSnapshot = Depends(snapshot_dependency),
                     session: Session = Depends(session_dependency)):
            locations = session.execute(select(ErpLocation.id, ErpLocation.code).where(
                ErpLocation.snapshot_id == snapshot.id,
                ErpLocation.id.in_(context["location_ids"])).order_by(ErpLocation.code)).all()
            package = build_review_package(
                session, snapshot, module, context["location_ids"],
                [row.code for row in locations],
                context["principal"].login_name or f"principal:{context['principal'].id}",
            )
            return StreamingResponse(
                BytesIO(package["content"]), media_type="application/zip",
                headers={
                    "Content-Disposition": f'attachment; filename="{package["filename"]}"',
                    "X-Content-SHA256": package["sha256"],
                    "X-Export-Module": module,
                    "X-Location-Scope": ",".join(row.code for row in locations),
                    "X-Posting-Enabled": "false",
                },
            )
        return endpoint

    for export_module, export_permission in EXPORT_MODULES.items():
        app.add_api_route(
            f"/api/v1/secure/exports/{export_module}",
            export_endpoint(export_module, export_permission), methods=["GET"],
            name=f"secure_{export_module}_review_export",
        )

    @app.get("/api/v1/secure/business-reviews")
    def secure_business_reviews(context=Depends(require_permission("accounting.view_reports")),
                                snapshot: SourceSnapshot = Depends(snapshot_dependency)):
        store = app.state.uat_review_store
        items = store.latest_business_review_decisions(snapshot.name) if store else []
        return {"items": items, "total": len(items),
                "allowed_decision_codes": sorted(BUSINESS_REVIEW_DECISION_CODES),
                "review_sidecar_enabled": store is not None,
                "synthetic_only": True, "production_signoff_enabled": False,
                "source_mutation_enabled": False}

    def business_review_decision_endpoint(module: str, permission_code: str):
        def endpoint(payload: BusinessReviewDecisionRequest, request: Request,
                     context=Depends(require_permission(permission_code)),
                     snapshot: SourceSnapshot = Depends(snapshot_dependency),
                     session: Session = Depends(session_dependency)):
            store = app.state.uat_review_store
            if not settings.uat_auth_enabled or not store:
                raise HTTPException(status_code=503, detail="UAT review sidecar is not enabled")
            active = app.state.uat_sessions.get(request.cookies.get(UAT_COOKIE))
            if not active or request.headers.get("x-csrf-token") != active.csrf_token:
                raise HTTPException(status_code=403, detail="CSRF validation failed")
            if payload.decision_code not in BUSINESS_REVIEW_DECISION_CODES:
                raise HTTPException(status_code=422, detail="Unsupported UAT decision code")
            locations = session.execute(select(ErpLocation.code).where(
                ErpLocation.snapshot_id == snapshot.id,
                ErpLocation.id.in_(context["location_ids"])).order_by(ErpLocation.code)).scalars().all()
            decision = store.add_business_review_decision(
                snapshot_name=snapshot.name, module_code=module,
                package_sha256=payload.package_sha256,
                decision_code=payload.decision_code, rationale=payload.rationale.strip(),
                decided_by=context["principal"].login_name or f"principal:{context['principal'].id}",
                location_codes=list(locations),
            )
            return {"decision": decision, "decision_recorded": True,
                    "synthetic_only": True, "production_signoff": False,
                    "source_or_clone_modified": False, "approval_performed": False}
        return endpoint

    for review_module, review_permission in EXPORT_MODULES.items():
        app.add_api_route(
            f"/api/v1/uat/business-reviews/{review_module}",
            business_review_decision_endpoint(review_module, review_permission), methods=["POST"],
            name=f"record_{review_module}_uat_business_review",
        )

    @app.get("/api/v1/secure/workflows")
    def secure_workflows(context=Depends(require_permission("accounting.view_reports")),
                         snapshot: SourceSnapshot = Depends(snapshot_dependency),
                         session: Session = Depends(session_dependency)):
        workflows = session.execute(select(
            ErpWorkflowDefinition.workflow_code, ErpWorkflowDefinition.workflow_name,
            ErpWorkflowDefinition.initial_state, ErpWorkflowDefinition.states,
            ErpWorkflowDefinition.transitions, ErpWorkflowDefinition.workflow_status,
            ErpWorkflowDefinition.execution_enabled,
        ).where(ErpWorkflowDefinition.snapshot_id == snapshot.id).order_by(
            ErpWorkflowDefinition.workflow_code)).all()
        policies = {row.policy_code: {"name": row.name, "status": row.status,
                                     "activation_enabled": row.activation_enabled}
                    for row in session.scalars(select(ErpApprovalPolicy).where(
                        ErpApprovalPolicy.snapshot_id == snapshot.id)).all()}
        items = []
        for row in workflows:
            values = dict(row._mapping)
            values["state_count"] = len(values.pop("states") or [])
            values["transition_count"] = len(values.pop("transitions") or [])
            values["policy_status"] = policies.get(row.workflow_code.casefold(), {}).get("status", "not_linked")
            items.append(values)
        return {"items": items, "total": len(items), "approval_policies": len(policies),
                "execution_enabled": False, "posting_enabled": False,
                "note": "Blueprint review only. No transition or approval mutation endpoint exists."}

    def safe_evidence(value):
        if isinstance(value, dict):
            return {str(key): ("[redacted]" if any(fragment in str(key).casefold()
                    for fragment in SENSITIVE_EVIDENCE_FRAGMENTS) else safe_evidence(item))
                    for key, item in value.items()}
        if isinstance(value, list):
            return [safe_evidence(item) for item in value[:50]]
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    def exception_fingerprint(item: ErpMigrationExceptionQueue) -> str:
        payload = {"id": item.id, "snapshot_id": item.snapshot_id,
                   "source_kind": item.source_kind, "source_id": item.source_id,
                   "exception_code": item.exception_code, "severity": item.severity,
                   "queue_status": item.queue_status, "activation_blocked": item.activation_blocked,
                   "evidence": item.evidence}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                         default=str).encode()).hexdigest()

    @app.get("/api/v1/secure/discrepancies")
    def secure_discrepancies(limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
                             exception_code: str | None = Query(None, max_length=100),
                             severity: str | None = Query(None, max_length=20),
                             q: str | None = Query(None, max_length=100),
                             context=Depends(require_permission("accounting.view_reports")),
                             snapshot: SourceSnapshot = Depends(snapshot_dependency),
                             session: Session = Depends(session_dependency)):
        filters = [ErpMigrationExceptionQueue.snapshot_id == snapshot.id]
        if exception_code:
            filters.append(ErpMigrationExceptionQueue.exception_code == exception_code)
        if severity:
            filters.append(ErpMigrationExceptionQueue.severity == severity)
        if q:
            term = q.strip()
            searchable = [ErpMigrationExceptionQueue.exception_code.ilike(f"%{term}%"),
                          ErpMigrationExceptionQueue.source_kind.ilike(f"%{term}%")]
            if term.isdigit():
                searchable.append(ErpMigrationExceptionQueue.source_id == int(term))
            filters.append(or_(*searchable))
        total = session.scalar(select(func.count(ErpMigrationExceptionQueue.id)).where(*filters)) or 0
        rows = list(session.scalars(select(ErpMigrationExceptionQueue).where(*filters).order_by(
            ErpMigrationExceptionQueue.severity, ErpMigrationExceptionQueue.exception_code,
            ErpMigrationExceptionQueue.id).offset(offset).limit(limit)).all())
        store = app.state.uat_review_store
        proposals = store.proposals_for(snapshot.name, [item.id for item in rows]) if store else {}
        return {"items": [{"id": item.id, "source_kind": item.source_kind,
                           "source_id": item.source_id, "exception_code": item.exception_code,
                           "severity": item.severity, "queue_status": item.queue_status,
                           "activation_blocked": item.activation_blocked,
                           "evidence": safe_evidence(item.evidence),
                           "proposal_count": len(proposals.get(item.id, [])),
                           "latest_proposal": (proposals.get(item.id) or [None])[0]}
                          for item in rows], "total": total, "limit": limit, "offset": offset,
                "review_sidecar_enabled": store is not None, "source_mutation_enabled": False,
                "allowed_resolution_codes": sorted(PROPOSAL_CODES)}

    @app.get("/api/v1/secure/approval-governance")
    def secure_approval_governance(context=Depends(require_permission("accounting.view_reports")),
                                   snapshot: SourceSnapshot = Depends(snapshot_dependency),
                                   session: Session = Depends(session_dependency)):
        rows = session.execute(select(
            ErpApprovalPolicy.policy_code, ErpApprovalPolicy.name.label("policy_name"),
            ErpApprovalStep.step_no, ErpApprovalStep.role_code.label("required_role"),
            ErpApprovalStep.decision_required, ErpSecurityRole.role_code.label("proposed_role"),
            ErpSecurityRole.role_name.label("proposed_role_name"),
            ErpApprovalRoleBinding.binding_status, ErpApprovalRoleBinding.assignment_enabled,
        ).join(ErpApprovalStep, ErpApprovalStep.policy_id == ErpApprovalPolicy.id).outerjoin(
            ErpApprovalRoleBinding, ErpApprovalRoleBinding.approval_step_id == ErpApprovalStep.id).outerjoin(
            ErpSecurityRole, ErpSecurityRole.id == ErpApprovalRoleBinding.target_role_id).where(
            ErpApprovalPolicy.snapshot_id == snapshot.id).order_by(
            ErpApprovalPolicy.policy_code, ErpApprovalStep.step_no)).all()
        draft_assignments = (app.state.uat_review_store.latest_governance_assignments()
                             if app.state.uat_review_store else {})
        items = []
        for row in rows:
            item = dict(row._mapping)
            draft = draft_assignments.get(item["required_role"])
            item["draft_assignee"] = draft["display_name"] if draft else "Unassigned"
            item["draft_login_alias"] = draft["login_alias"] if draft else None
            item["draft_locations"] = ", ".join(draft["location_codes"]) if draft else None
            item["threshold_rule"] = draft["threshold_rule"] if draft else None
            item["delegation_rule"] = draft["delegation_rule"] if draft else None
            item["synthetic_assignment_status"] = draft["assignment_status"] if draft else "unassigned"
            items.append(item)
        return {"items": items, "total": len(items),
                "thresholds_configured": False, "delegations_configured": False,
                "real_user_bindings": 0, "synthetic_draft_assignments": len(draft_assignments),
                "assignment_enabled": False,
                "approval_actions_enabled": False,
                "note": "Proposed role mappings only; named users and business approval are required."}

    @app.get("/api/v1/secure/segregation-controls")
    def secure_segregation_controls(context=Depends(require_permission("accounting.view_reports")),
                                    snapshot: SourceSnapshot = Depends(snapshot_dependency),
                                    session: Session = Depends(session_dependency)):
        rows = session.execute(select(
            ErpSegregationRule.rule_code, ErpSegregationRule.rule_name,
            ErpSegregationRule.maker_capability, ErpSegregationRule.checker_capability,
            ErpSegregationRule.status, ErpSegregationRule.enforcement_enabled,
        ).where(ErpSegregationRule.snapshot_id == snapshot.id).order_by(
            ErpSegregationRule.rule_code)).all()
        return {"items": [dict(row._mapping) for row in rows], "total": len(rows),
                "enforcement_enabled": False, "assignment_enabled": False,
                "note": "Draft controls only; no real-user permission grants are active."}

    @app.post("/api/v1/uat/discrepancy-proposals")
    def create_discrepancy_proposal(payload: DiscrepancyProposalRequest, request: Request,
                                    context=Depends(require_permission("accounting.view_reports")),
                                    snapshot: SourceSnapshot = Depends(snapshot_dependency),
                                    session: Session = Depends(session_dependency)):
        store = app.state.uat_review_store
        if not settings.uat_auth_enabled or not store:
            raise HTTPException(status_code=503, detail="UAT review sidecar is not enabled")
        active = app.state.uat_sessions.get(request.cookies.get(UAT_COOKIE))
        if not active or request.headers.get("x-csrf-token") != active.csrf_token:
            raise HTTPException(status_code=403, detail="CSRF validation failed")
        if payload.resolution_code not in PROPOSAL_CODES:
            raise HTTPException(status_code=422, detail="Unsupported resolution code")
        if len(json.dumps(payload.proposed_value, default=str)) > 4000:
            raise HTTPException(status_code=422, detail="Proposed value is too large")
        item = session.get(ErpMigrationExceptionQueue, payload.exception_id)
        if not item or item.snapshot_id != snapshot.id:
            raise HTTPException(status_code=404, detail="Discrepancy not found in the configured snapshot")
        principal = context["principal"]
        proposal = store.add_proposal(
            snapshot_name=snapshot.name, exception_id=item.id,
            resolution_code=payload.resolution_code, proposed_value=payload.proposed_value,
            rationale=payload.rationale.strip(), proposed_by=principal.login_name or f"principal:{principal.id}",
            source_exception_fingerprint=exception_fingerprint(item),
        )
        return {"proposal": proposal, "proposal_status": "draft",
                "source_exception_modified": False, "approval_performed": False}

    return app


app = create_app()


def run() -> None:
    import uvicorn
    uvicorn.run("klen_clone.web:app", host="127.0.0.1", port=int(os.getenv("KLEN_PORT", "8080")), reload=False)
