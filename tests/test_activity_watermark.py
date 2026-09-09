from __future__ import annotations

import json
from pathlib import Path

from klen_clone.activity_watermark import compare_watermarks, load_watermark


SOURCE = Path("source_exports/2026-09-09-pre-freeze-watermark/live_activity_watermark.json")


def test_pre_freeze_watermark_is_valid_but_cannot_authorize_capture(tmp_path):
    watermark = load_watermark(SOURCE)
    assert watermark["phase"] == "pre_freeze"
    assert watermark["transaction_free_window_confirmed"] is False
    assert watermark["summary"]["reliable_streams"] == 10

    output = tmp_path / "comparison.json"
    result = compare_watermarks(SOURCE, SOURCE, output)
    assert result["status"] == "stable_watermarks"
    assert result["changed_streams"] == []
    assert result["transaction_free_window_confirmed"] is False
    assert result["final_capture_allowed"] is False
    assert result["merge_allowed"] is False


def test_watermark_comparison_detects_activity(tmp_path):
    after = json.loads(SOURCE.read_text(encoding="utf-8"))
    after["watermarks"]["sales"]["visible_count"] += 1
    after["watermarks"]["sales"]["latest_key"] = "AK2026-03622"
    after_path = tmp_path / "after.json"
    after_path.write_text(json.dumps(after), encoding="utf-8")

    result = compare_watermarks(SOURCE, after_path, tmp_path / "comparison.json")
    assert result["status"] == "activity_detected"
    assert result["changed_streams"] == ["sales"]
    assert result["final_capture_allowed"] is False
