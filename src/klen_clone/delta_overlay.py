from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any


DEFAULT_CAPTURE = Path("source_exports/2026-09-09-current-non-atomic")
REGISTER_FILES = {
    "sales": "sales_2026_current.csv",
    "purchases": "purchases_2026_current.csv",
    "products": "products_current.csv",
    "customers": "customers_current.csv",
    "suppliers": "suppliers_current.csv",
    "stock_transfers": "stock_transfers_2026_current.csv",
}
FROZEN_REGISTER_FILES = {
    "sales": "sales_last_30_days.csv",
    "purchases": "purchases_2026.csv",
    "products": "products.csv",
    "customers": "customers.csv",
    "suppliers": "suppliers.csv",
    "stock_transfers": "stock_transfers_2026.csv",
    "sales_payments": "sales_payments_2026.csv",
    "purchase_payments": "purchase_payments_2026.csv",
    "sales_returns": "sales_returns_2026.csv",
    "purchase_returns": "purchase_returns_2026.csv",
}


class DeltaOverlayError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _money(value: Any) -> Decimal:
    matches = re.findall(r"-?[0-9,]+(?:\.[0-9]+)?", str(value or ""))
    return Decimal(matches[-1].replace(",", "")) if matches else Decimal("0")


def _date(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return datetime.strptime(text, "%m/%d/%Y %H:%M").isoformat()


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


@dataclass(frozen=True)
class DeltaOverlay:
    capture_path: Path
    captured_at_utc: str
    atomic: bool
    hashes_verified: bool
    rows_verified: bool
    counts: dict[str, int]
    prior_counts: dict[str, int]
    rows: dict[str, list[dict[str, str]]]
    overlap_entities: frozenset[str] = frozenset()

    @property
    def deltas(self) -> dict[str, int]:
        return {key: self.counts[key] - self.prior_counts.get(key, 0) for key in self.counts}

    def product_records(self) -> list[dict[str, Any]]:
        records = []
        for row in self.rows["products"]:
            stock = str(row.get("Current stock") or "").strip().split(" ", 1)
            records.append({
                "sku": row.get("SKU"),
                "name": row.get("Product"),
                "category_name": row.get("Category"),
                "brand_name": row.get("Brand"),
                "purchase_price_evidence": _money(row.get("Unit Purchase Price")),
                "selling_price_evidence": _money(row.get("Selling Price")),
                "base_uom": stock[1].strip() if len(stock) == 2 else str(row.get("Sub Unit") or "").strip(),
                "master_status": "provisional_overlay",
            })
        return records

    def party_records(self, kind: str) -> list[dict[str, Any]]:
        source = self.rows["customers" if kind == "customer" else "suppliers"]
        return [{
            "party_code": row.get("Contact ID"),
            "legal_or_business_name": row.get("Business Name") or row.get("Name"),
            "contact_name": row.get("Name"),
            "party_kind": kind,
            "master_status": "provisional_overlay",
        } for row in source]

    def sale_records(self) -> list[dict[str, Any]]:
        return [{
            "source_kind": "sale",
            "document_no": row.get("Invoice No."),
            "occurred_at": _date(row.get("Date")),
            "party_name": row.get("Customer name"),
            "location": row.get("Location"),
            "total_amount": _money(row.get("Total amount")),
            "paid_amount": _money(row.get("Total paid")),
            "due_amount": _money(row.get("Sell Due")),
            "source_status": row.get("Payment Status"),
            "migration_status": "provisional_overlay",
        } for row in self.rows["sales"]]

    def purchase_records(self) -> list[dict[str, Any]]:
        return [{
            "source_kind": "purchase",
            "document_no": row.get("Purchase No"),
            "occurred_at": _date(row.get("Date")),
            "party_name": row.get("Supplier"),
            "location": row.get("Location"),
            "total_amount": _money(row.get("Grand Total")),
            "paid_amount": _money(row.get("Grand Total")) - _money(row.get("Payment due")),
            "due_amount": _money(row.get("Payment due")),
            "source_status": row.get("Purchase Status"),
            "migration_status": "provisional_overlay",
        } for row in self.rows["purchases"]]

    def sale_return_records(self) -> list[dict[str, Any]]:
        return [{
            "source_kind": "sale_return",
            "document_no": row.get("Invoice No."),
            "occurred_at": _date(row.get("Date")),
            "party_name": row.get("Customer name"),
            "location": row.get("Location"),
            "total_amount": _money(row.get("Total amount")),
            "paid_amount": _money(row.get("Total paid")),
            "due_amount": _money(row.get("Payment due")),
            "source_status": row.get("Payment Status"),
            "migration_status": "provisional_overlay",
        } for row in self.rows.get("sales_returns", [])]

    def purchase_return_records(self) -> list[dict[str, Any]]:
        return [{
            "source_kind": "purchase_return",
            "document_no": row.get("Reference No"),
            "occurred_at": _date(row.get("Date")),
            "party_name": row.get("Supplier"),
            "location": row.get("Location"),
            "total_amount": _money(row.get("Grand Total")),
            "paid_amount": _money(row.get("Grand Total")) - _money(row.get("Payment due")),
            "due_amount": _money(row.get("Payment due")),
            "source_status": row.get("Payment Status"),
            "migration_status": "provisional_overlay",
        } for row in self.rows.get("purchase_returns", [])]


def load_delta_overlay(path: Path | None = None) -> DeltaOverlay | None:
    configured = path or Path(os.getenv("ASAS_DELTA_CAPTURE", DEFAULT_CAPTURE))
    capture = configured.resolve()
    status_path = capture / "CAPTURE_STATUS.json"
    if not status_path.is_file():
        return None
    status = json.loads(status_path.read_text(encoding="utf-8"))
    frozen = bool(status.get("exports"))
    file_map = FROZEN_REGISTER_FILES if frozen else REGISTER_FILES
    declared = {item.get("file") or item.get("name"): item for item in status.get("exports", status.get("files", []))}
    register_rows: dict[str, list[dict[str, str]]] = {}
    hashes_verified = True
    rows_verified = True
    for key, filename in file_map.items():
        metadata = declared.get(filename)
        file_path = capture / filename
        if metadata is None or not file_path.is_file():
            raise DeltaOverlayError(f"Required sealed register is missing: {filename}")
        actual_hash = _sha256(file_path)
        if actual_hash != str(metadata.get("sha256", "")).upper():
            hashes_verified = False
        register_rows[key] = _rows(file_path)
        if len(register_rows[key]) != int(metadata.get("rows", -1)):
            rows_verified = False
    if not hashes_verified or not rows_verified:
        raise DeltaOverlayError("Delta overlay refused because sealed evidence verification failed")
    comparisons = status.get("prior_watermark_comparison", {})
    counts = {key: len(value) for key, value in register_rows.items()}
    if frozen:
        reconciliation_path = capture / "delta" / "DELTA_RECONCILIATION.json"
        reconciliation = json.loads(reconciliation_path.read_text(encoding="utf-8"))
        new_rows = reconciliation.get("new_rows", {})
        prior_counts = {key: counts[key] - int(new_rows.get(key, 0)) for key in counts}
    else:
        prior_counts = {key: int(comparisons.get(key, {}).get("prior", counts[key])) for key in counts}
    return DeltaOverlay(
        capture_path=capture,
        captured_at_utc=str(status.get("captured_at_utc") or status.get("capture_completed_at_local") or ""),
        atomic=(bool(status.get("atomic_database_snapshot")) if frozen
                else str(status.get("atomicity") or "").upper() == "ATOMIC"),
        hashes_verified=True,
        rows_verified=True,
        counts=counts,
        prior_counts=prior_counts,
        rows=register_rows,
        overlap_entities=frozenset({"sales"} if frozen else set()),
    )
