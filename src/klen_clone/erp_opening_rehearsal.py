from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


class ErpOpeningRehearsalError(RuntimeError):
    pass


AR_COLUMNS = [
    "invoice_no", "customer_code", "invoice_date", "due_date", "currency_code",
    "amount", "control_account_code", "offset_account_code",
]
AP_COLUMNS = [
    "invoice_no", "supplier_code", "invoice_date", "due_date", "currency_code",
    "amount", "control_account_code", "offset_account_code",
]
STOCK_COLUMNS = [
    "sku", "warehouse_code", "location_code", "quantity_base", "unit_cost", "lot_no",
]
LOCATION_MAP = {
    "Asas General Trading LLC": {
        "source_location_id": "BL0001", "target_branch_code": "BL0001",
        "warehouse_code": "BL0001", "location_code": "STORAGE",
        "target_configuration_status": "required_before_validation",
    },
    "SHJ": {
        "source_location_id": "BL0002", "target_branch_code": "SHJ",
        "warehouse_code": "MAIN", "location_code": "STORAGE",
        "target_configuration_status": "already_present",
    },
    "RAK": {
        "source_location_id": "BL0003", "target_branch_code": "RAK",
        "warehouse_code": "RAK", "location_code": "STORAGE",
        "target_configuration_status": "required_before_validation",
    },
    "DXB": {
        "source_location_id": "BL0004", "target_branch_code": "DXB",
        "warehouse_code": "DXB", "location_code": "STORAGE",
        "target_configuration_status": "required_before_validation",
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [
            {str(key): str(value or "").strip() for key, value in row.items() if key is not None}
            for row in csv.DictReader(handle)
        ]


def _decimal_from_text(value: str) -> Decimal:
    """Read the first quantity or final currency value without joining labels/numbers."""
    matches = re.findall(r"-?[\d,]+(?:\.\d+)?", value or "")
    if not matches:
        return Decimal("0")
    try:
        return Decimal(matches[-1].replace(",", ""))
    except InvalidOperation:
        return Decimal("0")


def _quantity(value: str) -> Decimal:
    match = re.search(r"-?[\d,]+(?:\.\d+)?", value or "")
    if not match:
        return Decimal("0")
    try:
        return Decimal(match.group().replace(",", ""))
    except InvalidOperation:
        return Decimal("0")


def _format(value: Decimal) -> str:
    return f"{value:.2f}"


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)


def _verify_current_capture(capture: Path) -> dict[str, Any]:
    try:
        status = json.loads((capture / "CAPTURE_STATUS.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ErpOpeningRehearsalError("Capture status is not readable") from exc
    if status.get("atomicity") != "NON_ATOMIC" or status.get("final_cutover_eligible") is not False:
        raise ErpOpeningRehearsalError("Expected the sealed non-atomic capture checkpoint")
    inventory = {item["name"]: item for item in status.get("files", [])}
    required = {
        "products_current.csv", "customers_current.csv", "suppliers_current.csv",
        "sales_2026_current.csv", "purchases_2026_current.csv",
    }
    missing = sorted(required - inventory.keys())
    if missing:
        raise ErpOpeningRehearsalError(f"Required capture files missing: {', '.join(missing)}")
    for name in required:
        if _sha256(capture / name) != str(inventory[name].get("sha256", "")).upper():
            raise ErpOpeningRehearsalError(f"Capture checksum mismatch: {name}")
    return status


def build_erp_opening_package(
    capture_dir: Path, baseline_dir: Path, output_dir: Path, as_of: date | None = None,
) -> dict[str, Any]:
    capture = capture_dir.resolve()
    baseline = baseline_dir.resolve()
    output = output_dir.resolve()
    if not capture.is_dir() or not baseline.is_dir():
        raise ErpOpeningRehearsalError("Capture or baseline directory not found")
    if output.exists():
        raise ErpOpeningRehearsalError(f"Output already exists; overwrite refused: {output}")
    capture_status = _verify_current_capture(capture)
    stock_path = baseline / "stock_snapshot_all_locations.csv"
    if not stock_path.is_file():
        raise ErpOpeningRehearsalError("Baseline stock snapshot is missing")

    capture_date = as_of or date.fromisoformat(str(capture_status.get("capture_date", "2026-09-09"))[:10])
    customers = _read_csv(capture / "customers_current.csv")
    suppliers = _read_csv(capture / "suppliers_current.csv")
    sales = _read_csv(capture / "sales_2026_current.csv")
    purchases = _read_csv(capture / "purchases_2026_current.csv")
    products = _read_csv(capture / "products_current.csv")
    stock_source = _read_csv(stock_path)
    exceptions: list[dict[str, Any]] = []

    receivables: list[dict[str, str]] = []
    for row_number, row in enumerate(customers, 2):
        code = row.get("Contact ID", "")
        net = _decimal_from_text(row.get("Total Sale Due", "")) - _decimal_from_text(row.get("Total Sell Return Due", ""))
        if net > 0:
            receivables.append({
                "invoice_no": f"OPEN-AR-{code}", "customer_code": code,
                "invoice_date": capture_date.isoformat(), "due_date": capture_date.isoformat(),
                "currency_code": "AED", "amount": _format(net),
                "control_account_code": "1100", "offset_account_code": "3100",
            })
        elif net < 0:
            exceptions.append({
                "entity": "customer_balance", "source_key": code, "source_row": row_number,
                "action": "deferred_negative_balance_for_advance_review", "amount_aed": _format(net),
            })

    payables: list[dict[str, str]] = []
    for row_number, row in enumerate(suppliers, 2):
        code = row.get("Contact ID", "")
        net = _decimal_from_text(row.get("Total Purchase Due", "")) - _decimal_from_text(row.get("Total Purchase Return Due", ""))
        if net > 0:
            payables.append({
                "invoice_no": f"OPEN-AP-{code}", "supplier_code": code,
                "invoice_date": capture_date.isoformat(), "due_date": capture_date.isoformat(),
                "currency_code": "AED", "amount": _format(net),
                "control_account_code": "2000", "offset_account_code": "3100",
            })
        elif net < 0:
            exceptions.append({
                "entity": "supplier_balance", "source_key": code, "source_row": row_number,
                "action": "deferred_negative_balance_for_supplier_receivable_review", "amount_aed": _format(net),
            })

    product_cost = {row.get("SKU", ""): _decimal_from_text(row.get("Unit Purchase Price", "")) for row in products}
    current_qty = {row.get("SKU", ""): _quantity(row.get("Current stock", "")) for row in products}
    baseline_qty: defaultdict[str, Decimal] = defaultdict(Decimal)
    provisional_qty: defaultdict[str, Decimal] = defaultdict(Decimal)
    stock: list[dict[str, str]] = []
    summary_rows = zero_rows = 0
    for row_number, row in enumerate(stock_source, 2):
        sku, location = row.get("SKU", ""), row.get("Location", "")
        quantity = _quantity(row.get("Available Stock", ""))
        if sku == "Total:" or location == "Total:" or row.get("Action", "") == "Total:":
            summary_rows += 1
            exceptions.append({"entity": "stock", "source_row": row_number, "action": "excluded_report_summary_row"})
            continue
        if sku:
            baseline_qty[sku] += quantity
        if not location:
            exceptions.append({
                "entity": "stock", "source_key": sku, "source_row": row_number,
                "action": "deferred_missing_source_location", "quantity_base": _format(quantity),
            })
            continue
        if quantity < 0:
            exceptions.append({
                "entity": "stock", "source_key": sku, "source_row": row_number,
                "source_location": location, "action": "deferred_negative_stock_review",
                "quantity_base": _format(quantity),
            })
            continue
        if quantity == 0:
            zero_rows += 1
            continue
        mapping = LOCATION_MAP.get(location)
        if not mapping:
            exceptions.append({
                "entity": "stock", "source_key": sku, "source_row": row_number,
                "source_location": location, "action": "deferred_unmapped_source_location",
                "quantity_base": _format(quantity),
            })
            continue
        if sku not in product_cost:
            exceptions.append({
                "entity": "stock", "source_key": sku, "source_row": row_number,
                "action": "deferred_missing_current_product", "quantity_base": _format(quantity),
            })
            continue
        stock.append({
            "sku": sku, "warehouse_code": mapping["warehouse_code"],
            "location_code": mapping["location_code"], "quantity_base": _format(quantity),
            "unit_cost": _format(product_cost[sku]), "lot_no": "",
        })
        provisional_qty[sku] += quantity

    all_skus = set(baseline_qty) | set(current_qty)
    mismatches = []
    for sku in sorted(all_skus):
        difference = current_qty.get(sku, Decimal("0")) - provisional_qty.get(sku, Decimal("0"))
        if difference:
            mismatches.append({
                "sku": sku, "baseline_quantity": _format(baseline_qty.get(sku, Decimal("0"))),
                "provisional_import_quantity": _format(provisional_qty.get(sku, Decimal("0"))),
                "current_quantity": _format(current_qty.get(sku, Decimal("0"))),
                "delta_required": _format(difference),
            })

    ar_contact = sum((Decimal(row["amount"]) for row in receivables), Decimal("0"))
    ap_contact = sum((Decimal(row["amount"]) for row in payables), Decimal("0"))
    ar_headers = sum((_decimal_from_text(row.get("Sell Due", "")) for row in sales), Decimal("0"))
    ap_headers = sum((_decimal_from_text(row.get("Payment due", "")) for row in purchases), Decimal("0"))
    stock_package_qty = sum((Decimal(row["quantity_base"]) for row in stock), Decimal("0"))

    output.mkdir(parents=True)
    _write_csv(output / "opening_receivables.csv", AR_COLUMNS, receivables)
    _write_csv(output / "opening_payables.csv", AP_COLUMNS, payables)
    _write_csv(output / "opening_stock_provisional.csv", STOCK_COLUMNS, stock)
    (output / "locations.json").write_text(json.dumps(LOCATION_MAP, indent=2) + "\n", encoding="utf-8")
    (output / "stock_delta_required.json").write_text(json.dumps(mismatches, indent=2) + "\n", encoding="utf-8")
    (output / "exceptions.json").write_text(json.dumps(exceptions, indent=2) + "\n", encoding="utf-8")

    status = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "as_of_date": capture_date.isoformat(),
        "mode": "isolated_non_posting_opening_balance_rehearsal",
        "source_capture_atomicity": "NON_ATOMIC",
        "source_mutation": False, "target_staging_mutation": False,
        "posting_enabled": False, "approval_enabled": False, "promotion_allowed": False,
        "balances": {
            "receivables": {"rows": len(receivables), "amount_aed": _format(ar_contact)},
            "payables": {"rows": len(payables), "amount_aed": _format(ap_contact)},
            "negative_customer_balances_deferred": sum(e["entity"] == "customer_balance" for e in exceptions),
            "negative_supplier_balances_deferred": sum(e["entity"] == "supplier_balance" for e in exceptions),
        },
        "header_reconciliation": {
            "receivables_header_due_aed": _format(ar_headers),
            "receivables_positive_contact_due_aed": _format(ar_contact),
            "receivables_variance_aed": _format(ar_contact - ar_headers),
            "payables_header_due_aed": _format(ap_headers),
            "payables_positive_contact_due_aed": _format(ap_contact),
            "payables_variance_aed": _format(ap_contact - ap_headers),
            "decision": "Contact-ID-linked balances are packaged; invoice-header variances remain unresolved and block final cutover qualification.",
        },
        "stock": {
            "source_snapshot": str(stock_path), "snapshot_is_stale": True,
            "provisional_rows": len(stock), "provisional_quantity_base": _format(stock_package_qty),
            "excluded_zero_rows": zero_rows, "excluded_summary_rows": summary_rows,
            "baseline_sku_count": len(baseline_qty), "current_sku_count": len(current_qty),
            "matching_skus": len(all_skus) - len(mismatches), "mismatched_skus": len(mismatches),
            "baseline_total_quantity": _format(sum(baseline_qty.values(), Decimal("0"))),
            "current_total_quantity": _format(sum(current_qty.values(), Decimal("0"))),
            "baseline_to_current_delta": _format(sum(current_qty.values(), Decimal("0")) - sum(baseline_qty.values(), Decimal("0"))),
            "provisional_to_current_delta_required": _format(sum(current_qty.values(), Decimal("0")) - stock_package_qty),
            "location_distribution_delta_required": True,
        },
        "required_configuration": {
            "new_branches_and_warehouses": ["BL0001", "RAK", "DXB"],
            "existing_mapping": "BL0002 maps to SHJ / MAIN / STORAGE",
            "accounts": {"receivables_control": "1100", "payables_control": "2000", "opening_offset": "3100"},
        },
        "transformation_exceptions": len(exceptions),
        "qualification": "Prepared for isolated validation only. Stock is provisional and AR/AP header variances must remain visible; no operational posting is authorized.",
    }
    (output / "PACKAGE_STATUS.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    names = [
        "opening_receivables.csv", "opening_payables.csv", "opening_stock_provisional.csv",
        "locations.json", "stock_delta_required.json", "exceptions.json", "PACKAGE_STATUS.json",
    ]
    (output / "SHA256SUMS.txt").write_text(
        "\n".join(f"{_sha256(output / name)}  {name}" for name in names) + "\n", encoding="utf-8"
    )
    return {
        "status": "prepared_non_posting", "output": str(output),
        "receivables": status["balances"]["receivables"],
        "payables": status["balances"]["payables"], "stock": status["stock"],
        "exceptions": len(exceptions), "posting_enabled": False, "promotion_allowed": False,
    }
