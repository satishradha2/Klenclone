from __future__ import annotations

from collections import defaultdict
from datetime import date
import hashlib
import json
import re

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .models import (
    ErpApprovalPolicy, ErpApprovalStep, ErpAuditEvent, ErpFiscalPeriod,
    ErpLocation, ErpMigrationBatch, ErpMigrationBatchEntity, ErpModulePolicy,
    ErpNumberSequence, ErpOrganization, ErpSourceKeyRegistry,
    RawFileManifest, RawRecord, SourceSnapshot,
)


REFERENCE_PATTERN = re.compile(r"^(.*?)(\d+)$")
OPERATIONAL_MODULES = ("sales", "purchasing", "inventory", "accounting", "crm", "delivery", "reporting", "administration", "hrm")
ARCHIVAL_ONLY_MODULES = ("payroll",)


def source_entity_counts_statement(snapshot_id: int):
    return (
        select(
            RawFileManifest.entity_type,
            func.count(RawRecord.id),
            func.sum(case((RawRecord.is_presentation_row.is_(False), 1), else_=0)),
        )
        .join(RawRecord)
        .where(RawFileManifest.snapshot_id == snapshot_id)
        .group_by(RawFileManifest.entity_type)
    )


def parse_reference(value: str | None) -> tuple[str, int, int] | None:
    if not value:
        return None
    match = REFERENCE_PATTERN.match(value.strip())
    if not match:
        return None
    digits = match.group(2)
    return match.group(1), int(digits), len(digits)


def canonical_content_hash(record: RawRecord) -> str:
    if record.payload is not None:
        serialized = json.dumps(record.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    else:
        serialized = record.payload_text or ""
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _add_once(session: Session, model, filters: dict, values: dict):
    row = session.scalar(select(model).filter_by(**filters))
    if row:
        for key, expected in values.items():
            if getattr(row, key) != expected:
                raise RuntimeError(f"Immutable foundation mismatch: {model.__name__}.{key}")
        return row, False
    row = model(**filters, **values)
    session.add(row)
    session.flush()
    return row, True


def _sequence_evidence(records: list[RawRecord]) -> list[dict]:
    grouped: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    for record in records:
        parsed = parse_reference(record.source_document_number)
        if parsed:
            prefix, number, width = parsed
            grouped[prefix].append((number, width, record.source_document_number or ""))
    result = []
    for prefix, values in grouped.items():
        maximum = max(values, key=lambda item: item[0])
        result.append({"prefix": prefix, "last": maximum[0], "width": maximum[1], "sample": maximum[2], "observations": len(values)})
    return sorted(result, key=lambda item: (-item["observations"], item["prefix"]))


def _business_control(records: list[RawRecord], name: str) -> str | None:
    for record in records:
        if record.manifest.entity_type != "business_setting" or not isinstance(record.payload, dict):
            continue
        for control in record.payload.get("controls", []):
            if isinstance(control, dict) and control.get("name") == name:
                value = control.get("value")
                return str(value).strip() if value not in (None, "") else None
    return None


def build_erp_foundation(session: Session, snapshot_name: str) -> dict:
    snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == snapshot_name))
    if not snapshot:
        raise ValueError(f"Unknown snapshot: {snapshot_name}")

    created = defaultdict(int)
    raw_records = list(session.scalars(select(RawRecord).join(RawFileManifest).where(RawFileManifest.snapshot_id == snapshot.id)))
    tax_registration_number = _business_control(raw_records, "tax_number_1")
    org, was_created = _add_once(session, ErpOrganization,
        {"snapshot_id": snapshot.id, "source_key": "bizmodo-business"},
        {"legal_name": "Asas General Trading LLC", "currency_code": "AED", "timezone_name": "Asia/Dubai",
         "inventory_cost_method": "FIFO", "tax_registration_number": tax_registration_number,
         "operational_status": "migration_locked", "posting_enabled": False,
         "settings": {"fiscal_year_start_month": 1, "currency_precision": 2, "quantity_precision": 2,
                      "default_vat_percent": 5, "source_pos_rounding": "nearest_0.25", "source_version": "BizModo V7.5.1"}})
    created["organizations"] += was_created

    locations = [
        ("BL0001", "MAIN", "Asas General Trading LLC", "1007 Mohammed Al Mualla Tower, A Nahda, Sharjah, UAE"),
        ("BL0004", "DXB", "DXB", None), ("BL0003", "RAK", "RAK", None), ("BL0002", "SHJ", "SHJ", None),
    ]
    for source_key, code, name, address in locations:
        _, was_created = _add_once(session, ErpLocation, {"snapshot_id": snapshot.id, "source_key": source_key},
            {"organization_id": org.id, "code": code, "name": name, "address": address,
             "operational_status": "migration_locked", "posting_enabled": False})
        created["locations"] += was_created

    _, was_created = _add_once(session, ErpFiscalPeriod, {"snapshot_id": snapshot.id, "period_code": "FY2026"},
        {"organization_id": org.id, "starts_on": date(2026, 1, 1), "ends_on": date(2026, 12, 31),
         "status": "locked_pending_cutover", "posting_enabled": False})
    created["fiscal_periods"] += was_created

    entity_records: dict[str, list[RawRecord]] = defaultdict(list)
    for row in raw_records:
        entity_records[row.manifest.entity_type].append(row)
        _, was_created = _add_once(session, ErpSourceKeyRegistry, {"raw_record_id": row.id},
            {"snapshot_id": snapshot.id, "source_entity": row.manifest.entity_type,
             "source_record_id": row.source_record_id, "source_document_number": row.source_document_number,
             "manifest_sha256": row.manifest.sha256, "content_sha256": canonical_content_hash(row),
             "source_locator": f"{row.manifest.relative_path}#{row.ordinal}"})
        created["source_keys"] += was_created

    sequence_kinds = {"sale": "sales_invoice", "purchase": "purchase", "sale_payment": "sales_payment",
                      "purchase_payment": "purchase_payment", "sales_return": "sales_return",
                      "purchase_return": "purchase_return", "stock_transfer": "stock_transfer"}
    sequence_count = 0
    for entity, kind in sequence_kinds.items():
        for index, evidence in enumerate(_sequence_evidence(entity_records.get(entity, [])), start=1):
            sequence_code = f"{kind}:{index}:{evidence['prefix'] or 'numeric'}"
            _, was_created = _add_once(session, ErpNumberSequence,
                {"snapshot_id": snapshot.id, "sequence_code": sequence_code},
                {"document_kind": kind, "source_prefix": evidence["prefix"], "digit_width": evidence["width"],
                 "last_observed_value": evidence["last"], "next_candidate_value": evidence["last"] + 1,
                 "status": "frozen_pending_cutover", "reservation_enabled": False,
                 "evidence": {**evidence, "warning": "candidate only; browser snapshot is non-atomic"}})
            created["number_sequences"] += was_created
            sequence_count += 1
    # Preserve configured invoice schemes even if the header extract predates them.
    for code, kind, prefix, width, last in (("sales_invoice:configured_default", "sales_invoice", "AK2026-", 5, 3611),
                                            ("sales_invoice:configured_van", "sales_invoice", "NUVO-", 4, 3)):
        _, was_created = _add_once(session, ErpNumberSequence, {"snapshot_id": snapshot.id, "sequence_code": code},
            {"document_kind": kind, "source_prefix": prefix, "digit_width": width, "last_observed_value": last,
             "next_candidate_value": last + 1, "status": "frozen_pending_cutover", "reservation_enabled": False,
             "evidence": {"source": "invoice scheme configuration", "warning": "count is not a guaranteed next number"}})
        created["number_sequences"] += was_created
        sequence_count += 1

    for module in (*OPERATIONAL_MODULES, *ARCHIVAL_ONLY_MODULES):
        archival = module in ARCHIVAL_ONLY_MODULES
        _, was_created = _add_once(session, ErpModulePolicy, {"snapshot_id": snapshot.id, "module_code": module},
            {"source_observed": True, "target_enabled": False, "mode": "archival_only" if archival else "draft_disabled",
             "posting_enabled": False,
             "rationale": "Source evidence preserved; excluded from target operational ERP." if archival else "Disabled until reconciled migration approval and cutover."})
        created["module_policies"] += was_created

    policies = {
        "migration_batch_activation": ("Migration batch activation", ("data_owner", "finance_controller", "system_administrator")),
        "journal_activation": ("Journal blueprint activation", ("finance_controller", "system_administrator")),
        "inventory_opening": ("Inventory opening approval", ("inventory_controller", "finance_controller")),
        "exception_resolution": ("Reconciliation exception resolution", ("data_owner", "finance_controller")),
    }
    for policy_code, (name, roles) in policies.items():
        policy, was_created = _add_once(session, ErpApprovalPolicy, {"snapshot_id": snapshot.id, "policy_code": policy_code},
            {"name": name, "status": "draft_locked", "activation_enabled": False,
             "scope": {"thresholds": None, "note": "No monetary threshold inferred from source."}})
        created["approval_policies"] += was_created
        for step_no, role in enumerate(roles, start=1):
            _, step_created = _add_once(session, ErpApprovalStep, {"policy_id": policy.id, "step_no": step_no},
                {"role_code": role, "decision_required": True})
            created["approval_steps"] += step_created

    manifests = list(session.scalars(select(RawFileManifest).where(RawFileManifest.snapshot_id == snapshot.id)))
    digest_input = "\n".join(f"{m.relative_path}:{m.sha256}:{m.source_record_count}" for m in sorted(manifests, key=lambda x: x.relative_path))
    digest = hashlib.sha256(digest_input.encode()).hexdigest()
    batch, was_created = _add_once(session, ErpMigrationBatch,
        {"snapshot_id": snapshot.id, "batch_code": f"{snapshot.name}:foundation"},
        {"manifest_digest": digest, "status": "staged_nonposting", "atomic_source": snapshot.is_atomic, "posting_enabled": False})
    created["migration_batches"] += was_created
    counts = session.execute(source_entity_counts_statement(snapshot.id)).all()
    for entity, raw_count, business_count in counts:
        _, was_created = _add_once(session, ErpMigrationBatchEntity, {"batch_id": batch.id, "source_entity": entity},
            {"raw_count": raw_count, "business_count": business_count or 0, "status": "registered"})
        created["batch_entities"] += was_created

    _, was_created = _add_once(session, ErpAuditEvent,
        {"snapshot_id": snapshot.id, "event_key": f"foundation:{digest}"},
        {"event_type": "erp_foundation_registered", "actor_type": "migration_service",
         "details": {"batch_code": batch.batch_code, "manifest_digest": digest, "posting_enabled": False,
                     "source_mutated": False, "hrm_mode": "operational_controlled", "payroll_mode": "archival_only"}})
    created["audit_events"] += was_created
    session.commit()

    return {"snapshot": snapshot.name, "status": batch.status, "manifest_digest": digest,
            "raw_source_keys": len(raw_records), "organizations": 1, "locations": len(locations),
            "number_sequences": sequence_count, "module_policies": 10, "approval_policies": len(policies),
            "posting_enabled_records": 0, "new_records": dict(created)}
