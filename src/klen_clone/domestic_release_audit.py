"""Read-only, repeatable domestic migration-discrepancy export."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import make_engine
from .models import (
    ErpMigrationExceptionQueue, RawFileManifest, ReconciliationException, SourceSnapshot,
    StgDocumentLine, StgInventoryMovement, StgPayment, StgSaleLine,
)


FINANCE_CODES = {
    "FINANCIAL_DOCUMENT_REVIEW", "FINANCIAL_ALLOCATION_RESIDUAL", "SETTLEMENT_RESIDUAL",
    "PAYMENT_WITHOUT_CASH_FLOW", "JOURNAL_BLUEPRINT_REVIEW", "ACCOUNTING_CONTROL_VARIANCE",
    "CASH_FLOW_PAYMENT_UNMATCHED", "TAX_EVIDENCE_UNMATCHED", "TRIAL_BALANCE_LABEL_MISSING",
}
INVENTORY_CODES = {
    "INVENTORY_MOVEMENT_READINESS", "OPENING_STOCK_BLOCKED", "UOM_REGISTRY_CONFLICT",
    "UOM_CONVERSION_UNRESOLVED", "NEGATIVE_STOCK", "MISSING_STOCK_LOCATION",
}


def disposition(code: str, evidence: dict) -> tuple[str, str, str]:
    area = ("Finance and accounting" if code in FINANCE_CODES else
            "Inventory and UOM" if code in INVENTORY_CODES else
            "Transaction/master relationships")
    if code == "INVENTORY_MOVEMENT_READINESS":
        if evidence.get("migration_status") == "review_required_source_header":
            return area, "Inventory owner", "Recapture or identify the source document header; keep movement blocked"
        if evidence.get("migration_status") == "review_required_uom_conversion":
            return area, "Product/UOM owner", "Approve a product-specific factor-to-base snapshot; keep movement blocked"
    if code in {"UOM_REGISTRY_CONFLICT", "UOM_CONVERSION_UNRESOLVED"}:
        return area, "Product/UOM owner", "Approve product-specific unit definitions and conversions; no global factor guess"
    if code == "TRANSACTION_LINE_RELATIONSHIP":
        if evidence.get("document_id") is None:
            return area, "Sales/procurement owner", "Recapture or identify the source header before linking this line"
        if evidence.get("product_id") is None:
            return area, "Product master owner", "Resolve product identity with source evidence; do not match on name alone"
    if code in {"AMBIGUOUS_RELATIONSHIP", "PAYMENT_PARENT_RELATIONSHIP", "DUPLICATE_DOCUMENT_NUMBER",
                "DETAIL_HEADER_DRIFT", "MASTER_SNAPSHOT_DRIFT"}:
        return area, "Sales/procurement owner", "Approve the source-to-target relationship or document-number decision"
    if code in FINANCE_CODES:
        return area, "Finance owner", "Reconcile source document, cash and ledger evidence; approve target-side treatment"
    if code in INVENTORY_CODES:
        return area, "Inventory owner", "Reconcile source stock and location evidence; approve target-side treatment"
    return area, "Migration owner", "Inspect source evidence and record an approved target-side decision"


def source_reference(session: Session, snapshot_id: int, item: ErpMigrationExceptionQueue) -> dict:
    """Expose identifiers for review without inferring or repairing a relationship."""
    model_by_kind = {
        "document_line": StgDocumentLine,
        "inventory_movement": StgInventoryMovement,
        "payment": StgPayment,
        "sale_line": StgSaleLine,
        "reconciliation_exception": ReconciliationException,
    }
    model = model_by_kind.get(item.source_kind)
    source = session.get(model, item.source_id) if model is not None else None
    evidence = item.evidence or {}
    if source is None or source.snapshot_id != snapshot_id:
        return {"source_reference": evidence.get("document_no") or evidence.get("reference_no")
                or evidence.get("source_key") or "", "raw_record_id": "",
                "source_sku": "", "source_uom": ""}
    reference = (
        getattr(source, "document_no", None)
        or getattr(source, "parent_document_no", None)
        or getattr(source, "reference_no", None)
        or getattr(source, "source_key", None)
        or evidence.get("document_no")
        or ""
    )
    return {
        "source_reference": reference,
        "raw_record_id": getattr(source, "raw_record_id", None) or "",
        "source_sku": getattr(source, "sku", None) or "",
        "source_uom": (getattr(source, "source_uom", None)
                       or getattr(source, "unit", None) or ""),
    }


def build_audit(session: Session, snapshot_name: str) -> tuple[dict, list[dict]]:
    snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == snapshot_name))
    if snapshot is None:
        raise ValueError(f"Unknown snapshot: {snapshot_name}")
    manifests = session.scalars(select(RawFileManifest).where(
        RawFileManifest.snapshot_id == snapshot.id).order_by(RawFileManifest.relative_path)).all()
    manifest_lines = [f"{row.relative_path}|{row.sha256}|{row.source_record_count}" for row in manifests]
    manifest_digest = hashlib.sha256("\n".join(manifest_lines).encode("utf-8")).hexdigest()
    blocked = session.scalars(select(ErpMigrationExceptionQueue).where(
        ErpMigrationExceptionQueue.snapshot_id == snapshot.id,
        ErpMigrationExceptionQueue.activation_blocked.is_(True),
    ).order_by(ErpMigrationExceptionQueue.exception_code,
               ErpMigrationExceptionQueue.source_kind,
               ErpMigrationExceptionQueue.source_id)).all()
    rows = []
    by_area: Counter[str] = Counter()
    by_code: Counter[str] = Counter()
    by_action: Counter[str] = Counter()
    for item in blocked:
        evidence = item.evidence or {}
        area, owner, action = disposition(item.exception_code, evidence)
        rows.append({
            "queue_id": item.id, "area": area, "code": item.exception_code,
            "severity": item.severity, "source_kind": item.source_kind,
            "source_id": item.source_id, "queue_status": item.queue_status,
            **source_reference(session, snapshot.id, item),
            "owner_role": owner, "required_action": action,
            "evidence": json.dumps(evidence, sort_keys=True, ensure_ascii=False),
        })
        by_area[area] += 1
        by_code[item.exception_code] += 1
        by_action[action] += 1
    review_open = session.scalar(select(func.count(ReconciliationException.id)).where(
        ReconciliationException.snapshot_id == snapshot.id,
        ReconciliationException.status == "open")) or 0
    return {
        "snapshot": snapshot.name,
        "snapshot_created_at": snapshot.created_at.isoformat(),
        "snapshot_atomic": snapshot.is_atomic,
        "manifest_count": len(manifests),
        "manifest_digest_sha256": manifest_digest,
        "blocked_migration_items": len(rows),
        "open_reconciliation_findings": review_open,
        "counts_are_not_additive": True,
        "by_area": dict(sorted(by_area.items())),
        "by_code": dict(sorted(by_code.items())),
        "by_action": dict(sorted(by_action.items())),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "boundary": "Read-only audit; no BizModo or clone evidence changed; no item auto-approved",
    }, rows


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m klen_clone.domestic_release_audit")
    parser.add_argument("--database-url", default=os.getenv("KLEN_DATABASE_URL"))
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or KLEN_DATABASE_URL is required")
    engine = make_engine(args.database_url)
    with Session(engine) as session:
        summary, rows = build_audit(session, args.snapshot)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.output_dir / "summary.json"
    queue_path = args.output_dir / "blocked_queue.csv"
    if summary_path.exists() or queue_path.exists():
        parser.error("output files already exist; choose a new audit directory")
    with summary_path.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    with queue_path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else [
            "queue_id", "area", "code", "severity", "source_kind", "source_id",
            "queue_status", "source_reference", "raw_record_id", "source_sku",
            "source_uom", "owner_role", "required_action", "evidence",
        ])
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"summary": str(summary_path), "queue": str(queue_path),
                      "blocked_items": summary["blocked_migration_items"]}))


if __name__ == "__main__":
    main()
