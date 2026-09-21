import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from klen_clone.operational import OperationalSchemaMigration, initialize_operational_database, make_operational_engine, operational_session_factory
from klen_clone.security_runtime import (
    OperationalLoginThrottle,
    OperationalWebSession,
    PersistentSessionStore,
    validate_production_security,
)


def test_persistent_sessions_survive_store_instances_and_revoke(tmp_path):
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'security.db'}")
    initialize_operational_database(engine)
    factory = operational_session_factory(engine)
    secret = "production-session-secret-with-more-than-32-characters"
    first = PersistentSessionStore(factory, secret)
    token, issued = first.create(42, ttl_seconds=1800, now=100)
    second = PersistentSessionStore(factory, secret)
    restored = second.get(token, now=101)
    assert restored and restored.principal_id == 42
    assert restored.csrf_token == issued.csrf_token
    second.revoke(token)
    assert first.get(token, now=102) is None
    with Session(engine) as session:
        assert session.scalar(select(func.count(OperationalWebSession.token_hash))) == 1
        assert session.get(OperationalSchemaMigration, "0049") is not None


def test_persistent_login_throttle_is_shared_and_clearable(tmp_path):
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'throttle.db'}")
    initialize_operational_database(engine)
    store = PersistentSessionStore(operational_session_factory(engine), "x" * 40)
    assert [store.allow_attempt("client:user", now=100, limit=2, window=300) for _ in range(3)] == [True, True, False]
    store.clear_attempts("client:user")
    assert store.allow_attempt("client:user", now=101, limit=2, window=300) is True
    with Session(engine) as session:
        assert session.scalar(select(func.count(OperationalLoginThrottle.attempt_key_hash))) == 1


def test_production_configuration_fails_closed():
    base = {"production": True, "session_secret": "s" * 40, "allowed_hosts": ("erp.example.com",),
            "posting_requested": False, "posting_confirmed": False, "posting_approval_reference": ""}
    validate_production_security(base, auth_enabled=True,
                                 operational_url="postgresql+psycopg://user:password@db/erp")
    with pytest.raises(RuntimeError, match="Posting activation"):
        validate_production_security(base | {"posting_requested": True}, auth_enabled=True,
                                     operational_url="postgresql+psycopg://user:password@db/erp")


@pytest.mark.parametrize(("settings", "auth_enabled", "url", "message"), [
    ({"production": True, "session_secret": "s" * 40, "allowed_hosts": ("erp.example.com",),
      "posting_requested": False, "posting_confirmed": False, "posting_approval_reference": ""},
     False, "postgresql+psycopg://user:password@db/erp", "ASAS_AUTH_ENABLED"),
    ({"production": True, "session_secret": "short", "allowed_hosts": ("erp.example.com",),
      "posting_requested": False, "posting_confirmed": False, "posting_approval_reference": ""},
     True, "postgresql+psycopg://user:password@db/erp", "SESSION_SECRET"),
    ({"production": True, "session_secret": "s" * 40, "allowed_hosts": ("*",),
      "posting_requested": False, "posting_confirmed": False, "posting_approval_reference": ""},
     True, "postgresql+psycopg://user:password@db/erp", "ALLOWED_HOSTS"),
    ({"production": True, "session_secret": "s" * 40, "allowed_hosts": ("erp.example.com",),
      "posting_requested": False, "posting_confirmed": False, "posting_approval_reference": ""},
     True, "sqlite:///erp.db", "PostgreSQL"),
])
def test_each_mandatory_production_control_is_enforced(settings, auth_enabled, url, message):
    with pytest.raises(RuntimeError, match=message):
        validate_production_security(settings, auth_enabled=auth_enabled, operational_url=url)
