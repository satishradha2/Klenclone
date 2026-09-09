from __future__ import annotations

from dataclasses import dataclass
import os


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RuntimeSettings:
    database_url: str
    snapshot_name: str
    auth_enabled: bool
    auth_secret: str | None
    production_mode: bool
    token_ttl_seconds: int
    uat_auth_enabled: bool = False
    cookie_secure: bool = True
    uat_review_database: str | None = None

    @classmethod
    def from_env(cls, database_url: str, snapshot_name: str) -> "RuntimeSettings":
        return cls(database_url=database_url, snapshot_name=snapshot_name,
                   auth_enabled=env_bool("KLEN_AUTH_ENABLED"), auth_secret=os.getenv("KLEN_AUTH_SECRET"),
                   production_mode=env_bool("KLEN_PRODUCTION_MODE"),
                   token_ttl_seconds=int(os.getenv("KLEN_TOKEN_TTL_SECONDS", "1800")),
                   uat_auth_enabled=env_bool("KLEN_UAT_AUTH_ENABLED"),
                   cookie_secure=env_bool("KLEN_COOKIE_SECURE", True),
                   uat_review_database=os.getenv("KLEN_UAT_REVIEW_DATABASE"))

    def validate(self) -> None:
        if self.token_ttl_seconds < 300 or self.token_ttl_seconds > 43200:
            raise ValueError("KLEN_TOKEN_TTL_SECONDS must be between 300 and 43200")
        if self.auth_enabled and (not self.auth_secret or len(self.auth_secret) < 32):
            raise ValueError("Authentication requires KLEN_AUTH_SECRET with at least 32 characters")
        if self.uat_auth_enabled and not self.auth_enabled:
            raise ValueError("UAT authentication requires KLEN_AUTH_ENABLED=true")
        if self.uat_auth_enabled and self.production_mode:
            raise ValueError("The synthetic UAT login flow cannot run in production mode")
        if self.uat_review_database and not self.uat_auth_enabled:
            raise ValueError("The UAT review sidecar requires KLEN_UAT_AUTH_ENABLED=true")
        if self.production_mode:
            if self.database_url.startswith("sqlite:"):
                raise ValueError("Production mode requires PostgreSQL")
            if not self.auth_enabled:
                raise ValueError("Production mode requires authentication")
