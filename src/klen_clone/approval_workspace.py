from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class ApprovalSource:
    workflow: str
    table: str
    route: str
    permissions: frozenset[str]
    status: str
    key_column: str
    reference_column: str
    actor_column: str | None = None
    created_column: str | None = "created_at"
    location_column: str | None = None
    extra_where: str | None = None


def _source(workflow: str, table: str, route: str, permissions: Iterable[str], status: str,
            key: str, reference: str, actor: str | None = None,
            created: str | None = "created_at", location: str | None = None,
            extra_where: str | None = None) -> ApprovalSource:
    return ApprovalSource(workflow, table, route, frozenset(permissions), status, key,
                          reference, actor, created, location, extra_where)


# This is the server-owned registry for approval discovery. It does not perform
# decisions: users are routed to the owning workspace, whose existing endpoint
# remains authoritative for permission, revision, scope and maker-checker checks.
APPROVAL_SOURCES = (
    _source("Operating branch", "operational_branches", "company-setup", {"enterprise.approve"},
            "pending_approval", "branch_key", "branch_code", "created_by"),
    _source("Warehouse activation", "operational_warehouses", "company-setup", {"enterprise.approve"},
            "pending_approval", "warehouse_key", "warehouse_code", "created_by"),
    _source("Van activation", "operational_vans", "company-setup", {"enterprise.approve"},
            "pending_approval", "van_key", "van_code", "created_by"),
    _source("Commercial price list", "operational_price_lists", "sales-orders", {"discount.approve"},
            "draft", "price_list_key", "name", "created_by", None),
    _source("Commercial promotion", "operational_commercial_promotions", "sales-orders", {"discount.approve"},
            "draft", "promotion_key", "promotion_code", "created_by", None),
    _source("Sales or purchase draft", "operational_drafts", "drafts", {"draft.approve"},
            "submitted", "draft_key", "draft_no", "created_by", location="location_code"),
    _source("Sales quotation", "operational_sales_quotations", "sales-orders", {"draft.approve"},
            "submitted", "quotation_key", "quotation_no", "created_by", location="location_code"),
    _source("Inventory document", "operational_inventory_documents", "inventory-operations", {"inventory.approve"},
            "submitted", "document_key", "document_no", "created_by", location="location_code"),
    _source("Cycle count", "operational_cycle_count_sessions", "warehouse-controls", {"inventory.approve"},
            "submitted", "count_key", "count_no", "created_by", location="location_code"),
    _source("Quarantine release", "operational_quarantine_holds", "warehouse-controls", {"quarantine.manage"},
            "held", "hold_key", "hold_no", "created_by", location="location_code"),
    _source("Serial quarantine release", "operational_serial_units", "warehouse-controls", {"quarantine.manage"},
            "quarantined", "serial_key", "serial_number", "status_changed_by",
            "status_changed_at", "location_code"),
    _source("Goods receipt", "operational_goods_receipts", "goods-receipts",
            {"goods_receipt.accept", "goods_receipt.reject"}, "submitted", "receipt_key", "receipt_no",
            "created_by", location="location_code"),
    _source("Customer invoice", "operational_customer_invoices", "customer-invoices",
            {"customer_invoice.approve", "draft.approve"}, "submitted", "invoice_key", "invoice_no",
            "created_by", location="location_code"),
    _source("Sales return", "operational_sales_returns", "sales-returns", {"sales_return.approve"},
            "submitted", "return_key", "return_no", "created_by", location="location_code"),
    _source("Purchase return", "operational_purchase_returns", "purchase-returns", {"purchase_return.approve"},
            "submitted", "return_key", "return_no", "created_by", location="location_code"),
    _source("Receipt or payment", "operational_payments", "payments", {"payment.approve"},
            "submitted", "payment_key", "payment_no", "created_by", location="location_code"),
    _source("Purchase requisition", "operational_purchase_requisitions", "procurement",
            {"purchase.requisition.approve", "enterprise.setup"}, "submitted", "requisition_key",
            "requisition_no", "created_by", location="location_code"),
    _source("Purchase order", "operational_purchase_orders", "procurement",
            {"purchase_order.approve", "enterprise.setup"}, "submitted", "purchase_order_key",
            "purchase_order_no", "created_by", location="location_code"),
    _source("Supplier invoice", "operational_supplier_invoices", "procurement",
            {"supplier_bill.approve", "enterprise.setup"}, "matched", "invoice_key",
            "supplier_invoice_no", "created_by", location="location_code"),
    _source("Supplier invoice exception", "operational_supplier_invoices", "procurement",
            {"supplier_bill.tolerance.approve", "enterprise.setup"}, "exception", "invoice_key",
            "supplier_invoice_no", "created_by", location="location_code"),
    _source("Supplier adjustment", "operational_supplier_adjustments", "procurement",
            {"supplier_adjustment.approve", "enterprise.setup"}, "submitted", "adjustment_key",
            "supplier_reference", "created_by", location="location_code"),
    _source("Matching tolerance policy", "operational_match_tolerance_policies", "procurement",
            {"match_tolerance.approve", "enterprise.setup"}, "change_pending", "policy_key",
            "policy_key", "requested_by", None),
    _source("Cash or bank account", "operational_cash_accounts", "cash-management", {"cash.account.approve"},
            "pending", "account_key", "account_code", "created_by", location="location_code"),
    _source("Bank reconciliation", "operational_statement_batches", "cash-management",
            {"bank.reconcile.approve"}, "submitted", "batch_key", "statement_reference", "created_by"),
    _source("Expense claim", "operational_expense_claims", "expenses", {"expense.approve"},
            "submitted", "claim_key", "claim_no", "created_by", location="location_code"),
    _source("Petty-cash advance", "operational_petty_cash_advances", "expenses", {"petty_cash.approve"},
            "pending", "advance_key", "advance_no", "created_by", location="location_code"),
    _source("Fixed asset", "operational_fixed_assets", "fixed-assets", {"fixed_asset.approve"},
            "submitted", "asset_key", "asset_no", "created_by", location="location_code"),
    _source("VAT return", "operational_vat_periods", "vat-control", {"vat.period.approve"},
            "submitted", "period_key", "period_code", "created_by"),
    _source("VAT adjustment", "operational_vat_adjustments", "vat-control", {"vat.adjustment.approve"},
            "pending", "adjustment_key", "adjustment_no", "created_by"),
    _source("Period close", "operational_period_closes", "period-close", {"close.approve"},
            "submitted", "close_key", "close_no", "created_by"),
    _source("Close adjustment", "operational_close_adjustments", "period-close", {"close.adjustment.approve"},
            "pending", "adjustment_key", "adjustment_no", "created_by"),
    _source("Financial report package", "operational_financial_report_packages", "financial-statements",
            {"financial_report.approve"}, "submitted", "package_key", "package_no", "submitted_by"),
    _source("Statutory evidence package", "operational_statutory_evidence_packages", "audit-compliance",
            {"audit_compliance.approve"}, "submitted", "package_key", "package_no", "submitted_by"),
    _source("Cutover rehearsal", "operational_cutover_rehearsal_packages", "cutover-rehearsal",
            {"cutover_rehearsal.approve"}, "submitted", "package_key", "package_no", "submitted_by"),
    _source("Finance foundation", "operational_finance_approvals", "chart-of-accounts",
            {"finance.chart.approve", "finance.mapping.approve"}, "pending", "resource_key",
            "resource_key", "requested_by", None),
    _source("Finance reconciliation", "operational_finance_reconciliation_reviews", "accounting",
            {"finance.reconciliation.approve"}, "pending", "review_key", "control_name", "proposed_by"),
    _source("General journal", "operational_general_journals", "general-ledger", {"journal.approve"},
            "pending", "journal_key", "journal_no", "requested_by"),
    _source("Credit-limit request", "operational_credit_limit_requests", "credit-control",
            {"credit.limit.approve"}, "pending", "request_key", "party_code", "created_by"),
    _source("Credit override", "operational_credit_override_requests", "credit-control",
            {"credit.override.approve"}, "pending", "request_key", "quotation_no", "created_by"),
    _source("Dunning escalation", "operational_dunning_requests", "credit-control",
            {"collection.escalation.approve"}, "pending", "request_key", "party_code", "created_by"),
    _source("HR workforce request", "operational_hrm_workforce_requests", "hrm",
            {"hrm.lifecycle.approve", "hrm.manage", "enterprise.setup"}, "pending", "request_key",
            "request_no", "requested_by"),
    _source("HR leave request", "operational_hrm_leave_requests", "hrm",
            {"leave.approve", "hrm.manage", "enterprise.setup"}, "pending", "leave_key",
            "leave_key", "requested_by"),
    _source("Attendance correction", "operational_hrm_attendance_corrections", "hrm",
            {"attendance.approve", "hrm.manage", "enterprise.setup"}, "pending", "correction_key",
            "correction_key", "requested_by"),
    _source("HR lifecycle case", "operational_hrm_lifecycle_cases", "hrm",
            {"hrm.lifecycle.approve", "hrm.manage", "enterprise.setup"}, "pending", "case_key",
            "case_no", "requested_by"),
    _source("POS shift close", "operational_pos_shifts", "pos", {"cash.close.approve"},
            "closing_submitted", "shift_key", "shift_no", "opened_by"),
    _source("Van load", "operational_van_routes", "van-sales", {"van.shift.approve"},
            "load_submitted", "route_key", "route_no", "created_by"),
    _source("Van close", "operational_van_routes", "van-sales", {"van.close.approve"},
            "close_submitted", "route_key", "route_no", "created_by"),
    _source("CRM proposal", "operational_crm_proposals", "crm", {"crm.proposal.approve"},
            "draft", "proposal_key", "title", "created_by"),
)


def _serialise(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def approval_workspace_payload(session: Session, *, username: str | None,
                               permissions: Iterable[str] | None,
                               allowed_locations: Iterable[str] | None,
                               limit_per_source: int = 100) -> dict[str, object]:
    granted = None if permissions is None else set(permissions)
    locations = {value.upper() for value in (allowed_locations or ())}
    unrestricted = granted is None or "*" in locations
    items: list[dict[str, object]] = []
    visible_workflows = 0
    for source in APPROVAL_SOURCES:
        if granted is not None and source.permissions.isdisjoint(granted):
            continue
        visible_workflows += 1
        created_select = f"{source.created_column} AS created_at" if source.created_column else "NULL AS created_at"
        actor_select = f"{source.actor_column} AS submitted_by" if source.actor_column else "NULL AS submitted_by"
        location_select = f"{source.location_column} AS location_code" if source.location_column else "NULL AS location_code"
        conditions = ["status = :status"]
        if source.extra_where:
            conditions.append(source.extra_where)
        statement = text(
            f"SELECT {source.key_column} AS resource_key, {source.reference_column} AS reference, "
            f"status, {actor_select}, {created_select}, {location_select} "
            f"FROM {source.table} WHERE {' AND '.join(conditions)} "
            f"ORDER BY {source.created_column or source.key_column} DESC LIMIT :limit"
        )
        for row in session.execute(statement, {"status": source.status, "limit": limit_per_source}).mappings():
            location = (row["location_code"] or "").upper()
            if not unrestricted and source.location_column and location not in locations:
                continue
            submitted_by = row["submitted_by"]
            self_submitted = bool(username and submitted_by and username.casefold() == str(submitted_by).casefold())
            items.append({
                "workflow": source.workflow,
                "resource_key": str(row["resource_key"]),
                "reference": str(row["reference"] or row["resource_key"]),
                "status": str(row["status"]),
                "route": source.route,
                "submitted_by": submitted_by,
                "created_at": _serialise(row["created_at"]),
                "location_code": row["location_code"],
                "required_permissions": sorted(source.permissions),
                "action_eligible": not self_submitted,
                "eligibility_reason": "independent_approver_required" if self_submitted else "eligible",
                "posting_enabled": False,
            })
    items.sort(key=lambda item: (str(item["created_at"] or ""), item["workflow"], item["reference"]), reverse=True)
    actionable = sum(bool(item["action_eligible"]) for item in items)
    return {
        "controls": {
            "visible_pending": len(items),
            "actionable": actionable,
            "self_submitted": len(items) - actionable,
            "visible_workflows": visible_workflows,
            "posting_enabled": False,
        },
        "items": items,
        "boundary": {
            "read_only_aggregation": True,
            "decisions_remain_in_owning_workspace": True,
            "permission_filtered": granted is not None,
            "location_scoped": not unrestricted,
            "source_read_only": True,
        },
    }
