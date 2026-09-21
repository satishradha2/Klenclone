from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .operational import OperationalAuditEvent, OperationalBase, utc_now


class OperationalCompanyProfile(OperationalBase):
    """Target-ERP company setup; deliberately separate from immutable source evidence."""

    __tablename__ = "operational_company_profiles"
    __table_args__ = (
        UniqueConstraint("company_code", name="uq_operational_company_profile_code"),
        CheckConstraint("status IN ('setup_pending','active','inactive')", name="ck_operational_company_profile_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    company_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    legal_name: Mapped[str] = mapped_column(String(500), nullable=False)
    functional_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="AED")
    accounting_framework: Mapped[str] = mapped_column(String(40), nullable=False, default="full_ifrs")
    fiscal_year_start_month: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    vat_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    corporate_tax_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    einvoicing_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="setup_pending")
    profile_fields: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalBranch(OperationalBase):
    __tablename__ = "operational_branches"
    __table_args__ = (
        UniqueConstraint("company_code", "branch_code", name="uq_operational_branch_company_code"),
        CheckConstraint("status IN ('planned','pending_approval','active','inactive')", name="ck_operational_branch_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    branch_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    company_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    branch_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="planned")
    is_primary_branch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False, default="enterprise_setup")
    approved_by: Mapped[str | None] = mapped_column(String(200))
    approval_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalWarehouse(OperationalBase):
    __tablename__ = "operational_warehouses"
    __table_args__ = (
        UniqueConstraint("company_code", "warehouse_code", name="uq_operational_warehouse_company_code"),
        CheckConstraint("warehouse_type IN ('available','returns','quarantine','in_transit')", name="ck_operational_warehouse_type"),
        CheckConstraint("status IN ('planned','active','inactive')", name="ck_operational_warehouse_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    warehouse_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    company_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    branch_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    warehouse_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    warehouse_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="planned")
    created_by: Mapped[str] = mapped_column(String(200), nullable=False, default="enterprise_setup")
    approved_by: Mapped[str | None] = mapped_column(String(200))
    approval_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalVan(OperationalBase):
    __tablename__ = "operational_vans"
    __table_args__ = (
        UniqueConstraint("company_code", "van_code", name="uq_operational_van_company_code"),
        CheckConstraint("status IN ('planned','active','inactive')", name="ck_operational_van_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    van_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    company_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    van_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    assigned_branch_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="planned")
    created_by: Mapped[str] = mapped_column(String(200), nullable=False, default="enterprise_setup")
    approved_by: Mapped[str | None] = mapped_column(String(200))
    approval_note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalFinancePolicy(OperationalBase):
    __tablename__ = "operational_finance_policies"
    __table_args__ = (UniqueConstraint("company_code", "policy_code", name="uq_operational_finance_policy"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    company_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    policy_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


def _add_once(session: Session, model, filters: dict, values: dict) -> bool:
    if session.scalar(select(model).filter_by(**filters)) is not None:
        return False
    session.add(model(**filters, **values))
    return True


def initialize_enterprise_setup(session: Session, *, actor: str = "enterprise_setup") -> dict:
    """Seed only decisions explicitly approved for the target ERP; never touch clone tables."""

    company_code = "ASAS"
    created = 0
    created += _add_once(session, OperationalCompanyProfile, {"company_code": company_code}, {
        "company_key": str(uuid.uuid4()), "legal_name": "Asas General Trading LLC",
        "functional_currency": "AED", "accounting_framework": "full_ifrs",
        "fiscal_year_start_month": 1, "vat_enabled": True, "corporate_tax_enabled": True,
        "einvoicing_enabled": True, "status": "setup_pending",
        "profile_fields": json.dumps({"legal_details": "enter_later", "tax_registration": "enter_later", "logo": "enter_later"}),
    })
    created += _add_once(session, OperationalBranch, {"company_code": company_code, "branch_code": "MAIN"}, {
        "branch_key": str(uuid.uuid4()), "name": "Main branch", "status": "planned", "is_primary_branch": True,
        "created_by": actor,
    })
    for code, name, warehouse_type in (
        ("MAIN-AVAILABLE", "Main / Available", "available"),
        ("MAIN-RETURNS", "Main / Returns", "returns"),
        ("MAIN-QUARANTINE", "Main / Damaged and quarantine", "quarantine"),
        ("MAIN-IN-TRANSIT", "Main / In transit", "in_transit"),
    ):
        created += _add_once(session, OperationalWarehouse, {"company_code": company_code, "warehouse_code": code}, {
            "warehouse_key": str(uuid.uuid4()), "branch_code": "MAIN", "name": name,
            "warehouse_type": warehouse_type, "status": "planned", "created_by": actor,
        })
    for code in ("DXB", "RAK", "SHJ"):
        created += _add_once(session, OperationalVan, {"company_code": company_code, "van_code": code}, {
            "van_key": str(uuid.uuid4()), "assigned_branch_code": "MAIN", "name": f"{code} van", "status": "planned", "created_by": actor,
        })
    policies = {
        "document_locking": {"posted_documents": "locked", "correction": "approved_credit_debit_or_reversal"},
        "inventory_costing": {"method": "FIFO", "negative_stock": "blocked", "landed_cost": "approval_required"},
        "security": {"mfa_required_roles": ["administrator", "finance", "approver"], "self_approval": "prohibited"},
        "fiscal_close": {"vat_and_year_close": "locked", "reopen": "finance_controller_approval"},
        "einvoicing": {"mode": "structured_provider_ready", "accredited_service_provider": "select_before_go_live"},
    }
    for code, value in policies.items():
        created += _add_once(session, OperationalFinancePolicy, {"company_code": company_code, "policy_code": code}, {
            "policy_key": str(uuid.uuid4()), "value_json": json.dumps(value, sort_keys=True),
        })
    if created:
        session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="enterprise_setup.seeded",
            actor=actor, resource_key=company_code,
            detail="Target ERP company, branch, warehouse, van and Full-IFRS policies seeded; BizModo source untouched."))
        session.commit()
    return {"company_code": company_code, "created_records": created}


def enterprise_setup_payload(session: Session) -> dict:
    company = session.scalar(select(OperationalCompanyProfile).where(OperationalCompanyProfile.company_code == "ASAS"))
    if not company:
        return {"configured": False}
    policies = session.scalars(select(OperationalFinancePolicy).where(
        OperationalFinancePolicy.company_code == company.company_code).order_by(OperationalFinancePolicy.policy_code)).all()
    return {
        "configured": True,
        "company": {"code": company.company_code, "legal_name": company.legal_name,
                    "functional_currency": company.functional_currency, "accounting_framework": company.accounting_framework,
                    "fiscal_year_start_month": company.fiscal_year_start_month, "status": company.status,
                    "profile_fields": json.loads(company.profile_fields)},
        "branches": [{"code": row.branch_code, "name": row.name, "status": row.status,
                      "is_primary": row.is_primary_branch, "revision": row.revision,
                      "created_by": row.created_by, "approved_by": row.approved_by} for row in session.scalars(select(OperationalBranch).where(
                          OperationalBranch.company_code == company.company_code).order_by(OperationalBranch.branch_code))],
        "warehouses": [{"code": row.warehouse_code, "branch_code": row.branch_code, "name": row.name,
                        "type": row.warehouse_type, "status": row.status, "revision": row.revision,
                        "created_by": row.created_by, "approved_by": row.approved_by} for row in session.scalars(select(OperationalWarehouse).where(
                            OperationalWarehouse.company_code == company.company_code).order_by(OperationalWarehouse.warehouse_code))],
        "vans": [{"code": row.van_code, "name": row.name, "assigned_branch_code": row.assigned_branch_code,
                  "status": row.status, "revision": row.revision, "created_by": row.created_by,
                  "approved_by": row.approved_by} for row in session.scalars(select(OperationalVan).where(
                      OperationalVan.company_code == company.company_code).order_by(OperationalVan.van_code))],
        "finance_policies": {row.policy_code: json.loads(row.value_json) for row in policies},
    }


def _audit(session: Session, *, actor: str, event_type: str, resource_key: str, detail: str) -> None:
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=event_type,
        actor=actor, resource_key=resource_key, detail=detail))


def update_company_profile(session: Session, *, actor: str, legal_name: str | None,
                           profile_updates: dict[str, str | None]) -> dict:
    company = session.scalar(select(OperationalCompanyProfile).where(OperationalCompanyProfile.company_code == "ASAS"))
    if not company:
        raise ValueError("Enterprise company setup is unavailable")
    profile = json.loads(company.profile_fields)
    for key, value in profile_updates.items():
        if value is not None:
            profile[key] = value.strip() or "enter_later"
    if legal_name is not None:
        company.legal_name = legal_name.strip()
    company.profile_fields = json.dumps(profile, sort_keys=True)
    company.updated_at = utc_now()
    _audit(session, actor=actor, event_type="enterprise_setup.company_profile_updated", resource_key=company.company_code,
           detail="Target-ERP company profile updated; preserved BizModo company evidence was not changed.")
    session.commit()
    return enterprise_setup_payload(session)


def add_branch(session: Session, *, actor: str, branch_code: str, name: str) -> dict:
    company_code = "ASAS"
    branch_code = branch_code.strip().upper()
    if session.scalar(select(OperationalBranch).where(OperationalBranch.company_code == company_code,
                                                       OperationalBranch.branch_code == branch_code)):
        raise ValueError("A branch with this code already exists")
    session.add(OperationalBranch(branch_key=str(uuid.uuid4()), company_code=company_code,
        branch_code=branch_code, name=name.strip(), status="pending_approval", is_primary_branch=False, created_by=actor))
    _audit(session, actor=actor, event_type="enterprise_setup.branch_created", resource_key=branch_code,
           detail="Future target-ERP branch created pending administrator activation.")
    session.commit()
    return enterprise_setup_payload(session)


def add_warehouse(session: Session, *, actor: str, branch_code: str, warehouse_code: str,
                  name: str, warehouse_type: str) -> dict:
    company_code = "ASAS"
    branch_code, warehouse_code = branch_code.strip().upper(), warehouse_code.strip().upper()
    if not session.scalar(select(OperationalBranch).where(OperationalBranch.company_code == company_code,
                                                           OperationalBranch.branch_code == branch_code)):
        raise ValueError("Assign the warehouse to an existing ERP branch")
    if session.scalar(select(OperationalWarehouse).where(OperationalWarehouse.company_code == company_code,
                                                          OperationalWarehouse.warehouse_code == warehouse_code)):
        raise ValueError("A warehouse with this code already exists")
    session.add(OperationalWarehouse(warehouse_key=str(uuid.uuid4()), company_code=company_code,
        branch_code=branch_code, warehouse_code=warehouse_code, name=name.strip(),
        warehouse_type=warehouse_type, status="planned", created_by=actor))
    _audit(session, actor=actor, event_type="enterprise_setup.warehouse_created", resource_key=warehouse_code,
           detail=f"Target-ERP {warehouse_type} warehouse created for {branch_code}; activation remains controlled.")
    session.commit()
    return enterprise_setup_payload(session)


def add_van(session: Session, *, actor: str, van_code: str, name: str,
            assigned_branch_code: str) -> dict:
    company_code = "ASAS"
    van_code, assigned_branch_code = van_code.strip().upper(), assigned_branch_code.strip().upper()
    if not session.scalar(select(OperationalBranch).where(OperationalBranch.company_code == company_code,
                                                           OperationalBranch.branch_code == assigned_branch_code)):
        raise ValueError("Assign the van to an existing ERP branch")
    if session.scalar(select(OperationalVan).where(OperationalVan.company_code == company_code,
                                                    OperationalVan.van_code == van_code)):
        raise ValueError("A van with this code already exists")
    session.add(OperationalVan(van_key=str(uuid.uuid4()), company_code=company_code, van_code=van_code,
        assigned_branch_code=assigned_branch_code, name=name.strip(), status="planned", created_by=actor))
    _audit(session, actor=actor, event_type="enterprise_setup.van_created", resource_key=van_code,
           detail=f"Target-ERP van assigned to {assigned_branch_code}; activation remains controlled.")
    session.commit()
    return enterprise_setup_payload(session)


_APPROVABLE_MODELS = {
    "branch": (OperationalBranch, "branch_code"),
    "warehouse": (OperationalWarehouse, "warehouse_code"),
    "van": (OperationalVan, "van_code"),
}


def transition_operating_unit(session: Session, *, actor: str, unit_kind: str, unit_code: str,
                              action: str, expected_revision: int, note: str) -> dict:
    """Move an ERP operating unit through request/approve/reject without source mutation."""

    model, code_field = _APPROVABLE_MODELS.get(unit_kind, (None, None))
    if model is None:
        raise ValueError("Unknown operating-unit type")
    unit_code = unit_code.strip().upper()
    row = session.scalar(select(model).where(model.company_code == "ASAS", getattr(model, code_field) == unit_code))
    if not row:
        raise ValueError("Operating unit was not found")
    if row.revision != expected_revision:
        raise RuntimeError("This operating unit was changed by another user; refresh before deciding")
    if action == "request_activation":
        if row.status != "planned":
            raise ValueError("Only planned operating units can be submitted for approval")
        row.status = "pending_approval"
        row.created_by = actor
        event_type = "enterprise_setup.activation_requested"
    elif action in {"approve", "reject"}:
        if row.status != "pending_approval":
            raise ValueError("Only pending operating units can be approved or rejected")
        if row.created_by == actor:
            raise ValueError("The person who requested activation cannot approve or reject it")
        if action == "approve":
            if unit_kind in {"warehouse", "van"}:
                branch_code = row.branch_code if unit_kind == "warehouse" else row.assigned_branch_code
                branch = session.scalar(select(OperationalBranch).where(
                    OperationalBranch.company_code == "ASAS", OperationalBranch.branch_code == branch_code))
                if not branch or branch.status != "active":
                    raise ValueError("Activate the assigned branch before activating this warehouse or van")
            row.status = "active"
            event_type = "enterprise_setup.activation_approved"
        else:
            row.status = "inactive"
            event_type = "enterprise_setup.activation_rejected"
        row.approved_by = actor
        row.approval_note = note
    else:
        raise ValueError("Unknown approval action")
    row.revision += 1
    _audit(session, actor=actor, event_type=event_type, resource_key=f"{unit_kind}:{unit_code}",
           detail=f"status={row.status}; note={note}")
    session.commit()
    return enterprise_setup_payload(session)
