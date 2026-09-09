from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def database_url() -> str:
    return os.getenv("KLEN_DATABASE_URL", "sqlite:///var/klen_staging.db")


def make_engine(url: str | None = None) -> Engine:
    resolved = url or database_url()
    if resolved.startswith("sqlite:///"):
        db_path = Path(resolved.removeprefix("sqlite:///"))
        db_path.parent.mkdir(parents=True, exist_ok=True)
    options = {"future": True, "pool_pre_ping": True}
    if resolved.startswith("sqlite:"):
        options["connect_args"] = {"check_same_thread": False}
    engine = create_engine(resolved, **options)
    if resolved.startswith("sqlite:"):
        @event.listens_for(engine, "connect")
        def _sqlite_foreign_keys(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine


SessionFactory = sessionmaker(expire_on_commit=False, future=True)
