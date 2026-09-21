from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .foundation import _add_once
from .transactions import _cache, _ensure
from .models import (
    ErpAuditEvent, ErpCashLedgerEvidence, ErpCoverageGate, ErpGlAccount,
    ErpInventoryMovement, ErpOpeningBalanceQueue, ErpParty, ErpProductMaster,
    ErpReferenceMaster, ErpResidualBusinessRecord, ErpSecurityRole, ErpSecurityUser,
    ErpSourceCoverage, ErpSourceKeyRegistry, ErpTaxLedgerEvidence,
    ErpTransactionDocument, ErpTransactionLine, ErpTransactionPayment,
    ErpTrialBalanceEvidence, ErpUomMaster, RawFileManifest, RawRecord, SourceSnapshot,
    ErpPortalIdentity, ErpSalesTargetEvidence, ErpSalesWorkflowDocument,
    ErpShipmentRecord, ErpStockTransferDetailArtifact,
    StgCashFlowEntry, StgInventoryOpeningControl, StgPaymentAccount, StgStockBalance,
    StgTaxEvidence, StgTrialBalanceEntry,
)

REFERENCE_ENTITIES = {"brand", "category", "industry", "expense_category", "zone"}
OPERATIONAL_PENDING_ENTITIES = {"contact_login", "sales_quotation", "sales_draft", "shipment", "sales_target", "attendance", "shift"}
ARCHIVAL_ONLY_ENTITIES = set()
CONTROL_EVIDENCE_ENTITIES = {"pos_sale", "profit_by_product", "item_trace", "business_setting", "configuration_inventory", "cash_flow_boundary"}
KNOWN_STRUCTURED_UNMAPPED_ENTITIES = {"stock_transfer_detail"}


def residual_class(entity: str) -> tuple[str, str]:
    if entity in OPERATIONAL_PENDING_ENTITIES:
        return "operational_pending", "structured_promotion_required"
    if entity in ARCHIVAL_ONLY_ENTITIES:
        return "hrm_archival", "archival_only_preserved"
    if entity in CONTROL_EVIDENCE_ENTITIES:
        return "control_evidence", "control_evidence_preserved"
    return "unclassified", "unknown_review_required"


def reference_identity(entity: str, payload: dict, raw_id: int) -> tuple[str, str]:
    fields = {
        "brand": (None, "Brands"),
        "category": ("Category Code", "Category"),
        "industry": (None, "Name"),
        "expense_category": ("Category code", "Category name"),
        "zone": (None, "Zone name"),
    }
    code_field, name_field = fields[entity]
    name = str(payload.get(name_field) or f"SOURCE-{entity}-{raw_id}").strip()
    explicit_code = str(payload.get(code_field) or "").strip() if code_field else ""
    generated = re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-")
    return explicit_code or generated or f"RAW-{raw_id}", name


def build_coverage_closure(session: Session, snapshot_name: str) -> dict:
    snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == snapshot_name))
    if not snapshot:
        raise ValueError(f"Unknown snapshot: {snapshot_name}")
    raw_rows = list(session.scalars(select(RawRecord).join(RawFileManifest).where(
        RawFileManifest.snapshot_id == snapshot.id).order_by(RawRecord.id)))
    registries = {row.raw_record_id: row for row in session.scalars(select(ErpSourceKeyRegistry).where(
        ErpSourceKeyRegistry.snapshot_id == snapshot.id))}
    if len(registries) != len(raw_rows):
        raise RuntimeError("Source-key registry must cover all raw rows before coverage closure")

    targets: dict[int, list[tuple[str, int]]] = defaultdict(list)
    def add(raw_id: int | None, kind: str, target_id: int | None):
        if raw_id is not None and target_id is not None:
            targets[raw_id].append((kind, target_id))

    for model, kind, raw_field in (
        (ErpParty, "party", "source_raw_record_id"), (ErpProductMaster, "product", "source_raw_record_id"),
        (ErpUomMaster, "uom", "source_raw_record_id"),
        (ErpTransactionDocument, "transaction_document", "source_raw_record_id"),
        (ErpTransactionLine, "transaction_line", "source_raw_record_id"),
        (ErpTransactionPayment, "transaction_payment", "source_raw_record_id"),
        (ErpSecurityUser, "security_user", "source_user_id"),
        (ErpPortalIdentity, "portal_identity", "source_raw_record_id"),
        (ErpSalesWorkflowDocument, "sales_workflow_document", "source_raw_record_id"),
        (ErpShipmentRecord, "shipment", "source_raw_record_id"),
        (ErpSalesTargetEvidence, "sales_target", "source_raw_record_id"),
        (ErpStockTransferDetailArtifact, "stock_transfer_detail_artifact", "source_raw_record_id"),
    ):
        for row in session.scalars(select(model).where(model.snapshot_id == snapshot.id)):
            add(getattr(row, raw_field), kind, row.id)
    for row in session.scalars(select(ErpSecurityRole).where(ErpSecurityRole.snapshot_id == snapshot.id)):
        add(row.source_raw_record_id, "security_role", row.id)

    for target, source in session.execute(select(ErpTaxLedgerEvidence, StgTaxEvidence).join(
        StgTaxEvidence, ErpTaxLedgerEvidence.source_tax_id == StgTaxEvidence.id).where(
        ErpTaxLedgerEvidence.snapshot_id == snapshot.id)):
        add(source.raw_record_id, "tax_ledger_evidence", target.id)
    for target, source in session.execute(select(ErpCashLedgerEvidence, StgCashFlowEntry).join(
        StgCashFlowEntry, ErpCashLedgerEvidence.source_cash_id == StgCashFlowEntry.id).where(
        ErpCashLedgerEvidence.snapshot_id == snapshot.id)):
        add(source.raw_record_id, "cash_ledger_evidence", target.id)
    for target, source in session.execute(select(ErpTrialBalanceEvidence, StgTrialBalanceEntry).join(
        StgTrialBalanceEntry, ErpTrialBalanceEvidence.source_trial_id == StgTrialBalanceEntry.id).where(
        ErpTrialBalanceEvidence.snapshot_id == snapshot.id)):
        add(source.raw_record_id, "trial_balance_evidence", target.id)
    gl_by_name = {row.source_name.casefold(): row for row in session.scalars(select(ErpGlAccount).where(
        ErpGlAccount.snapshot_id == snapshot.id, ErpGlAccount.source_name.is_not(None)))}
    for source in session.scalars(select(StgPaymentAccount).where(StgPaymentAccount.snapshot_id == snapshot.id)):
        account = gl_by_name.get(source.name.casefold())
        add(source.raw_record_id, "gl_account", account.id if account else None)
    for queue, balance in session.execute(select(ErpOpeningBalanceQueue, StgStockBalance).join(
        StgInventoryOpeningControl, ErpOpeningBalanceQueue.source_id == StgInventoryOpeningControl.id).join(
        StgStockBalance, StgInventoryOpeningControl.stock_balance_id == StgStockBalance.id).where(
        ErpOpeningBalanceQueue.snapshot_id == snapshot.id,
        ErpOpeningBalanceQueue.source_kind == "inventory_opening_control")):
        add(balance.raw_record_id, "opening_balance_queue", queue.id)

    sale_docs_by_no: dict[str, list[ErpTransactionDocument]] = defaultdict(list)
    for doc in session.scalars(select(ErpTransactionDocument).where(
        ErpTransactionDocument.snapshot_id == snapshot.id, ErpTransactionDocument.source_kind == "sale")):
        sale_docs_by_no[doc.document_no].append(doc)
    for raw in raw_rows:
        if raw.manifest.entity_type == "pos_sale":
            number = raw.source_document_number or str((raw.payload or {}).get("Invoice No.") or "")
            candidates = sale_docs_by_no.get(number, [])
            if len(candidates) == 1:
                add(raw.id, "transaction_document_control_view", candidates[0].id)

    created = Counter()
    reference_fields = ("snapshot_id", "source_raw_record_id")
    references = _cache(session, ErpReferenceMaster, reference_fields, snapshot.id)
    for raw in raw_rows:
        entity = raw.manifest.entity_type
        if raw.is_presentation_row or entity not in REFERENCE_ENTITIES:
            continue
        payload = raw.payload if isinstance(raw.payload, dict) else {}
        code, name = reference_identity(entity, payload, raw.id)
        key = (snapshot.id, raw.id)
        reference, was_created = _ensure(session, ErpReferenceMaster, references, key, reference_fields,
            {"reference_kind": entity, "reference_code": code, "reference_name": name,
             "migration_status": "migration_locked_ready", "operational_enabled": False,
             "evidence": {"source_note": payload.get("Note") or payload.get("Description"),
                          "shipping_charges": payload.get("Shipping Charges") if entity == "zone" else None,
                          "source_record_id": raw.source_record_id}})
        created["reference_masters"] += was_created
    session.flush()
    for (_, raw_id), reference in references.items():
        add(raw_id, "reference_master", reference.id)

    residual_fields = ("snapshot_id", "source_raw_record_id")
    residuals = _cache(session, ErpResidualBusinessRecord, residual_fields, snapshot.id)
    coverage_fields = ("snapshot_id", "source_raw_record_id")
    coverage = _cache(session, ErpSourceCoverage, coverage_fields, snapshot.id)
    coverage_statuses = Counter()
    residual_classes = Counter()
    promoted_residuals = 0
    entity_stats = defaultdict(Counter)
    for raw in raw_rows:
        entity = raw.manifest.entity_type
        entity_stats[entity]["source"] += 1
        registry = registries[raw.id]
        mapped = sorted(set(targets.get(raw.id, [])))
        needs_residual = (raw.is_presentation_row or entity in ARCHIVAL_ONLY_ENTITIES | CONTROL_EVIDENCE_ENTITIES
                          or (entity in OPERATIONAL_PENDING_ENTITIES and not mapped))
        if raw.is_presentation_row:
            evidence_class, status = "presentation_quarantine", "presentation_quarantined"
            action = "Retain as UI/footer evidence; never load as a business record."
        elif entity in CONTROL_EVIDENCE_ENTITIES:
            evidence_class, status = residual_class(entity)
            status = "control_evidence_linked" if mapped else status
            action = "Retain as report/configuration evidence; do not double-post."
        elif entity in ARCHIVAL_ONLY_ENTITIES:
            evidence_class, status = residual_class(entity)
            action = "Preserve payroll-only evidence in archive; HRM is promoted through its controlled workflow."
        elif mapped:
            evidence_class, status, action = "structured", "structured_linked", None
        elif entity in OPERATIONAL_PENDING_ENTITIES:
            evidence_class, status = residual_class(entity)
            action = "Build and reconcile the dedicated operational workflow before activation."
        elif entity in KNOWN_STRUCTURED_UNMAPPED_ENTITIES and not mapped:
            evidence_class, status = "operational_pending", "structured_promotion_required"
            action = "Resolve the missing canonical parent/product relationship before activation."
            needs_residual = True
        else:
            evidence_class, status = residual_class(entity)
            action = "Classify and map before cutover."
            needs_residual = True
        if needs_residual:
            key = (snapshot.id, raw.id)
            _, was_created = _ensure(session, ErpResidualBusinessRecord, residuals, key, residual_fields,
                {"source_entity": entity, "evidence_class": evidence_class,
                 "migration_status": status, "content_sha256": registry.content_sha256,
                 "operational_enabled": False,
                 "evidence": {"source_locator": registry.source_locator,
                              "source_record_id": raw.source_record_id,
                              "source_document_number": raw.source_document_number,
                              "target_links": [{"kind": kind, "id": target_id} for kind, target_id in mapped]}})
            created["residual_records"] += was_created
            residual_classes[evidence_class] += 1
            entity_stats[entity]["residual"] += 1
        elif mapped and entity in OPERATIONAL_PENDING_ENTITIES | KNOWN_STRUCTURED_UNMAPPED_ENTITIES:
            historical = residuals.get((snapshot.id, raw.id))
            if historical:
                historical.migration_status = "structured_promoted_locked"
                historical.evidence = {**(historical.evidence or {}),
                    "target_links": [{"kind": kind, "id": target_id} for kind, target_id in mapped]}
                promoted_residuals += 1
        if mapped:
            entity_stats[entity]["structured"] += 1
        if raw.is_presentation_row:
            entity_stats[entity]["presentation"] += 1
        target_kinds = sorted({kind for kind, _ in mapped})
        key = (snapshot.id, raw.id)
        coverage_values = {"source_entity": entity, "coverage_status": status,
            "target_kind": target_kinds[0] if len(target_kinds) == 1 else "multiple" if target_kinds else None,
            "target_ids": [{"kind": kind, "id": target_id} for kind, target_id in mapped],
            "target_count": len(mapped), "required_action": action, "activation_enabled": False}
        coverage_row = coverage.get(key)
        if coverage_row:
            for field, value in coverage_values.items():
                setattr(coverage_row, field, value)
            was_created = False
        else:
            coverage_row = ErpSourceCoverage(**dict(zip(coverage_fields, key)), **coverage_values)
            session.add(coverage_row)
            coverage[key] = coverage_row
            was_created = True
        created["coverage_rows"] += was_created
        coverage_statuses[status] += 1
        if status == "structured_promotion_required":
            entity_stats[entity]["pending"] += 1
        elif status == "unknown_review_required":
            entity_stats[entity]["unknown"] += 1

    gate_fields = ("snapshot_id", "source_entity")
    gates = _cache(session, ErpCoverageGate, gate_fields, snapshot.id)
    gate_statuses = Counter()
    blocked_entities = []
    for entity, stats in sorted(entity_stats.items()):
        pending = stats["pending"]
        unknown = stats["unknown"]
        gate_status = "blocked_structured_promotion" if pending else "blocked_unclassified" if unknown else "covered_locked"
        key = (snapshot.id, entity)
        gate_values = {"source_row_count": stats["source"], "structured_count": stats["structured"],
            "residual_count": stats["residual"], "presentation_count": stats["presentation"],
            "gate_status": gate_status, "activation_enabled": False,
            "evidence": {"structured_promotion_pending": pending, "unclassified_rows": unknown}}
        gate = gates.get(key)
        if gate:
            for field, value in gate_values.items():
                setattr(gate, field, value)
            was_created = False
        else:
            gate = ErpCoverageGate(**dict(zip(gate_fields, key)), **gate_values)
            session.add(gate)
            gates[key] = gate
            was_created = True
        created["coverage_gates"] += was_created
        gate_statuses[gate_status] += 1
        if gate_status != "covered_locked":
            blocked_entities.append({"entity": entity, "status": gate_status, "rows": pending or unknown})

    state_digest = hashlib.sha256(json.dumps({"statuses": sorted(coverage_statuses.items()),
        "blocked": blocked_entities}, sort_keys=True).encode()).hexdigest()[:16]
    event_key = f"coverage-closure:{len(raw_rows)}:{state_digest}"
    _, was_created = _add_once(session, ErpAuditEvent,
        {"snapshot_id": snapshot.id, "event_key": event_key},
        {"event_type": "source_coverage_registered", "actor_type": "migration_service",
         "details": {"raw_rows": len(raw_rows), "coverage_rows": len(coverage),
                     "reference_masters": len(references), "residual_records": len(residuals),
            "coverage_gates": len(gates), "blocked_entities": blocked_entities,
                     "promoted_residuals": promoted_residuals,
                     "source_mutated": False, "activation_enabled": False}})
    created["audit_events"] += was_created
    session.commit()

    active = session.scalar(select(func.count(ErpSourceCoverage.id)).where(
        ErpSourceCoverage.snapshot_id == snapshot.id, ErpSourceCoverage.activation_enabled.is_(True))) or 0
    return {"snapshot": snapshot.name, "raw_rows": len(raw_rows), "coverage_rows": len(coverage),
            "coverage_status": dict(coverage_statuses), "reference_masters": len(references),
            "residual_records": len(residuals), "residual_class": dict(residual_classes),
            "coverage_gates": len(gates), "gate_status": dict(gate_statuses),
            "blocked_entities": blocked_entities, "uncovered_rows": len(raw_rows) - len(coverage),
            "promoted_residuals": promoted_residuals,
            "activation_enabled_rows": active, "new_records": dict(created)}
