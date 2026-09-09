from __future__ import annotations

import json
from pathlib import Path

import pytest

from klen_clone.activity_watermark import compare_watermarks, load_watermark
from klen_clone.capture_watermark import CaptureWatermarkError, build_capture_watermark


CAPTURE = Path("source_exports/2026-09-09-current-non-atomic")
BEFORE = Path("source_exports/2026-09-09-pre-freeze-watermark/live_activity_watermark.json")


def test_build_capture_watermark_detects_current_activity(tmp_path):
    after_path = tmp_path / "after.json"
    result = build_capture_watermark(CAPTURE, BEFORE, after_path)

    assert result["status"] == "activity_detected"
    assert result["changed_streams"] == ["sales", "stock_transfers"]
    assert result["final_capture_allowed"] is False

    after = load_watermark(after_path)
    assert after["watermarks"]["sales"]["visible_count"] == 3584
    assert after["watermarks"]["sales"]["latest_key"] == "AK2026-03623"
    assert after["watermarks"]["stock_transfers"]["latest_key"] == "ST2026/0930"
    assert after["transaction_free_window_confirmed"] is False

    comparison = compare_watermarks(BEFORE, after_path, tmp_path / "comparison.json")
    assert comparison["status"] == "activity_detected"
    assert comparison["changed_streams"] == ["sales", "stock_transfers"]
    assert comparison["final_capture_allowed"] is False


def test_capture_watermark_refuses_overwrite(tmp_path):
    output = tmp_path / "after.json"
    output.write_text(json.dumps({}), encoding="utf-8")

    with pytest.raises(CaptureWatermarkError, match="overwrite refused"):
        build_capture_watermark(CAPTURE, BEFORE, output)
