from __future__ import annotations

from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .foundation import _add_once
from .transactions import _cache, _ensure
from .models import (
    ErpApprovalRequest, ErpAuditEvent, ErpAuthPrincipal, ErpRuntimeActivationGate,
    ErpRuntimeModule, ErpSecurityLocationScope, ErpSecurityRolePermission,
    ErpSecurityUser, ErpWorkflowDefinition, SourceSnapshot,
)


def build_runtime_foundation(session: Session, snapshot_name: str) -> dict:
    snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == snapshot_name))
    if not snapshot:
        raise ValueError(f"Unknown snapshot: {snapshot_name}")
    users = list(session.scalars(select(ErpSecurityUser).where(ErpSecurityUser.snapshot_id == snapshot.id)))
    if not users:
        raise RuntimeError("Security controls must exist before runtime foundation")
    created = Counter()

    principal_fields = ("snapshot_id", "security_user_id")
    principals = _cache(session, ErpAuthPrincipal, principal_fields, snapshot.id)
    for user in users:
        key = (snapshot.id, user.id)
        _, was_created = _ensure(session, ErpAuthPrincipal, principals, key, principal_fields,
            {"login_name": user.username, "password_hash": None,
             "auth_status": "disabled_unprovisioned", "mfa_enrolled": False,
             "authentication_enabled": False,
             "evidence": {"source_user_id": user.source_user_id,
                          "requires_identity_verification": True, "requires_new_password": True}})
        created["auth_principals"] += was_created

    workflow_specs = {
        "MIGRATION_ACTIVATION": ("Migration batch activation", "draft",
            ["draft", "submitted", "approved", "activated", "rejected"],
            [{"from": "draft", "to": "submitted"}, {"from": "submitted", "to": "approved"},
             {"from": "submitted", "to": "rejected"}, {"from": "approved", "to": "activated"}]),
        "JOURNAL_ACTIVATION": ("Journal blueprint activation", "draft",
            ["draft", "submitted", "approved", "rejected"],
            [{"from": "draft", "to": "submitted"}, {"from": "submitted", "to": "approved"},
             {"from": "submitted", "to": "rejected"}]),
        "OPENING_BALANCE": ("Opening balance approval", "pending",
            ["pending", "approved", "rejected"],
            [{"from": "pending", "to": "approved"}, {"from": "pending", "to": "rejected"}]),
        "EXCEPTION_RESOLUTION": ("Migration exception resolution", "open",
            ["open", "evidence_attached", "approved", "rejected"],
            [{"from": "open", "to": "evidence_attached"},
             {"from": "evidence_attached", "to": "approved"},
             {"from": "evidence_attached", "to": "rejected"}]),
    }
    for code, (name, initial, states, transitions) in workflow_specs.items():
        _, was_created = _add_once(session, ErpWorkflowDefinition,
            {"snapshot_id": snapshot.id, "workflow_code": code},
            {"workflow_name": name, "initial_state": initial, "states": states,
             "transitions": transitions, "workflow_status": "draft_locked",
             "execution_enabled": False})
        created["workflow_definitions"] += was_created

    module_specs = {
        "sales": ("Sales", "/erp/sales"), "purchasing": ("Purchasing", "/erp/purchasing"),
        "inventory": ("Inventory", "/erp/inventory"), "accounting": ("Accounting", "/erp/accounting"),
        "crm": ("CRM", "/erp/crm"), "delivery": ("Delivery", "/erp/delivery"),
        "reporting": ("Reports", "/erp/reports"), "administration": ("Administration", "/erp/admin"),
    }
    for code, (name, prefix) in module_specs.items():
        _, was_created = _add_once(session, ErpRuntimeModule,
            {"snapshot_id": snapshot.id, "module_code": code},
            {"module_name": name, "route_prefix": prefix, "module_status": "shell_disabled",
             "operation_enabled": False, "evidence": {"hrm_payroll_excluded": True}})
        created["runtime_modules"] += was_created

    active_grants = session.scalar(select(func.count(ErpSecurityRolePermission.id)).where(
        ErpSecurityRolePermission.target_granted.is_(True))) or 0
    active_scopes = session.scalar(select(func.count(ErpSecurityLocationScope.id)).where(
        ErpSecurityLocationScope.snapshot_id == snapshot.id, ErpSecurityLocationScope.access_enabled.is_(True))) or 0
    gate_specs = {
        "AUTH_PRINCIPAL_PROVISIONING": ("Identity, credential and MFA provisioning", len(principals), {}),
        "POSTGRESQL_DEPLOYMENT": ("PostgreSQL deployment and backup verification", 1, {"local_engine": "sqlite"}),
        "RBAC_ENFORCEMENT": ("Approved target permission grants", 1 if active_grants == 0 else 0, {"active_grants": active_grants}),
        "LOCATION_SCOPE_ENFORCEMENT": ("Approved user location scopes", 1 if active_scopes == 0 else 0, {"active_scopes": active_scopes}),
        "WORKFLOW_APPROVAL": ("Workflow definition and approver approval", len(workflow_specs), {}),
        "TLS_AND_SECRETS": ("TLS, secret rotation and deployment security", 1, {}),
        "FROZEN_CUTOVER": ("Frozen source extraction and delta reconciliation", 1, {}),
    }
    gates = {}
    for code, (name, issues, evidence) in gate_specs.items():
        gate, was_created = _add_once(session, ErpRuntimeActivationGate,
            {"snapshot_id": snapshot.id, "gate_code": code},
            {"gate_name": name, "issue_count": issues, "gate_status": "blocked" if issues else "ready_disabled",
             "activation_enabled": False, "evidence": evidence})
        created["runtime_gates"] += was_created
        gates[code] = {"status": gate.gate_status, "issues": gate.issue_count}

    event_key = f"runtime-foundation:{len(principals)}:{len(workflow_specs)}:{len(module_specs)}"
    _, was_created = _add_once(session, ErpAuditEvent,
        {"snapshot_id": snapshot.id, "event_key": event_key},
        {"event_type": "runtime_foundation_registered", "actor_type": "migration_service",
         "details": {"auth_principals": len(principals), "workflow_definitions": len(workflow_specs),
                     "runtime_modules": len(module_specs), "approval_requests": 0,
                     "authentication_enabled": False, "workflow_execution_enabled": False,
                     "module_operation_enabled": False, "source_mutated": False}})
    created["audit_events"] += was_created
    session.commit()
    active = {
        "authenticated_principals": session.scalar(select(func.count(ErpAuthPrincipal.id)).where(
            ErpAuthPrincipal.snapshot_id == snapshot.id, ErpAuthPrincipal.authentication_enabled.is_(True))) or 0,
        "executable_workflows": session.scalar(select(func.count(ErpWorkflowDefinition.id)).where(
            ErpWorkflowDefinition.snapshot_id == snapshot.id, ErpWorkflowDefinition.execution_enabled.is_(True))) or 0,
        "operational_modules": session.scalar(select(func.count(ErpRuntimeModule.id)).where(
            ErpRuntimeModule.snapshot_id == snapshot.id, ErpRuntimeModule.operation_enabled.is_(True))) or 0,
        "approval_requests": session.scalar(select(func.count(ErpApprovalRequest.id)).where(
            ErpApprovalRequest.snapshot_id == snapshot.id)) or 0,
    }
    return {"snapshot": snapshot.name, "auth_principals": len(principals),
            "workflow_definitions": len(workflow_specs), "runtime_modules": len(module_specs),
            "runtime_gates": gates, "active_controls": active, "new_records": dict(created)}
