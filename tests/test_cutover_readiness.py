from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from klen_clone.cutover_readiness import CutoverReadinessError, build_cutover_readiness


BASELINE = Path("source_exports/2026-09-08")
DELTA = Path("source_exports/2026-09-09-ui-delta")
CLONE = Path("var/klen_staging.db")
DELTA_DB = Path("var/delta_dry_runs/20260908T224316Z/delta_validation.db")
SIMULATION_DB = Path("var/delta_merge_simulations/20260908T224332Z/merge_simulation.db")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_cutover_readiness_is_read_only_and_fails_closed(tmp_path):
    hashes_before = {path: _hash(path) for path in (CLONE, DELTA_DB, SIMULATION_DB)}
    output = tmp_path / "cutover-readiness.json"

    result = build_cutover_readiness(BASELINE, DELTA, CLONE, DELTA_DB, SIMULATION_DB, output)

    assert result["status"] == "blocked_pending_frozen_capture"
    assert result["merge_allowed"] is False
    assert result["posting_enabled"] is False
    assert result["evidence_controls_passed"] is True
    assert result["failed_gates"] == 0
    assert result["blocked_gates"] == 4
    assert {path: _hash(path) for path in hashes_before} == hashes_before

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["source_mutation"] is False
    assert report["clone_mutation"] is False
    assert report["merge_allowed"] is False
    hrm = next(item for item in report["cutover_export_families"] if item["family"] == "hrm")
    assert hrm["target_operational"] is True
    assert hrm["payroll_included"] is False
    assert next(item for item in report["cutover_export_families"] if item["family"] == "uploaded_files")["browser_exportable"] is False


def test_cutover_readiness_refuses_overwrite(tmp_path):
    output = tmp_path / "cutover-readiness.json"
    output.write_text("preserve", encoding="utf-8")

    with pytest.raises(CutoverReadinessError, match="overwrite refused"):
        build_cutover_readiness(BASELINE, DELTA, CLONE, DELTA_DB, SIMULATION_DB, output)

    assert output.read_text(encoding="utf-8") == "preserve"
