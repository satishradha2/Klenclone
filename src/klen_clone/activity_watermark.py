from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ActivityWatermarkError(RuntimeError):
    pass


REQUIRED_RELIABLE_STREAMS = {
    "sales",
    "purchases",
    "products",
    "customers",
    "suppliers",
    "stock_transfers",
    "sales_payments",
    "purchase_payments",
    "sales_returns",
    "purchase_returns",
}


def load_watermark(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ActivityWatermarkError(f"Watermark not found: {resolved}")
    value = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ActivityWatermarkError("Unsupported activity-watermark schema")
    if value.get("source_mutation") is not False or value.get("merge_allowed") is not False or value.get("posting_enabled") is not False:
        raise ActivityWatermarkError("Watermark does not prove read-only safety controls")
    streams = value.get("watermarks")
    if not isinstance(streams, dict):
        raise ActivityWatermarkError("Watermark stream map is missing")
    missing = sorted(REQUIRED_RELIABLE_STREAMS - streams.keys())
    if missing:
        raise ActivityWatermarkError(f"Required watermark streams missing: {', '.join(missing)}")
    unreliable = sorted(name for name in REQUIRED_RELIABLE_STREAMS if streams[name].get("reliable") is not True)
    if unreliable:
        raise ActivityWatermarkError(f"Required watermark streams are unreliable: {', '.join(unreliable)}")
    return value


def compare_watermarks(before_path: Path, after_path: Path, output_path: Path) -> dict[str, Any]:
    output = output_path.resolve()
    if output.exists():
        raise ActivityWatermarkError(f"Output already exists; overwrite refused: {output}")
    if output.suffix.lower() != ".json":
        raise ActivityWatermarkError("Watermark comparison output must be a new JSON file")

    before = load_watermark(before_path)
    after = load_watermark(after_path)
    comparisons = []
    changes = []
    for name in sorted(REQUIRED_RELIABLE_STREAMS):
        old = before["watermarks"][name]
        new = after["watermarks"][name]
        fields = sorted({"visible_count", "latest_key", "latest_evidence_key"} & (old.keys() | new.keys()))
        differences = {field: {"before": old.get(field), "after": new.get(field)} for field in fields if old.get(field) != new.get(field)}
        comparisons.append({"stream": name, "status": "changed" if differences else "stable", "differences": differences})
        if differences:
            changes.append(name)

    both_frozen = before.get("transaction_free_window_confirmed") is True and after.get("transaction_free_window_confirmed") is True
    report = {
        "schema_version": 1,
        "status": "activity_detected" if changes else "stable_watermarks",
        "changed_streams": changes,
        "transaction_free_window_confirmed": both_frozen,
        "final_capture_allowed": not changes and both_frozen,
        "merge_allowed": False,
        "posting_enabled": False,
        "before": str(before_path.resolve()),
        "after": str(after_path.resolve()),
        "comparisons": comparisons,
        "qualification": "Stable watermarks detect common activity but are not atomic database isolation.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "status": report["status"],
        "changed_streams": changes,
        "transaction_free_window_confirmed": both_frozen,
        "final_capture_allowed": report["final_capture_allowed"],
        "merge_allowed": False,
        "posting_enabled": False,
        "output": str(output),
    }
