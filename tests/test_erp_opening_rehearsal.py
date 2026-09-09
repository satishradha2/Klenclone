from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from klen_clone.erp_opening_rehearsal import ErpOpeningRehearsalError, build_erp_opening_package


CAPTURE = Path("source_exports/2026-09-09-current-non-atomic")
BASELINE = Path("source_exports/2026-09-08")


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_builds_non_posting_opening_package_with_reconciliations(tmp_path):
    output = tmp_path / "opening"
    result = build_erp_opening_package(CAPTURE, BASELINE, output)

    assert result["status"] == "prepared_non_posting"
    assert result["posting_enabled"] is False
    assert result["promotion_allowed"] is False
    assert result["receivables"] == {"rows": 199, "amount_aed": "63159.66"}
    assert result["payables"] == {"rows": 53, "amount_aed": "30737.85"}

    status = json.loads((output / "PACKAGE_STATUS.json").read_text(encoding="utf-8"))
    assert status["header_reconciliation"]["receivables_variance_aed"] == "-906.59"
    assert status["header_reconciliation"]["payables_variance_aed"] == "-1449.56"
    assert status["stock"]["baseline_total_quantity"] == "29252.02"
    assert status["stock"]["current_total_quantity"] == "29094.02"
    assert status["stock"]["baseline_to_current_delta"] == "-158.00"
    assert status["stock"]["provisional_to_current_delta_required"] == "-171.00"
    assert status["stock"]["mismatched_skus"] == 26
    assert all(row["sku"] != "Total:" for row in _rows(output / "opening_stock_provisional.csv"))

    manifest = {}
    for line in (output / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        manifest[name] = digest
    assert len(manifest) == 7
    for name, digest in manifest.items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest().upper() == digest


def test_refuses_overwrite(tmp_path):
    output = tmp_path / "opening"
    output.mkdir()
    with pytest.raises(ErpOpeningRehearsalError, match="overwrite refused"):
        build_erp_opening_package(CAPTURE, BASELINE, output)
