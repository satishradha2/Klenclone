from __future__ import annotations

import os
import uuid
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker

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
    ErpTransactionDocument,
    SourceSnapshot,
)
from .operational import (
    OperationalDraft, OperationalFiscalPeriod, OperationalJournalBatch,
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
from .sales_returns import (
    OperationalSalesReturn, create_sales_return, list_sales_returns,
    rehearse_sales_return_posting, replace_sales_return,
    sales_return_control_counts, transition_sales_return,
)
from .provisioned_users import load_provisioned_users


STATIC_DIR = Path(__file__).with_name("static")
DEFAULT_SNAPSHOT = "bizmodo-2026-09-08-browser"
SESSION_COOKIE = "asas_erp_session"


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
        description="Independent read-only ERP preview backed only by the BizModo clone database.",
    )
    app.state.engine = engine
    app.state.snapshot_name = selected_snapshot
    app.state.sessions = UatSessionStore()
    app.state.auth_enabled = os.getenv("ASAS_AUTH_ENABLED", "false").lower() == "true"
    app.state.posting_enabled = os.getenv("ASAS_POSTING_ENABLED", "false").lower() == "true"
    app.state.admin_username = os.getenv("ASAS_ADMIN_USERNAME", "").strip()
    app.state.admin_password_hash = os.getenv("ASAS_ADMIN_PASSWORD_HASH", "").strip()
    app.state.session_ttl = int(os.getenv("ASAS_SESSION_TTL_SECONDS", "1800"))
    app.state.users_by_login, app.state.users_by_id = load_provisioned_users(
        os.getenv("ASAS_USERS_FILE"), app.state.admin_username, app.state.admin_password_hash,
    )
    if app.state.auth_enabled and not app.state.users_by_login:
        raise RuntimeError("Asas authentication is enabled but administrator credentials are not provisioned")
    operational_url = os.getenv("ASAS_OPERATIONAL_DATABASE_URL", "").strip()
    app.state.operational_engine = make_operational_engine(operational_url) if operational_url else None
    app.state.operational_sessions = operational_session_factory(app.state.operational_engine) if operational_url else None
    if app.state.operational_engine:
        initialize_operational_database(app.state.operational_engine)
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
        return app.state.sessions.get(request.cookies.get(SESSION_COOKIE))

    def current_user(request: Request):
        current = active_session(request)
        return app.state.users_by_id.get(current.principal_id) if current else None

    def principal_payload(user) -> dict:
        return {"login_name": user.username, "roles": list(user.roles),
                "permissions": list(user.permissions),
                "allowed_locations": list(user.allowed_locations), "posting_enabled": False}

    def location_allowed(user, location_code: str) -> bool:
        allowed = set(user.allowed_locations)
        return "*" in allowed or location_code.upper() in allowed

    def operational_session_dependency():
        if app.state.operational_sessions is None:
            raise HTTPException(status_code=503, detail="Operational database is not configured")
        with app.state.operational_sessions() as operational_session:
            yield operational_session

    def audit(session: Session, snapshot_id: int, event_type: str, outcome: str, request: Request) -> None:
        client = request.client.host if request.client else "unknown"
        session.add(ErpAuditEvent(
            snapshot_id=snapshot_id,
            event_key=f"asas-auth:{uuid.uuid4()}",
            event_type=event_type,
            actor_type="provisioned_preview_admin",
            details={"outcome": outcome, "client": client, "posting_enabled": False},
        ))
        session.commit()

    @app.middleware("http")
    async def preview_safety(request: Request, call_next):
        auth_posts = {"/api/v1/auth/login", "/api/v1/auth/logout"}
        operational_mutation = (request.url.path.startswith("/api/v1/drafts")
                                or request.url.path.startswith("/api/v1/journal-batches")
                                or request.url.path.startswith("/api/v1/inventory-documents")
                                or request.url.path.startswith("/api/v1/goods-receipts")
                                or request.url.path.startswith("/api/v1/sales-returns")) and request.method in {"POST", "PUT"}
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path not in auth_posts and not operational_mutation:
            return JSONResponse(
                status_code=405,
                content={"detail": "Read-only clone preview: operational writes are not enabled"},
                headers={"Allow": "GET, HEAD, OPTIONS"},
            )
        public_api = {"/api/v1/health", "/api/v1/auth/login", "/api/v1/auth/session"}
        if (app.state.auth_enabled and request.url.path.startswith("/api/v1/")
                and request.url.path not in public_api and active_session(request) is None):
            return JSONResponse(status_code=401, content={"detail": "Asas ERP authentication required"})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'"
        return response

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
        response.set_cookie(SESSION_COOKIE, token, max_age=app.state.session_ttl, httponly=True,
                            secure=False, samesite="strict", path="/")
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
        token = request.cookies.get(SESSION_COOKIE)
        current = app.state.sessions.get(token)
        if not current:
            raise HTTPException(status_code=401, detail="Authentication required")
        if request.headers.get("x-csrf-token") != current.csrf_token:
            raise HTTPException(status_code=403, detail="CSRF validation failed")
        snapshot_id = session.scalar(select(SourceSnapshot.id).where(SourceSnapshot.name == selected_snapshot))
        app.state.sessions.revoke(token)
        if snapshot_id:
            audit(session, snapshot_id, "auth.logout", "success", request)
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(SESSION_COOKIE, path="/", samesite="strict")
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
            "posting_enabled": False,
            "hr_payroll_enabled": False,
            "authentication_enabled": app.state.auth_enabled,
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
                          session: Session = Depends(session_dependency)):
        user = current_user(request)
        rows = [row for row in session.execute(select(ErpLocation.code, ErpLocation.name).where(
            ErpLocation.snapshot_id == snapshot.id).order_by(ErpLocation.code)).all()
                if user and location_allowed(user, row.code)]
        return {"items": [dict(row._mapping) for row in rows]}

    @app.get("/api/v1/selectors/parties")
    def party_selector(kind: str = Query(pattern="^(customer|supplier)$"), q: str = Query("", max_length=120),
                       snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency)):
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
                         snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency)):
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

    def require_csrf(request: Request, permission: str):
        current = active_session(request)
        if not app.state.auth_enabled or not current:
            raise HTTPException(status_code=401, detail="Authentication required")
        if request.headers.get("x-csrf-token") != current.csrf_token:
            raise HTTPException(status_code=403, detail="CSRF validation failed")
        user = current_user(request)
        if not user or permission not in user.permissions:
            raise HTTPException(status_code=403, detail=f"Permission {permission} is required")
        return user

    def prepare_draft(payload: DraftRequest, session: Session, user):
        snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == selected_snapshot))
        location = session.execute(select(ErpLocation.code, ErpLocation.name).where(
            ErpLocation.snapshot_id == snapshot.id,
            or_(func.lower(ErpLocation.code) == payload.location_code.casefold(),
                func.lower(ErpLocation.name) == payload.location_code.casefold()))).first()
        if not location:
            raise HTTPException(status_code=422, detail="Location is not present in the cloned location master")
        if not location_allowed(user, location[0]):
            raise HTTPException(status_code=403, detail="Location is outside the user's operational scope")
        expected_kind = "customer" if payload.document_type == "sale" else "supplier"
        party = session.execute(select(ErpParty.party_code, ErpParty.legal_or_business_name).where(
            ErpParty.snapshot_id == snapshot.id, ErpParty.party_code == payload.party_code,
            ErpParty.party_kind.in_((expected_kind, "both")))).first()
        if not party and app.state.delta_overlay:
            party = next(((row["party_code"], row["legal_or_business_name"])
                          for row in app.state.delta_overlay.party_records(expected_kind)
                          if row["party_code"] == payload.party_code), None)
        if not party:
            raise HTTPException(status_code=422, detail=f"{expected_kind.title()} is not present in the cloned master")
        prepared_lines = []
        for item in payload.lines:
            product = session.execute(select(
                ErpProductMaster.sku, ErpProductMaster.name,
                ErpProductMaster.purchase_price_evidence, ErpProductMaster.selling_price_evidence,
                ErpProductUom.source_base_uom, ErpProductUom.canonical_base_uom,
                ErpProductUom.factor_to_base_snapshot, ErpProductUom.conversion_status,
            ).outerjoin(ErpProductUom, ErpProductUom.product_id == ErpProductMaster.id).where(
                ErpProductMaster.snapshot_id == snapshot.id, ErpProductMaster.sku == item.sku)).first()
            if not product and app.state.delta_overlay:
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
        location, party, prepared_lines = prepare_draft(payload, session, user)
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
        location, party, lines = prepare_draft(payload, session, user)
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
        requested_locations = [payload.location_code]
        if payload.destination_location_code:
            requested_locations.append(payload.destination_location_code)
        locations = set(clone_session.scalars(select(ErpLocation.code).where(
            ErpLocation.snapshot_id == snapshot.id,
            ErpLocation.code.in_(requested_locations),
        )))
        if locations != set(requested_locations):
            raise HTTPException(status_code=422, detail="Every inventory location must exist in the cloned master")
        if any(not location_allowed(user, code) for code in requested_locations):
            raise HTTPException(status_code=403, detail="Inventory location is outside the user's operational scope")
        prepared: list[dict] = []
        for item in payload.lines:
            product = clone_session.execute(select(
                ErpProductMaster.sku, ErpProductMaster.name, ErpProductMaster.purchase_price_evidence,
                ErpProductUom.source_base_uom, ErpProductUom.canonical_base_uom,
                ErpProductUom.factor_to_base_snapshot, ErpProductUom.conversion_status,
            ).outerjoin(ErpProductUom, ErpProductUom.product_id == ErpProductMaster.id).where(
                ErpProductMaster.snapshot_id == snapshot.id, ErpProductMaster.sku == item.sku,
            )).first()
            if not product:
                raise HTTPException(status_code=422, detail=f"Product SKU {item.sku} is not present in the cloned master")
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

    def prepare_goods_receipt(payload: GoodsReceiptRequest, clone_session: Session, user) -> tuple[str, list[dict]]:
        snapshot = clone_session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == selected_snapshot))
        if not snapshot:
            raise HTTPException(status_code=404, detail="Configured BizModo clone snapshot is unavailable")
        if not location_allowed(user, payload.location_code):
            raise HTTPException(status_code=403, detail="Receipt location is outside the user's operational scope")
        if not clone_session.scalar(select(ErpLocation.id).where(
                ErpLocation.snapshot_id == snapshot.id, ErpLocation.code == payload.location_code)):
            raise HTTPException(status_code=422, detail="Receipt location is not present in the cloned master")
        supplier = clone_session.execute(select(ErpParty.legal_or_business_name, ErpParty.party_kind).where(
            ErpParty.snapshot_id == snapshot.id, ErpParty.party_code == payload.supplier_code)).first()
        if not supplier or supplier.party_kind not in {"supplier", "both"}:
            raise HTTPException(status_code=422, detail="Supplier is not present in the cloned supplier master")
        prepared: list[dict] = []
        for item in payload.lines:
            product = clone_session.execute(select(
                ErpProductMaster.name, ErpProductMaster.purchase_price_evidence,
                ErpProductUom.source_base_uom, ErpProductUom.canonical_base_uom,
                ErpProductUom.factor_to_base_snapshot, ErpProductUom.conversion_status,
            ).outerjoin(ErpProductUom, ErpProductUom.product_id == ErpProductMaster.id).where(
                ErpProductMaster.snapshot_id == snapshot.id, ErpProductMaster.sku == item.sku)).first()
            if not product:
                raise HTTPException(status_code=422, detail=f"Product SKU {item.sku} is not present in the cloned master")
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
        return supplier.legal_or_business_name, prepared

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
        supplier_name, lines = prepare_goods_receipt(payload, clone_session, user)
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
        supplier_name, lines = prepare_goods_receipt(payload, clone_session, user)
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
        if not clone_session.scalar(select(ErpLocation.id).where(
                ErpLocation.snapshot_id == snapshot.id, ErpLocation.code == payload.location_code)):
            raise HTTPException(status_code=422, detail="Return location is not present in the cloned master")
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
            product = clone_session.execute(select(
                ErpProductMaster.name, ErpProductMaster.purchase_price_evidence,
                ErpProductMaster.selling_price_evidence, ErpProductUom.source_base_uom,
                ErpProductUom.canonical_base_uom, ErpProductUom.factor_to_base_snapshot,
                ErpProductUom.conversion_status,
            ).outerjoin(ErpProductUom, ErpProductUom.product_id == ErpProductMaster.id).where(
                ErpProductMaster.snapshot_id == snapshot.id, ErpProductMaster.sku == item.sku)).first()
            if not product:
                raise HTTPException(status_code=422, detail=f"Product SKU {item.sku} is not present in the cloned master")
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
        return customer.legal_or_business_name, prepared

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
        return {"source_system": snapshot.source_system, "source_snapshot": snapshot.name,
                "clone_remains_immutable": True, "promotion_executed": False,
                "cloned_counts": cloned_counts, "registry": promotion_control_counts(operational_session),
                "activation_gates": PROMOTION_GATES,
                "lifecycle_policy": {
                    "promoted_master_active": lifecycle_actions("master", "active", referenced=True, source_promoted=True),
                    "erp_draft_transaction": lifecycle_actions("transaction", "draft"),
                    "posted_transaction": lifecycle_actions("transaction", "posted"),
                    "imported_history": lifecycle_actions("transaction", "historical"),
                }}

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
            for key in ("customers", "suppliers", "products", "sales", "purchases", "stock_transfers"):
                latest_counts[key] = overlay.counts[key]
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
                 snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency)):
        filters = [ErpProductMaster.snapshot_id == snapshot.id]
        rows = session.execute(select(
            ErpProductMaster.id, ErpProductMaster.sku, ErpProductMaster.name,
            ErpProductMaster.category_name, ErpProductMaster.brand_name,
            ErpProductMaster.purchase_price_evidence, ErpProductMaster.selling_price_evidence,
            ErpProductMaster.master_status,
        ).where(*filters)).all()
        overlay = app.state.delta_overlay
        return _merge_records(rows, overlay.product_records() if overlay else [], "sku", q, "sku", limit, offset)

    def parties(kind: str, limit: int, offset: int, q: str | None, snapshot: SourceSnapshot, session: Session):
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
                  snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency)):
        return parties("customer", limit, offset, q, snapshot, session)

    @app.get("/api/v1/suppliers")
    def suppliers(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                  q: str | None = Query(None, max_length=120),
                  snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency)):
        return parties("supplier", limit, offset, q, snapshot, session)

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
        return _merge_records(rows, overlay_rows, "document_no", q, "occurred_at", limit, offset, reverse=True)

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

    @app.get("/api/v1/accounting")
    def accounting(snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency),
                   operational_session=Depends(operational_session_dependency)):
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
        return {"opening_controls": [dict(row._mapping) for row in openings], "gl_accounts": accounts,
                "staged_opening_controls": [dict(row._mapping) for row in staged],
                "open_financial_exceptions": finance_exceptions,
                "posting_enabled": False, "currency": "AED"}

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
