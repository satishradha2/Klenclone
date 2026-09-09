from pathlib import Path
import hashlib
import sqlite3

import pytest

from klen_clone.delta_merge_simulation import MergeSimulationError, simulate_delta_merge


CLONE = Path("var/klen_staging.db")
DELTA = Path("var/delta_dry_runs/20260908T224316Z/delta_validation.db")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_merge_simulation_builds_plan_without_business_table_writes(tmp_path):
    clone_before = _hash(CLONE)
    delta_before = _hash(DELTA)
    output = tmp_path / "merge_simulation.db"

    result = simulate_delta_merge(CLONE, DELTA, output)

    assert result["status"] == "passed"
    assert result["merge_allowed"] is False
    assert result["actions"] == {"insert": 82, "reuse_existing": 13, "update": 0, "conflict": 0}
    assert result["plan_rows"] == 95
    assert _hash(CLONE) == clone_before
    assert _hash(DELTA) == delta_before

    with sqlite3.connect(output) as connection:
        assert connection.execute("SELECT COUNT(*) FROM delta_merge_plan").fetchone() == (95,)
        assert connection.execute("SELECT COUNT(*) FROM delta_merge_plan WHERE action='conflict'").fetchone() == (0,)
        assert connection.execute("SELECT status FROM delta_merge_control WHERE code='STOCK_LOCATION_RECONCILED'").fetchone() == ("pass",)
        assert connection.execute("SELECT merge_allowed, posting_enabled, source_business_tables_changed FROM delta_merge_run").fetchone() == (0, 0, 0)
        assert connection.execute("SELECT COUNT(*) FROM delta_merge_projection WHERE actual_after_simulation_count <> before_count").fetchone() == (0,)


def test_merge_simulation_refuses_existing_output(tmp_path):
    output = tmp_path / "merge_simulation.db"
    output.write_bytes(b"preserve")

    with pytest.raises(MergeSimulationError, match="overwrite refused"):
        simulate_delta_merge(CLONE, DELTA, output)

    assert output.read_bytes() == b"preserve"
