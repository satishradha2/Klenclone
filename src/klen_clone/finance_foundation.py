from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .operational import OperationalAuditEvent, OperationalBase, utc_now


class OperationalChartAccount(OperationalBase):
    __tablename__ = "operational_chart_accounts"
    __table_args__ = (
        UniqueConstraint("company_code", "account_code", name="uq_operational_chart_account"),
        CheckConstraint("account_class IN ('asset','liability','equity','income','expense')", name="ck_operational_chart_class"),
        CheckConstraint("status IN ('draft','active','inactive')", name="ck_operational_chart_status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    company_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    account_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    account_class: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    statement_section: Mapped[str] = mapped_column(String(80), nullable=False)
    is_postable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OperationalAccountMapping(OperationalBase):
    __tablename__ = "operational_account_mappings"
    __table_args__ = (UniqueConstraint("company_code", "mapping_key", name="uq_operational_account_mapping"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    mapping_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    target_account_code: Mapped[str] = mapped_column(String(40), nullable=False)
    mapping_status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending_finance_review")
    rationale: Mapped[str] = mapped_column(Text, nullable=False)


class OperationalFinanceApproval(OperationalBase):
    __tablename__ = "operational_finance_approvals"
    __table_args__ = (UniqueConstraint("company_code", "resource_type", "resource_key", name="uq_operational_finance_approval"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_key: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    requested_by: Mapped[str | None] = mapped_column(String(200))
    approved_by: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


ACCOUNT_TEMPLATE = (
    ("1100", "Cash on hand", "asset", "cash_and_cash_equivalents"),
    ("1110", "Bank accounts", "asset", "cash_and_cash_equivalents"),
    ("1120", "Card-payment clearing", "asset", "cash_and_cash_equivalents"),
    ("1200", "Trade receivables", "asset", "trade_and_other_receivables"),
    ("1300", "Inventory", "asset", "inventories"),
    ("1310", "Inventory in transit", "asset", "inventories"),
    ("1320", "Input VAT recoverable", "asset", "tax_assets"),
    ("1500", "Property, plant and equipment", "asset", "non_current_assets"),
    ("1510", "Accumulated depreciation", "asset", "non_current_assets"),
    ("1600", "Right-of-use assets", "asset", "non_current_assets"),
    ("2100", "Trade payables", "liability", "trade_and_other_payables"),
    ("2110", "Accrued expenses", "liability", "trade_and_other_payables"),
    ("2120", "Output VAT payable", "liability", "tax_liabilities"),
    ("2200", "Lease liabilities", "liability", "non_current_liabilities"),
    ("2300", "Corporate Tax payable", "liability", "tax_liabilities"),
    ("3000", "Share capital", "equity", "equity"),
    ("3100", "Retained earnings", "equity", "equity"),
    ("4000", "Sales revenue", "income", "revenue"),
    ("4010", "Sales returns and discounts", "income", "revenue"),
    ("5000", "Cost of goods sold", "expense", "cost_of_sales"),
    ("5100", "Freight and landed cost", "expense", "cost_of_sales"),
    ("5110", "Purchase price variance", "expense", "cost_of_sales"),
    ("5120", "Inventory write-off", "expense", "cost_of_sales"),
    ("6000", "Selling and distribution expense", "expense", "operating_expenses"),
    ("6100", "Administrative expense", "expense", "operating_expenses"),
    ("6200", "Depreciation expense", "expense", "operating_expenses"),
    ("6300", "Finance cost", "expense", "finance_costs"),
    ("6400", "Corporate Tax expense", "expense", "income_tax_expense"),
)


MAPPING_TEMPLATE = {
    "sales_invoice": ("4000", "Revenue is recognised through approved sales documents."),
    "sales_return": ("4010", "Credit notes reduce revenue without overwriting the original invoice."),
    "inventory_receipt": ("1300", "Approved goods receipts increase inventory before supplier-bill reconciliation."),
    "supplier_bill": ("2100", "Supplier bills control trade-payable recognition."),
    "input_vat": ("1320", "Input VAT remains separately controlled for UAE VAT reconciliation."),
    "output_vat": ("2120", "Output VAT remains separately controlled for UAE VAT reconciliation."),
}


def initialize_finance_foundation(session: Session, *, actor: str = "finance_foundation") -> dict:
    company_code = "ASAS"
    created = 0
    for code, name, account_class, section in ACCOUNT_TEMPLATE:
        if not session.scalar(select(OperationalChartAccount).where(OperationalChartAccount.company_code == company_code,
                                                                      OperationalChartAccount.account_code == code)):
            session.add(OperationalChartAccount(account_key=str(uuid.uuid4()), company_code=company_code,
                account_code=code, name=name, account_class=account_class, statement_section=section,
                is_postable=True, status="draft"))
            created += 1
    for mapping_key, (target, rationale) in MAPPING_TEMPLATE.items():
        if not session.scalar(select(OperationalAccountMapping).where(OperationalAccountMapping.company_code == company_code,
                                                                       OperationalAccountMapping.mapping_key == mapping_key)):
            session.add(OperationalAccountMapping(company_code=company_code, mapping_key=mapping_key,
                target_account_code=target, mapping_status="pending_finance_review", rationale=rationale))
            created += 1
    if created:
        session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="finance_foundation.seeded",
            actor=actor, resource_key=company_code,
            detail="Full-IFRS chart template and draft mappings seeded; source balances remain unposted evidence."))
        session.commit()
    return finance_foundation_payload(session)


def _finance_resource(session: Session, resource_type: str, resource_key: str, *, lock: bool = False):
    if resource_type == "chart_account":
        query = select(OperationalChartAccount).where(
            OperationalChartAccount.company_code == "ASAS",
            OperationalChartAccount.account_code == resource_key,
        )
    elif resource_type == "account_mapping":
        query = select(OperationalAccountMapping).where(
            OperationalAccountMapping.company_code == "ASAS",
            OperationalAccountMapping.mapping_key == resource_key,
        )
    else:
        raise ValueError("Unsupported finance approval resource type")
    resource = session.scalar(query.with_for_update() if lock else query)
    if resource is None:
        raise ValueError("Finance approval resource was not found")
    return resource


def request_finance_approval(session: Session, *, actor: str, resource_type: str,
                             resource_key: str, note: str) -> OperationalFinanceApproval:
    resource = _finance_resource(session, resource_type, resource_key, lock=True)
    approval = session.scalar(select(OperationalFinanceApproval).where(
        OperationalFinanceApproval.company_code == "ASAS",
        OperationalFinanceApproval.resource_type == resource_type,
        OperationalFinanceApproval.resource_key == resource_key,
    ).with_for_update())
    if approval and approval.status == "pending":
        raise RuntimeError("This finance item is already awaiting approval")
    if approval and approval.status == "approved":
        raise RuntimeError("This finance item is already approved")
    if resource_type == "chart_account" and resource.status == "active":
        raise RuntimeError("This chart account is already active")
    if resource_type == "account_mapping" and resource.mapping_status == "approved":
        raise RuntimeError("This account mapping is already approved")
    if approval is None:
        approval = OperationalFinanceApproval(
            company_code="ASAS", resource_type=resource_type, resource_key=resource_key,
            status="pending", requested_by=actor, note=note, revision=1,
        )
        session.add(approval)
    else:
        approval.status = "pending"
        approval.requested_by = actor
        approval.approved_by = None
        approval.note = note
        approval.revision += 1
    session.flush()
    session.add(OperationalAuditEvent(
        event_key=str(uuid.uuid4()), event_type="finance.approval_requested", actor=actor,
        resource_key=f"{resource_type}:{resource_key}",
        detail=f"revision={approval.revision}; note={note}; posting disabled",
    ))
    session.commit()
    return approval


def decide_finance_approval(session: Session, *, actor: str, resource_type: str,
                            resource_key: str, action: str, expected_revision: int,
                            note: str) -> OperationalFinanceApproval:
    if action not in {"approve", "reject"}:
        raise ValueError("Finance approval action must be approve or reject")
    resource = _finance_resource(session, resource_type, resource_key, lock=True)
    approval = session.scalar(select(OperationalFinanceApproval).where(
        OperationalFinanceApproval.company_code == "ASAS",
        OperationalFinanceApproval.resource_type == resource_type,
        OperationalFinanceApproval.resource_key == resource_key,
    ).with_for_update())
    if approval is None or approval.status != "pending":
        raise RuntimeError("This finance item is not awaiting approval")
    if approval.revision != expected_revision:
        raise RuntimeError(f"Finance approval revision conflict; current revision is {approval.revision}")
    if approval.requested_by and approval.requested_by.casefold() == actor.casefold():
        raise PermissionError("The finance maker cannot approve or reject their own request")
    approval.status = "approved" if action == "approve" else "rejected"
    approval.approved_by = actor
    approval.note = note
    approval.revision += 1
    if resource_type == "chart_account":
        resource.status = "active" if action == "approve" else "draft"
    else:
        resource.mapping_status = "approved" if action == "approve" else "pending_finance_review"
    session.add(OperationalAuditEvent(
        event_key=str(uuid.uuid4()), event_type=f"finance.approval_{action}d", actor=actor,
        resource_key=f"{resource_type}:{resource_key}",
        detail=f"revision={approval.revision}; note={note}; posting disabled",
    ))
    session.commit()
    return approval


def finance_foundation_payload(session: Session) -> dict:
    accounts = session.scalars(select(OperationalChartAccount).where(OperationalChartAccount.company_code == "ASAS").order_by(OperationalChartAccount.account_code)).all()
    mappings = session.scalars(select(OperationalAccountMapping).where(OperationalAccountMapping.company_code == "ASAS").order_by(OperationalAccountMapping.mapping_key)).all()
    classes = {kind: sum(row.account_class == kind for row in accounts) for kind in ("asset", "liability", "equity", "income", "expense")}
    approvals = session.scalars(select(OperationalFinanceApproval).where(OperationalFinanceApproval.company_code == "ASAS")).all()
    approvals_by_resource = {(row.resource_type, row.resource_key): row for row in approvals}
    def approval_payload(resource_type: str, resource_key: str):
        row = approvals_by_resource.get((resource_type, resource_key))
        if row is None:
            return None
        return {"status": row.status, "requested_by": row.requested_by,
                "decided_by": row.approved_by, "note": row.note, "revision": row.revision}
    return {"accounting_framework": "full_ifrs", "posting_enabled": False,
            "accounts": [{"code": row.account_code, "name": row.name, "class": row.account_class,
                          "statement_section": row.statement_section, "status": row.status,
                          "postable": row.is_postable,
                          "approval": approval_payload("chart_account", row.account_code)} for row in accounts],
            "mappings": [{"key": row.mapping_key, "target_account_code": row.target_account_code,
                          "status": row.mapping_status, "rationale": row.rationale,
                          "approval": approval_payload("account_mapping", row.mapping_key)} for row in mappings],
            "account_classes": classes,
            "financial_statements": ["statement_of_financial_position", "profit_or_loss", "cash_flows", "changes_in_equity", "notes"],
            "approvals": [{"resource_type": row.resource_type, "resource_key": row.resource_key, "status": row.status,
                           "requested_by": row.requested_by, "decided_by": row.approved_by,
                           "note": row.note, "revision": row.revision} for row in approvals],
            "activation_gate": "Finance must approve the chart, mappings, opening balances and reconciliations before posting."}
