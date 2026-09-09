from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


class ErpMasterRehearsalError(RuntimeError):
    pass


PRODUCT_COLUMNS = [
    "sku", "name", "base_uom", "barcode", "description", "hs_code",
    "country_of_origin", "standard_cost", "default_sales_price", "pack_uom",
    "pack_factor", "pack_barcode",
]
PARTNER_COLUMNS = [
    "code", "legal_name", "trade_name", "trn", "country_code", "currency_code",
    "credit_limit", "phone", "email", "address", "city", "payment_term",
]
SUPPLIER_COLUMNS = [column for column in PARTNER_COLUMNS if column != "credit_limit"]
_UOM = {
    "pieces": "PCS", "piece": "PCS", "pc(s)": "PCS", "pcs": "PCS",
    "pack": "PACK", "carton": "CARTON", "kg": "KG", "kilogram": "KG",
    "box": "BOX", "bundle": "BUNDLE", "dozen": "DOZEN",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{str(key): str(value or "").strip() for key, value in row.items() if key is not None}
                for row in csv.DictReader(handle)]


def _money(value: str) -> str:
    cleaned = re.sub(r"[^0-9.\-]", "", value or "")
    try:
        return f"{Decimal(cleaned or '0'):.2f}"
    except InvalidOperation:
        return "0.00"


def _base_uom(stock_text: str) -> str:
    match = re.match(r"^[-0-9,.]+\s+(.+?)\s*$", stock_text or "")
    if not match:
        raise ErpMasterRehearsalError(f"Cannot identify base UOM from {stock_text!r}")
    source = match.group(1).strip().lower()
    if source not in _UOM:
        raise ErpMasterRehearsalError(f"Unsupported source base UOM: {source}")
    return _UOM[source]


def _payment_term(value: str) -> tuple[str, int]:
    match = re.search(r"(\d+)\s*days?", value or "", re.IGNORECASE)
    if not match:
        return "COD", 0
    days = int(match.group(1))
    return f"NET{days}", days


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)


def build_erp_master_package(capture_dir: Path, output_dir: Path) -> dict[str, Any]:
    capture = capture_dir.resolve()
    output = output_dir.resolve()
    if not capture.is_dir():
        raise ErpMasterRehearsalError(f"Capture directory not found: {capture}")
    if output.exists():
        raise ErpMasterRehearsalError(f"Output already exists; overwrite refused: {output}")

    status_path = capture / "CAPTURE_STATUS.json"
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ErpMasterRehearsalError("Capture status is not readable") from exc
    if status.get("atomicity") != "NON_ATOMIC" or status.get("final_cutover_eligible") is not False:
        raise ErpMasterRehearsalError("Expected the sealed non-atomic capture checkpoint")

    inventory = {item["name"]: item for item in status.get("files", [])}
    required = {
        "products_current.csv", "customers_current.csv", "suppliers_current.csv",
        "sales_2026_current.csv", "purchases_2026_current.csv",
    }
    missing = sorted(required - inventory.keys())
    if missing:
        raise ErpMasterRehearsalError(f"Required capture files missing: {', '.join(missing)}")
    for name in required:
        actual = _sha256(capture / name)
        if actual != str(inventory[name].get("sha256", "")).upper():
            raise ErpMasterRehearsalError(f"Capture checksum mismatch: {name}")

    products_source = _read_csv(capture / "products_current.csv")
    customers_source = _read_csv(capture / "customers_current.csv")
    suppliers_source = _read_csv(capture / "suppliers_current.csv")
    sales_source = _read_csv(capture / "sales_2026_current.csv")
    purchases_source = _read_csv(capture / "purchases_2026_current.csv")

    exceptions: list[dict[str, Any]] = []
    products: list[dict[str, Any]] = []
    seen_skus: set[str] = set()
    for row_number, source in enumerate(products_source, start=2):
        sku = source.get("SKU", "")
        if not sku or sku in seen_skus:
            raise ErpMasterRehearsalError(f"Missing or duplicate product SKU at source row {row_number}")
        seen_skus.add(sku)
        products.append({
            "sku": sku,
            "name": source.get("Product", "") or f"Source product {sku}",
            "base_uom": _base_uom(source.get("Current stock", "")),
            "barcode": "",
            "description": "",
            "hs_code": "",
            "country_of_origin": "AE",
            "standard_cost": _money(source.get("Unit Purchase Price", "")),
            "default_sales_price": _money(source.get("Selling Price", "")),
            "pack_uom": "",
            "pack_factor": "",
            "pack_barcode": "",
        })

    all_partner_sources = customers_source + suppliers_source
    trn_counts = Counter(row.get("Tax number", "") for row in all_partner_sources if row.get("Tax number", ""))
    required_terms: dict[str, int] = {"COD": 0}

    def partner_rows(source_rows: list[dict[str, str]], kind: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row_number, source in enumerate(source_rows, start=2):
            code = source.get("Contact ID", "")
            if not code or code in seen:
                raise ErpMasterRehearsalError(f"Missing or duplicate {kind} code at source row {row_number}")
            seen.add(code)
            legal_name = source.get("Business Name", "")
            if not legal_name:
                legal_name = source.get("Name", "") or f"Source partner {code}"
                exceptions.append({"entity": kind, "source_key": code, "field": "legal_name",
                                   "action": "fallback_to_contact_name", "source_row": row_number})
            raw_trn = source.get("Tax number", "")
            trn = raw_trn
            if raw_trn and not re.fullmatch(r"\d{15}", raw_trn):
                trn = ""
                exceptions.append({"entity": kind, "source_key": code, "field": "trn",
                                   "action": "quarantined_invalid_uae_trn", "source_row": row_number,
                                   "source_value_sha256": hashlib.sha256(raw_trn.encode()).hexdigest().upper()})
            elif raw_trn and trn_counts[raw_trn] > 1:
                trn = ""
                exceptions.append({"entity": kind, "source_key": code, "field": "trn",
                                   "action": "quarantined_duplicate_trn", "source_row": row_number,
                                   "source_value_sha256": hashlib.sha256(raw_trn.encode()).hexdigest().upper()})
            term, days = _payment_term(source.get("Pay term", ""))
            required_terms[term] = days
            target = {
                "code": code,
                "legal_name": legal_name,
                "trade_name": source.get("Name", ""),
                "trn": trn,
                "country_code": "AE",
                "currency_code": "AED",
                "phone": source.get("Mobile", ""),
                "email": source.get("Email", ""),
                "address": source.get("Address", ""),
                "city": "",
                "payment_term": term,
            }
            if kind == "customer":
                target["credit_limit"] = _money(source.get("Credit Limit", ""))
            result.append(target)
        return result

    customers = partner_rows(customers_source, "customer")
    suppliers = partner_rows(suppliers_source, "supplier")
    customer_names = Counter(
        re.sub(r"\s+", " ", (row.get("Business Name") or row.get("Name") or "").strip()).casefold()
        for row in customers_source if row.get("Business Name") or row.get("Name")
    )
    supplier_names = Counter(
        re.sub(r"\s+", " ", (row.get("Business Name") or row.get("Name") or "").strip()).casefold()
        for row in suppliers_source if row.get("Business Name") or row.get("Name")
    )

    def balance_candidates(rows: list[dict[str, str]], name_field: str, due_field: str,
                           names: Counter[str]) -> dict[str, Any]:
        positive = []
        matched = 0
        ambiguous = 0
        unmatched = 0
        total = Decimal("0")
        for row in rows:
            amount = Decimal(_money(row.get(due_field, "")))
            if amount <= 0:
                continue
            positive.append(row)
            total += amount
            normalized = re.sub(r"\s+", " ", row.get(name_field, "").strip()).casefold()
            count = names.get(normalized, 0)
            if count == 1:
                matched += 1
            elif count > 1:
                ambiguous += 1
            else:
                unmatched += 1
        return {"candidate_rows": len(positive), "candidate_total_aed": f"{total:.2f}",
                "unique_name_matches": matched, "ambiguous_name_matches": ambiguous,
                "unmatched_names": unmatched, "status": "deferred_not_posted"}

    output.mkdir(parents=True)
    _write_csv(output / "products.csv", PRODUCT_COLUMNS, products)
    _write_csv(output / "customers.csv", PARTNER_COLUMNS, customers)
    _write_csv(output / "suppliers.csv", SUPPLIER_COLUMNS, suppliers)
    (output / "exceptions.json").write_text(json.dumps(exceptions, indent=2) + "\n", encoding="utf-8")

    package_status = {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source_capture": str(capture),
        "source_capture_atomicity": "NON_ATOMIC",
        "mode": "isolated_non_posting_erp_master_import_rehearsal",
        "source_mutation": False,
        "preserved_clone_mutation": False,
        "target_staging_mutation": False,
        "posting_enabled": False,
        "approval_enabled": False,
        "later_delta_supported": True,
        "deduplication_keys": {"products": "sku", "customers": "code", "suppliers": "code"},
        "ready_master_rows": {"products": len(products), "customers": len(customers), "suppliers": len(suppliers)},
        "required_configuration": {
            "units_of_measure": sorted({row["base_uom"] for row in products}),
            "payment_terms": [{"code": code, "due_days": days} for code, days in sorted(required_terms.items())],
        },
        "opening_receivables": balance_candidates(sales_source, "Customer name", "Sell Due", customer_names),
        "opening_payables": balance_candidates(purchases_source, "Supplier", "Payment due", supplier_names),
        "deferred": {
            "opening_stock": "Location-level current stock was not available in this non-atomic register package.",
            "historical_sales": f"{len(sales_source)} headers preserved; transaction posting deferred because line detail is incomplete.",
            "historical_purchases": f"{len(purchases_source)} headers preserved; transaction posting deferred because line detail is incomplete.",
            "attachments": "Deferred; username/password-only capture does not guarantee uploaded-file completeness.",
        },
        "transformation_exceptions": len(exceptions),
        "promotion_allowed": False,
        "qualification": "Master rows are ready for isolated validation only; no operational ERP posting is authorized.",
    }
    status_file = output / "PACKAGE_STATUS.json"
    status_file.write_text(json.dumps(package_status, indent=2) + "\n", encoding="utf-8")
    package_files = ["products.csv", "customers.csv", "suppliers.csv", "exceptions.json", "PACKAGE_STATUS.json"]
    checksums = [_sha256(output / name) + "  " + name for name in package_files]
    (output / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")
    return {
        "status": "prepared_non_posting",
        "output": str(output),
        "ready_master_rows": package_status["ready_master_rows"],
        "transformation_exceptions": len(exceptions),
        "opening_receivables": package_status["opening_receivables"],
        "opening_payables": package_status["opening_payables"],
        "posting_enabled": False,
        "promotion_allowed": False,
    }
