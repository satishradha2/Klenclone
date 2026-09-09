from __future__ import annotations

import csv
import json
from pathlib import Path

from klen_clone.reconciliation_refresh import build_reconciliation_refresh


CAPTURE = Path("source_exports/2026-09-09-reconciliation-20260909T101320Z")
PRIOR = Path("source_exports/2026-09-09-current-non-atomic")


def _count(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return len(list(csv.DictReader(handle)))


def test_builds_reconciled_non_posting_refresh(tmp_path):
    output = tmp_path / "refresh"
    result = build_reconciliation_refresh(CAPTURE, PRIOR, output)
    assert result["status"] == "prepared_non_posting"
    assert result["products"]["new_rows"] == 5
    assert result["stock"]["reconciled"] is True
    assert result["stock"]["net_quantity"] == "29124.02"
    assert result["stock"]["negative_quantity"] == "-13.00"
    assert result["balances"]["receivables_aed"] == "62680.16"
    assert result["balances"]["payables_aed"] == "31665.00"
    assert _count(output / "products_delta.csv") == 5
    assert _count(output / "opening_stock_positive.csv") == 579
    assert _count(output / "opening_stock_negative_adjustments.csv") == 4
    status = json.loads((output / "PACKAGE_STATUS.json").read_text(encoding="utf-8"))
    assert status["posting_enabled"] is False
    assert status["promotion_allowed"] is False
    assert status["stock"]["sku_differences"] == []
