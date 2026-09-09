import pytest

from klen_clone.config import RuntimeSettings


def test_production_requires_postgres_auth_and_secret():
    with pytest.raises(ValueError):
        RuntimeSettings("sqlite:///x.db", "snapshot", False, None, True, 1800).validate()
    RuntimeSettings("postgresql+psycopg://db/app", "snapshot", True, "x" * 32, True, 1800).validate()


def test_synthetic_uat_auth_is_explicit_and_never_production():
    with pytest.raises(ValueError):
        RuntimeSettings("sqlite:///x.db", "snapshot", False, None, False, 1800,
                        uat_auth_enabled=True, cookie_secure=False).validate()
    with pytest.raises(ValueError):
        RuntimeSettings("postgresql+psycopg://db/app", "snapshot", True, "x" * 32, True, 1800,
                        uat_auth_enabled=True, cookie_secure=True).validate()
