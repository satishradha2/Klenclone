from __future__ import annotations

from collections import Counter
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .foundation import _add_once
from .transactions import _cache, _ensure
from .models import (
    ErpApprovalRoleBinding, ErpApprovalStep, ErpAuditEvent, ErpSecurityActivationGate,
    ErpSecurityLocationScope, ErpSecurityPermission, ErpSecurityPolicy, ErpSecurityRole,
    ErpSecurityRolePermission, ErpSecurityUser, ErpSecurityUserRole, ErpSegregationRule,
    RawFileManifest, RawRecord, SourceSnapshot,
)

PAYROLL_TERMS = ("payroll", "salary", "wage")
HRM_TERMS = ("attendance", "leave", "shift", "employee", "human resource")


def role_code(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")


def permission_module(code: str, label: str | None = None) -> str:
    text = f"{code} {label or ''}".casefold()
    if any(term in text for term in PAYROLL_TERMS):
        return "payroll"
    if any(term in text for term in HRM_TERMS):
        return "hrm"
    prefix = re.split(r"[._]", code.casefold(), maxsplit=1)[0]
    return prefix or "other"


def _raw_records(session: Session, snapshot_id: int, entity: str) -> list[RawRecord]:
    return list(session.scalars(select(RawRecord).join(RawFileManifest).where(
        RawFileManifest.snapshot_id == snapshot_id, RawFileManifest.entity_type == entity,
        RawRecord.is_presentation_row.is_(False)).order_by(RawRecord.id)))


def build_security_controls(session: Session, snapshot_name: str) -> dict:
    snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == snapshot_name))
    if not snapshot:
        raise ValueError(f"Unknown snapshot: {snapshot_name}")
    user_records = _raw_records(session, snapshot.id, "user")
    matrix_records = _raw_records(session, snapshot.id, "role_permission_matrix")
    if not user_records or not matrix_records:
        raise RuntimeError("User and role permission evidence must be imported before security promotion")

    permission_catalog = {}
    matrix_by_role = {}
    for record in matrix_records:
        payload = record.payload or {}
        name = str(payload.get("role") or "").strip()
        matrix_by_role[name] = record
        for control in payload.get("controls", []):
            if not isinstance(control, dict) or not control.get("name"):
                continue
            value = control.get("value")
            if value in (None, "", "on", "1"):
                continue
            permission_catalog.setdefault(str(value), {"label": control.get("label"), "input_name": control.get("name")})
    user_role_names = {str((record.payload or {}).get("Role") or "").strip() for record in user_records}
    role_names = sorted((set(matrix_by_role) | user_role_names) - {""}, key=str.casefold)

    created = Counter()
    role_fields = ("snapshot_id", "role_code")
    roles = _cache(session, ErpSecurityRole, role_fields, snapshot.id)
    role_by_name = {}
    role_statuses = Counter()
    for name in role_names:
        matrix = matrix_by_role.get(name)
        status = "migration_locked_evidence" if matrix else "review_required_missing_matrix"
        key = (snapshot.id, role_code(name))
        role, was_created = _ensure(session, ErpSecurityRole, roles, key, role_fields,
            {"role_name": name, "source_raw_record_id": matrix.id if matrix else None,
             "migration_status": status, "assignment_enabled": False,
             "evidence": {"matrix_url": (matrix.payload or {}).get("url") if matrix else None,
                          "source_matrix_present": bool(matrix)}})
        role_by_name[name] = role
        created["roles"] += was_created
        role_statuses[status] += 1
    session.flush()

    permission_fields = ("snapshot_id", "permission_code")
    permissions = _cache(session, ErpSecurityPermission, permission_fields, snapshot.id)
    permission_by_code = {}
    permission_modes = Counter()
    for code in sorted(permission_catalog, key=str.casefold):
        item = permission_catalog[code]
        module = permission_module(code, item["label"])
        mode = "archival_only" if module == "payroll" else "draft_disabled"
        key = (snapshot.id, code)
        permission, was_created = _ensure(session, ErpSecurityPermission, permissions, key, permission_fields,
            {"label": item["label"], "module_code": module, "mode": mode,
             "grant_enabled": False, "evidence": {"source_input_name": item["input_name"]}})
        permission_by_code[code] = permission
        created["permissions"] += was_created
        permission_modes[mode] += 1
    session.flush()

    existing_role_permissions = {(row.role_id, row.permission_id): row for row in session.scalars(select(ErpSecurityRolePermission))}
    source_grants = 0
    archival_grants = 0
    for name, record in matrix_by_role.items():
        role = role_by_name[name]
        for control in (record.payload or {}).get("controls", []):
            if not isinstance(control, dict) or not control.get("checked"):
                continue
            code = str(control.get("value") or "")
            permission = permission_by_code.get(code)
            if not permission:
                continue
            key = (role.id, permission.id)
            values = {"source_granted": True, "target_granted": False,
                      "exclusion_reason": "Payroll excluded from operational ERP" if permission.mode == "archival_only" else "Target RBAC approval pending"}
            row = existing_role_permissions.get(key)
            if row:
                for field, expected in values.items():
                    if getattr(row, field) != expected:
                        raise RuntimeError(f"Immutable security mismatch: role permission {key} {field}")
            else:
                row = ErpSecurityRolePermission(role_id=role.id, permission_id=permission.id, **values)
                session.add(row)
                existing_role_permissions[key] = row
                created["role_permissions"] += 1
            source_grants += 1
            archival_grants += permission.mode == "archival_only"

    user_fields = ("snapshot_id", "source_user_id")
    users = _cache(session, ErpSecurityUser, user_fields, snapshot.id)
    user_map = {}
    for record in user_records:
        payload = record.payload or {}
        key = (snapshot.id, record.id)
        user, was_created = _ensure(session, ErpSecurityUser, users, key, user_fields,
            {"username": payload.get("Username"), "display_name": payload.get("Name"),
             "email": payload.get("Email"), "source_role_name": payload.get("Role"),
             "account_status": "disabled_pending_identity_and_scope_approval",
             "password_material_copied": False, "authentication_enabled": False,
             "evidence": {"source_action_markup_ignored": bool(payload.get("Action")),
                          "passwords_available_in_export": False}})
        user_map[record.id] = user
        created["users"] += was_created
    session.flush()

    existing_user_roles = {(row.user_id, row.role_id): row for row in session.scalars(select(ErpSecurityUserRole))}
    for record in user_records:
        user = user_map[record.id]
        source_role = str((record.payload or {}).get("Role") or "").strip()
        role = role_by_name.get(source_role)
        if not role:
            raise RuntimeError(f"User source role was not preserved: {source_role}")
        key = (user.id, role.id)
        row = existing_user_roles.get(key)
        if row:
            if row.assignment_enabled or not row.source_observed:
                raise RuntimeError(f"Unsafe user-role assignment state for {key}")
        else:
            session.add(ErpSecurityUserRole(user_id=user.id, role_id=role.id,
                                            source_observed=True, assignment_enabled=False))
            created["user_roles"] += 1

    scope_fields = ("snapshot_id", "user_id")
    scopes = _cache(session, ErpSecurityLocationScope, scope_fields, snapshot.id)
    for user in user_map.values():
        key = (snapshot.id, user.id)
        _, was_created = _ensure(session, ErpSecurityLocationScope, scopes, key, scope_fields,
            {"location_id": None, "scope_mode": "deny_all_pending_assignment", "access_enabled": False,
             "evidence": {"reason": "source user export has no deterministic location assignment"}})
        created["location_scopes"] += was_created

    proposed_role_bindings = {
        "data_owner": "Manager", "finance_controller": "Accounts",
        "system_administrator": "Admin", "inventory_controller": "Stock Transfer Coordinator",
    }
    existing_bindings = {row.approval_step_id: row for row in session.scalars(select(ErpApprovalRoleBinding))}
    steps = list(session.scalars(select(ErpApprovalStep)))
    for step in steps:
        candidate_name = proposed_role_bindings.get(step.role_code)
        candidate = role_by_name.get(candidate_name or "")
        values = {"target_role_id": candidate.id if candidate else None,
                  "binding_status": "proposed_requires_approval" if candidate else "review_required_no_candidate",
                  "assignment_enabled": False,
                  "evidence": {"logical_role": step.role_code, "candidate_source_role": candidate_name,
                               "warning": "No user approver assigned"}}
        row = existing_bindings.get(step.id)
        if row:
            for field, expected in values.items():
                if getattr(row, field) != expected:
                    raise RuntimeError(f"Immutable approval binding mismatch: step {step.id} {field}")
        else:
            session.add(ErpApprovalRoleBinding(approval_step_id=step.id, **values))
            created["approval_bindings"] += 1

    sod_specs = {
        "SUPPLIER_MAKER_CHECKER": ("Supplier maker/checker", "supplier.create_or_update", "supplier.approve"),
        "PURCHASE_MAKER_CHECKER": ("Purchase maker/checker", "purchase.create_or_update", "purchase.approve_or_post"),
        "SALES_CREDIT_CONTROL": ("Sales credit/return separation", "sale.create_or_return", "sale.credit_approve_or_post"),
        "PAYMENT_RECONCILIATION": ("Payment/reconciliation separation", "payment.create", "bank.reconcile"),
        "ACCESS_ADMINISTRATION": ("Access administration separation", "access.manage", "access.approve"),
    }
    for code, (name, maker, checker) in sod_specs.items():
        _, was_created = _add_once(session, ErpSegregationRule,
            {"snapshot_id": snapshot.id, "rule_code": code},
            {"rule_name": name, "maker_capability": maker, "checker_capability": checker,
             "status": "draft_pending_approval", "enforcement_enabled": False})
        created["segregation_rules"] += was_created

    policy_specs = {
        "AUTHENTICATION_BASELINE": ("Authentication baseline", {
            "mfa_required_for_privileged_roles": True, "password_reset_required": True,
            "source_passwords_imported": False, "lockout_attempts_proposed": 5}),
        "SESSION_CONTROL": ("Session control", {
            "idle_timeout_minutes_proposed": 30, "absolute_timeout_minutes_proposed": 720,
            "concurrent_session_policy": "requires_business_decision"}),
        "AUDIT_RETENTION": ("Security audit retention", {
            "append_only_required": True, "retention_period": "requires_legal_and_business_decision"}),
    }
    for code, (name, config) in policy_specs.items():
        _, was_created = _add_once(session, ErpSecurityPolicy,
            {"snapshot_id": snapshot.id, "policy_code": code},
            {"policy_name": name, "status": "draft_pending_approval",
             "enforcement_enabled": False, "configuration": config})
        created["security_policies"] += was_created

    gate_specs = {
        "IDENTITY_VERIFICATION": ("User identity verification and password reset", len(users), {}),
        "LOCATION_SCOPE": ("User branch/location assignment", len(scopes), {}),
        "ROLE_MATRIX_APPROVAL": ("Role permission matrix approval", len(roles), {}),
        "MISSING_ADMIN_MATRIX": ("Admin source matrix recovery or replacement", sum(r.migration_status == "review_required_missing_matrix" for r in roles.values()), {}),
        "APPROVAL_BINDINGS": ("Approval role and user assignment", len(steps), {"user_assignments": 0}),
        "SEGREGATION_OF_DUTIES": ("Segregation-of-duties approval", len(sod_specs), {}),
        "SECURITY_POLICY_APPROVAL": ("Authentication/session/audit policy approval", len(policy_specs), {}),
        "HR_PAYROLL_EXCLUSION": ("HRM/payroll operational exclusion", 0,
                                  {"archival_permissions": permission_modes["archival_only"], "operational_grants": 0}),
    }
    gates = {}
    for code, (name, issues, evidence) in gate_specs.items():
        gate, was_created = _add_once(session, ErpSecurityActivationGate,
            {"snapshot_id": snapshot.id, "gate_code": code},
            {"gate_name": name, "issue_count": issues,
             "gate_status": "blocked" if issues else "ready_disabled",
             "activation_enabled": False, "evidence": evidence})
        created["activation_gates"] += was_created
        gates[code] = {"status": gate.gate_status, "issues": gate.issue_count}

    event_key = f"security-controls:{len(users)}:{len(roles)}:{len(permissions)}:{source_grants}"
    _, was_created = _add_once(session, ErpAuditEvent,
        {"snapshot_id": snapshot.id, "event_key": event_key},
        {"event_type": "security_controls_registered", "actor_type": "migration_service",
         "details": {"users": len(users), "roles": len(roles), "permissions": len(permissions),
                     "source_grants": source_grants, "archival_source_grants": archival_grants,
                     "password_material_copied": False, "authentication_enabled": False,
                     "source_mutated": False}})
    created["audit_events"] += was_created
    session.commit()

    active = {
        "authenticated_users": session.scalar(select(func.count(ErpSecurityUser.id)).where(ErpSecurityUser.snapshot_id == snapshot.id, ErpSecurityUser.authentication_enabled.is_(True))) or 0,
        "granted_permissions": session.scalar(select(func.count(ErpSecurityRolePermission.id)).where(ErpSecurityRolePermission.target_granted.is_(True))) or 0,
        "active_scopes": session.scalar(select(func.count(ErpSecurityLocationScope.id)).where(ErpSecurityLocationScope.snapshot_id == snapshot.id, ErpSecurityLocationScope.access_enabled.is_(True))) or 0,
        "active_gates": session.scalar(select(func.count(ErpSecurityActivationGate.id)).where(ErpSecurityActivationGate.snapshot_id == snapshot.id, ErpSecurityActivationGate.activation_enabled.is_(True))) or 0,
    }
    return {"snapshot": snapshot.name, "users": len(users), "roles": len(roles),
            "role_status": dict(role_statuses), "permissions": len(permissions),
            "permission_mode": dict(permission_modes), "source_grants": source_grants,
            "archival_source_grants": archival_grants, "target_grants": active["granted_permissions"],
            "user_roles": len(user_records), "location_scopes": len(scopes),
            "approval_bindings": len(steps), "segregation_rules": len(sod_specs),
            "security_policies": len(policy_specs), "activation_gates": gates,
            "active_controls": active, "new_records": dict(created)}
