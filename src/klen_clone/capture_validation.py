from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any


class CaptureValidationError(RuntimeError):
    pass


_CHECKSUM_LINE = re.compile(r"^([A-Fa-f0-9]{64})  (.+)$")
_STREAM_FILES = {
    "sales": "sales_2026_current.csv",
    "purchases": "purchases_2026_current.csv",
    "products": "products_current.csv",
    "customers": "customers_current.csv",
    "suppliers": "suppliers_current.csv",
    "stock_transfers": "stock_transfers_2026_current.csv",
    "sales_payments": "sales_payments_current.csv",
    "purchase_payments": "purchase_payments_current.csv",
    "sales_returns": "sales_returns_2026_current.csv",
    "purchase_returns": "purchase_returns_2026_current.csv",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaptureValidationError(f"Invalid capture metadata: {path}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise CaptureValidationError("Unsupported capture-status schema")
    return value


def _manifest(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise CaptureValidationError(f"Checksum manifest not readable: {path}") from exc
    for line in lines:
        match = _CHECKSUM_LINE.fullmatch(line)
        if not match:
            raise CaptureValidationError(f"Invalid checksum line: {line!r}")
        name = match.group(2)
        if name in entries:
            raise CaptureValidationError(f"Duplicate checksum entry: {name}")
        entries[name] = match.group(1).upper()
    return entries


def _csv_shape(path: Path) -> tuple[int, int, list[int]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise CaptureValidationError(f"CSV has no header: {path.name}") from exc
        invalid_rows: list[int] = []
        row_count = 0
        for line_number, row in enumerate(reader, start=2):
            row_count += 1
            if len(row) != len(header):
                invalid_rows.append(line_number)
        return row_count, len(header), invalid_rows


def validate_capture(source_dir: Path, output_path: Path) -> dict[str, Any]:
    source = source_dir.resolve()
    output = output_path.resolve()
    if not source.is_dir():
        raise CaptureValidationError(f"Capture directory not found: {source}")
    if output.exists():
        raise CaptureValidationError(f"Output already exists; overwrite refused: {output}")
    if output.suffix.lower() != ".json":
        raise CaptureValidationError("Capture validation output must be a new JSON file")

    status_path = source / "CAPTURE_STATUS.json"
    manifest_path = source / "SHA256SUMS.txt"
    metadata = _load_json(status_path)
    checksums = _manifest(manifest_path)
    files = metadata.get("files")
    if not isinstance(files, list) or not files:
        raise CaptureValidationError("Capture file inventory is missing")

    before_hashes = {path.name: _sha256(path) for path in source.iterdir() if path.is_file()}
    declared_names = [item.get("name") for item in files if isinstance(item, dict)]
    expected_names = set(declared_names) | {"CAPTURE_STATUS.json", "SHA256SUMS.txt"}
    actual_names = {path.name for path in source.iterdir() if path.is_file()}

    controls: list[dict[str, Any]] = []

    def control(code: str, passed: bool, evidence: Any) -> None:
        controls.append({"code": code, "status": "pass" if passed else "fail", "evidence": evidence})

    inventory_ok = (
        len(declared_names) == len(set(declared_names))
        and None not in declared_names
        and expected_names == actual_names
    )
    control(
        "FILE_INVENTORY",
        inventory_ok,
        {"declared": sorted(name for name in declared_names if isinstance(name, str)),
         "missing": sorted(expected_names - actual_names),
         "unexpected": sorted(actual_names - expected_names)},
    )

    manifest_expected = set(declared_names) | {"CAPTURE_STATUS.json"}
    hash_results = []
    for name in sorted(manifest_expected):
        path = source / name
        actual = _sha256(path) if path.is_file() else None
        declared = checksums.get(name)
        metadata_hash = next((item.get("sha256") for item in files if item.get("name") == name), None)
        matches = actual is not None and actual == declared and (metadata_hash is None or actual == metadata_hash)
        hash_results.append({"name": name, "status": "pass" if matches else "fail",
                             "actual": actual, "manifest": declared, "metadata": metadata_hash})
    checksum_ok = set(checksums) == manifest_expected and all(item["status"] == "pass" for item in hash_results)
    control("CHECKSUM_MANIFEST", checksum_ok,
            {"entries": hash_results, "unexpected": sorted(set(checksums) - manifest_expected)})

    csv_results = []
    for item in files:
        name = item.get("name")
        path = source / name
        try:
            rows, columns, invalid_rows = _csv_shape(path)
        except (OSError, csv.Error, CaptureValidationError) as exc:
            csv_results.append({"name": name, "status": "fail", "error": str(exc)})
            continue
        matches = rows == item.get("rows") and columns == item.get("columns") and not invalid_rows
        csv_results.append({"name": name, "status": "pass" if matches else "fail",
                            "rows": rows, "expected_rows": item.get("rows"),
                            "columns": columns, "expected_columns": item.get("columns"),
                            "invalid_row_numbers": invalid_rows[:20]})
    control("CSV_SHAPE", len(csv_results) == len(files) and all(item["status"] == "pass" for item in csv_results), csv_results)

    safety_ok = (
        metadata.get("atomicity") == "NON_ATOMIC"
        and metadata.get("final_cutover_eligible") is False
        and "read-only" in str(metadata.get("source_access", "")).lower()
    )
    control("READ_ONLY_NON_ATOMIC_SAFETY", safety_ok,
            {"atomicity": metadata.get("atomicity"),
             "final_cutover_eligible": metadata.get("final_cutover_eligible"),
             "source_access": metadata.get("source_access")})

    comparison = metadata.get("prior_watermark_comparison", {})
    file_rows = {item.get("name"): item.get("rows") for item in files}
    drift_results = []
    for stream, filename in _STREAM_FILES.items():
        values = comparison.get(stream, {})
        prior = values.get("prior")
        current = values.get("current")
        delta = values.get("delta")
        valid = (
            isinstance(prior, int) and isinstance(current, int) and isinstance(delta, int)
            and current - prior == delta and file_rows.get(filename) == current
        )
        drift_results.append({"stream": stream, "status": "pass" if valid else "fail",
                              "prior": prior, "current": current, "delta": delta, "file": filename})
    control("WATERMARK_ARITHMETIC", all(item["status"] == "pass" for item in drift_results), drift_results)

    changed_streams = sorted(item["stream"] for item in drift_results if item.get("delta") not in (0, None))
    drift_detected = bool(changed_streams)
    control("FINAL_CUTOVER_GATE", not metadata.get("final_cutover_eligible") and drift_detected,
            {"drift_detected": drift_detected, "changed_streams": changed_streams,
             "merge_allowed": False, "posting_enabled": False})

    failed = [item["code"] for item in controls if item["status"] == "fail"]
    after_hashes = {path.name: _sha256(path) for path in source.iterdir() if path.is_file()}
    source_unchanged = before_hashes == after_hashes
    control("SOURCE_PACKAGE_UNCHANGED", source_unchanged, {"source_files_changed": [] if source_unchanged else "detected"})
    if not source_unchanged:
        failed.append("SOURCE_PACKAGE_UNCHANGED")

    report = {
        "schema_version": 1,
        "status": "valid_non_atomic_capture" if not failed else "failed",
        "source": str(source),
        "source_capture_unchanged": source_unchanged,
        "changed_streams": changed_streams,
        "drift_detected": drift_detected,
        "final_cutover_allowed": False,
        "merge_allowed": False,
        "posting_enabled": False,
        "failed_controls": failed,
        "controls": controls,
        "qualification": "A valid non-atomic browser capture is evidence only; it cannot prove a no-data-loss cutover.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {key: report[key] for key in (
        "status", "changed_streams", "drift_detected", "final_cutover_allowed",
        "merge_allowed", "posting_enabled", "failed_controls",
    )} | {"output": str(output)}
