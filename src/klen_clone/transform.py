from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import (
    RawFileManifest, RawRecord, ReconciliationException, SourceSnapshot, StgContact,
    StgDocumentLine, StgItemTrace, StgPayment, StgProduct, StgPurchase,
    StgPurchaseLine, StgReturn, StgSale, StgSaleLine, StgStockBalance,
    StgStockTransfer, StgFinancialAllocation, StgInventoryMovement,
    StgProductUomProfile, StgTaxEvidence, StgUomDefinition,
    StgAccountingControl, StgCashFlowEntry, StgPaymentAccount, StgTrialBalanceEntry,
)
from .derived import clear_blueprint_outputs

DUBAI = ZoneInfo("Asia/Dubai")
MONEY_PATTERN = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
QUANTITY_PATTERN = re.compile(r"^\s*(-?[\d,]+(?:\.\d+)?)\s*(.*?)\s*$")


def clean(value: object) -> str | None:
    text = str(value or "").replace("\xa0", " ").strip()
    return re.sub(r"\s+", " ", text) or None


def decimal_value(value: object) -> Decimal | None:
    text = clean(value)
    if not text:
        return None
    match = MONEY_PATTERN.search(text)
    if not match:
        return None
    try:
        return Decimal(match.group(0).replace(",", ""))
    except InvalidOperation:
        return None


def datetime_value(value: object) -> datetime | None:
    text = clean(value)
    if not text:
        return None
    for pattern in ("%m/%d/%Y %H:%M", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=DUBAI)
        except ValueError:
            continue
    return None


def quantity_value(value: object) -> tuple[Decimal | None, str | None]:
    text = clean(value)
    if not text:
        return None, None
    match = QUANTITY_PATTERN.match(text)
    if not match:
        return None, text
    return decimal_value(match.group(1)), clean(match.group(2))


def _records(session: Session, snapshot_id: int, *entities: str):
    return session.execute(
        select(RawRecord, RawFileManifest.entity_type)
        .join(RawFileManifest)
        .where(
            RawFileManifest.snapshot_id == snapshot_id,
            RawFileManifest.entity_type.in_(entities),
            RawRecord.is_presentation_row.is_(False),
        )
        .order_by(RawRecord.id)
    ).all()


def _exception(session: Session, snapshot_id: int, raw: RawRecord, entity: str, field: str, value: object) -> None:
    session.add(ReconciliationException(
        snapshot_id=snapshot_id,
        code="TRANSFORM_INVALID_VALUE",
        severity="high",
        entity_type=entity,
        source_key=raw.source_document_number or raw.source_record_id,
        details={"raw_record_id": raw.id, "field": field, "value": clean(value)},
    ))


def _required_decimal(session: Session, snapshot_id: int, raw: RawRecord, entity: str, field: str, value: object) -> Decimal | None:
    parsed = decimal_value(value)
    if clean(value) and parsed is None:
        _exception(session, snapshot_id, raw, entity, field, value)
    return parsed


def _parse_tab_lines(text: str, kind: str) -> list[dict]:
    result = []
    for line in text.splitlines():
        columns = line.split("\t")
        if not columns or not columns[0].strip().isdigit():
            continue
        if kind == "sales_return" and len(columns) >= 5:
            quantity, unit = quantity_value(columns[3])
            result.append({"line_no": int(columns[0]), "product_name": clean(columns[1]), "unit_price": decimal_value(columns[2]), "quantity": quantity, "unit": unit, "subtotal": decimal_value(columns[4]), "raw_columns": columns})
        elif kind == "stock_transfer" and len(columns) >= 7:
            product = clean(columns[1])
            sku_match = re.search(r"\s+-\s+(\S+)$", product or "")
            quantity, unit = quantity_value(columns[5])
            result.append({"line_no": int(columns[0]), "product_name": product[:sku_match.start()].strip() if sku_match else product, "sku": sku_match.group(1) if sku_match else None, "location_from": clean(columns[2]), "location_to": clean(columns[3]), "quantity": quantity, "unit": unit, "subtotal": decimal_value(columns[6]), "raw_columns": columns})
    return result


def _parse_purchase_return_snapshot(snapshot: str) -> list[dict]:
    matches = list(re.finditer(r'(?m)^    - row "([^"]+)"', snapshot))
    result = []
    for index, match in enumerate(matches):
        block = snapshot[match.end(): matches[index + 1].start() if index + 1 < len(matches) else len(snapshot)]
        cells = re.findall(r'(?m)^      - cell "([^"]*)"', block)
        if not cells:
            continue
        if cells[0].isdigit() and len(cells) >= 7:
            line_no, product, price, quantity_text, subtotal = int(cells[0]), cells[1], cells[2], cells[5], cells[6]
            sku = None
        elif len(cells) >= 4:
            line_no, product, quantity_text, price, subtotal = len(result) + 1, cells[0], cells[1], cells[2], cells[3]
            sku_match = re.search(r"\s+(\d{4,})$", product)
            sku = sku_match.group(1) if sku_match else None
            if sku_match:
                product = product[:sku_match.start()].strip()
        else:
            continue
        quantity, unit = quantity_value(quantity_text)
        result.append({"line_no": line_no, "product_name": clean(product), "sku": sku, "quantity": quantity, "unit": unit, "unit_price": decimal_value(price), "subtotal": decimal_value(subtotal), "raw_columns": cells})
    return result


def transform_snapshot(session: Session, snapshot_name: str) -> dict[str, int]:
    snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == snapshot_name))
    if not snapshot:
        raise ValueError(f"Unknown snapshot: {snapshot_name}")
    clear_blueprint_outputs(session, snapshot.id)
    typed = (StgAccountingControl, StgCashFlowEntry, StgTrialBalanceEntry, StgPaymentAccount,
             StgFinancialAllocation, StgTaxEvidence, StgInventoryMovement, StgProductUomProfile,
             StgUomDefinition, StgDocumentLine, StgItemTrace, StgPurchaseLine, StgSaleLine,
             StgStockTransfer, StgStockBalance, StgReturn, StgPayment, StgPurchase,
             StgSale, StgProduct, StgContact)
    for model in typed:
        session.execute(delete(model).where(model.snapshot_id == snapshot.id))
    session.execute(delete(ReconciliationException).where(ReconciliationException.snapshot_id == snapshot.id, ReconciliationException.code == "TRANSFORM_INVALID_VALUE"))

    counts: dict[str, int] = {}
    for raw, entity in _records(session, snapshot.id, "customer", "supplier"):
        p = raw.payload or {}; kind = entity
        session.add(StgContact(snapshot_id=snapshot.id, raw_record_id=raw.id, kind=kind, contact_id=clean(p.get("Contact ID")), business_name=clean(p.get("Business Name")), name=clean(p.get("Name")), email=clean(p.get("Email")), mobile=clean(p.get("Mobile")), address=clean(p.get("Address")), tax_number=clean(p.get("Tax number")), opening_balance=decimal_value(p.get("Opening Balance")), advance_balance=decimal_value(p.get("Advance Balance")), amount_due=decimal_value(p.get("Total Sale Due") if kind == "customer" else p.get("Total Purchase Due")), return_due=decimal_value(p.get("Total Sell Return Due") if kind == "customer" else p.get("Total Purchase Return Due"))))
        counts[kind] = counts.get(kind, 0) + 1

    for raw, _ in _records(session, snapshot.id, "product"):
        p = raw.payload or {}; name = clean(p.get("Product"))
        if not name: _exception(session, snapshot.id, raw, "product", "Product", p.get("Product")); continue
        quantity, unit = quantity_value(p.get("Current stock"))
        session.add(StgProduct(snapshot_id=snapshot.id, raw_record_id=raw.id, sku=clean(p.get("SKU")), name=name, product_type=clean(p.get("Product Type")), category=clean(p.get("Category")), brand=clean(p.get("Brand")), tax_name=clean(p.get("Tax")), locations=clean(p.get("Business Location")), purchase_price=decimal_value(p.get("Unit Purchase Price")), selling_price=decimal_value(p.get("Selling Price")), current_stock=quantity, stock_unit=unit))
        counts["product"] = counts.get("product", 0) + 1

    for raw, _ in _records(session, snapshot.id, "sale"):
        p=raw.payload or {}; doc=clean(p.get("Invoice No."))
        if not doc: _exception(session,snapshot.id,raw,"sale","Invoice No.",None); continue
        session.add(StgSale(snapshot_id=snapshot.id,raw_record_id=raw.id,document_no=doc,transaction_at=datetime_value(p.get("Date")),customer_name=clean(p.get("Customer name")),location=clean(p.get("Location")),payment_status=clean(p.get("Payment Status")),payment_method=clean(p.get("Payment Method")),total_amount=_required_decimal(session,snapshot.id,raw,"sale","Total amount",p.get("Total amount")),total_paid=decimal_value(p.get("Total paid")),amount_due=decimal_value(p.get("Sell Due")),return_due=decimal_value(p.get("Sell Return Due")),added_by=clean(p.get("Added By"))))
        counts["sale"] = counts.get("sale",0)+1

    for raw, _ in _records(session, snapshot.id, "purchase"):
        p=raw.payload or {}; doc=clean(p.get("Purchase No"))
        if not doc: _exception(session,snapshot.id,raw,"purchase","Purchase No",None); continue
        session.add(StgPurchase(snapshot_id=snapshot.id,raw_record_id=raw.id,document_no=doc,supplier_reference=clean(p.get("Supplier Ref")),transaction_at=datetime_value(p.get("Date")),supplier_name=clean(p.get("Supplier")),location=clean(p.get("Location")),purchase_status=clean(p.get("Purchase Status")),payment_status=clean(p.get("Payment Status")),total_amount=_required_decimal(session,snapshot.id,raw,"purchase","Grand Total",p.get("Grand Total")),amount_due=decimal_value(p.get("Payment due   ") or p.get("Payment due")),added_by=clean(p.get("Added By"))))
        counts["purchase"] = counts.get("purchase",0)+1

    for raw, _ in _records(session, snapshot.id, "sales_line", "sales_line_boundary"):
        p=raw.payload or {}; doc=clean(p.get("Invoice No.")); product=clean(p.get("Product"))
        if not doc or not product:
            _exception(session,snapshot.id,raw,"sales_line","Invoice No./Product",f"{doc}/{product}"); continue
        quantity,unit=quantity_value(p.get("Quantity"))
        session.add(StgSaleLine(snapshot_id=snapshot.id,raw_record_id=raw.id,document_no=doc,transaction_at=datetime_value(p.get("Date")),contact_id=clean(p.get("Contact ID")),customer_name=clean(p.get("Customer name")),sku=clean(p.get("SKU")),product_name=product,category=clean(p.get("Category")),quantity=quantity,unit=unit,cost_price=decimal_value(p.get("Cost Price Exc Tax")),unit_price=decimal_value(p.get("Unit Price")),discount=decimal_value(p.get("Discount")),tax_amount=decimal_value(p.get("Tax")),total=_required_decimal(session,snapshot.id,raw,"sales_line","Total",p.get("Total")),gross_profit=decimal_value(p.get("Gross Profit"))))
        counts["sales_line"]=counts.get("sales_line",0)+1

    for raw, _ in _records(session, snapshot.id, "purchase_line"):
        p=raw.payload or {}; doc=clean(p.get("Reference No")); product=clean(p.get("Product"))
        if not doc or not product:
            _exception(session,snapshot.id,raw,"purchase_line","Reference No/Product",f"{doc}/{product}"); continue
        quantity,unit=quantity_value(p.get("Quantity")); adjusted,_=quantity_value(p.get("Total Unit Adjusted"))
        session.add(StgPurchaseLine(snapshot_id=snapshot.id,raw_record_id=raw.id,document_no=doc,transaction_at=datetime_value(p.get("Date")),supplier_name=clean(p.get("Supplier")),supplier_reference=clean(p.get("Supplier Ref")),sku=clean(p.get("SKU")),product_name=product,quantity=quantity,unit=unit,adjusted_quantity=adjusted,unit_price=decimal_value(p.get("Unit Purchase Price")),subtotal=_required_decimal(session,snapshot.id,raw,"purchase_line","Subtotal",p.get("Subtotal"))))
        counts["purchase_line"]=counts.get("purchase_line",0)+1

    for raw, _ in _records(session, snapshot.id, "item_trace"):
        p=raw.payload or {}; product=clean(p.get("Product"))
        if not product:
            _exception(session,snapshot.id,raw,"item_trace","Product",None); continue
        quantity,unit=quantity_value(p.get("Sell Quantity"))
        session.add(StgItemTrace(snapshot_id=snapshot.id,raw_record_id=raw.id,sku=clean(p.get("SKU")),product_name=product,purchase_document_no=clean(p.get("Purchase")),sale_document_no=clean(p.get("Sale")),supplier_name=clean(p.get("Supplier")),customer_name=clean(p.get("Customer")),location=clean(p.get("Location")),quantity=quantity,unit=unit,purchase_price=decimal_value(p.get("Purchase Price")),selling_price=decimal_value(p.get("Selling Price")),subtotal=decimal_value(p.get("Subtotal"))))
        counts["item_trace"]=counts.get("item_trace",0)+1

    for raw, entity in _records(session, snapshot.id, "sales_payment", "purchase_payment"):
        p=raw.payload or {}; direction="sale" if entity=="sales_payment" else "purchase"
        session.add(StgPayment(snapshot_id=snapshot.id,raw_record_id=raw.id,direction=direction,reference_no=clean(p.get("Reference No")),parent_document_no=clean(p.get("Sales") if direction=="sale" else p.get("Purchase")),paid_at=datetime_value(p.get("Paid on")),contact_name=clean(p.get("Customer") if direction=="sale" else p.get("Supplier")),method=clean(p.get("Payment Method")),amount=_required_decimal(session,snapshot.id,raw,entity,"Amount",p.get("Amount"))))
        counts[entity]=counts.get(entity,0)+1

    for raw, entity in _records(session, snapshot.id, "sales_return", "purchase_return"):
        p=raw.payload or {}; direction="sale" if entity=="sales_return" else "purchase"; doc=clean(p.get("Invoice No.") if direction=="sale" else p.get("Reference No"))
        session.add(StgReturn(snapshot_id=snapshot.id,raw_record_id=raw.id,direction=direction,document_no=doc or f"RAW-{raw.id}",parent_document_no=clean(p.get("Parent Sale") if direction=="sale" else p.get("Parent Purchase")),transaction_at=datetime_value(p.get("Date")),contact_name=clean(p.get("Customer name") if direction=="sale" else p.get("Supplier")),location=clean(p.get("Location")),payment_status=clean(p.get("Payment Status")),total_amount=decimal_value(p.get("Total amount") if direction=="sale" else p.get("Grand Total")),amount_due=decimal_value(p.get("Payment due") or p.get("Payment due   "))))
        counts[entity]=counts.get(entity,0)+1

    for raw, _ in _records(session, snapshot.id, "stock_balance"):
        p=raw.payload or {}; product=clean(p.get("Product"))
        if not product: _exception(session,snapshot.id,raw,"stock_balance","Product",None); continue
        quantity, unit=quantity_value(p.get("Available Stock"))
        session.add(StgStockBalance(snapshot_id=snapshot.id,raw_record_id=raw.id,sku=clean(p.get("SKU")),product_name=product,location=clean(p.get("Location")),sub_location=clean(p.get("Sub Location")),unit=unit or clean(p.get("Unit")),available_quantity=quantity,selling_price=decimal_value(p.get("Unit Selling Price")),purchase_value=decimal_value(p.get("Current Stock Value (By purchase price)")),sale_value=decimal_value(p.get("Current Stock Value (By sale price)"))))
        counts["stock_balance"]=counts.get("stock_balance",0)+1

    for raw, _ in _records(session, snapshot.id, "stock_transfer"):
        p=raw.payload or {}; doc=clean(p.get("Reference No"))
        session.add(StgStockTransfer(snapshot_id=snapshot.id,raw_record_id=raw.id,document_no=doc or f"RAW-{raw.id}",transaction_at=datetime_value(p.get("Date")),location_from=clean(p.get("Location (From)")),location_to=clean(p.get("Location (To)")),status=clean(p.get("Status")),shipping_charge=decimal_value(p.get("Shipping Charges")),total_amount=decimal_value(p.get("Total Amount")),notes=clean(p.get("Additional Notes"))))
        counts["stock_transfer"]=counts.get("stock_transfer",0)+1

    for raw, entity in _records(session, snapshot.id, "sales_return_detail", "purchase_return_detail", "stock_transfer_detail"):
        p=raw.payload or {}; text=str(p.get("text") or p.get("snapshot") or "")
        kind={"sales_return_detail":"sales_return","purchase_return_detail":"purchase_return","stock_transfer_detail":"stock_transfer"}[entity]
        if kind=="purchase_return":
            lines=_parse_purchase_return_snapshot(text); match=re.search(r'textbox "Reference No:":\s*([^\n]+)',text)
        else:
            lines=_parse_tab_lines(text,kind); match=re.search(r"(?:Invoice No\.:|Reference No: #?)([^\n)]+)",text)
        parent=clean(match.group(1)) if match else raw.source_document_number
        for line in lines:
            session.add(StgDocumentLine(snapshot_id=snapshot.id,raw_record_id=raw.id,source_entity=kind,parent_document_no=parent,**line))
        counts[f"{kind}_line"]=counts.get(f"{kind}_line",0)+len(lines)

    session.commit()
    return counts
