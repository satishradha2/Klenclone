from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .operational import OperationalAuditEvent, OperationalBase, utc_now
from .role_matrix import MAKER_APPROVER_PAIRS, ROLE_MATRIX, permissions_for_roles


class OperationalUser(OperationalBase):
    """Target-ERP access profile; authentication secrets remain independently provisioned."""

    __tablename__ = "operational_users"
    __table_args__ = (UniqueConstraint("login_name", name="uq_operational_user_login"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    login_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    mfa_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class OperationalRoleAssignment(OperationalBase):
    __tablename__ = "operational_role_assignments"
    __table_args__ = (UniqueConstraint(
        "user_id", "role_code", "company_code", "branch_code", "warehouse_code", "van_code", "effective_from",
        name="uq_operational_role_scope",
    ),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("operational_users.id"), nullable=False, index=True)
    role_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    company_code: Mapped[str] = mapped_column(String(40), nullable=False, default="ASAS")
    branch_code: Mapped[str | None] = mapped_column(String(80), index=True)
    warehouse_code: Mapped[str | None] = mapped_column(String(80), index=True)
    van_code: Mapped[str | None] = mapped_column(String(80), index=True)
    approval_limit_aed: Mapped[str | None] = mapped_column(String(30))
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    assigned_by: Mapped[str] = mapped_column(String(200), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


SENSITIVE_ROLES = {
    "administrator", "security_administrator", "chief_financial_officer", "finance_controller",
    "finance_maker", "finance_approver", "treasury", "tax_officer", "procurement_manager",
    "hr_manager",
}

ROLE_DEPARTMENTS = {
    "administrator": "Administration", "security_administrator": "Administration",
    "integration_administrator": "Administration", "auditor": "Governance",
    "executive_read_only": "Executive", "chief_financial_officer": "Finance",
    "finance_controller": "Finance", "finance_maker": "Finance", "finance_approver": "Finance",
    "accounts_receivable": "Finance", "accounts_payable": "Finance", "treasury": "Finance",
    "tax_officer": "Finance", "fixed_asset_accountant": "Finance",
    "procurement_requester": "Purchasing", "buyer": "Purchasing",
    "procurement_manager": "Purchasing", "goods_receipt_clerk": "Purchasing",
    "warehouse_supervisor": "Inventory", "inventory_controller": "Inventory",
    "quality_controller": "Inventory", "logistics_manager": "Logistics",
    "sales_user": "Sales", "sales_manager": "Sales", "pos_cashier": "Sales",
    "credit_controller": "Sales", "returns_officer": "Sales",
    "branch_manager": "Operations", "van_user": "Van sales", "van_supervisor": "Van sales",
    "hr_manager": "HRM", "hr_officer": "HRM", "employee_self_service": "HRM",
}


def _audit(session: Session, *, actor: str, event_type: str, resource_key: str, detail: str) -> None:
    session.add(OperationalAuditEvent(
        event_key=str(uuid.uuid4()), event_type=event_type, actor=actor,
        resource_key=resource_key, detail=detail,
    ))


def _user(session: Session, user_key: str) -> OperationalUser:
    user = session.scalar(select(OperationalUser).where(OperationalUser.user_key == user_key))
    if user is None:
        raise ValueError("ERP user profile was not found")
    return user


def initialize_access_profiles(session: Session, provisioned_users, *, actor: str = "access_control") -> int:
    """Register only public identity metadata; never copy password hashes into ERP access tables."""
    created = 0
    principals = list(provisioned_users)
    for principal in principals:
        login = principal.username.strip()
        existing = session.scalar(select(OperationalUser).where(OperationalUser.login_name == login))
        if existing is None:
            session.add(OperationalUser(
                user_key=str(uuid.uuid4()), login_name=login,
                display_name=login.replace("-", " ").title(), status="active",
                mfa_required=bool(set(principal.roles) & SENSITIVE_ROLES),
            ))
            created += 1
    session.flush()
    bootstrap_assignments = 0
    for principal in principals:
        if "operations_administrator" not in principal.roles:
            continue
        user = session.scalar(select(OperationalUser).where(OperationalUser.login_name == principal.username.strip()))
        existing = session.scalar(select(OperationalRoleAssignment.id).where(
            OperationalRoleAssignment.user_id == user.id,
            OperationalRoleAssignment.role_code == "administrator",
            OperationalRoleAssignment.company_code == "ASAS",
        ))
        if existing is None:
            session.add(OperationalRoleAssignment(
                user_id=user.id, role_code="administrator", company_code="ASAS",
                effective_from=date.today(), assigned_by=actor,
            ))
            user.mfa_required = True
            bootstrap_assignments += 1
    if created or bootstrap_assignments:
        _audit(session, actor=actor, event_type="access.users_registered", resource_key="ASAS",
               detail=(f"Registered {created} independently provisioned ERP login profile(s); "
                       f"bootstrapped {bootstrap_assignments} administrator assignment(s); no secrets copied."))
        session.commit()
    return created


def create_user_profile(session: Session, *, actor: str, login_name: str, display_name: str,
                        identity_ready: bool) -> OperationalUser:
    login_name = login_name.strip()
    display_name = display_name.strip()
    if session.scalar(select(OperationalUser).where(OperationalUser.login_name == login_name)):
        raise ValueError("An ERP user profile already exists for this login")
    user = OperationalUser(
        user_key=str(uuid.uuid4()), login_name=login_name, display_name=display_name,
        status="active" if identity_ready else "pending_provisioning", mfa_required=False,
    )
    session.add(user)
    session.flush()
    _audit(session, actor=actor, event_type="access.user_created", resource_key=user.user_key,
           detail=f"login={login_name}; status={user.status}; authentication secret not stored here")
    session.commit()
    return user


def set_user_status(session: Session, *, actor: str, user_key: str, status: str,
                    identity_ready: bool) -> OperationalUser:
    user = _user(session, user_key)
    if user.login_name.casefold() == actor.casefold() and status != "active":
        raise ValueError("You cannot suspend or deactivate your own access profile")
    if status == "active" and not identity_ready:
        raise ValueError("This login must be independently provisioned before it can be activated")
    if status not in {"active", "suspended", "inactive", "pending_provisioning"}:
        raise ValueError("Unsupported user status")
    previous = user.status
    user.status = status
    _audit(session, actor=actor, event_type="access.user_status_changed", resource_key=user.user_key,
           detail=f"status={previous}->{status}")
    session.commit()
    return user


def _scope_exists(session: Session, company_code: str, branch_code: str | None,
                  warehouse_code: str | None, van_code: str | None) -> None:
    from .enterprise_setup import OperationalBranch, OperationalCompanyProfile, OperationalVan, OperationalWarehouse

    if session.scalar(select(OperationalCompanyProfile.id).where(
            OperationalCompanyProfile.company_code == company_code)) is None:
        raise ValueError("Company scope was not found")
    if branch_code and session.scalar(select(OperationalBranch.id).where(
            OperationalBranch.company_code == company_code,
            OperationalBranch.branch_code == branch_code)) is None:
        raise ValueError("Branch scope was not found")
    if warehouse_code:
        warehouse = session.scalar(select(OperationalWarehouse).where(
            OperationalWarehouse.company_code == company_code,
            OperationalWarehouse.warehouse_code == warehouse_code))
        if warehouse is None or (branch_code and warehouse.branch_code != branch_code):
            raise ValueError("Warehouse scope was not found under the selected branch")
    if van_code:
        van = session.scalar(select(OperationalVan).where(
            OperationalVan.company_code == company_code, OperationalVan.van_code == van_code))
        if van is None or (branch_code and van.assigned_branch_code != branch_code):
            raise ValueError("Van scope was not found under the selected branch")


def _overlaps(left: OperationalRoleAssignment, *, company_code: str, branch_code: str | None,
              warehouse_code: str | None, van_code: str | None,
              effective_from: date, effective_to: date | None) -> bool:
    if left.company_code != company_code:
        return False
    for old, new in ((left.branch_code, branch_code), (left.warehouse_code, warehouse_code), (left.van_code, van_code)):
        if old is not None and new is not None and old != new:
            return False
    return left.effective_from <= (effective_to or date.max) and effective_from <= (left.effective_to or date.max)


def assign_role(session: Session, *, actor: str, user_key: str, role_code: str,
                company_code: str, branch_code: str | None, warehouse_code: str | None,
                van_code: str | None, approval_limit_aed: Decimal | None,
                effective_from: date, effective_to: date | None) -> OperationalRoleAssignment:
    user = _user(session, user_key)
    role_code = role_code.strip().lower()
    company_code = company_code.strip().upper()
    branch_code = branch_code.strip().upper() if branch_code else None
    warehouse_code = warehouse_code.strip().upper() if warehouse_code else None
    van_code = van_code.strip().upper() if van_code else None
    if role_code not in ROLE_MATRIX:
        raise ValueError("Unknown ERP role")
    if effective_to and effective_to < effective_from:
        raise ValueError("Effective-to date cannot be before effective-from date")
    if approval_limit_aed is not None:
        try:
            approval_limit_aed = Decimal(approval_limit_aed).quantize(Decimal("0.01"))
        except InvalidOperation as exc:
            raise ValueError("Approval limit must be a valid AED amount") from exc
        if approval_limit_aed < 0:
            raise ValueError("Approval limit cannot be negative")
        if not any(permission.endswith(".approve") for permission in ROLE_MATRIX[role_code]):
            raise ValueError("Approval limits can only be set on approving roles")
    _scope_exists(session, company_code, branch_code, warehouse_code, van_code)
    existing = session.scalars(select(OperationalRoleAssignment).where(
        OperationalRoleAssignment.user_id == user.id)).all()
    opposite_roles = {right if role_code == left else left for left, right in MAKER_APPROVER_PAIRS
                      if role_code in {left, right}}
    for assignment in existing:
        if (assignment.role_code == role_code and assignment.company_code == company_code
                and assignment.branch_code == branch_code and assignment.warehouse_code == warehouse_code
                and assignment.van_code == van_code and assignment.effective_from == effective_from):
            raise ValueError("This scoped role assignment already exists")
        if assignment.role_code in opposite_roles and _overlaps(
                assignment, company_code=company_code, branch_code=branch_code,
                warehouse_code=warehouse_code, van_code=van_code,
                effective_from=effective_from, effective_to=effective_to):
            raise ValueError("Maker and approver roles cannot overlap for the same user, scope, and dates")
    assignment = OperationalRoleAssignment(
        user_id=user.id, role_code=role_code, company_code=company_code,
        branch_code=branch_code, warehouse_code=warehouse_code, van_code=van_code,
        approval_limit_aed=str(approval_limit_aed) if approval_limit_aed is not None else None,
        effective_from=effective_from, effective_to=effective_to, assigned_by=actor,
    )
    session.add(assignment)
    if role_code in SENSITIVE_ROLES:
        user.mfa_required = True
    try:
        session.flush()
    except Exception as exc:
        session.rollback()
        raise ValueError("This scoped role assignment already exists") from exc
    _audit(session, actor=actor, event_type="access.role_assigned", resource_key=user.user_key,
           detail=f"role={role_code}; company={company_code}; branch={branch_code or '*'}; "
                  f"warehouse={warehouse_code or '*'}; van={van_code or '*'}; from={effective_from}; to={effective_to or '*'}")
    session.commit()
    return assignment


def revoke_role(session: Session, *, actor: str, user_key: str, assignment_id: int) -> None:
    user = _user(session, user_key)
    assignment = session.scalar(select(OperationalRoleAssignment).where(
        OperationalRoleAssignment.id == assignment_id, OperationalRoleAssignment.user_id == user.id))
    if assignment is None:
        raise ValueError("Role assignment was not found")
    if user.login_name.casefold() == actor.casefold() and assignment.role_code in {
            "administrator", "security_administrator"}:
        raise ValueError("You cannot remove your own access-administration role")
    detail = (f"role={assignment.role_code}; company={assignment.company_code}; "
              f"branch={assignment.branch_code or '*'}; warehouse={assignment.warehouse_code or '*'}; "
              f"van={assignment.van_code or '*'}")
    session.delete(assignment)
    remaining = session.scalars(select(OperationalRoleAssignment.role_code).where(
        OperationalRoleAssignment.user_id == user.id, OperationalRoleAssignment.id != assignment_id)).all()
    user.mfa_required = bool(set(remaining) & SENSITIVE_ROLES)
    _audit(session, actor=actor, event_type="access.role_revoked", resource_key=user.user_key, detail=detail)
    session.commit()


def effective_principal(session: Session, principal):
    user = session.scalar(select(OperationalUser).where(OperationalUser.login_name == principal.username))
    if user is None:
        return principal
    if user.status != "active":
        return None
    today = date.today()
    assignments = session.scalars(select(OperationalRoleAssignment).where(
        OperationalRoleAssignment.user_id == user.id,
        OperationalRoleAssignment.effective_from <= today,
    )).all()
    assignments = [row for row in assignments if row.effective_to is None or row.effective_to >= today]
    assigned_roles = {row.role_code for row in assignments}
    roles = set(principal.roles) | assigned_roles
    permissions = set(principal.permissions) | permissions_for_roles(assigned_roles)
    locations = set(principal.allowed_locations)
    for row in assignments:
        locations.update(value for value in (row.branch_code, row.warehouse_code, row.van_code) if value)
        if (not any((row.branch_code, row.warehouse_code, row.van_code))
                and row.role_code not in {"administrator", "security_administrator",
                                          "integration_administrator", "auditor", "executive_read_only"}):
            locations.add("*")
    return replace(principal, roles=tuple(sorted(roles)), permissions=tuple(sorted(permissions)),
                   allowed_locations=tuple(sorted(locations)))


def access_control_payload(session: Session, *, provisioned_logins: set[str]) -> dict:
    today = date.today()
    users = session.scalars(select(OperationalUser).order_by(OperationalUser.display_name, OperationalUser.login_name)).all()
    assignments = session.scalars(select(OperationalRoleAssignment).order_by(
        OperationalRoleAssignment.user_id, OperationalRoleAssignment.role_code,
        OperationalRoleAssignment.effective_from)).all()
    by_user: dict[int, list[OperationalRoleAssignment]] = {}
    for row in assignments:
        by_user.setdefault(row.user_id, []).append(row)
    role_rows = [{
        "code": code, "name": code.replace("_", " ").title(),
        "department": ROLE_DEPARTMENTS.get(code, "Other"),
        "permissions": sorted(permissions), "mfa_required": code in SENSITIVE_ROLES,
    } for code, permissions in sorted(ROLE_MATRIX.items(), key=lambda item: (ROLE_DEPARTMENTS.get(item[0], "Other"), item[0]))]
    return {
        "users": [{
            "user_key": user.user_key, "login_name": user.login_name, "display_name": user.display_name,
            "status": user.status, "mfa_required": user.mfa_required,
            "identity_ready": user.login_name.casefold() in provisioned_logins,
            "assignments": [{
                "id": row.id, "role_code": row.role_code, "role_name": row.role_code.replace("_", " ").title(),
                "company_code": row.company_code, "branch_code": row.branch_code,
                "warehouse_code": row.warehouse_code, "van_code": row.van_code,
                "approval_limit_aed": row.approval_limit_aed,
                "effective_from": row.effective_from, "effective_to": row.effective_to,
                "assigned_by": row.assigned_by, "assigned_at": row.assigned_at,
                "currently_effective": row.effective_from <= today and (row.effective_to is None or row.effective_to >= today),
            } for row in by_user.get(user.id, [])],
        } for user in users],
        "roles": role_rows,
        "controls": {
            "multiple_roles_per_user": True, "scoped_assignments": True,
            "maker_approver_overlap_blocked": True, "passwords_stored_here": False,
            "role_count": len(role_rows), "user_count": len(users), "assignment_count": len(assignments),
        },
    }
