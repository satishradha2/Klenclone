"""Current ERP completion matrix.

This catalogue is deliberately explicit: a permission name, source export, or
database foundation is not treated as an implemented operating workflow.
"""

from __future__ import annotations


IMPLEMENTED_CAPABILITIES = (
    ("enterprise_setup", "Company, branch, warehouse and van setup", ("/api/v1/setup/enterprise",)),
    ("access_control", "Users, scoped roles and maker-checker access", ("/api/v1/access-control",)),
    ("crm", "CRM leads, follow-ups and controlled commercial proposals", ("/api/v1/crm", "/api/v1/crm/leads")),
    ("hrm", "Complete HRM lifecycle with payroll excluded", ("/api/v1/hrm", "/api/v1/hrm/workforce-requests", "/api/v1/hrm/lifecycle-cases")),
    ("finance_foundation", "Chart of accounts, mappings and reconciliation", ("/api/v1/finance/foundation", "/api/v1/finance/reconciliation")),
    ("general_ledger", "Controlled journals and ledger enquiry", ("/api/v1/general-ledger",)),
    ("procure_to_pay", "Requisition, RFQ, quotation award, PO and supplier matching", ("/api/v1/procurement",)),
    ("goods_receipt", "Receiving, inspection, batch and expiry capture", ("/api/v1/goods-receipts",)),
    ("purchase_returns", "Purchase returns and supplier debit-note rehearsal", ("/api/v1/purchase-returns",)),
    ("order_to_cash", "Quotation, approval, acceptance and sales-order conversion", ("/api/v1/sales-orders",)),
    ("commercial_pricing", "Effective price lists, customer groups, discount limits and approved promotions", ("/api/v1/commercial-pricing",)),
    ("pos_counter", "POS tills, counter sales, payment capture and independent cash close", ("/api/v1/pos",)),
    ("van_sales", "Van routes, load-out, offline sync, returns, collections and close", ("/api/v1/van-sales",)),
    ("delivery", "Allocation, picking, dispatch, delivery note and POD", ("/api/v1/deliveries",)),
    ("customer_invoicing", "POD-gated customer invoicing and posting rehearsal", ("/api/v1/customer-invoices",)),
    ("sales_returns", "Invoice-controlled returns and credit-note rehearsal", ("/api/v1/sales-returns",)),
    ("payments", "Customer receipts, supplier payments and allocation", ("/api/v1/payments",)),
    ("credit_collections", "Limits, holds, overrides, dunning and collections", ("/api/v1/credit-control",)),
    ("inventory", "Stock transfers, adjustments and UOM-controlled operations", ("/api/v1/inventory-documents",)),
    ("cash_management", "Bank accounts, statement matching and reconciliation", ("/api/v1/cash-management",)),
    ("expenses", "Expense claims, UAE VAT evidence and petty cash", ("/api/v1/expense-management/workspace",)),
    ("fixed_assets", "Asset register, depreciation and disposal rehearsal", ("/api/v1/fixed-assets/workspace",)),
    ("vat", "UAE VAT periods, adjustments and return rehearsal", ("/api/v1/vat-control/workspace",)),
    ("close_report", "Month-end close, financial statements and controlled exports", ("/api/v1/period-close/workspace", "/api/v1/close-reporting/workspace")),
    ("audit_cutover", "Audit evidence, statutory packages and non-destructive cutover rehearsal", ("/api/v1/audit-compliance/workspace", "/api/v1/cutover-rehearsal/workspace")),
)


REMAINING_GAPS = (
    {"priority": "high", "area": "Inventory", "capability": "Advanced traceability and warehouse control",
     "gap": "Batch and expiry are captured at receipt, and controlled cycle-count sessions plus independent quarantine release are available. Serial registry, barcode execution, recall and warehouse task controls remain incomplete."},
    {"priority": "high", "area": "Finance", "capability": "Multi-currency and foreign exchange",
     "gap": "The current operational model is AED-focused; currency masters, rates, realized/unrealized FX and revaluation are not implemented."},
    {"priority": "high", "area": "Finance", "capability": "Budgets, consolidation and corporate tax",
     "gap": "Role/catalogue labels and ledger accounts exist, but operating budgets, entity consolidation and UAE corporate-tax computation/return workflows are not implemented."},
    {"priority": "high", "area": "Compliance", "capability": "UAE e-invoicing provider integration",
     "gap": "Readiness labels exist; provider onboarding, document exchange, status monitoring, retry and evidence retention are not implemented."},
    {"priority": "high", "area": "Documents", "capability": "Attachments and document management",
     "gap": "Evidence references and selected receipt fields exist, but durable upload, malware scanning, retention, versioning and record-level attachment retrieval are not implemented."},
    {"priority": "high", "area": "Security", "capability": "MFA enforcement and production identity lifecycle",
     "gap": "Sensitive users are flagged as MFA-required, but a second-factor challenge, recovery flow and production identity-provider lifecycle are not implemented."},
    {"priority": "medium", "area": "Treasury", "capability": "Cash transfers and daily cash close",
     "gap": "Bank reconciliation exists; controlled cash/bank transfers, POS till close and cash-count variance workflows are not implemented."},
    {"priority": "medium", "area": "Integration", "capability": "Notifications and external interfaces",
     "gap": "Operational email/SMS notifications, webhooks, retry queues and integration monitoring are not implemented."},
    {"priority": "critical", "area": "Production", "capability": "Production activation and final migration",
     "gap": "Final frozen BizModo capture, attachment archive, backup/restore proof, fresh full import, row/checksum reconciliation, TLS/secrets/monitoring and named cutover approval remain blocked. Permanent posting and statutory filing stay disabled."},
)


def completion_audit_payload(route_paths: set[str]) -> dict:
    implemented = []
    for key, name, expected in IMPLEMENTED_CAPABILITIES:
        missing = [path for path in expected if path not in route_paths]
        implemented.append({
            "key": key,
            "name": name,
            "status": "implemented_staging" if not missing else "route_regression",
            "expected_routes": list(expected),
            "missing_routes": missing,
            "boundary": "Controlled staging; permanent posting and production activation remain disabled",
        })
    regressions = [item for item in implemented if item["missing_routes"]]
    priorities = {level: sum(item["priority"] == level for item in REMAINING_GAPS)
                  for level in ("critical", "high", "medium")}
    return {
        "assessment": "incomplete" if REMAINING_GAPS or regressions else "complete",
        "implemented": implemented,
        "remaining_gaps": list(REMAINING_GAPS),
        "summary": {
            "implemented_staging_capabilities": len(implemented) - len(regressions),
            "route_regressions": len(regressions),
            "remaining_capability_gaps": len(REMAINING_GAPS),
            **{f"{key}_gaps": value for key, value in priorities.items()},
        },
        "scope": {"hrm_included": True, "payroll_excluded": True,
                  "bizmodo_read_only": True, "test_data_only": True,
                  "permanent_posting_enabled": False, "production_enabled": False},
        "decision": "Do not declare the ERP complete or begin final cutover until the critical gaps are implemented and end-to-end UAT is approved.",
    }
