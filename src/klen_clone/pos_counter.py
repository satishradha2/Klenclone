from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .operational import MONEY, OperationalAuditEvent, OperationalBase, OperationalStockPosition, utc_now
from .operational_masters import OperationalProductMaster


class OperationalPosTill(OperationalBase):
    __tablename__ = "operational_pos_tills"
    __table_args__ = (UniqueConstraint("till_code", name="uq_pos_till_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    till_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    till_code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalPosShift(OperationalBase):
    __tablename__ = "operational_pos_shifts"
    __table_args__ = (
        UniqueConstraint("shift_no", name="uq_pos_shift_no"),
        CheckConstraint("status IN ('open','closing_submitted','closed')", name="ck_pos_shift_status"),
        CheckConstraint("opening_float >= 0 AND expected_cash >= 0", name="ck_pos_shift_cash"),
        CheckConstraint("posting_enabled = false", name="ck_pos_shift_no_posting"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shift_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    shift_no: Mapped[str] = mapped_column(String(50), nullable=False)
    till_id: Mapped[int] = mapped_column(ForeignKey("operational_pos_tills.id"), nullable=False, index=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    opening_float: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    expected_cash: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    counted_cash: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    variance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(30), default="open", nullable=False, index=True)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    opened_by: Mapped[str] = mapped_column(String(200), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    close_note: Mapped[str | None] = mapped_column(Text)
    closed_by: Mapped[str | None] = mapped_column(String(200))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    till: Mapped[OperationalPosTill] = relationship()
    sales: Mapped[list["OperationalPosSale"]] = relationship(back_populates="shift")


class OperationalPosSale(OperationalBase):
    __tablename__ = "operational_pos_sales"
    __table_args__ = (
        UniqueConstraint("receipt_no", name="uq_pos_receipt_no"),
        CheckConstraint("status IN ('completed','voided')", name="ck_pos_sale_status"),
        CheckConstraint("subtotal >= 0 AND tax_amount >= 0 AND total_amount >= 0", name="ck_pos_sale_totals"),
        CheckConstraint("posting_enabled = false", name="ck_pos_sale_no_posting"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sale_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    receipt_no: Mapped[str] = mapped_column(String(50), nullable=False)
    shift_id: Mapped[int] = mapped_column(ForeignKey("operational_pos_shifts.id"), nullable=False, index=True)
    customer_name: Mapped[str | None] = mapped_column(String(500))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(20), nullable=False)
    amount_tendered: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    change_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="completed", nullable=False)
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    shift: Mapped[OperationalPosShift] = relationship(back_populates="sales")
    lines: Mapped[list["OperationalPosSaleLine"]] = relationship(back_populates="sale", cascade="all, delete-orphan")


class OperationalPosSaleLine(OperationalBase):
    __tablename__ = "operational_pos_sale_lines"
    __table_args__ = (
        UniqueConstraint("sale_id", "line_no", name="uq_pos_sale_line"),
        CheckConstraint("quantity > 0 AND quantity_base > 0 AND factor_to_base_snapshot > 0", name="ck_pos_line_quantity"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("operational_pos_sales.id", ondelete="CASCADE"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    sku: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    product_name_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    uom: Mapped[str] = mapped_column(String(80), nullable=False)
    factor_to_base_snapshot: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    stock_available_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    sale: Mapped[OperationalPosSale] = relationship(back_populates="lines")


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)


def create_till(session: Session, *, till_code: str, name: str, location_code: str, actor: str) -> OperationalPosTill:
    code = till_code.strip().upper()
    if session.scalar(select(OperationalPosTill).where(OperationalPosTill.till_code == code)):
        raise ValueError("POS till code already exists")
    row = OperationalPosTill(till_key=str(uuid.uuid4()), till_code=code, name=name.strip(),
                             location_code=location_code.strip().upper(), created_by=actor)
    session.add(row); session.flush()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="pos.till.created", actor=actor,
                                      resource_key=row.till_key, detail=f"{code}; posting disabled"))
    session.commit(); return row


def open_shift(session: Session, *, till_key: str, business_date: date, opening_float: Decimal, actor: str) -> OperationalPosShift:
    till = session.scalar(select(OperationalPosTill).where(OperationalPosTill.till_key == till_key))
    if not till or not till.active: raise ValueError("Active POS till not found")
    if session.scalar(select(OperationalPosShift).where(OperationalPosShift.till_id == till.id,
                                                        OperationalPosShift.status != "closed")):
        raise ValueError("This till already has an open shift")
    key = str(uuid.uuid4()); opening = _money(opening_float)
    row = OperationalPosShift(shift_key=key, shift_no=f"POS-SH-{business_date:%Y%m%d}-{key[:6].upper()}",
        till_id=till.id, business_date=business_date, opening_float=opening, expected_cash=opening,
        opened_by=actor, posting_enabled=False)
    session.add(row); session.flush()
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="pos.shift.opened", actor=actor,
                                      resource_key=key, detail=f"{till.till_code}; float {opening}; posting disabled"))
    session.commit(); return row


def record_sale(session: Session, *, shift_key: str, lines: list[dict], payment_method: str,
                amount_tendered: Decimal, customer_name: str | None, actor: str) -> OperationalPosSale:
    shift = session.scalar(select(OperationalPosShift).where(OperationalPosShift.shift_key == shift_key).with_for_update())
    if not shift or shift.status != "open": raise ValueError("POS sale requires an open shift")
    if not lines: raise ValueError("POS sale requires at least one line")
    if payment_method not in {"cash", "card"}: raise ValueError("POS payment method must be cash or card")
    built=[]; subtotal=Decimal("0"); tax_total=Decimal("0")
    for index, value in enumerate(lines, 1):
        product=session.scalar(select(OperationalProductMaster).where(
            OperationalProductMaster.sku == str(value["sku"]), OperationalProductMaster.status == "active"))
        if not product: raise ValueError(f"Active product not found: {value['sku']}")
        quantity=Decimal(str(value["quantity"])); factor=Decimal(product.factor_to_base); quantity_base=quantity*factor
        position=session.scalar(select(OperationalStockPosition).where(
            OperationalStockPosition.location_code == shift.till.location_code,
            OperationalStockPosition.sku == product.sku))
        available=None if not position or not position.availability_enabled else Decimal(position.quantity_on_hand)-Decimal(position.quantity_reserved)
        if available is not None and quantity_base > available: raise ValueError(f"Insufficient available stock for {product.sku}")
        unit_price=Decimal(product.selling_price); net=_money(quantity*unit_price); tax=_money(net*Decimal(product.tax_rate)/Decimal("100"))
        subtotal += net; tax_total += tax
        built.append((index, product, quantity, factor, quantity_base, unit_price, net, tax, available))
    total=_money(subtotal+tax_total); tendered=_money(amount_tendered)
    if payment_method == "card" and tendered != total: raise ValueError("Card payment must equal the sale total")
    if payment_method == "cash" and tendered < total: raise ValueError("Cash tendered cannot be less than the sale total")
    key=str(uuid.uuid4()); sale=OperationalPosSale(sale_key=key,
        receipt_no=f"POS-{shift.business_date:%Y%m%d}-{key[:8].upper()}", shift_id=shift.id,
        customer_name=(customer_name or "").strip() or None, subtotal=_money(subtotal), tax_amount=_money(tax_total),
        total_amount=total, payment_method=payment_method, amount_tendered=tendered,
        change_amount=_money(tendered-total), created_by=actor, posting_enabled=False)
    for index, product, quantity, factor, quantity_base, unit_price, net, tax, available in built:
        sale.lines.append(OperationalPosSaleLine(line_no=index, sku=product.sku,
            product_name_snapshot=product.name, quantity=quantity, uom=product.base_uom,
            factor_to_base_snapshot=factor, quantity_base=quantity_base, unit_price=unit_price,
            tax_rate=product.tax_rate, net_amount=net, tax_amount=tax, gross_amount=_money(net+tax),
            stock_available_snapshot=available))
    session.add(sale); session.flush()
    if payment_method == "cash": shift.expected_cash=_money(shift.expected_cash+total)
    shift.revision += 1
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="pos.sale.completed", actor=actor,
        resource_key=key, detail=f"{sale.receipt_no}; {payment_method}; AED {total}; stock and accounting posting disabled"))
    session.commit(); return sale


def submit_close(session: Session, *, shift_key: str, expected_revision: int, counted_cash: Decimal,
                 note: str, actor: str) -> OperationalPosShift:
    row=session.scalar(select(OperationalPosShift).where(OperationalPosShift.shift_key == shift_key).with_for_update())
    if not row or row.status != "open": raise ValueError("Only an open POS shift can be submitted for close")
    if row.revision != expected_revision: raise ValueError("POS shift revision is stale")
    row.counted_cash=_money(counted_cash); row.variance=_money(row.counted_cash-row.expected_cash)
    row.close_note=note.strip(); row.status="closing_submitted"; row.revision += 1
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="pos.shift.close_submitted", actor=actor,
        resource_key=row.shift_key, detail=f"expected {row.expected_cash}; counted {row.counted_cash}; variance {row.variance}"))
    session.commit(); return row


def approve_close(session: Session, *, shift_key: str, expected_revision: int, note: str, actor: str) -> OperationalPosShift:
    row=session.scalar(select(OperationalPosShift).where(OperationalPosShift.shift_key == shift_key).with_for_update())
    if not row or row.status != "closing_submitted": raise ValueError("POS shift is not awaiting close approval")
    if row.revision != expected_revision: raise ValueError("POS shift revision is stale")
    if row.opened_by == actor: raise PermissionError("Maker-checker control prevents the shift opener from approving close")
    row.status="closed"; row.closed_by=actor; row.closed_at=utc_now(); row.close_note=f"{row.close_note}\nApproval: {note.strip()}"; row.revision += 1
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="pos.shift.closed", actor=actor,
        resource_key=row.shift_key, detail=f"variance {row.variance}; posting disabled; {note.strip()}"))
    session.commit(); return row


def pos_workspace_payload(session: Session, allowed_locations: tuple[str, ...] = ("*",)) -> dict:
    till_query=select(OperationalPosTill).order_by(OperationalPosTill.till_code)
    if "*" not in allowed_locations: till_query=till_query.where(OperationalPosTill.location_code.in_(allowed_locations))
    tills=list(session.scalars(till_query)); till_ids=[x.id for x in tills]
    shifts=list(session.scalars(select(OperationalPosShift).where(OperationalPosShift.till_id.in_(till_ids)).order_by(OperationalPosShift.opened_at.desc()))) if till_ids else []
    sales=list(session.scalars(select(OperationalPosSale).where(OperationalPosSale.shift_id.in_([x.id for x in shifts])).order_by(OperationalPosSale.created_at.desc()))) if shifts else []
    return {
        "controls":{"tills":len(tills),"open_shifts":sum(x.status=="open" for x in shifts),"close_approvals":sum(x.status=="closing_submitted" for x in shifts),"sales":len(sales),"posting_enabled":False},
        "tills":[{"till_key":x.till_key,"till_code":x.till_code,"name":x.name,"location_code":x.location_code,"active":x.active} for x in tills],
        "shifts":[{"shift_key":x.shift_key,"shift_no":x.shift_no,"till_code":x.till.till_code,"location_code":x.till.location_code,"business_date":x.business_date,"opening_float":x.opening_float,"expected_cash":x.expected_cash,"counted_cash":x.counted_cash,"variance":x.variance,"status":x.status,"opened_by":x.opened_by,"closed_by":x.closed_by,"revision":x.revision} for x in shifts],
        "sales":[{"sale_key":x.sale_key,"receipt_no":x.receipt_no,"shift_key":x.shift.shift_key,"customer_name":x.customer_name or "Walk-in customer","total_amount":x.total_amount,"tax_amount":x.tax_amount,"payment_method":x.payment_method,"change_amount":x.change_amount,"status":x.status,"created_by":x.created_by,"created_at":x.created_at,"lines":[{"sku":l.sku,"product_name":l.product_name_snapshot,"quantity":l.quantity,"uom":l.uom,"gross_amount":l.gross_amount} for l in x.lines]} for x in sales],
        "products":[{"sku":x.sku,"name":x.name,"uom":x.base_uom,"selling_price":x.selling_price,"tax_rate":x.tax_rate} for x in session.scalars(select(OperationalProductMaster).where(OperationalProductMaster.status=="active").order_by(OperationalProductMaster.name).limit(500))],
        "boundary":{"test_data_only":True,"stock_posting_performed":False,"accounting_posting_performed":False,"permanent_posting_enabled":False},
    }
