from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from klen_clone.capture_validation import CaptureValidationError, validate_capture


SOURCE = Path("source_exports/2026-09-09-current-non-atomic")


def test_current_capture_is_valid_but_never_cutover_eligible(tmp_path):
    output = tmp_path / "validation.json"
    result = validate_capture(SOURCE, output)

    assert result["status"] == "valid_non_atomic_capture"
    assert result["changed_streams"] == ["sales", "stock_transfers"]
    assert result["drift_detected"] is True
    assert result["final_cutover_allowed"] is False
    assert result["merge_allowed"] is False
    assert result["posting_enabled"] is False
    assert result["failed_controls"] == []

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["source_capture_unchanged"] is True
    assert all(control["status"] == "pass" for control in report["controls"])


def test_capture_validation_detects_tampered_csv(tmp_path):
    capture = tmp_path / "capture"
    shutil.copytree(SOURCE, capture)
    with (capture / "sales_2026_current.csv").open("ab") as handle:
        handle.write(b"tampered\r\n")

    result = validate_capture(capture, tmp_path / "tampered.json")

    assert result["status"] == "failed"
    assert "CHECKSUM_MANIFEST" in result["failed_controls"]
    assert "CSV_SHAPE" in result["failed_controls"]


def test_capture_validation_refuses_overwrite(tmp_path):
    output = tmp_path / "validation.json"
    output.write_text("existing", encoding="utf-8")

    with pytest.raises(CaptureValidationError, match="overwrite refused"):
        validate_capture(SOURCE, output)
