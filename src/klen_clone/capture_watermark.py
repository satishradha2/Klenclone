from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .activity_watermark import load_watermark


class CaptureWatermarkError(RuntimeError):
    pass


_STREAMS = {
    "sales": ("sales_2026_current.csv", "Invoice No.", "Date", "https://mart.bizmodo.io/sells", "This Year"),
    "purchases": ("purchases_2026_current.csv", "Purchase No", "Date", "https://mart.bizmodo.io/purchases", None),
    "products": ("products_current.csv", None, None, "https://mart.bizmodo.io/products", None),
    "customers": ("customers_current.csv", "Contact ID", None, "https://mart.bizmodo.io/contacts?type=customer", None),
    "suppliers": ("suppliers_current.csv", None, None, "https://mart.bizmodo.io/contacts?type=supplier", None),
    "stock_transfers": ("stock_transfers_2026_current.csv", "Reference No", "Date", "https://mart.bizmodo.io/stock-transfers", "This Year"),
    "sales_payments": ("sales_payments_current.csv", "Reference No", "Paid on", "https://mart.bizmodo.io/reports/sell-payment-report", None),
    "purchase_payments": ("purchase_payments_current.csv", "Reference No", "Paid on", "https://mart.bizmodo.io/reports/purchase-payment-report", None),
    "sales_returns": ("sales_returns_2026_current.csv", "Invoice No.", "Date", "https://mart.bizmodo.io/sell-return", "This Year"),
    "purchase_returns": ("purchase_returns_2026_current.csv", "Reference No", "Date", "https://mart.bizmodo.io/purchase-return", "This Year"),
}


def _load_status(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaptureWatermarkError(f"Capture status is invalid: {path}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise CaptureWatermarkError("Unsupported capture-status schema")
    if value.get("atomicity") != "NON_ATOMIC" or value.get("final_cutover_eligible") is not False:
        raise CaptureWatermarkError("Rehearsal watermark requires a sealed non-atomic capture")
    return value


def _rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except (OSError, csv.Error) as exc:
        raise CaptureWatermarkError(f"Capture CSV is unreadable: {path}") from exc


def build_capture_watermark(capture_dir: Path, before_path: Path, output_path: Path) -> dict[str, Any]:
    capture = capture_dir.resolve()
    output = output_path.resolve()
    if not capture.is_dir():
        raise CaptureWatermarkError(f"Capture directory not found: {capture}")
    if output.exists():
        raise CaptureWatermarkError(f"Output already exists; overwrite refused: {output}")
    if output.suffix.lower() != ".json":
        raise CaptureWatermarkError("Capture watermark output must be a new JSON file")

    status = _load_status(capture / "CAPTURE_STATUS.json")
    before = load_watermark(before_path)
    file_inventory = {item["name"]: item for item in status.get("files", []) if isinstance(item, dict) and "name" in item}
    watermarks: dict[str, dict[str, Any]] = {}

    for stream, (filename, key_field, date_field, source_url, scope) in _STREAMS.items():
        inventory = file_inventory.get(filename)
        if not inventory:
            raise CaptureWatermarkError(f"Capture inventory is missing {filename}")
        rows = _rows(capture / filename)
        if len(rows) != inventory.get("rows"):
            raise CaptureWatermarkError(f"Capture row count changed for {filename}")
        value: dict[str, Any] = {
            "source_url": source_url,
            "visible_count": len(rows),
            "reliable": True,
            "evidence_file": filename,
        }
        if scope:
            value["scope"] = scope
        if key_field:
            ordered_rows = reversed(rows) if stream == "customers" else iter(rows)
            latest = next((row for row in ordered_rows if row.get(key_field, "").strip()), None)
            if latest is not None:
                key_name = "latest_evidence_key" if stream == "customers" else "latest_key"
                value[key_name] = latest[key_field].strip()
                if date_field and latest.get(date_field, "").strip():
                    value["latest_at"] = latest[date_field].strip()
        else:
            prior = before["watermarks"][stream]
            if len(rows) == prior.get("visible_count"):
                for key_name in ("latest_key", "latest_evidence_key"):
                    if prior.get(key_name) is not None:
                        value[key_name] = prior[key_name]
                        value["retained_key_basis"] = "Count unchanged; key retained from the prior reliable watermark."
        watermarks[stream] = value

    changed = sorted(
        name for name, value in watermarks.items()
        if value["visible_count"] != before["watermarks"][name].get("visible_count")
        or value.get("latest_key") != before["watermarks"][name].get("latest_key")
        or value.get("latest_evidence_key") != before["watermarks"][name].get("latest_evidence_key")
    )
    report = {
        "schema_version": 1,
        "captured_at_utc": status.get("captured_at_utc"),
        "source_url": "https://mart.bizmodo.io/",
        "source_version": status.get("application", "BizModo V7.5.1"),
        "capture_mode": "sealed_authenticated_browser_register_package",
        "phase": "closing_rehearsal",
        "transaction_free_window_confirmed": False,
        "atomic": False,
        "source_mutation": False,
        "clone_mutation": False,
        "merge_allowed": False,
        "posting_enabled": False,
        "watermarks": watermarks,
        "summary": {
            "reliable_streams": len(watermarks),
            "changed_streams": changed,
            "activity_freeze_proven": False,
            "final_capture_allowed": False,
        },
        "limitations": [
            "This closing rehearsal was derived from a non-atomic browser capture.",
            "No transaction-free window was confirmed.",
            "Stable visible rows cannot detect hidden-field edits or guarantee database isolation.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "status": "activity_detected" if changed else "stable_watermarks",
        "changed_streams": changed,
        "transaction_free_window_confirmed": False,
        "final_capture_allowed": False,
        "merge_allowed": False,
        "posting_enabled": False,
        "output": str(output),
    }
