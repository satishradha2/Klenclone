"""Target ERP role catalogue; source-system identities are never modified."""

ROLE_MATRIX = {
    "administrator": {"enterprise.setup", "enterprise.approve", "user.manage", "role.manage", "access.review", "audit.read", "clone.read", "migration.review", "hrm.read", "hrm.manage", "hrm.lifecycle.prepare", "hrm.lifecycle.approve", "pos.read", "pos.manage", "pos.sale", "cash.close.prepare", "van.read", "van.route.prepare", "van.shift", "van.sale", "van.return", "van.offline_sync", "van.close.prepare", "crm.read", "crm.lead.prepare", "crm.activity.prepare", "crm.proposal.prepare", "barcode.manage", "serial.manage", "warehouse.scan"},
    "crm_user": {"crm.read", "crm.lead.prepare", "crm.activity.prepare", "crm.proposal.prepare"},
    "crm_manager": {"crm.read", "crm.proposal.approve"},
    "finance_maker": {"finance.chart.prepare", "finance.mapping.prepare", "finance.reconciliation.prepare", "journal.prepare", "payment.prepare", "cash.account.prepare", "bank.statement.import", "bank.reconcile.prepare"},
    "finance_approver": {"finance.chart.approve", "finance.mapping.approve", "finance.reconciliation.approve", "journal.approve", "payment.approve", "payment.rehearse", "cash.account.approve", "bank.reconcile.approve", "bank.reconcile.rehearse", "credit.limit.approve", "credit.hold.release", "credit.override.approve", "collection.escalation.approve", "supplier_bill.approve", "supplier_adjustment.approve"},
    "branch_manager": {"branch.review", "sales.approve", "credit.override.approve", "pos.read", "cash.close.approve"},
    "warehouse_supervisor": {"warehouse.receive", "warehouse.transfer.approve", "stock.adjust.approve", "inventory.approve", "inventory.rehearse", "delivery.allocate", "delivery.pick", "barcode.manage", "serial.manage", "warehouse.scan"},
    "van_user": {"van.read", "van.shift", "van.sale", "van.return", "van.offline_sync", "draft.create", "draft.edit", "draft.submit", "draft.cancel"},
    "sales_user": {"sales.quote", "sales.order", "sales.invoice", "delivery.allocate", "customer_invoice.create", "customer_invoice.submit", "customer_invoice.cancel", "draft.create", "draft.edit", "draft.submit", "draft.cancel"},
    "auditor": {"audit.read", "access.review", "finance.read", "report.export", "clone.read", "financial_report.read"},
    "chief_financial_officer": {"finance.read", "finance.close", "budget.approve", "consolidation.approve", "match_tolerance.approve", "supplier_bill.tolerance.approve"},
    "finance_controller": {"finance.close", "finance.reconciliation.approve", "journal.approve", "opening_balance.approve", "tax.approve", "match_tolerance.prepare"},
    "accounts_receivable": {"customer.manage", "receipt.prepare", "credit.review", "credit.limit.prepare", "credit.override.prepare", "collection.manage", "collection.escalation.prepare", "payment.create", "payment.edit", "payment.submit", "payment.cancel"},
    "accounts_payable": {"supplier.manage", "supplier_bill.prepare", "supplier_bill.rehearse", "supplier_adjustment.prepare", "payment.prepare", "payment.create", "payment.edit", "payment.submit", "payment.cancel"},
    "treasury": {"cash.account.prepare", "bank.statement.import", "bank.reconcile.prepare", "bank.reconcile.approve", "bank.reconcile.rehearse", "cash.transfer.prepare", "payment.approve", "payment.rehearse"},
    "tax_officer": {"vat.return.prepare", "corporate_tax.prepare", "einvoice.monitor"},
    "fixed_asset_accountant": {"asset.register", "asset.depreciation.prepare", "asset.disposal.prepare"},
    "procurement_requester": {"purchase.requisition.create"},
    "buyer": {"rfq.create", "supplier_quote.manage", "purchase_order.prepare", "draft.create", "draft.edit", "draft.submit", "draft.cancel"},
    "procurement_manager": {"purchase.requisition.approve", "purchase_order.approve", "supplier.approve", "contract.approve", "draft.approve", "goods_receipt.accept", "goods_receipt.reject"},
    "goods_receipt_clerk": {"goods_receipt.create", "quality.inspect", "goods_receipt.edit", "goods_receipt.submit", "goods_receipt.cancel"},
    "inventory_controller": {"stock.count", "stock.adjust.prepare", "stock.transfer.prepare", "inventory.create", "inventory.edit", "inventory.submit", "inventory.cancel", "barcode.manage", "serial.manage", "warehouse.scan"},
    "quality_controller": {"quarantine.manage", "recall.manage", "disposal.prepare", "goods_receipt.accept", "goods_receipt.reject", "goods_receipt.rehearse", "warehouse.scan"},
    "logistics_manager": {"delivery.manage", "delivery.allocate", "delivery.pick", "delivery.dispatch", "delivery.pod", "delivery.cancel", "dispatch.approve", "transfer.approve"},
    "sales_manager": {"sales.approve", "discount.approve", "price_list.manage", "customer_invoice.approve", "customer_invoice.rehearse", "draft.approve", "sales_return.approve", "sales_return.rehearse"},
    "pos_cashier": {"pos.read", "pos.sale", "cash.close.prepare"},
    "credit_controller": {"credit.limit.manage", "credit.hold.release", "credit.override.approve", "collection.escalation.approve"},
    "returns_officer": {"sales_return.prepare", "purchase_return.prepare", "sales_return.create", "sales_return.edit", "sales_return.submit", "sales_return.cancel", "purchase_return.create", "purchase_return.edit", "purchase_return.submit", "purchase_return.cancel"},
    "van_supervisor": {"van.read", "van.shift.approve", "van.close.approve", "van.stock.approve"},
    "security_administrator": {"user.manage", "role.manage", "mfa.manage", "access.review"},
    "integration_administrator": {"integration.manage", "webhook.manage", "einvoice.provider.manage"},
    "executive_read_only": {"dashboard.read", "report.export", "clone.read", "financial_report.read"},
    "hr_manager": {"hrm.read", "hrm.manage", "hrm.employee.approve", "attendance.approve", "leave.approve", "shift.manage", "hrm.lifecycle.prepare", "hrm.lifecycle.approve"},
    "hr_officer": {"hrm.read", "hrm.employee.prepare", "attendance.prepare", "leave.prepare", "hrm.lifecycle.prepare"},
    "employee_self_service": {"hrm.self.read", "attendance.self.create", "leave.self.create"},
}

MAKER_APPROVER_PAIRS = (
    ("finance_maker", "finance_approver"),
    ("hr_officer", "hr_manager"),
    ("procurement_requester", "procurement_manager"),
    ("buyer", "procurement_manager"),
    ("accounts_payable", "finance_approver"),
)


def permissions_for_roles(roles: set[str]) -> set[str]:
    return set().union(*(ROLE_MATRIX.get(role, set()) for role in roles))
