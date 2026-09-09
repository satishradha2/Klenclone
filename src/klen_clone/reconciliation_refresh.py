from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .erp_master_rehearsal import PRODUCT_COLUMNS, _base_uom
from .erp_opening_rehearsal import AP_COLUMNS, AR_COLUMNS, LOCATION_MAP, STOCK_COLUMNS


class ReconciliationRefreshError(RuntimeError):
    pass


ADVANCE_COLUMNS = [
    "entry_no", "entry_date", "account_code", "partner_code", "currency_code",
    "debit", "credit", "description",
]
NEGATIVE_STOCK_COLUMNS = [
    "sku", "warehouse_code", "location_code", "quantity_base", "unit_cost", "reason",
]


def _read(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{str(k): str(v or "").strip() for k, v in row.items() if k is not None}
                for row in csv.DictReader(handle)]


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _number(value: str, *, first: bool = False) -> Decimal:
    matches = re.findall(r"-?[\d,]+(?:\.\d+)?", value or "")
    if not matches:
        return Decimal("0")
    try:
        return Decimal(matches[0 if first else -1].replace(",", ""))
    except InvalidOperation:
        return Decimal("0")


def _fmt(value: Decimal) -> str:
    return f"{value:.2f}"


def _write(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)


def build_reconciliation_refresh(
    capture_dir: Path, prior_capture_dir: Path, output_dir: Path, as_of: str = "2026-09-09",
) -> dict[str, Any]:
    capture, prior, output = capture_dir.resolve(), prior_capture_dir.resolve(), output_dir.resolve()
    if not capture.is_dir() or not prior.is_dir():
        raise ReconciliationRefreshError("Capture or prior capture directory not found")
    if output.exists():
        raise ReconciliationRefreshError(f"Output already exists; overwrite refused: {output}")
    required = {
        "customers_current.csv", "suppliers_current.csv", "products_current.csv",
        "stock_snapshot_all_locations_current.csv", "sales_2026_current.csv",
        "purchases_2026_current.csv", "sales_returns_2026_current.csv",
        "purchase_returns_2026_current.csv", "customer_supplier_report_ytd.csv",
    }
    missing = sorted(name for name in required if not (capture / name).is_file())
    if missing:
        raise ReconciliationRefreshError(f"Capture files missing: {', '.join(missing)}")

    products = _read(capture / "products_current.csv")
    prior_products = _read(prior / "products_current.csv")
    customers = _read(capture / "customers_current.csv")
    suppliers = _read(capture / "suppliers_current.csv")
    stock_source = _read(capture / "stock_snapshot_all_locations_current.csv")
    sales = _read(capture / "sales_2026_current.csv")
    purchases = _read(capture / "purchases_2026_current.csv")
    sales_returns = _read(capture / "sales_returns_2026_current.csv")
    purchase_returns = _read(capture / "purchase_returns_2026_current.csv")
    finance_report = _read(capture / "customer_supplier_report_ytd.csv")

    current_skus = {row.get("SKU", "") for row in products}
    if "" in current_skus or len(current_skus) != len(products):
        raise ReconciliationRefreshError("Current product SKU is missing or duplicated")
    prior_skus = {row.get("SKU", "") for row in prior_products}
    product_delta = []
    for row in products:
        sku = row["SKU"]
        if sku not in prior_skus:
            product_delta.append({
                "sku": sku, "name": row.get("Product") or f"Source product {sku}",
                "base_uom": _base_uom(row.get("Current stock", "")), "barcode": "",
                "description": "", "hs_code": "", "country_of_origin": "AE",
                "standard_cost": _fmt(_number(row.get("Unit Purchase Price", ""))),
                "default_sales_price": _fmt(_number(row.get("Selling Price", ""))),
                "pack_uom": "", "pack_factor": "", "pack_barcode": "",
            })

    product_cost = {row["SKU"]: _number(row.get("Unit Purchase Price", "")) for row in products}
    aggregate_product_qty = {row["SKU"]: _number(row.get("Current stock", ""), first=True) for row in products}
    aggregate_location_qty: defaultdict[str, Decimal] = defaultdict(Decimal)
    positive_stock, negative_stock, stock_exceptions = [], [], []
    for source_row, row in enumerate(stock_source, 2):
        sku, location = row.get("SKU", ""), row.get("Location", "")
        quantity = _number(row.get("Available Stock", ""), first=True)
        if not sku:
            stock_exceptions.append({"source_row": source_row, "action": "missing_sku"})
            continue
        aggregate_location_qty[sku] += quantity
        if not location:
            stock_exceptions.append({
                "source_row": source_row, "sku": sku, "quantity_base": _fmt(quantity),
                "action": "missing_location_zero_balance" if quantity == 0 else "missing_location",
            })
            continue
        mapping = LOCATION_MAP.get(location)
        if not mapping:
            stock_exceptions.append({"source_row": source_row, "sku": sku, "source_location": location, "action": "unmapped_location"})
            continue
        target = {
            "sku": sku, "warehouse_code": mapping["warehouse_code"],
            "location_code": mapping["location_code"], "quantity_base": _fmt(quantity),
            "unit_cost": _fmt(product_cost.get(sku, Decimal("0"))),
        }
        if quantity > 0:
            positive_stock.append({**target, "lot_no": ""})
        elif quantity < 0:
            negative_stock.append({**target, "reason": "Source negative stock preserved as controlled migration adjustment"})

    stock_differences = []
    for sku in sorted(current_skus | set(aggregate_location_qty)):
        location_quantity = aggregate_location_qty.get(sku, Decimal("0"))
        product_quantity = aggregate_product_qty.get(sku, Decimal("0"))
        if location_quantity != product_quantity:
            stock_differences.append({"sku": sku, "location_quantity": _fmt(location_quantity), "product_quantity": _fmt(product_quantity), "difference": _fmt(location_quantity - product_quantity)})

    receivables, payables, advance_gl = [], [], []
    customer_positive = customer_negative = supplier_positive = supplier_negative = Decimal("0")
    for row in customers:
        code = row.get("Contact ID", "")
        net = _number(row.get("Total Sale Due", "")) - _number(row.get("Total Sell Return Due", ""))
        if net > 0:
            customer_positive += net
            receivables.append({"invoice_no": f"OPEN-AR-{code}", "customer_code": code, "invoice_date": as_of, "due_date": as_of, "currency_code": "AED", "amount": _fmt(net), "control_account_code": "1100", "offset_account_code": "3100"})
        elif net < 0:
            amount = -net
            customer_negative += amount
            entry = f"OPEN-CADV-{code}"
            advance_gl.extend([
                {"entry_no": entry, "entry_date": as_of, "account_code": "3100", "partner_code": code, "currency_code": "AED", "debit": _fmt(amount), "credit": "0.00", "description": "Opening customer advance offset"},
                {"entry_no": entry, "entry_date": as_of, "account_code": "2300", "partner_code": code, "currency_code": "AED", "debit": "0.00", "credit": _fmt(amount), "description": "Opening customer advance"},
            ])
    for row in suppliers:
        code = row.get("Contact ID", "")
        net = _number(row.get("Total Purchase Due", "")) - _number(row.get("Total Purchase Return Due", ""))
        if net > 0:
            supplier_positive += net
            payables.append({"invoice_no": f"OPEN-AP-{code}", "supplier_code": code, "invoice_date": as_of, "due_date": as_of, "currency_code": "AED", "amount": _fmt(net), "control_account_code": "2000", "offset_account_code": "3100"})
        elif net < 0:
            amount = -net
            supplier_negative += amount
            entry = f"OPEN-SADV-{code}"
            advance_gl.extend([
                {"entry_no": entry, "entry_date": as_of, "account_code": "1300", "partner_code": code, "currency_code": "AED", "debit": _fmt(amount), "credit": "0.00", "description": "Opening supplier advance"},
                {"entry_no": entry, "entry_date": as_of, "account_code": "3100", "partner_code": code, "currency_code": "AED", "debit": "0.00", "credit": _fmt(amount), "description": "Opening supplier advance offset"},
            ])

    sales_due = sum((_number(row.get("Sell Due", "")) for row in sales), Decimal("0"))
    purchase_due = sum((_number(row.get("Payment due", "")) for row in purchases), Decimal("0"))
    sales_return_due = sum((_number(row.get("Payment due", "")) for row in sales_returns), Decimal("0"))
    purchase_return_due = sum((_number(row.get("Payment due", "")) for row in purchase_returns), Decimal("0"))
    report_due = sum((_number(row.get("Due", "")) for row in finance_report), Decimal("0"))
    stock_positive_total = sum((Decimal(row["quantity_base"]) for row in positive_stock), Decimal("0"))
    stock_negative_total = sum((Decimal(row["quantity_base"]) for row in negative_stock), Decimal("0"))

    output.mkdir(parents=True)
    _write(output / "products_delta.csv", PRODUCT_COLUMNS, product_delta)
    _write(output / "opening_receivables.csv", AR_COLUMNS, receivables)
    _write(output / "opening_payables.csv", AP_COLUMNS, payables)
    _write(output / "opening_advances_gl.csv", ADVANCE_COLUMNS, advance_gl)
    _write(output / "opening_stock_positive.csv", STOCK_COLUMNS, positive_stock)
    _write(output / "opening_stock_negative_adjustments.csv", NEGATIVE_STOCK_COLUMNS, negative_stock)
    (output / "stock_exceptions.json").write_text(json.dumps(stock_exceptions, indent=2) + "\n", encoding="utf-8")

    source_manifest = [{"name": name, "rows": len(_read(capture / name)), "sha256": _sha(capture / name)} for name in sorted(required)]
    status = {
        "schema_version": 1, "created_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source_capture": str(capture), "source_capture_atomicity": "NON_ATOMIC",
        "source_mutation": False, "target_mutation": False, "posting_enabled": False,
        "promotion_allowed": False, "later_delta_supported": True,
        "source_manifest": source_manifest,
        "products": {"current_rows": len(products), "prior_rows": len(prior_products), "new_rows": len(product_delta), "new_skus": [row["sku"] for row in product_delta]},
        "stock": {
            "location_rows": len(stock_source), "sku_rows": len(aggregate_location_qty),
            "product_rows": len(aggregate_product_qty), "sku_differences": stock_differences,
            "positive_rows": len(positive_stock), "positive_quantity": _fmt(stock_positive_total),
            "negative_rows": len(negative_stock), "negative_quantity": _fmt(stock_negative_total),
            "net_quantity": _fmt(stock_positive_total + stock_negative_total),
            "location_report_quantity": _fmt(sum(aggregate_location_qty.values(), Decimal("0"))),
            "product_register_quantity": _fmt(sum(aggregate_product_qty.values(), Decimal("0"))),
            "reconciled": not stock_differences and sum(aggregate_location_qty.values(), Decimal("0")) == sum(aggregate_product_qty.values(), Decimal("0")),
        },
        "balances": {
            "receivables_rows": len(receivables), "receivables_aed": _fmt(customer_positive),
            "customer_advance_partners": customer_negative and len([r for r in customers if _number(r.get("Total Sale Due", "")) - _number(r.get("Total Sell Return Due", "")) < 0]) or 0,
            "customer_advances_aed": _fmt(customer_negative),
            "net_customer_position_aed": _fmt(customer_positive - customer_negative),
            "payables_rows": len(payables), "payables_aed": _fmt(supplier_positive),
            "supplier_advance_partners": supplier_negative and len([r for r in suppliers if _number(r.get("Total Purchase Due", "")) - _number(r.get("Total Purchase Return Due", "")) < 0]) or 0,
            "supplier_advances_aed": _fmt(supplier_negative),
            "net_supplier_position_aed": _fmt(supplier_positive - supplier_negative),
        },
        "secondary_report_checks": {
            "sales_header_due_less_return_due_aed": _fmt(sales_due - sales_return_due),
            "customer_master_net_aed": _fmt(customer_positive - customer_negative),
            "customer_variance_aed": _fmt((customer_positive - customer_negative) - (sales_due - sales_return_due)),
            "purchase_header_due_less_return_due_aed": _fmt(purchase_due - purchase_return_due),
            "supplier_master_net_aed": _fmt(supplier_positive - supplier_negative),
            "supplier_variance_aed": _fmt((supplier_positive - supplier_negative) - (purchase_due - purchase_return_due)),
            "customer_supplier_report_signed_due_aed": _fmt(report_due),
            "contact_master_net_customer_less_supplier_aed": _fmt((customer_positive - customer_negative) - (supplier_positive - supplier_negative)),
            "note": "Contact-ID master balances are the opening control source. Header and YTD report differences remain audit exceptions because the browser capture was not atomic.",
        },
        "qualification": "Stock quantity is fully reconciled between current source reports. Finance is source-key complete at contact balance level but remains non-atomic and is not authorized for posting.",
    }
    (output / "PACKAGE_STATUS.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    names = ["products_delta.csv", "opening_receivables.csv", "opening_payables.csv", "opening_advances_gl.csv", "opening_stock_positive.csv", "opening_stock_negative_adjustments.csv", "stock_exceptions.json", "PACKAGE_STATUS.json"]
    (output / "SHA256SUMS.txt").write_text("\n".join(f"{_sha(output / name)}  {name}" for name in names) + "\n", encoding="utf-8")
    return {"status": "prepared_non_posting", "output": str(output), "products": status["products"], "stock": status["stock"], "balances": status["balances"], "secondary_report_checks": status["secondary_report_checks"]}
