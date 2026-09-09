from pathlib import Path
import shutil
import sqlite3

import pytest

from klen_clone.delta_dry_run import DeltaEvidenceError, run_delta_dry_run


SOURCE = Path("source_exports/2026-09-09-ui-delta")


def test_delta_dry_run_builds_isolated_validated_database(tmp_path):
    output = tmp_path / "delta_validation.db"
    result = run_delta_dry_run(SOURCE, output)

    assert result["status"] == "passed"
    assert result["failed"] == 0
    assert result["rows"] == {
        "customers": 1,
        "products": 1,
        "stock_balances": 2,
        "purchases": 1,
        "sales": 15,
        "sale_lines": 35,
        "sale_detail_payments": 8,
        "sales_payments": 12,
        "output_vat": 12,
        "cash_flow": 12,
    }

    with sqlite3.connect(output) as connection:
        assert connection.execute("SELECT value FROM dry_run_meta WHERE key='posting_enabled'").fetchone() == ("false",)
        assert connection.execute("SELECT value FROM dry_run_meta WHERE key='promotion_allowed'").fetchone() == ("false",)
        assert connection.execute("SELECT COUNT(*) FROM validation_result WHERE status='fail'").fetchone() == (0,)
        assert connection.execute("SELECT SUM(CAST(credit AS NUMERIC)) FROM delta_cash_flow").fetchone() == (934.5,)
        assert connection.execute("SELECT location, available_quantity FROM delta_stock_balance ORDER BY location").fetchall() == [
            ("Asas General Trading LLC", 0),
            ("DXB", 1),
        ]


def test_delta_dry_run_refuses_existing_output(tmp_path):
    output = tmp_path / "delta_validation.db"
    output.write_bytes(b"preserve me")

    with pytest.raises(DeltaEvidenceError, match="overwrite refused"):
        run_delta_dry_run(SOURCE, output)

    assert output.read_bytes() == b"preserve me"


def test_delta_dry_run_rejects_tampered_evidence(tmp_path):
    source = tmp_path / "evidence"
    shutil.copytree(SOURCE, source)
    with (source / "sales_details.json").open("a", encoding="utf-8") as handle:
        handle.write(" ")

    with pytest.raises(DeltaEvidenceError, match="Checksum mismatch"):
        run_delta_dry_run(source, tmp_path / "delta_validation.db")
