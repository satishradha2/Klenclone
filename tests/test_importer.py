import csv
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from klen_clone.db import Base
from klen_clone.importer import EvidenceChangedError, import_evidence
from klen_clone.models import RawFileManifest, RawRecord


def write_csv(path: Path, amount: str = "10.00") -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["Invoice No.", "Amount"])
        writer.writeheader()
        writer.writerow({"Invoice No.": "AK2026-0001", "Amount": amount})
        writer.writerow({"Invoice No.": "Total:", "Amount": amount})


def test_import_is_idempotent_and_rejects_changed_evidence(tmp_path):
    source = tmp_path / "evidence"
    source.mkdir()
    path = source / "sales_2026.csv"
    write_csv(path)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        first = import_evidence(session, source, "snapshot-1", "https://example.test")
        second = import_evidence(session, source, "snapshot-1", "https://example.test")
        assert first.files_imported == 1 and first.records_imported == 2
        assert second.files_skipped == 1 and second.records_imported == 0
        assert session.scalar(select(func.count(RawFileManifest.id))) == 1
        assert session.scalar(select(func.count(RawRecord.id))) == 2

    write_csv(path, "11.00")
    with Session() as session, pytest.raises(EvidenceChangedError):
        import_evidence(session, source, "snapshot-1", "https://example.test")
