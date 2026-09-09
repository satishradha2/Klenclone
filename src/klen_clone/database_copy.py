from __future__ import annotations

import base64
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import Connection, Engine, make_url

from .db import Base, make_engine


def _normalized(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float):
        return format(Decimal(str(value)), "f")
    if isinstance(value, datetime):
        actual = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return actual.isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes):
        return {"base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (dict, list)):
        return value
    return str(value)


def _row_bytes(table, row) -> bytes:
    payload = {column.name: _normalized(row[column.name]) for column in table.columns}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"


def _table_digest(connection: Connection, table, batch_size: int = 1000) -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    order = list(table.primary_key.columns) or list(table.columns)
    result = connection.execute(select(table).order_by(*order)).mappings()
    while rows := result.fetchmany(batch_size):
        for row in rows:
            digest.update(_row_bytes(table, row))
            count += 1
    return count, digest.hexdigest()


def _validate_urls(source_url: str, target_url: str) -> None:
    source = make_url(source_url)
    target = make_url(target_url)
    if not source.drivername.startswith("sqlite"):
        raise ValueError("Source must be an explicitly selected SQLite clone database")
    if not target.drivername.startswith("postgresql"):
        raise ValueError("Target must be an isolated PostgreSQL database")
    if source.database in {None, "", ":memory:"}:
        raise ValueError("Source SQLite database must be a persistent file")
    if not Path(source.database).is_file():
        raise ValueError(f"Source SQLite database does not exist: {source.database}")


def _verify_schema(source: Engine, target: Engine) -> None:
    expected = set(Base.metadata.tables)
    source_tables = set(inspect(source).get_table_names())
    target_tables = set(inspect(target).get_table_names())
    missing_source = sorted(expected - source_tables)
    missing_target = sorted(expected - target_tables)
    if missing_source:
        raise ValueError(f"Source schema is incomplete: {missing_source}")
    if missing_target:
        raise ValueError(f"Target schema is incomplete: {missing_target}")


def copy_sqlite_to_postgres(source_url: str, target_url: str, batch_size: int = 1000) -> dict:
    if batch_size < 100 or batch_size > 10_000:
        raise ValueError("batch_size must be between 100 and 10000")
    _validate_urls(source_url, target_url)
    source_engine = make_engine(source_url)
    target_engine = make_engine(target_url)
    _verify_schema(source_engine, target_engine)
    tables = list(Base.metadata.sorted_tables)
    report: list[dict] = []
    total_rows = 0
    overall = hashlib.sha256()

    with source_engine.connect() as source, target_engine.begin() as target:
        source.execute(text("PRAGMA query_only = ON"))
        target.execute(text("SELECT pg_advisory_xact_lock(hashtext('klen_clone_sqlite_to_postgres_copy'))"))
        occupied = []
        for table in tables:
            count = target.scalar(select(func.count()).select_from(table)) or 0
            if count:
                occupied.append(f"{table.name}={count}")
        if occupied:
            raise ValueError("Target must be empty before copy: " + ", ".join(occupied))

        for table in tables:
            source_hash = hashlib.sha256()
            row_count = 0
            order = list(table.primary_key.columns) or list(table.columns)
            result = source.execute(select(table).order_by(*order)).mappings()
            while rows := result.fetchmany(batch_size):
                payload = [dict(row) for row in rows]
                for row in payload:
                    source_hash.update(_row_bytes(table, row))
                target.execute(table.insert(), payload)
                row_count += len(payload)

            target_count, target_hash = _table_digest(target, table, batch_size)
            source_digest = source_hash.hexdigest()
            if target_count != row_count or target_hash != source_digest:
                raise RuntimeError(
                    f"Copy verification failed for {table.name}: source={row_count}/{source_digest}, "
                    f"target={target_count}/{target_hash}"
                )
            report.append({"table": table.name, "rows": row_count, "sha256": source_digest})
            total_rows += row_count
            overall.update(f"{table.name}:{row_count}:{source_digest}\n".encode())

        for table in tables:
            primary_keys = list(table.primary_key.columns)
            if len(primary_keys) != 1:
                continue
            column = primary_keys[0]
            sequence = target.scalar(text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
                                     {"table_name": table.name, "column_name": column.name})
            if not sequence:
                continue
            maximum = target.scalar(select(func.max(column)))
            if maximum is not None:
                target.execute(text("SELECT setval(CAST(:sequence AS regclass), :value, true)"),
                               {"sequence": sequence, "value": maximum})

    return {
        "status": "verified",
        "source_mode": "sqlite_query_only",
        "target": "postgresql",
        "tables": len(report),
        "rows": total_rows,
        "sha256": overall.hexdigest(),
        "table_results": report,
    }
