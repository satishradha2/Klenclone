from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from threading import Lock


PBKDF2_ITERATIONS = 600_000


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str, salt: bytes | None = None) -> str:
    if len(password) < 12:
        raise ValueError("Target passwords must contain at least 12 characters")
    actual_salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), actual_salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${_b64(actual_salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256" or int(iterations) < PBKDF2_ITERATIONS:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), _unb64(salt), int(iterations))
        return hmac.compare_digest(actual, _unb64(expected))
    except (ValueError, TypeError):
        return False


def issue_token(principal_id: int, secret: str, ttl_seconds: int, now: int | None = None) -> str:
    issued = int(time.time() if now is None else now)
    payload = {"sub": principal_id, "iat": issued, "exp": issued + ttl_seconds, "v": 1}
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{signature}"


def verify_token(token: str, secret: str, now: int | None = None) -> dict:
    try:
        body, signature = token.split(".", 1)
        expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(signature)):
            raise ValueError("Invalid token signature")
        payload = json.loads(_unb64(body))
        current = int(time.time() if now is None else now)
        if payload.get("v") != 1 or not isinstance(payload.get("sub"), int) or current >= int(payload.get("exp", 0)):
            raise ValueError("Expired or invalid token")
        return payload
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid authentication token") from exc


@dataclass(frozen=True)
class UatSession:
    principal_id: int
    expires_at: int
    csrf_token: str


class UatSessionStore:
    """Process-local sessions for isolated synthetic UAT only, never production."""

    def __init__(self) -> None:
        self._sessions: dict[str, UatSession] = {}
        self._attempts: dict[str, list[int]] = {}
        self._lock = Lock()

    def create(self, principal_id: int, ttl_seconds: int, now: int | None = None) -> tuple[str, UatSession]:
        current = int(time.time() if now is None else now)
        token = _b64(os.urandom(32))
        session = UatSession(principal_id, current + ttl_seconds, _b64(os.urandom(24)))
        with self._lock:
            self._sessions[hashlib.sha256(token.encode()).hexdigest()] = session
        return token, session

    def get(self, token: str | None, now: int | None = None) -> UatSession | None:
        if not token:
            return None
        current = int(time.time() if now is None else now)
        key = hashlib.sha256(token.encode()).hexdigest()
        with self._lock:
            session = self._sessions.get(key)
            if session and current >= session.expires_at:
                self._sessions.pop(key, None)
                return None
            return session

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(hashlib.sha256(token.encode()).hexdigest(), None)

    def allow_attempt(self, key: str, now: int | None = None, limit: int = 5, window: int = 300) -> bool:
        current = int(time.time() if now is None else now)
        with self._lock:
            recent = [stamp for stamp in self._attempts.get(key, []) if stamp > current - window]
            if len(recent) >= limit:
                self._attempts[key] = recent
                return False
            recent.append(current)
            self._attempts[key] = recent
            return True

    def clear_attempts(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)
