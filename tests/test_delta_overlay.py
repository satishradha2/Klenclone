import csv
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from klen_clone.delta_overlay import DeltaOverlayError, FROZEN_REGISTER_FILES, REGISTER_FILES, load_delta_overlay


HEADERS = {
    "sales": ["Date", "Invoice No.", "Customer name", "Location", "Payment Status", "Total amount", "Total paid", "Sell Due"],
    "purchases": ["Date", "Purchase No", "Location", "Supplier", "Purchase Status", "Grand Total", "Payment due"],
    "products": ["Product", "Unit Purchase Price", "Selling Price", "Category", "Brand", "SKU"],
    "customers": ["Contact ID", "Business Name", "Name"],
    "suppliers": ["Contact ID", "Business Name", "Name"],
    "stock_transfers": ["Date", "Reference No"],
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def sealed_capture(path: Path) -> Path:
    rows = {
        "sales": [["09/09/2026 09:46", "AK2026-03623", "Customer", "SHJ", "Due", "AED 119.75", "0.00", "119.75"]],
        "purchases": [["09/08/2026 20:15", "PO2026/0456", "Asas General Trading LLC", "Supplier", "Received", "AED 65.00", "Purchase: AED 65.00"]],
        "products": [["Tape", "AED 61.90", "AED 81.71", "Disposable", "", "98081"]],
        "customers": [["CO0892", "Al sahwat cafeteria", "No"]],
        "suppliers": [["SU0001", "Supplier", "Owner"]],
        "stock_transfers": [["09/09/2026 09:17", "ST2026/0930"]],
    }
    files = []
    for key, filename in REGISTER_FILES.items():
        file_path = path / filename
        with file_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(HEADERS[key])
            writer.writerows(rows[key])
        files.append({"name": filename, "rows": 1, "sha256": _sha(file_path)})
    status = {
        "captured_at_utc": "2026-09-09T06:30:24.859Z",
        "atomicity": "NON_ATOMIC",
        "files": files,
        "prior_watermark_comparison": {key: {"prior": 0} for key in REGISTER_FILES},
    }
    (path / "CAPTURE_STATUS.json").write_text(json.dumps(status), encoding="utf-8")
    return path


def test_sealed_overlay_parses_provisional_registers(tmp_path):
    overlay = load_delta_overlay(sealed_capture(tmp_path))
    assert overlay is not None
    assert overlay.hashes_verified and overlay.rows_verified
    assert not overlay.atomic
    assert overlay.counts["sales"] == 1
    assert overlay.sale_records()[0]["document_no"] == "AK2026-03623"
    assert overlay.sale_records()[0]["total_amount"] == Decimal("119.75")
    assert overlay.purchase_records()[0]["due_amount"] == Decimal("65")
    assert overlay.product_records()[0]["master_status"] == "provisional_overlay"


def test_overlay_refuses_changed_sealed_file(tmp_path):
    capture = sealed_capture(tmp_path)
    (capture / REGISTER_FILES["sales"]).write_text("changed", encoding="utf-8")
    with pytest.raises(DeltaOverlayError, match="verification failed"):
        load_delta_overlay(capture)


def test_frozen_overlay_accepts_new_manifest_and_overlap_sales(tmp_path):
    path = tmp_path / "frozen"
    (path / "delta").mkdir(parents=True)
    rows = {
        "sales": [["09/09/2026 09:46", "AK2026-03667", "Customer", "SHJ", "Due", "AED 10", "0", "10"]],
        "purchases": [["09/09/2026 09:46", "PO2026/0467", "SHJ", "Supplier", "Received", "AED 20", "Purchase: AED 20"]],
        "products": [["Tape", "AED 1", "AED 2", "Disposable", "", "98096"]],
        "customers": [["CO0894", "Customer", "Owner"]],
        "suppliers": [["CO0896", "Supplier", "Owner"]],
        "stock_transfers": [["09/09/2026 09:46", "ST2026/0947"]],
        "sales_payments": [["SP2026/3826"]],
        "purchase_payments": [["PP2026/0446"]],
        "sales_returns": [["09/09/2026 09:46", "CN2026/0043", "Customer", "SHJ", "Due", "AED 5", "0", "5"]],
        "purchase_returns": [["09/09/2026 09:46", "2026/0013", "SHJ", "Supplier", "Due", "AED 6", "6"]],
    }
    headers = dict(HEADERS)
    headers.update({
        "sales_payments": ["Reference No"], "purchase_payments": ["Reference No"],
        "sales_returns": ["Date", "Invoice No.", "Customer name", "Location", "Payment Status", "Total amount", "Total paid", "Payment due"],
        "purchase_returns": ["Date", "Reference No", "Location", "Supplier", "Payment Status", "Grand Total", "Payment due"],
    })
    exports = []
    for key, filename in FROZEN_REGISTER_FILES.items():
        file_path = path / filename
        with file_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle); writer.writerow(headers[key]); writer.writerows(rows[key])
        exports.append({"file": filename, "rows": 1, "sha256": _sha(file_path)})
    (path / "CAPTURE_STATUS.json").write_text(json.dumps({
        "exports": exports, "capture_completed_at_local": "2026-09-10T03:49:42+04:00",
        "atomic_database_snapshot": False,
    }), encoding="utf-8")
    (path / "delta" / "DELTA_RECONCILIATION.json").write_text(json.dumps({
        "new_rows": {key: 1 for key in rows}
    }), encoding="utf-8")
    overlay = load_delta_overlay(path)
    assert overlay and overlay.counts["products"] == 1
    assert overlay.deltas["sales"] == 1 and "sales" in overlay.overlap_entities
    assert overlay.sale_return_records()[0]["document_no"] == "CN2026/0043"
    assert overlay.purchase_return_records()[0]["document_no"] == "2026/0013"
