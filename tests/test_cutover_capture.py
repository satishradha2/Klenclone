from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from klen_clone.cutover_capture import CutoverCaptureError, build_cutover_rehearsal


BASELINE = Path("source_exports/2026-09-08")
DELTA = Path("source_exports/2026-09-09-ui-delta")
READINESS = Path("var/cutover_readiness/20260908T224623Z/cutover-readiness.json")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_cutover_rehearsal_packages_and_verifies_all_evidence(tmp_path):
    protected = [*BASELINE.glob("*"), *DELTA.glob("*")]
    hashes_before = {path: _hash(path) for path in protected if path.is_file()}
    output = tmp_path / "cutover-rehearsal.zip"

    result = build_cutover_rehearsal(BASELINE, DELTA, READINESS, output)

    assert result["status"] == "rehearsal_complete_non_atomic"
    assert result["evidence_files"] == 92
    assert result["archive_members"] == 93
    assert result["final_cutover_eligible"] is False
    assert result["merge_allowed"] is False
    assert result["posting_enabled"] is False
    assert {path: _hash(path) for path in hashes_before} == hashes_before

    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        manifest = json.loads(archive.read("capture-manifest.json"))
        assert manifest["evidence_file_count"] == 92
        assert manifest["transaction_free_window_confirmed"] is False
        assert manifest["uploaded_files_complete"] is False
        assert manifest["hrm_target_mode"] == "archive_only"


def test_cutover_rehearsal_refuses_overwrite(tmp_path):
    output = tmp_path / "cutover-rehearsal.zip"
    output.write_bytes(b"preserve")

    with pytest.raises(CutoverCaptureError, match="overwrite refused"):
        build_cutover_rehearsal(BASELINE, DELTA, READINESS, output)

    assert output.read_bytes() == b"preserve"
