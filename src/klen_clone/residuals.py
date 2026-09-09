from __future__ import annotations

from collections import Counter, defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .blueprint import location_key
from .foundation import _add_once
from .resolve import normalize_name
from .transform import datetime_value
from .transactions import _cache, _ensure
from .models import (
    ErpAuditEvent, ErpLocation, ErpParty, ErpPortalIdentity, ErpResidualWorkflowGate,
    ErpSalesTargetEvidence, ErpSalesWorkflowDocument, ErpSecurityUser, ErpShipmentRecord,
    ErpSourceKeyRegistry, ErpStockTransferDetailArtifact, ErpTransactionDocument,
    ErpTransactionLine, RawFileManifest, RawRecord, SourceSnapshot,
)


def unique_match(index: dict[str, list], value: str | None):
    candidates = index.get(normalize_name(value), []) if value else []
    unique = list({row.id: row for row in candidates}.values())
    return unique[0] if len(unique) == 1 else None


def workflow_datetime(value):
    parsed = datetime_value(value)
    return parsed.replace(tzinfo=None) if parsed else None


def _raw_records(session: Session, snapshot_id: int, entity: str) -> list[RawRecord]:
    return list(session.scalars(select(RawRecord).join(RawFileManifest).where(
        RawFileManifest.snapshot_id == snapshot_id, RawFileManifest.entity_type == entity,
        RawRecord.is_presentation_row.is_(False)).order_by(RawRecord.id)))


def build_residual_workflows(session: Session, snapshot_name: str) -> dict:
    snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == snapshot_name))
    if not snapshot:
        raise ValueError(f"Unknown snapshot: {snapshot_name}")
    parties = list(session.scalars(select(ErpParty).where(ErpParty.snapshot_id == snapshot.id)))
    users = list(session.scalars(select(ErpSecurityUser).where(ErpSecurityUser.snapshot_id == snapshot.id)))
    locations = {location_key(row.name): row for row in session.scalars(select(ErpLocation).where(ErpLocation.snapshot_id == snapshot.id))}
    sale_docs = list(session.scalars(select(ErpTransactionDocument).where(
        ErpTransactionDocument.snapshot_id == snapshot.id, ErpTransactionDocument.source_kind == "sale")))
    if not parties or not users or not sale_docs:
        raise RuntimeError("Canonical masters, transactions and security must exist before residual workflows")

    party_email: dict[str, list] = defaultdict(list)
    party_name: dict[str, list] = defaultdict(list)
    for party in parties:
        if party.email:
            party_email[normalize_name(party.email)].append(party)
        for value in (party.legal_or_business_name, party.contact_name):
            if value:
                party_name[normalize_name(value)].append(party)
    user_name: dict[str, list] = defaultdict(list)
    for user in users:
        for value in (user.display_name, user.username):
            if value:
                user_name[normalize_name(value)].append(user)
    documents_by_no: dict[str, list] = defaultdict(list)
    for document in sale_docs:
        documents_by_no[document.document_no].append(document)

    created = Counter()
    portal_fields = ("snapshot_id", "source_raw_record_id")
    portals = _cache(session, ErpPortalIdentity, portal_fields, snapshot.id)
    portal_statuses = Counter()
    for raw in _raw_records(session, snapshot.id, "contact_login"):
        payload = raw.payload or {}
        party = unique_match(party_email, payload.get("Email")) or unique_match(party_name, payload.get("Contact"))
        status = "migration_locked_party_linked" if party else "review_required_party_link"
        key = (snapshot.id, raw.id)
        _, was_created = _ensure(session, ErpPortalIdentity, portals, key, portal_fields,
            {"party_id": party.id if party else None, "username": payload.get("Username"),
             "display_name": payload.get("Name"), "email": payload.get("Email"),
             "department": payload.get("Department"), "designation": payload.get("Designation"),
             "party_link_status": status, "credential_status": "credential_unavailable_reset_required",
             "authentication_enabled": False,
             "evidence": {"source_contact_text": payload.get("Contact"),
                          "source_action_markup_ignored": bool(payload.get("Action")),
                          "password_material_copied": False}})
        created["portal_identities"] += was_created
        portal_statuses[status] += 1

    workflow_fields = ("snapshot_id", "source_raw_record_id")
    workflows = _cache(session, ErpSalesWorkflowDocument, workflow_fields, snapshot.id)
    workflow_statuses = Counter()
    for entity, kind in (("sales_quotation", "quotation"), ("sales_draft", "draft")):
        for raw in _raw_records(session, snapshot.id, entity):
            payload = raw.payload or {}
            party = unique_match(party_name, payload.get("Customer name"))
            location = locations.get(location_key(payload.get("Location")))
            status = "migration_locked_linked" if party and location else "review_required_relationship"
            key = (snapshot.id, raw.id)
            _, was_created = _ensure(session, ErpSalesWorkflowDocument, workflows, key, workflow_fields,
                {"workflow_kind": kind, "reference_no": payload.get("Reference No"),
                 "occurred_at": workflow_datetime(payload.get("Date")), "party_id": party.id if party else None,
                 "location_id": location.id if location else None,
                 "source_total_items": str(payload.get("Total Items")) if payload.get("Total Items") is not None else None,
                 "relationship_status": status, "conversion_enabled": False, "operational_enabled": False,
                 "evidence": {"source_customer_name": payload.get("Customer name"),
                              "source_contact_number_present": bool(payload.get("Contact Number")),
                              "added_by": payload.get("Added By"), "source_action_markup_ignored": bool(payload.get("Action"))}})
            created["sales_workflows"] += was_created
            workflow_statuses[f"{kind}:{status}"] += 1

    shipment_fields = ("snapshot_id", "source_raw_record_id")
    shipments = _cache(session, ErpShipmentRecord, shipment_fields, snapshot.id)
    shipment_statuses = Counter()
    for raw in _raw_records(session, snapshot.id, "shipment"):
        payload = raw.payload or {}
        candidates = documents_by_no.get(str(payload.get("Invoice No.") or ""), [])
        document = candidates[0] if len(candidates) == 1 else None
        location = locations.get(location_key(payload.get("Location")))
        status = "migration_locked_linked" if document and location else "review_required_relationship"
        key = (snapshot.id, raw.id)
        _, was_created = _ensure(session, ErpShipmentRecord, shipments, key, shipment_fields,
            {"sale_document_id": document.id if document else None, "location_id": location.id if location else None,
             "occurred_at": workflow_datetime(payload.get("Date")),
             "source_shipping_status": payload.get("Shipping Status"),
             "source_payment_status": payload.get("Payment Status"), "relationship_status": status,
             "operational_enabled": False,
             "evidence": {"source_invoice_no": payload.get("Invoice No."),
                          "source_customer_name": payload.get("Customer name"),
                          "source_contact_number_present": bool(payload.get("Contact Number")),
                          "source_action_markup_ignored": bool(payload.get("Action"))}})
        created["shipments"] += was_created
        shipment_statuses[status] += 1

    target_fields = ("snapshot_id", "source_raw_record_id")
    targets = _cache(session, ErpSalesTargetEvidence, target_fields, snapshot.id)
    target_statuses = Counter()
    for raw in _raw_records(session, snapshot.id, "sales_target"):
        payload = raw.payload or {}
        user = unique_match(user_name, payload.get("User"))
        status = "user_linked_target_value_unavailable" if user else "review_required_user_link"
        key = (snapshot.id, raw.id)
        _, was_created = _ensure(session, ErpSalesTargetEvidence, targets, key, target_fields,
            {"user_id": user.id if user else None, "source_user_name": payload.get("User"),
             "target_amount": None, "relationship_status": status, "operational_enabled": False,
             "evidence": {"source_action": payload.get("Action"),
                          "warning": "List export exposes target action but no target amount or period."}})
        created["sales_targets"] += was_created
        target_statuses[status] += 1

    mapped_detail_raw_ids = set(session.scalars(select(ErpTransactionLine.source_raw_record_id).where(
        ErpTransactionLine.snapshot_id == snapshot.id, ErpTransactionLine.source_kind == "document_line")))
    registries = {row.raw_record_id: row for row in session.scalars(select(ErpSourceKeyRegistry).where(
        ErpSourceKeyRegistry.snapshot_id == snapshot.id))}
    artifact_fields = ("snapshot_id", "source_raw_record_id")
    artifacts = _cache(session, ErpStockTransferDetailArtifact, artifact_fields, snapshot.id)
    for raw in _raw_records(session, snapshot.id, "stock_transfer_detail"):
        if raw.id in mapped_detail_raw_ids:
            continue
        payload = raw.payload or {}
        key = (snapshot.id, raw.id)
        _, was_created = _ensure(session, ErpStockTransferDetailArtifact, artifacts, key, artifact_fields,
            {"source_url": payload.get("url"), "source_document_number": raw.source_document_number,
             "content_sha256": registries[raw.id].content_sha256,
             "parse_status": "blocked_no_parsed_business_lines", "operational_enabled": False,
             "evidence": {"source_locator": registries[raw.id].source_locator,
                          "text_present": bool(payload.get("text")),
                          "warning": "Artifact retained; no document/product relationship inferred."}})
        created["transfer_artifacts"] += was_created

    gate_specs = {
        "PORTAL_PARTY_LINK": ("Portal identity to party linkage", portal_statuses["review_required_party_link"], {}),
        "PORTAL_CREDENTIAL_RESET": ("Portal credential provisioning", len(portals), {"password_material_copied": False}),
        "QUOTATION_RELATIONSHIPS": ("Quotation party/location relationships", workflow_statuses["quotation:review_required_relationship"], {}),
        "DRAFT_RELATIONSHIPS": ("Draft party/location relationships", workflow_statuses["draft:review_required_relationship"], {}),
        "SHIPMENT_RELATIONSHIPS": ("Shipment invoice/location relationships", shipment_statuses["review_required_relationship"], {}),
        "SALES_TARGET_DEFINITION": ("Sales target amount and period definition", len(targets), {"source_amounts_available": 0}),
        "TRANSFER_DETAIL_PARSE": ("Stock-transfer detail parsing", len(artifacts), {}),
    }
    gates = {}
    for code, (name, issues, evidence) in gate_specs.items():
        gate, was_created = _add_once(session, ErpResidualWorkflowGate,
            {"snapshot_id": snapshot.id, "gate_code": code},
            {"gate_name": name, "issue_count": issues,
             "gate_status": "blocked" if issues else "ready_disabled",
             "activation_enabled": False, "evidence": evidence})
        created["workflow_gates"] += was_created
        gates[code] = {"status": gate.gate_status, "issues": gate.issue_count}

    event_key = f"residual-workflows:{len(portals)}:{len(workflows)}:{len(shipments)}:{len(targets)}:{len(artifacts)}"
    _, was_created = _add_once(session, ErpAuditEvent,
        {"snapshot_id": snapshot.id, "event_key": event_key},
        {"event_type": "residual_workflows_registered", "actor_type": "migration_service",
         "details": {"portal_identities": len(portals), "sales_workflows": len(workflows),
                     "shipments": len(shipments), "sales_targets": len(targets),
                     "transfer_artifacts": len(artifacts), "password_material_copied": False,
                     "authentication_enabled": False, "operational_enabled": False,
                     "source_mutated": False}})
    created["audit_events"] += was_created
    session.commit()

    enabled = {
        "portal_authentication": session.scalar(select(func.count(ErpPortalIdentity.id)).where(ErpPortalIdentity.snapshot_id == snapshot.id, ErpPortalIdentity.authentication_enabled.is_(True))) or 0,
        "workflow_operation": session.scalar(select(func.count(ErpSalesWorkflowDocument.id)).where(ErpSalesWorkflowDocument.snapshot_id == snapshot.id, ErpSalesWorkflowDocument.operational_enabled.is_(True))) or 0,
        "shipment_operation": session.scalar(select(func.count(ErpShipmentRecord.id)).where(ErpShipmentRecord.snapshot_id == snapshot.id, ErpShipmentRecord.operational_enabled.is_(True))) or 0,
        "target_operation": session.scalar(select(func.count(ErpSalesTargetEvidence.id)).where(ErpSalesTargetEvidence.snapshot_id == snapshot.id, ErpSalesTargetEvidence.operational_enabled.is_(True))) or 0,
        "gate_activation": session.scalar(select(func.count(ErpResidualWorkflowGate.id)).where(ErpResidualWorkflowGate.snapshot_id == snapshot.id, ErpResidualWorkflowGate.activation_enabled.is_(True))) or 0,
    }
    return {"snapshot": snapshot.name, "portal_identities": len(portals),
            "portal_status": dict(portal_statuses), "sales_workflows": len(workflows),
            "workflow_status": dict(workflow_statuses), "shipments": len(shipments),
            "shipment_status": dict(shipment_statuses), "sales_targets": len(targets),
            "target_status": dict(target_statuses), "transfer_artifacts": len(artifacts),
            "workflow_gates": gates, "active_controls": enabled, "new_records": dict(created)}
