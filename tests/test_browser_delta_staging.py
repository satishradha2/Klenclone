import csv
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from klen_clone.browser_delta_staging import KEY_COLUMNS, stage_browser_delta


def _write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def _capture(root: Path) -> Path:
    capture = root / "capture"
    for entity, key in KEY_COLUMNS.items():
        _write_csv(capture / "delta" / f"{entity}_delta.csv", [key], [[f"{entity}-1"]])
    _write_csv(capture / "details" / "sales_product_lines_current_business_day.csv", ["Invoice No."], [["sales-1"]])
    _write_csv(capture / "details" / "purchase_product_lines_2026-09-09.csv", ["Reference No"], [["purchases-1"]])
    _write_csv(capture / "details" / "stock_by_location.csv", ["SKU"], [["sku-1"]])
    (capture / "details" / "stock_transfer_details_ST2026_0931_0947.json").write_text(json.dumps([{"reference": "stock_transfers-1"}]), encoding="utf-8")
    (capture / "details" / "sales_return_details_CN2026_0040_0043.json").write_text(json.dumps([{"reference": "sales_returns-1"}]), encoding="utf-8")
    (capture / "details" / "purchase_return_2026_0013_form_evidence.json").write_text(json.dumps({"reference": "purchase_returns-1"}), encoding="utf-8")
    counts = {entity: 1 for entity in KEY_COLUMNS} | {"total": len(KEY_COLUMNS)}
    (capture / "delta" / "DELTA_RECONCILIATION.json").write_text(json.dumps({"new_rows": counts}), encoding="utf-8")
    paths = [p for p in capture.rglob("*") if p.is_file()]
    manifest = "\n".join(f"{hashlib.sha256(p.read_bytes()).hexdigest().upper()}  {p.relative_to(capture).as_posix()}" for p in paths)
    (capture / "SHA256SUMS.txt").write_text(manifest + "\n", encoding="utf-8")
    return capture


def test_stages_verified_delta_without_enabling_posting(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    output = tmp_path / "out" / "delta.db"
    result = stage_browser_delta(capture, output)
    assert result["status"] == "passed"
    assert result["delta_rows"] == len(KEY_COLUMNS)
    assert result["posting_enabled"] is False
    with sqlite3.connect(output) as db:
        assert db.execute("SELECT value FROM staging_metadata WHERE key='production_merge_allowed'").fetchone()[0] == "false"


def test_rejects_checksum_mismatch_and_existing_output(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    output = tmp_path / "delta.db"
    output.write_text("protected", encoding="utf-8")
    with pytest.raises(FileExistsError):
        stage_browser_delta(capture, output)
    output.unlink()
    (capture / "delta" / "sales_delta.csv").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="integrity"):
        stage_browser_delta(capture, output)
