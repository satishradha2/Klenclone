from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .auth import UatSessionStore, verify_password
from .delta_overlay import load_delta_overlay
from .db import make_engine
from .models import (
    ErpGlAccount,
    ErpAuditEvent,
    ErpInventoryMovement,
    ErpLocation,
    ErpMigrationExceptionQueue,
    ErpOpeningBalanceQueue,
    ErpOrganization,
    ErpParty,
    ErpProductMaster,
    ErpProductUom,
    ErpTransactionLine,
    ErpTransactionDocument,
    SourceSnapshot,
)
from .operational import (
    OperationalAuditEvent, OperationalDraft, OperationalFiscalPeriod, OperationalJournalBatch,
    OperationalFinancialMigrationException, OperationalOpeningPartyBalance,
    OperationalPostingProbe, OperationalReversalRequest, OperationalStockPosition,
    OperationalStockReservation, OperationalSubledgerEntry,
    calculate_line, create_draft, initialize_operational_database, list_drafts,
    make_operational_engine, operational_session_factory, execute_posting, execute_reversal,
    rehearse_posting, replace_draft, transition_draft,
)
from .inventory_operations import (
    OperationalInventoryDocument,
    create_inventory_document,
    inventory_control_counts,
    list_inventory_documents,
    rehearse_inventory_posting,
    replace_inventory_document,
    transition_inventory_document,
)
from .goods_receipts import (
    OperationalGoodsReceipt,
    create_goods_receipt,
    goods_receipt_control_counts,
    list_goods_receipts,
    rehearse_goods_receipt_posting,
    replace_goods_receipt,
    transition_goods_receipt,
)
from .data_governance import PROMOTION_GATES, lifecycle_actions, promotion_control_counts
from .data_reviews import (
    OperationalDataReview, enrich_review_source, review_control_counts, review_payload, start_review,
    transaction_review_findings, transition_review,
)
from .sales_returns import (
    OperationalSalesReturn, create_sales_return, list_sales_returns,
    rehearse_sales_return_posting, replace_sales_return,
    sales_return_control_counts, transition_sales_return,
)
from .purchase_returns import (
    OperationalPurchaseReturn, create_purchase_return, list_purchase_returns,
    purchase_return_control_counts, rehearse_purchase_return_posting,
    replace_purchase_return, transition_purchase_return,
)
from .payments import (
    OperationalPayment, OperationalPaymentAllocationClaim, create_payment,
    list_payments, payment_control_counts, rehearse_payment_posting,
    replace_payment, transition_payment,
)
from .financial_reports import build_accounting_summary, build_ageing_report
from .posting_integration import (
    RESOURCE_TYPES,
    OperationalIntegratedPostingBatch,
    execute_integrated_posting,
    execute_integrated_reversal,
    get_posting_resource,
    integrated_posting_counts,
)
from .provisioned_users import load_provisioned_users
from .security_runtime import PersistentSessionStore, production_security_settings, validate_production_security
from .operational_masters import OperationalLocationMaster, OperationalPartyMaster, OperationalProductMaster
from .source_verification import source_verification_counts


STATIC_DIR = Path(__file__).with_name("static")
DEFAULT_SNAPSHOT = "bizmodo-2026-09-08-browser"
SESSION_COOKIE = "asas_erp_session"


def baseline_review_evidence(session: Session, snapshot: SourceSnapshot, entity_type: str,
                             source_record_key: str) -> tuple[dict, str] | None:
    document = session.scalar(select(ErpTransactionDocument).where(
        ErpTransactionDocument.snapshot_id == snapshot.id,
        ErpTransactionDocument.source_kind == entity_type,
        ErpTransactionDocument.document_no == source_record_key,
    ))
    if not document:
        return None
    party = session.get(ErpParty, document.party_id) if document.party_id else None
    location = session.get(ErpLocation, document.location_id) if document.location_id else None
    line_rows = session.execute(select(
        ErpTransactionLine, ErpProductMaster.sku, ErpProductMaster.name,
    ).outerjoin(ErpProductMaster, ErpProductMaster.id == ErpTransactionLine.product_id).where(
        ErpTransactionLine.document_id == document.id).order_by(ErpTransactionLine.source_line_no)).all()
    evidence = {
        "document_no": document.document_no, "source_kind": document.source_kind,
        "occurred_at": document.occurred_at, "total_amount": document.total_amount,
        "paid_amount": document.paid_amount, "due_amount": document.due_amount,
        "return_due_amount": document.return_due_amount, "source_status": document.source_status,
        "migration_status": document.migration_status,
        "party_name": party.legal_or_business_name if party else None,
        "location": location.code if location else None,
        "lines": [{
            "line_no": line.source_line_no,
            "sku": sku, "description": product_name,
            "entered_quantity": line.entered_quantity, "entered_uom": line.entered_uom,
            "unit_price": line.unit_price, "subtotal": line.subtotal,
            "relation_status": line.relation_status, "evidence": line.evidence,
        } for line, sku, product_name in line_rows],
    }
    return evidence, document.migration_status


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=500)


class DraftLineRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    uom: str = Field(min_length=1, max_length=80)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    tax_rate: Decimal = Field(default=Decimal("5"), ge=0, le=100, max_digits=7, decimal_places=4)


class DraftRequest(BaseModel):
    document_type: str = Field(pattern="^(sale|purchase)$")
    party_code: str = Field(min_length=1, max_length=80)
    location_code: str = Field(min_length=1, max_length=80)
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=2)
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[DraftLineRequest] = Field(min_length=1, max_length=100)


class DraftUpdateRequest(DraftRequest):
    expected_revision: int = Field(ge=1)


class DraftTransitionRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=2000)


class PostingExecutionRequest(BaseModel):
    idempotency_key: str = Field(min_length=20, max_length=160)


class ReversalExecutionRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)


class InventoryLineRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    uom: str = Field(min_length=1, max_length=80)
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)


class InventoryDocumentRequest(BaseModel):
    document_type: str = Field(pattern="^(transfer|adjustment)$")
    location_code: str = Field(min_length=1, max_length=80)
    destination_location_code: str | None = Field(default=None, max_length=80)
    adjustment_direction: str | None = Field(default=None, pattern="^(increase|decrease)$")
    reason_code: str = Field(min_length=2, max_length=40)
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[InventoryLineRequest] = Field(min_length=1, max_length=100)


class GoodsReceiptLineRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    ordered_quantity: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    received_quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    accepted_quantity: Decimal = Field(ge=0, max_digits=18, decimal_places=6)
    rejected_quantity: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=6)
    uom: str = Field(min_length=1, max_length=80)
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    batch_no: str | None = Field(default=None, max_length=160)
    expiry_date: date | None = None
    rejection_reason: str | None = Field(default=None, max_length=500)


class GoodsReceiptRequest(BaseModel):
    supplier_code: str = Field(min_length=1, max_length=80)
    location_code: str = Field(min_length=1, max_length=80)
    purchase_reference: str | None = Field(default=None, max_length=160)
    supplier_delivery_note: str | None = Field(default=None, max_length=160)
    received_on: date
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[GoodsReceiptLineRequest] = Field(min_length=1, max_length=100)


class SalesReturnLineRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    restock_quantity: Decimal = Field(ge=0, max_digits=18, decimal_places=6)
    writeoff_quantity: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=6)
    uom: str = Field(min_length=1, max_length=80)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    tax_rate: Decimal = Field(default=Decimal("5"), ge=0, le=100, max_digits=7, decimal_places=4)
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    disposition_reason: str | None = Field(default=None, max_length=500)


class SalesReturnRequest(BaseModel):
    customer_code: str = Field(min_length=1, max_length=80)
    location_code: str = Field(min_length=1, max_length=80)
    original_invoice_reference: str = Field(min_length=1, max_length=160)
    return_date: date
    reason_code: str = Field(min_length=2, max_length=80)
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[SalesReturnLineRequest] = Field(min_length=1, max_length=100)


class PurchaseReturnLineRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    supplier_return_quantity: Decimal = Field(ge=0, max_digits=18, decimal_places=6)
    internal_writeoff_quantity: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=6)
    uom: str = Field(min_length=1, max_length=80)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    tax_rate: Decimal = Field(default=Decimal("5"), ge=0, le=100, max_digits=7, decimal_places=4)
    disposition_reason: str | None = Field(default=None, max_length=500)


class PurchaseReturnRequest(BaseModel):
    supplier_code: str = Field(min_length=1, max_length=80)
    location_code: str = Field(min_length=1, max_length=80)
    source_reference_type: str = Field(pattern="^(goods_receipt|purchase_invoice)$")
    source_reference_key: str = Field(min_length=1, max_length=160)
    return_date: date
    reason_code: str = Field(min_length=2, max_length=80)
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[PurchaseReturnLineRequest] = Field(min_length=1, max_length=100)


class PaymentAllocationRequest(BaseModel):
    source_type: str = Field(pattern="^(invoice|opening_balance)$")
    source_reference_key: str = Field(min_length=1, max_length=160)
    allocation_amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)


class PaymentRequest(BaseModel):
    payment_type: str = Field(pattern="^(customer_receipt|supplier_payment)$")
    party_code: str = Field(min_length=1, max_length=80)
    location_code: str = Field(min_length=1, max_length=80)
    payment_date: date
    payment_method: str = Field(pattern="^(cash|bank_transfer|card|cheque|other)$")
    cash_bank_account_code: str = Field(min_length=1, max_length=80)
    reference_no: str | None = Field(default=None, max_length=160)
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    notes: str | None = Field(default=None, max_length=2000)
    allocations: list[PaymentAllocationRequest] = Field(default_factory=list, max_length=100)


class ProductMasterUpdateRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=500)
    category_name: str | None = Field(default=None, max_length=200)
    brand_name: str | None = Field(default=None, max_length=200)
    purchase_price: Decimal = Field(ge=0, max_digits=18, decimal_places=6)
    selling_price: Decimal = Field(ge=0, max_digits=18, decimal_places=6)
    tax_rate: Decimal = Field(ge=0, le=100, max_digits=7, decimal_places=4)


class PartyMasterUpdateRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    legal_or_business_name: str = Field(min_length=1, max_length=500)
    contact_name: str | None = Field(default=None, max_length=300)
    email: str | None = Field(default=None, max_length=320)
    mobile: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=2000)
    tax_number: str | None = Field(default=None, max_length=120)


class MasterStatusRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=500)


class DataReviewStartRequest(BaseModel):
    entity_type: str = Field(pattern="^(sale|purchase|sale_return|purchase_return)$")
    source_record_key: str = Field(min_length=1, max_length=200)


class DataReviewActionRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    rationale: str | None = Field(default=None, max_length=2000)
    corrected_payload: dict | None = None


def create_app(database_url: str | None = None, snapshot_name: str | None = None,
               delta_capture: Path | bool | None = None) -> FastAPI:
    engine = make_engine(database_url)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    selected_snapshot = snapshot_name or os.getenv("KLEN_SNAPSHOT", DEFAULT_SNAPSHOT)
    app = FastAPI(
        title="Asas ERP Preview",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        description="Independent ERP staging application backed by preserved BizModo evidence and a separate operational database.",
    )
    app.state.engine = engine
    app.state.snapshot_name = selected_snapshot
    security_settings = production_security_settings()
    app.state.production_mode = security_settings["production"]
    app.state.auth_enabled = os.getenv("ASAS_AUTH_ENABLED", "false").lower() == "true"
    app.state.admin_username = os.getenv("ASAS_ADMIN_USERNAME", "").strip()
    app.state.admin_password_hash = os.getenv("ASAS_ADMIN_PASSWORD_HASH", "").strip()
    app.state.session_ttl = int(os.getenv("ASAS_SESSION_TTL_SECONDS", "1800"))
    if not 300 <= app.state.session_ttl <= 43_200:
        raise RuntimeError("ASAS_SESSION_TTL_SECONDS must be between 300 and 43200")
    app.state.users_by_login, app.state.users_by_id = load_provisioned_users(
        os.getenv("ASAS_USERS_FILE"), app.state.admin_username, app.state.admin_password_hash,
    )
    operational_url = os.getenv("ASAS_OPERATIONAL_DATABASE_URL", "").strip()
    validate_production_security(security_settings, auth_enabled=app.state.auth_enabled,
                                 operational_url=operational_url)
    app.state.posting_enabled = security_settings["posting_requested"] and (
        not app.state.production_mode or (
            security_settings["posting_confirmed"]
            and len(security_settings["posting_approval_reference"]) >= 8
        )
    )
    app.state.secure_cookies = security_settings["secure_cookies"]
    app.state.session_cookie_name = "__Host-asas_erp_session" if app.state.production_mode else SESSION_COOKIE
    app.state.posting_approval_reference = security_settings["posting_approval_reference"]
    if app.state.auth_enabled and not app.state.users_by_login:
        raise RuntimeError("Asas authentication is enabled but administrator credentials are not provisioned")
    app.state.operational_engine = make_operational_engine(operational_url) if operational_url else None
    app.state.operational_sessions = operational_session_factory(app.state.operational_engine) if operational_url else None
    if app.state.operational_engine:
        initialize_operational_database(app.state.operational_engine)
    app.state.sessions = (PersistentSessionStore(app.state.operational_sessions, security_settings["session_secret"])
                          if app.state.production_mode else UatSessionStore())
    if security_settings["allowed_hosts"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(security_settings["allowed_hosts"]))
    if delta_capture is False or (delta_capture is None and database_url is not None):
        app.state.delta_overlay = None
    else:
        app.state.delta_overlay = load_delta_overlay(delta_capture if isinstance(delta_capture, Path) else None)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def session_dependency():
        with sessions() as session:
            yield session

    def snapshot_dependency(session: Session = Depends(session_dependency)) -> SourceSnapshot:
        snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == selected_snapshot))
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Configured BizModo clone snapshot is unavailable")
        return snapshot

    def active_session(request: Request):
        return app.state.sessions.get(request.cookies.get(app.state.session_cookie_name))

    def current_user(request: Request):
        current = active_session(request)
        return app.state.users_by_id.get(current.principal_id) if current else None

    def require_user(request: Request, permission: str):
        if not app.state.auth_enabled:
            return None
        user = current_user(request)
        if not user:
            raise HTTPException(status_code=401, detail="Authentication required")
        if permission not in user.permissions:
            raise HTTPException(status_code=403, detail=f"Permission {permission} is required")
        return user

    def principal_payload(user) -> dict:
        return {"login_name": user.username, "roles": list(user.roles),
                "permissions": list(user.permissions),
                "allowed_locations": list(user.allowed_locations),
                "posting_enabled": app.state.posting_enabled}

    def location_allowed(user, location_code: str) -> bool:
        allowed = set(user.allowed_locations)
        return "*" in allowed or location_code.upper() in allowed

    def operational_session_dependency():
        if app.state.operational_sessions is None:
            raise HTTPException(status_code=503, detail="Operational database is not configured")
        with app.state.operational_sessions() as operational_session:
            yield operational_session

    def optional_operational_session_dependency():
        if app.state.operational_sessions is None:
            yield None
            return
        with app.state.operational_sessions() as operational_session:
            yield operational_session

    def audit(session: Session, snapshot_id: int, event_type: str, outcome: str, request: Request) -> None:
        client = request.client.host if request.client else "unknown"
        if app.state.production_mode and app.state.operational_sessions:
            with app.state.operational_sessions() as operational_session:
                operational_session.add(OperationalAuditEvent(
                    event_key=str(uuid.uuid4()), event_type=event_type,
                    actor="authentication_service", resource_key=None,
                    detail=f"outcome={outcome}; client_sha256={hashlib.sha256(client.encode()).hexdigest()}",
                ))
                operational_session.commit()
            return
        session.add(ErpAuditEvent(
            snapshot_id=snapshot_id,
            event_key=f"asas-auth:{uuid.uuid4()}",
            event_type=event_type,
            actor_type="provisioned_preview_admin",
            details={"outcome": outcome, "client": client, "posting_enabled": False},
        ))
        session.commit()

    def secure_response(response, request_id: str):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = ("default-src 'self'; base-uri 'self'; object-src 'none'; "
            "frame-ancestors 'none'; form-action 'self'; style-src 'self'; script-src 'self'; connect-src 'self'")
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
        if app.state.production_mode:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Request-ID"] = request_id
        return response

    @app.middleware("http")
    async def preview_safety(request: Request, call_next):
        request_id = request.headers.get("x-request-id", "").strip()
        if not request_id or len(request_id) > 128:
            request_id = str(uuid.uuid4())
        if (app.state.production_mode and request.url.path != "/api/v1/health"
                and request.url.scheme != "https"):
            return secure_response(RedirectResponse(str(request.url.replace(scheme="https")), status_code=307), request_id)
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > 2 * 1024 * 1024:
            return secure_response(JSONResponse(status_code=413, content={"detail": "Request body is too large"}), request_id)
        auth_posts = {"/api/v1/auth/login", "/api/v1/auth/logout"}
        operational_mutation = (request.url.path.startswith("/api/v1/drafts")
                                or request.url.path.startswith("/api/v1/journal-batches")
                                or request.url.path.startswith("/api/v1/inventory-documents")
                                or request.url.path.startswith("/api/v1/goods-receipts")
                                or request.url.path.startswith("/api/v1/sales-returns")
                                or request.url.path.startswith("/api/v1/purchase-returns")
                                or request.url.path.startswith("/api/v1/payments")
                                or request.url.path.startswith("/api/v1/posting/")
                                or request.url.path.startswith("/api/v1/integrated-posting-batches")
                                or request.url.path.startswith("/api/v1/data-reviews")
                                or request.url.path.startswith("/api/v1/master-data/")) and request.method in {"POST", "PUT", "PATCH"}
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path not in auth_posts and not operational_mutation:
            return secure_response(JSONResponse(
                status_code=405,
                content={"detail": "Read-only clone preview: operational writes are not enabled"},
                headers={"Allow": "GET, HEAD, OPTIONS"},
            ), request_id)
        public_api = {"/api/v1/health", "/api/v1/auth/login", "/api/v1/auth/session"}
        if (app.state.auth_enabled and request.url.path.startswith("/api/v1/")
                and request.url.path not in public_api and active_session(request) is None):
            return secure_response(JSONResponse(status_code=401, content={"detail": "Asas ERP authentication required"}), request_id)
        response = await call_next(request)
        return secure_response(response, request_id)

    @app.get("/", include_in_schema=False)
    def index(request: Request):
        if app.state.auth_enabled and active_session(request) is None:
            return RedirectResponse("/login", status_code=303)
        return FileResponse(STATIC_DIR / "erp.html")

    @app.get("/login", include_in_schema=False)
    def login_page(request: Request):
        if app.state.auth_enabled and active_session(request) is not None:
            return RedirectResponse("/", status_code=303)
        return FileResponse(STATIC_DIR / "asas-login.html")

    @app.get("/draft-review.html", include_in_schema=False)
    def draft_review_page(request: Request):
        if app.state.auth_enabled and active_session(request) is None:
            return RedirectResponse("/login", status_code=303)
        return FileResponse(STATIC_DIR / "draft-review.html")

    @app.post("/api/v1/auth/login")
    def login(payload: LoginRequest, request: Request, session: Session = Depends(session_dependency)):
        if not app.state.auth_enabled:
            raise HTTPException(status_code=404, detail="Asas ERP authentication is not enabled")
        attempt_key = f"{request.client.host if request.client else 'unknown'}:{payload.username.casefold()}"
        snapshot_id = session.scalar(select(SourceSnapshot.id).where(SourceSnapshot.name == selected_snapshot))
        if not app.state.sessions.allow_attempt(attempt_key):
            if snapshot_id:
                audit(session, snapshot_id, "auth.login", "rate_limited", request)
            raise HTTPException(status_code=429, detail="Too many sign-in attempts; try again later")
        user = app.state.users_by_login.get(payload.username.strip().casefold())
        valid = bool(user and verify_password(payload.password, user.password_hash))
        if not valid:
            if snapshot_id:
                audit(session, snapshot_id, "auth.login", "denied", request)
            raise HTTPException(status_code=401, detail="Invalid username or password")
        app.state.sessions.clear_attempts(attempt_key)
        token, login_session = app.state.sessions.create(user.id, app.state.session_ttl)
        if snapshot_id:
            audit(session, snapshot_id, "auth.login", "success", request)
        response = JSONResponse({
            "authenticated": True,
            "expires_at": login_session.expires_at,
            "csrf_token": login_session.csrf_token,
            "principal": principal_payload(user),
        })
        response.set_cookie(app.state.session_cookie_name, token, max_age=app.state.session_ttl, httponly=True,
                            secure=app.state.secure_cookies, samesite="strict", path="/")
        return response

    @app.get("/api/v1/auth/session")
    def auth_session(request: Request):
        current = active_session(request) if app.state.auth_enabled else None
        if not current:
            return {"authenticated": False, "authentication_enabled": app.state.auth_enabled}
        user = app.state.users_by_id.get(current.principal_id)
        if not user:
            return {"authenticated": False, "authentication_enabled": True}
        return {"authenticated": True, "authentication_enabled": True,
                "expires_at": current.expires_at, "csrf_token": current.csrf_token,
                "principal": principal_payload(user)}

    @app.post("/api/v1/auth/logout")
    def logout(request: Request, session: Session = Depends(session_dependency)):
        token = request.cookies.get(app.state.session_cookie_name)
        current = app.state.sessions.get(token)
        if not current:
            raise HTTPException(status_code=401, detail="Authentication required")
        if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), current.csrf_token):
            raise HTTPException(status_code=403, detail="CSRF validation failed")
        snapshot_id = session.scalar(select(SourceSnapshot.id).where(SourceSnapshot.name == selected_snapshot))
        app.state.sessions.revoke(token)
        if snapshot_id:
            audit(session, snapshot_id, "auth.logout", "success", request)
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(app.state.session_cookie_name, path="/", samesite="strict",
                               secure=app.state.secure_cookies)
        return response

    @app.get("/api/v1/health")
    def health(session: Session = Depends(session_dependency)):
        session.execute(text("SELECT 1"))
        operational_status = "not_configured"
        if app.state.operational_sessions:
            with app.state.operational_sessions() as operational_session:
                operational_session.execute(text("SELECT 1"))
            operational_status = "reachable"
        exists = session.scalar(select(func.count(SourceSnapshot.id)).where(SourceSnapshot.name == selected_snapshot)) or 0
        return {
            "status": "ok",
            "application": "Asas ERP",
            "mode": "independent_clone_preview",
            "database": "reachable",
            "snapshot": selected_snapshot,
            "snapshot_found": exists == 1,
            "posting_enabled": app.state.posting_enabled,
            "hr_payroll_enabled": False,
            "authentication_enabled": app.state.auth_enabled,
            "production_mode": app.state.production_mode,
            "session_backend": "database" if app.state.production_mode else "process_local",
            "operational_database": operational_status,
        }

    def draft_payload(draft) -> dict:
        return {
            "draft_key": draft.draft_key, "draft_no": draft.draft_no,
            "document_type": draft.document_type, "party_code": draft.party_code,
            "party_name": draft.party_name_snapshot, "location_code": draft.location_code,
            "currency_code": draft.currency_code, "subtotal": draft.subtotal,
            "discount_amount": draft.discount_amount, "tax_amount": draft.tax_amount,
            "total_amount": draft.total_amount, "status": draft.status,
            "posting_enabled": draft.posting_enabled, "created_by": draft.created_by,
            "created_at": draft.created_at, "notes": draft.notes,
            "revision": draft.revision, "state_changed_at": draft.state_changed_at,
            "state_changed_by": draft.state_changed_by,
            "lines": [{"line_no": line.line_no, "sku": line.sku,
                       "product_name": line.product_name_snapshot, "quantity": line.quantity,
                       "uom": line.uom, "canonical_uom": line.canonical_uom,
                       "factor_to_base_snapshot": line.factor_to_base_snapshot,
                       "quantity_base": line.quantity_base, "unit_price": line.unit_price,
                       "tax_rate": line.tax_rate, "net_amount": line.net_amount,
                       "tax_amount": line.tax_amount, "gross_amount": line.gross_amount,
                       "unit_cost_snapshot": line.unit_cost_snapshot,
                       "cost_amount": line.cost_amount}
                      for line in draft.lines],
        }

    @app.get("/api/v1/drafts")
    def drafts(request: Request, operational_session=Depends(operational_session_dependency)):
        user = current_user(request)
        rows = list_drafts(operational_session, allowed_locations=user.allowed_locations if user else ())
        stock_query = select(func.count(OperationalStockPosition.id))
        if user and "*" not in user.allowed_locations:
            stock_query = stock_query.where(OperationalStockPosition.location_code.in_(user.allowed_locations))
        stock_positions = operational_session.scalar(stock_query) or 0
        open_periods = operational_session.scalar(select(func.count(OperationalFiscalPeriod.id)).where(
            OperationalFiscalPeriod.status == "open",
            OperationalFiscalPeriod.rehearsal_enabled.is_(True))) or 0
        return {"items": [draft_payload(row) for row in rows], "total": len(rows),
                "posting_enabled": False, "workflow": ["draft", "submitted", "approved", "cancelled"],
                "controls": {"stock_positions": stock_positions, "open_rehearsal_periods": open_periods,
                             "permanent_journals": operational_session.scalar(select(func.count(OperationalJournalBatch.id))) or 0,
                             "subledger_entries": operational_session.scalar(select(func.count(OperationalSubledgerEntry.id))) or 0,
                             "reversal_requests": operational_session.scalar(select(func.count(OperationalReversalRequest.id))) or 0,
                             "posting_probes": operational_session.scalar(select(func.count(OperationalPostingProbe.id))) or 0,
                             "active_reservations": operational_session.scalar(select(func.count(OperationalStockReservation.id)).where(
                                 OperationalStockReservation.status == "active")) or 0}}

    @app.get("/api/v1/drafts/{draft_key}")
    def draft_detail(draft_key: str, request: Request,
                     operational_session=Depends(operational_session_dependency)):
        draft = operational_session.scalar(select(OperationalDraft).where(
            OperationalDraft.draft_key == draft_key).with_for_update())
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        if not location_allowed(current_user(request), draft.location_code):
            raise HTTPException(status_code=404, detail="Draft not found")
        return draft_payload(draft)

    @app.get("/api/v1/selectors/locations")
    def location_selector(request: Request, snapshot: SourceSnapshot = Depends(snapshot_dependency),
                          session: Session = Depends(session_dependency),
                          operational_session=Depends(optional_operational_session_dependency)):
        user = current_user(request)
        if operational_session is not None and operational_session.scalar(select(func.count(OperationalLocationMaster.id))):
            source_rows = operational_session.execute(select(
                OperationalLocationMaster.location_code.label("code"), OperationalLocationMaster.name
            ).where(OperationalLocationMaster.status == "active").order_by(OperationalLocationMaster.location_code)).all()
        else:
            source_rows = session.execute(select(ErpLocation.code, ErpLocation.name).where(
                ErpLocation.snapshot_id == snapshot.id).order_by(ErpLocation.code)).all()
        rows = [row for row in source_rows
                if user and location_allowed(user, row.code)]
        return {"items": [dict(row._mapping) for row in rows]}

    @app.get("/api/v1/selectors/parties")
    def party_selector(kind: str = Query(pattern="^(customer|supplier)$"), q: str = Query("", max_length=120),
                       snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency),
                       operational_session=Depends(optional_operational_session_dependency)):
        if operational_session is not None and operational_session.scalar(select(func.count(OperationalPartyMaster.id))):
            filters = [OperationalPartyMaster.status == "active", OperationalPartyMaster.party_kind.in_((kind, "both"))]
            if q:
                pattern = f"%{q.strip()}%"
                filters.append(or_(OperationalPartyMaster.party_code.ilike(pattern), OperationalPartyMaster.legal_or_business_name.ilike(pattern)))
            rows = [dict(row._mapping) for row in operational_session.execute(select(
                OperationalPartyMaster.party_code, OperationalPartyMaster.legal_or_business_name.label("name")
            ).where(*filters).order_by(OperationalPartyMaster.legal_or_business_name).limit(30)).all()]
            return {"items": rows}
        filters = [ErpParty.snapshot_id == snapshot.id, ErpParty.party_kind.in_((kind, "both"))]
        if q:
            pattern = f"%{q.strip()}%"
            filters.append(or_(ErpParty.party_code.ilike(pattern), ErpParty.legal_or_business_name.ilike(pattern)))
        rows = [dict(row._mapping) for row in session.execute(select(
            ErpParty.party_code, ErpParty.legal_or_business_name.label("name")
        ).where(*filters).order_by(ErpParty.legal_or_business_name).limit(30)).all()]
        if app.state.delta_overlay:
            existing = {row["party_code"] for row in rows}
            additions = [{"party_code": row["party_code"], "name": row["legal_or_business_name"]}
                         for row in app.state.delta_overlay.party_records(kind)
                         if row["party_code"] not in existing and _contains(row, q)]
            rows = (rows + additions)[:30]
        return {"items": rows}

    @app.get("/api/v1/selectors/products")
    def product_selector(q: str = Query("", max_length=120),
                         snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency),
                         operational_session=Depends(optional_operational_session_dependency)):
        if operational_session is not None and operational_session.scalar(select(func.count(OperationalProductMaster.id))):
            filters = [OperationalProductMaster.status == "active"]
            if q:
                pattern = f"%{q.strip()}%"
                filters.append(or_(OperationalProductMaster.sku.ilike(pattern), OperationalProductMaster.name.ilike(pattern)))
            rows = [dict(row._mapping) for row in operational_session.execute(select(
                OperationalProductMaster.sku, OperationalProductMaster.name,
                OperationalProductMaster.purchase_price.label("purchase_price_evidence"),
                OperationalProductMaster.selling_price.label("selling_price_evidence"),
                OperationalProductMaster.base_uom.label("uom"), OperationalProductMaster.canonical_base_uom,
                OperationalProductMaster.factor_to_base.label("factor_to_base_snapshot"),
            ).where(*filters).order_by(OperationalProductMaster.name).limit(30)).all()]
            for row in rows:
                row["conversion_status"] = "operational"
            return {"items": rows}
        filters = [ErpProductMaster.snapshot_id == snapshot.id]
        if q:
            pattern = f"%{q.strip()}%"
            filters.append(or_(ErpProductMaster.sku.ilike(pattern), ErpProductMaster.name.ilike(pattern)))
        rows = [dict(row._mapping) for row in session.execute(select(
            ErpProductMaster.sku, ErpProductMaster.name,
            ErpProductMaster.purchase_price_evidence, ErpProductMaster.selling_price_evidence,
            ErpProductUom.source_base_uom.label("uom"), ErpProductUom.canonical_base_uom,
            ErpProductUom.factor_to_base_snapshot, ErpProductUom.conversion_status,
        ).outerjoin(ErpProductUom, ErpProductUom.product_id == ErpProductMaster.id).where(
            *filters).order_by(ErpProductMaster.name).limit(30)).all()]
        if app.state.delta_overlay:
            existing = {row["sku"] for row in rows}
            additions = [{"sku": row["sku"], "name": row["name"],
                          "purchase_price_evidence": row["purchase_price_evidence"],
                          "selling_price_evidence": row["selling_price_evidence"],
                          "uom": row["base_uom"], "canonical_base_uom": row["base_uom"].casefold(),
                          "factor_to_base_snapshot": 1, "conversion_status": "provisional"}
                         for row in app.state.delta_overlay.product_records()
                         if row["sku"] not in existing and _contains(row, q)]
            rows = (rows + additions)[:30]
        return {"items": rows}

    @app.get("/api/v1/selectors/sales-invoices")
    def sales_invoice_selector(customer_code: str = Query(min_length=1, max_length=80),
                               snapshot: SourceSnapshot = Depends(snapshot_dependency),
                               session: Session = Depends(session_dependency)):
        rows = session.execute(select(ErpTransactionDocument.document_no,
                                      ErpTransactionDocument.occurred_at,
                                      ErpTransactionDocument.total_amount).join(
            ErpParty, ErpParty.id == ErpTransactionDocument.party_id).where(
            ErpTransactionDocument.snapshot_id == snapshot.id,
            ErpTransactionDocument.source_kind == "sale",
            ErpParty.party_code == customer_code).order_by(
            ErpTransactionDocument.occurred_at.desc()).limit(30)).all()
        return {"items": [dict(row._mapping) for row in rows]}

    @app.get("/api/v1/selectors/purchase-invoices")
    def purchase_invoice_selector(supplier_code: str = Query(min_length=1, max_length=80),
                                  snapshot: SourceSnapshot = Depends(snapshot_dependency),
                                  session: Session = Depends(session_dependency)):
        rows = session.execute(select(ErpTransactionDocument.document_no,
                                      ErpTransactionDocument.occurred_at,
                                      ErpTransactionDocument.total_amount).join(
            ErpParty, ErpParty.id == ErpTransactionDocument.party_id).where(
            ErpTransactionDocument.snapshot_id == snapshot.id,
            ErpTransactionDocument.source_kind == "purchase",
            ErpParty.party_code == supplier_code).order_by(
            ErpTransactionDocument.occurred_at.desc()).limit(30)).all()
        return {"items": [dict(row._mapping) for row in rows]}

    def require_csrf(request: Request, permission: str):
        current = active_session(request)
        if not app.state.auth_enabled or not current:
            raise HTTPException(status_code=401, detail="Authentication required")
        if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), current.csrf_token):
            raise HTTPException(status_code=403, detail="CSRF validation failed")
        user = current_user(request)
        if not user or permission not in user.permissions:
            raise HTTPException(status_code=403, detail=f"Permission {permission} is required")
        return user

    def operational_masters_present(operational_session: Session, model) -> bool:
        return bool(operational_session.scalar(select(func.count(model.id))))

    def prepare_draft(payload: DraftRequest, session: Session, operational_session: Session, user):
        snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == selected_snapshot))
        if operational_masters_present(operational_session, OperationalLocationMaster):
            location_record = operational_session.scalar(select(OperationalLocationMaster).where(or_(
                func.lower(OperationalLocationMaster.location_code) == payload.location_code.casefold(),
                func.lower(OperationalLocationMaster.name) == payload.location_code.casefold())))
            if location_record and location_record.status != "active":
                raise HTTPException(status_code=422, detail="Location is inactive in the operational master")
            location = ((location_record.location_code, location_record.name) if location_record else None)
        else:
            location = session.execute(select(ErpLocation.code, ErpLocation.name).where(
                ErpLocation.snapshot_id == snapshot.id,
                or_(func.lower(ErpLocation.code) == payload.location_code.casefold(),
                    func.lower(ErpLocation.name) == payload.location_code.casefold()))).first()
        if not location:
            raise HTTPException(status_code=422, detail="Location is not present in the operational master")
        if not location_allowed(user, location[0]):
            raise HTTPException(status_code=403, detail="Location is outside the user's operational scope")
        expected_kind = "customer" if payload.document_type == "sale" else "supplier"
        if operational_masters_present(operational_session, OperationalPartyMaster):
            party_record = operational_session.scalar(select(OperationalPartyMaster).where(
                OperationalPartyMaster.party_code == payload.party_code,
                OperationalPartyMaster.party_kind.in_((expected_kind, "both"))))
            if party_record and party_record.status != "active":
                raise HTTPException(status_code=422, detail=f"{expected_kind.title()} is inactive in the operational master")
            party = ((party_record.party_code, party_record.legal_or_business_name) if party_record else None)
        else:
            party = session.execute(select(ErpParty.party_code, ErpParty.legal_or_business_name).where(
                ErpParty.snapshot_id == snapshot.id, ErpParty.party_code == payload.party_code,
                ErpParty.party_kind.in_((expected_kind, "both")))).first()
        if not party and not operational_masters_present(operational_session, OperationalPartyMaster) and app.state.delta_overlay:
            party = next(((row["party_code"], row["legal_or_business_name"])
                          for row in app.state.delta_overlay.party_records(expected_kind)
                          if row["party_code"] == payload.party_code), None)
        if not party:
            raise HTTPException(status_code=422, detail=f"{expected_kind.title()} is not present in the cloned master")
        prepared_lines = []
        for item in payload.lines:
            if operational_masters_present(operational_session, OperationalProductMaster):
                product_record = operational_session.scalar(select(OperationalProductMaster).where(
                    OperationalProductMaster.sku == item.sku))
                if product_record and product_record.status != "active":
                    raise HTTPException(status_code=422, detail=f"Product SKU {item.sku} is inactive in the operational master")
                product = ((product_record.sku, product_record.name, product_record.purchase_price,
                            product_record.selling_price, product_record.base_uom,
                            product_record.canonical_base_uom, product_record.factor_to_base,
                            "operational") if product_record else None)
            else:
                product = session.execute(select(
                    ErpProductMaster.sku, ErpProductMaster.name,
                    ErpProductMaster.purchase_price_evidence, ErpProductMaster.selling_price_evidence,
                    ErpProductUom.source_base_uom, ErpProductUom.canonical_base_uom,
                    ErpProductUom.factor_to_base_snapshot, ErpProductUom.conversion_status,
                ).outerjoin(ErpProductUom, ErpProductUom.product_id == ErpProductMaster.id).where(
                    ErpProductMaster.snapshot_id == snapshot.id, ErpProductMaster.sku == item.sku)).first()
            if not product and not operational_masters_present(operational_session, OperationalProductMaster) and app.state.delta_overlay:
                overlay_product = next((row for row in app.state.delta_overlay.product_records()
                                        if row["sku"] == item.sku), None)
                if overlay_product:
                    product = (overlay_product["sku"], overlay_product["name"],
                               overlay_product["purchase_price_evidence"], overlay_product["selling_price_evidence"],
                               overlay_product["base_uom"], overlay_product["base_uom"].casefold(), Decimal("1"), "provisional")
            if not product:
                raise HTTPException(status_code=422, detail=f"Product SKU {item.sku} is not present in the cloned master")
            source_uom, canonical_uom = str(product[4] or ""), str(product[5] or "")
            if product[7] == "unobserved" or item.uom.casefold() not in {source_uom.casefold(), canonical_uom.casefold()}:
                raise HTTPException(status_code=422, detail=f"UOM {item.uom} is not an approved base-unit mapping for SKU {item.sku}")
            factor = Decimal(str(product[6]))
            default_price = product[3] if payload.document_type == "sale" else product[2]
            price = item.unit_price if item.unit_price is not None else Decimal(str(default_price or "0"))
            net, tax, gross = calculate_line(item.quantity, price, item.tax_rate)
            unit_cost = Decimal(str(product[2])) if product[2] is not None else None
            cost_amount = ((item.quantity * factor * unit_cost).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP)
                           if unit_cost is not None else None)
            prepared_lines.append({"sku": item.sku, "product_name_snapshot": product[1],
                                   "quantity": item.quantity, "uom": item.uom,
                                   "canonical_uom": canonical_uom, "factor_to_base_snapshot": factor,
                                   "quantity_base": item.quantity * factor,
                                   "unit_price": price, "tax_rate": item.tax_rate,
                                   "net_amount": net, "tax_amount": tax, "gross_amount": gross,
                                   "unit_cost_snapshot": unit_cost, "cost_amount": cost_amount})
        return location, party, prepared_lines

    @app.post("/api/v1/drafts", status_code=201)
    def new_draft(payload: DraftRequest, request: Request,
                  session: Session = Depends(session_dependency),
                  operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "draft.create")
        location, party, prepared_lines = prepare_draft(payload, session, operational_session, user)
        try:
            draft = create_draft(
                operational_session, document_type=payload.document_type,
                party_code=payload.party_code, party_name=party[1], location_code=location[0],
                discount_amount=payload.discount_amount, notes=payload.notes,
                actor=user.username, lines=prepared_lines,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return draft_payload(draft)

    @app.put("/api/v1/drafts/{draft_key}")
    def edit_draft(draft_key: str, payload: DraftUpdateRequest, request: Request,
                   session: Session = Depends(session_dependency),
                   operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "draft.edit")
        draft = operational_session.scalar(select(OperationalDraft).where(
            OperationalDraft.draft_key == draft_key).with_for_update())
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        if draft.document_type != payload.document_type:
            raise HTTPException(status_code=422, detail="Draft document type cannot be changed")
        location, party, lines = prepare_draft(payload, session, operational_session, user)
        try:
            return draft_payload(replace_draft(
                operational_session, draft, expected_revision=payload.expected_revision,
                party_code=payload.party_code, party_name=party[1], location_code=location[0],
                discount_amount=payload.discount_amount, notes=payload.notes,
                actor=user.username, lines=lines,
            ))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def workflow_action(draft_key: str, action: str, payload: DraftTransitionRequest,
                        request: Request, operational_session):
        permission = {"submit": "draft.submit", "cancel": "draft.cancel", "approve": "draft.approve"}[action]
        user = require_csrf(request, permission)
        draft = operational_session.scalar(select(OperationalDraft).where(
            OperationalDraft.draft_key == draft_key).with_for_update())
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        if not location_allowed(user, draft.location_code):
            raise HTTPException(status_code=404, detail="Draft not found")
        try:
            return draft_payload(transition_draft(
                operational_session, draft, expected_revision=payload.expected_revision,
                action=action, actor=user.username, note=payload.note,
            ))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/drafts/{draft_key}/submit")
    def submit_draft(draft_key: str, payload: DraftTransitionRequest, request: Request,
                     operational_session=Depends(operational_session_dependency)):
        return workflow_action(draft_key, "submit", payload, request, operational_session)

    @app.post("/api/v1/drafts/{draft_key}/cancel")
    def cancel_draft(draft_key: str, payload: DraftTransitionRequest, request: Request,
                     operational_session=Depends(operational_session_dependency)):
        return workflow_action(draft_key, "cancel", payload, request, operational_session)

    @app.post("/api/v1/drafts/{draft_key}/approve")
    def approve_draft(draft_key: str, payload: DraftTransitionRequest, request: Request,
                      operational_session=Depends(operational_session_dependency)):
        return workflow_action(draft_key, "approve", payload, request, operational_session)

    @app.post("/api/v1/drafts/{draft_key}/posting-rehearsal")
    def posting_rehearsal(draft_key: str, request: Request,
                          operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "posting.rehearse")
        draft = operational_session.scalar(select(OperationalDraft).where(
            OperationalDraft.draft_key == draft_key).with_for_update())
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        if not location_allowed(user, draft.location_code):
            raise HTTPException(status_code=404, detail="Draft not found")
        try:
            return rehearse_posting(operational_session, draft, actor=user.username)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/drafts/{draft_key}/post")
    def post_draft(draft_key: str, payload: PostingExecutionRequest, request: Request,
                   operational_session=Depends(operational_session_dependency)):
        if not app.state.posting_enabled:
            raise HTTPException(status_code=503, detail="Permanent posting activation is disabled")
        user = require_csrf(request, "posting.execute")
        draft = operational_session.scalar(select(OperationalDraft).where(
            OperationalDraft.draft_key == draft_key).with_for_update())
        if not draft or not location_allowed(user, draft.location_code):
            raise HTTPException(status_code=404, detail="Draft not found")
        try:
            return execute_posting(operational_session, draft, actor=user.username,
                                   idempotency_key=payload.idempotency_key)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/journal-batches/{batch_key}/reverse")
    def reverse_batch(batch_key: str, payload: ReversalExecutionRequest, request: Request,
                      operational_session=Depends(operational_session_dependency)):
        if not app.state.posting_enabled:
            raise HTTPException(status_code=503, detail="Permanent posting activation is disabled")
        user = require_csrf(request, "posting.reverse")
        batch = operational_session.scalar(select(OperationalJournalBatch).where(
            OperationalJournalBatch.batch_key == batch_key).with_for_update())
        if not batch:
            raise HTTPException(status_code=404, detail="Journal batch not found")
        draft = operational_session.scalar(select(OperationalDraft).where(
            OperationalDraft.draft_key == batch.draft_key))
        if not draft or not location_allowed(user, draft.location_code):
            raise HTTPException(status_code=404, detail="Journal batch not found")
        try:
            return execute_reversal(operational_session, batch, actor=user.username,
                                    reason=payload.reason)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def inventory_document_payload(document: OperationalInventoryDocument) -> dict:
        return {
            "document_key": document.document_key, "document_no": document.document_no,
            "document_type": document.document_type, "location_code": document.location_code,
            "destination_location_code": document.destination_location_code,
            "adjustment_direction": document.adjustment_direction,
            "reason_code": document.reason_code, "status": document.status,
            "posting_enabled": document.posting_enabled, "notes": document.notes,
            "created_by": document.created_by, "created_at": document.created_at,
            "revision": document.revision, "state_changed_at": document.state_changed_at,
            "state_changed_by": document.state_changed_by,
            "lines": [{"line_no": line.line_no, "sku": line.sku,
                       "product_name": line.product_name_snapshot, "quantity": line.quantity,
                       "uom": line.uom, "canonical_uom": line.canonical_uom,
                       "factor_to_base_snapshot": line.factor_to_base_snapshot,
                       "quantity_base": line.quantity_base,
                       "unit_cost_snapshot": line.unit_cost_snapshot,
                       "value_snapshot": line.value_snapshot} for line in document.lines],
        }

    def prepare_inventory_document(payload: InventoryDocumentRequest, clone_session: Session,
                                   operational_session: Session, user) -> list[dict]:
        snapshot = clone_session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == selected_snapshot))
        if not snapshot:
            raise HTTPException(status_code=404, detail="Configured BizModo clone snapshot is unavailable")
        requested_locations = [payload.location_code]
        if payload.destination_location_code:
            requested_locations.append(payload.destination_location_code)
        if operational_masters_present(operational_session, OperationalLocationMaster):
            locations = set(operational_session.scalars(select(OperationalLocationMaster.location_code).where(
                OperationalLocationMaster.location_code.in_(requested_locations),
                OperationalLocationMaster.status == "active")))
        else:
            locations = set(clone_session.scalars(select(ErpLocation.code).where(
                ErpLocation.snapshot_id == snapshot.id,
                ErpLocation.code.in_(requested_locations),
            )))
        if locations != set(requested_locations):
            raise HTTPException(status_code=422, detail="Every inventory location must be active in the operational master")
        if any(not location_allowed(user, code) for code in requested_locations):
            raise HTTPException(status_code=403, detail="Inventory location is outside the user's operational scope")
        prepared: list[dict] = []
        for item in payload.lines:
            if operational_masters_present(operational_session, OperationalProductMaster):
                master = operational_session.scalar(select(OperationalProductMaster).where(
                    OperationalProductMaster.sku == item.sku, OperationalProductMaster.status == "active"))
                product = ((master.sku, master.name, master.purchase_price, master.base_uom,
                            master.canonical_base_uom, master.factor_to_base, "operational") if master else None)
            else:
                product = clone_session.execute(select(
                    ErpProductMaster.sku, ErpProductMaster.name, ErpProductMaster.purchase_price_evidence,
                    ErpProductUom.source_base_uom, ErpProductUom.canonical_base_uom,
                    ErpProductUom.factor_to_base_snapshot, ErpProductUom.conversion_status,
                ).outerjoin(ErpProductUom, ErpProductUom.product_id == ErpProductMaster.id).where(
                    ErpProductMaster.snapshot_id == snapshot.id, ErpProductMaster.sku == item.sku,
                )).first()
            if not product:
                raise HTTPException(status_code=422, detail=f"Product SKU {item.sku} is not active in the operational master")
            source_uom, canonical_uom = str(product[3] or ""), str(product[4] or "")
            if product[6] == "unobserved" or item.uom.casefold() not in {source_uom.casefold(), canonical_uom.casefold()}:
                raise HTTPException(status_code=422, detail=f"UOM {item.uom} is not an approved base-unit mapping for SKU {item.sku}")
            position = operational_session.scalar(select(OperationalStockPosition).where(
                OperationalStockPosition.location_code == payload.location_code,
                OperationalStockPosition.sku == item.sku,
            ))
            cost = item.unit_cost
            if cost is None and position is not None:
                cost = Decimal(str(position.average_unit_cost))
            if cost is None and product[2] is not None:
                cost = Decimal(str(product[2]))
            if cost is None:
                raise HTTPException(status_code=422, detail=f"Cost basis is unavailable for SKU {item.sku}")
            prepared.append({
                "sku": item.sku, "product_name_snapshot": product[1], "quantity": item.quantity,
                "uom": item.uom, "canonical_uom": canonical_uom,
                "factor_to_base_snapshot": Decimal(str(product[5])), "unit_cost_snapshot": cost,
            })
        return prepared

    @app.get("/api/v1/inventory-documents")
    def inventory_documents(request: Request,
                            operational_session=Depends(operational_session_dependency)):
        user = current_user(request)
        rows = list_inventory_documents(
            operational_session, allowed_locations=user.allowed_locations if user else (),
        )
        return {"items": [inventory_document_payload(row) for row in rows], "total": len(rows),
                "posting_enabled": False, "controls": inventory_control_counts(operational_session)}

    @app.get("/api/v1/inventory-documents/{document_key}")
    def inventory_document_detail(document_key: str, request: Request,
                                  operational_session=Depends(operational_session_dependency)):
        document = operational_session.scalar(select(OperationalInventoryDocument).where(
            OperationalInventoryDocument.document_key == document_key))
        user = current_user(request)
        if (not document or not user or not location_allowed(user, document.location_code)
                or (document.destination_location_code
                    and not location_allowed(user, document.destination_location_code))):
            raise HTTPException(status_code=404, detail="Inventory document not found")
        return inventory_document_payload(document)

    @app.post("/api/v1/inventory-documents", status_code=201)
    def new_inventory_document(payload: InventoryDocumentRequest, request: Request,
                               clone_session: Session = Depends(session_dependency),
                               operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "inventory.create")
        lines = prepare_inventory_document(payload, clone_session, operational_session, user)
        try:
            document = create_inventory_document(
                operational_session, document_type=payload.document_type,
                location_code=payload.location_code,
                destination_location_code=payload.destination_location_code,
                adjustment_direction=payload.adjustment_direction,
                reason_code=payload.reason_code, notes=payload.notes,
                actor=user.username, lines=lines,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return inventory_document_payload(document)

    @app.put("/api/v1/inventory-documents/{document_key}")
    def edit_inventory_document(document_key: str, payload: InventoryDocumentRequest,
                                request: Request, expected_revision: int = Query(ge=1),
                                clone_session: Session = Depends(session_dependency),
                                operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "inventory.edit")
        document = operational_session.scalar(select(OperationalInventoryDocument).where(
            OperationalInventoryDocument.document_key == document_key).with_for_update())
        if (not document or not location_allowed(user, document.location_code)
                or (document.destination_location_code
                    and not location_allowed(user, document.destination_location_code))):
            raise HTTPException(status_code=404, detail="Inventory document not found")
        lines = prepare_inventory_document(payload, clone_session, operational_session, user)
        try:
            return inventory_document_payload(replace_inventory_document(
                operational_session, document, expected_revision=expected_revision,
                document_type=payload.document_type, location_code=payload.location_code,
                destination_location_code=payload.destination_location_code,
                adjustment_direction=payload.adjustment_direction,
                reason_code=payload.reason_code, notes=payload.notes,
                actor=user.username, lines=lines,
            ))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def inventory_workflow_action(document_key: str, action: str,
                                  payload: DraftTransitionRequest, request: Request,
                                  operational_session: Session):
        permission = {"submit": "inventory.submit", "cancel": "inventory.cancel",
                      "approve": "inventory.approve"}[action]
        user = require_csrf(request, permission)
        document = operational_session.scalar(select(OperationalInventoryDocument).where(
            OperationalInventoryDocument.document_key == document_key).with_for_update())
        if (not document or not location_allowed(user, document.location_code)
                or (document.destination_location_code
                    and not location_allowed(user, document.destination_location_code))):
            raise HTTPException(status_code=404, detail="Inventory document not found")
        try:
            return inventory_document_payload(transition_inventory_document(
                operational_session, document, expected_revision=payload.expected_revision,
                action=action, actor=user.username, note=payload.note,
            ))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/inventory-documents/{document_key}/submit")
    def submit_inventory_document(document_key: str, payload: DraftTransitionRequest,
                                  request: Request,
                                  operational_session=Depends(operational_session_dependency)):
        return inventory_workflow_action(document_key, "submit", payload, request, operational_session)

    @app.post("/api/v1/inventory-documents/{document_key}/cancel")
    def cancel_inventory_document(document_key: str, payload: DraftTransitionRequest,
                                  request: Request,
                                  operational_session=Depends(operational_session_dependency)):
        return inventory_workflow_action(document_key, "cancel", payload, request, operational_session)

    @app.post("/api/v1/inventory-documents/{document_key}/approve")
    def approve_inventory_document(document_key: str, payload: DraftTransitionRequest,
                                   request: Request,
                                   operational_session=Depends(operational_session_dependency)):
        return inventory_workflow_action(document_key, "approve", payload, request, operational_session)

    @app.post("/api/v1/inventory-documents/{document_key}/posting-rehearsal")
    def inventory_posting_rehearsal(document_key: str, request: Request,
                                    operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "inventory.rehearse")
        document = operational_session.scalar(select(OperationalInventoryDocument).where(
            OperationalInventoryDocument.document_key == document_key).with_for_update())
        if (not document or not location_allowed(user, document.location_code)
                or (document.destination_location_code
                    and not location_allowed(user, document.destination_location_code))):
            raise HTTPException(status_code=404, detail="Inventory document not found")
        try:
            return rehearse_inventory_posting(operational_session, document, actor=user.username)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def goods_receipt_payload(receipt: OperationalGoodsReceipt) -> dict:
        return {
            "receipt_key": receipt.receipt_key, "receipt_no": receipt.receipt_no,
            "supplier_code": receipt.supplier_code, "supplier_name": receipt.supplier_name_snapshot,
            "location_code": receipt.location_code, "purchase_reference": receipt.purchase_reference,
            "supplier_delivery_note": receipt.supplier_delivery_note, "received_on": receipt.received_on,
            "status": receipt.status, "posting_enabled": receipt.posting_enabled,
            "notes": receipt.notes, "created_by": receipt.created_by, "created_at": receipt.created_at,
            "revision": receipt.revision, "state_changed_at": receipt.state_changed_at,
            "state_changed_by": receipt.state_changed_by,
            "lines": [{"line_no": line.line_no, "sku": line.sku,
                       "product_name": line.product_name_snapshot,
                       "ordered_quantity": line.ordered_quantity,
                       "received_quantity": line.received_quantity,
                       "accepted_quantity": line.accepted_quantity,
                       "rejected_quantity": line.rejected_quantity, "uom": line.uom,
                       "canonical_uom": line.canonical_uom,
                       "factor_to_base_snapshot": line.factor_to_base_snapshot,
                       "accepted_quantity_base": line.accepted_quantity_base,
                       "unit_cost_snapshot": line.unit_cost_snapshot,
                       "accepted_value": line.accepted_value, "batch_no": line.batch_no,
                       "expiry_date": line.expiry_date,
                       "rejection_reason": line.rejection_reason} for line in receipt.lines],
        }

    def prepare_goods_receipt(payload: GoodsReceiptRequest, clone_session: Session,
                              operational_session: Session, user) -> tuple[str, list[dict]]:
        snapshot = clone_session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == selected_snapshot))
        if not snapshot:
            raise HTTPException(status_code=404, detail="Configured BizModo clone snapshot is unavailable")
        if not location_allowed(user, payload.location_code):
            raise HTTPException(status_code=403, detail="Receipt location is outside the user's operational scope")
        if operational_masters_present(operational_session, OperationalLocationMaster):
            location_exists = operational_session.scalar(select(OperationalLocationMaster.id).where(
                OperationalLocationMaster.location_code == payload.location_code,
                OperationalLocationMaster.status == "active"))
        else:
            location_exists = clone_session.scalar(select(ErpLocation.id).where(
                ErpLocation.snapshot_id == snapshot.id, ErpLocation.code == payload.location_code))
        if not location_exists:
            raise HTTPException(status_code=422, detail="Receipt location is not active in the operational master")
        if operational_masters_present(operational_session, OperationalPartyMaster):
            supplier_record = operational_session.scalar(select(OperationalPartyMaster).where(
                OperationalPartyMaster.party_code == payload.supplier_code,
                OperationalPartyMaster.party_kind.in_(("supplier", "both")),
                OperationalPartyMaster.status == "active"))
            supplier = ((supplier_record.legal_or_business_name, supplier_record.party_kind)
                        if supplier_record else None)
        else:
            supplier = clone_session.execute(select(ErpParty.legal_or_business_name, ErpParty.party_kind).where(
                ErpParty.snapshot_id == snapshot.id, ErpParty.party_code == payload.supplier_code)).first()
        if not supplier or supplier[1] not in {"supplier", "both"}:
            raise HTTPException(status_code=422, detail="Supplier is not active in the operational supplier master")
        prepared: list[dict] = []
        for item in payload.lines:
            if operational_masters_present(operational_session, OperationalProductMaster):
                master = operational_session.scalar(select(OperationalProductMaster).where(
                    OperationalProductMaster.sku == item.sku, OperationalProductMaster.status == "active"))
                product = ((master.name, master.purchase_price, master.base_uom,
                            master.canonical_base_uom, master.factor_to_base, "operational") if master else None)
            else:
                product = clone_session.execute(select(
                    ErpProductMaster.name, ErpProductMaster.purchase_price_evidence,
                    ErpProductUom.source_base_uom, ErpProductUom.canonical_base_uom,
                    ErpProductUom.factor_to_base_snapshot, ErpProductUom.conversion_status,
                ).outerjoin(ErpProductUom, ErpProductUom.product_id == ErpProductMaster.id).where(
                    ErpProductMaster.snapshot_id == snapshot.id, ErpProductMaster.sku == item.sku)).first()
            if not product:
                raise HTTPException(status_code=422, detail=f"Product SKU {item.sku} is not active in the operational master")
            source_uom, canonical_uom = str(product[2] or ""), str(product[3] or "")
            if product[5] == "unobserved" or item.uom.casefold() not in {source_uom.casefold(), canonical_uom.casefold()}:
                raise HTTPException(status_code=422, detail=f"UOM {item.uom} is not an approved base-unit mapping for SKU {item.sku}")
            cost = item.unit_cost if item.unit_cost is not None else product[1]
            if cost is None:
                raise HTTPException(status_code=422, detail=f"Cost basis is unavailable for SKU {item.sku}")
            prepared.append({
                "sku": item.sku, "product_name_snapshot": product[0],
                "ordered_quantity": item.ordered_quantity, "received_quantity": item.received_quantity,
                "accepted_quantity": item.accepted_quantity, "rejected_quantity": item.rejected_quantity,
                "uom": item.uom, "canonical_uom": canonical_uom,
                "factor_to_base_snapshot": Decimal(str(product[4])),
                "unit_cost_snapshot": cost, "batch_no": item.batch_no,
                "expiry_date": item.expiry_date, "rejection_reason": item.rejection_reason,
            })
        return supplier[0], prepared

    @app.get("/api/v1/goods-receipts")
    def goods_receipts(request: Request, operational_session=Depends(operational_session_dependency)):
        user = current_user(request)
        rows = list_goods_receipts(operational_session, allowed_locations=user.allowed_locations if user else ())
        return {"items": [goods_receipt_payload(row) for row in rows], "total": len(rows),
                "posting_enabled": False, "controls": goods_receipt_control_counts(operational_session)}

    @app.get("/api/v1/goods-receipts/{receipt_key}")
    def goods_receipt_detail(receipt_key: str, request: Request,
                             operational_session=Depends(operational_session_dependency)):
        receipt = operational_session.scalar(select(OperationalGoodsReceipt).where(
            OperationalGoodsReceipt.receipt_key == receipt_key))
        user = current_user(request)
        if not receipt or not user or not location_allowed(user, receipt.location_code):
            raise HTTPException(status_code=404, detail="Goods receipt not found")
        return goods_receipt_payload(receipt)

    @app.post("/api/v1/goods-receipts", status_code=201)
    def new_goods_receipt(payload: GoodsReceiptRequest, request: Request,
                          clone_session: Session = Depends(session_dependency),
                          operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "goods_receipt.create")
        supplier_name, lines = prepare_goods_receipt(payload, clone_session, operational_session, user)
        try:
            receipt = create_goods_receipt(
                operational_session, supplier_code=payload.supplier_code,
                supplier_name_snapshot=supplier_name, location_code=payload.location_code,
                purchase_reference=payload.purchase_reference,
                supplier_delivery_note=payload.supplier_delivery_note, received_on=payload.received_on,
                notes=payload.notes, actor=user.username, lines=lines)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return goods_receipt_payload(receipt)

    @app.put("/api/v1/goods-receipts/{receipt_key}")
    def edit_goods_receipt(receipt_key: str, payload: GoodsReceiptRequest, request: Request,
                           expected_revision: int = Query(ge=1),
                           clone_session: Session = Depends(session_dependency),
                           operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "goods_receipt.edit")
        receipt = operational_session.scalar(select(OperationalGoodsReceipt).where(
            OperationalGoodsReceipt.receipt_key == receipt_key).with_for_update())
        if not receipt or not location_allowed(user, receipt.location_code):
            raise HTTPException(status_code=404, detail="Goods receipt not found")
        supplier_name, lines = prepare_goods_receipt(payload, clone_session, operational_session, user)
        try:
            receipt = replace_goods_receipt(
                operational_session, receipt, expected_revision=expected_revision,
                supplier_code=payload.supplier_code, supplier_name_snapshot=supplier_name,
                location_code=payload.location_code, purchase_reference=payload.purchase_reference,
                supplier_delivery_note=payload.supplier_delivery_note, received_on=payload.received_on,
                notes=payload.notes, actor=user.username, lines=lines)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return goods_receipt_payload(receipt)

    def goods_receipt_action(receipt_key: str, action: str, payload: DraftTransitionRequest,
                             request: Request, operational_session: Session):
        permission = {"submit": "goods_receipt.submit", "cancel": "goods_receipt.cancel",
                      "accept": "goods_receipt.accept", "reject": "goods_receipt.reject"}[action]
        user = require_csrf(request, permission)
        receipt = operational_session.scalar(select(OperationalGoodsReceipt).where(
            OperationalGoodsReceipt.receipt_key == receipt_key).with_for_update())
        if not receipt or not location_allowed(user, receipt.location_code):
            raise HTTPException(status_code=404, detail="Goods receipt not found")
        try:
            return goods_receipt_payload(transition_goods_receipt(
                operational_session, receipt, expected_revision=payload.expected_revision,
                action=action, actor=user.username, note=payload.note))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/goods-receipts/{receipt_key}/submit")
    def submit_goods_receipt(receipt_key: str, payload: DraftTransitionRequest, request: Request,
                             operational_session=Depends(operational_session_dependency)):
        return goods_receipt_action(receipt_key, "submit", payload, request, operational_session)

    @app.post("/api/v1/goods-receipts/{receipt_key}/cancel")
    def cancel_goods_receipt(receipt_key: str, payload: DraftTransitionRequest, request: Request,
                             operational_session=Depends(operational_session_dependency)):
        return goods_receipt_action(receipt_key, "cancel", payload, request, operational_session)

    @app.post("/api/v1/goods-receipts/{receipt_key}/accept")
    def accept_goods_receipt(receipt_key: str, payload: DraftTransitionRequest, request: Request,
                             operational_session=Depends(operational_session_dependency)):
        return goods_receipt_action(receipt_key, "accept", payload, request, operational_session)

    @app.post("/api/v1/goods-receipts/{receipt_key}/reject")
    def reject_goods_receipt(receipt_key: str, payload: DraftTransitionRequest, request: Request,
                             operational_session=Depends(operational_session_dependency)):
        return goods_receipt_action(receipt_key, "reject", payload, request, operational_session)

    @app.post("/api/v1/goods-receipts/{receipt_key}/posting-rehearsal")
    def goods_receipt_posting_rehearsal(receipt_key: str, request: Request,
                                        operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "goods_receipt.rehearse")
        receipt = operational_session.scalar(select(OperationalGoodsReceipt).where(
            OperationalGoodsReceipt.receipt_key == receipt_key).with_for_update())
        if not receipt or not location_allowed(user, receipt.location_code):
            raise HTTPException(status_code=404, detail="Goods receipt not found")
        try:
            return rehearse_goods_receipt_posting(operational_session, receipt, actor=user.username)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def sales_return_payload(document: OperationalSalesReturn) -> dict:
        return {"return_key": document.return_key, "return_no": document.return_no,
                "customer_code": document.customer_code, "customer_name": document.customer_name_snapshot,
                "location_code": document.location_code,
                "original_invoice_reference": document.original_invoice_reference,
                "return_date": document.return_date, "reason_code": document.reason_code,
                "currency_code": document.currency_code, "subtotal": document.subtotal,
                "tax_amount": document.tax_amount, "total_amount": document.total_amount,
                "status": document.status, "posting_enabled": document.posting_enabled,
                "notes": document.notes, "created_by": document.created_by, "created_at": document.created_at,
                "revision": document.revision, "state_changed_at": document.state_changed_at,
                "state_changed_by": document.state_changed_by,
                "credit_note": ({"credit_note_key": document.credit_note.credit_note_key,
                                 "credit_note_no": document.credit_note.credit_note_no,
                                 "status": document.credit_note.status,
                                 "posting_enabled": document.credit_note.posting_enabled,
                                 "total_amount": document.credit_note.total_amount}
                                if document.credit_note else None),
                "lines": [{"line_no": line.line_no, "sku": line.sku,
                           "product_name": line.product_name_snapshot, "quantity": line.quantity,
                           "restock_quantity": line.restock_quantity,
                           "writeoff_quantity": line.writeoff_quantity, "uom": line.uom,
                           "canonical_uom": line.canonical_uom,
                           "factor_to_base_snapshot": line.factor_to_base_snapshot,
                           "quantity_base": line.quantity_base, "unit_price": line.unit_price,
                           "tax_rate": line.tax_rate, "net_amount": line.net_amount,
                           "tax_amount": line.tax_amount, "gross_amount": line.gross_amount,
                           "unit_cost_snapshot": line.unit_cost_snapshot,
                           "disposition_reason": line.disposition_reason} for line in document.lines]}

    def prepare_sales_return(payload: SalesReturnRequest, clone_session: Session,
                             operational_session: Session, user) -> tuple[str, list[dict]]:
        snapshot = clone_session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == selected_snapshot))
        if not snapshot:
            raise HTTPException(status_code=404, detail="Configured BizModo clone snapshot is unavailable")
        if not location_allowed(user, payload.location_code):
            raise HTTPException(status_code=403, detail="Return location is outside the user's operational scope")
        if operational_masters_present(operational_session, OperationalLocationMaster):
            location_exists = operational_session.scalar(select(OperationalLocationMaster.id).where(
                OperationalLocationMaster.location_code == payload.location_code,
                OperationalLocationMaster.status == "active"))
        else:
            location_exists = clone_session.scalar(select(ErpLocation.id).where(
                ErpLocation.snapshot_id == snapshot.id, ErpLocation.code == payload.location_code))
        if not location_exists:
            raise HTTPException(status_code=422, detail="Return location is not active in the operational master")
        operational_customer = None
        if operational_masters_present(operational_session, OperationalPartyMaster):
            operational_customer = operational_session.scalar(select(OperationalPartyMaster).where(
                OperationalPartyMaster.party_code == payload.customer_code,
                OperationalPartyMaster.party_kind.in_(("customer", "both")),
                OperationalPartyMaster.status == "active"))
            if not operational_customer:
                raise HTTPException(status_code=422, detail="Customer is not active in the operational customer master")
        customer = clone_session.execute(select(ErpParty.id, ErpParty.legal_or_business_name).where(
            ErpParty.snapshot_id == snapshot.id, ErpParty.party_code == payload.customer_code,
            ErpParty.party_kind.in_(("customer", "both")))).first()
        if not customer:
            raise HTTPException(status_code=422, detail="Customer is not present in the cloned customer master")
        invoice = clone_session.scalar(select(ErpTransactionDocument.id).where(
            ErpTransactionDocument.snapshot_id == snapshot.id,
            ErpTransactionDocument.source_kind == "sale",
            ErpTransactionDocument.document_no == payload.original_invoice_reference,
            ErpTransactionDocument.party_id == customer.id))
        if not invoice:
            raise HTTPException(status_code=422, detail="Original invoice was not found for the selected customer in the cloned sales register")
        prepared: list[dict] = []
        for item in payload.lines:
            if operational_masters_present(operational_session, OperationalProductMaster):
                master = operational_session.scalar(select(OperationalProductMaster).where(
                    OperationalProductMaster.sku == item.sku, OperationalProductMaster.status == "active"))
                product = ((master.name, master.purchase_price, master.selling_price, master.base_uom,
                            master.canonical_base_uom, master.factor_to_base, "operational") if master else None)
            else:
                product = clone_session.execute(select(
                    ErpProductMaster.name, ErpProductMaster.purchase_price_evidence,
                    ErpProductMaster.selling_price_evidence, ErpProductUom.source_base_uom,
                    ErpProductUom.canonical_base_uom, ErpProductUom.factor_to_base_snapshot,
                    ErpProductUom.conversion_status,
                ).outerjoin(ErpProductUom, ErpProductUom.product_id == ErpProductMaster.id).where(
                    ErpProductMaster.snapshot_id == snapshot.id, ErpProductMaster.sku == item.sku)).first()
            if not product:
                raise HTTPException(status_code=422, detail=f"Product SKU {item.sku} is not active in the operational master")
            source_uom, canonical_uom = str(product[3] or ""), str(product[4] or "")
            if product[6] == "unobserved" or item.uom.casefold() not in {source_uom.casefold(), canonical_uom.casefold()}:
                raise HTTPException(status_code=422, detail=f"UOM {item.uom} is not an approved base-unit mapping for SKU {item.sku}")
            position = operational_session.scalar(select(OperationalStockPosition).where(
                OperationalStockPosition.location_code == payload.location_code,
                OperationalStockPosition.sku == item.sku))
            price = item.unit_price if item.unit_price is not None else product[2]
            cost = item.unit_cost
            if cost is None and position is not None:
                cost = position.average_unit_cost
            if cost is None:
                cost = product[1]
            if price is None or cost is None:
                raise HTTPException(status_code=422, detail=f"Return price or cost basis is unavailable for SKU {item.sku}")
            prepared.append({"sku": item.sku, "product_name_snapshot": product[0],
                "quantity": item.quantity, "restock_quantity": item.restock_quantity,
                "writeoff_quantity": item.writeoff_quantity, "uom": item.uom,
                "canonical_uom": canonical_uom, "factor_to_base_snapshot": Decimal(str(product[5])),
                "unit_price": price, "tax_rate": item.tax_rate, "unit_cost_snapshot": cost,
                "disposition_reason": item.disposition_reason})
        return (operational_customer.legal_or_business_name if operational_customer
                else customer.legal_or_business_name), prepared

    @app.get("/api/v1/sales-returns")
    def sales_returns(request: Request, operational_session=Depends(operational_session_dependency)):
        user = current_user(request)
        rows = list_sales_returns(operational_session, allowed_locations=user.allowed_locations if user else ())
        return {"items": [sales_return_payload(row) for row in rows], "total": len(rows),
                "posting_enabled": False, "controls": sales_return_control_counts(operational_session)}

    @app.get("/api/v1/sales-returns/{return_key}")
    def sales_return_detail(return_key: str, request: Request,
                            operational_session=Depends(operational_session_dependency)):
        document = operational_session.scalar(select(OperationalSalesReturn).where(OperationalSalesReturn.return_key == return_key))
        user = current_user(request)
        if not document or not user or not location_allowed(user, document.location_code):
            raise HTTPException(status_code=404, detail="Sales return not found")
        return sales_return_payload(document)

    @app.post("/api/v1/sales-returns", status_code=201)
    def new_sales_return(payload: SalesReturnRequest, request: Request,
                         clone_session: Session = Depends(session_dependency),
                         operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "sales_return.create")
        customer_name, lines = prepare_sales_return(payload, clone_session, operational_session, user)
        try:
            document = create_sales_return(operational_session, customer_code=payload.customer_code,
                customer_name_snapshot=customer_name, location_code=payload.location_code,
                original_invoice_reference=payload.original_invoice_reference, return_date=payload.return_date,
                reason_code=payload.reason_code, notes=payload.notes, actor=user.username, lines=lines)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return sales_return_payload(document)

    @app.put("/api/v1/sales-returns/{return_key}")
    def edit_sales_return(return_key: str, payload: SalesReturnRequest, request: Request,
                          expected_revision: int = Query(ge=1),
                          clone_session: Session = Depends(session_dependency),
                          operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "sales_return.edit")
        document = operational_session.scalar(select(OperationalSalesReturn).where(
            OperationalSalesReturn.return_key == return_key).with_for_update())
        if not document or not location_allowed(user, document.location_code):
            raise HTTPException(status_code=404, detail="Sales return not found")
        customer_name, lines = prepare_sales_return(payload, clone_session, operational_session, user)
        try:
            document = replace_sales_return(operational_session, document, expected_revision=expected_revision,
                customer_code=payload.customer_code, customer_name_snapshot=customer_name,
                location_code=payload.location_code, original_invoice_reference=payload.original_invoice_reference,
                return_date=payload.return_date, reason_code=payload.reason_code, notes=payload.notes,
                actor=user.username, lines=lines)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return sales_return_payload(document)

    def sales_return_action(return_key: str, action: str, payload: DraftTransitionRequest,
                            request: Request, operational_session: Session):
        permission = {"submit": "sales_return.submit", "cancel": "sales_return.cancel",
                      "approve": "sales_return.approve"}[action]
        user = require_csrf(request, permission)
        document = operational_session.scalar(select(OperationalSalesReturn).where(
            OperationalSalesReturn.return_key == return_key).with_for_update())
        if not document or not location_allowed(user, document.location_code):
            raise HTTPException(status_code=404, detail="Sales return not found")
        try:
            return sales_return_payload(transition_sales_return(operational_session, document,
                expected_revision=payload.expected_revision, action=action, actor=user.username, note=payload.note))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/sales-returns/{return_key}/submit")
    def submit_sales_return(return_key: str, payload: DraftTransitionRequest, request: Request,
                            operational_session=Depends(operational_session_dependency)):
        return sales_return_action(return_key, "submit", payload, request, operational_session)

    @app.post("/api/v1/sales-returns/{return_key}/cancel")
    def cancel_sales_return(return_key: str, payload: DraftTransitionRequest, request: Request,
                            operational_session=Depends(operational_session_dependency)):
        return sales_return_action(return_key, "cancel", payload, request, operational_session)

    @app.post("/api/v1/sales-returns/{return_key}/approve")
    def approve_sales_return(return_key: str, payload: DraftTransitionRequest, request: Request,
                             operational_session=Depends(operational_session_dependency)):
        return sales_return_action(return_key, "approve", payload, request, operational_session)

    @app.post("/api/v1/sales-returns/{return_key}/posting-rehearsal")
    def sales_return_posting_rehearsal(return_key: str, request: Request,
                                       operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "sales_return.rehearse")
        document = operational_session.scalar(select(OperationalSalesReturn).where(
            OperationalSalesReturn.return_key == return_key).with_for_update())
        if not document or not location_allowed(user, document.location_code):
            raise HTTPException(status_code=404, detail="Sales return not found")
        try:
            return rehearse_sales_return_posting(operational_session, document, actor=user.username)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def purchase_return_payload(document: OperationalPurchaseReturn) -> dict:
        return {"return_key":document.return_key,"return_no":document.return_no,
                "supplier_code":document.supplier_code,"supplier_name":document.supplier_name_snapshot,
                "location_code":document.location_code,"source_reference_type":document.source_reference_type,
                "source_reference_key":document.source_reference_key,"return_date":document.return_date,
                "reason_code":document.reason_code,"currency_code":document.currency_code,
                "subtotal":document.subtotal,"tax_amount":document.tax_amount,"total_amount":document.total_amount,
                "status":document.status,"posting_enabled":document.posting_enabled,"notes":document.notes,
                "created_by":document.created_by,"created_at":document.created_at,"revision":document.revision,
                "state_changed_at":document.state_changed_at,"state_changed_by":document.state_changed_by,
                "debit_note":({"debit_note_key":document.debit_note.debit_note_key,
                               "debit_note_no":document.debit_note.debit_note_no,
                               "status":document.debit_note.status,"posting_enabled":document.debit_note.posting_enabled,
                               "total_amount":document.debit_note.total_amount} if document.debit_note else None),
                "lines":[{"line_no":line.line_no,"sku":line.sku,"product_name":line.product_name_snapshot,
                          "source_received_quantity":line.source_received_quantity,"quantity":line.quantity,
                          "supplier_return_quantity":line.supplier_return_quantity,
                          "internal_writeoff_quantity":line.internal_writeoff_quantity,"uom":line.uom,
                          "canonical_uom":line.canonical_uom,"factor_to_base_snapshot":line.factor_to_base_snapshot,
                          "quantity_base":line.quantity_base,"unit_price":line.unit_price,"tax_rate":line.tax_rate,
                          "net_amount":line.net_amount,"tax_amount":line.tax_amount,"gross_amount":line.gross_amount,
                          "unit_cost_snapshot":line.unit_cost_snapshot,
                          "disposition_reason":line.disposition_reason} for line in document.lines]}

    def prepare_purchase_return(payload: PurchaseReturnRequest, clone_session: Session,
                                operational_session: Session, user) -> tuple[str,list[dict]]:
        snapshot=clone_session.scalar(select(SourceSnapshot).where(SourceSnapshot.name==selected_snapshot))
        if not snapshot: raise HTTPException(status_code=404,detail="Configured BizModo clone snapshot is unavailable")
        if not location_allowed(user,payload.location_code): raise HTTPException(status_code=403,detail="Return location is outside the user's operational scope")
        if operational_masters_present(operational_session,OperationalLocationMaster):
            if not operational_session.scalar(select(OperationalLocationMaster.id).where(OperationalLocationMaster.location_code==payload.location_code,OperationalLocationMaster.status=="active")): raise HTTPException(status_code=422,detail="Return location is not active in the operational master")
        elif not clone_session.scalar(select(ErpLocation.id).where(ErpLocation.snapshot_id==snapshot.id,ErpLocation.code==payload.location_code)): raise HTTPException(status_code=422,detail="Return location is not present in the cloned master")
        operational_supplier=None
        if operational_masters_present(operational_session,OperationalPartyMaster):
            operational_supplier=operational_session.scalar(select(OperationalPartyMaster).where(OperationalPartyMaster.party_code==payload.supplier_code,OperationalPartyMaster.party_kind.in_(("supplier","both")),OperationalPartyMaster.status=="active"))
            if not operational_supplier: raise HTTPException(status_code=422,detail="Supplier is not active in the operational supplier master")
        supplier=clone_session.execute(select(ErpParty.id,ErpParty.legal_or_business_name).where(ErpParty.snapshot_id==snapshot.id,ErpParty.party_code==payload.supplier_code,ErpParty.party_kind.in_(("supplier","both")))).first()
        if not supplier: raise HTTPException(status_code=422,detail="Supplier is not present in the cloned supplier master")
        source_grn=None; source_invoice=None
        if payload.source_reference_type=="goods_receipt":
            source_grn=operational_session.scalar(select(OperationalGoodsReceipt).where(
                or_(OperationalGoodsReceipt.receipt_key==payload.source_reference_key,
                    OperationalGoodsReceipt.receipt_no==payload.source_reference_key),
                OperationalGoodsReceipt.supplier_code==payload.supplier_code,
                OperationalGoodsReceipt.location_code==payload.location_code,
                OperationalGoodsReceipt.status=="accepted"))
            if not source_grn: raise HTTPException(status_code=422,detail="Accepted goods receipt was not found for this supplier and location")
        else:
            source_invoice=clone_session.scalar(select(ErpTransactionDocument).where(
                ErpTransactionDocument.snapshot_id==snapshot.id,ErpTransactionDocument.source_kind=="purchase",
                ErpTransactionDocument.document_no==payload.source_reference_key,
                ErpTransactionDocument.party_id==supplier.id))
            if not source_invoice: raise HTTPException(status_code=422,detail="Purchase invoice was not found for the selected supplier in the cloned register")
        prepared=[]
        for item in payload.lines:
            product=clone_session.execute(select(ErpProductMaster.id,ErpProductMaster.name,ErpProductMaster.purchase_price_evidence,ErpProductUom.source_base_uom,ErpProductUom.canonical_base_uom,ErpProductUom.factor_to_base_snapshot,ErpProductUom.conversion_status).outerjoin(ErpProductUom,ErpProductUom.product_id==ErpProductMaster.id).where(ErpProductMaster.snapshot_id==snapshot.id,ErpProductMaster.sku==item.sku)).first()
            if operational_masters_present(operational_session,OperationalProductMaster):
                master=operational_session.scalar(select(OperationalProductMaster).where(OperationalProductMaster.sku==item.sku,OperationalProductMaster.status=="active"))
                if master and product: product=(product[0],master.name,master.purchase_price,master.base_uom,master.canonical_base_uom,master.factor_to_base,"operational")
                elif not master: product=None
            if not product: raise HTTPException(status_code=422,detail=f"Product SKU {item.sku} is not present in the cloned master")
            source_uom,canonical_uom=str(product[3] or ""),str(product[4] or ""); factor=Decimal(str(product[5]))
            if product[6]=="unobserved" or item.uom.casefold() not in {source_uom.casefold(),canonical_uom.casefold()}: raise HTTPException(status_code=422,detail=f"UOM {item.uom} is not an approved base-unit mapping for SKU {item.sku}")
            if source_grn:
                accepted_base=sum((line.accepted_quantity_base for line in source_grn.lines if line.sku==item.sku),Decimal("0")); source_quantity=accepted_base/factor
                source_price=next((line.unit_cost_snapshot for line in source_grn.lines if line.sku==item.sku),None)
            else:
                source_lines=clone_session.execute(select(ErpTransactionLine.entered_quantity,ErpTransactionLine.entered_uom,ErpTransactionLine.unit_price).where(ErpTransactionLine.document_id==source_invoice.id,ErpTransactionLine.product_id==product[0])).all()
                compatible=[line for line in source_lines if str(line.entered_uom or "").casefold() in {source_uom.casefold(),canonical_uom.casefold()}]
                source_quantity=sum((Decimal(str(line.entered_quantity or 0)) for line in compatible),Decimal("0")); source_price=next((line.unit_price for line in compatible if line.unit_price is not None),None)
            if source_quantity<=0: raise HTTPException(status_code=422,detail=f"Verified received quantity is unavailable for SKU {item.sku} on the selected source")
            position=operational_session.scalar(select(OperationalStockPosition).where(OperationalStockPosition.location_code==payload.location_code,OperationalStockPosition.sku==item.sku))
            price=item.unit_price if item.unit_price is not None else (source_price if source_price is not None else product[2])
            cost=position.average_unit_cost if position is not None else product[2]
            if price is None or cost is None: raise HTTPException(status_code=422,detail=f"Purchase return price or cost basis is unavailable for SKU {item.sku}")
            prepared.append({"sku":item.sku,"product_name_snapshot":product[1],"source_received_quantity":source_quantity,
                "quantity":item.quantity,"supplier_return_quantity":item.supplier_return_quantity,
                "internal_writeoff_quantity":item.internal_writeoff_quantity,"uom":item.uom,"canonical_uom":canonical_uom,
                "factor_to_base_snapshot":factor,"unit_price":price,"tax_rate":item.tax_rate,
                "unit_cost_snapshot":cost,"disposition_reason":item.disposition_reason})
        return (operational_supplier.legal_or_business_name if operational_supplier else supplier.legal_or_business_name),prepared

    @app.get("/api/v1/purchase-returns")
    def purchase_returns(request:Request,operational_session=Depends(operational_session_dependency)):
        user=current_user(request); rows=list_purchase_returns(operational_session,allowed_locations=user.allowed_locations if user else ())
        return {"items":[purchase_return_payload(row) for row in rows],"total":len(rows),"posting_enabled":False,"controls":purchase_return_control_counts(operational_session)}

    @app.get("/api/v1/purchase-returns/{return_key}")
    def purchase_return_detail(return_key:str,request:Request,operational_session=Depends(operational_session_dependency)):
        document=operational_session.scalar(select(OperationalPurchaseReturn).where(OperationalPurchaseReturn.return_key==return_key)); user=current_user(request)
        if not document or not user or not location_allowed(user,document.location_code): raise HTTPException(status_code=404,detail="Purchase return not found")
        return purchase_return_payload(document)

    @app.post("/api/v1/purchase-returns",status_code=201)
    def new_purchase_return(payload:PurchaseReturnRequest,request:Request,clone_session:Session=Depends(session_dependency),operational_session=Depends(operational_session_dependency)):
        user=require_csrf(request,"purchase_return.create"); supplier_name,lines=prepare_purchase_return(payload,clone_session,operational_session,user)
        try: document=create_purchase_return(operational_session,supplier_code=payload.supplier_code,supplier_name_snapshot=supplier_name,location_code=payload.location_code,source_reference_type=payload.source_reference_type,source_reference_key=payload.source_reference_key,return_date=payload.return_date,reason_code=payload.reason_code,notes=payload.notes,actor=user.username,lines=lines)
        except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc
        return purchase_return_payload(document)

    @app.put("/api/v1/purchase-returns/{return_key}")
    def edit_purchase_return(return_key:str,payload:PurchaseReturnRequest,request:Request,expected_revision:int=Query(ge=1),clone_session:Session=Depends(session_dependency),operational_session=Depends(operational_session_dependency)):
        user=require_csrf(request,"purchase_return.edit"); document=operational_session.scalar(select(OperationalPurchaseReturn).where(OperationalPurchaseReturn.return_key==return_key).with_for_update())
        if not document or not location_allowed(user,document.location_code): raise HTTPException(status_code=404,detail="Purchase return not found")
        supplier_name,lines=prepare_purchase_return(payload,clone_session,operational_session,user)
        try: document=replace_purchase_return(operational_session,document,expected_revision=expected_revision,supplier_code=payload.supplier_code,supplier_name_snapshot=supplier_name,location_code=payload.location_code,source_reference_type=payload.source_reference_type,source_reference_key=payload.source_reference_key,return_date=payload.return_date,reason_code=payload.reason_code,notes=payload.notes,actor=user.username,lines=lines)
        except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc
        return purchase_return_payload(document)

    def purchase_return_action(return_key:str,action:str,payload:DraftTransitionRequest,request:Request,operational_session:Session):
        permission={"submit":"purchase_return.submit","cancel":"purchase_return.cancel","approve":"purchase_return.approve"}[action]; user=require_csrf(request,permission); document=operational_session.scalar(select(OperationalPurchaseReturn).where(OperationalPurchaseReturn.return_key==return_key).with_for_update())
        if not document or not location_allowed(user,document.location_code): raise HTTPException(status_code=404,detail="Purchase return not found")
        try: return purchase_return_payload(transition_purchase_return(operational_session,document,expected_revision=payload.expected_revision,action=action,actor=user.username,note=payload.note))
        except PermissionError as exc: raise HTTPException(status_code=403,detail=str(exc)) from exc
        except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc

    @app.post("/api/v1/purchase-returns/{return_key}/submit")
    def submit_purchase_return(return_key:str,payload:DraftTransitionRequest,request:Request,operational_session=Depends(operational_session_dependency)): return purchase_return_action(return_key,"submit",payload,request,operational_session)
    @app.post("/api/v1/purchase-returns/{return_key}/cancel")
    def cancel_purchase_return(return_key:str,payload:DraftTransitionRequest,request:Request,operational_session=Depends(operational_session_dependency)): return purchase_return_action(return_key,"cancel",payload,request,operational_session)
    @app.post("/api/v1/purchase-returns/{return_key}/approve")
    def approve_purchase_return(return_key:str,payload:DraftTransitionRequest,request:Request,operational_session=Depends(operational_session_dependency)): return purchase_return_action(return_key,"approve",payload,request,operational_session)
    @app.post("/api/v1/purchase-returns/{return_key}/posting-rehearsal")
    def purchase_return_posting_rehearsal(return_key:str,request:Request,operational_session=Depends(operational_session_dependency)):
        user=require_csrf(request,"purchase_return.rehearse"); document=operational_session.scalar(select(OperationalPurchaseReturn).where(OperationalPurchaseReturn.return_key==return_key).with_for_update())
        if not document or not location_allowed(user,document.location_code): raise HTTPException(status_code=404,detail="Purchase return not found")
        try: return rehearse_purchase_return_posting(operational_session,document,actor=user.username)
        except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc

    def payment_payload(payment: OperationalPayment) -> dict:
        return {"payment_key": payment.payment_key, "payment_no": payment.payment_no,
                "payment_type": payment.payment_type, "party_code": payment.party_code,
                "party_name": payment.party_name_snapshot, "location_code": payment.location_code,
                "payment_date": payment.payment_date, "payment_method": payment.payment_method,
                "cash_bank_account_code": payment.cash_bank_account_code,
                "reference_no": payment.reference_no, "currency_code": payment.currency_code,
                "amount": payment.amount, "allocated_amount": payment.allocated_amount,
                "unallocated_amount": payment.unallocated_amount, "status": payment.status,
                "posting_enabled": payment.posting_enabled, "notes": payment.notes,
                "created_by": payment.created_by, "created_at": payment.created_at,
                "revision": payment.revision, "state_changed_at": payment.state_changed_at,
                "state_changed_by": payment.state_changed_by,
                "allocations": [{"line_no": line.line_no, "source_type": line.source_type,
                    "source_reference_key": line.source_reference_key,
                    "source_document_date": line.source_document_date,
                    "source_outstanding_snapshot": line.source_outstanding_snapshot,
                    "allocation_amount": line.allocation_amount} for line in payment.allocations]}

    def payment_open_items(payment_type: str, party_code: str, clone_session: Session,
                           operational_session: Session) -> tuple[object, list[dict]]:
        snapshot = clone_session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == selected_snapshot))
        if not snapshot:
            raise HTTPException(status_code=404, detail="Configured BizModo clone snapshot is unavailable")
        party_kind = "customer" if payment_type == "customer_receipt" else "supplier"
        source_kind = "sale" if payment_type == "customer_receipt" else "purchase"
        balance_type = "receivable" if payment_type == "customer_receipt" else "payable"
        if operational_masters_present(operational_session, OperationalPartyMaster) and not operational_session.scalar(
                select(OperationalPartyMaster.id).where(
                    OperationalPartyMaster.party_code == party_code,
                    OperationalPartyMaster.party_kind.in_((party_kind, "both")),
                    OperationalPartyMaster.status == "active")):
            raise HTTPException(status_code=422, detail=f"{party_kind.title()} is not active in the operational master")
        party = clone_session.execute(select(ErpParty.id, ErpParty.legal_or_business_name).where(
            ErpParty.snapshot_id == snapshot.id, ErpParty.party_code == party_code,
            ErpParty.party_kind.in_((party_kind, "both")))).first()
        if not party:
            raise HTTPException(status_code=422, detail=f"{party_kind.title()} is not present in the cloned master")
        items = []
        invoices = clone_session.execute(select(
            ErpTransactionDocument.document_no, ErpTransactionDocument.occurred_at,
            ErpTransactionDocument.total_amount, ErpTransactionDocument.paid_amount,
            ErpTransactionDocument.due_amount).where(
                ErpTransactionDocument.snapshot_id == snapshot.id,
                ErpTransactionDocument.source_kind == source_kind,
                ErpTransactionDocument.party_id == party.id).order_by(
                    ErpTransactionDocument.occurred_at.desc())).all()
        for invoice in invoices:
            outstanding = Decimal(str(invoice.due_amount if invoice.due_amount is not None else
                              (invoice.total_amount or 0) - (invoice.paid_amount or 0))).quantize(Decimal("0.01"))
            if outstanding > 0:
                items.append({"source_type": "invoice", "source_reference_key": invoice.document_no,
                              "source_document_date": invoice.occurred_at.date() if invoice.occurred_at else None,
                              "source_outstanding": outstanding})
        openings = operational_session.scalars(select(OperationalOpeningPartyBalance).where(
            OperationalOpeningPartyBalance.party_type == party_kind,
            OperationalOpeningPartyBalance.party_code == party_code,
            OperationalOpeningPartyBalance.balance_type == balance_type)).all()
        for opening in openings:
            items.append({"source_type": "opening_balance", "source_reference_key": f"OB:{opening.id}",
                          "source_document_date": None, "source_outstanding": opening.amount})
        for item in items:
            claimed = operational_session.scalar(select(func.coalesce(func.sum(OperationalPaymentAllocationClaim.amount), 0)).where(
                OperationalPaymentAllocationClaim.party_code == party_code,
                OperationalPaymentAllocationClaim.source_type == item["source_type"],
                OperationalPaymentAllocationClaim.source_reference_key == item["source_reference_key"],
                OperationalPaymentAllocationClaim.status == "active")) or Decimal("0")
            item["reserved_amount"] = claimed
            item["available_outstanding"] = max(Decimal("0"), item["source_outstanding"] - claimed)
        return party, [item for item in items if item["available_outstanding"] > 0]

    @app.get("/api/v1/selectors/payment-open-items")
    def payment_open_item_selector(payment_type: str = Query(pattern="^(customer_receipt|supplier_payment)$"),
                                   party_code: str = Query(min_length=1, max_length=80),
                                   clone_session: Session = Depends(session_dependency),
                                   operational_session=Depends(operational_session_dependency)):
        _, items = payment_open_items(payment_type, party_code, clone_session, operational_session)
        return {"items": items}

    def prepare_payment(payload: PaymentRequest, clone_session: Session, operational_session: Session, user) -> tuple[str, list[dict]]:
        snapshot = clone_session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == selected_snapshot))
        if not snapshot:
            raise HTTPException(status_code=404, detail="Configured BizModo clone snapshot is unavailable")
        if not location_allowed(user, payload.location_code):
            raise HTTPException(status_code=403, detail="Payment location is outside the user's operational scope")
        if operational_masters_present(operational_session, OperationalLocationMaster):
            location_exists = operational_session.scalar(select(OperationalLocationMaster.id).where(
                OperationalLocationMaster.location_code == payload.location_code,
                OperationalLocationMaster.status == "active"))
        else:
            location_exists = clone_session.scalar(select(ErpLocation.id).where(
                ErpLocation.snapshot_id == snapshot.id, ErpLocation.code == payload.location_code))
        if not location_exists:
            raise HTTPException(status_code=422, detail="Payment location is not active in the operational master")
        party, items = payment_open_items(payload.payment_type, payload.party_code, clone_session, operational_session)
        operational_party = (operational_session.scalar(select(OperationalPartyMaster).where(
            OperationalPartyMaster.party_code == payload.party_code))
            if operational_masters_present(operational_session, OperationalPartyMaster) else None)
        sources = {(item["source_type"], item["source_reference_key"]): item for item in items}
        prepared = []
        for allocation in payload.allocations:
            source = sources.get((allocation.source_type, allocation.source_reference_key))
            if not source:
                raise HTTPException(status_code=422, detail=f"Open allocation source {allocation.source_reference_key} is unavailable")
            if allocation.allocation_amount > source["available_outstanding"]:
                raise HTTPException(status_code=422, detail=f"Allocation exceeds available outstanding for {allocation.source_reference_key}")
            prepared.append({"source_type": allocation.source_type,
                             "source_reference_key": allocation.source_reference_key,
                             "source_document_date": source["source_document_date"],
                             "source_outstanding_snapshot": source["source_outstanding"],
                             "allocation_amount": allocation.allocation_amount})
        return (operational_party.legal_or_business_name if operational_party
                else party.legal_or_business_name), prepared

    @app.get("/api/v1/payments")
    def payments(request: Request, operational_session=Depends(operational_session_dependency)):
        user = current_user(request)
        rows = list_payments(operational_session, allowed_locations=user.allowed_locations if user else ())
        return {"items": [payment_payload(row) for row in rows], "total": len(rows),
                "posting_enabled": False, "controls": payment_control_counts(operational_session)}

    @app.get("/api/v1/payments/{payment_key}")
    def payment_detail(payment_key: str, request: Request,
                       operational_session=Depends(operational_session_dependency)):
        payment = operational_session.scalar(select(OperationalPayment).where(OperationalPayment.payment_key == payment_key))
        user = current_user(request)
        if not payment or not user or not location_allowed(user, payment.location_code):
            raise HTTPException(status_code=404, detail="Payment not found")
        return payment_payload(payment)

    @app.post("/api/v1/payments", status_code=201)
    def new_payment(payload: PaymentRequest, request: Request,
                    clone_session: Session = Depends(session_dependency),
                    operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "payment.create")
        party_name, allocations = prepare_payment(payload, clone_session, operational_session, user)
        try:
            payment = create_payment(operational_session, actor=user.username,
                payment_type=payload.payment_type, party_code=payload.party_code,
                party_name_snapshot=party_name, location_code=payload.location_code,
                payment_date=payload.payment_date, payment_method=payload.payment_method,
                cash_bank_account_code=payload.cash_bank_account_code, reference_no=payload.reference_no,
                amount=payload.amount, notes=payload.notes, lines=allocations)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return payment_payload(payment)

    @app.put("/api/v1/payments/{payment_key}")
    def edit_payment(payment_key: str, payload: PaymentRequest, request: Request,
                     expected_revision: int = Query(ge=1),
                     clone_session: Session = Depends(session_dependency),
                     operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "payment.edit")
        payment = operational_session.scalar(select(OperationalPayment).where(
            OperationalPayment.payment_key == payment_key).with_for_update())
        if not payment or not location_allowed(user, payment.location_code):
            raise HTTPException(status_code=404, detail="Payment not found")
        party_name, allocations = prepare_payment(payload, clone_session, operational_session, user)
        try:
            payment = replace_payment(operational_session, payment, expected_revision=expected_revision,
                actor=user.username, payment_type=payload.payment_type, party_code=payload.party_code,
                party_name_snapshot=party_name, location_code=payload.location_code,
                payment_date=payload.payment_date, payment_method=payload.payment_method,
                cash_bank_account_code=payload.cash_bank_account_code, reference_no=payload.reference_no,
                amount=payload.amount, notes=payload.notes, lines=allocations)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return payment_payload(payment)

    def payment_action(payment_key: str, action: str, payload: DraftTransitionRequest,
                       request: Request, operational_session: Session):
        permission = {"submit": "payment.submit", "cancel": "payment.cancel", "approve": "payment.approve"}[action]
        user = require_csrf(request, permission)
        payment = operational_session.scalar(select(OperationalPayment).where(
            OperationalPayment.payment_key == payment_key).with_for_update())
        if not payment or not location_allowed(user, payment.location_code):
            raise HTTPException(status_code=404, detail="Payment not found")
        try:
            return payment_payload(transition_payment(operational_session, payment,
                expected_revision=payload.expected_revision, action=action, actor=user.username, note=payload.note))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/payments/{payment_key}/submit")
    def submit_payment(payment_key: str, payload: DraftTransitionRequest, request: Request,
                       operational_session=Depends(operational_session_dependency)):
        return payment_action(payment_key, "submit", payload, request, operational_session)

    @app.post("/api/v1/payments/{payment_key}/cancel")
    def cancel_payment(payment_key: str, payload: DraftTransitionRequest, request: Request,
                       operational_session=Depends(operational_session_dependency)):
        return payment_action(payment_key, "cancel", payload, request, operational_session)

    @app.post("/api/v1/payments/{payment_key}/approve")
    def approve_payment(payment_key: str, payload: DraftTransitionRequest, request: Request,
                        operational_session=Depends(operational_session_dependency)):
        return payment_action(payment_key, "approve", payload, request, operational_session)

    @app.post("/api/v1/payments/{payment_key}/posting-rehearsal")
    def payment_posting_rehearsal(payment_key: str, request: Request,
                                  operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "payment.rehearse")
        payment = operational_session.scalar(select(OperationalPayment).where(
            OperationalPayment.payment_key == payment_key).with_for_update())
        if not payment or not location_allowed(user, payment.location_code):
            raise HTTPException(status_code=404, detail="Payment not found")
        try:
            return rehearse_payment_posting(operational_session, payment, actor=user.username)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def require_integrated_resource(request: Request, operational_session, resource_type: str,
                                    resource_key: str, permission: str):
        user = require_csrf(request, permission)
        if resource_type not in RESOURCE_TYPES:
            raise HTTPException(status_code=404, detail="Posting resource not found")
        resource = get_posting_resource(operational_session, resource_type, resource_key)
        locations = [resource.location_code] if resource else []
        destination = getattr(resource, "destination_location_code", None) if resource else None
        if destination:
            locations.append(destination)
        if not resource or any(not location_allowed(user, location) for location in locations):
            raise HTTPException(status_code=404, detail="Posting resource not found")
        return user, resource

    @app.get("/api/v1/posting/readiness")
    def posting_readiness(request: Request,
                          operational_session=Depends(operational_session_dependency)):
        require_user(request, "clone.read")
        return {
            "posting_enabled": app.state.posting_enabled,
            "production_ready": False,
            "supported_resources": ["sale", "purchase", *sorted(RESOURCE_TYPES)],
            "controls": integrated_posting_counts(operational_session),
            "activation_requirement": "Explicit production approval and ASAS_POSTING_ENABLED=true",
        }

    @app.get("/api/v1/deployment/readiness")
    def deployment_readiness(request: Request):
        require_user(request, "clone.read")
        gates = {
            "production_mode": app.state.production_mode,
            "authentication": app.state.auth_enabled,
            "persistent_sessions": app.state.production_mode,
            "secure_cookies": app.state.secure_cookies,
            "explicit_allowed_hosts": bool(security_settings["allowed_hosts"]),
            "operational_postgresql": operational_url.startswith("postgresql"),
            "hr_payroll_excluded": True,
            "posting_dual_control": (not security_settings["posting_requested"]
                                     or (security_settings["posting_confirmed"]
                                         and len(security_settings["posting_approval_reference"]) >= 8)),
        }
        return {
            "production_ready": all(gates.values()),
            "posting_enabled": app.state.posting_enabled,
            "posting_approval_reference_present": bool(app.state.posting_approval_reference),
            "gates": gates,
        }

    @app.post("/api/v1/posting/{resource_type}/{resource_key}")
    def post_integrated_resource(resource_type: str, resource_key: str, payload: PostingExecutionRequest,
                                 request: Request,
                                 operational_session=Depends(operational_session_dependency)):
        if not app.state.posting_enabled:
            raise HTTPException(status_code=503, detail="Permanent posting activation is disabled")
        user, _ = require_integrated_resource(request, operational_session, resource_type, resource_key,
                                              "posting.execute")
        try:
            return execute_integrated_posting(operational_session, resource_type=resource_type,
                                              resource_key=resource_key,
                                              idempotency_key=payload.idempotency_key,
                                              actor=user.username)
        except ValueError as exc:
            operational_session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/integrated-posting-batches/{batch_key}/reverse")
    def reverse_integrated_batch(batch_key: str, payload: ReversalExecutionRequest, request: Request,
                                 operational_session=Depends(operational_session_dependency)):
        if not app.state.posting_enabled:
            raise HTTPException(status_code=503, detail="Permanent posting activation is disabled")
        batch = operational_session.scalar(select(OperationalIntegratedPostingBatch).where(
            OperationalIntegratedPostingBatch.batch_key == batch_key))
        if not batch:
            raise HTTPException(status_code=404, detail="Posting batch not found")
        user, _ = require_integrated_resource(request, operational_session, batch.resource_type,
                                              batch.resource_key, "posting.reverse")
        try:
            return execute_integrated_reversal(operational_session, batch, actor=user.username,
                                               reason=payload.reason)
        except ValueError as exc:
            operational_session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/data-governance/promotion")
    def promotion_governance(snapshot: SourceSnapshot = Depends(snapshot_dependency),
                             clone_session: Session = Depends(session_dependency),
                             operational_session=Depends(operational_session_dependency)):
        cloned_counts = {
            "locations": clone_session.scalar(select(func.count(ErpLocation.id)).where(ErpLocation.snapshot_id == snapshot.id)) or 0,
            "parties": clone_session.scalar(select(func.count(ErpParty.id)).where(ErpParty.snapshot_id == snapshot.id)) or 0,
            "products": clone_session.scalar(select(func.count(ErpProductMaster.id)).where(ErpProductMaster.snapshot_id == snapshot.id)) or 0,
            "product_uoms": clone_session.scalar(select(func.count(ErpProductUom.id)).where(ErpProductUom.snapshot_id == snapshot.id)) or 0,
            "transaction_documents": clone_session.scalar(select(func.count(ErpTransactionDocument.id)).where(ErpTransactionDocument.snapshot_id == snapshot.id)) or 0,
            "inventory_movements": clone_session.scalar(select(func.count(ErpInventoryMovement.id)).where(ErpInventoryMovement.snapshot_id == snapshot.id)) or 0,
            "opening_balance_queue": clone_session.scalar(select(func.count(ErpOpeningBalanceQueue.id)).where(ErpOpeningBalanceQueue.snapshot_id == snapshot.id)) or 0,
        }
        registry = promotion_control_counts(operational_session)
        return {"source_system": snapshot.source_system, "source_snapshot": snapshot.name,
                "clone_remains_immutable": True, "promotion_executed": registry["mapped_records"] > 0,
                "cloned_counts": cloned_counts, "registry": registry,
                "activation_gates": PROMOTION_GATES,
                "lifecycle_policy": {
                    "promoted_master_active": lifecycle_actions("master", "active", referenced=True, source_promoted=True),
                    "erp_draft_transaction": lifecycle_actions("transaction", "draft"),
                    "posted_transaction": lifecycle_actions("transaction", "posted"),
                    "imported_history": lifecycle_actions("transaction", "historical"),
                }}

    @app.get("/api/v1/data-governance/source-verification")
    def source_verification_governance(operational_session=Depends(operational_session_dependency)):
        return {**source_verification_counts(operational_session),
                "verification_scope": "immutable_raw_clone_evidence",
                "posting_enabled": False, "promotion_executed": False}

    @app.get("/api/v1/overview")
    def overview(snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency)):
        count = lambda model: session.scalar(select(func.count(model.id)).where(model.snapshot_id == snapshot.id)) or 0
        organization = session.scalar(select(ErpOrganization).where(
            ErpOrganization.snapshot_id == snapshot.id).order_by(ErpOrganization.id).limit(1))
        document_counts = dict(session.execute(select(
            ErpTransactionDocument.source_kind, func.count(ErpTransactionDocument.id)
        ).where(ErpTransactionDocument.snapshot_id == snapshot.id).group_by(
            ErpTransactionDocument.source_kind)).all())
        party_counts = dict(session.execute(select(
            ErpParty.party_kind, func.count(ErpParty.id)
        ).where(ErpParty.snapshot_id == snapshot.id).group_by(ErpParty.party_kind)).all())
        inventory_quantity = session.scalar(select(func.coalesce(func.sum(
            ErpInventoryMovement.quantity_base), 0)).where(ErpInventoryMovement.snapshot_id == snapshot.id))
        baseline_counts = {
            "customers": party_counts.get("customer", 0) + party_counts.get("both", 0),
            "suppliers": party_counts.get("supplier", 0) + party_counts.get("both", 0),
            "products": count(ErpProductMaster),
            "sales": document_counts.get("sale", 0),
            "purchases": document_counts.get("purchase", 0),
            "sales_returns": document_counts.get("sale_return", 0),
            "purchase_returns": document_counts.get("purchase_return", 0),
            "stock_transfers": document_counts.get("stock_transfer", 0),
            "inventory_movements": count(ErpInventoryMovement),
            "exceptions": count(ErpMigrationExceptionQueue),
        }
        latest_counts = dict(baseline_counts)
        overlay = app.state.delta_overlay
        if overlay:
            for key in ("customers", "suppliers", "products", "sales", "purchases", "sales_returns", "purchase_returns", "stock_transfers"):
                if key in overlay.counts:
                    latest_counts[key] = (baseline_counts.get(key, 0) + overlay.deltas[key]
                                          if key in overlay.overlap_entities else overlay.counts[key])
        return {
            "organization": organization.legal_name if organization else "Asas General Trading LLC",
            "currency": organization.currency_code if organization else "AED",
            "snapshot": snapshot.name,
            "source_system": snapshot.source_system,
            "snapshot_created_at": snapshot.created_at,
            "atomic_source": snapshot.is_atomic,
            "mode": "read_only_preview",
            "posting_enabled": False,
            "hr_payroll_enabled": False,
            "counts": latest_counts,
            "baseline_counts": baseline_counts,
            "delta_overlay": _overlay_status(overlay),
            "inventory_quantity_base": inventory_quantity,
        }

    def page(limit: int, offset: int, total: int, rows) -> dict:
        return {"items": [dict(row._mapping) if hasattr(row, "_mapping") else dict(row) for row in rows],
                "total": total, "limit": limit, "offset": offset}

    def _overlay_status(overlay):
        if not overlay:
            return {"available": False, "posting_allowed": False}
        return {
            "available": True,
            "captured_at_utc": overlay.captured_at_utc,
            "atomic": overlay.atomic,
            "hashes_verified": overlay.hashes_verified,
            "rows_verified": overlay.rows_verified,
            "counts": overlay.counts,
            "deltas_from_prior_watermark": overlay.deltas,
            "posting_allowed": False,
            "newest_child_details_complete": False,
        }

    def _contains(record: dict, q: str | None) -> bool:
        return not q or q.casefold() in " ".join(str(value or "") for value in record.values()).casefold()

    def _merge_records(baseline_rows, overlay_rows: list[dict], key: str, q: str | None,
                       sort_key: str, limit: int, offset: int, reverse: bool = False):
        baseline = [dict(row._mapping) for row in baseline_rows]
        existing = {str(row.get(key) or "") for row in baseline}
        additions = [row for row in overlay_rows if str(row.get(key) or "") not in existing]
        merged = [row for row in baseline + additions if _contains(row, q)]
        merged.sort(key=lambda row: str(row.get(sort_key) or ""), reverse=reverse)
        return page(limit, offset, len(merged), merged[offset:offset + limit])

    @app.get("/api/v1/products")
    def products(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                 q: str | None = Query(None, max_length=120),
                 snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency),
                 operational_session=Depends(optional_operational_session_dependency)):
        if operational_session is not None and operational_session.scalar(select(func.count(OperationalProductMaster.id))):
            filters = []
            if q:
                pattern = f"%{q.strip()}%"
                filters.append(or_(OperationalProductMaster.sku.ilike(pattern), OperationalProductMaster.name.ilike(pattern)))
            total = operational_session.scalar(select(func.count(OperationalProductMaster.id)).where(*filters)) or 0
            rows = operational_session.execute(select(
                OperationalProductMaster.id, OperationalProductMaster.sku, OperationalProductMaster.name,
                OperationalProductMaster.category_name, OperationalProductMaster.brand_name,
                OperationalProductMaster.purchase_price.label("purchase_price_evidence"),
                OperationalProductMaster.selling_price.label("selling_price_evidence"),
                OperationalProductMaster.tax_rate, OperationalProductMaster.status.label("master_status"),
                OperationalProductMaster.revision,
            ).where(*filters).order_by(OperationalProductMaster.sku).offset(offset).limit(limit)).all()
            return page(limit, offset, total, rows)
        filters = [ErpProductMaster.snapshot_id == snapshot.id]
        rows = session.execute(select(
            ErpProductMaster.id, ErpProductMaster.sku, ErpProductMaster.name,
            ErpProductMaster.category_name, ErpProductMaster.brand_name,
            ErpProductMaster.purchase_price_evidence, ErpProductMaster.selling_price_evidence,
            ErpProductMaster.master_status,
        ).where(*filters)).all()
        overlay = app.state.delta_overlay
        return _merge_records(rows, overlay.product_records() if overlay else [], "sku", q, "sku", limit, offset)

    def operational_product_payload(record: OperationalProductMaster) -> dict:
        return {"sku": record.sku, "name": record.name, "category_name": record.category_name,
                "brand_name": record.brand_name, "purchase_price_evidence": record.purchase_price,
                "selling_price_evidence": record.selling_price, "tax_rate": record.tax_rate,
                "master_status": record.status, "revision": record.revision,
                "source_promoted": record.source_promoted}

    @app.patch("/api/v1/master-data/products/{sku}")
    def update_product_master(sku: str, payload: ProductMasterUpdateRequest, request: Request,
                              operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "migration.review")
        record = operational_session.scalar(select(OperationalProductMaster).where(
            OperationalProductMaster.sku == sku).with_for_update())
        if not record:
            raise HTTPException(status_code=404, detail="Operational product not found")
        if record.revision != payload.expected_revision:
            raise HTTPException(status_code=409, detail=f"Product revision conflict; current revision is {record.revision}")
        for field in ("name", "category_name", "brand_name", "purchase_price", "selling_price", "tax_rate"):
            setattr(record, field, getattr(payload, field))
        record.revision += 1; record.updated_by = user.username; record.updated_at = datetime.now().astimezone()
        operational_session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="master.product.edited",
            actor=user.username, resource_key=record.product_key, detail=f"SKU {record.sku}; revision {record.revision}"))
        operational_session.commit()
        return operational_product_payload(record)

    @app.post("/api/v1/master-data/products/{sku}/{action}")
    def product_master_status(sku: str, action: str, payload: MasterStatusRequest, request: Request,
                              operational_session=Depends(operational_session_dependency)):
        if action not in {"deactivate", "reactivate"}:
            raise HTTPException(status_code=404, detail="Unsupported master action")
        user = require_csrf(request, "migration.review")
        record = operational_session.scalar(select(OperationalProductMaster).where(
            OperationalProductMaster.sku == sku).with_for_update())
        if not record: raise HTTPException(status_code=404, detail="Operational product not found")
        if record.revision != payload.expected_revision:
            raise HTTPException(status_code=409, detail=f"Product revision conflict; current revision is {record.revision}")
        target = "inactive" if action == "deactivate" else "active"
        if record.status == target: raise HTTPException(status_code=409, detail=f"Product is already {target}")
        record.status = target; record.revision += 1; record.updated_by = user.username; record.updated_at = datetime.now().astimezone()
        operational_session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"master.product.{action}d",
            actor=user.username, resource_key=record.product_key, detail=payload.note or f"SKU {record.sku}"))
        operational_session.commit()
        return operational_product_payload(record)

    def parties(kind: str, limit: int, offset: int, q: str | None, snapshot: SourceSnapshot,
                session: Session, operational_session):
        filters = [OperationalPartyMaster.party_kind.in_((kind, "both"))]
        if q:
            pattern = f"%{q.strip()}%"
            filters.append(or_(OperationalPartyMaster.party_code.ilike(pattern), OperationalPartyMaster.legal_or_business_name.ilike(pattern)))
        if operational_session is not None and operational_session.scalar(select(func.count(OperationalPartyMaster.id))):
            total = operational_session.scalar(select(func.count(OperationalPartyMaster.id)).where(*filters)) or 0
            rows = operational_session.execute(select(
                OperationalPartyMaster.id, OperationalPartyMaster.party_code,
                OperationalPartyMaster.legal_or_business_name, OperationalPartyMaster.contact_name,
                OperationalPartyMaster.email, OperationalPartyMaster.mobile,
                OperationalPartyMaster.address, OperationalPartyMaster.tax_number,
                OperationalPartyMaster.party_kind, OperationalPartyMaster.status.label("master_status"),
                OperationalPartyMaster.revision,
            ).where(*filters).order_by(OperationalPartyMaster.legal_or_business_name).offset(offset).limit(limit)).all()
            return page(limit, offset, total, rows)
        kinds = (kind, "both")
        filters = [ErpParty.snapshot_id == snapshot.id, ErpParty.party_kind.in_(kinds)]
        rows = session.execute(select(
            ErpParty.id, ErpParty.party_code, ErpParty.legal_or_business_name,
            ErpParty.contact_name, ErpParty.party_kind, ErpParty.master_status,
        ).where(*filters)).all()
        overlay = app.state.delta_overlay
        overlay_rows = overlay.party_records(kind) if overlay else []
        return _merge_records(rows, overlay_rows, "party_code", q, "legal_or_business_name", limit, offset)

    @app.get("/api/v1/customers")
    def customers(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                  q: str | None = Query(None, max_length=120),
                  snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency),
                  operational_session=Depends(optional_operational_session_dependency)):
        return parties("customer", limit, offset, q, snapshot, session, operational_session)

    @app.get("/api/v1/suppliers")
    def suppliers(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                  q: str | None = Query(None, max_length=120),
                  snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency),
                  operational_session=Depends(optional_operational_session_dependency)):
        return parties("supplier", limit, offset, q, snapshot, session, operational_session)

    def operational_party_payload(record: OperationalPartyMaster) -> dict:
        return {"party_code": record.party_code, "party_kind": record.party_kind,
                "legal_or_business_name": record.legal_or_business_name, "contact_name": record.contact_name,
                "email": record.email, "mobile": record.mobile, "address": record.address,
                "tax_number": record.tax_number, "master_status": record.status,
                "revision": record.revision, "source_promoted": record.source_promoted}

    @app.patch("/api/v1/master-data/parties/{party_code}")
    def update_party_master(party_code: str, payload: PartyMasterUpdateRequest, request: Request,
                            operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "migration.review")
        record = operational_session.scalar(select(OperationalPartyMaster).where(
            OperationalPartyMaster.party_code == party_code).with_for_update())
        if not record: raise HTTPException(status_code=404, detail="Operational party not found")
        if record.revision != payload.expected_revision:
            raise HTTPException(status_code=409, detail=f"Party revision conflict; current revision is {record.revision}")
        for field in ("legal_or_business_name", "contact_name", "email", "mobile", "address", "tax_number"):
            setattr(record, field, getattr(payload, field))
        record.revision += 1; record.updated_by = user.username; record.updated_at = datetime.now().astimezone()
        operational_session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="master.party.edited",
            actor=user.username, resource_key=record.party_key, detail=f"Party {record.party_code}; revision {record.revision}"))
        operational_session.commit()
        return operational_party_payload(record)

    @app.post("/api/v1/master-data/parties/{party_code}/{action}")
    def party_master_status(party_code: str, action: str, payload: MasterStatusRequest, request: Request,
                            operational_session=Depends(operational_session_dependency)):
        if action not in {"deactivate", "reactivate"}: raise HTTPException(status_code=404, detail="Unsupported master action")
        user = require_csrf(request, "migration.review")
        record = operational_session.scalar(select(OperationalPartyMaster).where(
            OperationalPartyMaster.party_code == party_code).with_for_update())
        if not record: raise HTTPException(status_code=404, detail="Operational party not found")
        if record.revision != payload.expected_revision:
            raise HTTPException(status_code=409, detail=f"Party revision conflict; current revision is {record.revision}")
        target = "inactive" if action == "deactivate" else "active"
        if record.status == target: raise HTTPException(status_code=409, detail=f"Party is already {target}")
        record.status = target; record.revision += 1; record.updated_by = user.username; record.updated_at = datetime.now().astimezone()
        operational_session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"master.party.{action}d",
            actor=user.username, resource_key=record.party_key, detail=payload.note or f"Party {record.party_code}"))
        operational_session.commit()
        return operational_party_payload(record)

    def documents(kinds: tuple[str, ...], limit: int, offset: int, q: str | None,
                  snapshot: SourceSnapshot, session: Session):
        filters = [ErpTransactionDocument.snapshot_id == snapshot.id,
                   ErpTransactionDocument.source_kind.in_(kinds)]
        rows = session.execute(select(
            ErpTransactionDocument.id, ErpTransactionDocument.source_kind,
            ErpTransactionDocument.document_no, ErpTransactionDocument.occurred_at,
            ErpParty.legal_or_business_name.label("party_name"), ErpLocation.code.label("location"),
            ErpTransactionDocument.total_amount, ErpTransactionDocument.paid_amount,
            ErpTransactionDocument.due_amount, ErpTransactionDocument.source_status,
            ErpTransactionDocument.migration_status,
        ).outerjoin(ErpParty, ErpParty.id == ErpTransactionDocument.party_id).outerjoin(
            ErpLocation, ErpLocation.id == ErpTransactionDocument.location_id).where(
            *filters)).all()
        overlay = app.state.delta_overlay
        overlay_rows = []
        if overlay and "sale" in kinds:
            overlay_rows.extend(overlay.sale_records())
        if overlay and "purchase" in kinds:
            overlay_rows.extend(overlay.purchase_records())
        if overlay and "sale_return" in kinds:
            overlay_rows.extend(overlay.sale_return_records())
        if overlay and "purchase_return" in kinds:
            overlay_rows.extend(overlay.purchase_return_records())
        return _merge_records(rows, overlay_rows, "document_no", q, "occurred_at", limit, offset, reverse=True)

    def source_review_evidence(entity_type: str, source_record_key: str,
                               snapshot: SourceSnapshot, session: Session) -> tuple[dict, str]:
        baseline = baseline_review_evidence(session, snapshot, entity_type, source_record_key)
        if baseline:
            return baseline
        overlay = app.state.delta_overlay
        overlay_methods = {
            "sale": "sale_records", "purchase": "purchase_records",
            "sale_return": "sale_return_records", "purchase_return": "purchase_return_records",
        }
        if overlay:
            method = getattr(overlay, overlay_methods[entity_type])
            for candidate in method():
                if str(candidate.get("document_no")) == source_record_key:
                    return dict(candidate), str(candidate.get("migration_status") or "provisional_overlay")
        raise HTTPException(status_code=404, detail="Captured source record not found")

    @app.get("/api/v1/data-reviews")
    def data_reviews(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                     status: str | None = Query(None, max_length=30),
                     operational_session=Depends(operational_session_dependency)):
        filters = []
        if status == "open":
            filters.append(OperationalDataReview.status.in_(("in_review", "correction_required", "corrected")))
        elif status:
            filters.append(OperationalDataReview.status == status)
        total = operational_session.scalar(select(func.count(OperationalDataReview.id)).where(*filters)) or 0
        rows = operational_session.scalars(select(OperationalDataReview).where(*filters).order_by(
            OperationalDataReview.created_at.desc()).offset(offset).limit(limit)).all()
        return {"items": [review_payload(row, posting_enabled=app.state.posting_enabled) for row in rows],
                "total": total, "limit": limit, "offset": offset,
                "controls": review_control_counts(operational_session),
                "posting_enabled": app.state.posting_enabled}

    @app.get("/api/v1/data-review-suggestions")
    def data_review_suggestions(limit: int = Query(20, ge=1, le=100),
                                snapshot: SourceSnapshot = Depends(snapshot_dependency),
                                session: Session = Depends(session_dependency),
                                operational_session=Depends(operational_session_dependency)):
        reviewed = set(operational_session.execute(select(
            OperationalDataReview.entity_type, OperationalDataReview.source_record_key)).all())
        line_totals = select(
            ErpTransactionLine.document_id.label("document_id"),
            func.count(ErpTransactionLine.id).label("line_count"),
            func.sum(ErpTransactionLine.subtotal).label("line_subtotal"),
        ).group_by(ErpTransactionLine.document_id).subquery()
        rows = session.execute(select(
            ErpTransactionDocument,
            ErpParty.legal_or_business_name.label("party_name"),
            ErpLocation.code.label("location"),
            line_totals.c.line_count,
            line_totals.c.line_subtotal,
        ).outerjoin(ErpParty, ErpParty.id == ErpTransactionDocument.party_id).outerjoin(
            ErpLocation, ErpLocation.id == ErpTransactionDocument.location_id).outerjoin(
            line_totals, line_totals.c.document_id == ErpTransactionDocument.id).where(
            ErpTransactionDocument.snapshot_id == snapshot.id,
            ErpTransactionDocument.source_kind.in_(("sale", "purchase")),
        )).all()
        totals: dict[str, list[Decimal]] = {"sale": [], "purchase": []}
        for document, *_ in rows:
            if document.total_amount is not None and document.total_amount >= 0:
                totals[document.source_kind].append(Decimal(document.total_amount))
        thresholds = {}
        for kind, values in totals.items():
            values.sort()
            thresholds[kind] = values[min(len(values) - 1, int(len(values) * .99))] if values else None
        suggestions = []
        for document, party_name, location, line_count, line_subtotal in rows:
            if (document.source_kind, document.document_no) in reviewed:
                continue
            finding = transaction_review_findings(
                total_amount=document.total_amount, paid_amount=document.paid_amount,
                due_amount=document.due_amount, source_status=document.source_status,
                party_present=bool(party_name), location_present=bool(location),
                line_count=int(line_count or 0), line_subtotal=line_subtotal,
                high_value_threshold=thresholds[document.source_kind],
            )
            if finding:
                suggestions.append({
                    **finding, "entity_type": document.source_kind,
                    "document_no": document.document_no, "occurred_at": document.occurred_at,
                    "party_name": party_name, "location": location,
                    "total_amount": document.total_amount,
                    "source_status": document.source_status,
                })
        suggestions.sort(key=lambda item: (-item["score"], -abs(Decimal(item["total_amount"] or 0)),
                                           item["document_no"]))
        severity_counts = {severity: sum(1 for item in suggestions if item["severity"] == severity)
                           for severity in ("critical", "high", "medium")}
        assessed = sum(1 for document, *_ in rows
                       if (document.source_kind, document.document_no) not in reviewed)
        return {"items": suggestions[:limit], "total": len(suggestions),
                "assessed": assessed, "severity_counts": severity_counts,
                "method": "Conservative transaction consistency and robust high-value checks"}

    @app.post("/api/v1/data-reviews")
    def create_data_review(payload: DataReviewStartRequest, request: Request,
                           snapshot: SourceSnapshot = Depends(snapshot_dependency),
                           session: Session = Depends(session_dependency),
                           operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "migration.review")
        original, source_status = source_review_evidence(
            payload.entity_type, payload.source_record_key, snapshot, session)
        record = start_review(operational_session, entity_type=payload.entity_type,
                              source_record_key=payload.source_record_key, source_status=source_status,
                              original_payload=original, actor=user.username)
        enrich_review_source(
            operational_session, record, source_payload=original, actor=user.username,
            note="Complete item details recovered from the preserved baseline; review this revision again.",
        )
        operational_session.commit()
        return review_payload(record, posting_enabled=app.state.posting_enabled)

    @app.post("/api/v1/data-reviews/{review_key}/{action}")
    def act_on_data_review(review_key: str, action: str, payload: DataReviewActionRequest,
                           request: Request, operational_session=Depends(operational_session_dependency)):
        if action not in {"verify", "flag-incorrect", "correct", "reject", "promote"}:
            raise HTTPException(status_code=404, detail="Unsupported review action")
        user = require_csrf(request, "migration.review")
        record = operational_session.scalar(select(OperationalDataReview).where(
            OperationalDataReview.review_key == review_key).with_for_update())
        if not record:
            raise HTTPException(status_code=404, detail="Data review not found")
        try:
            transition_review(operational_session, record, action=action,
                              expected_revision=payload.expected_revision, actor=user.username,
                              rationale=payload.rationale, corrected_payload=payload.corrected_payload,
                              posting_enabled=app.state.posting_enabled)
            operational_session.commit()
        except ValueError as exc:
            operational_session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return review_payload(record, posting_enabled=app.state.posting_enabled)

    @app.get("/api/v1/sales")
    def sales(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
              q: str | None = Query(None, max_length=120),
              snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency)):
        return documents(("sale", "sale_return"), limit, offset, q, snapshot, session)

    @app.get("/api/v1/purchases")
    def purchases(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                  q: str | None = Query(None, max_length=120),
                  snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency)):
        return documents(("purchase", "purchase_return"), limit, offset, q, snapshot, session)

    @app.get("/api/v1/inventory")
    def inventory(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                  q: str | None = Query(None, max_length=120),
                  snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency)):
        filters = [ErpInventoryMovement.snapshot_id == snapshot.id]
        if q:
            pattern = f"%{q.strip()}%"
            filters.append(or_(ErpProductMaster.sku.ilike(pattern), ErpProductMaster.name.ilike(pattern)))
        grouped = select(
            ErpProductMaster.sku, ErpProductMaster.name,
            ErpLocation.code.label("location"),
            func.sum(ErpInventoryMovement.quantity_base).label("quantity_base"),
            func.max(ErpInventoryMovement.canonical_uom).label("uom"),
            func.count(ErpInventoryMovement.id).label("movement_count"),
        ).join(ErpProductMaster, ErpProductMaster.id == ErpInventoryMovement.product_id).outerjoin(
            ErpLocation, ErpLocation.id == ErpInventoryMovement.location_id).where(*filters).group_by(
            ErpProductMaster.sku, ErpProductMaster.name, ErpLocation.code)
        total = session.scalar(select(func.count()).select_from(grouped.subquery())) or 0
        rows = session.execute(grouped.order_by(ErpProductMaster.sku, ErpLocation.code).offset(offset).limit(limit)).all()
        return page(limit, offset, total, rows)

    def require_finance_report_scope(request: Request, snapshot: SourceSnapshot, session: Session):
        user = current_user(request)
        if not user or "financial_report.read" not in user.permissions:
            raise HTTPException(status_code=403, detail="Permission financial_report.read is required")
        location_codes = {row[0].upper() for row in session.execute(select(ErpLocation.code).where(
            ErpLocation.snapshot_id == snapshot.id)).all()}
        allowed = set(user.allowed_locations)
        if "*" not in allowed and not location_codes.issubset(allowed):
            raise HTTPException(status_code=403, detail="Company-wide location scope is required because migrated opening AR/AP is not location-distributed")
        return user

    @app.get("/api/v1/accounting")
    def accounting(request: Request, snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency),
                   operational_session=Depends(operational_session_dependency)):
        require_finance_report_scope(request, snapshot, session)
        openings = session.execute(select(
            ErpOpeningBalanceQueue.balance_kind,
            func.count(ErpOpeningBalanceQueue.id).label("rows"),
            func.coalesce(func.sum(ErpOpeningBalanceQueue.amount), 0).label("amount"),
            func.coalesce(func.sum(ErpOpeningBalanceQueue.quantity), 0).label("quantity"),
        ).where(ErpOpeningBalanceQueue.snapshot_id == snapshot.id).group_by(
            ErpOpeningBalanceQueue.balance_kind).order_by(ErpOpeningBalanceQueue.balance_kind)).all()
        accounts = session.scalar(select(func.count(ErpGlAccount.id)).where(ErpGlAccount.snapshot_id == snapshot.id)) or 0
        staged = operational_session.execute(select(
            OperationalOpeningPartyBalance.balance_type,
            func.count(OperationalOpeningPartyBalance.id).label("rows"),
            func.coalesce(func.sum(OperationalOpeningPartyBalance.amount), 0).label("amount"),
        ).group_by(OperationalOpeningPartyBalance.balance_type).order_by(
            OperationalOpeningPartyBalance.balance_type)).all()
        finance_exceptions = operational_session.scalar(select(
            func.count(OperationalFinancialMigrationException.id)).where(
            OperationalFinancialMigrationException.status == "open")) or 0
        summary = build_accounting_summary(session, operational_session, snapshot_id=snapshot.id)
        return {"opening_controls": [dict(row._mapping) for row in openings], "gl_accounts": accounts,
                "staged_opening_controls": [dict(row._mapping) for row in staged],
                "open_financial_exceptions": finance_exceptions,
                "accounting_summary": summary, "posting_enabled": False, "currency": "AED"}

    @app.get("/api/v1/reports/ageing")
    def ageing_report(request: Request, ledger_kind: str = Query(pattern="^(receivable|payable)$"),
                      as_of: date | None = Query(None), q: str = Query("", max_length=120),
                      limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                      snapshot: SourceSnapshot = Depends(snapshot_dependency),
                      session: Session = Depends(session_dependency),
                      operational_session=Depends(operational_session_dependency)):
        require_finance_report_scope(request, snapshot, session)
        return build_ageing_report(session, operational_session, snapshot_id=snapshot.id,
            ledger_kind=ledger_kind, as_of=as_of or date.today(), query=q, limit=limit, offset=offset)

    @app.get("/api/v1/reports")
    def reports(snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency)):
        exceptions = session.execute(select(
            ErpMigrationExceptionQueue.severity, ErpMigrationExceptionQueue.queue_status,
            func.count(ErpMigrationExceptionQueue.id).label("count"),
        ).where(ErpMigrationExceptionQueue.snapshot_id == snapshot.id).group_by(
            ErpMigrationExceptionQueue.severity, ErpMigrationExceptionQueue.queue_status).order_by(
            ErpMigrationExceptionQueue.severity, ErpMigrationExceptionQueue.queue_status)).all()
        return {"exceptions": [dict(row._mapping) for row in exceptions], "source_atomic": snapshot.is_atomic,
                "source_system": snapshot.source_system, "snapshot": snapshot.name,
                "production_ready": False, "posting_enabled": False,
                "delta_overlay": _overlay_status(app.state.delta_overlay)}

    @app.get("/api/v1/delta-overlay")
    def delta_overlay():
        return _overlay_status(app.state.delta_overlay)

    return app


app = create_app()
