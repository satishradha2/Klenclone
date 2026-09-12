from __future__ import annotations

import hashlib
import hmac
import os
import time
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, delete, select
from sqlalchemy.orm import Mapped, mapped_column

from .auth import UatSession, _b64
from .operational import OperationalBase, utc_now


class OperationalWebSession(OperationalBase):
    __tablename__ = "operational_web_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    principal_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    expires_at: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OperationalLoginThrottle(OperationalBase):
    __tablename__ = "operational_login_throttles"

    attempt_key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_started_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    blocked_until: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class PersistentSessionStore:
    """Database-backed opaque sessions suitable for multiple ERP workers."""

    def __init__(self, session_factory, secret: str) -> None:
        if len(secret) < 32:
            raise RuntimeError("ASAS_SESSION_SECRET must contain at least 32 characters")
        self._session_factory = session_factory
        self._secret = secret.encode("utf-8")

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def _csrf(self, token: str) -> str:
        return _b64(hmac.new(self._secret, f"csrf:{token}".encode("ascii"), hashlib.sha256).digest())

    def _attempt_hash(self, key: str) -> str:
        return hmac.new(self._secret, f"attempt:{key}".encode("utf-8"), hashlib.sha256).hexdigest()

    def create(self, principal_id: int, ttl_seconds: int, now: int | None = None) -> tuple[str, UatSession]:
        current = int(time.time() if now is None else now)
        token = _b64(os.urandom(32))
        result = UatSession(principal_id, current + ttl_seconds, self._csrf(token))
        with self._session_factory() as session:
            session.execute(delete(OperationalWebSession).where(OperationalWebSession.expires_at <= current))
            session.add(OperationalWebSession(token_hash=self._token_hash(token), principal_id=principal_id,
                expires_at=result.expires_at))
            session.commit()
        return token, result

    def get(self, token: str | None, now: int | None = None) -> UatSession | None:
        if not token:
            return None
        current = int(time.time() if now is None else now)
        with self._session_factory() as session:
            row = session.get(OperationalWebSession, self._token_hash(token))
            if not row or row.revoked_at is not None:
                return None
            if current >= row.expires_at:
                row.revoked_at = utc_now()
                session.commit()
                return None
            row.last_seen_at = utc_now()
            session.commit()
            return UatSession(row.principal_id, row.expires_at, self._csrf(token))

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        with self._session_factory() as session:
            row = session.get(OperationalWebSession, self._token_hash(token))
            if row and row.revoked_at is None:
                row.revoked_at = utc_now()
                session.commit()

    def allow_attempt(self, key: str, now: int | None = None, limit: int = 5, window: int = 300) -> bool:
        current = int(time.time() if now is None else now)
        identity = self._attempt_hash(key)
        with self._session_factory() as session:
            row = session.scalar(select(OperationalLoginThrottle).where(
                OperationalLoginThrottle.attempt_key_hash == identity).with_for_update())
            if row and current < row.blocked_until:
                return False
            if not row or row.window_started_at <= current - window:
                if not row:
                    row = OperationalLoginThrottle(attempt_key_hash=identity, window_started_at=current,
                        attempt_count=1, blocked_until=0)
                    session.add(row)
                else:
                    row.window_started_at, row.attempt_count, row.blocked_until = current, 1, 0
                session.commit()
                return True
            if row.attempt_count >= limit:
                row.blocked_until = current + window
                session.commit()
                return False
            row.attempt_count += 1
            session.commit()
            return True

    def clear_attempts(self, key: str) -> None:
        with self._session_factory() as session:
            session.execute(delete(OperationalLoginThrottle).where(
                OperationalLoginThrottle.attempt_key_hash == self._attempt_hash(key)))
            session.commit()


def production_security_settings() -> dict:
    production = os.getenv("ASAS_PRODUCTION_MODE", "false").lower() == "true"
    posting_requested = os.getenv("ASAS_POSTING_ENABLED", "false").lower() == "true"
    posting_confirmed = os.getenv("ASAS_POSTING_ACTIVATION_CONFIRMED", "false").lower() == "true"
    approval_reference = os.getenv("ASAS_POSTING_APPROVAL_REFERENCE", "").strip()
    allowed_hosts = tuple(value.strip() for value in os.getenv("ASAS_ALLOWED_HOSTS", "").split(",") if value.strip())
    return {
        "production": production,
        "secure_cookies": production or os.getenv("ASAS_SECURE_COOKIES", "false").lower() == "true",
        "session_secret": os.getenv("ASAS_SESSION_SECRET", ""),
        "allowed_hosts": allowed_hosts,
        "posting_requested": posting_requested,
        "posting_confirmed": posting_confirmed,
        "posting_approval_reference": approval_reference,
    }


def validate_production_security(settings: dict, *, auth_enabled: bool, operational_url: str) -> None:
    if not settings["production"]:
        return
    if not auth_enabled:
        raise RuntimeError("Production mode requires ASAS_AUTH_ENABLED=true")
    if not operational_url.startswith("postgresql"):
        raise RuntimeError("Production mode requires a PostgreSQL operational database")
    if len(settings["session_secret"]) < 32:
        raise RuntimeError("Production mode requires ASAS_SESSION_SECRET with at least 32 characters")
    if not settings["allowed_hosts"] or "*" in settings["allowed_hosts"]:
        raise RuntimeError("Production mode requires explicit ASAS_ALLOWED_HOSTS")
    if settings["posting_requested"] and (
        not settings["posting_confirmed"] or len(settings["posting_approval_reference"]) < 8
    ):
        raise RuntimeError("Posting activation requires confirmation and an approval reference")
