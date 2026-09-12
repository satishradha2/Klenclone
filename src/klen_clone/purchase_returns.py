from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .operational import MONEY, OperationalAuditEvent, OperationalBase, OperationalFiscalPeriod, OperationalStockPosition, utc_now


class OperationalPurchaseReturn(OperationalBase):
    __tablename__ = "operational_purchase_returns"
    __table_args__ = (
        CheckConstraint("source_reference_type IN ('goods_receipt','purchase_invoice')", name="ck_purchase_return_source_type"),
        CheckConstraint("status IN ('draft','submitted','approved','cancelled','posted','reversed')", name="ck_purchase_return_status"),
        CheckConstraint("posting_enabled = false", name="ck_purchase_return_no_posting"),
        CheckConstraint("subtotal >= 0 AND tax_amount >= 0 AND total_amount >= 0", name="ck_purchase_return_totals"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    return_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    return_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    supplier_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    supplier_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_reference_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_reference_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    return_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), default="AED", nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False, index=True)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    state_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    state_changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    lines: Mapped[list["OperationalPurchaseReturnLine"]] = relationship(back_populates="purchase_return", cascade="all, delete-orphan", order_by="OperationalPurchaseReturnLine.line_no")
    debit_note: Mapped["OperationalPurchaseDebitNote | None"] = relationship(back_populates="purchase_return", cascade="all, delete-orphan", uselist=False)


class OperationalPurchaseReturnLine(OperationalBase):
    __tablename__ = "operational_purchase_return_lines"
    __table_args__ = (
        UniqueConstraint("purchase_return_id", "line_no", name="uq_purchase_return_line"),
        CheckConstraint("source_received_quantity > 0 AND quantity > 0", name="ck_purchase_return_source_quantity"),
        CheckConstraint("supplier_return_quantity >= 0 AND internal_writeoff_quantity >= 0 AND supplier_return_quantity + internal_writeoff_quantity = quantity", name="ck_purchase_return_disposition"),
        CheckConstraint("factor_to_base_snapshot > 0 AND quantity_base > 0", name="ck_purchase_return_base_quantity"),
        CheckConstraint("unit_price >= 0 AND unit_cost_snapshot >= 0 AND tax_rate >= 0 AND tax_rate <= 100", name="ck_purchase_return_values"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_return_id: Mapped[int] = mapped_column(ForeignKey("operational_purchase_returns.id", ondelete="CASCADE"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    product_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    source_received_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    supplier_return_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    internal_writeoff_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    uom: Mapped[str] = mapped_column(String(80), nullable=False)
    canonical_uom: Mapped[str] = mapped_column(String(80), nullable=False)
    factor_to_base_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    unit_cost_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    disposition_reason: Mapped[str | None] = mapped_column(String(500))
    purchase_return: Mapped[OperationalPurchaseReturn] = relationship(back_populates="lines")


class OperationalPurchaseReturnReservation(OperationalBase):
    __tablename__ = "operational_purchase_return_reservations"
    __table_args__ = (UniqueConstraint("purchase_return_line_id", name="uq_purchase_return_reservation_line"), CheckConstraint("quantity_base > 0", name="ck_purchase_return_reservation_quantity"), CheckConstraint("status IN ('active','released','consumed')", name="ck_purchase_return_reservation_status"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reservation_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    purchase_return_id: Mapped[int] = mapped_column(ForeignKey("operational_purchase_returns.id"), nullable=False, index=True)
    purchase_return_line_id: Mapped[int] = mapped_column(ForeignKey("operational_purchase_return_lines.id"), nullable=False)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OperationalPurchaseDebitNote(OperationalBase):
    __tablename__ = "operational_purchase_debit_notes"
    __table_args__ = (UniqueConstraint("purchase_return_id", name="uq_debit_note_purchase_return"), CheckConstraint("status IN ('approved','posted','reversed')", name="ck_purchase_debit_note_status"), CheckConstraint("posting_enabled = false", name="ck_purchase_debit_note_no_posting"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    debit_note_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    debit_note_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    purchase_return_id: Mapped[int] = mapped_column(ForeignKey("operational_purchase_returns.id"), nullable=False, index=True)
    supplier_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_reference_key: Mapped[str] = mapped_column(String(160), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approved_by: Mapped[str] = mapped_column(String(200), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    purchase_return: Mapped[OperationalPurchaseReturn] = relationship(back_populates="debit_note")


class OperationalPurchaseReturnWorkflowEvent(OperationalBase):
    __tablename__ = "operational_purchase_return_workflow_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    purchase_return_id: Mapped[int] = mapped_column(ForeignKey("operational_purchase_returns.id"), nullable=False, index=True)
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


def _normalise_line(raw: dict) -> dict:
    source_qty=Decimal(str(raw["source_received_quantity"])); quantity=Decimal(str(raw["quantity"])); supplier_qty=Decimal(str(raw["supplier_return_quantity"])); writeoff=Decimal(str(raw["internal_writeoff_quantity"])); factor=Decimal(str(raw["factor_to_base_snapshot"])); price=Decimal(str(raw["unit_price"])); tax_rate=Decimal(str(raw["tax_rate"])); cost=Decimal(str(raw["unit_cost_snapshot"]))
    if source_qty<=0 or quantity<=0 or quantity>source_qty: raise ValueError("Purchase return quantity must be positive and cannot exceed its source received quantity")
    if supplier_qty<0 or writeoff<0 or supplier_qty+writeoff!=quantity: raise ValueError("Return disposition must conserve quantity: supplier return plus internal write-off must equal quantity")
    if factor<=0 or price<0 or cost<0 or tax_rate<0 or tax_rate>100: raise ValueError("Purchase return factor, price, cost or tax is invalid")
    if writeoff>0 and not (raw.get("disposition_reason") or "").strip(): raise ValueError("A disposition reason is required for internal write-off quantity")
    net=(supplier_qty*price).quantize(MONEY,rounding=ROUND_HALF_UP); tax=(net*tax_rate/Decimal("100")).quantize(MONEY,rounding=ROUND_HALF_UP)
    return dict(raw,source_received_quantity=source_qty,quantity=quantity,supplier_return_quantity=supplier_qty,internal_writeoff_quantity=writeoff,factor_to_base_snapshot=factor,quantity_base=quantity*factor,unit_price=price,tax_rate=tax_rate,net_amount=net,tax_amount=tax,gross_amount=net+tax,unit_cost_snapshot=cost,disposition_reason=(raw.get("disposition_reason") or "").strip() or None)


def _replace_lines(document: OperationalPurchaseReturn, lines: list[dict]) -> None:
    document.lines.clear()
    for number,raw in enumerate(lines,1): document.lines.append(OperationalPurchaseReturnLine(line_no=number,**_normalise_line(raw)))


def _set_totals(document: OperationalPurchaseReturn) -> None:
    document.subtotal=sum((x.net_amount for x in document.lines),Decimal("0")); document.tax_amount=sum((x.tax_amount for x in document.lines),Decimal("0")); document.total_amount=document.subtotal+document.tax_amount


def create_purchase_return(session: Session, *, supplier_code: str, supplier_name_snapshot: str, location_code: str, source_reference_type: str, source_reference_key: str, return_date: date, reason_code: str, notes: str|None, actor: str, lines: list[dict]) -> OperationalPurchaseReturn:
    if source_reference_type not in {"goods_receipt","purchase_invoice"}: raise ValueError("Purchase return source must be a goods receipt or purchase invoice")
    if not source_reference_key.strip() or not lines: raise ValueError("Source reference and at least one purchase return line are required")
    key=str(uuid.uuid4()); document=OperationalPurchaseReturn(return_key=key,return_no=f"PR-{key[:8].upper()}",supplier_code=supplier_code,supplier_name_snapshot=supplier_name_snapshot,location_code=location_code,source_reference_type=source_reference_type,source_reference_key=source_reference_key.strip(),return_date=return_date,reason_code=reason_code,subtotal=0,tax_amount=0,total_amount=0,status="draft",posting_enabled=False,notes=notes,created_by=actor,state_changed_by=actor)
    _replace_lines(document,lines); _set_totals(document); session.add(document); session.flush(); session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()),event_type="purchase_return.created",actor=actor,resource_key=document.return_key,detail=f"{document.return_no}; {len(lines)} lines; posting disabled")); session.commit(); return document


def replace_purchase_return(session: Session, document: OperationalPurchaseReturn, *, expected_revision: int, supplier_code: str, supplier_name_snapshot: str, location_code: str, source_reference_type: str, source_reference_key: str, return_date: date, reason_code: str, notes: str|None, actor: str, lines: list[dict]) -> OperationalPurchaseReturn:
    if document.status!="draft": raise ValueError("Only draft-state purchase returns can be edited")
    if document.revision!=expected_revision: raise ValueError(f"Purchase return revision conflict; current revision is {document.revision}")
    if source_reference_type not in {"goods_receipt","purchase_invoice"} or not source_reference_key.strip() or not lines: raise ValueError("Valid source reference and lines are required")
    document.supplier_code=supplier_code; document.supplier_name_snapshot=supplier_name_snapshot; document.location_code=location_code; document.source_reference_type=source_reference_type; document.source_reference_key=source_reference_key.strip(); document.return_date=return_date; document.reason_code=reason_code; document.notes=notes; document.revision+=1; document.state_changed_at=utc_now(); document.state_changed_by=actor
    document.lines.clear(); session.flush(); _replace_lines(document,lines); _set_totals(document); session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()),event_type="purchase_return.edited",actor=actor,resource_key=document.return_key,detail=f"{document.return_no}; revision {document.revision}; posting disabled")); session.commit(); return document


def list_purchase_returns(session: Session, *, allowed_locations: tuple[str,...] = ("*",), limit: int=100) -> list[OperationalPurchaseReturn]:
    query=select(OperationalPurchaseReturn)
    if "*" not in allowed_locations: query=query.where(OperationalPurchaseReturn.location_code.in_(allowed_locations))
    return list(session.scalars(query.order_by(OperationalPurchaseReturn.created_at.desc()).limit(limit)))


def _reserve(session: Session, document: OperationalPurchaseReturn) -> None:
    for line in document.lines:
        prior=session.scalar(select(func.coalesce(func.sum(OperationalPurchaseReturnLine.quantity),0)).join(OperationalPurchaseReturn).where(OperationalPurchaseReturn.source_reference_type==document.source_reference_type,OperationalPurchaseReturn.source_reference_key==document.source_reference_key,OperationalPurchaseReturn.id!=document.id,OperationalPurchaseReturn.status.in_(("submitted","approved","posted")),OperationalPurchaseReturnLine.sku==line.sku)) or Decimal("0")
        if prior+line.quantity>line.source_received_quantity: raise ValueError(f"Return quantity exceeds remaining source quantity for {line.sku}")
        position=session.scalar(select(OperationalStockPosition).where(OperationalStockPosition.location_code==document.location_code,OperationalStockPosition.sku==line.sku).with_for_update())
        if not position or not position.availability_enabled: raise ValueError(f"Approved stock is unavailable for {line.sku} at {document.location_code}")
        if position.canonical_uom.casefold()!=line.canonical_uom.casefold(): raise ValueError(f"Stock UOM mismatch for {line.sku}")
        available=position.quantity_on_hand-position.quantity_reserved
        if available<line.quantity_base: raise ValueError(f"Insufficient available stock for {line.sku}: required {line.quantity_base}, available {available}")
        line.unit_cost_snapshot=position.average_unit_cost; position.quantity_reserved+=line.quantity_base; position.revision+=1; position.updated_at=utc_now()
        session.add(OperationalPurchaseReturnReservation(reservation_key=str(uuid.uuid4()),purchase_return_id=document.id,purchase_return_line_id=line.id,location_code=document.location_code,sku=line.sku,quantity_base=line.quantity_base,status="active"))


def _release(session: Session, document: OperationalPurchaseReturn) -> None:
    for reservation in session.scalars(select(OperationalPurchaseReturnReservation).where(OperationalPurchaseReturnReservation.purchase_return_id==document.id,OperationalPurchaseReturnReservation.status=="active").with_for_update()):
        position=session.scalar(select(OperationalStockPosition).where(OperationalStockPosition.location_code==reservation.location_code,OperationalStockPosition.sku==reservation.sku).with_for_update())
        if not position or position.quantity_reserved<reservation.quantity_base: raise RuntimeError(f"Purchase return reservation mismatch for {reservation.sku}")
        position.quantity_reserved-=reservation.quantity_base; position.revision+=1; position.updated_at=utc_now(); reservation.status="released"; reservation.released_at=utc_now()


def transition_purchase_return(session: Session, document: OperationalPurchaseReturn, *, expected_revision: int, action: str, actor: str, note: str|None=None) -> OperationalPurchaseReturn:
    transitions={("draft","submit"):"submitted",("draft","cancel"):"cancelled",("submitted","cancel"):"cancelled",("submitted","approve"):"approved"}
    if document.revision!=expected_revision: raise ValueError(f"Purchase return revision conflict; current revision is {document.revision}")
    target=transitions.get((document.status,action))
    if not target: raise ValueError(f"Action {action} is not allowed from {document.status}")
    if action=="approve" and document.created_by==actor: raise PermissionError("Maker-checker control prevents the creator from approving this purchase return")
    if action=="submit": _reserve(session,document)
    if action=="cancel" and document.status=="submitted": _release(session,document)
    if action=="approve":
        if document.total_amount<=0: raise ValueError("A purchase return debit note requires supplier-return quantity")
        key=str(uuid.uuid4()); document.debit_note=OperationalPurchaseDebitNote(debit_note_key=key,debit_note_no=f"DN-{key[:8].upper()}",supplier_code=document.supplier_code,source_reference_key=document.source_reference_key,subtotal=document.subtotal,tax_amount=document.tax_amount,total_amount=document.total_amount,status="approved",posting_enabled=False,approved_by=actor)
    prior=document.status; document.status=target; document.revision+=1; document.state_changed_at=utc_now(); document.state_changed_by=actor; session.add(OperationalPurchaseReturnWorkflowEvent(event_key=str(uuid.uuid4()),purchase_return_id=document.id,from_status=prior,to_status=target,actor=actor,note=note)); session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()),event_type=f"purchase_return.{action}",actor=actor,resource_key=document.return_key,detail=f"{prior} to {target}; revision {document.revision}; posting disabled")); session.commit(); return document


def rehearse_purchase_return_posting(session: Session, document: OperationalPurchaseReturn, *, actor: str) -> dict:
    if document.status!="approved" or not document.debit_note: raise ValueError("Only an approved purchase return with a debit note can be rehearsed")
    period=session.scalar(select(OperationalFiscalPeriod).where(OperationalFiscalPeriod.starts_on<=document.return_date,OperationalFiscalPeriod.ends_on>=document.return_date,OperationalFiscalPeriod.status=="open",OperationalFiscalPeriod.rehearsal_enabled.is_(True)))
    if not period: raise ValueError("Return date is not in an open rehearsal-enabled fiscal period")
    reservations={r.purchase_return_line_id:r.quantity_base for r in session.scalars(select(OperationalPurchaseReturnReservation).where(OperationalPurchaseReturnReservation.purchase_return_id==document.id,OperationalPurchaseReturnReservation.status=="active"))}
    if any(reservations.get(line.id)!=line.quantity_base for line in document.lines): raise ValueError("Active reservations do not fully cover the purchase return")
    supplier_cost=sum(((x.supplier_return_quantity*x.factor_to_base_snapshot*x.unit_cost_snapshot).quantize(MONEY,rounding=ROUND_HALF_UP) for x in document.lines),Decimal("0")); writeoff_cost=sum(((x.internal_writeoff_quantity*x.factor_to_base_snapshot*x.unit_cost_snapshot).quantize(MONEY,rounding=ROUND_HALF_UP) for x in document.lines),Decimal("0")); variance=document.subtotal-supplier_cost
    journal=[{"account":"Accounts Payable","debit":document.total_amount,"credit":Decimal("0")},{"account":"Input VAT","debit":Decimal("0"),"credit":document.tax_amount},{"account":"Inventory","debit":Decimal("0"),"credit":supplier_cost+writeoff_cost},{"account":"Inventory Write-off","debit":writeoff_cost,"credit":Decimal("0")}]
    if variance>0: journal.append({"account":"Purchase Return Variance","debit":Decimal("0"),"credit":variance})
    elif variance<0: journal.append({"account":"Purchase Return Variance","debit":-variance,"credit":Decimal("0")})
    debit=sum((x["debit"] for x in journal),Decimal("0")); credit=sum((x["credit"] for x in journal),Decimal("0"))
    if debit!=credit: raise RuntimeError("Purchase return posting rehearsal is not balanced")
    movements=[{"line_no":x.line_no,"location":document.location_code,"sku":x.sku,"quantity_base":-x.quantity_base,"canonical_uom":x.canonical_uom,"unit_cost":x.unit_cost_snapshot,"value_delta":-(x.quantity_base*x.unit_cost_snapshot).quantize(MONEY,rounding=ROUND_HALF_UP)} for x in document.lines]
    source=json.dumps({"return_key":document.return_key,"revision":document.revision,"journal":journal,"movements":movements},default=str,sort_keys=True,separators=(",",":")); fingerprint=hashlib.sha256(source.encode()).hexdigest(); session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()),event_type="purchase_return.posting_rehearsed",actor=actor,resource_key=document.return_key,detail=f"AED {debit}; {len(movements)} outgoing movements; fingerprint {fingerprint}; no posting")); session.commit()
    return {"return_key":document.return_key,"return_no":document.return_no,"debit_note_no":document.debit_note.debit_note_no,"posting_enabled":False,"period_key":period.period_key,"journal":journal,"movements":movements,"supplier_return_cost":supplier_cost,"writeoff_cost":writeoff_cost,"purchase_return_variance":variance,"debit":debit,"credit":credit,"posting_fingerprint":fingerprint,"idempotency_key":f"purchase-return:{document.return_key}:{document.revision}:{fingerprint[:20]}"}


def purchase_return_control_counts(session: Session) -> dict:
    return {"returns":session.scalar(select(func.count(OperationalPurchaseReturn.id))) or 0,"debit_notes":session.scalar(select(func.count(OperationalPurchaseDebitNote.id))) or 0,"active_reservations":session.scalar(select(func.count(OperationalPurchaseReturnReservation.id)).where(OperationalPurchaseReturnReservation.status=="active")) or 0,"posted":session.scalar(select(func.count(OperationalPurchaseDebitNote.id)).where(OperationalPurchaseDebitNote.status=="posted")) or 0}
