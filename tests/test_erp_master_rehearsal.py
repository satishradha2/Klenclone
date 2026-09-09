from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from klen_clone.erp_master_rehearsal import ErpMasterRehearsalError, build_erp_master_package


CAPTURE = Path("source_exports/2026-09-09-current-non-atomic")


def test_builds_checksum_bound_non_posting_master_package(tmp_path):
    output = tmp_path / "package"
    result = build_erp_master_package(CAPTURE, output)

    assert result["status"] == "prepared_non_posting"
    assert result["ready_master_rows"] == {"products": 465, "customers": 794, "suppliers": 88}
    assert result["posting_enabled"] is False
    assert result["promotion_allowed"] is False

    status = json.loads((output / "PACKAGE_STATUS.json").read_text(encoding="utf-8"))
    assert status["source_mutation"] is False
    assert status["preserved_clone_mutation"] is False
    assert status["target_staging_mutation"] is False
    assert status["later_delta_supported"] is True
    assert status["deferred"]["opening_stock"]

    expected = {"products.csv": 465, "customers.csv": 794, "suppliers.csv": 88}
    for name, count in expected.items():
        with (output / name).open("r", encoding="utf-8", newline="") as handle:
            assert len(list(csv.DictReader(handle))) == count

    manifest = {}
    for line in (output / "SHA256SUMS.txt").read_text(encoding="utf-8-sig").splitlines():
        digest, name = line.split("  ", 1)
        manifest[name] = digest
    assert set(manifest) == {"products.csv", "customers.csv", "suppliers.csv", "exceptions.json", "PACKAGE_STATUS.json"}
    for name, digest in manifest.items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest().upper() == digest


def test_rehearsal_package_refuses_overwrite(tmp_path):
    output = tmp_path / "package"
    output.mkdir()

    with pytest.raises(ErpMasterRehearsalError, match="overwrite refused"):
        build_erp_master_package(CAPTURE, output)
