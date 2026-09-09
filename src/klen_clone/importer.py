from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import RawFileManifest, RawRecord, SourceSnapshot
from .parsers import infer_entity, media_type, presentation_row, read_records, sha256_file, source_keys


class EvidenceChangedError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImportResult:
    files_imported: int = 0
    files_skipped: int = 0
    records_imported: int = 0


SUPPORTED_SUFFIXES = {".csv", ".json", ".xlsx"}


def get_or_create_snapshot(session: Session, name: str, source_url: str) -> SourceSnapshot:
    snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == name))
    if snapshot:
        return snapshot
    snapshot = SourceSnapshot(
        name=name,
        source_url=source_url,
        is_atomic=False,
        notes="Browser-only, non-atomic evidence. Final cutover requires a transaction freeze or server backup.",
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def import_evidence(session: Session, root: Path, snapshot_name: str, source_url: str) -> ImportResult:
    root = root.resolve()
    snapshot = get_or_create_snapshot(session, snapshot_name, source_url)
    imported = skipped = records_total = 0

    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES):
        relative = path.relative_to(root).as_posix()
        digest = sha256_file(path)
        existing = session.scalar(
            select(RawFileManifest).where(
                RawFileManifest.snapshot_id == snapshot.id,
                RawFileManifest.relative_path == relative,
            )
        )
        if existing:
            if existing.sha256 != digest or existing.byte_length != path.stat().st_size:
                raise EvidenceChangedError(f"Evidence changed after import: {relative}")
            skipped += 1
            continue

        records = list(read_records(path))
        manifest = RawFileManifest(
            snapshot_id=snapshot.id,
            relative_path=relative,
            entity_type=infer_entity(path),
            sha256=digest,
            byte_length=path.stat().st_size,
            media_type=media_type(path),
            source_record_count=len(records),
        )
        session.add(manifest)
        session.flush()
        for ordinal, record in enumerate(records, start=1):
            source_id, document = source_keys(record)
            if isinstance(record, (dict, list)):
                payload, payload_text = record, None
            else:
                payload, payload_text = None, record
            session.add(RawRecord(
                manifest_id=manifest.id,
                ordinal=ordinal,
                source_record_id=source_id,
                source_document_number=document,
                is_presentation_row=presentation_row(record),
                payload=payload,
                payload_text=payload_text,
            ))
        imported += 1
        records_total += len(records)
        session.commit()

    return ImportResult(imported, skipped, records_total)
