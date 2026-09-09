from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class CutoverCaptureError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _source_files(root: Path, prefix: str) -> list[tuple[Path, str]]:
    return [
        (path, f"evidence/{prefix}/{path.relative_to(root).as_posix()}")
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    ]


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    return info


def build_cutover_rehearsal(
    baseline_dir: Path,
    delta_dir: Path,
    readiness_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    baseline = baseline_dir.resolve()
    delta = delta_dir.resolve()
    readiness = readiness_path.resolve()
    output = output_path.resolve()

    if not baseline.is_dir() or not delta.is_dir():
        raise CutoverCaptureError("Baseline and delta evidence directories are required")
    if not readiness.is_file():
        raise CutoverCaptureError(f"Readiness manifest not found: {readiness}")
    if output.exists():
        raise CutoverCaptureError(f"Output already exists; overwrite refused: {output}")
    if output.suffix.lower() != ".zip":
        raise CutoverCaptureError("Cutover rehearsal output must be a new ZIP file")

    readiness_doc = json.loads(readiness.read_text(encoding="utf-8"))
    if (
        readiness_doc.get("mode") != "read_only_cutover_preflight"
        or readiness_doc.get("evidence_controls_passed") is not True
        or readiness_doc.get("merge_allowed") is not False
        or readiness_doc.get("posting_enabled") is not False
    ):
        raise CutoverCaptureError("Readiness manifest does not prove a safe evidence state")

    sources = _source_files(baseline, "baseline") + _source_files(delta, "delta")
    hashes_before = {archive_name: _sha256(path) for path, archive_name in sources}
    readiness_hash_before = _sha256(readiness)
    manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "capture_type": "non_atomic_cutover_rehearsal",
        "final_cutover_eligible": False,
        "transaction_free_window_confirmed": False,
        "uploaded_files_complete": False,
        "source_mutation": False,
        "clone_mutation": False,
        "posting_enabled": False,
        "merge_allowed": False,
        "hrm_target_mode": "archive_only",
        "readiness_manifest": {"path": str(readiness), "sha256": readiness_hash_before},
        "evidence_file_count": len(sources),
        "evidence_total_bytes": sum(path.stat().st_size for path, _ in sources),
        "files": [
            {
                "archive_path": archive_name,
                "size_bytes": path.stat().st_size,
                "sha256": hashes_before[archive_name],
            }
            for path, archive_name in sources
        ],
        "limitations": [
            "This package rehearses the final capture procedure using already preserved evidence.",
            "It is not an atomic source snapshot and cannot authorize a real merge.",
            "Uploaded files unavailable through the browser are not represented as complete.",
        ],
    }
    manifest_bytes = (json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    if temporary.exists():
        raise CutoverCaptureError(f"Temporary output already exists; cleanup required: {temporary}")
    try:
        with zipfile.ZipFile(temporary, "x") as archive:
            archive.writestr(_zip_info("capture-manifest.json"), manifest_bytes)
            for path, archive_name in sources:
                archive.writestr(_zip_info(archive_name), path.read_bytes())

        with zipfile.ZipFile(temporary, "r") as archive:
            if archive.testzip() is not None:
                raise CutoverCaptureError("ZIP integrity validation failed")
            names = archive.namelist()
            expected_names = ["capture-manifest.json", *hashes_before]
            if names != expected_names:
                raise CutoverCaptureError("ZIP member inventory differs from the planned package")
            for archive_name, expected_hash in hashes_before.items():
                if _sha256_bytes(archive.read(archive_name)) != expected_hash:
                    raise CutoverCaptureError(f"Archived evidence checksum mismatch: {archive_name}")

        hashes_after = {archive_name: _sha256(path) for path, archive_name in sources}
        if hashes_after != hashes_before or _sha256(readiness) != readiness_hash_before:
            raise CutoverCaptureError("Source evidence changed during package creation")
        temporary.replace(output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    return {
        "status": "rehearsal_complete_non_atomic",
        "output": str(output),
        "sha256": _sha256(output),
        "evidence_files": len(sources),
        "archive_members": len(sources) + 1,
        "evidence_total_bytes": manifest["evidence_total_bytes"],
        "final_cutover_eligible": False,
        "merge_allowed": False,
        "posting_enabled": False,
        "source_evidence_unchanged": True,
    }
