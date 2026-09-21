from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .enterprise_setup import OperationalVan
from .operational import MONEY, OperationalAuditEvent, OperationalBase, OperationalStockPosition, utc_now
from .operational_masters import OperationalPartyMaster, OperationalProductMaster


class OperationalVanRoute(OperationalBase):
    __tablename__ = "operational_van_routes"
    __table_args__ = (
        UniqueConstraint("route_no", name="uq_van_route_no"),
        CheckConstraint("status IN ('planned','load_submitted','load_approved','active','close_submitted','closed')", name="ck_van_route_status"),
        CheckConstraint("opening_float >= 0 AND expected_cash >= 0", name="ck_van_route_cash"),
        CheckConstraint("posting_enabled = false", name="ck_van_route_no_posting"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    route_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    route_no: Mapped[str] = mapped_column(String(50), nullable=False)
    van_id: Mapped[int] = mapped_column(ForeignKey("operational_vans.id"), nullable=False, index=True)
    route_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    driver_name: Mapped[str] = mapped_column(String(200), nullable=False)
    device_id: Mapped[str] = mapped_column(String(100), nullable=False)
    opening_float: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    expected_cash: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    counted_cash: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    variance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(30), default="planned", nullable=False, index=True)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    close_approved_by: Mapped[str | None] = mapped_column(String(200))
    close_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    van: Mapped[OperationalVan] = relationship()
    stops: Mapped[list["OperationalVanRouteStop"]] = relationship(cascade="all, delete-orphan")
    loads: Mapped[list["OperationalVanLoadLine"]] = relationship(cascade="all, delete-orphan")
    events: Mapped[list["OperationalVanOfflineEvent"]] = relationship(cascade="all, delete-orphan")


class OperationalVanRouteStop(OperationalBase):
    __tablename__ = "operational_van_route_stops"
    __table_args__ = (UniqueConstraint("route_id", "sequence_no", name="uq_van_route_stop"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("operational_van_routes.id", ondelete="CASCADE"), nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    customer_code: Mapped[str] = mapped_column(String(80), nullable=False)
    customer_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)


class OperationalVanLoadLine(OperationalBase):
    __tablename__ = "operational_van_load_lines"
    __table_args__ = (
        UniqueConstraint("route_id", "sku", name="uq_van_route_load_sku"),
        CheckConstraint("quantity > 0 AND quantity_base > 0", name="ck_van_load_quantity"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("operational_van_routes.id", ondelete="CASCADE"), nullable=False)
    sku: Mapped[str] = mapped_column(String(160), nullable=False)
    product_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    uom: Mapped[str] = mapped_column(String(80), nullable=False)
    factor_to_base_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    loaded_from_location: Mapped[str] = mapped_column(String(80), nullable=False)
    stock_available_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))


class OperationalVanOfflineEvent(OperationalBase):
    __tablename__ = "operational_van_offline_events"
    __table_args__ = (
        UniqueConstraint("device_id", "client_reference", name="uq_van_offline_event"),
        CheckConstraint("event_type IN ('sale','return','collection')", name="ck_van_event_type"),
        CheckConstraint("amount >= 0 AND tax_amount >= 0", name="ck_van_event_amount"),
        CheckConstraint("posting_enabled = false", name="ck_van_event_no_posting"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    route_id: Mapped[int] = mapped_column(ForeignKey("operational_van_routes.id", ondelete="CASCADE"), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(100), nullable=False)
    client_reference: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    customer_code: Mapped[str] = mapped_column(String(80), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    payment_method: Mapped[str | None] = mapped_column(String(20))
    evidence_reference: Mapped[str | None] = mapped_column(String(300))
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    synced_by: Mapped[str] = mapped_column(String(200), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)


def create_route(session: Session, *, van_code: str, route_date: date, driver_name: str, device_id: str,
                 opening_float: Decimal, customer_codes: list[str], actor: str) -> OperationalVanRoute:
    van=session.scalar(select(OperationalVan).where(OperationalVan.van_code==van_code.strip().upper()))
    if not van: raise ValueError("Van master not found")
    if session.scalar(select(OperationalVanRoute).where(OperationalVanRoute.van_id==van.id,
        OperationalVanRoute.route_date==route_date, OperationalVanRoute.status!="closed")):
        raise ValueError("This van already has an open route for the date")
    if not customer_codes: raise ValueError("A van route requires at least one customer stop")
    customers=[]
    for code in customer_codes:
        row=session.scalar(select(OperationalPartyMaster).where(OperationalPartyMaster.party_code==code,
            OperationalPartyMaster.party_kind.in_(("customer","both")), OperationalPartyMaster.status=="active"))
        if not row: raise ValueError(f"Active customer not found: {code}")
        customers.append(row)
    key=str(uuid.uuid4()); opening=_money(opening_float)
    route=OperationalVanRoute(route_key=key, route_no=f"VAN-{route_date:%Y%m%d}-{key[:7].upper()}",
        van_id=van.id, route_date=route_date, driver_name=driver_name.strip(), device_id=device_id.strip(),
        opening_float=opening, expected_cash=opening, created_by=actor, posting_enabled=False)
    for index, customer in enumerate(customers,1):
        route.stops.append(OperationalVanRouteStop(sequence_no=index,customer_code=customer.party_code,
            customer_name_snapshot=customer.legal_or_business_name))
    session.add(route); session.flush(); _audit(session,"van.route.created",actor,key,route.route_no); session.commit(); return route


def submit_load(session: Session, *, route_key: str, source_location: str, lines: list[dict],
                expected_revision: int, actor: str) -> OperationalVanRoute:
    route=_route(session,route_key); _expect(route,"planned",expected_revision)
    if not lines: raise ValueError("Van load-out requires at least one item")
    route.loads.clear()
    for value in lines:
        product=session.scalar(select(OperationalProductMaster).where(OperationalProductMaster.sku==str(value["sku"]),OperationalProductMaster.status=="active"))
        if not product: raise ValueError(f"Active product not found: {value['sku']}")
        qty=Decimal(str(value["quantity"])); base=qty*Decimal(product.factor_to_base)
        position=session.scalar(select(OperationalStockPosition).where(OperationalStockPosition.location_code==source_location.upper(),OperationalStockPosition.sku==product.sku))
        available=None if not position or not position.availability_enabled else Decimal(position.quantity_on_hand)-Decimal(position.quantity_reserved)
        if available is not None and base>available: raise ValueError(f"Insufficient available stock for {product.sku}")
        route.loads.append(OperationalVanLoadLine(sku=product.sku,product_name_snapshot=product.name,quantity=qty,
            uom=product.base_uom,factor_to_base_snapshot=product.factor_to_base,quantity_base=base,
            loaded_from_location=source_location.upper(),stock_available_snapshot=available))
    route.status="load_submitted"; route.revision+=1; _audit(session,"van.load.submitted",actor,route.route_key,f"{len(lines)} lines; no stock posting"); session.commit(); return route


def transition_route(session: Session, *, route_key: str, action: str, expected_revision: int,
                     note: str, actor: str, counted_cash: Decimal | None = None) -> OperationalVanRoute:
    route=_route(session,route_key); transitions={("load_submitted","approve_load"):"load_approved",("load_approved","start"):"active",("active","submit_close"):"close_submitted",("close_submitted","approve_close"):"closed"}
    target=transitions.get((route.status,action))
    if not target: raise ValueError(f"Action {action} is not allowed from {route.status}")
    if route.revision!=expected_revision: raise ValueError("Van route revision is stale")
    if action in {"approve_load","approve_close"} and route.created_by==actor: raise PermissionError("Maker-checker control prevents route self-approval")
    if action=="submit_close":
        if counted_cash is None: raise ValueError("Counted cash is required")
        route.counted_cash=_money(counted_cash); route.variance=_money(route.counted_cash-route.expected_cash); route.close_note=note.strip()
    if action=="approve_load": route.approved_by=actor
    if action=="approve_close": route.close_approved_by=actor; route.close_note=f"{route.close_note or ''}\nApproval: {note.strip()}"
    route.status=target; route.revision+=1; _audit(session,f"van.route.{action}",actor,route.route_key,f"{target}; {note.strip()}; no posting"); session.commit(); return route


def sync_offline_event(session: Session, *, route_key: str, device_id: str, client_reference: str,
                       event_type: str, customer_code: str, captured_at: datetime, payment_method: str | None,
                       amount: Decimal | None, evidence_reference: str | None, lines: list[dict], actor: str) -> tuple[OperationalVanOfflineEvent,bool]:
    existing=session.scalar(select(OperationalVanOfflineEvent).where(OperationalVanOfflineEvent.device_id==device_id,OperationalVanOfflineEvent.client_reference==client_reference))
    if existing: return existing,True
    route=_route(session,route_key)
    if route.status!="active" or route.device_id!=device_id: raise ValueError("Offline event requires the active route and assigned device")
    if customer_code not in {x.customer_code for x in route.stops}: raise ValueError("Customer is not on this route")
    if event_type not in {"sale","return","collection"}: raise ValueError("Unsupported van event")
    tax=Decimal("0"); total=_money(amount or 0); normalized=[]
    if event_type in {"sale","return"}:
        if not lines: raise ValueError("Van sale/return requires item lines")
        net=Decimal("0")
        loaded={x.sku:x for x in route.loads}
        for item in lines:
            product=session.scalar(select(OperationalProductMaster).where(OperationalProductMaster.sku==str(item["sku"]),OperationalProductMaster.status=="active"))
            if not product or product.sku not in loaded: raise ValueError(f"Product is not in the approved van load: {item['sku']}")
            qty=Decimal(str(item["quantity"])); line_net=_money(qty*Decimal(product.selling_price)); line_tax=_money(line_net*Decimal(product.tax_rate)/100)
            net+=line_net; tax+=line_tax; normalized.append({"sku":product.sku,"name":product.name,"quantity":str(qty),"uom":product.base_uom,"net":str(line_net),"tax":str(line_tax)})
        total=_money(net+tax)
    if event_type=="collection" and total<=0: raise ValueError("Collection amount must be positive")
    if event_type in {"sale","collection"} and payment_method not in {"cash","card","bank"}: raise ValueError("Payment method is required")
    if event_type=="return" and not evidence_reference: raise ValueError("Return evidence reference is required")
    row=OperationalVanOfflineEvent(event_key=str(uuid.uuid4()),route_id=route.id,device_id=device_id,
        client_reference=client_reference,event_type=event_type,customer_code=customer_code,captured_at=captured_at,
        payload_json=json.dumps(normalized,sort_keys=True),amount=total,tax_amount=_money(tax),payment_method=payment_method,
        evidence_reference=evidence_reference,posting_enabled=False,synced_by=actor)
    session.add(row)
    if payment_method=="cash": route.expected_cash=_money(route.expected_cash+(total if event_type!="return" else -total))
    route.revision+=1; _audit(session,f"van.offline.{event_type}.synced",actor,row.event_key,f"{client_reference}; AED {total}; no posting"); session.commit(); return row,False


def van_workspace_payload(session: Session) -> dict:
    routes=list(session.scalars(select(OperationalVanRoute).order_by(OperationalVanRoute.created_at.desc())))
    events=list(session.scalars(select(OperationalVanOfflineEvent).order_by(OperationalVanOfflineEvent.synced_at.desc())))
    return {"controls":{"routes":len(routes),"active_routes":sum(x.status=="active" for x in routes),"pending_approvals":sum(x.status in {"load_submitted","close_submitted"} for x in routes),"synced_events":len(events),"posting_enabled":False},
        "vans":[{"van_code":x.van_code,"name":x.name,"status":x.status} for x in session.scalars(select(OperationalVan).order_by(OperationalVan.van_code))],
        "customers":[{"code":x.party_code,"name":x.legal_or_business_name} for x in session.scalars(select(OperationalPartyMaster).where(OperationalPartyMaster.party_kind.in_(("customer","both")),OperationalPartyMaster.status=="active").order_by(OperationalPartyMaster.legal_or_business_name).limit(500))],
        "products":[{"sku":x.sku,"name":x.name,"uom":x.base_uom,"price":x.selling_price} for x in session.scalars(select(OperationalProductMaster).where(OperationalProductMaster.status=="active").order_by(OperationalProductMaster.name).limit(500))],
        "routes":[{"route_key":x.route_key,"route_no":x.route_no,"van_code":x.van.van_code,"route_date":x.route_date,"driver_name":x.driver_name,"device_id":x.device_id,"status":x.status,"opening_float":x.opening_float,"expected_cash":x.expected_cash,"counted_cash":x.counted_cash,"variance":x.variance,"created_by":x.created_by,"approved_by":x.approved_by,"close_approved_by":x.close_approved_by,"revision":x.revision,"stops":[{"sequence":s.sequence_no,"customer_code":s.customer_code,"customer_name":s.customer_name_snapshot} for s in x.stops],"loads":[{"sku":l.sku,"product_name":l.product_name_snapshot,"quantity":l.quantity,"uom":l.uom} for l in x.loads]} for x in routes],
        "events":[{"event_key":x.event_key,"route_key":next(r.route_key for r in routes if r.id==x.route_id),"client_reference":x.client_reference,"event_type":x.event_type,"customer_code":x.customer_code,"amount":x.amount,"tax_amount":x.tax_amount,"payment_method":x.payment_method,"captured_at":x.captured_at,"synced_at":x.synced_at} for x in events],
        "boundary":{"offline_idempotency":True,"test_data_only":True,"stock_posting_performed":False,"accounting_posting_performed":False,"permanent_posting_enabled":False}}


def _route(session: Session,key: str) -> OperationalVanRoute:
    row=session.scalar(select(OperationalVanRoute).where(OperationalVanRoute.route_key==key).with_for_update())
    if not row: raise ValueError("Van route not found")
    return row


def _expect(route: OperationalVanRoute,status: str,revision: int) -> None:
    if route.status!=status: raise ValueError(f"Van route must be {status}")
    if route.revision!=revision: raise ValueError("Van route revision is stale")


def _audit(session: Session,event_type: str,actor: str,key: str,detail: str) -> None:
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()),event_type=event_type,actor=actor,resource_key=key,detail=detail))
