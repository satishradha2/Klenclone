"""Operator-run PostgreSQL operational schema migration and preflight."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import inspect, text

from .operational import make_operational_engine
from .operational_migrations import (
    OPERATIONAL_SCHEMA_HEAD, migrate_operational_database, verify_operational_database,
)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m klen_clone.operational_migrate")
    parser.add_argument("--database-url", default=os.getenv("ASAS_OPERATIONAL_DATABASE_URL"))
    parser.add_argument("--backup-file", type=Path,
                        help="Verified pg_dump -Fc backup; required for an existing, unmigrated database")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or ASAS_OPERATIONAL_DATABASE_URL is required")
    engine = make_operational_engine(args.database_url)
    if args.verify_only:
        print(json.dumps(verify_operational_database(engine)))
        return
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    at_head = False
    if "operational_schema_migrations" in tables:
        with engine.connect() as connection:
            at_head = connection.execute(text(
                "SELECT 1 FROM operational_schema_migrations WHERE version = :version"
            ), {"version": OPERATIONAL_SCHEMA_HEAD}).scalar_one_or_none() is not None
    if tables and not at_head:
        backup = args.backup_file
        if backup is None or not backup.is_file():
            parser.error("an existing operational database requires an accessible --backup-file")
        digest = hashlib.sha256()
        with backup.open("rb") as stream:
            if stream.read(5) != b"PGDMP":
                parser.error("--backup-file must be a PostgreSQL custom-format pg_dump archive")
            stream.seek(0)
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        backup_reference = {"path": str(backup), "sha256": digest.hexdigest()}
    else:
        backup_reference = None
    result = migrate_operational_database(engine)
    print(json.dumps({**result, "backup": backup_reference}))


if __name__ == "__main__":
    main()
