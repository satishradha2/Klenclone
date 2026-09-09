from datetime import datetime, timezone
from decimal import Decimal

from klen_clone.database_copy import _normalized


def test_copy_digest_normalization_is_cross_database_stable():
    assert _normalized(Decimal("10.500000")) == "10.500000"
    assert _normalized(10.5) == "10.5"
    assert _normalized(datetime(2026, 9, 9, 1, 2, 3)) == "2026-09-09T01:02:03.000000+00:00"
    assert _normalized(datetime(2026, 9, 9, 5, 2, 3, tzinfo=timezone.utc)) == "2026-09-09T05:02:03.000000+00:00"


def test_copy_rejects_missing_source_and_non_postgres_target(tmp_path):
    from klen_clone.database_copy import _validate_urls

    missing = tmp_path / "missing.db"
    try:
        _validate_urls(f"sqlite:///{missing}", "postgresql+psycopg://example.invalid/db")
    except ValueError as exc:
        assert "does not exist" in str(exc)
    else:
        raise AssertionError("missing SQLite source was accepted")

    existing = tmp_path / "existing.db"
    existing.touch()
    try:
        _validate_urls(f"sqlite:///{existing}", f"sqlite:///{tmp_path / 'target.db'}")
    except ValueError as exc:
        assert "isolated PostgreSQL" in str(exc)
    else:
        raise AssertionError("non-PostgreSQL target was accepted")
