from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .auth import UatSessionStore, verify_password
from .delta_overlay import load_delta_overlay
from .db import make_engine
from .inventory import canonical_uom as normalize_uom
from .models import (
    ErpGlAccount,
    ErpAuditEvent,
    ErpInventoryMovement,
    ErpLocation,
    ErpMigrationExceptionQueue,
    ErpOpeningBalanceQueue,
    ErpOrganization,
    ErpParty,
    ErpProductMaster,
    ErpProductUom,
    ErpTransactionLine,
    ErpTransactionDocument,
    SourceSnapshot,
)
from .operational import (
    OperationalAuditEvent, OperationalDraft, OperationalFiscalPeriod, OperationalJournalBatch,
    OperationalFinancialMigrationException, OperationalOpeningPartyBalance,
    OperationalPostingProbe, OperationalReversalRequest, OperationalStockPosition,
    OperationalStockReservation, OperationalSubledgerEntry,
    calculate_line, create_draft, initialize_operational_database, list_drafts,
    make_operational_engine, operational_session_factory, execute_posting, execute_reversal,
    rehearse_posting, replace_draft, transition_draft,
)
from .inventory_operations import (
    OperationalInventoryDocument,
    create_inventory_document,
    inventory_control_counts,
    list_inventory_documents,
    rehearse_inventory_posting,
    replace_inventory_document,
    transition_inventory_document,
)
from .warehouse_controls import (
    OperationalBarcodeIdentity, OperationalCycleCountSession, OperationalQuarantineHold,
    OperationalSerialUnit, barcode_payload, create_cycle_count, create_quarantine_hold,
    cycle_count_payload, quarantine_payload, record_warehouse_scan, register_barcode,
    register_serial, release_quarantine_hold, scan_payload, serial_payload,
    transition_cycle_count, transition_serial, warehouse_control_payload,
)
from .approval_workspace import approval_workspace_payload
from .goods_receipts import (
    OperationalGoodsReceipt,
    create_goods_receipt,
    goods_receipt_control_counts,
    list_goods_receipts,
    rehearse_goods_receipt_posting,
    replace_goods_receipt,
    transition_goods_receipt,
)
from .data_governance import PROMOTION_GATES, lifecycle_actions, promotion_control_counts
from .data_reviews import (
    OperationalDataReview, enrich_review_source, review_control_counts, review_payload, start_review,
    transaction_review_findings, transition_review,
)
from .sales_returns import (
    OperationalSalesReturn, OperationalSalesReturnPostingRehearsal,
    _sales_return_rehearsal_payload, create_sales_return, list_sales_returns,
    rehearse_sales_return_posting, replace_sales_return,
    sales_return_control_counts, transition_sales_return,
)
from .sales_invoices import (
    OperationalSalesInvoicePostingRehearsal,
    rehearse_sales_invoice_posting,
    sales_invoice_rehearsal_payload,
)
from .sales_orders import (
    OperationalSalesOrder, OperationalSalesQuotation,
    accept_sales_quotation, convert_sales_quotation, create_sales_quotation,
    list_sales_orders, list_sales_quotations, replace_sales_quotation,
    sales_order_control_counts, transition_sales_quotation,
)
from .delivery_fulfillment import (
    OperationalDeliveryFulfillment, OperationalDeliveryReservation,
    OperationalDeliveryStockMovement, allocate_sales_order,
    delivery_control_counts, list_delivery_fulfillments, transition_delivery,
)
from .customer_invoices import (
    OperationalCustomerInvoice, OperationalCustomerInvoicePostingRehearsal,
    create_customer_invoice, customer_invoice_control_counts,
    customer_invoice_rehearsal_payload, list_customer_invoices,
    rehearse_customer_invoice, transition_customer_invoice,
)
from .purchase_returns import (
    OperationalPurchaseReturn, OperationalPurchaseReturnPostingRehearsal,
    create_purchase_return, list_purchase_returns,
    purchase_return_control_counts, rehearse_purchase_return_posting,
    replace_purchase_return, transition_purchase_return,
    _purchase_return_rehearsal_payload,
)
from .payments import (
    OperationalPayment, OperationalPaymentAllocationClaim,
    OperationalPaymentPostingRehearsal, create_payment,
    customer_invoice_open_items, customer_invoice_settlement,
    list_payments, payment_control_counts, rehearse_payment_posting,
    payment_rehearsal_payload, replace_payment, transition_payment,
)
from .cash_management import (
    OperationalCashAccount, OperationalStatementBatch, OperationalStatementLine,
    cash_account_payload, cash_management_payload, create_cash_account,
    create_statement_batch, decide_cash_account, explain_statement_line,
    match_statement_line, rehearse_reconciliation, statement_payload,
    transition_statement_batch,
)
from .expense_management import (
    OperationalExpenseClaim, OperationalPettyCashAdvance,
    create_expense_claim, create_petty_cash_advance, expense_claim_payload,
    expense_workspace_payload, petty_advance_payload, rehearse_expense,
    rehearse_petty_cash, transition_expense_claim, transition_petty_cash_advance,
)
from .fixed_assets import (
    OperationalFixedAsset, create_fixed_asset, decide_asset_disposal,
    fixed_asset_payload, fixed_asset_workspace_payload, rehearse_fixed_asset,
    request_asset_disposal, transition_fixed_asset,
)
from .vat_control import (
    OperationalVatAdjustment, OperationalVatPeriod, adjustment_payload as vat_adjustment_payload,
    create_vat_adjustment, create_vat_period, decide_vat_adjustment,
    rehearse_vat_return, transition_vat_period, vat_period_payload,
    vat_workspace_payload,
)
from .period_close import (
    OperationalCloseAdjustment, OperationalPeriodClose,
    close_adjustment_payload, create_close_adjustment, create_period_close,
    decide_close_adjustment, period_close_payload, period_close_workspace_payload,
    rehearse_period_close, transition_period_close,
)
from .close_reporting import (
    OperationalFinancialReportPackage, generate_report_package, pdf_bytes,
    report_package_payload, reporting_workspace_payload, transition_report_package,
    workbook_bytes,
)
from .audit_compliance import (
    OperationalStatutoryEvidencePackage, audit_compliance_workspace_payload,
    generate_statutory_package, statutory_json_bytes, statutory_package_payload,
    statutory_workbook_bytes, transition_statutory_package,
)
from .cutover_rehearsal import (
    OperationalCutoverRehearsalPackage, cutover_json_bytes,
    cutover_rehearsal_payload, cutover_rehearsal_workspace_payload,
    cutover_workbook_bytes, generate_cutover_rehearsal,
    transition_cutover_rehearsal,
)
from .completion_audit import completion_audit_payload
from .pos_counter import (
    OperationalPosShift, OperationalPosTill, approve_close, create_till,
    open_shift, pos_workspace_payload, record_sale, submit_close,
)
from .van_sales import (
    OperationalVanRoute, create_route, submit_load, sync_offline_event,
    transition_route, van_workspace_payload,
)
from .crm import add_activity, create_lead, create_proposal, crm_workspace_payload, decide_proposal
from .commercial_pricing import (
    OperationalCustomerPriceGroup, OperationalCustomerPriceGroupAssignment, OperationalPriceList,
    OperationalPriceListItem, OperationalPromotion, approve_price_list, approve_promotion,
    assign_customer_price_group, create_customer_price_group, create_price_list, create_promotion,
)
from .credit_management import (
    OperationalCollectionAction, OperationalCreditLimitRequest,
    OperationalCreditOverrideRequest, OperationalCustomerCreditProfile,
    OperationalDunningRequest, collection_action_payload,
    create_collection_action, create_credit_limit_request,
    create_credit_override_request, create_dunning_request,
    credit_override_payload, credit_request_payload, credit_workspace_payload,
    dunning_request_payload, set_credit_hold, transition_collection_action,
    transition_credit_limit_request, transition_credit_override_request,
    transition_dunning_request,
)
from .financial_reports import build_accounting_summary, build_ageing_report, build_customer_statement
from .hrm_lifecycle import (
    add_employee_document, create_candidate, create_lifecycle_case,
    create_workforce_request, decide_workforce_request, hrm_lifecycle_payload,
    move_candidate, transition_lifecycle_case,
)
from .posting_integration import (
    RESOURCE_TYPES,
    OperationalIntegratedPostingBatch,
    execute_integrated_posting,
    execute_integrated_reversal,
    get_posting_resource,
    integrated_posting_counts,
)
from .provisioned_users import load_provisioned_users
from .security_runtime import PersistentSessionStore, production_security_settings, validate_production_security
from .operational_masters import OperationalLocationMaster, OperationalPartyMaster, OperationalProductMaster
from .enterprise_setup import (
    add_branch, add_van, add_warehouse, enterprise_setup_payload,
    initialize_enterprise_setup, transition_operating_unit, update_company_profile,
)
from .finance_foundation import (
    OperationalChartAccount, decide_finance_approval, finance_foundation_payload, initialize_finance_foundation,
    request_finance_approval,
)
from .finance_reconciliation import (
    decide_reconciliation_review, finance_reconciliation_payload,
    initialize_finance_reconciliation, request_reconciliation_review,
)
from .finance_ledger import (
    OperationalGeneralJournal, create_general_journal, general_ledger_payload,
    replace_general_journal, transition_general_journal,
)
from .hrm import OperationalHrmAttendance, OperationalHrmEmployee, hrm_payload, initialize_hrm_test_data
from .hrm_operations import (
    assign_shift, create_attendance_correction, create_department, create_designation,
    create_holiday, create_leave_request, create_shift, decide_attendance_correction,
    decide_employee_change, decide_leave, hrm_operations_payload, initialize_hrm_operations,
    request_employee_change,
)
from .procurement import (
    award_quote, capture_quote, create_requisition, create_rfq, procurement_payload,
    transition_purchase_order, transition_requisition,
)
from .procurement_matching import (
    OperationalSupplierAdjustment, OperationalSupplierInvoice, adjustment_payload,
    approve_invoice_tolerance, create_supplier_adjustment, create_supplier_invoice,
    decide_policy_change, decide_supplier_invoice, evaluate_invoice_match,
    invoice_payload, policy_payload, rehearse_supplier_adjustment_posting,
    rehearse_supplier_invoice_posting, request_policy_change,
    transition_supplier_adjustment, validate_po_receipt,
)
from .access_control import (
    access_control_payload, assign_role, create_user_profile, effective_principal,
    initialize_access_profiles, revoke_role, set_user_status,
)
from .source_verification import source_verification_counts


STATIC_DIR = Path(__file__).with_name("static")
DEFAULT_SNAPSHOT = "bizmodo-2026-09-08-browser"
SESSION_COOKIE = "asas_erp_session"


def baseline_review_evidence(session: Session, snapshot: SourceSnapshot, entity_type: str,
                             source_record_key: str) -> tuple[dict, str] | None:
    document = session.scalar(select(ErpTransactionDocument).where(
        ErpTransactionDocument.snapshot_id == snapshot.id,
        ErpTransactionDocument.source_kind == entity_type,
        ErpTransactionDocument.document_no == source_record_key,
    ))
    if not document:
        return None
    party = session.get(ErpParty, document.party_id) if document.party_id else None
    location = session.get(ErpLocation, document.location_id) if document.location_id else None
    line_rows = session.execute(select(
        ErpTransactionLine, ErpProductMaster.sku, ErpProductMaster.name,
    ).outerjoin(ErpProductMaster, ErpProductMaster.id == ErpTransactionLine.product_id).where(
        ErpTransactionLine.document_id == document.id).order_by(ErpTransactionLine.source_line_no)).all()
    evidence = {
        "document_no": document.document_no, "source_kind": document.source_kind,
        "occurred_at": document.occurred_at, "total_amount": document.total_amount,
        "paid_amount": document.paid_amount, "due_amount": document.due_amount,
        "return_due_amount": document.return_due_amount, "source_status": document.source_status,
        "migration_status": document.migration_status,
        "party_name": party.legal_or_business_name if party else None,
        "location": location.code if location else None,
        "lines": [{
            "line_no": line.source_line_no,
            "sku": sku, "description": product_name,
            "entered_quantity": line.entered_quantity, "entered_uom": line.entered_uom,
            "unit_price": line.unit_price, "subtotal": line.subtotal,
            "relation_status": line.relation_status, "evidence": line.evidence,
        } for line, sku, product_name in line_rows],
    }
    return evidence, document.migration_status


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=500)


class CompanyProfileSetupRequest(BaseModel):
    legal_name: str | None = Field(default=None, min_length=2, max_length=500)
    registered_address: str | None = Field(default=None, max_length=2000)
    tax_registration_number: str | None = Field(default=None, max_length=120)
    trade_license_number: str | None = Field(default=None, max_length=120)
    logo_reference: str | None = Field(default=None, max_length=500)


class BranchSetupRequest(BaseModel):
    branch_code: str = Field(min_length=2, max_length=80, pattern="^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=300)


class WarehouseSetupRequest(BaseModel):
    branch_code: str = Field(min_length=2, max_length=80, pattern="^[A-Za-z0-9_-]+$")
    warehouse_code: str = Field(min_length=2, max_length=80, pattern="^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=300)
    warehouse_type: str = Field(pattern="^(available|returns|quarantine|in_transit)$")


class VanSetupRequest(BaseModel):
    van_code: str = Field(min_length=2, max_length=80, pattern="^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=300)
    assigned_branch_code: str = Field(min_length=2, max_length=80, pattern="^[A-Za-z0-9_-]+$")


class OperatingUnitDecisionRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    note: str = Field(min_length=5, max_length=2000)


class AccessUserRequest(BaseModel):
    login_name: str = Field(min_length=3, max_length=200, pattern="^[A-Za-z0-9._@-]+$")
    display_name: str = Field(min_length=2, max_length=300)


class AccessUserStatusRequest(BaseModel):
    status: str = Field(pattern="^(active|suspended|inactive|pending_provisioning)$")


class RoleAssignmentRequest(BaseModel):
    role_code: str = Field(min_length=2, max_length=80, pattern="^[a-z_]+$")
    company_code: str = Field(default="ASAS", min_length=2, max_length=40, pattern="^[A-Za-z0-9_-]+$")
    branch_code: str | None = Field(default=None, max_length=80)
    warehouse_code: str | None = Field(default=None, max_length=80)
    van_code: str | None = Field(default=None, max_length=80)
    approval_limit_aed: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    effective_from: date = Field(default_factory=date.today)
    effective_to: date | None = None


class HrmDepartmentRequest(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern="^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=200)


class HrmDesignationRequest(BaseModel):
    code: str = Field(min_length=2, max_length=60, pattern="^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=200)
    department_code: str = Field(min_length=2, max_length=40)


class HrmShiftRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    shift_type: str = Field(min_length=2, max_length=120)
    start_time: str | None = Field(default=None, max_length=40)
    end_time: str | None = Field(default=None, max_length=40)


class HrmHolidayRequest(BaseModel):
    holiday_date: date
    name: str = Field(min_length=2, max_length=200)
    department_code: str | None = Field(default=None, max_length=40)


class HrmEmployeeChangeRequest(BaseModel):
    employee_key: str = Field(min_length=1, max_length=200)
    employee_no: str = Field(min_length=1, max_length=60)
    department_code: str | None = Field(default=None, max_length=40)
    designation_code: str | None = Field(default=None, max_length=60)
    join_date: date | None = None
    employment_status: str = Field(pattern="^(active|on_leave|inactive|separated)$")
    note: str = Field(min_length=5, max_length=2000)


class HrmDecisionRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    note: str = Field(min_length=5, max_length=2000)


class HrmLeaveRequest(BaseModel):
    employee_key: str | None = Field(default=None, max_length=200)
    leave_type: str = Field(min_length=2, max_length=60)
    starts_on: date
    ends_on: date
    reason: str = Field(min_length=5, max_length=2000)


class HrmAttendanceCorrectionRequest(BaseModel):
    attendance_id: int = Field(ge=1)
    corrected_clock_in: str | None = Field(default=None, max_length=40)
    corrected_clock_out: str | None = Field(default=None, max_length=40)
    corrected_duration_minutes: int | None = Field(default=None, ge=0, le=10080)
    reason: str = Field(min_length=5, max_length=2000)


class HrmShiftAssignmentRequest(BaseModel):
    employee_key: str = Field(min_length=1, max_length=200)
    shift_name: str = Field(min_length=2, max_length=200)
    effective_from: date
    effective_to: date | None = None


class HrmWorkforceRequest(BaseModel):
    request_type: str = Field(pattern="^(new_position|replacement|temporary)$")
    department_code: str = Field(min_length=2, max_length=40)
    position_title: str = Field(min_length=2, max_length=200)
    headcount: int = Field(ge=1, le=100)
    needed_by: date
    justification: str = Field(min_length=5, max_length=2000)


class HrmCandidateRequest(BaseModel):
    workforce_request_key: str = Field(min_length=1, max_length=60)
    full_name: str = Field(min_length=2, max_length=300)
    contact_reference: str | None = Field(default=None, max_length=300)


class HrmCandidateStageRequest(BaseModel):
    stage: str = Field(pattern="^(screening|interview|offer|accepted|rejected)$")
    expected_revision: int = Field(ge=1)
    note: str = Field(min_length=5, max_length=2000)


class HrmEmployeeDocumentRequest(BaseModel):
    employee_key: str = Field(min_length=1, max_length=200)
    document_type: str = Field(pattern="^(passport|visa|emirates_id|work_permit|contract|certificate|other)$")
    document_number: str = Field(min_length=2, max_length=160)
    issued_on: date | None = None
    expires_on: date | None = None
    evidence_reference: str = Field(min_length=3, max_length=500)


class HrmLifecycleCaseRequest(BaseModel):
    employee_key: str = Field(min_length=1, max_length=200)
    case_type: str = Field(pattern="^(onboarding|performance|training|disciplinary|separation|end_of_service)$")
    subject: str = Field(min_length=3, max_length=300)
    effective_on: date
    details: str = Field(min_length=5, max_length=4000)
    evidence_reference: str | None = Field(default=None, max_length=500)


class ProcurementRequisitionLineRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=160)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    uom: str | None = Field(default=None, max_length=80)
    specification: str | None = Field(default=None, max_length=2000)


class ProcurementRequisitionRequest(BaseModel):
    needed_by: date
    location_code: str = Field(min_length=1, max_length=80)
    purpose: str = Field(min_length=5, max_length=2000)
    lines: list[ProcurementRequisitionLineRequest] = Field(min_length=1, max_length=100)


class ProcurementDecisionRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    note: str = Field(min_length=5, max_length=2000)


class ProcurementRfqRequest(BaseModel):
    requisition_key: str = Field(min_length=1, max_length=36)
    response_due_on: date
    supplier_codes: list[str] = Field(min_length=2, max_length=50)


class ProcurementQuoteLineRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=160)
    unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    tax_rate: Decimal = Field(default=Decimal("5"), ge=0, le=100, max_digits=7, decimal_places=4)


class ProcurementQuoteRequest(BaseModel):
    supplier_code: str = Field(min_length=1, max_length=80)
    supplier_reference: str | None = Field(default=None, max_length=160)
    quoted_on: date
    valid_until: date | None = None
    currency_code: str = Field(default="AED", min_length=3, max_length=3)
    delivery_days: int | None = Field(default=None, ge=0, le=3650)
    payment_terms: str | None = Field(default=None, max_length=500)
    lines: list[ProcurementQuoteLineRequest] = Field(min_length=1, max_length=100)


class ProcurementAwardRequest(ProcurementDecisionRequest):
    quotation_key: str = Field(min_length=1, max_length=36)
    expected_on: date | None = None


class SupplierInvoiceLineRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=160)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    tax_rate: Decimal = Field(default=Decimal("5"), ge=0, le=100, max_digits=7, decimal_places=4)


class SupplierInvoiceRequest(BaseModel):
    purchase_order_key: str = Field(min_length=1, max_length=36)
    supplier_invoice_no: str = Field(min_length=1, max_length=160)
    invoice_date: date
    due_date: date | None = None
    currency_code: str = Field(default="AED", min_length=3, max_length=3)
    document_type: str = Field(pattern="^(tax_invoice|simplified_tax_invoice|non_tax_invoice)$")
    supply_date: date | None = None
    supplier_name: str = Field(min_length=1, max_length=500)
    supplier_address: str = Field(min_length=1, max_length=2000)
    supplier_trn: str | None = Field(default=None, max_length=30)
    recipient_name: str = Field(min_length=1, max_length=500)
    recipient_address: str = Field(min_length=1, max_length=2000)
    recipient_trn: str | None = Field(default=None, max_length=30)
    lines: list[SupplierInvoiceLineRequest] = Field(min_length=1, max_length=100)


class MatchToleranceRequest(BaseModel):
    price_tolerance_pct: Decimal = Field(ge=0, le=100, max_digits=7, decimal_places=4)
    amount_tolerance: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    expected_revision: int = Field(ge=1)
    note: str = Field(min_length=5, max_length=2000)


class SupplierAdjustmentLineRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=160)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    tax_rate: Decimal | None = Field(default=None, ge=0, le=100, max_digits=7, decimal_places=4)


class SupplierAdjustmentRequest(BaseModel):
    invoice_key: str = Field(min_length=1, max_length=36)
    adjustment_type: str = Field(pattern="^(credit_note|debit_note)$")
    supplier_reference: str = Field(min_length=1, max_length=160)
    adjustment_date: date
    reason: str = Field(min_length=5, max_length=2000)
    accounting_treatment: str = Field(default="price_variance", pattern="^(price_variance|freight_landed_cost|administrative_expense)$")
    lines: list[SupplierAdjustmentLineRequest] = Field(min_length=1, max_length=100)


class FinanceApprovalSubmissionRequest(BaseModel):
    note: str = Field(min_length=5, max_length=2000)


class FinanceApprovalDecisionRequest(FinanceApprovalSubmissionRequest):
    expected_revision: int = Field(ge=1)


class FinanceReconciliationSubmissionRequest(BaseModel):
    resolution_type: str = Field(pattern="^(recheck_final_sync|source_correction_required|target_mapping_correction|accepted_test_variance)$")
    note: str = Field(min_length=5, max_length=2000)


class FinanceReconciliationDecisionRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    note: str = Field(min_length=5, max_length=2000)


class GeneralJournalLineRequest(BaseModel):
    account_code: str = Field(min_length=1, max_length=40)
    description: str | None = Field(default=None, max_length=500)
    debit: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=2)
    credit: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=2)


class GeneralJournalRequest(BaseModel):
    journal_date: date
    branch_code: str = Field(default="MAIN", min_length=1, max_length=80)
    reference: str | None = Field(default=None, max_length=200)
    description: str = Field(min_length=5, max_length=2000)
    lines: list[GeneralJournalLineRequest] = Field(min_length=2, max_length=100)


class GeneralJournalUpdateRequest(GeneralJournalRequest):
    expected_revision: int = Field(ge=1)


class GeneralJournalDecisionRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    note: str = Field(min_length=5, max_length=2000)


class DraftLineRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    uom: str = Field(min_length=1, max_length=80)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    tax_rate: Decimal = Field(default=Decimal("5"), ge=0, le=100, max_digits=7, decimal_places=4)


class DraftRequest(BaseModel):
    document_type: str = Field(pattern="^(sale|purchase)$")
    party_code: str = Field(min_length=1, max_length=80)
    location_code: str = Field(min_length=1, max_length=80)
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=2)
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[DraftLineRequest] = Field(min_length=1, max_length=100)


class DraftUpdateRequest(DraftRequest):
    expected_revision: int = Field(ge=1)


class DraftTransitionRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=2000)


class SalesQuotationRequest(BaseModel):
    customer_code: str = Field(min_length=1, max_length=80)
    location_code: str = Field(min_length=1, max_length=80)
    quotation_date: date
    valid_until: date
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=2)
    payment_terms: str | None = Field(default=None, max_length=500)
    delivery_terms: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)
    promotion_code: str | None = Field(default=None, max_length=80)
    lines: list[DraftLineRequest] = Field(min_length=1, max_length=100)


class CustomerPriceGroupRequest(BaseModel):
    group_code: str = Field(min_length=1, max_length=80, pattern="^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=200)


class CustomerPriceGroupAssignmentRequest(BaseModel):
    group_code: str = Field(min_length=1, max_length=80, pattern="^[A-Za-z0-9_-]+$")


class PriceListItemRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=4)


class PriceListRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    customer_group: str = Field(min_length=1, max_length=80)
    effective_from: date
    effective_to: date | None = None
    max_discount_percent: Decimal = Field(ge=0, le=100, max_digits=7, decimal_places=2)
    items: list[PriceListItemRequest] = Field(min_length=1, max_length=1000)


class PromotionRequest(BaseModel):
    promotion_code: str = Field(min_length=1, max_length=80, pattern="^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=200)
    customer_group: str = Field(min_length=1, max_length=80)
    sku: str | None = Field(default=None, max_length=100)
    discount_percent: Decimal = Field(gt=0, le=100, max_digits=7, decimal_places=2)
    effective_from: date
    effective_to: date | None = None


class SalesQuotationAcceptanceRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    acceptance_reference: str = Field(min_length=1, max_length=300)


class SalesOrderConversionRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    requested_delivery_date: date | None = None
    conversion_note: str = Field(min_length=5, max_length=2000)


class PosTillRequest(BaseModel):
    till_code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    location_code: str = Field(min_length=1, max_length=80)


class PosShiftOpenRequest(BaseModel):
    till_key: str = Field(min_length=1, max_length=36)
    business_date: date
    opening_float: Decimal = Field(ge=0, max_digits=18, decimal_places=2)


class PosSaleLineRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=160)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)


class PosSaleRequest(BaseModel):
    shift_key: str = Field(min_length=1, max_length=36)
    customer_name: str | None = Field(default=None, max_length=500)
    payment_method: str = Field(pattern="^(cash|card)$")
    amount_tendered: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    lines: list[PosSaleLineRequest] = Field(min_length=1, max_length=100)


class PosCloseRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    counted_cash: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    note: str = Field(min_length=5, max_length=2000)


class PosCloseApprovalRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    note: str = Field(min_length=5, max_length=2000)


class VanRouteRequest(BaseModel):
    van_code: str = Field(min_length=1, max_length=80)
    route_date: date
    driver_name: str = Field(min_length=1, max_length=200)
    device_id: str = Field(min_length=1, max_length=100)
    opening_float: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    customer_codes: list[str] = Field(min_length=1, max_length=100)


class VanLoadRequest(BaseModel):
    source_location: str = Field(min_length=1, max_length=80)
    lines: list[PosSaleLineRequest] = Field(min_length=1, max_length=200)
    expected_revision: int = Field(ge=1)


class VanTransitionRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    note: str = Field(min_length=5, max_length=2000)
    counted_cash: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)


class VanOfflineEventRequest(BaseModel):
    route_key: str = Field(min_length=1, max_length=36)
    device_id: str = Field(min_length=1, max_length=100)
    client_reference: str = Field(min_length=1, max_length=100)
    event_type: str = Field(pattern="^(sale|return|collection)$")
    customer_code: str = Field(min_length=1, max_length=80)
    captured_at: datetime
    payment_method: str | None = Field(default=None, pattern="^(cash|card|bank)$")
    amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    evidence_reference: str | None = Field(default=None, max_length=300)
    lines: list[PosSaleLineRequest] = Field(default_factory=list, max_length=100)


class CrmLeadRequest(BaseModel):
    company_name: str = Field(min_length=2, max_length=300)
    contact_name: str | None = Field(default=None, max_length=200)
    contact_email: str | None = Field(default=None, max_length=300)
    source: str = Field(min_length=2, max_length=80)
    owner: str = Field(min_length=2, max_length=200)
    follow_up_at: datetime | None = None


class CrmActivityRequest(BaseModel):
    activity_type: str = Field(pattern="^(call|meeting|email|note)$")
    note: str = Field(min_length=5, max_length=2000)
    due_at: datetime | None = None


class CrmProposalRequest(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    value_aed: Decimal = Field(gt=0, max_digits=18, decimal_places=2)


class CrmProposalDecisionRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    note: str = Field(min_length=5, max_length=2000)


class DeliveryAllocationRequest(BaseModel):
    note: str = Field(min_length=5, max_length=2000)


class DeliveryActionRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    note: str = Field(min_length=5, max_length=2000)


class DeliveryDispatchRequest(DeliveryActionRequest):
    vehicle_number: str | None = Field(default=None, max_length=100)
    driver_name: str | None = Field(default=None, max_length=200)
    dispatched_at: datetime | None = None


class ProofOfDeliveryRequest(DeliveryActionRequest):
    received_by: str = Field(min_length=1, max_length=200)
    pod_reference: str = Field(min_length=1, max_length=300)
    delivered_at: datetime | None = None


class CustomerInvoiceCreateRequest(BaseModel):
    invoice_date: date
    due_date: date
    notes: str | None = Field(default=None, max_length=2000)


class PostingExecutionRequest(BaseModel):
    idempotency_key: str = Field(min_length=20, max_length=160)


class ReversalExecutionRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)


class InventoryLineRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    uom: str = Field(min_length=1, max_length=80)
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)


class InventoryDocumentRequest(BaseModel):
    document_type: str = Field(pattern="^(transfer|adjustment)$")
    location_code: str = Field(min_length=1, max_length=80)
    destination_location_code: str | None = Field(default=None, max_length=80)
    adjustment_direction: str | None = Field(default=None, pattern="^(increase|decrease)$")
    reason_code: str = Field(min_length=2, max_length=40)
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[InventoryLineRequest] = Field(min_length=1, max_length=100)


class CycleCountLineRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    counted_quantity_base: Decimal = Field(ge=0, max_digits=18, decimal_places=6)


class CycleCountRequest(BaseModel):
    location_code: str = Field(min_length=1, max_length=80)
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[CycleCountLineRequest] = Field(min_length=1, max_length=1000)


class QuarantineHoldRequest(BaseModel):
    location_code: str = Field(min_length=1, max_length=80)
    sku: str = Field(min_length=1, max_length=100)
    quantity_base: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    reason: str = Field(min_length=5, max_length=2000)


class BarcodeRegistrationRequest(BaseModel):
    barcode_value: str = Field(min_length=4, max_length=80, pattern="^[A-Za-z0-9][A-Za-z0-9._/-]+$")
    sku: str = Field(min_length=1, max_length=100)
    location_code: str = Field(min_length=1, max_length=80)
    factor_to_base: Decimal = Field(gt=0, max_digits=18, decimal_places=6)


class SerialRegistrationRequest(BaseModel):
    serial_number: str = Field(min_length=4, max_length=80, pattern="^[A-Za-z0-9][A-Za-z0-9._/-]+$")
    sku: str = Field(min_length=1, max_length=100)
    location_code: str = Field(min_length=1, max_length=80)


class WarehouseScanRequest(BaseModel):
    scanned_value: str = Field(min_length=4, max_length=80, pattern="^[A-Za-z0-9][A-Za-z0-9._/-]+$")
    location_code: str = Field(min_length=1, max_length=80)


class SerialTransitionRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    note: str = Field(min_length=5, max_length=2000)


class GoodsReceiptLineRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    ordered_quantity: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    received_quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    accepted_quantity: Decimal = Field(ge=0, max_digits=18, decimal_places=6)
    rejected_quantity: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=6)
    uom: str = Field(min_length=1, max_length=80)
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    batch_no: str | None = Field(default=None, max_length=160)
    expiry_date: date | None = None
    rejection_reason: str | None = Field(default=None, max_length=500)


class GoodsReceiptRequest(BaseModel):
    supplier_code: str = Field(min_length=1, max_length=80)
    location_code: str = Field(min_length=1, max_length=80)
    purchase_reference: str | None = Field(default=None, max_length=160)
    supplier_delivery_note: str | None = Field(default=None, max_length=160)
    received_on: date
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[GoodsReceiptLineRequest] = Field(min_length=1, max_length=100)


class SalesReturnLineRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    restock_quantity: Decimal = Field(ge=0, max_digits=18, decimal_places=6)
    writeoff_quantity: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=6)
    uom: str = Field(min_length=1, max_length=80)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    tax_rate: Decimal = Field(default=Decimal("5"), ge=0, le=100, max_digits=7, decimal_places=4)
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    disposition_reason: str | None = Field(default=None, max_length=500)


class SalesReturnRequest(BaseModel):
    customer_code: str = Field(min_length=1, max_length=80)
    location_code: str = Field(min_length=1, max_length=80)
    original_invoice_reference: str = Field(min_length=1, max_length=160)
    return_date: date
    reason_code: str = Field(min_length=2, max_length=80)
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[SalesReturnLineRequest] = Field(min_length=1, max_length=100)


class PurchaseReturnLineRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    supplier_return_quantity: Decimal = Field(ge=0, max_digits=18, decimal_places=6)
    internal_writeoff_quantity: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=6)
    uom: str = Field(min_length=1, max_length=80)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    tax_rate: Decimal = Field(default=Decimal("5"), ge=0, le=100, max_digits=7, decimal_places=4)
    disposition_reason: str | None = Field(default=None, max_length=500)


class PurchaseReturnRequest(BaseModel):
    supplier_code: str = Field(min_length=1, max_length=80)
    location_code: str = Field(min_length=1, max_length=80)
    source_reference_type: str = Field(pattern="^(goods_receipt|purchase_invoice)$")
    source_reference_key: str = Field(min_length=1, max_length=160)
    return_date: date
    reason_code: str = Field(min_length=2, max_length=80)
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[PurchaseReturnLineRequest] = Field(min_length=1, max_length=100)


class PaymentAllocationRequest(BaseModel):
    source_type: str = Field(pattern="^(invoice|opening_balance)$")
    source_reference_key: str = Field(min_length=1, max_length=160)
    allocation_amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)


class PaymentRequest(BaseModel):
    payment_type: str = Field(pattern="^(customer_receipt|supplier_payment)$")
    party_code: str = Field(min_length=1, max_length=80)
    location_code: str = Field(min_length=1, max_length=80)
    payment_date: date
    payment_method: str = Field(pattern="^(cash|bank_transfer|card|cheque|other)$")
    cash_bank_account_code: str = Field(min_length=1, max_length=80)
    reference_no: str | None = Field(default=None, max_length=160)
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    notes: str | None = Field(default=None, max_length=2000)
    allocations: list[PaymentAllocationRequest] = Field(default_factory=list, max_length=100)


class CashAccountRequest(BaseModel):
    account_code: str = Field(min_length=1, max_length=80)
    account_name: str = Field(min_length=1, max_length=200)
    account_type: str = Field(pattern="^(bank|cash)$")
    bank_name: str | None = Field(default=None, max_length=200)
    identifier: str | None = Field(default=None, max_length=64)
    gl_account_code: str = Field(min_length=1, max_length=80)
    location_code: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=5, max_length=2000)


class CashDecisionRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    note: str = Field(min_length=5, max_length=2000)


class StatementLineRequest(BaseModel):
    external_id: str = Field(min_length=1, max_length=160)
    transaction_date: date
    value_date: date | None = None
    reference: str | None = Field(default=None, max_length=160)
    description: str = Field(min_length=1, max_length=500)
    debit_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=2)
    credit_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=2)


class StatementBatchRequest(BaseModel):
    account_key: str = Field(min_length=1, max_length=36)
    statement_reference: str = Field(min_length=1, max_length=160)
    statement_start: date
    statement_end: date
    opening_balance: Decimal = Field(max_digits=18, decimal_places=2)
    closing_balance: Decimal = Field(max_digits=18, decimal_places=2)
    source_file_name: str = Field(min_length=1, max_length=255)
    lines: list[StatementLineRequest] = Field(min_length=1, max_length=2000)


class StatementMatchRequest(BaseModel):
    payment_key: str = Field(min_length=1, max_length=36)


class StatementExceptionRequest(BaseModel):
    category: str = Field(pattern="^(bank_fee|bank_interest|timing_difference|bank_error|other)$")
    reason: str = Field(min_length=5, max_length=2000)


class StatementDecisionRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=2000)


class ExpenseClaimRequest(BaseModel):
    claimant_type: str = Field(pattern="^(employee|supplier|company)$")
    claimant_reference: str | None = Field(default=None, max_length=80)
    claimant_name: str = Field(min_length=1, max_length=200)
    expense_date: date
    location_code: str = Field(min_length=1, max_length=80)
    cost_center: str = Field(min_length=1, max_length=80)
    category_code: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    receipt_reference: str = Field(min_length=1, max_length=200)
    tax_invoice_no: str | None = Field(default=None, max_length=160)
    supplier_trn: str | None = Field(default=None, max_length=15)
    vat_rate: Decimal = Field(ge=0, le=100, max_digits=7, decimal_places=4)
    net_amount: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    vat_amount: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    settlement_method: str = Field(pattern="^(reimbursement|direct_payment|petty_cash)$")
    payment_account_key: str | None = Field(default=None, max_length=36)


class ExpenseActionRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=2000)


class PettyCashAdvanceRequest(BaseModel):
    recipient_reference: str | None = Field(default=None, max_length=80)
    recipient_name: str = Field(min_length=1, max_length=200)
    location_code: str = Field(min_length=1, max_length=80)
    cost_center: str = Field(min_length=1, max_length=80)
    account_key: str = Field(min_length=1, max_length=36)
    requested_on: date
    due_on: date
    purpose: str = Field(min_length=5, max_length=500)
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)


class PettyCashActionRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=2000)
    spent_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    returned_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    category_code: str | None = Field(default=None, max_length=80)
    receipt_reference: str | None = Field(default=None, max_length=200)


class FixedAssetCreateRequest(BaseModel):
    asset_name: str = Field(min_length=1, max_length=200)
    category_code: str = Field(min_length=1, max_length=80)
    supplier_reference: str | None = Field(default=None, max_length=120)
    acquisition_reference: str = Field(min_length=1, max_length=160)
    acquisition_date: date
    available_for_use_date: date
    location_code: str = Field(min_length=1, max_length=80)
    cost_center: str = Field(min_length=1, max_length=80)
    custodian: str | None = Field(default=None, max_length=200)
    serial_number: str | None = Field(default=None, max_length=160)
    useful_life_months: int = Field(ge=1, le=600)
    cost_amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    residual_value: Decimal = Field(ge=0, max_digits=18, decimal_places=2)


class FixedAssetActionRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=2000)


class FixedAssetDisposalRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    disposal_date: date
    disposal_proceeds: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    reason: str = Field(min_length=5, max_length=2000)


class FixedAssetRehearsalRequest(BaseModel):
    stage: str = Field(pattern="^(capitalization|depreciation|disposal)$")
    as_of_date: date


class VatPeriodCreateRequest(BaseModel):
    period_code: str = Field(min_length=1, max_length=80)
    starts_on: date
    ends_on: date
    due_on: date
    company_trn: str = Field(pattern=r"^\d{15}$")


class VatWorkflowRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=2000)


class VatAdjustmentCreateRequest(BaseModel):
    adjustment_type: str = Field(pattern="^(output_increase|output_decrease|input_increase|input_decrease|reverse_charge)$")
    adjustment_date: date
    evidence_reference: str = Field(min_length=3, max_length=200)
    reason: str = Field(min_length=5, max_length=2000)
    taxable_amount: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    vat_amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    recovery_percent: Decimal = Field(ge=0, le=100, max_digits=7, decimal_places=4)


class PeriodCloseCreateRequest(BaseModel):
    fiscal_period_key: str = Field(min_length=1, max_length=20)


class PeriodCloseWorkflowRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=2000)


class CloseAdjustmentCreateRequest(BaseModel):
    adjustment_type: str = Field(pattern="^(accrual|prepayment|fx_revaluation|inventory_valuation)$")
    adjustment_date: date
    debit_account: str = Field(min_length=2, max_length=120)
    credit_account: str = Field(min_length=2, max_length=120)
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    reversal_on: date | None = None
    evidence_reference: str = Field(min_length=3, max_length=200)
    reason: str = Field(min_length=5, max_length=2000)


class CreditLimitRequestCreate(BaseModel):
    party_code: str = Field(min_length=1, max_length=80)
    proposed_limit: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    proposed_terms_days: int = Field(ge=0, le=3650)
    reason: str = Field(min_length=5, max_length=2000)


class CreditWorkflowRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    note: str = Field(min_length=5, max_length=2000)


class CreditOverrideRequestCreate(BaseModel):
    quotation_key: str = Field(min_length=1, max_length=36)
    valid_until: date
    reason: str = Field(min_length=5, max_length=2000)


class DunningRequestCreate(BaseModel):
    party_code: str = Field(min_length=1, max_length=80)
    stage: str = Field(pattern="^(reminder_1|reminder_2|final_notice|legal_referral)$")
    reason: str = Field(min_length=5, max_length=2000)


class CollectionActionCreate(BaseModel):
    party_code: str = Field(min_length=1, max_length=80)
    invoice_no: str | None = Field(default=None, max_length=80)
    action_date: date
    action_type: str = Field(pattern="^(call|email|visit|promise_to_pay|final_notice|legal_referral)$")
    outcome: str = Field(min_length=3, max_length=2000)
    next_followup_date: date | None = None
    promise_amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    promise_date: date | None = None


class CollectionTransitionRequest(BaseModel):
    expected_revision: int = Field(ge=1)


class ProductMasterUpdateRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=500)
    category_name: str | None = Field(default=None, max_length=200)
    brand_name: str | None = Field(default=None, max_length=200)
    purchase_price: Decimal = Field(ge=0, max_digits=18, decimal_places=6)
    selling_price: Decimal = Field(ge=0, max_digits=18, decimal_places=6)
    tax_rate: Decimal = Field(ge=0, le=100, max_digits=7, decimal_places=4)


class PartyMasterUpdateRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    legal_or_business_name: str = Field(min_length=1, max_length=500)
    contact_name: str | None = Field(default=None, max_length=300)
    email: str | None = Field(default=None, max_length=320)
    mobile: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=2000)
    tax_number: str | None = Field(default=None, max_length=120)


class MasterStatusRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=500)


class DataReviewStartRequest(BaseModel):
    entity_type: str = Field(pattern="^(sale|purchase|sale_return|purchase_return)$")
    source_record_key: str = Field(min_length=1, max_length=200)


class DataReviewActionRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    rationale: str | None = Field(default=None, max_length=2000)
    corrected_payload: dict | None = None


# Server-owned route policy consumed by the sidebar, hash router and command
# centre. Routes omitted here are authenticated read workspaces for every user.
NAVIGATION_PERMISSION_RULES: dict[str, frozenset[str]] = {
    "company-setup": frozenset({"enterprise.setup", "enterprise.approve"}),
    "users-roles": frozenset({"access.review", "user.manage", "role.manage", "enterprise.setup"}),
    "hrm": frozenset({"hrm.read", "hrm.manage", "hrm.self.read", "enterprise.setup"}),
    "crm": frozenset({"crm.read"}),
    "pos": frozenset({"pos.read"}),
    "van-sales": frozenset({"van.read"}),
    "sales-orders": frozenset({"draft.create", "draft.approve", "price_list.manage", "discount.approve"}),
    "deliveries": frozenset({"delivery.allocate", "delivery.pick", "delivery.dispatch", "delivery.pod", "delivery.cancel", "inventory.create", "inventory.edit", "inventory.submit", "inventory.approve", "inventory.cancel"}),
    "customer-invoices": frozenset({"customer_invoice.create", "customer_invoice.submit", "customer_invoice.approve", "customer_invoice.rehearse", "draft.create", "draft.approve"}),
    "procurement": frozenset({"purchase.requisition.create", "purchase.requisition.approve", "rfq.create", "supplier_quote.manage", "purchase_order.prepare", "purchase_order.approve", "supplier_bill.prepare", "supplier_bill.approve", "supplier_bill.tolerance.approve", "supplier_bill.rehearse", "supplier_adjustment.prepare", "supplier_adjustment.approve", "match_tolerance.prepare", "match_tolerance.approve", "enterprise.setup"}),
    "drafts": frozenset({"draft.create", "draft.edit", "draft.submit", "draft.approve", "draft.cancel", "draft.rehearse"}),
    "inventory-operations": frozenset({"inventory.create", "inventory.edit", "inventory.submit", "inventory.approve", "inventory.cancel", "inventory.rehearse"}),
    "warehouse-controls": frozenset({"stock.count", "quarantine.manage", "barcode.manage", "serial.manage", "warehouse.scan", "inventory.submit", "inventory.approve"}),
    "goods-receipts": frozenset({"goods_receipt.create", "goods_receipt.edit", "goods_receipt.submit", "goods_receipt.accept", "goods_receipt.reject", "goods_receipt.rehearse"}),
    "sales-returns": frozenset({"sales_return.create", "sales_return.edit", "sales_return.submit", "sales_return.approve", "sales_return.cancel", "sales_return.rehearse"}),
    "purchase-returns": frozenset({"purchase_return.create", "purchase_return.edit", "purchase_return.submit", "purchase_return.approve", "purchase_return.cancel", "purchase_return.rehearse"}),
    "payments": frozenset({"payment.prepare", "payment.create", "payment.edit", "payment.submit", "payment.approve", "payment.cancel", "payment.rehearse"}),
    "cash-management": frozenset({"cash.account.prepare", "cash.account.approve", "bank.statement.import", "bank.reconcile.prepare", "bank.reconcile.approve", "bank.reconcile.rehearse"}),
    "expenses": frozenset({"expense.prepare", "expense.submit", "expense.approve", "expense.rehearse", "petty_cash.prepare", "petty_cash.approve", "petty_cash.manage"}),
    "fixed-assets": frozenset({"fixed_asset.prepare", "fixed_asset.submit", "fixed_asset.approve", "fixed_asset.disposal.prepare", "fixed_asset.disposal.approve", "fixed_asset.rehearse"}),
    "vat-control": frozenset({"vat.period.prepare", "vat.period.submit", "vat.period.approve", "vat.adjustment.prepare", "vat.adjustment.approve", "vat.rehearse"}),
    "period-close": frozenset({"close.prepare", "close.submit", "close.approve", "close.adjustment.prepare", "close.adjustment.approve", "close.rehearse"}),
    "chart-of-accounts": frozenset({"financial_report.read", "finance.chart.prepare", "finance.chart.approve", "finance.mapping.prepare", "finance.mapping.approve"}),
    "financial-statements": frozenset({"financial_report.read", "financial_report.prepare", "financial_report.submit", "financial_report.approve", "financial_report.export"}),
    "ageing": frozenset({"financial_report.read"}),
    "customer-statements": frozenset({"financial_report.read"}),
    "credit-control": frozenset({"financial_report.read", "credit.review", "credit.limit.manage", "credit.limit.prepare", "credit.limit.approve", "credit.hold.release", "credit.override.prepare", "credit.override.approve", "collection.manage", "collection.escalation.prepare", "collection.escalation.approve"}),
    "accounting": frozenset({"financial_report.read", "finance.chart.prepare", "finance.chart.approve", "finance.mapping.prepare", "finance.mapping.approve", "finance.reconciliation.prepare", "finance.reconciliation.approve"}),
    "general-ledger": frozenset({"financial_report.read", "journal.prepare", "journal.approve"}),
    "audit-compliance": frozenset({"audit_compliance.read", "audit_compliance.prepare", "audit_compliance.submit", "audit_compliance.approve", "audit_compliance.export"}),
    "cutover-rehearsal": frozenset({"cutover_rehearsal.read", "cutover_rehearsal.prepare", "cutover_rehearsal.submit", "cutover_rehearsal.approve", "cutover_rehearsal.export"}),
    "reviews": frozenset({"migration.review"}),
}


def navigation_access(permissions) -> dict[str, object]:
    granted = set(permissions)
    return {"denied_routes": sorted(route for route, required in NAVIGATION_PERMISSION_RULES.items()
                                     if required.isdisjoint(granted)),
            "policy_version": "2026-09-21"}


def create_app(database_url: str | None = None, snapshot_name: str | None = None,
               delta_capture: Path | bool | None = None) -> FastAPI:
    engine = make_engine(database_url)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    selected_snapshot = snapshot_name or os.getenv("KLEN_SNAPSHOT", DEFAULT_SNAPSHOT)
    app = FastAPI(
        title="Asas ERP Preview",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        description="Independent ERP staging application backed by preserved BizModo evidence and a separate operational database.",
    )
    app.state.engine = engine
    app.state.snapshot_name = selected_snapshot
    security_settings = production_security_settings()
    app.state.production_mode = security_settings["production"]
    app.state.auth_enabled = os.getenv("ASAS_AUTH_ENABLED", "false").lower() == "true"
    app.state.admin_username = os.getenv("ASAS_ADMIN_USERNAME", "").strip()
    app.state.admin_password_hash = os.getenv("ASAS_ADMIN_PASSWORD_HASH", "").strip()
    app.state.session_ttl = int(os.getenv("ASAS_SESSION_TTL_SECONDS", "1800"))
    if not 300 <= app.state.session_ttl <= 43_200:
        raise RuntimeError("ASAS_SESSION_TTL_SECONDS must be between 300 and 43200")
    app.state.users_by_login, app.state.users_by_id = load_provisioned_users(
        os.getenv("ASAS_USERS_FILE"), app.state.admin_username, app.state.admin_password_hash,
    )
    operational_url = os.getenv("ASAS_OPERATIONAL_DATABASE_URL", "").strip()
    validate_production_security(security_settings, auth_enabled=app.state.auth_enabled,
                                 operational_url=operational_url)
    app.state.posting_enabled = security_settings["posting_requested"] and (
        not app.state.production_mode or (
            security_settings["posting_confirmed"]
            and len(security_settings["posting_approval_reference"]) >= 8
        )
    )
    app.state.secure_cookies = security_settings["secure_cookies"]
    app.state.session_cookie_name = "__Host-asas_erp_session" if app.state.production_mode else SESSION_COOKIE
    app.state.posting_approval_reference = security_settings["posting_approval_reference"]
    if app.state.auth_enabled and not app.state.users_by_login:
        raise RuntimeError("Asas authentication is enabled but administrator credentials are not provisioned")
    app.state.operational_engine = make_operational_engine(operational_url) if operational_url else None
    app.state.operational_sessions = operational_session_factory(app.state.operational_engine) if operational_url else None
    if app.state.operational_engine:
        initialize_operational_database(app.state.operational_engine)
        with app.state.operational_sessions() as operational_session:
            initialize_enterprise_setup(operational_session)
            initialize_finance_foundation(operational_session)
            initialize_access_profiles(operational_session, app.state.users_by_id.values())
            with sessions() as clone_session:
                finance_snapshot = clone_session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == selected_snapshot))
                if finance_snapshot is not None:
                    hrm_batch = initialize_hrm_test_data(clone_session, operational_session, finance_snapshot)
                    initialize_hrm_operations(operational_session, hrm_batch)
                    finance_summary = build_accounting_summary(
                        clone_session, operational_session, snapshot_id=finance_snapshot.id,
                    )
                    initialize_finance_reconciliation(
                        operational_session, snapshot_name=finance_snapshot.name,
                        trial_balance=finance_summary["trial_balance"],
                    )
    app.state.sessions = (PersistentSessionStore(app.state.operational_sessions, security_settings["session_secret"])
                          if app.state.production_mode else UatSessionStore())
    if security_settings["allowed_hosts"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(security_settings["allowed_hosts"]))
    if delta_capture is False or (delta_capture is None and database_url is not None):
        app.state.delta_overlay = None
    else:
        app.state.delta_overlay = load_delta_overlay(delta_capture if isinstance(delta_capture, Path) else None)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def session_dependency():
        with sessions() as session:
            yield session

    def snapshot_dependency(session: Session = Depends(session_dependency)) -> SourceSnapshot:
        snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == selected_snapshot))
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Configured BizModo clone snapshot is unavailable")
        return snapshot

    def active_session(request: Request):
        return app.state.sessions.get(request.cookies.get(app.state.session_cookie_name))

    def resolve_principal(principal):
        if principal is None or app.state.operational_sessions is None:
            return principal
        with app.state.operational_sessions() as operational_session:
            return effective_principal(operational_session, principal)

    def current_user(request: Request):
        current = active_session(request)
        return resolve_principal(app.state.users_by_id.get(current.principal_id)) if current else None

    def require_user(request: Request, permission: str):
        if not app.state.auth_enabled:
            return None
        user = current_user(request)
        if not user:
            raise HTTPException(status_code=401, detail="Authentication required")
        if permission not in user.permissions:
            raise HTTPException(status_code=403, detail=f"Permission {permission} is required")
        return user

    def principal_payload(user) -> dict:
        return {"login_name": user.username, "roles": list(user.roles),
                "permissions": list(user.permissions),
                "allowed_locations": list(user.allowed_locations),
                "navigation": navigation_access(user.permissions),
                "posting_enabled": app.state.posting_enabled}

    def location_allowed(user, location_code: str) -> bool:
        allowed = set(user.allowed_locations)
        return "*" in allowed or location_code.upper() in allowed

    def operational_session_dependency():
        if app.state.operational_sessions is None:
            raise HTTPException(status_code=503, detail="Operational database is not configured")
        with app.state.operational_sessions() as operational_session:
            yield operational_session

    def optional_operational_session_dependency():
        if app.state.operational_sessions is None:
            yield None
            return
        with app.state.operational_sessions() as operational_session:
            yield operational_session

    def audit(session: Session, snapshot_id: int, event_type: str, outcome: str, request: Request) -> None:
        client = request.client.host if request.client else "unknown"
        if app.state.production_mode and app.state.operational_sessions:
            with app.state.operational_sessions() as operational_session:
                operational_session.add(OperationalAuditEvent(
                    event_key=str(uuid.uuid4()), event_type=event_type,
                    actor="authentication_service", resource_key=None,
                    detail=f"outcome={outcome}; client_sha256={hashlib.sha256(client.encode()).hexdigest()}",
                ))
                operational_session.commit()
            return
        session.add(ErpAuditEvent(
            snapshot_id=snapshot_id,
            event_key=f"asas-auth:{uuid.uuid4()}",
            event_type=event_type,
            actor_type="provisioned_preview_admin",
            details={"outcome": outcome, "client": client, "posting_enabled": False},
        ))
        session.commit()

    def secure_response(response, request_id: str):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = ("default-src 'self'; base-uri 'self'; object-src 'none'; "
            "frame-ancestors 'none'; form-action 'self'; style-src 'self'; script-src 'self'; connect-src 'self'")
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
        if app.state.production_mode:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Request-ID"] = request_id
        return response

    @app.middleware("http")
    async def preview_safety(request: Request, call_next):
        request_id = request.headers.get("x-request-id", "").strip()
        if not request_id or len(request_id) > 128:
            request_id = str(uuid.uuid4())
        if (app.state.production_mode and request.url.path != "/api/v1/health"
                and request.url.scheme != "https"):
            return secure_response(RedirectResponse(str(request.url.replace(scheme="https")), status_code=307), request_id)
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > 2 * 1024 * 1024:
            return secure_response(JSONResponse(status_code=413, content={"detail": "Request body is too large"}), request_id)
        auth_posts = {"/api/v1/auth/login", "/api/v1/auth/logout"}
        operational_mutation = (request.url.path.startswith("/api/v1/drafts")
                                or request.url.path.startswith("/api/v1/journal-batches")
                                or request.url.path.startswith("/api/v1/inventory-documents")
                                or request.url.path.startswith("/api/v1/warehouse-controls")
                                or request.url.path.startswith("/api/v1/goods-receipts")
                                or request.url.path.startswith("/api/v1/sales-returns")
                                or request.url.path.startswith("/api/v1/sales-orders")
                                or request.url.path.startswith("/api/v1/commercial-pricing")
                                or request.url.path.startswith("/api/v1/deliveries")
                                or request.url.path.startswith("/api/v1/customer-invoices")
                                or request.url.path.startswith("/api/v1/pos")
                                or request.url.path.startswith("/api/v1/van-sales")
                                or request.url.path.startswith("/api/v1/crm")
                                or request.url.path.startswith("/api/v1/credit-control")
                                or request.url.path.startswith("/api/v1/purchase-returns")
                                or request.url.path.startswith("/api/v1/payments")
                                or request.url.path.startswith("/api/v1/cash-management")
                                or request.url.path.startswith("/api/v1/expense-management")
                                or request.url.path.startswith("/api/v1/fixed-assets")
                                or request.url.path.startswith("/api/v1/vat-control")
                                or request.url.path.startswith("/api/v1/period-close")
                                or request.url.path.startswith("/api/v1/close-reporting")
                                or request.url.path.startswith("/api/v1/audit-compliance")
                                or request.url.path.startswith("/api/v1/cutover-rehearsal")
                                or request.url.path.startswith("/api/v1/posting/")
                                or request.url.path.startswith("/api/v1/integrated-posting-batches")
                                or request.url.path.startswith("/api/v1/data-reviews")
                                or request.url.path.startswith("/api/v1/master-data/")
                                or request.url.path.startswith("/api/v1/setup/enterprise")
                                or request.url.path.startswith("/api/v1/finance/approvals")
                                or request.url.path.startswith("/api/v1/finance/reconciliation")
                                or request.url.path.startswith("/api/v1/general-ledger")
                                or request.url.path.startswith("/api/v1/access-control")
                                or request.url.path.startswith("/api/v1/hrm/")
                                or request.url.path.startswith("/api/v1/procurement")) and request.method in {"POST", "PUT", "PATCH", "DELETE"}
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path not in auth_posts and not operational_mutation:
            return secure_response(JSONResponse(
                status_code=405,
                content={"detail": "Read-only clone preview: operational writes are not enabled"},
                headers={"Allow": "GET, HEAD, OPTIONS"},
            ), request_id)
        public_api = {"/api/v1/health", "/api/v1/auth/login", "/api/v1/auth/session"}
        if (app.state.auth_enabled and request.url.path.startswith("/api/v1/")
                and request.url.path not in public_api and active_session(request) is None):
            return secure_response(JSONResponse(status_code=401, content={"detail": "Asas ERP authentication required"}), request_id)
        response = await call_next(request)
        return secure_response(response, request_id)

    @app.get("/", include_in_schema=False)
    def index(request: Request):
        if app.state.auth_enabled and active_session(request) is None:
            return RedirectResponse("/login", status_code=303)
        return FileResponse(STATIC_DIR / "erp.html")

    @app.get("/login", include_in_schema=False)
    def login_page(request: Request):
        if app.state.auth_enabled and active_session(request) is not None:
            return RedirectResponse("/", status_code=303)
        return FileResponse(STATIC_DIR / "asas-login.html")

    @app.get("/draft-review.html", include_in_schema=False)
    def draft_review_page(request: Request):
        if app.state.auth_enabled and active_session(request) is None:
            return RedirectResponse("/login", status_code=303)
        return FileResponse(STATIC_DIR / "draft-review.html")

    @app.post("/api/v1/auth/login")
    def login(payload: LoginRequest, request: Request, session: Session = Depends(session_dependency)):
        if not app.state.auth_enabled:
            raise HTTPException(status_code=404, detail="Asas ERP authentication is not enabled")
        attempt_key = f"{request.client.host if request.client else 'unknown'}:{payload.username.casefold()}"
        snapshot_id = session.scalar(select(SourceSnapshot.id).where(SourceSnapshot.name == selected_snapshot))
        if not app.state.sessions.allow_attempt(attempt_key):
            if snapshot_id:
                audit(session, snapshot_id, "auth.login", "rate_limited", request)
            raise HTTPException(status_code=429, detail="Too many sign-in attempts; try again later")
        user = app.state.users_by_login.get(payload.username.strip().casefold())
        valid = bool(user and verify_password(payload.password, user.password_hash))
        if not valid:
            if snapshot_id:
                audit(session, snapshot_id, "auth.login", "denied", request)
            raise HTTPException(status_code=401, detail="Invalid username or password")
        user = resolve_principal(user)
        if user is None:
            if snapshot_id:
                audit(session, snapshot_id, "auth.login", "access_profile_disabled", request)
            raise HTTPException(status_code=403, detail="This ERP access profile is not active")
        app.state.sessions.clear_attempts(attempt_key)
        token, login_session = app.state.sessions.create(user.id, app.state.session_ttl)
        if snapshot_id:
            audit(session, snapshot_id, "auth.login", "success", request)
        response = JSONResponse({
            "authenticated": True,
            "expires_at": login_session.expires_at,
            "csrf_token": login_session.csrf_token,
            "principal": principal_payload(user),
        })
        response.set_cookie(app.state.session_cookie_name, token, max_age=app.state.session_ttl, httponly=True,
                            secure=app.state.secure_cookies, samesite="strict", path="/")
        return response

    @app.get("/api/v1/auth/session")
    def auth_session(request: Request):
        current = active_session(request) if app.state.auth_enabled else None
        if not current:
            return {"authenticated": False, "authentication_enabled": app.state.auth_enabled}
        user = resolve_principal(app.state.users_by_id.get(current.principal_id))
        if not user:
            return {"authenticated": False, "authentication_enabled": True}
        return {"authenticated": True, "authentication_enabled": True,
                "expires_at": current.expires_at, "csrf_token": current.csrf_token,
                "principal": principal_payload(user)}

    @app.post("/api/v1/auth/logout")
    def logout(request: Request, session: Session = Depends(session_dependency)):
        token = request.cookies.get(app.state.session_cookie_name)
        current = app.state.sessions.get(token)
        if not current:
            raise HTTPException(status_code=401, detail="Authentication required")
        if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), current.csrf_token):
            raise HTTPException(status_code=403, detail="CSRF validation failed")
        snapshot_id = session.scalar(select(SourceSnapshot.id).where(SourceSnapshot.name == selected_snapshot))
        app.state.sessions.revoke(token)
        if snapshot_id:
            audit(session, snapshot_id, "auth.logout", "success", request)
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(app.state.session_cookie_name, path="/", samesite="strict",
                               secure=app.state.secure_cookies)
        return response

    @app.get("/api/v1/health")
    def health(session: Session = Depends(session_dependency)):
        session.execute(text("SELECT 1"))
        operational_status = "not_configured"
        if app.state.operational_sessions:
            with app.state.operational_sessions() as operational_session:
                operational_session.execute(text("SELECT 1"))
            operational_status = "reachable"
        exists = session.scalar(select(func.count(SourceSnapshot.id)).where(SourceSnapshot.name == selected_snapshot)) or 0
        return {
            "status": "ok",
            "application": "Asas ERP",
            "mode": "independent_clone_preview",
            "database": "reachable",
            "snapshot": selected_snapshot,
            "snapshot_found": exists == 1,
            "posting_enabled": app.state.posting_enabled,
            "hrm_enabled": app.state.operational_sessions is not None,
            "payroll_enabled": False,
            "authentication_enabled": app.state.auth_enabled,
            "production_mode": app.state.production_mode,
            "session_backend": "database" if app.state.production_mode else "process_local",
            "operational_database": operational_status,
        }

    @app.get("/api/v1/setup/enterprise")
    def enterprise_setup(operational_session=Depends(operational_session_dependency)):
        """Read the target-ERP configuration without exposing or editing source evidence."""
        return enterprise_setup_payload(operational_session)

    @app.get("/api/v1/finance/foundation")
    def finance_foundation(request: Request,
                           operational_session=Depends(operational_session_dependency)):
        require_any_user(request, NAVIGATION_PERMISSION_RULES["chart-of-accounts"])
        return finance_foundation_payload(operational_session)

    def finance_permission(resource_type: str, action: str) -> str:
        permissions = {
            ("chart_account", "request"): "finance.chart.prepare",
            ("chart_account", "decide"): "finance.chart.approve",
            ("account_mapping", "request"): "finance.mapping.prepare",
            ("account_mapping", "decide"): "finance.mapping.approve",
        }
        permission = permissions.get((resource_type, action))
        if permission is None:
            raise HTTPException(status_code=422, detail="Unsupported finance approval resource type")
        return permission

    @app.post("/api/v1/finance/approvals/{resource_type}/{resource_key}/request")
    def submit_finance_approval(resource_type: str, resource_key: str,
                                payload: FinanceApprovalSubmissionRequest, request: Request,
                                operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, finance_permission(resource_type, "request"))
        try:
            request_finance_approval(
                operational_session, actor=user.username, resource_type=resource_type,
                resource_key=resource_key, note=payload.note,
            )
            return finance_foundation_payload(operational_session)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/finance/approvals/{resource_type}/{resource_key}/{action}")
    def resolve_finance_approval(resource_type: str, resource_key: str, action: str,
                                 payload: FinanceApprovalDecisionRequest, request: Request,
                                 operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, finance_permission(resource_type, "decide"))
        try:
            decide_finance_approval(
                operational_session, actor=user.username, resource_type=resource_type,
                resource_key=resource_key, action=action,
                expected_revision=payload.expected_revision, note=payload.note,
            )
            return finance_foundation_payload(operational_session)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v1/finance/reconciliation")
    def finance_reconciliation(request: Request,
                               snapshot: SourceSnapshot = Depends(snapshot_dependency),
                               session: Session = Depends(session_dependency),
                               operational_session=Depends(operational_session_dependency)):
        require_finance_report_scope(request, snapshot, session,
                                     NAVIGATION_PERMISSION_RULES["accounting"] | {"financial_report.read"})
        return finance_reconciliation_payload(operational_session)

    @app.post("/api/v1/finance/reconciliation/{review_key}/request")
    def submit_finance_reconciliation(
        review_key: str, payload: FinanceReconciliationSubmissionRequest, request: Request,
        operational_session=Depends(operational_session_dependency),
    ):
        user = require_csrf(request, "finance.reconciliation.prepare")
        try:
            request_reconciliation_review(
                operational_session, actor=user.username, review_key=review_key,
                resolution_type=payload.resolution_type, note=payload.note,
            )
            return finance_reconciliation_payload(operational_session)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/finance/reconciliation/{review_key}/{action}")
    def resolve_finance_reconciliation(
        review_key: str, action: str, payload: FinanceReconciliationDecisionRequest,
        request: Request, operational_session=Depends(operational_session_dependency),
    ):
        user = require_csrf(request, "finance.reconciliation.approve")
        try:
            decide_reconciliation_review(
                operational_session, actor=user.username, review_key=review_key, action=action,
                expected_revision=payload.expected_revision, note=payload.note,
            )
            return finance_reconciliation_payload(operational_session)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v1/general-ledger")
    def general_ledger(
        request: Request, account_code: str | None = Query(default=None, max_length=40),
        snapshot: SourceSnapshot = Depends(snapshot_dependency),
        session: Session = Depends(session_dependency),
        operational_session=Depends(operational_session_dependency),
    ):
        require_finance_report_scope(request, snapshot, session,
                                     NAVIGATION_PERMISSION_RULES["general-ledger"])
        if account_code and not operational_session.scalar(select(OperationalChartAccount.id).where(
            OperationalChartAccount.company_code == "ASAS",
            OperationalChartAccount.account_code == account_code,
        )):
            raise HTTPException(status_code=404, detail="General-ledger account was not found")
        return general_ledger_payload(operational_session, account_code=account_code)

    def find_general_journal(operational_session: Session, journal_key: str, *, lock: bool = False):
        query = select(OperationalGeneralJournal).where(
            OperationalGeneralJournal.company_code == "ASAS",
            OperationalGeneralJournal.journal_key == journal_key,
        )
        journal = operational_session.scalar(query.with_for_update() if lock else query)
        if journal is None:
            raise HTTPException(status_code=404, detail="General journal was not found")
        return journal

    @app.post("/api/v1/general-ledger/journals", status_code=201)
    def new_general_journal(payload: GeneralJournalRequest, request: Request,
                            operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "journal.prepare")
        try:
            create_general_journal(
                operational_session, actor=user.username, journal_date=payload.journal_date,
                branch_code=payload.branch_code, reference=payload.reference,
                description=payload.description,
                lines=[row.model_dump() for row in payload.lines],
            )
            return general_ledger_payload(operational_session)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.put("/api/v1/general-ledger/journals/{journal_key}")
    def update_general_journal(journal_key: str, payload: GeneralJournalUpdateRequest,
                               request: Request,
                               operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "journal.prepare")
        journal = find_general_journal(operational_session, journal_key, lock=True)
        try:
            replace_general_journal(
                operational_session, journal, actor=user.username,
                expected_revision=payload.expected_revision, journal_date=payload.journal_date,
                branch_code=payload.branch_code, reference=payload.reference,
                description=payload.description,
                lines=[row.model_dump() for row in payload.lines],
            )
            return general_ledger_payload(operational_session)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/general-ledger/journals/{journal_key}/{action}")
    def decide_general_journal(journal_key: str, action: str,
                               payload: GeneralJournalDecisionRequest, request: Request,
                               operational_session=Depends(operational_session_dependency)):
        if action not in {"request", "approve", "reject"}:
            raise HTTPException(status_code=404, detail="Unsupported general-journal action")
        permission = "journal.prepare" if action == "request" else "journal.approve"
        user = require_csrf(request, permission)
        journal = find_general_journal(operational_session, journal_key, lock=True)
        try:
            transition_general_journal(
                operational_session, journal, actor=user.username, action=action,
                expected_revision=payload.expected_revision, note=payload.note,
            )
            return general_ledger_payload(operational_session)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def access_payload(operational_session):
        return access_control_payload(
            operational_session, provisioned_logins=set(app.state.users_by_login),
        )

    @app.get("/api/v1/access-control")
    def access_control(request: Request, operational_session=Depends(operational_session_dependency)):
        require_any_user(request, {"access.review", "user.manage", "role.manage", "enterprise.setup"})
        return access_payload(operational_session)

    @app.get("/api/v1/hrm")
    def hrm_workspace(request: Request, q: str = Query("", max_length=120),
                      limit: int = Query(500, ge=1, le=500), offset: int = Query(0, ge=0),
                      operational_session=Depends(operational_session_dependency)):
        user = require_any_user(request, {"hrm.read", "hrm.manage", "enterprise.setup"})
        result = hrm_payload(operational_session, query=q, limit=limit, offset=offset)
        result["operations"] = hrm_operations_payload(
            operational_session, principal_username=user.username if user else None,
        )
        result["lifecycle"] = hrm_lifecycle_payload(operational_session)
        result["permissions"] = sorted(user.permissions) if user else []
        return result

    def hrm_result(operational_session, user):
        result = hrm_payload(operational_session, query="", limit=500, offset=0)
        result["operations"] = hrm_operations_payload(
            operational_session, principal_username=user.username if user else None,
        )
        result["lifecycle"] = hrm_lifecycle_payload(operational_session)
        result["permissions"] = sorted(user.permissions) if user else []
        return result

    @app.get("/api/v1/hrm/self-service")
    def hrm_self_service(request: Request, operational_session=Depends(operational_session_dependency)):
        user = require_any_user(request, {"hrm.self.read", "hrm.read", "hrm.manage", "enterprise.setup"})
        result = hrm_result(operational_session, user)
        own = next((row for row in result["employees"]
                    if (row.get("username") or "").casefold() == user.username.casefold()), None)
        if own is None:
            result["employees"] = []
            result["attendance"] = []
        else:
            result["employees"] = [own]
            result["attendance"] = [row for row in result["attendance"]
                                    if row.get("employee_name") == own.get("display_name")]
        operations = result["operations"]
        own_key = operations["self_service"]["employee_key"]
        operations["profiles"] = [row for row in operations["profiles"] if row["employee_key"] == own_key]
        operations["leave_requests"] = [row for row in operations["leave_requests"] if row["employee_key"] == own_key]
        operations["shift_assignments"] = [row for row in operations["shift_assignments"] if row["employee_key"] == own_key]
        operations["attendance_corrections"] = [row for row in operations["attendance_corrections"]
                                                 if row["attendance_id"] in {item["id"] for item in result["attendance"]}]
        return result

    @app.post("/api/v1/hrm/departments", status_code=201)
    def add_hrm_department(payload: HrmDepartmentRequest, request: Request,
                           operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"hrm.manage", "enterprise.setup"})
        try:
            create_department(operational_session, code=payload.code, name=payload.name, actor=user.username)
            return hrm_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/hrm/designations", status_code=201)
    def add_hrm_designation(payload: HrmDesignationRequest, request: Request,
                            operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"hrm.manage", "enterprise.setup"})
        try:
            create_designation(operational_session, code=payload.code, name=payload.name,
                               department_code=payload.department_code, actor=user.username)
            return hrm_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/hrm/shifts", status_code=201)
    def add_hrm_shift(payload: HrmShiftRequest, request: Request,
                      operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"shift.manage", "hrm.manage", "enterprise.setup"})
        try:
            create_shift(operational_session, name=payload.name, shift_type=payload.shift_type,
                         start_time=payload.start_time, end_time=payload.end_time, actor=user.username)
            return hrm_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/hrm/holidays", status_code=201)
    def add_hrm_holiday(payload: HrmHolidayRequest, request: Request,
                        operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"hrm.manage", "enterprise.setup"})
        try:
            create_holiday(operational_session, holiday_date=payload.holiday_date, name=payload.name,
                           department_code=payload.department_code, actor=user.username)
            return hrm_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/hrm/employee-changes", status_code=201)
    def add_hrm_employee_change(payload: HrmEmployeeChangeRequest, request: Request,
                                operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"hrm.employee.prepare", "hrm.manage", "enterprise.setup"})
        try:
            request_employee_change(operational_session, actor=user.username, **payload.model_dump())
            return hrm_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/hrm/employee-changes/{profile_key}/{action}")
    def decide_hrm_employee(profile_key: str, action: str, payload: HrmDecisionRequest, request: Request,
                            operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"hrm.employee.approve", "hrm.manage", "enterprise.setup"})
        try:
            decide_employee_change(operational_session, profile_key=profile_key, action=action,
                                   expected_revision=payload.expected_revision, note=payload.note, actor=user.username)
            return hrm_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def own_employee_key(operational_session, username: str) -> str | None:
        employee = operational_session.scalar(select(OperationalHrmEmployee).where(
            func.lower(OperationalHrmEmployee.username) == username.casefold()))
        return employee.employee_key if employee else None

    @app.post("/api/v1/hrm/leave-requests", status_code=201)
    def add_hrm_leave(payload: HrmLeaveRequest, request: Request,
                      operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"leave.prepare", "leave.self.create", "hrm.manage", "enterprise.setup"})
        employee_key = payload.employee_key or own_employee_key(operational_session, user.username)
        if not employee_key:
            raise HTTPException(status_code=422, detail="No HRM employee is linked to this login")
        if "leave.self.create" in user.permissions and not {"leave.prepare", "hrm.manage", "enterprise.setup"}.intersection(user.permissions):
            if employee_key != own_employee_key(operational_session, user.username):
                raise HTTPException(status_code=403, detail="Self-service leave may only be requested for the signed-in employee")
        try:
            values = payload.model_dump(exclude={"employee_key"}); values["employee_key"] = employee_key
            create_leave_request(operational_session, actor=user.username, **values)
            return hrm_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/hrm/leave-requests/{leave_key}/{action}")
    def decide_hrm_leave(leave_key: str, action: str, payload: HrmDecisionRequest, request: Request,
                         operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"leave.approve", "hrm.manage", "enterprise.setup"})
        try:
            decide_leave(operational_session, leave_key=leave_key, action=action,
                         expected_revision=payload.expected_revision, note=payload.note, actor=user.username)
            return hrm_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/hrm/attendance-corrections", status_code=201)
    def add_hrm_attendance_correction(payload: HrmAttendanceCorrectionRequest, request: Request,
                                      operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"attendance.prepare", "attendance.self.create", "hrm.manage", "enterprise.setup"})
        if "attendance.self.create" in user.permissions and not {"attendance.prepare", "hrm.manage", "enterprise.setup"}.intersection(user.permissions):
            attendance = operational_session.get(OperationalHrmAttendance, payload.attendance_id)
            own = own_employee_key(operational_session, user.username)
            employee = operational_session.get(OperationalHrmEmployee, attendance.employee_id) if attendance else None
            if not employee or employee.employee_key != own:
                raise HTTPException(status_code=403, detail="Self-service correction may only target the signed-in employee")
        try:
            create_attendance_correction(operational_session, actor=user.username, **payload.model_dump())
            return hrm_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/hrm/attendance-corrections/{correction_key}/{action}")
    def decide_hrm_attendance(correction_key: str, action: str, payload: HrmDecisionRequest, request: Request,
                              operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"attendance.approve", "hrm.manage", "enterprise.setup"})
        try:
            decide_attendance_correction(operational_session, correction_key=correction_key, action=action,
                                         expected_revision=payload.expected_revision, note=payload.note, actor=user.username)
            return hrm_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/hrm/shift-assignments", status_code=201)
    def add_hrm_shift_assignment(payload: HrmShiftAssignmentRequest, request: Request,
                                 operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"shift.manage", "hrm.manage", "enterprise.setup"})
        try:
            assign_shift(operational_session, actor=user.username, **payload.model_dump())
            return hrm_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/hrm/workforce-requests", status_code=201)
    def add_hrm_workforce_request(payload: HrmWorkforceRequest, request: Request,
                                  operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"hrm.lifecycle.prepare", "hrm.manage", "enterprise.setup"})
        try:
            create_workforce_request(operational_session, actor=user.username, **payload.model_dump())
            return hrm_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/hrm/workforce-requests/{request_key}/{action}")
    def decide_hrm_workforce_request(request_key: str, action: str, payload: HrmDecisionRequest,
                                     request: Request,
                                     operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"hrm.lifecycle.approve", "hrm.manage", "enterprise.setup"})
        try:
            decide_workforce_request(operational_session, request_key=request_key, action=action,
                expected_revision=payload.expected_revision, note=payload.note, actor=user.username)
            return hrm_result(operational_session, user)
        except (ValueError, PermissionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/hrm/candidates", status_code=201)
    def add_hrm_candidate(payload: HrmCandidateRequest, request: Request,
                          operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"hrm.lifecycle.prepare", "hrm.manage", "enterprise.setup"})
        try:
            create_candidate(operational_session, actor=user.username, **payload.model_dump())
            return hrm_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/hrm/candidates/{candidate_key}/stage")
    def move_hrm_candidate(candidate_key: str, payload: HrmCandidateStageRequest, request: Request,
                           operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"hrm.lifecycle.prepare", "hrm.manage", "enterprise.setup"})
        try:
            move_candidate(operational_session, candidate_key=candidate_key, actor=user.username,
                           **payload.model_dump())
            return hrm_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/hrm/employee-documents", status_code=201)
    def add_hrm_document(payload: HrmEmployeeDocumentRequest, request: Request,
                         operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"hrm.lifecycle.prepare", "hrm.manage", "enterprise.setup"})
        try:
            add_employee_document(operational_session, actor=user.username, **payload.model_dump())
            return hrm_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/hrm/lifecycle-cases", status_code=201)
    def add_hrm_lifecycle_case(payload: HrmLifecycleCaseRequest, request: Request,
                               operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"hrm.lifecycle.prepare", "hrm.manage", "enterprise.setup"})
        try:
            create_lifecycle_case(operational_session, actor=user.username, **payload.model_dump())
            return hrm_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/hrm/lifecycle-cases/{case_key}/{action}")
    def transition_hrm_lifecycle_case(case_key: str, action: str, payload: HrmDecisionRequest,
                                      request: Request,
                                      operational_session=Depends(operational_session_dependency)):
        permission = "hrm.lifecycle.approve" if action in {"approve", "reject"} else "hrm.lifecycle.prepare"
        user = require_any_csrf(request, {permission, "hrm.manage", "enterprise.setup"})
        try:
            transition_lifecycle_case(operational_session, case_key=case_key, action=action,
                expected_revision=payload.expected_revision, note=payload.note, actor=user.username)
            return hrm_result(operational_session, user)
        except (ValueError, PermissionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    PROCUREMENT_READ = {"purchase.requisition.create", "purchase.requisition.approve", "rfq.create", "supplier_quote.manage",
                        "purchase_order.prepare", "purchase_order.approve", "supplier_bill.prepare",
                        "supplier_bill.approve", "supplier_bill.tolerance.approve",
                        "supplier_adjustment.prepare", "supplier_adjustment.approve",
                        "supplier_bill.rehearse", "match_tolerance.prepare", "match_tolerance.approve",
                        "posting.execute", "posting.reverse", "enterprise.setup"}

    def procurement_scope(user) -> tuple[str, ...]:
        return tuple(user.allowed_locations) if user else ("*",)

    def procurement_result(operational_session: Session, user) -> dict:
        scope = procurement_scope(user)
        result = procurement_payload(operational_session, allowed_locations=scope)
        invoices = invoice_payload(operational_session, allowed_locations=scope)
        invoice_keys = {row["invoice_key"] for row in invoices}
        posting_rows = list(operational_session.scalars(select(OperationalIntegratedPostingBatch).where(
            OperationalIntegratedPostingBatch.resource_type == "supplier_invoice",
            OperationalIntegratedPostingBatch.resource_key.in_(invoice_keys),
            OperationalIntegratedPostingBatch.batch_kind == "posting"))) if invoice_keys else []
        postings = {row.resource_key: row for row in posting_rows}
        for invoice in invoices:
            batch = postings.get(invoice["invoice_key"])
            invoice["posting_enabled"] = app.state.posting_enabled
            invoice["posting"] = ({"batch_key": batch.batch_key, "status": batch.status,
                "posted_at": batch.posted_at, "posted_by": batch.posted_by,
                "posting_fingerprint": batch.posting_fingerprint} if batch else None)
        result["supplier_invoices"] = invoices
        adjustments = adjustment_payload(operational_session, allowed_locations=scope)
        adjustment_keys = {row["adjustment_key"] for row in adjustments}
        adjustment_posting_rows = list(operational_session.scalars(select(OperationalIntegratedPostingBatch).where(
            OperationalIntegratedPostingBatch.resource_type == "supplier_adjustment",
            OperationalIntegratedPostingBatch.resource_key.in_(adjustment_keys),
            OperationalIntegratedPostingBatch.batch_kind == "posting"))) if adjustment_keys else []
        adjustment_postings = {row.resource_key: row for row in adjustment_posting_rows}
        for adjustment in adjustments:
            batch = adjustment_postings.get(adjustment["adjustment_key"])
            adjustment["posting_enabled"] = app.state.posting_enabled
            adjustment["posting"] = ({"batch_key": batch.batch_key, "status": batch.status,
                "posted_at": batch.posted_at, "posted_by": batch.posted_by,
                "posting_fingerprint": batch.posting_fingerprint} if batch else None)
        result["supplier_adjustments"] = adjustments
        result["match_policy"] = policy_payload(operational_session)
        result["controls"].update({
            "posting_enabled": app.state.posting_enabled,
            "supplier_invoices": len(invoices),
            "invoice_match_exceptions": sum(row["match_status"] == "exception" for row in invoices),
            "approved_supplier_invoices": sum(row["status"] == "approved" for row in invoices),
            "tax_document_exceptions": sum((row["tax_document"] or {}).get("validation_status") == "exception" for row in invoices),
            "invoice_posting_rehearsals": sum(row["posting_rehearsal"] is not None for row in invoices),
            "posted_supplier_invoices": sum(row["status"] == "posted" for row in invoices),
            "supplier_adjustments": len(adjustments),
            "pending_supplier_adjustments": sum(row["status"] == "submitted" for row in adjustments),
            "adjustment_posting_rehearsals": sum(row["posting_rehearsal"] is not None for row in adjustments),
            "posted_supplier_adjustments": sum(row["status"] == "posted" for row in adjustments),
        })
        return result

    @app.get("/api/v1/procurement")
    def procurement_workspace(request: Request,
                              operational_session=Depends(operational_session_dependency)):
        user = require_any_user(request, PROCUREMENT_READ)
        return procurement_result(operational_session, user)

    @app.post("/api/v1/procurement/requisitions", status_code=201)
    def add_procurement_requisition(payload: ProcurementRequisitionRequest, request: Request,
                                    operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"purchase.requisition.create", "enterprise.setup"})
        try:
            if not location_allowed(user, payload.location_code):
                raise HTTPException(status_code=403, detail="Receiving location is outside the user's operational scope")
            create_requisition(operational_session, actor=user.username, **payload.model_dump())
            return procurement_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/procurement/requisitions/{requisition_key}/{action}")
    def change_procurement_requisition(requisition_key: str, action: str,
                                       payload: ProcurementDecisionRequest, request: Request,
                                       operational_session=Depends(operational_session_dependency)):
        permission = ({"purchase.requisition.create", "enterprise.setup"} if action in {"submit", "cancel"}
                      else {"purchase.requisition.approve", "enterprise.setup"})
        user = require_any_csrf(request, permission)
        try:
            transition_requisition(operational_session, requisition_key=requisition_key, action=action,
                                   expected_revision=payload.expected_revision, note=payload.note,
                                   actor=user.username, allowed_locations=procurement_scope(user))
            return procurement_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/procurement/rfqs", status_code=201)
    def add_procurement_rfq(payload: ProcurementRfqRequest, request: Request,
                            operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"rfq.create", "enterprise.setup"})
        try:
            create_rfq(operational_session, actor=user.username,
                       allowed_locations=procurement_scope(user), **payload.model_dump())
            return procurement_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/procurement/rfqs/{rfq_key}/quotations", status_code=201)
    def add_supplier_quotation(rfq_key: str, payload: ProcurementQuoteRequest, request: Request,
                               operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"supplier_quote.manage", "enterprise.setup"})
        try:
            capture_quote(operational_session, rfq_key=rfq_key, actor=user.username,
                          allowed_locations=procurement_scope(user), **payload.model_dump())
            return procurement_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/procurement/rfqs/{rfq_key}/award", status_code=201)
    def award_supplier_quotation(rfq_key: str, payload: ProcurementAwardRequest, request: Request,
                                 operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"purchase_order.prepare", "enterprise.setup"})
        try:
            award_quote(operational_session, rfq_key=rfq_key, actor=user.username,
                        allowed_locations=procurement_scope(user), **payload.model_dump())
            return procurement_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/procurement/purchase-orders/{purchase_order_key}/{action}")
    def change_purchase_order(purchase_order_key: str, action: str,
                              payload: ProcurementDecisionRequest, request: Request,
                              operational_session=Depends(operational_session_dependency)):
        permission = ({"purchase_order.prepare", "enterprise.setup"} if action in {"submit", "cancel"}
                      else {"purchase_order.approve", "enterprise.setup"})
        user = require_any_csrf(request, permission)
        try:
            transition_purchase_order(operational_session, purchase_order_key=purchase_order_key,
                                      action=action, expected_revision=payload.expected_revision,
                                      note=payload.note, actor=user.username,
                                      allowed_locations=procurement_scope(user))
            return procurement_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/procurement/supplier-invoices", status_code=201)
    def add_supplier_invoice(payload: SupplierInvoiceRequest, request: Request,
                             operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"supplier_bill.prepare", "enterprise.setup"})
        try:
            create_supplier_invoice(operational_session, actor=user.username,
                allowed_locations=procurement_scope(user), **payload.model_dump())
            return procurement_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/procurement/supplier-invoices/{invoice_key}/match")
    def match_supplier_invoice(invoice_key: str, request: Request,
                               operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"supplier_bill.prepare", "enterprise.setup"})
        invoice = operational_session.scalar(select(OperationalSupplierInvoice).where(
            OperationalSupplierInvoice.invoice_key == invoice_key).with_for_update())
        if not invoice or not location_allowed(user, invoice.location_code):
            raise HTTPException(status_code=404, detail="Supplier invoice not found")
        try:
            evaluate_invoice_match(operational_session, invoice, actor=user.username)
            return procurement_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/procurement/supplier-invoices/{invoice_key}/posting-rehearsal")
    def rehearse_supplier_invoice(invoice_key: str, request: Request,
                                  operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"supplier_bill.rehearse", "enterprise.setup"})
        invoice = operational_session.scalar(select(OperationalSupplierInvoice).where(
            OperationalSupplierInvoice.invoice_key == invoice_key).with_for_update())
        if not invoice or not location_allowed(user, invoice.location_code):
            raise HTTPException(status_code=404, detail="Supplier invoice not found")
        try:
            return rehearse_supplier_invoice_posting(operational_session, invoice, actor=user.username)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/procurement/supplier-invoices/{invoice_key}/{action}")
    def approve_supplier_invoice(invoice_key: str, action: str, payload: ProcurementDecisionRequest,
                                 request: Request,
                                 operational_session=Depends(operational_session_dependency)):
        if action not in {"approve", "reject", "approve-tolerance"}:
            raise HTTPException(status_code=404, detail="Supplier invoice action not found")
        permission = ({"supplier_bill.tolerance.approve", "enterprise.setup"}
                      if action == "approve-tolerance"
                      else {"supplier_bill.approve", "enterprise.setup"})
        user = require_any_csrf(request, permission)
        invoice = operational_session.scalar(select(OperationalSupplierInvoice).where(
            OperationalSupplierInvoice.invoice_key == invoice_key).with_for_update())
        if not invoice or not location_allowed(user, invoice.location_code):
            raise HTTPException(status_code=404, detail="Supplier invoice not found")
        try:
            if action == "approve-tolerance":
                approve_invoice_tolerance(operational_session, invoice,
                    expected_revision=payload.expected_revision, note=payload.note, actor=user.username)
            else:
                decide_supplier_invoice(operational_session, invoice, action=action,
                    expected_revision=payload.expected_revision, note=payload.note, actor=user.username)
            return procurement_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/procurement/match-policy/request")
    def request_match_policy(payload: MatchToleranceRequest, request: Request,
                             operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"match_tolerance.prepare", "enterprise.setup"})
        try:
            request_policy_change(operational_session, actor=user.username, **payload.model_dump())
            return procurement_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/procurement/match-policy/{action}")
    def approve_match_policy(action: str, payload: ProcurementDecisionRequest, request: Request,
                             operational_session=Depends(operational_session_dependency)):
        if action not in {"approve", "reject"}:
            raise HTTPException(status_code=404, detail="Match-policy action not found")
        user = require_any_csrf(request, {"match_tolerance.approve", "enterprise.setup"})
        try:
            decide_policy_change(operational_session, action=action,
                expected_revision=payload.expected_revision, note=payload.note, actor=user.username)
            return procurement_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/procurement/supplier-adjustments", status_code=201)
    def add_supplier_adjustment(payload: SupplierAdjustmentRequest, request: Request,
                                operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"supplier_adjustment.prepare", "enterprise.setup"})
        try:
            create_supplier_adjustment(operational_session, actor=user.username,
                allowed_locations=procurement_scope(user), **payload.model_dump())
            return procurement_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/procurement/supplier-adjustments/{adjustment_key}/posting-rehearsal")
    def rehearse_supplier_adjustment(adjustment_key: str, request: Request,
                                     operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"supplier_bill.rehearse", "enterprise.setup"})
        adjustment = operational_session.scalar(select(OperationalSupplierAdjustment).where(
            OperationalSupplierAdjustment.adjustment_key == adjustment_key).with_for_update())
        if not adjustment or not location_allowed(user, adjustment.location_code):
            raise HTTPException(status_code=404, detail="Supplier adjustment not found")
        try:
            return rehearse_supplier_adjustment_posting(operational_session, adjustment, actor=user.username)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/procurement/supplier-adjustments/{adjustment_key}/{action}")
    def change_supplier_adjustment(adjustment_key: str, action: str,
                                   payload: ProcurementDecisionRequest, request: Request,
                                   operational_session=Depends(operational_session_dependency)):
        if action not in {"submit", "cancel", "approve", "reject"}:
            raise HTTPException(status_code=404, detail="Supplier-adjustment action not found")
        permission = ({"supplier_adjustment.prepare", "enterprise.setup"}
                      if action in {"submit", "cancel"}
                      else {"supplier_adjustment.approve", "enterprise.setup"})
        user = require_any_csrf(request, permission)
        adjustment = operational_session.scalar(select(OperationalSupplierAdjustment).where(
            OperationalSupplierAdjustment.adjustment_key == adjustment_key).with_for_update())
        if not adjustment or not location_allowed(user, adjustment.location_code):
            raise HTTPException(status_code=404, detail="Supplier adjustment not found")
        try:
            transition_supplier_adjustment(operational_session, adjustment, action=action,
                expected_revision=payload.expected_revision, note=payload.note, actor=user.username)
            return procurement_result(operational_session, user)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/access-control/users", status_code=201)
    def create_access_user(payload: AccessUserRequest, request: Request,
                           operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"user.manage", "enterprise.setup"})
        try:
            create_user_profile(
                operational_session, actor=user.username, login_name=payload.login_name,
                display_name=payload.display_name,
                identity_ready=payload.login_name.casefold() in app.state.users_by_login,
            )
            return access_payload(operational_session)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.patch("/api/v1/access-control/users/{user_key}/status")
    def change_access_user_status(user_key: str, payload: AccessUserStatusRequest, request: Request,
                                  operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"user.manage", "enterprise.setup"})
        target = next((row for row in access_payload(operational_session)["users"]
                       if row["user_key"] == user_key), None)
        if target is None:
            raise HTTPException(status_code=404, detail="ERP user profile was not found")
        try:
            set_user_status(
                operational_session, actor=user.username, user_key=user_key, status=payload.status,
                identity_ready=bool(target["identity_ready"]),
            )
            return access_payload(operational_session)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/access-control/users/{user_key}/assignments", status_code=201)
    def create_role_assignment(user_key: str, payload: RoleAssignmentRequest, request: Request,
                               operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"role.manage", "user.manage", "enterprise.setup"})
        try:
            assign_role(
                operational_session, actor=user.username, user_key=user_key,
                role_code=payload.role_code, company_code=payload.company_code,
                branch_code=payload.branch_code, warehouse_code=payload.warehouse_code,
                van_code=payload.van_code, approval_limit_aed=payload.approval_limit_aed,
                effective_from=payload.effective_from, effective_to=payload.effective_to,
            )
            return access_payload(operational_session)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.delete("/api/v1/access-control/users/{user_key}/assignments/{assignment_id}")
    def delete_role_assignment(user_key: str, assignment_id: int, request: Request,
                               operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"role.manage", "user.manage", "enterprise.setup"})
        try:
            revoke_role(operational_session, actor=user.username, user_key=user_key,
                        assignment_id=assignment_id)
            return access_payload(operational_session)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.patch("/api/v1/setup/enterprise/company")
    def update_enterprise_company(payload: CompanyProfileSetupRequest, request: Request,
                                  operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "enterprise.setup")
        try:
            return update_company_profile(operational_session, actor=user.username,
                legal_name=payload.legal_name, profile_updates={
                    "registered_address": payload.registered_address,
                    "tax_registration_number": payload.tax_registration_number,
                    "trade_license_number": payload.trade_license_number,
                    "logo_reference": payload.logo_reference,
                })
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/setup/enterprise/branches", status_code=201)
    def create_enterprise_branch(payload: BranchSetupRequest, request: Request,
                                 operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "enterprise.setup")
        try:
            return add_branch(operational_session, actor=user.username,
                              branch_code=payload.branch_code, name=payload.name)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/setup/enterprise/warehouses", status_code=201)
    def create_enterprise_warehouse(payload: WarehouseSetupRequest, request: Request,
                                    operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "enterprise.setup")
        try:
            return add_warehouse(operational_session, actor=user.username,
                                 branch_code=payload.branch_code, warehouse_code=payload.warehouse_code,
                                 name=payload.name, warehouse_type=payload.warehouse_type)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/setup/enterprise/vans", status_code=201)
    def create_enterprise_van(payload: VanSetupRequest, request: Request,
                              operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "enterprise.setup")
        try:
            return add_van(operational_session, actor=user.username, van_code=payload.van_code,
                           name=payload.name, assigned_branch_code=payload.assigned_branch_code)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/setup/enterprise/{unit_kind}/{unit_code}/{action}")
    def decide_operating_unit(unit_kind: str, unit_code: str, action: str,
                              payload: OperatingUnitDecisionRequest, request: Request,
                              operational_session=Depends(operational_session_dependency)):
        required_permission = "enterprise.setup" if action == "request_activation" else "enterprise.approve"
        user = require_csrf(request, required_permission)
        try:
            return transition_operating_unit(operational_session, actor=user.username,
                unit_kind=unit_kind, unit_code=unit_code, action=action,
                expected_revision=payload.expected_revision, note=payload.note)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def draft_payload(draft, operational_session: Session | None = None) -> dict:
        rehearsal = None
        posting = None
        if operational_session is not None and draft.document_type == "sale":
            rehearsal = operational_session.scalar(select(OperationalSalesInvoicePostingRehearsal).where(
                OperationalSalesInvoicePostingRehearsal.sales_invoice_id == draft.id,
                OperationalSalesInvoicePostingRehearsal.invoice_revision == draft.revision))
            posting = operational_session.scalar(select(OperationalIntegratedPostingBatch).where(
                OperationalIntegratedPostingBatch.resource_type == "sales_invoice",
                OperationalIntegratedPostingBatch.resource_key == draft.draft_key,
                OperationalIntegratedPostingBatch.batch_kind == "posting").order_by(
                    OperationalIntegratedPostingBatch.posting_sequence.desc()))
        return {
            "draft_key": draft.draft_key, "draft_no": draft.draft_no,
            "document_type": draft.document_type, "party_code": draft.party_code,
            "party_name": draft.party_name_snapshot, "location_code": draft.location_code,
            "currency_code": draft.currency_code, "subtotal": draft.subtotal,
            "discount_amount": draft.discount_amount, "tax_amount": draft.tax_amount,
            "total_amount": draft.total_amount, "status": draft.status,
            "posting_enabled": draft.posting_enabled, "created_by": draft.created_by,
            "created_at": draft.created_at, "notes": draft.notes,
            "revision": draft.revision, "state_changed_at": draft.state_changed_at,
            "state_changed_by": draft.state_changed_by,
            "posting_rehearsal": (sales_invoice_rehearsal_payload(rehearsal, draft)
                                  if rehearsal else None),
            "posting": ({"batch_key": posting.batch_key, "status": posting.status}
                        if posting else None),
            "lines": [{"line_no": line.line_no, "sku": line.sku,
                       "product_name": line.product_name_snapshot, "quantity": line.quantity,
                       "uom": line.uom, "canonical_uom": line.canonical_uom,
                       "factor_to_base_snapshot": line.factor_to_base_snapshot,
                       "quantity_base": line.quantity_base, "unit_price": line.unit_price,
                       "tax_rate": line.tax_rate, "net_amount": line.net_amount,
                       "tax_amount": line.tax_amount, "gross_amount": line.gross_amount,
                       "unit_cost_snapshot": line.unit_cost_snapshot,
                       "cost_amount": line.cost_amount}
                      for line in draft.lines],
        }

    @app.get("/api/v1/drafts")
    def drafts(request: Request, operational_session=Depends(operational_session_dependency)):
        user = current_user(request)
        rows = list_drafts(operational_session, allowed_locations=user.allowed_locations if user else ())
        stock_query = select(func.count(OperationalStockPosition.id))
        if user and "*" not in user.allowed_locations:
            stock_query = stock_query.where(OperationalStockPosition.location_code.in_(user.allowed_locations))
        stock_positions = operational_session.scalar(stock_query) or 0
        open_periods = operational_session.scalar(select(func.count(OperationalFiscalPeriod.id)).where(
            OperationalFiscalPeriod.status == "open",
            OperationalFiscalPeriod.rehearsal_enabled.is_(True))) or 0
        return {"items": [draft_payload(row, operational_session) for row in rows], "total": len(rows),
                "posting_enabled": app.state.posting_enabled,
                "workflow": ["draft", "submitted", "approved", "cancelled", "posted", "reversed"],
                "controls": {"stock_positions": stock_positions, "open_rehearsal_periods": open_periods,
                             "permanent_journals": operational_session.scalar(select(func.count(OperationalJournalBatch.id))) or 0,
                             "sales_invoice_rehearsals": operational_session.scalar(select(func.count(
                                 OperationalSalesInvoicePostingRehearsal.id))) or 0,
                             "posted_sales_invoices": operational_session.scalar(select(func.count(
                                 OperationalIntegratedPostingBatch.id)).where(
                                     OperationalIntegratedPostingBatch.resource_type == "sales_invoice",
                                     OperationalIntegratedPostingBatch.batch_kind == "posting")) or 0,
                             "subledger_entries": operational_session.scalar(select(func.count(OperationalSubledgerEntry.id))) or 0,
                             "reversal_requests": operational_session.scalar(select(func.count(OperationalReversalRequest.id))) or 0,
                             "posting_probes": operational_session.scalar(select(func.count(OperationalPostingProbe.id))) or 0,
                             "active_reservations": operational_session.scalar(select(func.count(OperationalStockReservation.id)).where(
                                 OperationalStockReservation.status == "active")) or 0}}

    @app.get("/api/v1/drafts/{draft_key}")
    def draft_detail(draft_key: str, request: Request,
                     operational_session=Depends(operational_session_dependency)):
        draft = operational_session.scalar(select(OperationalDraft).where(
            OperationalDraft.draft_key == draft_key).with_for_update())
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        if not location_allowed(current_user(request), draft.location_code):
            raise HTTPException(status_code=404, detail="Draft not found")
        return draft_payload(draft, operational_session)

    @app.get("/api/v1/selectors/locations")
    def location_selector(request: Request, snapshot: SourceSnapshot = Depends(snapshot_dependency),
                          session: Session = Depends(session_dependency),
                          operational_session=Depends(optional_operational_session_dependency)):
        user = current_user(request)
        if operational_session is not None and operational_session.scalar(select(func.count(OperationalLocationMaster.id))):
            source_rows = operational_session.execute(select(
                OperationalLocationMaster.location_code.label("code"), OperationalLocationMaster.name
            ).where(OperationalLocationMaster.status == "active").order_by(OperationalLocationMaster.location_code)).all()
        else:
            source_rows = session.execute(select(ErpLocation.code, ErpLocation.name).where(
                ErpLocation.snapshot_id == snapshot.id).order_by(ErpLocation.code)).all()
        rows = [row for row in source_rows
                if user and location_allowed(user, row.code)]
        return {"items": [dict(row._mapping) for row in rows]}

    @app.get("/api/v1/selectors/parties")
    def party_selector(kind: str = Query(pattern="^(customer|supplier)$"), q: str = Query("", max_length=120),
                       limit: int = Query(30, ge=1, le=500),
                       snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency),
                       operational_session=Depends(optional_operational_session_dependency)):
        if operational_session is not None and operational_session.scalar(select(func.count(OperationalPartyMaster.id))):
            filters = [OperationalPartyMaster.status == "active", OperationalPartyMaster.party_kind.in_((kind, "both"))]
            if q:
                pattern = f"%{q.strip()}%"
                filters.append(or_(OperationalPartyMaster.party_code.ilike(pattern), OperationalPartyMaster.legal_or_business_name.ilike(pattern)))
            rows = [dict(row._mapping) for row in operational_session.execute(select(
                OperationalPartyMaster.party_code, OperationalPartyMaster.legal_or_business_name.label("name")
            ).where(*filters).order_by(OperationalPartyMaster.legal_or_business_name).limit(limit)).all()]
            return {"items": rows}
        filters = [ErpParty.snapshot_id == snapshot.id, ErpParty.party_kind.in_((kind, "both"))]
        if q:
            pattern = f"%{q.strip()}%"
            filters.append(or_(ErpParty.party_code.ilike(pattern), ErpParty.legal_or_business_name.ilike(pattern)))
        rows = [dict(row._mapping) for row in session.execute(select(
            ErpParty.party_code, ErpParty.legal_or_business_name.label("name")
        ).where(*filters).order_by(ErpParty.legal_or_business_name).limit(limit)).all()]
        if app.state.delta_overlay:
            existing = {row["party_code"] for row in rows}
            additions = [{"party_code": row["party_code"], "name": row["legal_or_business_name"]}
                         for row in app.state.delta_overlay.party_records(kind)
                         if row["party_code"] not in existing and _contains(row, q)]
            rows = (rows + additions)[:limit]
        return {"items": rows}

    @app.get("/api/v1/selectors/products")
    def product_selector(q: str = Query("", max_length=120),
                         snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency),
                         operational_session=Depends(optional_operational_session_dependency)):
        if operational_session is not None and operational_session.scalar(select(func.count(OperationalProductMaster.id))):
            filters = [OperationalProductMaster.status == "active"]
            if q:
                pattern = f"%{q.strip()}%"
                filters.append(or_(OperationalProductMaster.sku.ilike(pattern), OperationalProductMaster.name.ilike(pattern)))
            rows = [dict(row._mapping) for row in operational_session.execute(select(
                OperationalProductMaster.sku, OperationalProductMaster.name,
                OperationalProductMaster.purchase_price.label("purchase_price_evidence"),
                OperationalProductMaster.selling_price.label("selling_price_evidence"),
                OperationalProductMaster.base_uom.label("uom"), OperationalProductMaster.canonical_base_uom,
                OperationalProductMaster.factor_to_base.label("factor_to_base_snapshot"),
            ).where(*filters).order_by(OperationalProductMaster.name).limit(30)).all()]
            for row in rows:
                row["conversion_status"] = "operational"
            return {"items": rows}
        filters = [ErpProductMaster.snapshot_id == snapshot.id]
        if q:
            pattern = f"%{q.strip()}%"
            filters.append(or_(ErpProductMaster.sku.ilike(pattern), ErpProductMaster.name.ilike(pattern)))
        rows = [dict(row._mapping) for row in session.execute(select(
            ErpProductMaster.sku, ErpProductMaster.name,
            ErpProductMaster.purchase_price_evidence, ErpProductMaster.selling_price_evidence,
            ErpProductUom.source_base_uom.label("uom"), ErpProductUom.canonical_base_uom,
            ErpProductUom.factor_to_base_snapshot, ErpProductUom.conversion_status,
        ).outerjoin(ErpProductUom, ErpProductUom.product_id == ErpProductMaster.id).where(
            *filters).order_by(ErpProductMaster.name).limit(30)).all()]
        if app.state.delta_overlay:
            existing = {row["sku"] for row in rows}
            additions = [{"sku": row["sku"], "name": row["name"],
                          "purchase_price_evidence": row["purchase_price_evidence"],
                          "selling_price_evidence": row["selling_price_evidence"],
                          "uom": row["base_uom"], "canonical_base_uom": row["base_uom"].casefold(),
                          "factor_to_base_snapshot": 1, "conversion_status": "provisional"}
                         for row in app.state.delta_overlay.product_records()
                         if row["sku"] not in existing and _contains(row, q)]
            rows = (rows + additions)[:30]
        return {"items": rows}

    @app.get("/api/v1/selectors/sales-invoices")
    def sales_invoice_selector(customer_code: str = Query(min_length=1, max_length=80),
                               snapshot: SourceSnapshot = Depends(snapshot_dependency),
                               session: Session = Depends(session_dependency)):
        rows = session.execute(select(ErpTransactionDocument.document_no,
                                      ErpTransactionDocument.occurred_at,
                                      ErpTransactionDocument.total_amount).join(
            ErpParty, ErpParty.id == ErpTransactionDocument.party_id).where(
            ErpTransactionDocument.snapshot_id == snapshot.id,
            ErpTransactionDocument.source_kind == "sale",
            ErpParty.party_code == customer_code).order_by(
            ErpTransactionDocument.occurred_at.desc()).limit(30)).all()
        return {"items": [dict(row._mapping) for row in rows]}

    @app.get("/api/v1/selectors/purchase-invoices")
    def purchase_invoice_selector(supplier_code: str = Query(min_length=1, max_length=80),
                                  snapshot: SourceSnapshot = Depends(snapshot_dependency),
                                  session: Session = Depends(session_dependency)):
        rows = session.execute(select(ErpTransactionDocument.document_no,
                                      ErpTransactionDocument.occurred_at,
                                      ErpTransactionDocument.total_amount).join(
            ErpParty, ErpParty.id == ErpTransactionDocument.party_id).where(
            ErpTransactionDocument.snapshot_id == snapshot.id,
            ErpTransactionDocument.source_kind == "purchase",
            ErpParty.party_code == supplier_code).order_by(
            ErpTransactionDocument.occurred_at.desc()).limit(30)).all()
        return {"items": [dict(row._mapping) for row in rows]}

    def require_csrf(request: Request, permission: str):
        current = active_session(request)
        if not app.state.auth_enabled or not current:
            raise HTTPException(status_code=401, detail="Authentication required")
        if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), current.csrf_token):
            raise HTTPException(status_code=403, detail="CSRF validation failed")
        user = current_user(request)
        if not user or permission not in user.permissions:
            raise HTTPException(status_code=403, detail=f"Permission {permission} is required")
        return user

    def require_any_csrf(request: Request, permissions: set[str]):
        current = active_session(request)
        if not current:
            raise HTTPException(status_code=401, detail="Authentication required")
        if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), current.csrf_token):
            raise HTTPException(status_code=403, detail="CSRF validation failed")
        user = current_user(request)
        if not user or not permissions.intersection(user.permissions):
            raise HTTPException(status_code=403, detail=f"One of these permissions is required: {', '.join(sorted(permissions))}")
        return user

    def require_any_user(request: Request, permissions: set[str]):
        if not app.state.auth_enabled:
            return None
        user = current_user(request)
        if not user:
            raise HTTPException(status_code=401, detail="Authentication required")
        if not permissions.intersection(user.permissions):
            raise HTTPException(status_code=403, detail=f"One of these permissions is required: {', '.join(sorted(permissions))}")
        return user

    def operational_masters_present(operational_session: Session, model) -> bool:
        return bool(operational_session.scalar(select(func.count(model.id))))

    def prepare_draft(payload: DraftRequest, session: Session, operational_session: Session, user):
        snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == selected_snapshot))
        if operational_masters_present(operational_session, OperationalLocationMaster):
            location_record = operational_session.scalar(select(OperationalLocationMaster).where(or_(
                func.lower(OperationalLocationMaster.location_code) == payload.location_code.casefold(),
                func.lower(OperationalLocationMaster.name) == payload.location_code.casefold())))
            if location_record and location_record.status != "active":
                raise HTTPException(status_code=422, detail="Location is inactive in the operational master")
            location = ((location_record.location_code, location_record.name) if location_record else None)
        else:
            location = session.execute(select(ErpLocation.code, ErpLocation.name).where(
                ErpLocation.snapshot_id == snapshot.id,
                or_(func.lower(ErpLocation.code) == payload.location_code.casefold(),
                    func.lower(ErpLocation.name) == payload.location_code.casefold()))).first()
        if not location:
            raise HTTPException(status_code=422, detail="Location is not present in the operational master")
        if not location_allowed(user, location[0]):
            raise HTTPException(status_code=403, detail="Location is outside the user's operational scope")
        expected_kind = "customer" if payload.document_type == "sale" else "supplier"
        if operational_masters_present(operational_session, OperationalPartyMaster):
            party_record = operational_session.scalar(select(OperationalPartyMaster).where(
                OperationalPartyMaster.party_code == payload.party_code,
                OperationalPartyMaster.party_kind.in_((expected_kind, "both"))))
            if party_record and party_record.status != "active":
                raise HTTPException(status_code=422, detail=f"{expected_kind.title()} is inactive in the operational master")
            party = ((party_record.party_code, party_record.legal_or_business_name) if party_record else None)
        else:
            party = session.execute(select(ErpParty.party_code, ErpParty.legal_or_business_name).where(
                ErpParty.snapshot_id == snapshot.id, ErpParty.party_code == payload.party_code,
                ErpParty.party_kind.in_((expected_kind, "both")))).first()
        if not party and not operational_masters_present(operational_session, OperationalPartyMaster) and app.state.delta_overlay:
            party = next(((row["party_code"], row["legal_or_business_name"])
                          for row in app.state.delta_overlay.party_records(expected_kind)
                          if row["party_code"] == payload.party_code), None)
        if not party:
            raise HTTPException(status_code=422, detail=f"{expected_kind.title()} is not present in the cloned master")
        prepared_lines = []
        for item in payload.lines:
            if operational_masters_present(operational_session, OperationalProductMaster):
                product_record = operational_session.scalar(select(OperationalProductMaster).where(
                    OperationalProductMaster.sku == item.sku))
                if product_record and product_record.status != "active":
                    raise HTTPException(status_code=422, detail=f"Product SKU {item.sku} is inactive in the operational master")
                product = ((product_record.sku, product_record.name, product_record.purchase_price,
                            product_record.selling_price, product_record.base_uom,
                            product_record.canonical_base_uom, product_record.factor_to_base,
                            "operational") if product_record else None)
            else:
                product = session.execute(select(
                    ErpProductMaster.sku, ErpProductMaster.name,
                    ErpProductMaster.purchase_price_evidence, ErpProductMaster.selling_price_evidence,
                    ErpProductUom.source_base_uom, ErpProductUom.canonical_base_uom,
                    ErpProductUom.factor_to_base_snapshot, ErpProductUom.conversion_status,
                ).outerjoin(ErpProductUom, ErpProductUom.product_id == ErpProductMaster.id).where(
                    ErpProductMaster.snapshot_id == snapshot.id, ErpProductMaster.sku == item.sku)).first()
            if not product and not operational_masters_present(operational_session, OperationalProductMaster) and app.state.delta_overlay:
                overlay_product = next((row for row in app.state.delta_overlay.product_records()
                                        if row["sku"] == item.sku), None)
                if overlay_product:
                    product = (overlay_product["sku"], overlay_product["name"],
                               overlay_product["purchase_price_evidence"], overlay_product["selling_price_evidence"],
                               overlay_product["base_uom"], normalize_uom(overlay_product["base_uom"]),
                               Decimal("1"), "provisional")
            if not product:
                raise HTTPException(status_code=422, detail=f"Product SKU {item.sku} is not present in the cloned master")
            source_uom = str(product[4] or "")
            canonical_uom = normalize_uom(str(product[5] or "") or source_uom) or ""
            if (product[7] == "unobserved"
                    or normalize_uom(item.uom) not in {normalize_uom(source_uom), canonical_uom}):
                raise HTTPException(status_code=422, detail=f"UOM {item.uom} is not an approved base-unit mapping for SKU {item.sku}")
            factor = Decimal(str(product[6]))
            default_price = product[3] if payload.document_type == "sale" else product[2]
            price = item.unit_price if item.unit_price is not None else Decimal(str(default_price or "0"))
            net, tax, gross = calculate_line(item.quantity, price, item.tax_rate)
            unit_cost = Decimal(str(product[2])) if product[2] is not None else None
            cost_amount = ((item.quantity * factor * unit_cost).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP)
                           if unit_cost is not None else None)
            prepared_lines.append({"sku": item.sku, "product_name_snapshot": product[1],
                                   "quantity": item.quantity, "uom": item.uom,
                                   "canonical_uom": canonical_uom, "factor_to_base_snapshot": factor,
                                   "quantity_base": item.quantity * factor,
                                   "unit_price": price, "tax_rate": item.tax_rate,
                                   "net_amount": net, "tax_amount": tax, "gross_amount": gross,
                                   "unit_cost_snapshot": unit_cost, "cost_amount": cost_amount})
        return location, party, prepared_lines

    @app.post("/api/v1/drafts", status_code=201)
    def new_draft(payload: DraftRequest, request: Request,
                  session: Session = Depends(session_dependency),
                  operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "draft.create")
        location, party, prepared_lines = prepare_draft(payload, session, operational_session, user)
        try:
            draft = create_draft(
                operational_session, document_type=payload.document_type,
                party_code=payload.party_code, party_name=party[1], location_code=location[0],
                discount_amount=payload.discount_amount, notes=payload.notes,
                actor=user.username, lines=prepared_lines,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return draft_payload(draft)

    @app.put("/api/v1/drafts/{draft_key}")
    def edit_draft(draft_key: str, payload: DraftUpdateRequest, request: Request,
                   session: Session = Depends(session_dependency),
                   operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "draft.edit")
        draft = operational_session.scalar(select(OperationalDraft).where(
            OperationalDraft.draft_key == draft_key).with_for_update())
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        if draft.document_type != payload.document_type:
            raise HTTPException(status_code=422, detail="Draft document type cannot be changed")
        location, party, lines = prepare_draft(payload, session, operational_session, user)
        try:
            return draft_payload(replace_draft(
                operational_session, draft, expected_revision=payload.expected_revision,
                party_code=payload.party_code, party_name=party[1], location_code=location[0],
                discount_amount=payload.discount_amount, notes=payload.notes,
                actor=user.username, lines=lines,
            ))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def workflow_action(draft_key: str, action: str, payload: DraftTransitionRequest,
                        request: Request, operational_session):
        permission = {"submit": "draft.submit", "cancel": "draft.cancel", "approve": "draft.approve"}[action]
        user = require_csrf(request, permission)
        draft = operational_session.scalar(select(OperationalDraft).where(
            OperationalDraft.draft_key == draft_key).with_for_update())
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        if not location_allowed(user, draft.location_code):
            raise HTTPException(status_code=404, detail="Draft not found")
        try:
            return draft_payload(transition_draft(
                operational_session, draft, expected_revision=payload.expected_revision,
                action=action, actor=user.username, note=payload.note,
            ))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/drafts/{draft_key}/submit")
    def submit_draft(draft_key: str, payload: DraftTransitionRequest, request: Request,
                     operational_session=Depends(operational_session_dependency)):
        return workflow_action(draft_key, "submit", payload, request, operational_session)

    @app.post("/api/v1/drafts/{draft_key}/cancel")
    def cancel_draft(draft_key: str, payload: DraftTransitionRequest, request: Request,
                     operational_session=Depends(operational_session_dependency)):
        return workflow_action(draft_key, "cancel", payload, request, operational_session)

    @app.post("/api/v1/drafts/{draft_key}/approve")
    def approve_draft(draft_key: str, payload: DraftTransitionRequest, request: Request,
                      operational_session=Depends(operational_session_dependency)):
        return workflow_action(draft_key, "approve", payload, request, operational_session)

    @app.post("/api/v1/drafts/{draft_key}/posting-rehearsal")
    def posting_rehearsal(draft_key: str, request: Request,
                          operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "posting.rehearse")
        draft = operational_session.scalar(select(OperationalDraft).where(
            OperationalDraft.draft_key == draft_key).with_for_update())
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        if not location_allowed(user, draft.location_code):
            raise HTTPException(status_code=404, detail="Draft not found")
        try:
            if draft.document_type == "sale":
                return rehearse_sales_invoice_posting(operational_session, draft, actor=user.username)
            return rehearse_posting(operational_session, draft, actor=user.username)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/drafts/{draft_key}/post")
    def post_draft(draft_key: str, payload: PostingExecutionRequest, request: Request,
                   operational_session=Depends(operational_session_dependency)):
        if not app.state.posting_enabled:
            raise HTTPException(status_code=503, detail="Permanent posting activation is disabled")
        user = require_csrf(request, "posting.execute")
        draft = operational_session.scalar(select(OperationalDraft).where(
            OperationalDraft.draft_key == draft_key).with_for_update())
        if not draft or not location_allowed(user, draft.location_code):
            raise HTTPException(status_code=404, detail="Draft not found")
        try:
            if draft.document_type == "sale":
                return execute_integrated_posting(operational_session, resource_type="sales_invoice",
                    resource_key=draft.draft_key, actor=user.username,
                    idempotency_key=payload.idempotency_key)
            return execute_posting(operational_session, draft, actor=user.username,
                                   idempotency_key=payload.idempotency_key)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/journal-batches/{batch_key}/reverse")
    def reverse_batch(batch_key: str, payload: ReversalExecutionRequest, request: Request,
                      operational_session=Depends(operational_session_dependency)):
        if not app.state.posting_enabled:
            raise HTTPException(status_code=503, detail="Permanent posting activation is disabled")
        user = require_csrf(request, "posting.reverse")
        batch = operational_session.scalar(select(OperationalJournalBatch).where(
            OperationalJournalBatch.batch_key == batch_key).with_for_update())
        if not batch:
            raise HTTPException(status_code=404, detail="Journal batch not found")
        draft = operational_session.scalar(select(OperationalDraft).where(
            OperationalDraft.draft_key == batch.draft_key))
        if not draft or not location_allowed(user, draft.location_code):
            raise HTTPException(status_code=404, detail="Journal batch not found")
        try:
            return execute_reversal(operational_session, batch, actor=user.username,
                                    reason=payload.reason)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def inventory_document_payload(document: OperationalInventoryDocument) -> dict:
        return {
            "document_key": document.document_key, "document_no": document.document_no,
            "document_type": document.document_type, "location_code": document.location_code,
            "destination_location_code": document.destination_location_code,
            "adjustment_direction": document.adjustment_direction,
            "reason_code": document.reason_code, "status": document.status,
            "posting_enabled": document.posting_enabled, "notes": document.notes,
            "created_by": document.created_by, "created_at": document.created_at,
            "revision": document.revision, "state_changed_at": document.state_changed_at,
            "state_changed_by": document.state_changed_by,
            "lines": [{"line_no": line.line_no, "sku": line.sku,
                       "product_name": line.product_name_snapshot, "quantity": line.quantity,
                       "uom": line.uom, "canonical_uom": line.canonical_uom,
                       "factor_to_base_snapshot": line.factor_to_base_snapshot,
                       "quantity_base": line.quantity_base,
                       "unit_cost_snapshot": line.unit_cost_snapshot,
                       "value_snapshot": line.value_snapshot} for line in document.lines],
        }

    def prepare_inventory_document(payload: InventoryDocumentRequest, clone_session: Session,
                                   operational_session: Session, user) -> list[dict]:
        snapshot = clone_session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == selected_snapshot))
        if not snapshot:
            raise HTTPException(status_code=404, detail="Configured BizModo clone snapshot is unavailable")
        requested_locations = [payload.location_code]
        if payload.destination_location_code:
            requested_locations.append(payload.destination_location_code)
        if operational_masters_present(operational_session, OperationalLocationMaster):
            locations = set(operational_session.scalars(select(OperationalLocationMaster.location_code).where(
                OperationalLocationMaster.location_code.in_(requested_locations),
                OperationalLocationMaster.status == "active")))
        else:
            locations = set(clone_session.scalars(select(ErpLocation.code).where(
                ErpLocation.snapshot_id == snapshot.id,
                ErpLocation.code.in_(requested_locations),
            )))
        if locations != set(requested_locations):
            raise HTTPException(status_code=422, detail="Every inventory location must be active in the operational master")
        if any(not location_allowed(user, code) for code in requested_locations):
            raise HTTPException(status_code=403, detail="Inventory location is outside the user's operational scope")
        prepared: list[dict] = []
        for item in payload.lines:
            if operational_masters_present(operational_session, OperationalProductMaster):
                master = operational_session.scalar(select(OperationalProductMaster).where(
                    OperationalProductMaster.sku == item.sku, OperationalProductMaster.status == "active"))
                product = ((master.sku, master.name, master.purchase_price, master.base_uom,
                            master.canonical_base_uom, master.factor_to_base, "operational") if master else None)
            else:
                product = clone_session.execute(select(
                    ErpProductMaster.sku, ErpProductMaster.name, ErpProductMaster.purchase_price_evidence,
                    ErpProductUom.source_base_uom, ErpProductUom.canonical_base_uom,
                    ErpProductUom.factor_to_base_snapshot, ErpProductUom.conversion_status,
                ).outerjoin(ErpProductUom, ErpProductUom.product_id == ErpProductMaster.id).where(
                    ErpProductMaster.snapshot_id == snapshot.id, ErpProductMaster.sku == item.sku,
                )).first()
            if not product:
                raise HTTPException(status_code=422, detail=f"Product SKU {item.sku} is not active in the operational master")
            source_uom, canonical_uom = str(product[3] or ""), str(product[4] or "")
            if product[6] == "unobserved" or item.uom.casefold() not in {source_uom.casefold(), canonical_uom.casefold()}:
                raise HTTPException(status_code=422, detail=f"UOM {item.uom} is not an approved base-unit mapping for SKU {item.sku}")
            position = operational_session.scalar(select(OperationalStockPosition).where(
                OperationalStockPosition.location_code == payload.location_code,
                OperationalStockPosition.sku == item.sku,
            ))
            cost = item.unit_cost
            if cost is None and position is not None:
                cost = Decimal(str(position.average_unit_cost))
            if cost is None and product[2] is not None:
                cost = Decimal(str(product[2]))
            if cost is None:
                raise HTTPException(status_code=422, detail=f"Cost basis is unavailable for SKU {item.sku}")
            prepared.append({
                "sku": item.sku, "product_name_snapshot": product[1], "quantity": item.quantity,
                "uom": item.uom, "canonical_uom": canonical_uom,
                "factor_to_base_snapshot": Decimal(str(product[5])), "unit_cost_snapshot": cost,
            })
        return prepared

    @app.get("/api/v1/inventory-documents")
    def inventory_documents(request: Request,
                            operational_session=Depends(operational_session_dependency)):
        user = current_user(request)
        rows = list_inventory_documents(
            operational_session, allowed_locations=user.allowed_locations if user else (),
        )
        return {"items": [inventory_document_payload(row) for row in rows], "total": len(rows),
                "posting_enabled": False, "controls": inventory_control_counts(operational_session)}

    @app.get("/api/v1/inventory-documents/{document_key}")
    def inventory_document_detail(document_key: str, request: Request,
                                  operational_session=Depends(operational_session_dependency)):
        document = operational_session.scalar(select(OperationalInventoryDocument).where(
            OperationalInventoryDocument.document_key == document_key))
        user = current_user(request)
        if (not document or not user or not location_allowed(user, document.location_code)
                or (document.destination_location_code
                    and not location_allowed(user, document.destination_location_code))):
            raise HTTPException(status_code=404, detail="Inventory document not found")
        return inventory_document_payload(document)

    @app.post("/api/v1/inventory-documents", status_code=201)
    def new_inventory_document(payload: InventoryDocumentRequest, request: Request,
                               clone_session: Session = Depends(session_dependency),
                               operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "inventory.create")
        lines = prepare_inventory_document(payload, clone_session, operational_session, user)
        try:
            document = create_inventory_document(
                operational_session, document_type=payload.document_type,
                location_code=payload.location_code,
                destination_location_code=payload.destination_location_code,
                adjustment_direction=payload.adjustment_direction,
                reason_code=payload.reason_code, notes=payload.notes,
                actor=user.username, lines=lines,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return inventory_document_payload(document)

    @app.put("/api/v1/inventory-documents/{document_key}")
    def edit_inventory_document(document_key: str, payload: InventoryDocumentRequest,
                                request: Request, expected_revision: int = Query(ge=1),
                                clone_session: Session = Depends(session_dependency),
                                operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "inventory.edit")
        document = operational_session.scalar(select(OperationalInventoryDocument).where(
            OperationalInventoryDocument.document_key == document_key).with_for_update())
        if (not document or not location_allowed(user, document.location_code)
                or (document.destination_location_code
                    and not location_allowed(user, document.destination_location_code))):
            raise HTTPException(status_code=404, detail="Inventory document not found")
        lines = prepare_inventory_document(payload, clone_session, operational_session, user)
        try:
            return inventory_document_payload(replace_inventory_document(
                operational_session, document, expected_revision=expected_revision,
                document_type=payload.document_type, location_code=payload.location_code,
                destination_location_code=payload.destination_location_code,
                adjustment_direction=payload.adjustment_direction,
                reason_code=payload.reason_code, notes=payload.notes,
                actor=user.username, lines=lines,
            ))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def inventory_workflow_action(document_key: str, action: str,
                                  payload: DraftTransitionRequest, request: Request,
                                  operational_session: Session):
        permission = {"submit": "inventory.submit", "cancel": "inventory.cancel",
                      "approve": "inventory.approve"}[action]
        user = require_csrf(request, permission)
        document = operational_session.scalar(select(OperationalInventoryDocument).where(
            OperationalInventoryDocument.document_key == document_key).with_for_update())
        if (not document or not location_allowed(user, document.location_code)
                or (document.destination_location_code
                    and not location_allowed(user, document.destination_location_code))):
            raise HTTPException(status_code=404, detail="Inventory document not found")
        try:
            return inventory_document_payload(transition_inventory_document(
                operational_session, document, expected_revision=payload.expected_revision,
                action=action, actor=user.username, note=payload.note,
            ))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/inventory-documents/{document_key}/submit")
    def submit_inventory_document(document_key: str, payload: DraftTransitionRequest,
                                  request: Request,
                                  operational_session=Depends(operational_session_dependency)):
        return inventory_workflow_action(document_key, "submit", payload, request, operational_session)

    @app.post("/api/v1/inventory-documents/{document_key}/cancel")
    def cancel_inventory_document(document_key: str, payload: DraftTransitionRequest,
                                  request: Request,
                                  operational_session=Depends(operational_session_dependency)):
        return inventory_workflow_action(document_key, "cancel", payload, request, operational_session)

    @app.post("/api/v1/inventory-documents/{document_key}/approve")
    def approve_inventory_document(document_key: str, payload: DraftTransitionRequest,
                                   request: Request,
                                   operational_session=Depends(operational_session_dependency)):
        return inventory_workflow_action(document_key, "approve", payload, request, operational_session)

    @app.post("/api/v1/inventory-documents/{document_key}/posting-rehearsal")
    def inventory_posting_rehearsal(document_key: str, request: Request,
                                    operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "inventory.rehearse")
        document = operational_session.scalar(select(OperationalInventoryDocument).where(
            OperationalInventoryDocument.document_key == document_key).with_for_update())
        if (not document or not location_allowed(user, document.location_code)
                or (document.destination_location_code
                    and not location_allowed(user, document.destination_location_code))):
            raise HTTPException(status_code=404, detail="Inventory document not found")
        try:
            return rehearse_inventory_posting(operational_session, document, actor=user.username)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/warehouse-controls")
    def warehouse_controls(request: Request, operational_session=Depends(operational_session_dependency)):
        user = require_any_user(request, NAVIGATION_PERMISSION_RULES["warehouse-controls"])
        return warehouse_control_payload(operational_session, allowed_locations=user.allowed_locations)

    @app.post("/api/v1/warehouse-controls/cycle-counts", status_code=201)
    def new_cycle_count(payload: CycleCountRequest, request: Request,
                        operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "stock.count")
        if not location_allowed(user, payload.location_code):
            raise HTTPException(status_code=404, detail="Warehouse location not found")
        try:
            return cycle_count_payload(create_cycle_count(operational_session, location_code=payload.location_code,
                lines=[line.model_dump() for line in payload.lines], notes=payload.notes, actor=user.username))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/warehouse-controls/cycle-counts/{count_key}/{action}")
    def cycle_count_action(count_key: str, action: str, payload: DraftTransitionRequest, request: Request,
                           operational_session=Depends(operational_session_dependency)):
        if action not in {"submit", "cancel", "approve"}: raise HTTPException(status_code=404, detail="Cycle-count action not found")
        user = require_csrf(request, "inventory.submit" if action in {"submit", "cancel"} else "inventory.approve")
        record = operational_session.scalar(select(OperationalCycleCountSession).where(OperationalCycleCountSession.count_key == count_key).with_for_update())
        if not record or not location_allowed(user, record.location_code): raise HTTPException(status_code=404, detail="Cycle-count session not found")
        try: return cycle_count_payload(transition_cycle_count(operational_session, record, action=action, expected_revision=payload.expected_revision, actor=user.username, note=payload.note))
        except PermissionError as exc: raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/warehouse-controls/quarantine-holds", status_code=201)
    def new_quarantine_hold(payload: QuarantineHoldRequest, request: Request,
                            operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "quarantine.manage")
        if not location_allowed(user, payload.location_code): raise HTTPException(status_code=404, detail="Warehouse location not found")
        try: return quarantine_payload(create_quarantine_hold(operational_session, actor=user.username, **payload.model_dump()))
        except ValueError as exc: raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/warehouse-controls/quarantine-holds/{hold_key}/release")
    def release_quarantine(hold_key: str, payload: DraftTransitionRequest, request: Request,
                           operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "quarantine.manage")
        hold = operational_session.scalar(select(OperationalQuarantineHold).where(OperationalQuarantineHold.hold_key == hold_key).with_for_update())
        if not hold or not location_allowed(user, hold.location_code): raise HTTPException(status_code=404, detail="Quarantine hold not found")
        try: return quarantine_payload(release_quarantine_hold(operational_session, hold, expected_revision=payload.expected_revision, actor=user.username, note=payload.note or "Independent quarantine release"))
        except PermissionError as exc: raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/warehouse-controls/barcodes", status_code=201)
    def new_barcode_identity(payload: BarcodeRegistrationRequest, request: Request,
                             operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "barcode.manage")
        if not location_allowed(user, payload.location_code):
            raise HTTPException(status_code=404, detail="Warehouse location not found")
        try:
            return barcode_payload(register_barcode(
                operational_session, actor=user.username, **payload.model_dump()))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/warehouse-controls/serials", status_code=201)
    def new_serial_identity(payload: SerialRegistrationRequest, request: Request,
                            operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "serial.manage")
        if not location_allowed(user, payload.location_code):
            raise HTTPException(status_code=404, detail="Warehouse location not found")
        try:
            return serial_payload(register_serial(
                operational_session, actor=user.username, **payload.model_dump()))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/warehouse-controls/serials/{serial_key}/{action}")
    def serial_identity_action(serial_key: str, action: str, payload: SerialTransitionRequest,
                               request: Request,
                               operational_session=Depends(operational_session_dependency)):
        if action not in {"quarantine", "release", "retire"}:
            raise HTTPException(status_code=404, detail="Serial action not found")
        permission = "quarantine.manage" if action in {"quarantine", "release"} else "serial.manage"
        user = require_csrf(request, permission)
        row = operational_session.scalar(select(OperationalSerialUnit).where(
            OperationalSerialUnit.serial_key == serial_key).with_for_update())
        if not row or not location_allowed(user, row.location_code):
            raise HTTPException(status_code=404, detail="Serial identity not found")
        try:
            return serial_payload(transition_serial(
                operational_session, row, action=action,
                expected_revision=payload.expected_revision, actor=user.username,
                note=payload.note))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/warehouse-controls/scans", status_code=201)
    def warehouse_scan(payload: WarehouseScanRequest, request: Request,
                       operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "warehouse.scan")
        if not location_allowed(user, payload.location_code):
            raise HTTPException(status_code=404, detail="Warehouse location not found")
        try:
            return scan_payload(record_warehouse_scan(
                operational_session, actor=user.username, **payload.model_dump()))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def goods_receipt_payload(receipt: OperationalGoodsReceipt) -> dict:
        return {
            "receipt_key": receipt.receipt_key, "receipt_no": receipt.receipt_no,
            "supplier_code": receipt.supplier_code, "supplier_name": receipt.supplier_name_snapshot,
            "location_code": receipt.location_code, "purchase_reference": receipt.purchase_reference,
            "supplier_delivery_note": receipt.supplier_delivery_note, "received_on": receipt.received_on,
            "status": receipt.status, "posting_enabled": receipt.posting_enabled,
            "notes": receipt.notes, "created_by": receipt.created_by, "created_at": receipt.created_at,
            "revision": receipt.revision, "state_changed_at": receipt.state_changed_at,
            "state_changed_by": receipt.state_changed_by,
            "lines": [{"line_no": line.line_no, "sku": line.sku,
                       "product_name": line.product_name_snapshot,
                       "ordered_quantity": line.ordered_quantity,
                       "received_quantity": line.received_quantity,
                       "accepted_quantity": line.accepted_quantity,
                       "rejected_quantity": line.rejected_quantity, "uom": line.uom,
                       "canonical_uom": line.canonical_uom,
                       "factor_to_base_snapshot": line.factor_to_base_snapshot,
                       "accepted_quantity_base": line.accepted_quantity_base,
                       "unit_cost_snapshot": line.unit_cost_snapshot,
                       "accepted_value": line.accepted_value, "batch_no": line.batch_no,
                       "expiry_date": line.expiry_date,
                       "rejection_reason": line.rejection_reason} for line in receipt.lines],
        }

    def prepare_goods_receipt(payload: GoodsReceiptRequest, clone_session: Session,
                              operational_session: Session, user,
                              exclude_receipt_id: int | None = None) -> tuple[str, list[dict]]:
        snapshot = clone_session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == selected_snapshot))
        if not snapshot:
            raise HTTPException(status_code=404, detail="Configured BizModo clone snapshot is unavailable")
        if not location_allowed(user, payload.location_code):
            raise HTTPException(status_code=403, detail="Receipt location is outside the user's operational scope")
        if operational_masters_present(operational_session, OperationalLocationMaster):
            location_exists = operational_session.scalar(select(OperationalLocationMaster.id).where(
                OperationalLocationMaster.location_code == payload.location_code,
                OperationalLocationMaster.status == "active"))
        else:
            location_exists = clone_session.scalar(select(ErpLocation.id).where(
                ErpLocation.snapshot_id == snapshot.id, ErpLocation.code == payload.location_code))
        if not location_exists:
            raise HTTPException(status_code=422, detail="Receipt location is not active in the operational master")
        if operational_masters_present(operational_session, OperationalPartyMaster):
            supplier_record = operational_session.scalar(select(OperationalPartyMaster).where(
                OperationalPartyMaster.party_code == payload.supplier_code,
                OperationalPartyMaster.party_kind.in_(("supplier", "both")),
                OperationalPartyMaster.status == "active"))
            supplier = ((supplier_record.legal_or_business_name, supplier_record.party_kind)
                        if supplier_record else None)
        else:
            supplier = clone_session.execute(select(ErpParty.legal_or_business_name, ErpParty.party_kind).where(
                ErpParty.snapshot_id == snapshot.id, ErpParty.party_code == payload.supplier_code)).first()
        if not supplier or supplier[1] not in {"supplier", "both"}:
            raise HTTPException(status_code=422, detail="Supplier is not active in the operational supplier master")
        prepared: list[dict] = []
        for item in payload.lines:
            if operational_masters_present(operational_session, OperationalProductMaster):
                master = operational_session.scalar(select(OperationalProductMaster).where(
                    OperationalProductMaster.sku == item.sku, OperationalProductMaster.status == "active"))
                product = ((master.name, master.purchase_price, master.base_uom,
                            master.canonical_base_uom, master.factor_to_base, "operational") if master else None)
            else:
                product = clone_session.execute(select(
                    ErpProductMaster.name, ErpProductMaster.purchase_price_evidence,
                    ErpProductUom.source_base_uom, ErpProductUom.canonical_base_uom,
                    ErpProductUom.factor_to_base_snapshot, ErpProductUom.conversion_status,
                ).outerjoin(ErpProductUom, ErpProductUom.product_id == ErpProductMaster.id).where(
                    ErpProductMaster.snapshot_id == snapshot.id, ErpProductMaster.sku == item.sku)).first()
            if not product:
                raise HTTPException(status_code=422, detail=f"Product SKU {item.sku} is not active in the operational master")
            source_uom, canonical_uom = str(product[2] or ""), str(product[3] or "")
            if product[5] == "unobserved" or item.uom.casefold() not in {source_uom.casefold(), canonical_uom.casefold()}:
                raise HTTPException(status_code=422, detail=f"UOM {item.uom} is not an approved base-unit mapping for SKU {item.sku}")
            cost = item.unit_cost if item.unit_cost is not None else product[1]
            if cost is None:
                raise HTTPException(status_code=422, detail=f"Cost basis is unavailable for SKU {item.sku}")
            prepared.append({
                "sku": item.sku, "product_name_snapshot": product[0],
                "ordered_quantity": item.ordered_quantity, "received_quantity": item.received_quantity,
                "accepted_quantity": item.accepted_quantity, "rejected_quantity": item.rejected_quantity,
                "uom": item.uom, "canonical_uom": canonical_uom,
                "factor_to_base_snapshot": Decimal(str(product[4])),
                "unit_cost_snapshot": cost, "batch_no": item.batch_no,
                "expiry_date": item.expiry_date, "rejection_reason": item.rejection_reason,
            })
        try:
            validate_po_receipt(operational_session,
                purchase_reference=payload.purchase_reference,
                supplier_code=payload.supplier_code, location_code=payload.location_code,
                lines=prepared, exclude_receipt_id=exclude_receipt_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return supplier[0], prepared

    @app.get("/api/v1/goods-receipts")
    def goods_receipts(request: Request, operational_session=Depends(operational_session_dependency)):
        user = current_user(request)
        rows = list_goods_receipts(operational_session, allowed_locations=user.allowed_locations if user else ())
        return {"items": [goods_receipt_payload(row) for row in rows], "total": len(rows),
                "posting_enabled": False, "controls": goods_receipt_control_counts(operational_session)}

    @app.get("/api/v1/goods-receipts/{receipt_key}")
    def goods_receipt_detail(receipt_key: str, request: Request,
                             operational_session=Depends(operational_session_dependency)):
        receipt = operational_session.scalar(select(OperationalGoodsReceipt).where(
            OperationalGoodsReceipt.receipt_key == receipt_key))
        user = current_user(request)
        if not receipt or not user or not location_allowed(user, receipt.location_code):
            raise HTTPException(status_code=404, detail="Goods receipt not found")
        return goods_receipt_payload(receipt)

    @app.post("/api/v1/goods-receipts", status_code=201)
    def new_goods_receipt(payload: GoodsReceiptRequest, request: Request,
                          clone_session: Session = Depends(session_dependency),
                          operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "goods_receipt.create")
        supplier_name, lines = prepare_goods_receipt(payload, clone_session, operational_session, user)
        try:
            receipt = create_goods_receipt(
                operational_session, supplier_code=payload.supplier_code,
                supplier_name_snapshot=supplier_name, location_code=payload.location_code,
                purchase_reference=payload.purchase_reference,
                supplier_delivery_note=payload.supplier_delivery_note, received_on=payload.received_on,
                notes=payload.notes, actor=user.username, lines=lines)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return goods_receipt_payload(receipt)

    @app.put("/api/v1/goods-receipts/{receipt_key}")
    def edit_goods_receipt(receipt_key: str, payload: GoodsReceiptRequest, request: Request,
                           expected_revision: int = Query(ge=1),
                           clone_session: Session = Depends(session_dependency),
                           operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "goods_receipt.edit")
        receipt = operational_session.scalar(select(OperationalGoodsReceipt).where(
            OperationalGoodsReceipt.receipt_key == receipt_key).with_for_update())
        if not receipt or not location_allowed(user, receipt.location_code):
            raise HTTPException(status_code=404, detail="Goods receipt not found")
        supplier_name, lines = prepare_goods_receipt(payload, clone_session, operational_session, user,
                                                     exclude_receipt_id=receipt.id)
        try:
            receipt = replace_goods_receipt(
                operational_session, receipt, expected_revision=expected_revision,
                supplier_code=payload.supplier_code, supplier_name_snapshot=supplier_name,
                location_code=payload.location_code, purchase_reference=payload.purchase_reference,
                supplier_delivery_note=payload.supplier_delivery_note, received_on=payload.received_on,
                notes=payload.notes, actor=user.username, lines=lines)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return goods_receipt_payload(receipt)

    def goods_receipt_action(receipt_key: str, action: str, payload: DraftTransitionRequest,
                             request: Request, operational_session: Session):
        permission = {"submit": "goods_receipt.submit", "cancel": "goods_receipt.cancel",
                      "accept": "goods_receipt.accept", "reject": "goods_receipt.reject"}[action]
        user = require_csrf(request, permission)
        receipt = operational_session.scalar(select(OperationalGoodsReceipt).where(
            OperationalGoodsReceipt.receipt_key == receipt_key).with_for_update())
        if not receipt or not location_allowed(user, receipt.location_code):
            raise HTTPException(status_code=404, detail="Goods receipt not found")
        try:
            return goods_receipt_payload(transition_goods_receipt(
                operational_session, receipt, expected_revision=payload.expected_revision,
                action=action, actor=user.username, note=payload.note))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/goods-receipts/{receipt_key}/submit")
    def submit_goods_receipt(receipt_key: str, payload: DraftTransitionRequest, request: Request,
                             operational_session=Depends(operational_session_dependency)):
        return goods_receipt_action(receipt_key, "submit", payload, request, operational_session)

    @app.post("/api/v1/goods-receipts/{receipt_key}/cancel")
    def cancel_goods_receipt(receipt_key: str, payload: DraftTransitionRequest, request: Request,
                             operational_session=Depends(operational_session_dependency)):
        return goods_receipt_action(receipt_key, "cancel", payload, request, operational_session)

    @app.post("/api/v1/goods-receipts/{receipt_key}/accept")
    def accept_goods_receipt(receipt_key: str, payload: DraftTransitionRequest, request: Request,
                             operational_session=Depends(operational_session_dependency)):
        return goods_receipt_action(receipt_key, "accept", payload, request, operational_session)

    @app.post("/api/v1/goods-receipts/{receipt_key}/reject")
    def reject_goods_receipt(receipt_key: str, payload: DraftTransitionRequest, request: Request,
                             operational_session=Depends(operational_session_dependency)):
        return goods_receipt_action(receipt_key, "reject", payload, request, operational_session)

    @app.post("/api/v1/goods-receipts/{receipt_key}/posting-rehearsal")
    def goods_receipt_posting_rehearsal(receipt_key: str, request: Request,
                                        operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "goods_receipt.rehearse")
        receipt = operational_session.scalar(select(OperationalGoodsReceipt).where(
            OperationalGoodsReceipt.receipt_key == receipt_key).with_for_update())
        if not receipt or not location_allowed(user, receipt.location_code):
            raise HTTPException(status_code=404, detail="Goods receipt not found")
        try:
            return rehearse_goods_receipt_posting(operational_session, receipt, actor=user.username)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def sales_quotation_payload(document: OperationalSalesQuotation, operational_session: Session) -> dict:
        promotion_code = None
        if document.promotion_key:
            promotion_code = operational_session.scalar(select(OperationalPromotion.promotion_code).where(
                OperationalPromotion.promotion_key == document.promotion_key))
        return {"quotation_key": document.quotation_key, "quotation_no": document.quotation_no,
                "customer_code": document.customer_code, "customer_name": document.customer_name_snapshot,
                "location_code": document.location_code, "quotation_date": document.quotation_date,
                "valid_until": document.valid_until, "currency_code": document.currency_code,
                "subtotal": document.subtotal, "discount_amount": document.discount_amount,
                "tax_amount": document.tax_amount, "total_amount": document.total_amount,
                "payment_terms": document.payment_terms, "delivery_terms": document.delivery_terms,
                "notes": document.notes, "status": document.status,
                "customer_price_group": document.customer_price_group, "price_list_key": document.price_list_key,
                "promotion_key": document.promotion_key, "promotion_code": promotion_code,
                "posting_enabled": False, "stock_reservation_enabled": False,
                "created_by": document.created_by, "created_at": document.created_at,
                "approved_by": document.approved_by, "approval_note": document.approval_note,
                "acceptance_reference": document.acceptance_reference,
                "accepted_by": document.accepted_by, "accepted_at": document.accepted_at,
                "revision": document.revision, "state_changed_at": document.state_changed_at,
                "state_changed_by": document.state_changed_by,
                "sales_order_no": document.order.order_no if document.order else None,
                "lines": [{"line_no": line.line_no, "sku": line.sku,
                           "product_name": line.product_name_snapshot, "quantity": line.quantity,
                           "uom": line.uom, "canonical_uom": line.canonical_uom,
                           "factor_to_base_snapshot": line.factor_to_base_snapshot,
                           "quantity_base": line.quantity_base, "unit_price": line.unit_price,
                           "tax_rate": line.tax_rate, "net_amount": line.net_amount,
                           "tax_amount": line.tax_amount, "gross_amount": line.gross_amount}
                          for line in document.lines]}

    def sales_order_payload(document: OperationalSalesOrder) -> dict:
        return {"order_key": document.order_key, "order_no": document.order_no,
                "quotation_key": document.quotation.quotation_key,
                "quotation_no": document.quotation.quotation_no,
                "customer_code": document.customer_code, "customer_name": document.customer_name_snapshot,
                "location_code": document.location_code,
                "requested_delivery_date": document.requested_delivery_date,
                "currency_code": document.currency_code, "subtotal": document.subtotal,
                "discount_amount": document.discount_amount, "tax_amount": document.tax_amount,
                "total_amount": document.total_amount, "status": document.status,
                "posting_enabled": False, "stock_reservation_enabled": False,
                "created_by": document.created_by, "created_at": document.created_at,
                "lines": [{"line_no": line.line_no, "sku": line.sku,
                           "product_name": line.product_name_snapshot, "quantity": line.quantity,
                           "uom": line.uom, "canonical_uom": line.canonical_uom,
                           "factor_to_base_snapshot": line.factor_to_base_snapshot,
                           "quantity_base": line.quantity_base, "unit_price": line.unit_price,
                           "tax_rate": line.tax_rate, "net_amount": line.net_amount,
                           "tax_amount": line.tax_amount, "gross_amount": line.gross_amount}
                          for line in document.lines]}

    def prepare_sales_quotation(payload: SalesQuotationRequest, clone_session: Session,
                                operational_session: Session, user):
        draft_payload = DraftRequest(document_type="sale", party_code=payload.customer_code,
            location_code=payload.location_code, discount_amount=payload.discount_amount,
            notes=payload.notes, lines=payload.lines)
        location, customer, lines = prepare_draft(draft_payload, clone_session, operational_session, user)
        return location, customer, lines

    @app.get("/api/v1/pos")
    def pos_workspace(request: Request, operational_session: Session = Depends(operational_session_dependency)):
        user = require_user(request, "pos.read")
        return pos_workspace_payload(operational_session, user.allowed_locations if user else ("*",))

    @app.post("/api/v1/pos/tills", status_code=201)
    def pos_create_till(payload: PosTillRequest, request: Request,
                        operational_session: Session = Depends(operational_session_dependency)):
        user = require_user(request, "pos.manage")
        if user and not location_allowed(user, payload.location_code):
            raise HTTPException(status_code=403, detail="POS till location is outside your assigned scope")
        try:
            row = create_till(operational_session, actor=user.username if user else "test-user", **payload.model_dump())
            return {"till_key": row.till_key, "till_code": row.till_code, "posting_performed": False}
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/pos/shifts", status_code=201)
    def pos_open_shift(payload: PosShiftOpenRequest, request: Request,
                       operational_session: Session = Depends(operational_session_dependency)):
        user = require_user(request, "pos.sale")
        till = operational_session.scalar(select(OperationalPosTill).where(OperationalPosTill.till_key == payload.till_key))
        if till and user and not location_allowed(user, till.location_code):
            raise HTTPException(status_code=403, detail="POS till location is outside your assigned scope")
        try:
            row = open_shift(operational_session, actor=user.username if user else "test-user", **payload.model_dump())
            return {"shift_key": row.shift_key, "shift_no": row.shift_no, "status": row.status, "posting_performed": False}
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/pos/sales", status_code=201)
    def pos_record_sale(payload: PosSaleRequest, request: Request,
                        operational_session: Session = Depends(operational_session_dependency)):
        user = require_user(request, "pos.sale")
        shift = operational_session.scalar(select(OperationalPosShift).where(OperationalPosShift.shift_key == payload.shift_key))
        if shift and user and not location_allowed(user, shift.till.location_code):
            raise HTTPException(status_code=403, detail="POS shift location is outside your assigned scope")
        try:
            values = payload.model_dump(); values["lines"] = [line.model_dump() for line in payload.lines]
            row = record_sale(operational_session, actor=user.username if user else "test-user", **values)
            return {"sale_key": row.sale_key, "receipt_no": row.receipt_no, "total_amount": row.total_amount,
                    "change_amount": row.change_amount, "posting_performed": False, "stock_posting_performed": False}
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/pos/shifts/{shift_key}/submit-close")
    def pos_submit_close(shift_key: str, payload: PosCloseRequest, request: Request,
                         operational_session: Session = Depends(operational_session_dependency)):
        user = require_user(request, "cash.close.prepare")
        try:
            row = submit_close(operational_session, shift_key=shift_key,
                actor=user.username if user else "test-user", **payload.model_dump())
            return {"shift_key": row.shift_key, "status": row.status, "variance": row.variance, "posting_performed": False}
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/pos/shifts/{shift_key}/approve-close")
    def pos_approve_close(shift_key: str, payload: PosCloseApprovalRequest, request: Request,
                          operational_session: Session = Depends(operational_session_dependency)):
        user = require_user(request, "cash.close.approve")
        try:
            row = approve_close(operational_session, shift_key=shift_key,
                actor=user.username if user else "test-approver", **payload.model_dump())
            return {"shift_key": row.shift_key, "status": row.status, "variance": row.variance, "posting_performed": False}
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/van-sales")
    def van_sales_workspace(request: Request, operational_session: Session = Depends(operational_session_dependency)):
        require_user(request, "van.read")
        return van_workspace_payload(operational_session)

    @app.post("/api/v1/van-sales/routes", status_code=201)
    def van_create_route(payload: VanRouteRequest, request: Request,
                         operational_session: Session = Depends(operational_session_dependency)):
        user=require_user(request,"van.route.prepare")
        try:
            row=create_route(operational_session,actor=user.username if user else "test-user",**payload.model_dump())
            return {"route_key":row.route_key,"route_no":row.route_no,"status":row.status,"posting_performed":False}
        except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc

    @app.post("/api/v1/van-sales/routes/{route_key}/load")
    def van_submit_load(route_key: str, payload: VanLoadRequest, request: Request,
                        operational_session: Session = Depends(operational_session_dependency)):
        user=require_user(request,"van.route.prepare")
        try:
            values=payload.model_dump(); values["lines"]=[line.model_dump() for line in payload.lines]
            row=submit_load(operational_session,route_key=route_key,actor=user.username if user else "test-user",**values)
            return {"route_key":row.route_key,"status":row.status,"revision":row.revision,"stock_posting_performed":False}
        except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc

    @app.post("/api/v1/van-sales/routes/{route_key}/{action}")
    def van_transition(route_key: str, action: str, payload: VanTransitionRequest, request: Request,
                       operational_session: Session = Depends(operational_session_dependency)):
        permissions={"approve_load":"van.shift.approve","start":"van.shift","submit_close":"van.close.prepare","approve_close":"van.close.approve"}
        if action not in permissions: raise HTTPException(status_code=404,detail="Unsupported van-route action")
        user=require_user(request,permissions[action])
        try:
            row=transition_route(operational_session,route_key=route_key,action=action,
                actor=user.username if user else "test-user",**payload.model_dump())
            return {"route_key":row.route_key,"status":row.status,"revision":row.revision,
                    "variance":row.variance,"posting_performed":False}
        except PermissionError as exc: raise HTTPException(status_code=403,detail=str(exc)) from exc
        except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc

    @app.post("/api/v1/van-sales/offline-events")
    def van_sync_event(payload: VanOfflineEventRequest, request: Request,
                       operational_session: Session = Depends(operational_session_dependency)):
        user=require_user(request,"van.offline_sync")
        try:
            values=payload.model_dump(); values["lines"]=[line.model_dump() for line in payload.lines]
            row,replay=sync_offline_event(operational_session,actor=user.username if user else "test-user",**values)
            return {"event_key":row.event_key,"client_reference":row.client_reference,"amount":row.amount,
                    "tax_amount":row.tax_amount,"idempotent_replay":replay,"posting_performed":False}
        except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc

    @app.get("/api/v1/crm")
    def crm_workspace(request: Request, operational_session: Session = Depends(operational_session_dependency)):
        require_user(request, "crm.read")
        return crm_workspace_payload(operational_session)

    @app.post("/api/v1/crm/leads", status_code=201)
    def crm_create_lead(payload: CrmLeadRequest, request: Request, operational_session: Session = Depends(operational_session_dependency)):
        user=require_user(request, "crm.lead.prepare")
        row=create_lead(operational_session, actor=user.username, **payload.model_dump())
        return {"lead_key":row.lead_key,"lead_no":row.lead_no,"status":row.status,"posting_performed":False}

    @app.post("/api/v1/crm/leads/{lead_key}/activities", status_code=201)
    def crm_add_activity(lead_key: str, payload: CrmActivityRequest, request: Request, operational_session: Session = Depends(operational_session_dependency)):
        user=require_user(request, "crm.activity.prepare")
        try:
            row=add_activity(operational_session, lead_key=lead_key, actor=user.username, **payload.model_dump())
            return {"activity_key":row.activity_key,"posting_performed":False}
        except ValueError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc

    @app.post("/api/v1/crm/leads/{lead_key}/proposals", status_code=201)
    def crm_create_proposal(lead_key: str, payload: CrmProposalRequest, request: Request, operational_session: Session = Depends(operational_session_dependency)):
        user=require_user(request, "crm.proposal.prepare")
        try:
            row=create_proposal(operational_session, lead_key=lead_key, actor=user.username, **payload.model_dump())
            return {"proposal_key":row.proposal_key,"status":row.status,"revision":row.revision,"posting_performed":False}
        except ValueError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc

    @app.post("/api/v1/crm/proposals/{proposal_key}/{decision}")
    def crm_decide_proposal(proposal_key: str, decision: str, payload: CrmProposalDecisionRequest, request: Request, operational_session: Session = Depends(operational_session_dependency)):
        if decision not in {"approved","rejected"}: raise HTTPException(status_code=404,detail="Unsupported proposal decision")
        user=require_user(request, "crm.proposal.approve")
        try:
            row=decide_proposal(operational_session, proposal_key=proposal_key, decision=decision, actor=user.username, **payload.model_dump())
            return {"proposal_key":row.proposal_key,"status":row.status,"revision":row.revision,"posting_performed":False}
        except PermissionError as exc: raise HTTPException(status_code=403,detail=str(exc)) from exc
        except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc

    @app.get("/api/v1/commercial-pricing")
    def commercial_pricing_workspace(request: Request, operational_session=Depends(operational_session_dependency)):
        require_any_user(request, {"draft.create", "draft.edit", "draft.approve",
                                   "price_list.manage", "discount.approve"})
        lists = operational_session.scalars(select(OperationalPriceList).order_by(OperationalPriceList.effective_from.desc())).all()
        return {"posting_enabled": False,
                "groups": [{"group_code": row.group_code, "name": row.name, "status": row.status} for row in operational_session.scalars(select(OperationalCustomerPriceGroup).order_by(OperationalCustomerPriceGroup.group_code))],
                "assignments": [{"customer_code": row.customer_code, "group_code": row.group_code} for row in operational_session.scalars(select(OperationalCustomerPriceGroupAssignment).order_by(OperationalCustomerPriceGroupAssignment.customer_code))],
                "price_lists": [{"price_list_key": row.price_list_key, "name": row.name, "customer_group": row.customer_group, "effective_from": row.effective_from, "effective_to": row.effective_to, "max_discount_percent": row.max_discount_percent, "status": row.status, "created_by": row.created_by, "approved_by": row.approved_by, "items": [{"sku": item.sku, "unit_price": item.unit_price} for item in operational_session.scalars(select(OperationalPriceListItem).where(OperationalPriceListItem.price_list_id == row.id))]} for row in lists],
                "promotions": [{"promotion_key": row.promotion_key, "promotion_code": row.promotion_code, "name": row.name, "customer_group": row.customer_group, "sku": row.sku, "discount_percent": row.discount_percent, "effective_from": row.effective_from, "effective_to": row.effective_to, "status": row.status, "created_by": row.created_by, "approved_by": row.approved_by} for row in operational_session.scalars(select(OperationalPromotion).order_by(OperationalPromotion.effective_from.desc()))]}

    @app.post("/api/v1/commercial-pricing/groups", status_code=201)
    def commercial_price_group(payload: CustomerPriceGroupRequest, request: Request, operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "price_list.manage")
        try: return {"group_code": create_customer_price_group(operational_session, actor=user.username, **payload.model_dump()).group_code}
        except ValueError as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc

    def validate_pricing_customer(customer_code: str, clone_session: Session,
                                  operational_session: Session) -> None:
        if operational_masters_present(operational_session, OperationalPartyMaster):
            exists = operational_session.scalar(select(OperationalPartyMaster.id).where(
                OperationalPartyMaster.party_code == customer_code,
                OperationalPartyMaster.party_kind.in_(("customer", "both")),
                OperationalPartyMaster.status == "active"))
        else:
            snapshot = clone_session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == selected_snapshot))
            exists = clone_session.scalar(select(ErpParty.id).where(
                ErpParty.snapshot_id == snapshot.id, ErpParty.party_code == customer_code,
                ErpParty.party_kind.in_(("customer", "both"))))
        if not exists:
            raise ValueError("Customer is not active in the controlled customer master")

    def validate_pricing_skus(skus: set[str], clone_session: Session,
                              operational_session: Session) -> None:
        if not skus:
            return
        if operational_masters_present(operational_session, OperationalProductMaster):
            found = set(operational_session.scalars(select(OperationalProductMaster.sku).where(
                OperationalProductMaster.sku.in_(skus),
                OperationalProductMaster.status == "active")).all())
        else:
            snapshot = clone_session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == selected_snapshot))
            found = set(clone_session.scalars(select(ErpProductMaster.sku).where(
                ErpProductMaster.snapshot_id == snapshot.id,
                ErpProductMaster.sku.in_(skus))).all())
        missing = sorted(skus - found)
        if missing:
            raise ValueError(f"Product SKU is not active in the controlled product master: {', '.join(missing)}")

    @app.put("/api/v1/commercial-pricing/customers/{customer_code}/group")
    def commercial_customer_group(customer_code: str, payload: CustomerPriceGroupAssignmentRequest,
                                  request: Request, clone_session: Session = Depends(session_dependency),
                                  operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "price_list.manage")
        try:
            validate_pricing_customer(customer_code, clone_session, operational_session)
            return {"customer_code": assign_customer_price_group(operational_session, customer_code=customer_code, group_code=payload.group_code, actor=user.username).customer_code}
        except ValueError as exc: raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/commercial-pricing/price-lists", status_code=201)
    def commercial_price_list(payload: PriceListRequest, request: Request,
                              clone_session: Session = Depends(session_dependency),
                              operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "price_list.manage")
        try:
            values = payload.model_dump(); values["items"] = [item.model_dump() for item in payload.items]
            validate_pricing_skus({item.sku for item in payload.items}, clone_session, operational_session)
            return {"price_list_key": create_price_list(operational_session, actor=user.username, **values).price_list_key, "posting_enabled": False}
        except ValueError as exc: raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/commercial-pricing/price-lists/{price_list_key}/approve")
    def commercial_price_list_approval(price_list_key: str, request: Request, operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "discount.approve")
        try: return {"price_list_key": approve_price_list(operational_session, key=price_list_key, actor=user.username).price_list_key, "status": "approved", "posting_enabled": False}
        except PermissionError as exc: raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc: raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/commercial-pricing/promotions", status_code=201)
    def commercial_promotion(payload: PromotionRequest, request: Request,
                             clone_session: Session = Depends(session_dependency),
                             operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "price_list.manage")
        try:
            validate_pricing_skus({payload.sku} if payload.sku else set(), clone_session, operational_session)
            return {"promotion_key": create_promotion(operational_session, actor=user.username, **payload.model_dump()).promotion_key, "posting_enabled": False}
        except ValueError as exc: raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/commercial-pricing/promotions/{promotion_key}/approve")
    def commercial_promotion_approval(promotion_key: str, request: Request, operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "discount.approve")
        try: return {"promotion_key": approve_promotion(operational_session, promotion_key=promotion_key, actor=user.username).promotion_key, "status": "approved", "posting_enabled": False}
        except PermissionError as exc: raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc: raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v1/sales-orders")
    def sales_orders_workspace(request: Request,
                               operational_session=Depends(operational_session_dependency)):
        user = current_user(request)
        locations = user.allowed_locations if user else ()
        quotations = list_sales_quotations(operational_session, allowed_locations=locations)
        orders = list_sales_orders(operational_session, allowed_locations=locations)
        return {"quotations": [sales_quotation_payload(row, operational_session) for row in quotations],
                "orders": [sales_order_payload(row) for row in orders],
                "controls": sales_order_control_counts(operational_session)}

    @app.get("/api/v1/sales-orders/quotations/{quotation_key}")
    def sales_quotation_detail(quotation_key: str, request: Request,
                               operational_session=Depends(operational_session_dependency)):
        user = current_user(request)
        document = operational_session.scalar(select(OperationalSalesQuotation).where(
            OperationalSalesQuotation.quotation_key == quotation_key))
        if not document or not user or not location_allowed(user, document.location_code):
            raise HTTPException(status_code=404, detail="Sales quotation not found")
        return sales_quotation_payload(document, operational_session)

    @app.post("/api/v1/sales-orders/quotations", status_code=201)
    def new_sales_quotation(payload: SalesQuotationRequest, request: Request,
                            clone_session: Session = Depends(session_dependency),
                            operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "draft.create")
        location, customer, lines = prepare_sales_quotation(payload, clone_session, operational_session, user)
        try:
            document = create_sales_quotation(operational_session,
                customer_code=customer[0], customer_name_snapshot=customer[1], location_code=location[0],
                quotation_date=payload.quotation_date, valid_until=payload.valid_until,
                discount_amount=payload.discount_amount, payment_terms=payload.payment_terms,
                delivery_terms=payload.delivery_terms, notes=payload.notes,
                actor=user.username, lines=lines, promotion_code=payload.promotion_code)
        except ValueError as exc:
            operational_session.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return sales_quotation_payload(document, operational_session)

    @app.put("/api/v1/sales-orders/quotations/{quotation_key}")
    def edit_sales_quotation(quotation_key: str, payload: SalesQuotationRequest, request: Request,
                             expected_revision: int = Query(ge=1),
                             clone_session: Session = Depends(session_dependency),
                             operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "draft.edit")
        document = operational_session.scalar(select(OperationalSalesQuotation).where(
            OperationalSalesQuotation.quotation_key == quotation_key).with_for_update())
        if not document or not location_allowed(user, document.location_code):
            raise HTTPException(status_code=404, detail="Sales quotation not found")
        location, customer, lines = prepare_sales_quotation(payload, clone_session, operational_session, user)
        try:
            document = replace_sales_quotation(operational_session, document,
                expected_revision=expected_revision, customer_code=customer[0],
                customer_name_snapshot=customer[1], location_code=location[0],
                quotation_date=payload.quotation_date, valid_until=payload.valid_until,
                discount_amount=payload.discount_amount, payment_terms=payload.payment_terms,
                delivery_terms=payload.delivery_terms, notes=payload.notes,
                actor=user.username, lines=lines, promotion_code=payload.promotion_code)
        except ValueError as exc:
            operational_session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return sales_quotation_payload(document, operational_session)

    def sales_quotation_action(quotation_key: str, action: str, payload: DraftTransitionRequest,
                               request: Request, operational_session: Session):
        permission = "draft.approve" if action in {"approve", "reject"} else f"draft.{action}"
        user = require_csrf(request, permission)
        document = operational_session.scalar(select(OperationalSalesQuotation).where(
            OperationalSalesQuotation.quotation_key == quotation_key).with_for_update())
        if not document or not location_allowed(user, document.location_code):
            raise HTTPException(status_code=404, detail="Sales quotation not found")
        try:
            document = transition_sales_quotation(operational_session, document,
                expected_revision=payload.expected_revision, action=action,
                actor=user.username, note=payload.note)
        except PermissionError as exc:
            operational_session.rollback()
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            operational_session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return sales_quotation_payload(document, operational_session)

    @app.post("/api/v1/sales-orders/quotations/{quotation_key}/submit")
    def submit_sales_quotation(quotation_key: str, payload: DraftTransitionRequest, request: Request,
                               operational_session=Depends(operational_session_dependency)):
        return sales_quotation_action(quotation_key, "submit", payload, request, operational_session)

    @app.post("/api/v1/sales-orders/quotations/{quotation_key}/cancel")
    def cancel_sales_quotation(quotation_key: str, payload: DraftTransitionRequest, request: Request,
                               operational_session=Depends(operational_session_dependency)):
        return sales_quotation_action(quotation_key, "cancel", payload, request, operational_session)

    @app.post("/api/v1/sales-orders/quotations/{quotation_key}/approve")
    def approve_sales_quotation(quotation_key: str, payload: DraftTransitionRequest, request: Request,
                                operational_session=Depends(operational_session_dependency)):
        return sales_quotation_action(quotation_key, "approve", payload, request, operational_session)

    @app.post("/api/v1/sales-orders/quotations/{quotation_key}/reject")
    def reject_sales_quotation(quotation_key: str, payload: DraftTransitionRequest, request: Request,
                               operational_session=Depends(operational_session_dependency)):
        return sales_quotation_action(quotation_key, "reject", payload, request, operational_session)

    @app.post("/api/v1/sales-orders/quotations/{quotation_key}/accept")
    def record_sales_quotation_acceptance(quotation_key: str, payload: SalesQuotationAcceptanceRequest,
                                          request: Request,
                                          operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"draft.create", "draft.approve"})
        document = operational_session.scalar(select(OperationalSalesQuotation).where(
            OperationalSalesQuotation.quotation_key == quotation_key).with_for_update())
        if not document or not location_allowed(user, document.location_code):
            raise HTTPException(status_code=404, detail="Sales quotation not found")
        try:
            document = accept_sales_quotation(operational_session, document,
                expected_revision=payload.expected_revision, actor=user.username,
                acceptance_reference=payload.acceptance_reference)
        except ValueError as exc:
            operational_session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return sales_quotation_payload(document, operational_session)

    @app.post("/api/v1/sales-orders/quotations/{quotation_key}/convert")
    def convert_sales_quotation_to_order(quotation_key: str, payload: SalesOrderConversionRequest,
                                         request: Request,
                                         operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"draft.create", "draft.approve"})
        document = operational_session.scalar(select(OperationalSalesQuotation).where(
            OperationalSalesQuotation.quotation_key == quotation_key).with_for_update())
        if not document or not location_allowed(user, document.location_code):
            raise HTTPException(status_code=404, detail="Sales quotation not found")
        try:
            order = convert_sales_quotation(operational_session, document,
                expected_revision=payload.expected_revision, actor=user.username,
                requested_delivery_date=payload.requested_delivery_date,
                conversion_note=payload.conversion_note)
        except ValueError as exc:
            operational_session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return sales_order_payload(order)

    def delivery_payload(document: OperationalDeliveryFulfillment) -> dict:
        return {"fulfillment_key": document.fulfillment_key,
                "fulfillment_no": document.fulfillment_no,
                "sales_order_key": document.sales_order.order_key,
                "sales_order_no": document.sales_order.order_no,
                "customer_name": document.sales_order.customer_name_snapshot,
                "location_code": document.location_code, "status": document.status,
                "revision": document.revision, "posting_enabled": False,
                "invoice_eligible": document.status == "delivered",
                "allocation_note": document.allocation_note,
                "delivery_note_no": document.delivery_note_no,
                "vehicle_number": document.vehicle_number, "driver_name": document.driver_name,
                "dispatched_at": document.dispatched_at, "dispatched_by": document.dispatched_by,
                "received_by": document.received_by, "pod_reference": document.pod_reference,
                "pod_note": document.pod_note, "delivered_at": document.delivered_at,
                "delivered_by": document.delivered_by, "created_by": document.created_by,
                "created_at": document.created_at, "state_changed_at": document.state_changed_at,
                "state_changed_by": document.state_changed_by,
                "total_amount": document.sales_order.total_amount,
                "lines": [{"line_no": line.line_no, "sku": line.sku,
                           "product_name": line.product_name_snapshot,
                           "ordered_quantity": line.ordered_quantity, "uom": line.uom,
                           "canonical_uom": line.canonical_uom,
                           "factor_to_base_snapshot": line.factor_to_base_snapshot,
                           "ordered_quantity_base": line.ordered_quantity_base,
                           "allocated_quantity_base": line.allocated_quantity_base,
                           "picked_quantity_base": line.picked_quantity_base,
                           "dispatched_quantity_base": line.dispatched_quantity_base,
                           "delivered_quantity_base": line.delivered_quantity_base}
                          for line in document.lines]}

    @app.get("/api/v1/deliveries")
    def deliveries_workspace(request: Request,
                             operational_session=Depends(operational_session_dependency)):
        user=current_user(request); locations=user.allowed_locations if user else ()
        allocated_order_ids=select(OperationalDeliveryFulfillment.sales_order_id)
        order_query=select(OperationalSalesOrder).where(
            OperationalSalesOrder.status == "confirmed",
            OperationalSalesOrder.id.not_in(allocated_order_ids))
        if "*" not in locations:
            order_query=order_query.where(OperationalSalesOrder.location_code.in_(locations))
        orders=list(operational_session.scalars(order_query.order_by(OperationalSalesOrder.created_at.desc()).limit(100)))
        deliveries=list_delivery_fulfillments(operational_session, allowed_locations=locations)
        return {"ready_orders": [sales_order_payload(row) for row in orders],
                "deliveries": [delivery_payload(row) for row in deliveries],
                "controls": delivery_control_counts(operational_session)}

    @app.post("/api/v1/deliveries/orders/{order_key}/allocate", status_code=201)
    def allocate_delivery(order_key: str, payload: DeliveryAllocationRequest, request: Request,
                          operational_session=Depends(operational_session_dependency)):
        user=require_any_csrf(request, {"delivery.allocate", "inventory.create"})
        order=operational_session.scalar(select(OperationalSalesOrder).where(
            OperationalSalesOrder.order_key == order_key).with_for_update())
        if not order or not location_allowed(user, order.location_code):
            raise HTTPException(status_code=404, detail="Sales order not found")
        try:
            document=allocate_sales_order(operational_session, order, actor=user.username, note=payload.note)
        except ValueError as exc:
            operational_session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return delivery_payload(document)

    def delivery_action(fulfillment_key: str, action: str, payload, request: Request,
                        operational_session: Session):
        permissions={"pick": {"delivery.pick", "inventory.edit"},
                     "dispatch": {"delivery.dispatch", "inventory.submit"},
                     "deliver": {"delivery.pod", "inventory.approve"},
                     "cancel": {"delivery.cancel", "inventory.cancel"}}[action]
        user=require_any_csrf(request, permissions)
        document=operational_session.scalar(select(OperationalDeliveryFulfillment).where(
            OperationalDeliveryFulfillment.fulfillment_key == fulfillment_key).with_for_update())
        if not document or not location_allowed(user, document.location_code):
            raise HTTPException(status_code=404, detail="Delivery fulfillment not found")
        try:
            document=transition_delivery(operational_session, document,
                expected_revision=payload.expected_revision, action=action,
                actor=user.username, note=payload.note,
                vehicle_number=getattr(payload, "vehicle_number", None),
                driver_name=getattr(payload, "driver_name", None),
                received_by=getattr(payload, "received_by", None),
                pod_reference=getattr(payload, "pod_reference", None),
                occurred_at=(getattr(payload, "dispatched_at", None)
                             or getattr(payload, "delivered_at", None)))
        except (RuntimeError, ValueError) as exc:
            operational_session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return delivery_payload(document)

    @app.post("/api/v1/deliveries/{fulfillment_key}/pick")
    def pick_delivery(fulfillment_key: str, payload: DeliveryActionRequest, request: Request,
                      operational_session=Depends(operational_session_dependency)):
        return delivery_action(fulfillment_key, "pick", payload, request, operational_session)

    @app.post("/api/v1/deliveries/{fulfillment_key}/cancel")
    def cancel_delivery(fulfillment_key: str, payload: DeliveryActionRequest, request: Request,
                        operational_session=Depends(operational_session_dependency)):
        return delivery_action(fulfillment_key, "cancel", payload, request, operational_session)

    @app.post("/api/v1/deliveries/{fulfillment_key}/dispatch")
    def dispatch_delivery(fulfillment_key: str, payload: DeliveryDispatchRequest, request: Request,
                          operational_session=Depends(operational_session_dependency)):
        return delivery_action(fulfillment_key, "dispatch", payload, request, operational_session)

    @app.post("/api/v1/deliveries/{fulfillment_key}/proof-of-delivery")
    def complete_delivery(fulfillment_key: str, payload: ProofOfDeliveryRequest, request: Request,
                          operational_session=Depends(operational_session_dependency)):
        return delivery_action(fulfillment_key, "deliver", payload, request, operational_session)

    def customer_invoice_payload(document: OperationalCustomerInvoice,
                                 operational_session: Session) -> dict:
        rehearsal = operational_session.scalar(select(OperationalCustomerInvoicePostingRehearsal).where(
            OperationalCustomerInvoicePostingRehearsal.invoice_id == document.id).order_by(
                OperationalCustomerInvoicePostingRehearsal.generated_at.desc()))
        settlement = customer_invoice_settlement(operational_session, document)
        return {
            "invoice_key": document.invoice_key, "invoice_no": document.invoice_no,
            "sales_order_no": document.sales_order_no_snapshot,
            "delivery_note_no": document.delivery_note_no_snapshot,
            "pod_reference": document.pod_reference_snapshot,
            "customer_code": document.customer_code,
            "customer_name": document.customer_name_snapshot,
            "location_code": document.location_code, "invoice_date": document.invoice_date,
            "due_date": document.due_date, "currency_code": document.currency_code,
            "subtotal": document.subtotal, "discount_amount": document.discount_amount,
            "tax_amount": document.tax_amount, "total_amount": document.total_amount,
            "status": document.status, "posting_enabled": False, "notes": document.notes,
            "created_by": document.created_by, "created_at": document.created_at,
            "approved_by": document.approved_by, "approval_note": document.approval_note,
            "revision": document.revision, "state_changed_at": document.state_changed_at,
            "state_changed_by": document.state_changed_by,
            **settlement,
            "posting_rehearsal": (customer_invoice_rehearsal_payload(rehearsal, document)
                                   if rehearsal else None),
            "lines": [{"line_no": line.line_no, "sku": line.sku,
                       "product_name": line.product_name_snapshot, "quantity": line.quantity,
                       "uom": line.uom, "canonical_uom": line.canonical_uom,
                       "factor_to_base_snapshot": line.factor_to_base_snapshot,
                       "quantity_base": line.quantity_base, "unit_price": line.unit_price,
                       "tax_rate": line.tax_rate, "net_amount": line.net_amount,
                       "tax_amount": line.tax_amount, "gross_amount": line.gross_amount}
                      for line in document.lines],
        }

    @app.get("/api/v1/customer-invoices")
    def customer_invoices_workspace(request: Request,
                                    operational_session=Depends(operational_session_dependency)):
        user = current_user(request); locations = user.allowed_locations if user else ()
        invoiced_fulfillment_ids = select(OperationalCustomerInvoice.fulfillment_id)
        ready_query = select(OperationalDeliveryFulfillment).where(
            OperationalDeliveryFulfillment.status == "delivered",
            OperationalDeliveryFulfillment.id.not_in(invoiced_fulfillment_ids))
        if "*" not in locations:
            ready_query = ready_query.where(OperationalDeliveryFulfillment.location_code.in_(locations))
        ready = list(operational_session.scalars(ready_query.order_by(
            OperationalDeliveryFulfillment.delivered_at.desc()).limit(100)))
        invoices = list_customer_invoices(operational_session, allowed_locations=locations)
        return {"ready_deliveries": [delivery_payload(row) for row in ready],
                "invoices": [customer_invoice_payload(row, operational_session) for row in invoices],
                "controls": customer_invoice_control_counts(operational_session)}

    @app.post("/api/v1/customer-invoices/deliveries/{fulfillment_key}", status_code=201)
    def new_customer_invoice(fulfillment_key: str, payload: CustomerInvoiceCreateRequest,
                             request: Request,
                             operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"customer_invoice.create", "draft.create"})
        fulfillment = operational_session.scalar(select(OperationalDeliveryFulfillment).where(
            OperationalDeliveryFulfillment.fulfillment_key == fulfillment_key).with_for_update())
        if not fulfillment or not location_allowed(user, fulfillment.location_code):
            raise HTTPException(status_code=404, detail="Delivered order not found")
        try:
            document = create_customer_invoice(operational_session, fulfillment,
                actor=user.username, invoice_date=payload.invoice_date,
                due_date=payload.due_date, notes=payload.notes)
        except ValueError as exc:
            operational_session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return customer_invoice_payload(document, operational_session)

    def customer_invoice_action(invoice_key: str, action: str,
                                payload: DraftTransitionRequest, request: Request,
                                operational_session: Session):
        permissions = ({"customer_invoice.approve", "draft.approve"}
                       if action in {"approve", "reject"}
                       else {f"customer_invoice.{action}", f"draft.{action}"})
        user = require_any_csrf(request, permissions)
        document = operational_session.scalar(select(OperationalCustomerInvoice).where(
            OperationalCustomerInvoice.invoice_key == invoice_key).with_for_update())
        if not document or not location_allowed(user, document.location_code):
            raise HTTPException(status_code=404, detail="Customer invoice not found")
        try:
            document = transition_customer_invoice(operational_session, document,
                expected_revision=payload.expected_revision, action=action,
                actor=user.username, note=payload.note)
        except PermissionError as exc:
            operational_session.rollback()
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            operational_session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return customer_invoice_payload(document, operational_session)

    @app.post("/api/v1/customer-invoices/{invoice_key}/submit")
    def submit_customer_invoice(invoice_key: str, payload: DraftTransitionRequest,
                                request: Request,
                                operational_session=Depends(operational_session_dependency)):
        return customer_invoice_action(invoice_key, "submit", payload, request, operational_session)

    @app.post("/api/v1/customer-invoices/{invoice_key}/cancel")
    def cancel_customer_invoice(invoice_key: str, payload: DraftTransitionRequest,
                                request: Request,
                                operational_session=Depends(operational_session_dependency)):
        return customer_invoice_action(invoice_key, "cancel", payload, request, operational_session)

    @app.post("/api/v1/customer-invoices/{invoice_key}/approve")
    def approve_customer_invoice(invoice_key: str, payload: DraftTransitionRequest,
                                 request: Request,
                                 operational_session=Depends(operational_session_dependency)):
        return customer_invoice_action(invoice_key, "approve", payload, request, operational_session)

    @app.post("/api/v1/customer-invoices/{invoice_key}/reject")
    def reject_customer_invoice(invoice_key: str, payload: DraftTransitionRequest,
                                request: Request,
                                operational_session=Depends(operational_session_dependency)):
        return customer_invoice_action(invoice_key, "reject", payload, request, operational_session)

    @app.post("/api/v1/customer-invoices/{invoice_key}/posting-rehearsal")
    def rehearse_delivery_backed_customer_invoice(
            invoice_key: str, request: Request,
            operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"customer_invoice.rehearse", "draft.approve"})
        document = operational_session.scalar(select(OperationalCustomerInvoice).where(
            OperationalCustomerInvoice.invoice_key == invoice_key).with_for_update())
        if not document or not location_allowed(user, document.location_code):
            raise HTTPException(status_code=404, detail="Customer invoice not found")
        try:
            result = rehearse_customer_invoice(operational_session, document, actor=user.username)
        except (RuntimeError, ValueError) as exc:
            operational_session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return result

    def sales_return_payload(document: OperationalSalesReturn, operational_session: Session) -> dict:
        rehearsal = operational_session.scalar(select(OperationalSalesReturnPostingRehearsal).where(
            OperationalSalesReturnPostingRehearsal.sales_return_id == document.id).order_by(
                OperationalSalesReturnPostingRehearsal.generated_at.desc()))
        posting = operational_session.scalar(select(OperationalIntegratedPostingBatch).where(
            OperationalIntegratedPostingBatch.resource_type == "sales_return",
            OperationalIntegratedPostingBatch.resource_key == document.return_key,
            OperationalIntegratedPostingBatch.batch_kind == "posting"))
        return {"return_key": document.return_key, "return_no": document.return_no,
                "customer_code": document.customer_code, "customer_name": document.customer_name_snapshot,
                "location_code": document.location_code,
                "original_invoice_reference": document.original_invoice_reference,
                "original_invoice_source_record_id": document.original_invoice_source_record_id,
                "original_invoice_total_snapshot": document.original_invoice_total_snapshot,
                "original_invoice_evidence_hash": document.original_invoice_evidence_hash,
                "return_date": document.return_date, "reason_code": document.reason_code,
                "currency_code": document.currency_code, "subtotal": document.subtotal,
                "tax_amount": document.tax_amount, "total_amount": document.total_amount,
                "status": document.status, "posting_enabled": app.state.posting_enabled,
                "notes": document.notes, "created_by": document.created_by, "created_at": document.created_at,
                "revision": document.revision, "state_changed_at": document.state_changed_at,
                "state_changed_by": document.state_changed_by,
                "credit_note": ({"credit_note_key": document.credit_note.credit_note_key,
                                 "credit_note_no": document.credit_note.credit_note_no,
                                 "status": document.credit_note.status,
                                 "posting_enabled": document.credit_note.posting_enabled,
                                 "total_amount": document.credit_note.total_amount}
                                if document.credit_note else None),
                "posting_rehearsal": (_sales_return_rehearsal_payload(rehearsal, document)
                                      if rehearsal else None),
                "posting": ({"batch_key": posting.batch_key, "status": posting.status,
                    "posted_at": posting.posted_at, "posted_by": posting.posted_by,
                    "posting_fingerprint": posting.posting_fingerprint} if posting else None),
                "lines": [{"line_no": line.line_no, "sku": line.sku,
                           "product_name": line.product_name_snapshot, "quantity": line.quantity,
                           "restock_quantity": line.restock_quantity,
                           "writeoff_quantity": line.writeoff_quantity, "uom": line.uom,
                           "canonical_uom": line.canonical_uom,
                           "factor_to_base_snapshot": line.factor_to_base_snapshot,
                           "quantity_base": line.quantity_base, "unit_price": line.unit_price,
                           "tax_rate": line.tax_rate, "net_amount": line.net_amount,
                           "tax_amount": line.tax_amount, "gross_amount": line.gross_amount,
                           "unit_cost_snapshot": line.unit_cost_snapshot,
                           "disposition_reason": line.disposition_reason} for line in document.lines]}

    def prepare_sales_return(payload: SalesReturnRequest, clone_session: Session,
                             operational_session: Session, user) -> tuple[str, dict, list[dict]]:
        snapshot = clone_session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == selected_snapshot))
        if not snapshot:
            raise HTTPException(status_code=404, detail="Configured BizModo clone snapshot is unavailable")
        if not location_allowed(user, payload.location_code):
            raise HTTPException(status_code=403, detail="Return location is outside the user's operational scope")
        if operational_masters_present(operational_session, OperationalLocationMaster):
            location_exists = operational_session.scalar(select(OperationalLocationMaster.id).where(
                OperationalLocationMaster.location_code == payload.location_code,
                OperationalLocationMaster.status == "active"))
        else:
            location_exists = clone_session.scalar(select(ErpLocation.id).where(
                ErpLocation.snapshot_id == snapshot.id, ErpLocation.code == payload.location_code))
        if not location_exists:
            raise HTTPException(status_code=422, detail="Return location is not active in the operational master")
        operational_customer = None
        if operational_masters_present(operational_session, OperationalPartyMaster):
            operational_customer = operational_session.scalar(select(OperationalPartyMaster).where(
                OperationalPartyMaster.party_code == payload.customer_code,
                OperationalPartyMaster.party_kind.in_(("customer", "both")),
                OperationalPartyMaster.status == "active"))
            if not operational_customer:
                raise HTTPException(status_code=422, detail="Customer is not active in the operational customer master")
        customer = clone_session.execute(select(ErpParty.id, ErpParty.legal_or_business_name).where(
            ErpParty.snapshot_id == snapshot.id, ErpParty.party_code == payload.customer_code,
            ErpParty.party_kind.in_(("customer", "both")))).first()
        if not customer:
            raise HTTPException(status_code=422, detail="Customer is not present in the cloned customer master")
        invoice = clone_session.scalar(select(ErpTransactionDocument).where(
            ErpTransactionDocument.snapshot_id == snapshot.id,
            ErpTransactionDocument.source_kind == "sale",
            ErpTransactionDocument.document_no == payload.original_invoice_reference,
            ErpTransactionDocument.party_id == customer.id))
        if not invoice:
            raise HTTPException(status_code=422, detail="Original invoice was not found for the selected customer in the cloned sales register")
        invoice_total = Decimal(str(invoice.total_amount or 0))
        if invoice_total <= 0 or not invoice.source_raw_record_id:
            raise HTTPException(status_code=422, detail="Original invoice total or immutable source evidence is unavailable")
        prepared: list[dict] = []
        invoice_line_evidence: list[dict] = []
        for item in payload.lines:
            clone_product_id = clone_session.scalar(select(ErpProductMaster.id).where(
                ErpProductMaster.snapshot_id == snapshot.id, ErpProductMaster.sku == item.sku))
            if operational_masters_present(operational_session, OperationalProductMaster):
                master = operational_session.scalar(select(OperationalProductMaster).where(
                    OperationalProductMaster.sku == item.sku, OperationalProductMaster.status == "active"))
                product = ((master.name, master.purchase_price, master.selling_price, master.base_uom,
                            master.canonical_base_uom, master.factor_to_base, "operational") if master else None)
            else:
                product = clone_session.execute(select(
                    ErpProductMaster.name, ErpProductMaster.purchase_price_evidence,
                    ErpProductMaster.selling_price_evidence, ErpProductUom.source_base_uom,
                    ErpProductUom.canonical_base_uom, ErpProductUom.factor_to_base_snapshot,
                    ErpProductUom.conversion_status,
                ).outerjoin(ErpProductUom, ErpProductUom.product_id == ErpProductMaster.id).where(
                    ErpProductMaster.snapshot_id == snapshot.id, ErpProductMaster.sku == item.sku)).first()
            if not product:
                raise HTTPException(status_code=422, detail=f"Product SKU {item.sku} is not active in the operational master")
            if not clone_product_id:
                raise HTTPException(status_code=422, detail=f"Original invoice product evidence is unavailable for SKU {item.sku}")
            source_uom, canonical_uom = str(product[3] or ""), str(product[4] or "")
            if product[6] == "unobserved" or item.uom.casefold() not in {source_uom.casefold(), canonical_uom.casefold()}:
                raise HTTPException(status_code=422, detail=f"UOM {item.uom} is not an approved base-unit mapping for SKU {item.sku}")
            position = operational_session.scalar(select(OperationalStockPosition).where(
                OperationalStockPosition.location_code == payload.location_code,
                OperationalStockPosition.sku == item.sku))
            source_lines = clone_session.execute(select(ErpTransactionLine.entered_quantity,
                ErpTransactionLine.entered_uom, ErpTransactionLine.unit_price,
                ErpTransactionLine.source_raw_record_id).where(
                    ErpTransactionLine.document_id == invoice.id,
                    ErpTransactionLine.product_id == clone_product_id)).all()
            compatible = [row for row in source_lines if str(row.entered_uom or "").casefold()
                          in {source_uom.casefold(), canonical_uom.casefold()}]
            invoice_quantity = sum((Decimal(str(row.entered_quantity or 0)) for row in compatible), Decimal("0"))
            invoice_prices = {Decimal(str(row.unit_price)) for row in compatible if row.unit_price is not None}
            if invoice_quantity <= 0 or len(invoice_prices) != 1:
                raise HTTPException(status_code=422,
                    detail=f"Unique original invoice quantity and price evidence is unavailable for SKU {item.sku}")
            invoice_price = next(iter(invoice_prices))
            if item.quantity > invoice_quantity:
                raise HTTPException(status_code=422, detail=f"Return quantity exceeds original invoice quantity for SKU {item.sku}")
            if item.unit_price is not None and Decimal(str(item.unit_price)) != invoice_price:
                raise HTTPException(status_code=422, detail=f"Return price must match the original invoice price for SKU {item.sku}")
            price = invoice_price
            cost = item.unit_cost
            if cost is None and position is not None:
                cost = position.average_unit_cost
            if cost is None:
                cost = product[1]
            if price is None or cost is None:
                raise HTTPException(status_code=422, detail=f"Return price or cost basis is unavailable for SKU {item.sku}")
            prepared.append({"sku": item.sku, "product_name_snapshot": product[0],
                "quantity": item.quantity, "restock_quantity": item.restock_quantity,
                "writeoff_quantity": item.writeoff_quantity, "uom": item.uom,
                "canonical_uom": canonical_uom, "factor_to_base_snapshot": Decimal(str(product[5])),
                "unit_price": price, "tax_rate": item.tax_rate, "unit_cost_snapshot": cost,
                "original_invoice_quantity_snapshot": invoice_quantity,
                "original_invoice_unit_price_snapshot": invoice_price,
                "disposition_reason": item.disposition_reason})
            invoice_line_evidence.append({"sku": item.sku, "quantity": str(invoice_quantity),
                "unit_price": str(invoice_price),
                "source_record_ids": sorted({int(row.source_raw_record_id) for row in compatible})})
        evidence_source = json.dumps({"snapshot": snapshot.name,
            "source_record_id": invoice.source_raw_record_id,
            "document_no": invoice.document_no, "customer_code": payload.customer_code,
            "total": str(invoice_total), "lines": sorted(invoice_line_evidence, key=lambda row: row["sku"])},
            sort_keys=True, separators=(",", ":"))
        evidence = {"source_record_id": invoice.source_raw_record_id,
            "total_amount": invoice_total,
            "evidence_hash": hashlib.sha256(evidence_source.encode()).hexdigest()}
        return (operational_customer.legal_or_business_name if operational_customer
                else customer.legal_or_business_name), evidence, prepared

    @app.get("/api/v1/sales-returns")
    def sales_returns(request: Request, operational_session=Depends(operational_session_dependency)):
        user = current_user(request)
        rows = list_sales_returns(operational_session, allowed_locations=user.allowed_locations if user else ())
        controls = sales_return_control_counts(operational_session)
        controls.update({"posting_enabled": app.state.posting_enabled,
            "posting_rehearsals": operational_session.scalar(select(func.count(
                OperationalSalesReturnPostingRehearsal.id))) or 0})
        return {"items": [sales_return_payload(row, operational_session) for row in rows],
                "total": len(rows), "posting_enabled": app.state.posting_enabled, "controls": controls}

    @app.get("/api/v1/sales-returns/{return_key}")
    def sales_return_detail(return_key: str, request: Request,
                            operational_session=Depends(operational_session_dependency)):
        document = operational_session.scalar(select(OperationalSalesReturn).where(OperationalSalesReturn.return_key == return_key))
        user = current_user(request)
        if not document or not user or not location_allowed(user, document.location_code):
            raise HTTPException(status_code=404, detail="Sales return not found")
        return sales_return_payload(document, operational_session)

    @app.post("/api/v1/sales-returns", status_code=201)
    def new_sales_return(payload: SalesReturnRequest, request: Request,
                         clone_session: Session = Depends(session_dependency),
                         operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "sales_return.create")
        customer_name, evidence, lines = prepare_sales_return(payload, clone_session, operational_session, user)
        try:
            document = create_sales_return(operational_session, customer_code=payload.customer_code,
                customer_name_snapshot=customer_name, location_code=payload.location_code,
                original_invoice_reference=payload.original_invoice_reference, return_date=payload.return_date,
                reason_code=payload.reason_code, notes=payload.notes, actor=user.username, lines=lines,
                original_invoice_source_record_id=evidence["source_record_id"],
                original_invoice_total_snapshot=evidence["total_amount"],
                original_invoice_evidence_hash=evidence["evidence_hash"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return sales_return_payload(document, operational_session)

    @app.put("/api/v1/sales-returns/{return_key}")
    def edit_sales_return(return_key: str, payload: SalesReturnRequest, request: Request,
                          expected_revision: int = Query(ge=1),
                          clone_session: Session = Depends(session_dependency),
                          operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "sales_return.edit")
        document = operational_session.scalar(select(OperationalSalesReturn).where(
            OperationalSalesReturn.return_key == return_key).with_for_update())
        if not document or not location_allowed(user, document.location_code):
            raise HTTPException(status_code=404, detail="Sales return not found")
        customer_name, evidence, lines = prepare_sales_return(payload, clone_session, operational_session, user)
        try:
            document = replace_sales_return(operational_session, document, expected_revision=expected_revision,
                customer_code=payload.customer_code, customer_name_snapshot=customer_name,
                location_code=payload.location_code, original_invoice_reference=payload.original_invoice_reference,
                return_date=payload.return_date, reason_code=payload.reason_code, notes=payload.notes,
                actor=user.username, lines=lines,
                original_invoice_source_record_id=evidence["source_record_id"],
                original_invoice_total_snapshot=evidence["total_amount"],
                original_invoice_evidence_hash=evidence["evidence_hash"])
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return sales_return_payload(document, operational_session)

    def sales_return_action(return_key: str, action: str, payload: DraftTransitionRequest,
                            request: Request, operational_session: Session):
        permission = {"submit": "sales_return.submit", "cancel": "sales_return.cancel",
                      "approve": "sales_return.approve"}[action]
        user = require_csrf(request, permission)
        document = operational_session.scalar(select(OperationalSalesReturn).where(
            OperationalSalesReturn.return_key == return_key).with_for_update())
        if not document or not location_allowed(user, document.location_code):
            raise HTTPException(status_code=404, detail="Sales return not found")
        try:
            return sales_return_payload(transition_sales_return(operational_session, document,
                expected_revision=payload.expected_revision, action=action, actor=user.username, note=payload.note),
                operational_session)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/sales-returns/{return_key}/submit")
    def submit_sales_return(return_key: str, payload: DraftTransitionRequest, request: Request,
                            operational_session=Depends(operational_session_dependency)):
        return sales_return_action(return_key, "submit", payload, request, operational_session)

    @app.post("/api/v1/sales-returns/{return_key}/cancel")
    def cancel_sales_return(return_key: str, payload: DraftTransitionRequest, request: Request,
                            operational_session=Depends(operational_session_dependency)):
        return sales_return_action(return_key, "cancel", payload, request, operational_session)

    @app.post("/api/v1/sales-returns/{return_key}/approve")
    def approve_sales_return(return_key: str, payload: DraftTransitionRequest, request: Request,
                             operational_session=Depends(operational_session_dependency)):
        return sales_return_action(return_key, "approve", payload, request, operational_session)

    @app.post("/api/v1/sales-returns/{return_key}/posting-rehearsal")
    def sales_return_posting_rehearsal(return_key: str, request: Request,
                                       operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "sales_return.rehearse")
        document = operational_session.scalar(select(OperationalSalesReturn).where(
            OperationalSalesReturn.return_key == return_key).with_for_update())
        if not document or not location_allowed(user, document.location_code):
            raise HTTPException(status_code=404, detail="Sales return not found")
        try:
            return rehearse_sales_return_posting(operational_session, document, actor=user.username)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def purchase_return_payload(document: OperationalPurchaseReturn, operational_session: Session) -> dict:
        rehearsal = operational_session.scalar(select(OperationalPurchaseReturnPostingRehearsal).where(
            OperationalPurchaseReturnPostingRehearsal.purchase_return_id == document.id).order_by(
                OperationalPurchaseReturnPostingRehearsal.generated_at.desc()))
        posting = operational_session.scalar(select(OperationalIntegratedPostingBatch).where(
            OperationalIntegratedPostingBatch.resource_type == "purchase_return",
            OperationalIntegratedPostingBatch.resource_key == document.return_key,
            OperationalIntegratedPostingBatch.batch_kind == "posting"))
        linked_invoice = None
        if rehearsal:
            linked_invoice = operational_session.get(OperationalSupplierInvoice,
                                                     rehearsal.original_supplier_invoice_id)
        return {"return_key":document.return_key,"return_no":document.return_no,
                "supplier_code":document.supplier_code,"supplier_name":document.supplier_name_snapshot,
                "location_code":document.location_code,"source_reference_type":document.source_reference_type,
                "source_reference_key":document.source_reference_key,"return_date":document.return_date,
                "reason_code":document.reason_code,"currency_code":document.currency_code,
                "subtotal":document.subtotal,"tax_amount":document.tax_amount,"total_amount":document.total_amount,
                "status":document.status,"posting_enabled":app.state.posting_enabled,"notes":document.notes,
                "created_by":document.created_by,"created_at":document.created_at,"revision":document.revision,
                "state_changed_at":document.state_changed_at,"state_changed_by":document.state_changed_by,
                "debit_note":({"debit_note_key":document.debit_note.debit_note_key,
                               "debit_note_no":document.debit_note.debit_note_no,
                               "status":document.debit_note.status,"posting_enabled":document.debit_note.posting_enabled,
                               "total_amount":document.debit_note.total_amount} if document.debit_note else None),
                "linked_supplier_invoice":({"invoice_key":linked_invoice.invoice_key,
                    "supplier_invoice_no":linked_invoice.supplier_invoice_no,
                    "status":linked_invoice.status} if linked_invoice else None),
                "posting_rehearsal":(_purchase_return_rehearsal_payload(
                    rehearsal, document, linked_invoice) if rehearsal and linked_invoice else None),
                "posting":({"batch_key":posting.batch_key,"status":posting.status,
                    "posted_at":posting.posted_at,"posted_by":posting.posted_by,
                    "posting_fingerprint":posting.posting_fingerprint} if posting else None),
                "lines":[{"line_no":line.line_no,"sku":line.sku,"product_name":line.product_name_snapshot,
                          "source_received_quantity":line.source_received_quantity,"quantity":line.quantity,
                          "supplier_return_quantity":line.supplier_return_quantity,
                          "internal_writeoff_quantity":line.internal_writeoff_quantity,"uom":line.uom,
                          "canonical_uom":line.canonical_uom,"factor_to_base_snapshot":line.factor_to_base_snapshot,
                          "quantity_base":line.quantity_base,"unit_price":line.unit_price,"tax_rate":line.tax_rate,
                          "net_amount":line.net_amount,"tax_amount":line.tax_amount,"gross_amount":line.gross_amount,
                          "unit_cost_snapshot":line.unit_cost_snapshot,
                          "disposition_reason":line.disposition_reason} for line in document.lines]}

    def prepare_purchase_return(payload: PurchaseReturnRequest, clone_session: Session,
                                operational_session: Session, user) -> tuple[str,list[dict]]:
        snapshot=clone_session.scalar(select(SourceSnapshot).where(SourceSnapshot.name==selected_snapshot))
        if not snapshot: raise HTTPException(status_code=404,detail="Configured BizModo clone snapshot is unavailable")
        if not location_allowed(user,payload.location_code): raise HTTPException(status_code=403,detail="Return location is outside the user's operational scope")
        if operational_masters_present(operational_session,OperationalLocationMaster):
            if not operational_session.scalar(select(OperationalLocationMaster.id).where(OperationalLocationMaster.location_code==payload.location_code,OperationalLocationMaster.status=="active")): raise HTTPException(status_code=422,detail="Return location is not active in the operational master")
        elif not clone_session.scalar(select(ErpLocation.id).where(ErpLocation.snapshot_id==snapshot.id,ErpLocation.code==payload.location_code)): raise HTTPException(status_code=422,detail="Return location is not present in the cloned master")
        operational_supplier=None
        if operational_masters_present(operational_session,OperationalPartyMaster):
            operational_supplier=operational_session.scalar(select(OperationalPartyMaster).where(OperationalPartyMaster.party_code==payload.supplier_code,OperationalPartyMaster.party_kind.in_(("supplier","both")),OperationalPartyMaster.status=="active"))
            if not operational_supplier: raise HTTPException(status_code=422,detail="Supplier is not active in the operational supplier master")
        supplier=clone_session.execute(select(ErpParty.id,ErpParty.legal_or_business_name).where(ErpParty.snapshot_id==snapshot.id,ErpParty.party_code==payload.supplier_code,ErpParty.party_kind.in_(("supplier","both")))).first()
        if not supplier: raise HTTPException(status_code=422,detail="Supplier is not present in the cloned supplier master")
        source_grn=None; source_invoice=None
        if payload.source_reference_type=="goods_receipt":
            source_grn=operational_session.scalar(select(OperationalGoodsReceipt).where(
                or_(OperationalGoodsReceipt.receipt_key==payload.source_reference_key,
                    OperationalGoodsReceipt.receipt_no==payload.source_reference_key),
                OperationalGoodsReceipt.supplier_code==payload.supplier_code,
                OperationalGoodsReceipt.location_code==payload.location_code,
                OperationalGoodsReceipt.status=="accepted"))
            if not source_grn: raise HTTPException(status_code=422,detail="Accepted goods receipt was not found for this supplier and location")
        else:
            source_invoice=clone_session.scalar(select(ErpTransactionDocument).where(
                ErpTransactionDocument.snapshot_id==snapshot.id,ErpTransactionDocument.source_kind=="purchase",
                ErpTransactionDocument.document_no==payload.source_reference_key,
                ErpTransactionDocument.party_id==supplier.id))
            if not source_invoice: raise HTTPException(status_code=422,detail="Purchase invoice was not found for the selected supplier in the cloned register")
        prepared=[]
        for item in payload.lines:
            product=clone_session.execute(select(ErpProductMaster.id,ErpProductMaster.name,ErpProductMaster.purchase_price_evidence,ErpProductUom.source_base_uom,ErpProductUom.canonical_base_uom,ErpProductUom.factor_to_base_snapshot,ErpProductUom.conversion_status).outerjoin(ErpProductUom,ErpProductUom.product_id==ErpProductMaster.id).where(ErpProductMaster.snapshot_id==snapshot.id,ErpProductMaster.sku==item.sku)).first()
            if operational_masters_present(operational_session,OperationalProductMaster):
                master=operational_session.scalar(select(OperationalProductMaster).where(OperationalProductMaster.sku==item.sku,OperationalProductMaster.status=="active"))
                if master and product: product=(product[0],master.name,master.purchase_price,master.base_uom,master.canonical_base_uom,master.factor_to_base,"operational")
                elif not master: product=None
            if not product: raise HTTPException(status_code=422,detail=f"Product SKU {item.sku} is not present in the cloned master")
            source_uom,canonical_uom=str(product[3] or ""),str(product[4] or ""); factor=Decimal(str(product[5]))
            if product[6]=="unobserved" or item.uom.casefold() not in {source_uom.casefold(),canonical_uom.casefold()}: raise HTTPException(status_code=422,detail=f"UOM {item.uom} is not an approved base-unit mapping for SKU {item.sku}")
            if source_grn:
                accepted_base=sum((line.accepted_quantity_base for line in source_grn.lines if line.sku==item.sku),Decimal("0")); source_quantity=accepted_base/factor
                source_price=next((line.unit_cost_snapshot for line in source_grn.lines if line.sku==item.sku),None)
            else:
                source_lines=clone_session.execute(select(ErpTransactionLine.entered_quantity,ErpTransactionLine.entered_uom,ErpTransactionLine.unit_price).where(ErpTransactionLine.document_id==source_invoice.id,ErpTransactionLine.product_id==product[0])).all()
                compatible=[line for line in source_lines if str(line.entered_uom or "").casefold() in {source_uom.casefold(),canonical_uom.casefold()}]
                source_quantity=sum((Decimal(str(line.entered_quantity or 0)) for line in compatible),Decimal("0")); source_price=next((line.unit_price for line in compatible if line.unit_price is not None),None)
            if source_quantity<=0: raise HTTPException(status_code=422,detail=f"Verified received quantity is unavailable for SKU {item.sku} on the selected source")
            position=operational_session.scalar(select(OperationalStockPosition).where(OperationalStockPosition.location_code==payload.location_code,OperationalStockPosition.sku==item.sku))
            price=item.unit_price if item.unit_price is not None else (source_price if source_price is not None else product[2])
            cost=position.average_unit_cost if position is not None else product[2]
            if price is None or cost is None: raise HTTPException(status_code=422,detail=f"Purchase return price or cost basis is unavailable for SKU {item.sku}")
            prepared.append({"sku":item.sku,"product_name_snapshot":product[1],"source_received_quantity":source_quantity,
                "quantity":item.quantity,"supplier_return_quantity":item.supplier_return_quantity,
                "internal_writeoff_quantity":item.internal_writeoff_quantity,"uom":item.uom,"canonical_uom":canonical_uom,
                "factor_to_base_snapshot":factor,"unit_price":price,"tax_rate":item.tax_rate,
                "unit_cost_snapshot":cost,"disposition_reason":item.disposition_reason})
        return (operational_supplier.legal_or_business_name if operational_supplier else supplier.legal_or_business_name),prepared

    @app.get("/api/v1/purchase-returns")
    def purchase_returns(request:Request,operational_session=Depends(operational_session_dependency)):
        user=current_user(request); rows=list_purchase_returns(operational_session,allowed_locations=user.allowed_locations if user else ())
        controls=purchase_return_control_counts(operational_session)
        controls.update({"posting_enabled":app.state.posting_enabled,
            "posting_rehearsals":operational_session.scalar(select(func.count(
                OperationalPurchaseReturnPostingRehearsal.id))) or 0})
        return {"items":[purchase_return_payload(row,operational_session) for row in rows],
            "total":len(rows),"posting_enabled":app.state.posting_enabled,"controls":controls}

    @app.get("/api/v1/purchase-returns/{return_key}")
    def purchase_return_detail(return_key:str,request:Request,operational_session=Depends(operational_session_dependency)):
        document=operational_session.scalar(select(OperationalPurchaseReturn).where(OperationalPurchaseReturn.return_key==return_key)); user=current_user(request)
        if not document or not user or not location_allowed(user,document.location_code): raise HTTPException(status_code=404,detail="Purchase return not found")
        return purchase_return_payload(document,operational_session)

    @app.post("/api/v1/purchase-returns",status_code=201)
    def new_purchase_return(payload:PurchaseReturnRequest,request:Request,clone_session:Session=Depends(session_dependency),operational_session=Depends(operational_session_dependency)):
        user=require_csrf(request,"purchase_return.create"); supplier_name,lines=prepare_purchase_return(payload,clone_session,operational_session,user)
        try: document=create_purchase_return(operational_session,supplier_code=payload.supplier_code,supplier_name_snapshot=supplier_name,location_code=payload.location_code,source_reference_type=payload.source_reference_type,source_reference_key=payload.source_reference_key,return_date=payload.return_date,reason_code=payload.reason_code,notes=payload.notes,actor=user.username,lines=lines)
        except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc
        return purchase_return_payload(document,operational_session)

    @app.put("/api/v1/purchase-returns/{return_key}")
    def edit_purchase_return(return_key:str,payload:PurchaseReturnRequest,request:Request,expected_revision:int=Query(ge=1),clone_session:Session=Depends(session_dependency),operational_session=Depends(operational_session_dependency)):
        user=require_csrf(request,"purchase_return.edit"); document=operational_session.scalar(select(OperationalPurchaseReturn).where(OperationalPurchaseReturn.return_key==return_key).with_for_update())
        if not document or not location_allowed(user,document.location_code): raise HTTPException(status_code=404,detail="Purchase return not found")
        supplier_name,lines=prepare_purchase_return(payload,clone_session,operational_session,user)
        try: document=replace_purchase_return(operational_session,document,expected_revision=expected_revision,supplier_code=payload.supplier_code,supplier_name_snapshot=supplier_name,location_code=payload.location_code,source_reference_type=payload.source_reference_type,source_reference_key=payload.source_reference_key,return_date=payload.return_date,reason_code=payload.reason_code,notes=payload.notes,actor=user.username,lines=lines)
        except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc
        return purchase_return_payload(document,operational_session)

    def purchase_return_action(return_key:str,action:str,payload:DraftTransitionRequest,request:Request,operational_session:Session):
        permission={"submit":"purchase_return.submit","cancel":"purchase_return.cancel","approve":"purchase_return.approve"}[action]; user=require_csrf(request,permission); document=operational_session.scalar(select(OperationalPurchaseReturn).where(OperationalPurchaseReturn.return_key==return_key).with_for_update())
        if not document or not location_allowed(user,document.location_code): raise HTTPException(status_code=404,detail="Purchase return not found")
        try: return purchase_return_payload(transition_purchase_return(operational_session,document,expected_revision=payload.expected_revision,action=action,actor=user.username,note=payload.note),operational_session)
        except PermissionError as exc: raise HTTPException(status_code=403,detail=str(exc)) from exc
        except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc

    @app.post("/api/v1/purchase-returns/{return_key}/submit")
    def submit_purchase_return(return_key:str,payload:DraftTransitionRequest,request:Request,operational_session=Depends(operational_session_dependency)): return purchase_return_action(return_key,"submit",payload,request,operational_session)
    @app.post("/api/v1/purchase-returns/{return_key}/cancel")
    def cancel_purchase_return(return_key:str,payload:DraftTransitionRequest,request:Request,operational_session=Depends(operational_session_dependency)): return purchase_return_action(return_key,"cancel",payload,request,operational_session)
    @app.post("/api/v1/purchase-returns/{return_key}/approve")
    def approve_purchase_return(return_key:str,payload:DraftTransitionRequest,request:Request,operational_session=Depends(operational_session_dependency)): return purchase_return_action(return_key,"approve",payload,request,operational_session)
    @app.post("/api/v1/purchase-returns/{return_key}/posting-rehearsal")
    def purchase_return_posting_rehearsal(return_key:str,request:Request,operational_session=Depends(operational_session_dependency)):
        user=require_csrf(request,"purchase_return.rehearse"); document=operational_session.scalar(select(OperationalPurchaseReturn).where(OperationalPurchaseReturn.return_key==return_key).with_for_update())
        if not document or not location_allowed(user,document.location_code): raise HTTPException(status_code=404,detail="Purchase return not found")
        try: return rehearse_purchase_return_posting(operational_session,document,actor=user.username)
        except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc

    def payment_payload(payment: OperationalPayment, operational_session: Session) -> dict:
        rehearsal = operational_session.scalar(select(OperationalPaymentPostingRehearsal).where(
            OperationalPaymentPostingRehearsal.payment_id == payment.id).order_by(
                OperationalPaymentPostingRehearsal.generated_at.desc()))
        return {"payment_key": payment.payment_key, "payment_no": payment.payment_no,
                "payment_type": payment.payment_type, "party_code": payment.party_code,
                "party_name": payment.party_name_snapshot, "location_code": payment.location_code,
                "payment_date": payment.payment_date, "payment_method": payment.payment_method,
                "cash_bank_account_code": payment.cash_bank_account_code,
                "reference_no": payment.reference_no, "currency_code": payment.currency_code,
                "amount": payment.amount, "allocated_amount": payment.allocated_amount,
                "unallocated_amount": payment.unallocated_amount, "status": payment.status,
                "posting_enabled": payment.posting_enabled, "notes": payment.notes,
                "created_by": payment.created_by, "created_at": payment.created_at,
                "revision": payment.revision, "state_changed_at": payment.state_changed_at,
                "state_changed_by": payment.state_changed_by,
                "posting_rehearsal": (payment_rehearsal_payload(rehearsal, payment)
                                       if rehearsal else None),
                "allocations": [{"line_no": line.line_no, "source_type": line.source_type,
                    "source_reference_key": line.source_reference_key,
                    "source_document_date": line.source_document_date,
                    "source_outstanding_snapshot": line.source_outstanding_snapshot,
                    "allocation_amount": line.allocation_amount} for line in payment.allocations]}

    def payment_open_items(payment_type: str, party_code: str, clone_session: Session,
                           operational_session: Session) -> tuple[object, list[dict]]:
        snapshot = clone_session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == selected_snapshot))
        if not snapshot:
            raise HTTPException(status_code=404, detail="Configured BizModo clone snapshot is unavailable")
        party_kind = "customer" if payment_type == "customer_receipt" else "supplier"
        source_kind = "sale" if payment_type == "customer_receipt" else "purchase"
        balance_type = "receivable" if payment_type == "customer_receipt" else "payable"
        if operational_masters_present(operational_session, OperationalPartyMaster) and not operational_session.scalar(
                select(OperationalPartyMaster.id).where(
                    OperationalPartyMaster.party_code == party_code,
                    OperationalPartyMaster.party_kind.in_((party_kind, "both")),
                    OperationalPartyMaster.status == "active")):
            raise HTTPException(status_code=422, detail=f"{party_kind.title()} is not active in the operational master")
        party = clone_session.execute(select(ErpParty.id, ErpParty.legal_or_business_name).where(
            ErpParty.snapshot_id == snapshot.id, ErpParty.party_code == party_code,
            ErpParty.party_kind.in_((party_kind, "both")))).first()
        if not party:
            raise HTTPException(status_code=422, detail=f"{party_kind.title()} is not present in the cloned master")
        items = (customer_invoice_open_items(operational_session, party_code)
                 if payment_type == "customer_receipt" else [])
        invoices = clone_session.execute(select(
            ErpTransactionDocument.document_no, ErpTransactionDocument.occurred_at,
            ErpTransactionDocument.total_amount, ErpTransactionDocument.paid_amount,
            ErpTransactionDocument.due_amount).where(
                ErpTransactionDocument.snapshot_id == snapshot.id,
                ErpTransactionDocument.source_kind == source_kind,
                ErpTransactionDocument.party_id == party.id).order_by(
                    ErpTransactionDocument.occurred_at.desc())).all()
        for invoice in invoices:
            outstanding = Decimal(str(invoice.due_amount if invoice.due_amount is not None else
                              (invoice.total_amount or 0) - (invoice.paid_amount or 0))).quantize(Decimal("0.01"))
            if outstanding > 0:
                items.append({"source_type": "invoice", "source_reference_key": invoice.document_no,
                              "source_document_date": invoice.occurred_at.date() if invoice.occurred_at else None,
                              "source_outstanding": outstanding, "source_origin": "bizmodo_clone"})
        openings = operational_session.scalars(select(OperationalOpeningPartyBalance).where(
            OperationalOpeningPartyBalance.party_type == party_kind,
            OperationalOpeningPartyBalance.party_code == party_code,
            OperationalOpeningPartyBalance.balance_type == balance_type)).all()
        for opening in openings:
            items.append({"source_type": "opening_balance", "source_reference_key": f"OB:{opening.id}",
                          "source_document_date": None, "source_outstanding": opening.amount,
                          "source_origin": "opening_control"})
        for item in items:
            claimed = operational_session.scalar(select(func.coalesce(func.sum(OperationalPaymentAllocationClaim.amount), 0)).where(
                OperationalPaymentAllocationClaim.party_code == party_code,
                OperationalPaymentAllocationClaim.source_type == item["source_type"],
                OperationalPaymentAllocationClaim.source_reference_key == item["source_reference_key"],
                OperationalPaymentAllocationClaim.status == "active")) or Decimal("0")
            item["reserved_amount"] = claimed
            item["available_outstanding"] = max(Decimal("0"), item["source_outstanding"] - claimed)
        return party, [item for item in items if item["available_outstanding"] > 0]

    @app.get("/api/v1/selectors/payment-open-items")
    def payment_open_item_selector(payment_type: str = Query(pattern="^(customer_receipt|supplier_payment)$"),
                                   party_code: str = Query(min_length=1, max_length=80),
                                   clone_session: Session = Depends(session_dependency),
                                   operational_session=Depends(operational_session_dependency)):
        _, items = payment_open_items(payment_type, party_code, clone_session, operational_session)
        return {"items": items}

    def prepare_payment(payload: PaymentRequest, clone_session: Session, operational_session: Session, user) -> tuple[str, list[dict]]:
        snapshot = clone_session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == selected_snapshot))
        if not snapshot:
            raise HTTPException(status_code=404, detail="Configured BizModo clone snapshot is unavailable")
        if not location_allowed(user, payload.location_code):
            raise HTTPException(status_code=403, detail="Payment location is outside the user's operational scope")
        if operational_masters_present(operational_session, OperationalLocationMaster):
            location_exists = operational_session.scalar(select(OperationalLocationMaster.id).where(
                OperationalLocationMaster.location_code == payload.location_code,
                OperationalLocationMaster.status == "active"))
        else:
            location_exists = clone_session.scalar(select(ErpLocation.id).where(
                ErpLocation.snapshot_id == snapshot.id, ErpLocation.code == payload.location_code))
        if not location_exists:
            raise HTTPException(status_code=422, detail="Payment location is not active in the operational master")
        active_cash_accounts = operational_session.scalar(select(func.count(OperationalCashAccount.id)).where(
            OperationalCashAccount.status == "active")) or 0
        if active_cash_accounts and not operational_session.scalar(select(OperationalCashAccount.id).where(
                OperationalCashAccount.account_code == payload.cash_bank_account_code,
                OperationalCashAccount.status == "active",
                OperationalCashAccount.location_code.in_((payload.location_code.upper(), "MAIN")))):
            raise HTTPException(status_code=422, detail="Select an approved cash/bank account for this location")
        party, items = payment_open_items(payload.payment_type, payload.party_code, clone_session, operational_session)
        operational_party = (operational_session.scalar(select(OperationalPartyMaster).where(
            OperationalPartyMaster.party_code == payload.party_code))
            if operational_masters_present(operational_session, OperationalPartyMaster) else None)
        sources = {(item["source_type"], item["source_reference_key"]): item for item in items}
        prepared = []
        for allocation in payload.allocations:
            source = sources.get((allocation.source_type, allocation.source_reference_key))
            if not source:
                raise HTTPException(status_code=422, detail=f"Open allocation source {allocation.source_reference_key} is unavailable")
            if allocation.allocation_amount > source["available_outstanding"]:
                raise HTTPException(status_code=422, detail=f"Allocation exceeds available outstanding for {allocation.source_reference_key}")
            prepared.append({"source_type": allocation.source_type,
                             "source_reference_key": allocation.source_reference_key,
                             "source_document_date": source["source_document_date"],
                             "source_outstanding_snapshot": source["source_outstanding"],
                             "allocation_amount": allocation.allocation_amount})
        return (operational_party.legal_or_business_name if operational_party
                else party.legal_or_business_name), prepared

    @app.get("/api/v1/payments")
    def payments(request: Request, operational_session=Depends(operational_session_dependency)):
        user = current_user(request)
        rows = list_payments(operational_session, allowed_locations=user.allowed_locations if user else ())
        return {"items": [payment_payload(row, operational_session) for row in rows], "total": len(rows),
                "posting_enabled": False, "controls": payment_control_counts(operational_session)}

    @app.get("/api/v1/payments/{payment_key}")
    def payment_detail(payment_key: str, request: Request,
                       operational_session=Depends(operational_session_dependency)):
        payment = operational_session.scalar(select(OperationalPayment).where(OperationalPayment.payment_key == payment_key))
        user = current_user(request)
        if not payment or not user or not location_allowed(user, payment.location_code):
            raise HTTPException(status_code=404, detail="Payment not found")
        return payment_payload(payment, operational_session)

    @app.post("/api/v1/payments", status_code=201)
    def new_payment(payload: PaymentRequest, request: Request,
                    clone_session: Session = Depends(session_dependency),
                    operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "payment.create")
        party_name, allocations = prepare_payment(payload, clone_session, operational_session, user)
        try:
            payment = create_payment(operational_session, actor=user.username,
                payment_type=payload.payment_type, party_code=payload.party_code,
                party_name_snapshot=party_name, location_code=payload.location_code,
                payment_date=payload.payment_date, payment_method=payload.payment_method,
                cash_bank_account_code=payload.cash_bank_account_code, reference_no=payload.reference_no,
                amount=payload.amount, notes=payload.notes, lines=allocations)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return payment_payload(payment, operational_session)

    @app.put("/api/v1/payments/{payment_key}")
    def edit_payment(payment_key: str, payload: PaymentRequest, request: Request,
                     expected_revision: int = Query(ge=1),
                     clone_session: Session = Depends(session_dependency),
                     operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "payment.edit")
        payment = operational_session.scalar(select(OperationalPayment).where(
            OperationalPayment.payment_key == payment_key).with_for_update())
        if not payment or not location_allowed(user, payment.location_code):
            raise HTTPException(status_code=404, detail="Payment not found")
        party_name, allocations = prepare_payment(payload, clone_session, operational_session, user)
        try:
            payment = replace_payment(operational_session, payment, expected_revision=expected_revision,
                actor=user.username, payment_type=payload.payment_type, party_code=payload.party_code,
                party_name_snapshot=party_name, location_code=payload.location_code,
                payment_date=payload.payment_date, payment_method=payload.payment_method,
                cash_bank_account_code=payload.cash_bank_account_code, reference_no=payload.reference_no,
                amount=payload.amount, notes=payload.notes, lines=allocations)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return payment_payload(payment, operational_session)

    def payment_action(payment_key: str, action: str, payload: DraftTransitionRequest,
                       request: Request, operational_session: Session):
        permission = {"submit": "payment.submit", "cancel": "payment.cancel", "approve": "payment.approve"}[action]
        user = require_csrf(request, permission)
        payment = operational_session.scalar(select(OperationalPayment).where(
            OperationalPayment.payment_key == payment_key).with_for_update())
        if not payment or not location_allowed(user, payment.location_code):
            raise HTTPException(status_code=404, detail="Payment not found")
        try:
            return payment_payload(transition_payment(operational_session, payment,
                expected_revision=payload.expected_revision, action=action,
                actor=user.username, note=payload.note), operational_session)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/payments/{payment_key}/submit")
    def submit_payment(payment_key: str, payload: DraftTransitionRequest, request: Request,
                       operational_session=Depends(operational_session_dependency)):
        return payment_action(payment_key, "submit", payload, request, operational_session)

    @app.post("/api/v1/payments/{payment_key}/cancel")
    def cancel_payment(payment_key: str, payload: DraftTransitionRequest, request: Request,
                       operational_session=Depends(operational_session_dependency)):
        return payment_action(payment_key, "cancel", payload, request, operational_session)

    @app.post("/api/v1/payments/{payment_key}/approve")
    def approve_payment(payment_key: str, payload: DraftTransitionRequest, request: Request,
                        operational_session=Depends(operational_session_dependency)):
        return payment_action(payment_key, "approve", payload, request, operational_session)

    @app.post("/api/v1/payments/{payment_key}/posting-rehearsal")
    def payment_posting_rehearsal(payment_key: str, request: Request,
                                  operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "payment.rehearse")
        payment = operational_session.scalar(select(OperationalPayment).where(
            OperationalPayment.payment_key == payment_key).with_for_update())
        if not payment or not location_allowed(user, payment.location_code):
            raise HTTPException(status_code=404, detail="Payment not found")
        try:
            return rehearse_payment_posting(operational_session, payment, actor=user.username)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/cash-management")
    def cash_management(request: Request,
                        operational_session=Depends(operational_session_dependency)):
        user = current_user(request)
        payload = cash_management_payload(operational_session)
        if user and "*" not in user.allowed_locations:
            allowed = set(user.allowed_locations)
            payload["accounts"] = [row for row in payload["accounts"] if row["location_code"] in allowed]
            allowed_keys = {row["account_key"] for row in payload["accounts"]}
            payload["statements"] = [row for row in payload["statements"] if row["account_key"] in allowed_keys]
        return payload

    @app.post("/api/v1/cash-management/accounts", status_code=201)
    def request_cash_account(payload: CashAccountRequest, request: Request,
                             operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "cash.account.prepare")
        if not location_allowed(user, payload.location_code):
            raise HTTPException(status_code=403, detail="Cash/bank account location is outside the user's scope")
        try:
            row = create_cash_account(operational_session, actor=user.username, **payload.model_dump())
            return cash_account_payload(row)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/cash-management/accounts/{account_key}/{action}")
    def decide_cash_account_route(account_key: str, action: str, payload: CashDecisionRequest,
                                  request: Request,
                                  operational_session=Depends(operational_session_dependency)):
        if action not in {"approve", "reject"}:
            raise HTTPException(status_code=404, detail="Cash/bank account action not found")
        user = require_csrf(request, "cash.account.approve")
        row = operational_session.scalar(select(OperationalCashAccount).where(
            OperationalCashAccount.account_key == account_key).with_for_update())
        if not row or not location_allowed(user, row.location_code):
            raise HTTPException(status_code=404, detail="Cash/bank account not found")
        try:
            return cash_account_payload(decide_cash_account(operational_session, row,
                action=action, expected_revision=payload.expected_revision,
                actor=user.username, note=payload.note))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/cash-management/statements", status_code=201)
    def import_bank_statement(payload: StatementBatchRequest, request: Request,
                              operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "bank.statement.import")
        account = operational_session.scalar(select(OperationalCashAccount).where(
            OperationalCashAccount.account_key == payload.account_key).with_for_update())
        if not account or not location_allowed(user, account.location_code):
            raise HTTPException(status_code=404, detail="Approved bank account not found")
        try:
            batch = create_statement_batch(operational_session, account=account,
                statement_reference=payload.statement_reference,
                statement_start=payload.statement_start, statement_end=payload.statement_end,
                opening_balance=payload.opening_balance, closing_balance=payload.closing_balance,
                source_file_name=payload.source_file_name, actor=user.username,
                lines=[line.model_dump() for line in payload.lines])
            return statement_payload(operational_session, batch)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def statement_and_line(batch_key: str, line_no: int, operational_session: Session):
        batch = operational_session.scalar(select(OperationalStatementBatch).where(
            OperationalStatementBatch.batch_key == batch_key).with_for_update())
        line = operational_session.scalar(select(OperationalStatementLine).where(
            OperationalStatementLine.batch_id == batch.id,
            OperationalStatementLine.line_no == line_no).with_for_update()) if batch else None
        return batch, line

    @app.post("/api/v1/cash-management/statements/{batch_key}/lines/{line_no}/match")
    def match_bank_statement_line(batch_key: str, line_no: int, payload: StatementMatchRequest,
                                  request: Request,
                                  operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "bank.reconcile.prepare")
        batch, line = statement_and_line(batch_key, line_no, operational_session)
        if not batch or not line or not location_allowed(user, batch.account.location_code):
            raise HTTPException(status_code=404, detail="Statement line not found")
        payment = operational_session.scalar(select(OperationalPayment).where(
            OperationalPayment.payment_key == payload.payment_key).with_for_update())
        if not payment:
            raise HTTPException(status_code=404, detail="Receipt/payment not found")
        try:
            match_statement_line(operational_session, batch, line, payment, actor=user.username)
            return statement_payload(operational_session, batch)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/cash-management/statements/{batch_key}/lines/{line_no}/exception")
    def explain_bank_statement_line(batch_key: str, line_no: int,
                                    payload: StatementExceptionRequest, request: Request,
                                    operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "bank.reconcile.prepare")
        batch, line = statement_and_line(batch_key, line_no, operational_session)
        if not batch or not line or not location_allowed(user, batch.account.location_code):
            raise HTTPException(status_code=404, detail="Statement line not found")
        try:
            explain_statement_line(operational_session, batch, line, category=payload.category,
                                   reason=payload.reason, actor=user.username)
            return statement_payload(operational_session, batch)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/cash-management/statements/{batch_key}/actions/{action}")
    def transition_bank_statement(batch_key: str, action: str,
                                  payload: StatementDecisionRequest, request: Request,
                                  operational_session=Depends(operational_session_dependency)):
        permissions = {"submit": "bank.reconcile.prepare", "approve": "bank.reconcile.approve",
                       "reject": "bank.reconcile.approve"}
        if action not in permissions:
            raise HTTPException(status_code=404, detail="Reconciliation action not found")
        user = require_csrf(request, permissions[action])
        batch = operational_session.scalar(select(OperationalStatementBatch).where(
            OperationalStatementBatch.batch_key == batch_key).with_for_update())
        if not batch or not location_allowed(user, batch.account.location_code):
            raise HTTPException(status_code=404, detail="Statement reconciliation not found")
        try:
            transition_statement_batch(operational_session, batch, action=action,
                expected_revision=payload.expected_revision, actor=user.username, note=payload.note)
            return statement_payload(operational_session, batch)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/cash-management/statements/{batch_key}/rehearsal")
    def rehearse_bank_statement(batch_key: str, request: Request,
                               operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "bank.reconcile.rehearse")
        batch = operational_session.scalar(select(OperationalStatementBatch).where(
            OperationalStatementBatch.batch_key == batch_key).with_for_update())
        if not batch or not location_allowed(user, batch.account.location_code):
            raise HTTPException(status_code=404, detail="Statement reconciliation not found")
        try:
            return rehearse_reconciliation(operational_session, batch, actor=user.username)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/expense-management/workspace")
    def expenses_workspace(request: Request,
                           operational_session=Depends(operational_session_dependency)):
        user = current_user(request)
        payload = expense_workspace_payload(operational_session)
        if user and "*" not in user.allowed_locations:
            allowed = set(user.allowed_locations)
            payload["accounts"] = [row for row in payload["accounts"] if row["location_code"] in allowed]
            payload["claims"] = [row for row in payload["claims"] if row["location_code"] in allowed]
            payload["advances"] = [row for row in payload["advances"] if row["location_code"] in allowed]
        return payload

    @app.post("/api/v1/expense-management/claims", status_code=201)
    def create_expense_claim_route(payload: ExpenseClaimRequest, request: Request,
                                   operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "expense.prepare")
        if not location_allowed(user, payload.location_code):
            raise HTTPException(status_code=403, detail="Expense location is outside the user's scope")
        try:
            row = create_expense_claim(operational_session, actor=user.username, **payload.model_dump())
            return expense_claim_payload(operational_session, row)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/expense-management/claims/{claim_key}/actions/{action}")
    def expense_claim_action(claim_key: str, action: str, payload: ExpenseActionRequest,
                             request: Request,
                             operational_session=Depends(operational_session_dependency)):
        permissions = {"submit": "expense.submit", "cancel": "expense.submit",
                       "approve": "expense.approve", "reject": "expense.approve"}
        if action not in permissions:
            raise HTTPException(status_code=404, detail="Expense action not found")
        user = require_csrf(request, permissions[action])
        row = operational_session.scalar(select(OperationalExpenseClaim).where(
            OperationalExpenseClaim.claim_key == claim_key).with_for_update())
        if not row or not location_allowed(user, row.location_code):
            raise HTTPException(status_code=404, detail="Expense claim not found")
        try:
            transition_expense_claim(operational_session, row, action=action,
                expected_revision=payload.expected_revision, actor=user.username, note=payload.note)
            return expense_claim_payload(operational_session, row)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/expense-management/claims/{claim_key}/rehearsal")
    def expense_claim_rehearsal(claim_key: str, request: Request,
                                operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "expense.rehearse")
        row = operational_session.scalar(select(OperationalExpenseClaim).where(
            OperationalExpenseClaim.claim_key == claim_key).with_for_update())
        if not row or not location_allowed(user, row.location_code):
            raise HTTPException(status_code=404, detail="Expense claim not found")
        try:
            return rehearse_expense(operational_session, row, actor=user.username)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/expense-management/petty-cash", status_code=201)
    def create_petty_cash_route(payload: PettyCashAdvanceRequest, request: Request,
                                operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "petty_cash.prepare")
        if not location_allowed(user, payload.location_code):
            raise HTTPException(status_code=403, detail="Petty-cash location is outside the user's scope")
        try:
            row = create_petty_cash_advance(operational_session, actor=user.username, **payload.model_dump())
            return petty_advance_payload(operational_session, row)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/expense-management/petty-cash/{advance_key}/actions/{action}")
    def petty_cash_action(advance_key: str, action: str, payload: PettyCashActionRequest,
                          request: Request,
                          operational_session=Depends(operational_session_dependency)):
        permissions = {"approve": "petty_cash.approve", "reject": "petty_cash.approve",
                       "cancel": "petty_cash.manage", "issue": "petty_cash.manage",
                       "settle": "petty_cash.manage"}
        if action not in permissions:
            raise HTTPException(status_code=404, detail="Petty-cash action not found")
        user = require_csrf(request, permissions[action])
        row = operational_session.scalar(select(OperationalPettyCashAdvance).where(
            OperationalPettyCashAdvance.advance_key == advance_key).with_for_update())
        if not row or not location_allowed(user, row.location_code):
            raise HTTPException(status_code=404, detail="Petty-cash advance not found")
        try:
            transition_petty_cash_advance(operational_session, row, action=action,
                expected_revision=payload.expected_revision, actor=user.username,
                note=payload.note, spent_amount=payload.spent_amount,
                returned_amount=payload.returned_amount, category_code=payload.category_code,
                receipt_reference=payload.receipt_reference)
            return petty_advance_payload(operational_session, row)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/expense-management/petty-cash/{advance_key}/rehearsal")
    def petty_cash_rehearsal(advance_key: str, request: Request,
                             operational_session=Depends(operational_session_dependency)):
        user = require_any_csrf(request, {"expense.rehearse", "petty_cash.manage"})
        row = operational_session.scalar(select(OperationalPettyCashAdvance).where(
            OperationalPettyCashAdvance.advance_key == advance_key).with_for_update())
        if not row or not location_allowed(user, row.location_code):
            raise HTTPException(status_code=404, detail="Petty-cash advance not found")
        try:
            return rehearse_petty_cash(operational_session, row, actor=user.username)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/fixed-assets/workspace")
    def fixed_assets_workspace(request: Request,
                               operational_session=Depends(operational_session_dependency)):
        user = current_user(request)
        payload = fixed_asset_workspace_payload(operational_session)
        if user and "*" not in user.allowed_locations:
            allowed = set(user.allowed_locations)
            payload["assets"] = [row for row in payload["assets"] if row["location_code"] in allowed]
        return payload

    @app.post("/api/v1/fixed-assets", status_code=201)
    def create_fixed_asset_route(payload: FixedAssetCreateRequest, request: Request,
                                 operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "fixed_asset.prepare")
        if not location_allowed(user, payload.location_code):
            raise HTTPException(status_code=403, detail="Asset location is outside the user's scope")
        try:
            row = create_fixed_asset(operational_session, actor=user.username, **payload.model_dump())
            return fixed_asset_payload(operational_session, row)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/fixed-assets/{asset_key}/actions/{action}")
    def fixed_asset_action(asset_key: str, action: str, payload: FixedAssetActionRequest,
                           request: Request,
                           operational_session=Depends(operational_session_dependency)):
        permissions = {"submit": "fixed_asset.submit", "cancel": "fixed_asset.submit",
                       "approve": "fixed_asset.approve", "reject": "fixed_asset.approve"}
        if action not in permissions:
            raise HTTPException(status_code=404, detail="Fixed-asset action not found")
        user = require_csrf(request, permissions[action])
        row = operational_session.scalar(select(OperationalFixedAsset).where(
            OperationalFixedAsset.asset_key == asset_key).with_for_update())
        if not row or not location_allowed(user, row.location_code):
            raise HTTPException(status_code=404, detail="Fixed asset not found")
        try:
            transition_fixed_asset(operational_session, row, action=action,
                expected_revision=payload.expected_revision, actor=user.username, note=payload.note)
            return fixed_asset_payload(operational_session, row)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/fixed-assets/{asset_key}/disposal/request")
    def fixed_asset_disposal_request(asset_key: str, payload: FixedAssetDisposalRequest,
                                     request: Request,
                                     operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "fixed_asset.disposal.prepare")
        row = operational_session.scalar(select(OperationalFixedAsset).where(
            OperationalFixedAsset.asset_key == asset_key).with_for_update())
        if not row or not location_allowed(user, row.location_code):
            raise HTTPException(status_code=404, detail="Fixed asset not found")
        try:
            request_asset_disposal(operational_session, row, actor=user.username,
                **payload.model_dump())
            return fixed_asset_payload(operational_session, row)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/fixed-assets/{asset_key}/disposal/{action}")
    def fixed_asset_disposal_decision(asset_key: str, action: str,
                                      payload: FixedAssetActionRequest, request: Request,
                                      operational_session=Depends(operational_session_dependency)):
        if action not in {"approve", "reject"}:
            raise HTTPException(status_code=404, detail="Fixed-asset disposal action not found")
        user = require_csrf(request, "fixed_asset.disposal.approve")
        row = operational_session.scalar(select(OperationalFixedAsset).where(
            OperationalFixedAsset.asset_key == asset_key).with_for_update())
        if not row or not location_allowed(user, row.location_code):
            raise HTTPException(status_code=404, detail="Fixed asset not found")
        try:
            decide_asset_disposal(operational_session, row, action=action,
                expected_revision=payload.expected_revision, actor=user.username,
                note=payload.note or "")
            return fixed_asset_payload(operational_session, row)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/fixed-assets/{asset_key}/rehearsal")
    def fixed_asset_rehearsal(asset_key: str, payload: FixedAssetRehearsalRequest,
                              request: Request,
                              operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "fixed_asset.rehearse")
        row = operational_session.scalar(select(OperationalFixedAsset).where(
            OperationalFixedAsset.asset_key == asset_key).with_for_update())
        if not row or not location_allowed(user, row.location_code):
            raise HTTPException(status_code=404, detail="Fixed asset not found")
        try:
            return rehearse_fixed_asset(operational_session, row, actor=user.username,
                **payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/vat-control/workspace")
    def vat_control_workspace(operational_session=Depends(operational_session_dependency)):
        return vat_workspace_payload(operational_session)

    @app.post("/api/v1/vat-control/periods", status_code=201)
    def create_vat_period_route(payload: VatPeriodCreateRequest, request: Request,
                                operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "vat.period.prepare")
        try:
            row = create_vat_period(operational_session, actor=user.username, **payload.model_dump())
            return vat_period_payload(operational_session, row)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/vat-control/periods/{period_key}/actions/{action}")
    def vat_period_action(period_key: str, action: str, payload: VatWorkflowRequest,
                          request: Request,
                          operational_session=Depends(operational_session_dependency)):
        permissions = {"submit": "vat.period.submit", "cancel": "vat.period.submit",
                       "approve": "vat.period.approve", "reject": "vat.period.approve"}
        if action not in permissions:
            raise HTTPException(status_code=404, detail="VAT-period action not found")
        user = require_csrf(request, permissions[action])
        row = operational_session.scalar(select(OperationalVatPeriod).where(
            OperationalVatPeriod.period_key == period_key).with_for_update())
        if not row:
            raise HTTPException(status_code=404, detail="VAT period not found")
        try:
            transition_vat_period(operational_session, row, action=action,
                expected_revision=payload.expected_revision, actor=user.username, note=payload.note)
            return vat_period_payload(operational_session, row)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/vat-control/periods/{period_key}/adjustments", status_code=201)
    def create_vat_adjustment_route(period_key: str, payload: VatAdjustmentCreateRequest,
                                    request: Request,
                                    operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "vat.adjustment.prepare")
        period = operational_session.scalar(select(OperationalVatPeriod).where(
            OperationalVatPeriod.period_key == period_key).with_for_update())
        if not period:
            raise HTTPException(status_code=404, detail="VAT period not found")
        try:
            row = create_vat_adjustment(operational_session, period, actor=user.username,
                                        **payload.model_dump())
            return vat_adjustment_payload(row)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/vat-control/adjustments/{adjustment_key}/{action}")
    def vat_adjustment_action(adjustment_key: str, action: str,
                              payload: VatWorkflowRequest, request: Request,
                              operational_session=Depends(operational_session_dependency)):
        permissions = {"approve": "vat.adjustment.approve", "reject": "vat.adjustment.approve",
                       "cancel": "vat.adjustment.prepare"}
        if action not in permissions:
            raise HTTPException(status_code=404, detail="VAT-adjustment action not found")
        user = require_csrf(request, permissions[action])
        row = operational_session.scalar(select(OperationalVatAdjustment).where(
            OperationalVatAdjustment.adjustment_key == adjustment_key).with_for_update())
        if not row:
            raise HTTPException(status_code=404, detail="VAT adjustment not found")
        try:
            decide_vat_adjustment(operational_session, row, action=action,
                expected_revision=payload.expected_revision, actor=user.username,
                note=payload.note or "")
            return vat_adjustment_payload(row)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/vat-control/periods/{period_key}/rehearsal")
    def vat_return_rehearsal(period_key: str, request: Request,
                             operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "vat.rehearse")
        row = operational_session.scalar(select(OperationalVatPeriod).where(
            OperationalVatPeriod.period_key == period_key).with_for_update())
        if not row:
            raise HTTPException(status_code=404, detail="VAT period not found")
        try:
            return rehearse_vat_return(operational_session, row, actor=user.username)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/period-close/workspace")
    def period_close_workspace(operational_session=Depends(operational_session_dependency)):
        return period_close_workspace_payload(operational_session)

    @app.post("/api/v1/period-close", status_code=201)
    def create_period_close_route(payload: PeriodCloseCreateRequest, request: Request,
                                  operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "close.prepare")
        try:
            row = create_period_close(operational_session, actor=user.username, **payload.model_dump())
            return period_close_payload(operational_session, row)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/period-close/{close_key}/actions/{action}")
    def period_close_action(close_key: str, action: str, payload: PeriodCloseWorkflowRequest,
                            request: Request,
                            operational_session=Depends(operational_session_dependency)):
        permissions = {"submit": "close.submit", "cancel": "close.submit",
                       "approve": "close.approve", "reject": "close.approve"}
        if action not in permissions:
            raise HTTPException(status_code=404, detail="Period-close action not found")
        user = require_csrf(request, permissions[action])
        row = operational_session.scalar(select(OperationalPeriodClose).where(
            OperationalPeriodClose.close_key == close_key).with_for_update())
        if not row:
            raise HTTPException(status_code=404, detail="Period-close package not found")
        try:
            transition_period_close(operational_session, row, action=action,
                expected_revision=payload.expected_revision, actor=user.username,
                note=payload.note or "")
            return period_close_payload(operational_session, row)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/period-close/{close_key}/adjustments", status_code=201)
    def create_close_adjustment_route(close_key: str, payload: CloseAdjustmentCreateRequest,
                                      request: Request,
                                      operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "close.adjustment.prepare")
        row = operational_session.scalar(select(OperationalPeriodClose).where(
            OperationalPeriodClose.close_key == close_key).with_for_update())
        if not row:
            raise HTTPException(status_code=404, detail="Period-close package not found")
        try:
            item = create_close_adjustment(operational_session, row, actor=user.username,
                                           **payload.model_dump())
            return close_adjustment_payload(item)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/period-close/adjustments/{adjustment_key}/{action}")
    def close_adjustment_action(adjustment_key: str, action: str,
                                payload: PeriodCloseWorkflowRequest, request: Request,
                                operational_session=Depends(operational_session_dependency)):
        permissions = {"approve": "close.adjustment.approve", "reject": "close.adjustment.approve",
                       "cancel": "close.adjustment.prepare"}
        if action not in permissions:
            raise HTTPException(status_code=404, detail="Close-adjustment action not found")
        user = require_csrf(request, permissions[action])
        row = operational_session.scalar(select(OperationalCloseAdjustment).where(
            OperationalCloseAdjustment.adjustment_key == adjustment_key).with_for_update())
        if not row:
            raise HTTPException(status_code=404, detail="Close adjustment not found")
        try:
            decide_close_adjustment(operational_session, row, action=action,
                expected_revision=payload.expected_revision, actor=user.username,
                note=payload.note or "")
            return close_adjustment_payload(row)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/period-close/{close_key}/rehearsal")
    def period_close_rehearsal(close_key: str, request: Request,
                               operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "close.rehearse")
        row = operational_session.scalar(select(OperationalPeriodClose).where(
            OperationalPeriodClose.close_key == close_key).with_for_update())
        if not row:
            raise HTTPException(status_code=404, detail="Period-close package not found")
        try:
            return rehearse_period_close(operational_session, row, actor=user.username)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/close-reporting/workspace")
    def close_reporting_workspace(operational_session=Depends(operational_session_dependency)):
        return reporting_workspace_payload(operational_session)

    @app.post("/api/v1/close-reporting/{close_key}/generate", status_code=201)
    def generate_close_reporting_package(close_key: str, request: Request,
                                         operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "financial_report.prepare")
        close = operational_session.scalar(select(OperationalPeriodClose).where(
            OperationalPeriodClose.close_key == close_key).with_for_update())
        if not close:
            raise HTTPException(status_code=404, detail="Approved close package not found")
        try:
            row = generate_report_package(operational_session, close, actor=user.username)
            return report_package_payload(row)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/close-reporting/packages/{package_key}/{action}")
    def close_reporting_action(package_key: str, action: str, payload: PeriodCloseWorkflowRequest,
                               request: Request,
                               operational_session=Depends(operational_session_dependency)):
        permissions = {"submit": "financial_report.submit", "approve": "financial_report.approve",
                       "reject": "financial_report.approve"}
        if action not in permissions:
            raise HTTPException(status_code=404, detail="Financial-report action not found")
        user = require_csrf(request, permissions[action])
        row = operational_session.scalar(select(OperationalFinancialReportPackage).where(
            OperationalFinancialReportPackage.package_key == package_key).with_for_update())
        if not row:
            raise HTTPException(status_code=404, detail="Financial-report package not found")
        try:
            transition_report_package(operational_session, row, action=action,
                expected_revision=payload.expected_revision, note=payload.note or "", actor=user.username)
            return report_package_payload(row)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/close-reporting/packages/{package_key}/export/{format_name}")
    def export_close_reporting_package(package_key: str, format_name: str, request: Request,
                                       operational_session=Depends(operational_session_dependency)):
        user = current_user(request)
        if not user or "financial_report.export" not in user.permissions:
            raise HTTPException(status_code=403, detail="Permission financial_report.export is required")
        row = operational_session.scalar(select(OperationalFinancialReportPackage).where(
            OperationalFinancialReportPackage.package_key == package_key))
        if not row or row.status != "approved":
            raise HTTPException(status_code=409, detail="Exports require an approved financial-report package")
        if format_name == "xlsx":
            content, media = workbook_bytes(row), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        elif format_name == "pdf":
            content, media = pdf_bytes(row), "application/pdf"
        else:
            raise HTTPException(status_code=404, detail="Export format not found")
        return Response(content=content, media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{row.package_no}.{format_name}"'})

    @app.get("/api/v1/audit-compliance/workspace")
    def audit_compliance_workspace(request: Request,
                                   operational_session=Depends(operational_session_dependency)):
        user = current_user(request)
        if not user or "audit_compliance.read" not in user.permissions:
            raise HTTPException(status_code=403, detail="Permission audit_compliance.read is required")
        return audit_compliance_workspace_payload(operational_session)

    @app.post("/api/v1/audit-compliance/reports/{report_key}/generate", status_code=201)
    def generate_audit_compliance_package(report_key: str, request: Request,
                                          operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "audit_compliance.prepare")
        report = operational_session.scalar(select(OperationalFinancialReportPackage).where(
            OperationalFinancialReportPackage.package_key == report_key).with_for_update())
        if not report:
            raise HTTPException(status_code=404, detail="Approved financial report not found")
        try:
            return statutory_package_payload(generate_statutory_package(
                operational_session, report, actor=user.username))
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/audit-compliance/packages/{package_key}/{action}")
    def audit_compliance_action(package_key: str, action: str, payload: PeriodCloseWorkflowRequest,
                                request: Request,
                                operational_session=Depends(operational_session_dependency)):
        permissions = {"submit": "audit_compliance.submit", "approve": "audit_compliance.approve",
                       "reject": "audit_compliance.approve"}
        if action not in permissions:
            raise HTTPException(status_code=404, detail="Statutory-package action not found")
        user = require_csrf(request, permissions[action])
        row = operational_session.scalar(select(OperationalStatutoryEvidencePackage).where(
            OperationalStatutoryEvidencePackage.package_key == package_key).with_for_update())
        if not row:
            raise HTTPException(status_code=404, detail="Statutory evidence package not found")
        try:
            transition_statutory_package(operational_session, row, action=action,
                expected_revision=payload.expected_revision, note=payload.note or "", actor=user.username)
            return statutory_package_payload(row)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/audit-compliance/packages/{package_key}/export/{format_name}")
    def export_audit_compliance_package(package_key: str, format_name: str, request: Request,
                                        operational_session=Depends(operational_session_dependency)):
        user = current_user(request)
        if not user or "audit_compliance.export" not in user.permissions:
            raise HTTPException(status_code=403, detail="Permission audit_compliance.export is required")
        row = operational_session.scalar(select(OperationalStatutoryEvidencePackage).where(
            OperationalStatutoryEvidencePackage.package_key == package_key))
        if not row or row.status != "approved":
            raise HTTPException(status_code=409, detail="Exports require an approved statutory evidence package")
        if format_name == "xlsx":
            content = statutory_workbook_bytes(row)
            media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        elif format_name == "json":
            content, media = statutory_json_bytes(row), "application/json"
        else:
            raise HTTPException(status_code=404, detail="Export format not found")
        return Response(content=content, media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{row.package_no}.{format_name}"'})

    @app.get("/api/v1/cutover-rehearsal/workspace")
    def cutover_rehearsal_workspace(request: Request,
                                    operational_session=Depends(operational_session_dependency)):
        user = current_user(request)
        if not user or "cutover_rehearsal.read" not in user.permissions:
            raise HTTPException(status_code=403, detail="Permission cutover_rehearsal.read is required")
        return cutover_rehearsal_workspace_payload(operational_session)

    @app.post("/api/v1/cutover-rehearsal/generate", status_code=201)
    def generate_cutover_rehearsal_package(request: Request,
                                           operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "cutover_rehearsal.prepare")
        return cutover_rehearsal_payload(generate_cutover_rehearsal(
            operational_session, actor=user.username))

    @app.post("/api/v1/cutover-rehearsal/packages/{package_key}/{action}")
    def cutover_rehearsal_action(package_key: str, action: str, payload: PeriodCloseWorkflowRequest,
                                 request: Request,
                                 operational_session=Depends(operational_session_dependency)):
        permissions = {"submit": "cutover_rehearsal.submit", "approve": "cutover_rehearsal.approve",
                       "reject": "cutover_rehearsal.approve"}
        if action not in permissions:
            raise HTTPException(status_code=404, detail="Cutover-rehearsal action not found")
        user = require_csrf(request, permissions[action])
        row = operational_session.scalar(select(OperationalCutoverRehearsalPackage).where(
            OperationalCutoverRehearsalPackage.package_key == package_key).with_for_update())
        if not row:
            raise HTTPException(status_code=404, detail="Cutover rehearsal not found")
        try:
            transition_cutover_rehearsal(operational_session, row, action=action,
                expected_revision=payload.expected_revision, note=payload.note or "", actor=user.username)
            return cutover_rehearsal_payload(row)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/cutover-rehearsal/packages/{package_key}/export/{format_name}")
    def export_cutover_rehearsal_package(package_key: str, format_name: str, request: Request,
                                         operational_session=Depends(operational_session_dependency)):
        user = current_user(request)
        if not user or "cutover_rehearsal.export" not in user.permissions:
            raise HTTPException(status_code=403, detail="Permission cutover_rehearsal.export is required")
        row = operational_session.scalar(select(OperationalCutoverRehearsalPackage).where(
            OperationalCutoverRehearsalPackage.package_key == package_key))
        if not row or row.status != "approved":
            raise HTTPException(status_code=409, detail="Exports require an approved cutover rehearsal")
        if format_name == "xlsx":
            content = cutover_workbook_bytes(row)
            media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        elif format_name == "json":
            content, media = cutover_json_bytes(row), "application/json"
        else:
            raise HTTPException(status_code=404, detail="Export format not found")
        return Response(content=content, media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{row.package_no}.{format_name}"'})

    def require_integrated_resource(request: Request, operational_session, resource_type: str,
                                    resource_key: str, permission: str):
        user = require_csrf(request, permission)
        if resource_type not in RESOURCE_TYPES:
            raise HTTPException(status_code=404, detail="Posting resource not found")
        resource = get_posting_resource(operational_session, resource_type, resource_key)
        locations = [resource.location_code] if resource else []
        destination = getattr(resource, "destination_location_code", None) if resource else None
        if destination:
            locations.append(destination)
        if not resource or any(not location_allowed(user, location) for location in locations):
            raise HTTPException(status_code=404, detail="Posting resource not found")
        return user, resource

    @app.get("/api/v1/posting/readiness")
    def posting_readiness(request: Request,
                          operational_session=Depends(operational_session_dependency)):
        require_user(request, "clone.read")
        return {
            "posting_enabled": app.state.posting_enabled,
            "production_ready": False,
            "supported_resources": ["sale", "purchase", *sorted(RESOURCE_TYPES)],
            "controls": integrated_posting_counts(operational_session),
            "activation_requirement": "Explicit production approval and ASAS_POSTING_ENABLED=true",
        }

    @app.get("/api/v1/deployment/readiness")
    def deployment_readiness(request: Request):
        require_user(request, "clone.read")
        gates = {
            "production_mode": app.state.production_mode,
            "authentication": app.state.auth_enabled,
            "persistent_sessions": app.state.production_mode,
            "secure_cookies": app.state.secure_cookies,
            "explicit_allowed_hosts": bool(security_settings["allowed_hosts"]),
            "operational_postgresql": operational_url.startswith("postgresql"),
            "hrm_included": True,
            "payroll_excluded": True,
            "posting_dual_control": (not security_settings["posting_requested"]
                                     or (security_settings["posting_confirmed"]
                                         and len(security_settings["posting_approval_reference"]) >= 8)),
        }
        return {
            "production_ready": all(gates.values()),
            "posting_enabled": app.state.posting_enabled,
            "posting_approval_reference_present": bool(app.state.posting_approval_reference),
            "gates": gates,
        }

    @app.get("/api/v1/completion-audit")
    def completion_audit(request: Request):
        require_user(request, "clone.read")
        return completion_audit_payload({route.path for route in request.app.routes})

    @app.post("/api/v1/posting/{resource_type}/{resource_key}")
    def post_integrated_resource(resource_type: str, resource_key: str, payload: PostingExecutionRequest,
                                 request: Request,
                                 operational_session=Depends(operational_session_dependency)):
        if not app.state.posting_enabled:
            raise HTTPException(status_code=503, detail="Permanent posting activation is disabled")
        user, _ = require_integrated_resource(request, operational_session, resource_type, resource_key,
                                              "posting.execute")
        try:
            return execute_integrated_posting(operational_session, resource_type=resource_type,
                                              resource_key=resource_key,
                                              idempotency_key=payload.idempotency_key,
                                              actor=user.username)
        except ValueError as exc:
            operational_session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/integrated-posting-batches/{batch_key}/reverse")
    def reverse_integrated_batch(batch_key: str, payload: ReversalExecutionRequest, request: Request,
                                 operational_session=Depends(operational_session_dependency)):
        if not app.state.posting_enabled:
            raise HTTPException(status_code=503, detail="Permanent posting activation is disabled")
        batch = operational_session.scalar(select(OperationalIntegratedPostingBatch).where(
            OperationalIntegratedPostingBatch.batch_key == batch_key))
        if not batch:
            raise HTTPException(status_code=404, detail="Posting batch not found")
        user, _ = require_integrated_resource(request, operational_session, batch.resource_type,
                                              batch.resource_key, "posting.reverse")
        try:
            return execute_integrated_reversal(operational_session, batch, actor=user.username,
                                               reason=payload.reason)
        except ValueError as exc:
            operational_session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/data-governance/promotion")
    def promotion_governance(snapshot: SourceSnapshot = Depends(snapshot_dependency),
                             clone_session: Session = Depends(session_dependency),
                             operational_session=Depends(operational_session_dependency)):
        cloned_counts = {
            "locations": clone_session.scalar(select(func.count(ErpLocation.id)).where(ErpLocation.snapshot_id == snapshot.id)) or 0,
            "parties": clone_session.scalar(select(func.count(ErpParty.id)).where(ErpParty.snapshot_id == snapshot.id)) or 0,
            "products": clone_session.scalar(select(func.count(ErpProductMaster.id)).where(ErpProductMaster.snapshot_id == snapshot.id)) or 0,
            "product_uoms": clone_session.scalar(select(func.count(ErpProductUom.id)).where(ErpProductUom.snapshot_id == snapshot.id)) or 0,
            "transaction_documents": clone_session.scalar(select(func.count(ErpTransactionDocument.id)).where(ErpTransactionDocument.snapshot_id == snapshot.id)) or 0,
            "inventory_movements": clone_session.scalar(select(func.count(ErpInventoryMovement.id)).where(ErpInventoryMovement.snapshot_id == snapshot.id)) or 0,
            "opening_balance_queue": clone_session.scalar(select(func.count(ErpOpeningBalanceQueue.id)).where(ErpOpeningBalanceQueue.snapshot_id == snapshot.id)) or 0,
        }
        registry = promotion_control_counts(operational_session)
        return {"source_system": snapshot.source_system, "source_snapshot": snapshot.name,
                "clone_remains_immutable": True, "promotion_executed": registry["mapped_records"] > 0,
                "cloned_counts": cloned_counts, "registry": registry,
                "activation_gates": PROMOTION_GATES,
                "lifecycle_policy": {
                    "promoted_master_active": lifecycle_actions("master", "active", referenced=True, source_promoted=True),
                    "erp_draft_transaction": lifecycle_actions("transaction", "draft"),
                    "posted_transaction": lifecycle_actions("transaction", "posted"),
                    "imported_history": lifecycle_actions("transaction", "historical"),
                }}

    @app.get("/api/v1/data-governance/source-verification")
    def source_verification_governance(operational_session=Depends(operational_session_dependency)):
        return {**source_verification_counts(operational_session),
                "verification_scope": "immutable_raw_clone_evidence",
                "posting_enabled": False, "promotion_executed": False}

    @app.get("/api/v1/my-workspace")
    def my_workspace(request: Request,
                     operational_session=Depends(operational_session_dependency)):
        user = current_user(request)
        if app.state.auth_enabled and not user:
            raise HTTPException(status_code=401, detail="Authentication required")
        return approval_workspace_payload(
            operational_session,
            username=user.username if user else None,
            permissions=user.permissions if user else None,
            allowed_locations=user.allowed_locations if user else ("*",),
        )

    @app.get("/api/v1/overview")
    def overview(snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency)):
        count = lambda model: session.scalar(select(func.count(model.id)).where(model.snapshot_id == snapshot.id)) or 0
        organization = session.scalar(select(ErpOrganization).where(
            ErpOrganization.snapshot_id == snapshot.id).order_by(ErpOrganization.id).limit(1))
        document_counts = dict(session.execute(select(
            ErpTransactionDocument.source_kind, func.count(ErpTransactionDocument.id)
        ).where(ErpTransactionDocument.snapshot_id == snapshot.id).group_by(
            ErpTransactionDocument.source_kind)).all())
        party_counts = dict(session.execute(select(
            ErpParty.party_kind, func.count(ErpParty.id)
        ).where(ErpParty.snapshot_id == snapshot.id).group_by(ErpParty.party_kind)).all())
        inventory_quantity = session.scalar(select(func.coalesce(func.sum(
            ErpInventoryMovement.quantity_base), 0)).where(ErpInventoryMovement.snapshot_id == snapshot.id))
        baseline_counts = {
            "customers": party_counts.get("customer", 0) + party_counts.get("both", 0),
            "suppliers": party_counts.get("supplier", 0) + party_counts.get("both", 0),
            "products": count(ErpProductMaster),
            "sales": document_counts.get("sale", 0),
            "purchases": document_counts.get("purchase", 0),
            "sales_returns": document_counts.get("sale_return", 0),
            "purchase_returns": document_counts.get("purchase_return", 0),
            "stock_transfers": document_counts.get("stock_transfer", 0),
            "inventory_movements": count(ErpInventoryMovement),
            "exceptions": count(ErpMigrationExceptionQueue),
        }
        latest_counts = dict(baseline_counts)
        overlay = app.state.delta_overlay
        if overlay:
            for key in ("customers", "suppliers", "products", "sales", "purchases", "sales_returns", "purchase_returns", "stock_transfers"):
                if key in overlay.counts:
                    latest_counts[key] = (baseline_counts.get(key, 0) + overlay.deltas[key]
                                          if key in overlay.overlap_entities else overlay.counts[key])
        return {
            "organization": organization.legal_name if organization else "Asas General Trading LLC",
            "currency": organization.currency_code if organization else "AED",
            "snapshot": snapshot.name,
            "source_system": snapshot.source_system,
            "snapshot_created_at": snapshot.created_at,
            "atomic_source": snapshot.is_atomic,
            "mode": "read_only_preview",
            "posting_enabled": False,
            "hrm_enabled": app.state.operational_sessions is not None,
            "payroll_enabled": False,
            "counts": latest_counts,
            "baseline_counts": baseline_counts,
            "delta_overlay": _overlay_status(overlay),
            "inventory_quantity_base": inventory_quantity,
        }

    def page(limit: int, offset: int, total: int, rows) -> dict:
        return {"items": [dict(row._mapping) if hasattr(row, "_mapping") else dict(row) for row in rows],
                "total": total, "limit": limit, "offset": offset}

    def _overlay_status(overlay):
        if not overlay:
            return {"available": False, "posting_allowed": False}
        return {
            "available": True,
            "captured_at_utc": overlay.captured_at_utc,
            "atomic": overlay.atomic,
            "hashes_verified": overlay.hashes_verified,
            "rows_verified": overlay.rows_verified,
            "counts": overlay.counts,
            "deltas_from_prior_watermark": overlay.deltas,
            "posting_allowed": False,
            "newest_child_details_complete": False,
        }

    def _contains(record: dict, q: str | None) -> bool:
        return not q or q.casefold() in " ".join(str(value or "") for value in record.values()).casefold()

    def _merge_records(baseline_rows, overlay_rows: list[dict], key: str, q: str | None,
                       sort_key: str, limit: int, offset: int, reverse: bool = False):
        baseline = [dict(row._mapping) for row in baseline_rows]
        existing = {str(row.get(key) or "") for row in baseline}
        additions = [row for row in overlay_rows if str(row.get(key) or "") not in existing]
        merged = [row for row in baseline + additions if _contains(row, q)]
        merged.sort(key=lambda row: str(row.get(sort_key) or ""), reverse=reverse)
        return page(limit, offset, len(merged), merged[offset:offset + limit])

    @app.get("/api/v1/products")
    def products(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                 q: str | None = Query(None, max_length=120),
                 snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency),
                 operational_session=Depends(optional_operational_session_dependency)):
        if operational_session is not None and operational_session.scalar(select(func.count(OperationalProductMaster.id))):
            filters = []
            if q:
                pattern = f"%{q.strip()}%"
                filters.append(or_(OperationalProductMaster.sku.ilike(pattern), OperationalProductMaster.name.ilike(pattern)))
            total = operational_session.scalar(select(func.count(OperationalProductMaster.id)).where(*filters)) or 0
            rows = operational_session.execute(select(
                OperationalProductMaster.id, OperationalProductMaster.sku, OperationalProductMaster.name,
                OperationalProductMaster.category_name, OperationalProductMaster.brand_name,
                OperationalProductMaster.purchase_price.label("purchase_price_evidence"),
                OperationalProductMaster.selling_price.label("selling_price_evidence"),
                OperationalProductMaster.tax_rate, OperationalProductMaster.status.label("master_status"),
                OperationalProductMaster.revision,
            ).where(*filters).order_by(OperationalProductMaster.sku).offset(offset).limit(limit)).all()
            return page(limit, offset, total, rows)
        filters = [ErpProductMaster.snapshot_id == snapshot.id]
        rows = session.execute(select(
            ErpProductMaster.id, ErpProductMaster.sku, ErpProductMaster.name,
            ErpProductMaster.category_name, ErpProductMaster.brand_name,
            ErpProductMaster.purchase_price_evidence, ErpProductMaster.selling_price_evidence,
            ErpProductMaster.master_status,
        ).where(*filters)).all()
        overlay = app.state.delta_overlay
        return _merge_records(rows, overlay.product_records() if overlay else [], "sku", q, "sku", limit, offset)

    def operational_product_payload(record: OperationalProductMaster) -> dict:
        return {"sku": record.sku, "name": record.name, "category_name": record.category_name,
                "brand_name": record.brand_name, "purchase_price_evidence": record.purchase_price,
                "selling_price_evidence": record.selling_price, "tax_rate": record.tax_rate,
                "master_status": record.status, "revision": record.revision,
                "source_promoted": record.source_promoted}

    @app.patch("/api/v1/master-data/products/{sku}")
    def update_product_master(sku: str, payload: ProductMasterUpdateRequest, request: Request,
                              operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "migration.review")
        record = operational_session.scalar(select(OperationalProductMaster).where(
            OperationalProductMaster.sku == sku).with_for_update())
        if not record:
            raise HTTPException(status_code=404, detail="Operational product not found")
        if record.revision != payload.expected_revision:
            raise HTTPException(status_code=409, detail=f"Product revision conflict; current revision is {record.revision}")
        for field in ("name", "category_name", "brand_name", "purchase_price", "selling_price", "tax_rate"):
            setattr(record, field, getattr(payload, field))
        record.revision += 1; record.updated_by = user.username; record.updated_at = datetime.now().astimezone()
        operational_session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="master.product.edited",
            actor=user.username, resource_key=record.product_key, detail=f"SKU {record.sku}; revision {record.revision}"))
        operational_session.commit()
        return operational_product_payload(record)

    @app.post("/api/v1/master-data/products/{sku}/{action}")
    def product_master_status(sku: str, action: str, payload: MasterStatusRequest, request: Request,
                              operational_session=Depends(operational_session_dependency)):
        if action not in {"deactivate", "reactivate"}:
            raise HTTPException(status_code=404, detail="Unsupported master action")
        user = require_csrf(request, "migration.review")
        record = operational_session.scalar(select(OperationalProductMaster).where(
            OperationalProductMaster.sku == sku).with_for_update())
        if not record: raise HTTPException(status_code=404, detail="Operational product not found")
        if record.revision != payload.expected_revision:
            raise HTTPException(status_code=409, detail=f"Product revision conflict; current revision is {record.revision}")
        target = "inactive" if action == "deactivate" else "active"
        if record.status == target: raise HTTPException(status_code=409, detail=f"Product is already {target}")
        record.status = target; record.revision += 1; record.updated_by = user.username; record.updated_at = datetime.now().astimezone()
        operational_session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"master.product.{action}d",
            actor=user.username, resource_key=record.product_key, detail=payload.note or f"SKU {record.sku}"))
        operational_session.commit()
        return operational_product_payload(record)

    def parties(kind: str, limit: int, offset: int, q: str | None, snapshot: SourceSnapshot,
                session: Session, operational_session):
        filters = [OperationalPartyMaster.party_kind.in_((kind, "both"))]
        if q:
            pattern = f"%{q.strip()}%"
            filters.append(or_(OperationalPartyMaster.party_code.ilike(pattern), OperationalPartyMaster.legal_or_business_name.ilike(pattern)))
        if operational_session is not None and operational_session.scalar(select(func.count(OperationalPartyMaster.id))):
            total = operational_session.scalar(select(func.count(OperationalPartyMaster.id)).where(*filters)) or 0
            rows = operational_session.execute(select(
                OperationalPartyMaster.id, OperationalPartyMaster.party_code,
                OperationalPartyMaster.legal_or_business_name, OperationalPartyMaster.contact_name,
                OperationalPartyMaster.email, OperationalPartyMaster.mobile,
                OperationalPartyMaster.address, OperationalPartyMaster.tax_number,
                OperationalPartyMaster.party_kind, OperationalPartyMaster.status.label("master_status"),
                OperationalPartyMaster.revision,
            ).where(*filters).order_by(OperationalPartyMaster.legal_or_business_name).offset(offset).limit(limit)).all()
            return page(limit, offset, total, rows)
        kinds = (kind, "both")
        filters = [ErpParty.snapshot_id == snapshot.id, ErpParty.party_kind.in_(kinds)]
        rows = session.execute(select(
            ErpParty.id, ErpParty.party_code, ErpParty.legal_or_business_name,
            ErpParty.contact_name, ErpParty.party_kind, ErpParty.master_status,
        ).where(*filters)).all()
        overlay = app.state.delta_overlay
        overlay_rows = overlay.party_records(kind) if overlay else []
        return _merge_records(rows, overlay_rows, "party_code", q, "legal_or_business_name", limit, offset)

    @app.get("/api/v1/customers")
    def customers(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                  q: str | None = Query(None, max_length=120),
                  snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency),
                  operational_session=Depends(optional_operational_session_dependency)):
        return parties("customer", limit, offset, q, snapshot, session, operational_session)

    @app.get("/api/v1/suppliers")
    def suppliers(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                  q: str | None = Query(None, max_length=120),
                  snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency),
                  operational_session=Depends(optional_operational_session_dependency)):
        return parties("supplier", limit, offset, q, snapshot, session, operational_session)

    def operational_party_payload(record: OperationalPartyMaster) -> dict:
        return {"party_code": record.party_code, "party_kind": record.party_kind,
                "legal_or_business_name": record.legal_or_business_name, "contact_name": record.contact_name,
                "email": record.email, "mobile": record.mobile, "address": record.address,
                "tax_number": record.tax_number, "master_status": record.status,
                "revision": record.revision, "source_promoted": record.source_promoted}

    @app.patch("/api/v1/master-data/parties/{party_code}")
    def update_party_master(party_code: str, payload: PartyMasterUpdateRequest, request: Request,
                            operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "migration.review")
        record = operational_session.scalar(select(OperationalPartyMaster).where(
            OperationalPartyMaster.party_code == party_code).with_for_update())
        if not record: raise HTTPException(status_code=404, detail="Operational party not found")
        if record.revision != payload.expected_revision:
            raise HTTPException(status_code=409, detail=f"Party revision conflict; current revision is {record.revision}")
        for field in ("legal_or_business_name", "contact_name", "email", "mobile", "address", "tax_number"):
            setattr(record, field, getattr(payload, field))
        record.revision += 1; record.updated_by = user.username; record.updated_at = datetime.now().astimezone()
        operational_session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="master.party.edited",
            actor=user.username, resource_key=record.party_key, detail=f"Party {record.party_code}; revision {record.revision}"))
        operational_session.commit()
        return operational_party_payload(record)

    @app.post("/api/v1/master-data/parties/{party_code}/{action}")
    def party_master_status(party_code: str, action: str, payload: MasterStatusRequest, request: Request,
                            operational_session=Depends(operational_session_dependency)):
        if action not in {"deactivate", "reactivate"}: raise HTTPException(status_code=404, detail="Unsupported master action")
        user = require_csrf(request, "migration.review")
        record = operational_session.scalar(select(OperationalPartyMaster).where(
            OperationalPartyMaster.party_code == party_code).with_for_update())
        if not record: raise HTTPException(status_code=404, detail="Operational party not found")
        if record.revision != payload.expected_revision:
            raise HTTPException(status_code=409, detail=f"Party revision conflict; current revision is {record.revision}")
        target = "inactive" if action == "deactivate" else "active"
        if record.status == target: raise HTTPException(status_code=409, detail=f"Party is already {target}")
        record.status = target; record.revision += 1; record.updated_by = user.username; record.updated_at = datetime.now().astimezone()
        operational_session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type=f"master.party.{action}d",
            actor=user.username, resource_key=record.party_key, detail=payload.note or f"Party {record.party_code}"))
        operational_session.commit()
        return operational_party_payload(record)

    def documents(kinds: tuple[str, ...], limit: int, offset: int, q: str | None,
                  snapshot: SourceSnapshot, session: Session):
        filters = [ErpTransactionDocument.snapshot_id == snapshot.id,
                   ErpTransactionDocument.source_kind.in_(kinds)]
        rows = session.execute(select(
            ErpTransactionDocument.id, ErpTransactionDocument.source_kind,
            ErpTransactionDocument.document_no, ErpTransactionDocument.occurred_at,
            ErpParty.legal_or_business_name.label("party_name"), ErpLocation.code.label("location"),
            ErpTransactionDocument.total_amount, ErpTransactionDocument.paid_amount,
            ErpTransactionDocument.due_amount, ErpTransactionDocument.source_status,
            ErpTransactionDocument.migration_status,
        ).outerjoin(ErpParty, ErpParty.id == ErpTransactionDocument.party_id).outerjoin(
            ErpLocation, ErpLocation.id == ErpTransactionDocument.location_id).where(
            *filters)).all()
        overlay = app.state.delta_overlay
        overlay_rows = []
        if overlay and "sale" in kinds:
            overlay_rows.extend(overlay.sale_records())
        if overlay and "purchase" in kinds:
            overlay_rows.extend(overlay.purchase_records())
        if overlay and "sale_return" in kinds:
            overlay_rows.extend(overlay.sale_return_records())
        if overlay and "purchase_return" in kinds:
            overlay_rows.extend(overlay.purchase_return_records())
        return _merge_records(rows, overlay_rows, "document_no", q, "occurred_at", limit, offset, reverse=True)

    def source_review_evidence(entity_type: str, source_record_key: str,
                               snapshot: SourceSnapshot, session: Session) -> tuple[dict, str]:
        baseline = baseline_review_evidence(session, snapshot, entity_type, source_record_key)
        if baseline:
            return baseline
        overlay = app.state.delta_overlay
        overlay_methods = {
            "sale": "sale_records", "purchase": "purchase_records",
            "sale_return": "sale_return_records", "purchase_return": "purchase_return_records",
        }
        if overlay:
            method = getattr(overlay, overlay_methods[entity_type])
            for candidate in method():
                if str(candidate.get("document_no")) == source_record_key:
                    return dict(candidate), str(candidate.get("migration_status") or "provisional_overlay")
        raise HTTPException(status_code=404, detail="Captured source record not found")

    @app.get("/api/v1/data-reviews")
    def data_reviews(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                     status: str | None = Query(None, max_length=30),
                     operational_session=Depends(operational_session_dependency)):
        filters = []
        if status == "open":
            filters.append(OperationalDataReview.status.in_(("in_review", "correction_required", "corrected")))
        elif status:
            filters.append(OperationalDataReview.status == status)
        total = operational_session.scalar(select(func.count(OperationalDataReview.id)).where(*filters)) or 0
        rows = operational_session.scalars(select(OperationalDataReview).where(*filters).order_by(
            OperationalDataReview.created_at.desc()).offset(offset).limit(limit)).all()
        return {"items": [review_payload(row, posting_enabled=app.state.posting_enabled) for row in rows],
                "total": total, "limit": limit, "offset": offset,
                "controls": review_control_counts(operational_session),
                "posting_enabled": app.state.posting_enabled}

    @app.get("/api/v1/data-review-suggestions")
    def data_review_suggestions(limit: int = Query(20, ge=1, le=100),
                                snapshot: SourceSnapshot = Depends(snapshot_dependency),
                                session: Session = Depends(session_dependency),
                                operational_session=Depends(operational_session_dependency)):
        reviewed = set(operational_session.execute(select(
            OperationalDataReview.entity_type, OperationalDataReview.source_record_key)).all())
        line_totals = select(
            ErpTransactionLine.document_id.label("document_id"),
            func.count(ErpTransactionLine.id).label("line_count"),
            func.sum(ErpTransactionLine.subtotal).label("line_subtotal"),
        ).group_by(ErpTransactionLine.document_id).subquery()
        rows = session.execute(select(
            ErpTransactionDocument,
            ErpParty.legal_or_business_name.label("party_name"),
            ErpLocation.code.label("location"),
            line_totals.c.line_count,
            line_totals.c.line_subtotal,
        ).outerjoin(ErpParty, ErpParty.id == ErpTransactionDocument.party_id).outerjoin(
            ErpLocation, ErpLocation.id == ErpTransactionDocument.location_id).outerjoin(
            line_totals, line_totals.c.document_id == ErpTransactionDocument.id).where(
            ErpTransactionDocument.snapshot_id == snapshot.id,
            ErpTransactionDocument.source_kind.in_(("sale", "purchase")),
        )).all()
        totals: dict[str, list[Decimal]] = {"sale": [], "purchase": []}
        for document, *_ in rows:
            if document.total_amount is not None and document.total_amount >= 0:
                totals[document.source_kind].append(Decimal(document.total_amount))
        thresholds = {}
        for kind, values in totals.items():
            values.sort()
            thresholds[kind] = values[min(len(values) - 1, int(len(values) * .99))] if values else None
        suggestions = []
        for document, party_name, location, line_count, line_subtotal in rows:
            if (document.source_kind, document.document_no) in reviewed:
                continue
            finding = transaction_review_findings(
                total_amount=document.total_amount, paid_amount=document.paid_amount,
                due_amount=document.due_amount, source_status=document.source_status,
                party_present=bool(party_name), location_present=bool(location),
                line_count=int(line_count or 0), line_subtotal=line_subtotal,
                high_value_threshold=thresholds[document.source_kind],
            )
            if finding:
                suggestions.append({
                    **finding, "entity_type": document.source_kind,
                    "document_no": document.document_no, "occurred_at": document.occurred_at,
                    "party_name": party_name, "location": location,
                    "total_amount": document.total_amount,
                    "source_status": document.source_status,
                })
        suggestions.sort(key=lambda item: (-item["score"], -abs(Decimal(item["total_amount"] or 0)),
                                           item["document_no"]))
        severity_counts = {severity: sum(1 for item in suggestions if item["severity"] == severity)
                           for severity in ("critical", "high", "medium")}
        assessed = sum(1 for document, *_ in rows
                       if (document.source_kind, document.document_no) not in reviewed)
        return {"items": suggestions[:limit], "total": len(suggestions),
                "assessed": assessed, "severity_counts": severity_counts,
                "method": "Conservative transaction consistency and robust high-value checks"}

    @app.post("/api/v1/data-reviews")
    def create_data_review(payload: DataReviewStartRequest, request: Request,
                           snapshot: SourceSnapshot = Depends(snapshot_dependency),
                           session: Session = Depends(session_dependency),
                           operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "migration.review")
        original, source_status = source_review_evidence(
            payload.entity_type, payload.source_record_key, snapshot, session)
        record = start_review(operational_session, entity_type=payload.entity_type,
                              source_record_key=payload.source_record_key, source_status=source_status,
                              original_payload=original, actor=user.username)
        enrich_review_source(
            operational_session, record, source_payload=original, actor=user.username,
            note="Complete item details recovered from the preserved baseline; review this revision again.",
        )
        operational_session.commit()
        return review_payload(record, posting_enabled=app.state.posting_enabled)

    @app.post("/api/v1/data-reviews/{review_key}/{action}")
    def act_on_data_review(review_key: str, action: str, payload: DataReviewActionRequest,
                           request: Request, operational_session=Depends(operational_session_dependency)):
        if action not in {"verify", "flag-incorrect", "correct", "reject", "promote"}:
            raise HTTPException(status_code=404, detail="Unsupported review action")
        user = require_csrf(request, "migration.review")
        record = operational_session.scalar(select(OperationalDataReview).where(
            OperationalDataReview.review_key == review_key).with_for_update())
        if not record:
            raise HTTPException(status_code=404, detail="Data review not found")
        try:
            transition_review(operational_session, record, action=action,
                              expected_revision=payload.expected_revision, actor=user.username,
                              rationale=payload.rationale, corrected_payload=payload.corrected_payload,
                              posting_enabled=app.state.posting_enabled)
            operational_session.commit()
        except ValueError as exc:
            operational_session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return review_payload(record, posting_enabled=app.state.posting_enabled)

    @app.get("/api/v1/sales")
    def sales(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
              q: str | None = Query(None, max_length=120),
              snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency)):
        return documents(("sale",), limit, offset, q, snapshot, session)

    @app.get("/api/v1/purchases")
    def purchases(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                  q: str | None = Query(None, max_length=120),
                  snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency)):
        return documents(("purchase",), limit, offset, q, snapshot, session)

    @app.get("/api/v1/inventory")
    def inventory(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                  q: str | None = Query(None, max_length=120),
                  snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency)):
        filters = [ErpInventoryMovement.snapshot_id == snapshot.id]
        if q:
            pattern = f"%{q.strip()}%"
            filters.append(or_(ErpProductMaster.sku.ilike(pattern), ErpProductMaster.name.ilike(pattern)))
        grouped = select(
            ErpProductMaster.sku, ErpProductMaster.name,
            ErpLocation.code.label("location"),
            func.sum(ErpInventoryMovement.quantity_base).label("quantity_base"),
            func.max(ErpInventoryMovement.canonical_uom).label("uom"),
            func.count(ErpInventoryMovement.id).label("movement_count"),
        ).join(ErpProductMaster, ErpProductMaster.id == ErpInventoryMovement.product_id).outerjoin(
            ErpLocation, ErpLocation.id == ErpInventoryMovement.location_id).where(*filters).group_by(
            ErpProductMaster.sku, ErpProductMaster.name, ErpLocation.code)
        total = session.scalar(select(func.count()).select_from(grouped.subquery())) or 0
        rows = session.execute(grouped.order_by(ErpProductMaster.sku, ErpLocation.code).offset(offset).limit(limit)).all()
        return page(limit, offset, total, rows)

    def require_finance_report_scope(request: Request, snapshot: SourceSnapshot, session: Session,
                                     permissions: frozenset[str] | set[str] = frozenset({"financial_report.read"})):
        user = current_user(request)
        if not user or set(permissions).isdisjoint(user.permissions):
            raise HTTPException(status_code=403, detail="A permitted finance workspace role is required")
        location_codes = {row[0].upper() for row in session.execute(select(ErpLocation.code).where(
            ErpLocation.snapshot_id == snapshot.id)).all()}
        allowed = set(user.allowed_locations)
        if "*" not in allowed and not location_codes.issubset(allowed):
            raise HTTPException(status_code=403, detail="Company-wide location scope is required because migrated opening AR/AP is not location-distributed")
        return user

    @app.get("/api/v1/accounting")
    def accounting(request: Request, snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency),
                   operational_session=Depends(operational_session_dependency)):
        require_finance_report_scope(request, snapshot, session,
                                     NAVIGATION_PERMISSION_RULES["accounting"] | {"financial_report.read"})
        openings = session.execute(select(
            ErpOpeningBalanceQueue.balance_kind,
            func.count(ErpOpeningBalanceQueue.id).label("rows"),
            func.coalesce(func.sum(ErpOpeningBalanceQueue.amount), 0).label("amount"),
            func.coalesce(func.sum(ErpOpeningBalanceQueue.quantity), 0).label("quantity"),
        ).where(ErpOpeningBalanceQueue.snapshot_id == snapshot.id).group_by(
            ErpOpeningBalanceQueue.balance_kind).order_by(ErpOpeningBalanceQueue.balance_kind)).all()
        accounts = session.scalar(select(func.count(ErpGlAccount.id)).where(ErpGlAccount.snapshot_id == snapshot.id)) or 0
        staged = operational_session.execute(select(
            OperationalOpeningPartyBalance.balance_type,
            func.count(OperationalOpeningPartyBalance.id).label("rows"),
            func.coalesce(func.sum(OperationalOpeningPartyBalance.amount), 0).label("amount"),
        ).group_by(OperationalOpeningPartyBalance.balance_type).order_by(
            OperationalOpeningPartyBalance.balance_type)).all()
        finance_exceptions = operational_session.scalar(select(
            func.count(OperationalFinancialMigrationException.id)).where(
            OperationalFinancialMigrationException.status == "open")) or 0
        summary = build_accounting_summary(session, operational_session, snapshot_id=snapshot.id)
        return {"opening_controls": [dict(row._mapping) for row in openings], "gl_accounts": accounts,
                "staged_opening_controls": [dict(row._mapping) for row in staged],
                "open_financial_exceptions": finance_exceptions,
                "accounting_summary": summary, "posting_enabled": False, "currency": "AED"}

    @app.get("/api/v1/reports/ageing")
    def ageing_report(request: Request, ledger_kind: str = Query(pattern="^(receivable|payable)$"),
                      as_of: date | None = Query(None), q: str = Query("", max_length=120),
                      limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                      snapshot: SourceSnapshot = Depends(snapshot_dependency),
                      session: Session = Depends(session_dependency),
                      operational_session=Depends(operational_session_dependency)):
        require_finance_report_scope(request, snapshot, session)
        return build_ageing_report(session, operational_session, snapshot_id=snapshot.id,
            ledger_kind=ledger_kind, as_of=as_of or date.today(), query=q, limit=limit, offset=offset)

    @app.get("/api/v1/reports/customer-statement")
    def customer_statement(request: Request, party_code: str = Query(min_length=1, max_length=80),
                           as_of: date | None = Query(None),
                           snapshot: SourceSnapshot = Depends(snapshot_dependency),
                           session: Session = Depends(session_dependency),
                           operational_session=Depends(operational_session_dependency)):
        require_finance_report_scope(request, snapshot, session)
        party = session.scalar(select(ErpParty).where(
            ErpParty.snapshot_id == snapshot.id,
            ErpParty.party_code == party_code,
            ErpParty.party_kind.in_(("customer", "both"))))
        if not party:
            raise HTTPException(status_code=404, detail="Customer not found")
        return build_customer_statement(operational_session, party_code=party.party_code,
                                        party_name=party.legal_or_business_name,
                                        as_of=as_of or date.today())

    def credit_customer(snapshot: SourceSnapshot, session: Session, party_code: str):
        party = session.scalar(select(ErpParty).where(
            ErpParty.snapshot_id == snapshot.id,
            ErpParty.party_code == party_code,
            ErpParty.party_kind.in_(("customer", "both"))))
        if not party:
            raise HTTPException(status_code=404, detail="Customer not found")
        return party

    @app.get("/api/v1/credit-control")
    def credit_control_workspace(request: Request, as_of: date | None = Query(None),
                                 q: str = Query("", max_length=120),
                                 snapshot: SourceSnapshot = Depends(snapshot_dependency),
                                 session: Session = Depends(session_dependency),
                                 operational_session=Depends(operational_session_dependency)):
        require_finance_report_scope(request, snapshot, session,
                                     NAVIGATION_PERMISSION_RULES["credit-control"])
        filters = [ErpParty.snapshot_id == snapshot.id,
                   ErpParty.party_kind.in_(("customer", "both"))]
        if q.strip():
            pattern = f"%{q.strip()}%"
            filters.append(or_(ErpParty.party_code.ilike(pattern),
                               ErpParty.legal_or_business_name.ilike(pattern)))
        parties = [{"party_code": row.party_code, "party_name": row.legal_or_business_name}
                   for row in session.scalars(select(ErpParty).where(*filters).order_by(
                       ErpParty.legal_or_business_name))]
        return credit_workspace_payload(operational_session, parties, as_of=as_of or date.today())

    @app.post("/api/v1/credit-control/limit-requests", status_code=201)
    def new_credit_limit_request(payload: CreditLimitRequestCreate, request: Request,
                                 snapshot: SourceSnapshot = Depends(snapshot_dependency),
                                 session: Session = Depends(session_dependency),
                                 operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "credit.limit.prepare")
        party = credit_customer(snapshot, session, payload.party_code)
        try:
            row = create_credit_limit_request(operational_session,
                party_code=party.party_code, party_name=party.legal_or_business_name,
                proposed_limit=payload.proposed_limit,
                proposed_terms_days=payload.proposed_terms_days,
                reason=payload.reason, actor=user.username)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return credit_request_payload(row)

    @app.post("/api/v1/credit-control/limit-requests/{request_key}/{action}")
    def credit_limit_action(request_key: str, action: str, payload: CreditWorkflowRequest,
                            request: Request,
                            operational_session=Depends(operational_session_dependency)):
        if action not in {"approve", "reject", "cancel"}:
            raise HTTPException(status_code=404, detail="Credit workflow action not found")
        permission = "credit.limit.approve" if action in {"approve", "reject"} else "credit.limit.prepare"
        user = require_csrf(request, permission)
        row = operational_session.scalar(select(OperationalCreditLimitRequest).where(
            OperationalCreditLimitRequest.request_key == request_key).with_for_update())
        if not row:
            raise HTTPException(status_code=404, detail="Credit-limit request not found")
        try:
            row = transition_credit_limit_request(operational_session, row,
                expected_revision=payload.expected_revision, action=action,
                actor=user.username, note=payload.note)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return credit_request_payload(row)

    @app.post("/api/v1/credit-control/profiles/{party_code}/{action}")
    def credit_hold_action(party_code: str, action: str, payload: CreditWorkflowRequest,
                           request: Request,
                           operational_session=Depends(operational_session_dependency)):
        if action not in {"hold", "release"}:
            raise HTTPException(status_code=404, detail="Credit action not found")
        user = require_csrf(request, "credit.hold.release")
        profile = operational_session.scalar(select(OperationalCustomerCreditProfile).where(
            OperationalCustomerCreditProfile.party_code == party_code).with_for_update())
        if not profile:
            raise HTTPException(status_code=404, detail="Approved customer credit profile not found")
        try:
            profile = set_credit_hold(operational_session, profile,
                expected_revision=payload.expected_revision, action=action,
                reason=payload.note, actor=user.username)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"party_code": profile.party_code, "status": profile.status,
                "revision": profile.revision, "hold_reason": profile.hold_reason,
                "posting_enabled": False}

    @app.post("/api/v1/credit-control/overrides", status_code=201)
    def new_credit_override(payload: CreditOverrideRequestCreate, request: Request,
                            operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "credit.override.prepare")
        quotation = operational_session.scalar(select(OperationalSalesQuotation).where(
            OperationalSalesQuotation.quotation_key == payload.quotation_key).with_for_update())
        if not quotation or not location_allowed(user, quotation.location_code):
            raise HTTPException(status_code=404, detail="Sales quotation not found")
        try:
            row = create_credit_override_request(operational_session, quotation,
                valid_until=payload.valid_until, reason=payload.reason,
                actor=user.username, as_of=date.today())
        except ValueError as exc:
            operational_session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return credit_override_payload(row)

    @app.post("/api/v1/credit-control/overrides/{request_key}/{action}")
    def credit_override_action(request_key: str, action: str, payload: CreditWorkflowRequest,
                               request: Request,
                               operational_session=Depends(operational_session_dependency)):
        if action not in {"approve", "reject", "cancel"}:
            raise HTTPException(status_code=404, detail="Credit override action not found")
        permission = "credit.override.approve" if action in {"approve", "reject"} else "credit.override.prepare"
        user = require_csrf(request, permission)
        row = operational_session.scalar(select(OperationalCreditOverrideRequest).where(
            OperationalCreditOverrideRequest.request_key == request_key).with_for_update())
        if not row:
            raise HTTPException(status_code=404, detail="Credit override request not found")
        try:
            row = transition_credit_override_request(operational_session, row,
                expected_revision=payload.expected_revision, action=action,
                actor=user.username, note=payload.note)
        except PermissionError as exc:
            operational_session.rollback()
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            operational_session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return credit_override_payload(row)

    @app.post("/api/v1/credit-control/dunning", status_code=201)
    def new_dunning_request(payload: DunningRequestCreate, request: Request,
                            snapshot: SourceSnapshot = Depends(snapshot_dependency),
                            session: Session = Depends(session_dependency),
                            operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "collection.escalation.prepare")
        party = credit_customer(snapshot, session, payload.party_code)
        try:
            row = create_dunning_request(operational_session,
                party_code=party.party_code, party_name=party.legal_or_business_name,
                stage=payload.stage, reason=payload.reason,
                actor=user.username, as_of=date.today())
        except ValueError as exc:
            operational_session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return dunning_request_payload(row)

    @app.post("/api/v1/credit-control/dunning/{request_key}/{action}")
    def dunning_action(request_key: str, action: str, payload: CreditWorkflowRequest,
                       request: Request,
                       operational_session=Depends(operational_session_dependency)):
        if action not in {"approve", "reject", "cancel", "complete"}:
            raise HTTPException(status_code=404, detail="Dunning action not found")
        permission = ("collection.escalation.approve" if action in {"approve", "reject"}
                      else "collection.escalation.prepare")
        user = require_csrf(request, permission)
        row = operational_session.scalar(select(OperationalDunningRequest).where(
            OperationalDunningRequest.request_key == request_key).with_for_update())
        if not row:
            raise HTTPException(status_code=404, detail="Dunning request not found")
        try:
            row = transition_dunning_request(operational_session, row,
                expected_revision=payload.expected_revision, action=action,
                actor=user.username, note=payload.note)
        except PermissionError as exc:
            operational_session.rollback()
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            operational_session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return dunning_request_payload(row)

    @app.post("/api/v1/credit-control/collections", status_code=201)
    def new_collection_action(payload: CollectionActionCreate, request: Request,
                              snapshot: SourceSnapshot = Depends(snapshot_dependency),
                              session: Session = Depends(session_dependency),
                              operational_session=Depends(operational_session_dependency)):
        user = require_csrf(request, "collection.manage")
        party = credit_customer(snapshot, session, payload.party_code)
        if payload.invoice_no and not operational_session.scalar(select(OperationalCustomerInvoice.id).where(
                OperationalCustomerInvoice.customer_code == payload.party_code,
                OperationalCustomerInvoice.invoice_no == payload.invoice_no)):
            raise HTTPException(status_code=422, detail="Target-ERP customer invoice not found for this customer")
        try:
            row = create_collection_action(operational_session,
                party_code=party.party_code, party_name=party.legal_or_business_name,
                invoice_no=payload.invoice_no, action_date=payload.action_date,
                action_type=payload.action_type, outcome=payload.outcome,
                next_followup_date=payload.next_followup_date,
                promise_amount=payload.promise_amount, promise_date=payload.promise_date,
                actor=user.username)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return collection_action_payload(row)

    @app.post("/api/v1/credit-control/collections/{action_key}/{action}")
    def collection_workflow_action(action_key: str, action: str,
                                   payload: CollectionTransitionRequest, request: Request,
                                   operational_session=Depends(operational_session_dependency)):
        if action not in {"complete", "break", "cancel"}:
            raise HTTPException(status_code=404, detail="Collection workflow action not found")
        user = require_csrf(request, "collection.manage")
        row = operational_session.scalar(select(OperationalCollectionAction).where(
            OperationalCollectionAction.action_key == action_key).with_for_update())
        if not row:
            raise HTTPException(status_code=404, detail="Collection action not found")
        try:
            row = transition_collection_action(operational_session, row,
                expected_revision=payload.expected_revision, action=action,
                actor=user.username)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return collection_action_payload(row)

    @app.get("/api/v1/reports")
    def reports(snapshot: SourceSnapshot = Depends(snapshot_dependency), session: Session = Depends(session_dependency)):
        exceptions = session.execute(select(
            ErpMigrationExceptionQueue.severity, ErpMigrationExceptionQueue.queue_status,
            func.count(ErpMigrationExceptionQueue.id).label("count"),
        ).where(ErpMigrationExceptionQueue.snapshot_id == snapshot.id).group_by(
            ErpMigrationExceptionQueue.severity, ErpMigrationExceptionQueue.queue_status).order_by(
            ErpMigrationExceptionQueue.severity, ErpMigrationExceptionQueue.queue_status)).all()
        return {"exceptions": [dict(row._mapping) for row in exceptions], "source_atomic": snapshot.is_atomic,
                "source_system": snapshot.source_system, "snapshot": snapshot.name,
                "production_ready": False, "posting_enabled": False,
                "delta_overlay": _overlay_status(app.state.delta_overlay)}

    @app.get("/api/v1/delta-overlay")
    def delta_overlay():
        return _overlay_status(app.state.delta_overlay)

    return app


app = create_app()
