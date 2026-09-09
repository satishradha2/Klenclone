from __future__ import annotations

from collections import Counter

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from .models import (
    RawFileManifest, RawRecord, ReconciliationException, SourceSnapshot, StgContact,
    StgDocumentLine, StgDocumentReconciliation, StgEntityLink, StgItemTrace,
    StgAccountingControl, StgCashFlowEntry, StgFinancialAllocation,
    StgInventoryMovement, StgPaymentAccount, StgTaxEvidence, StgTrialBalanceEntry,
    StgCoaAccount, StgInventoryOpeningControl, StgJournalBlueprint,
    StgPayment, StgProduct, StgPurchase, StgPurchaseLine, StgReturn, StgSale,
    StgSaleLine, StgStockBalance, StgStockTransfer,
    ErpApprovalPolicy, ErpApprovalStep, ErpAuditEvent, ErpFiscalPeriod, ErpLocation,
    ErpMigrationBatch, ErpMigrationBatchEntity, ErpModulePolicy,
    ErpNumberSequence, ErpOrganization, ErpSourceKeyRegistry,
    ErpOpeningBalanceQueue, ErpParty, ErpProductMaster, ErpProductUom,
    ErpTaxProfile, ErpUomMaster,
    ErpInventoryMovement, ErpMigrationExceptionQueue, ErpTransactionDocument,
    ErpTransactionLine, ErpTransactionPayment,
    ErpCashLedgerEvidence, ErpFinancialActivationGate, ErpGlAccount,
    ErpJournalBlueprint, ErpJournalBlueprintLine, ErpSubledgerControl, ErpTaxLedgerEvidence,
    ErpTrialBalanceEvidence,
    ErpApprovalRoleBinding, ErpSecurityActivationGate, ErpSecurityLocationScope,
    ErpSecurityPermission, ErpSecurityPolicy, ErpSecurityRole,
    ErpSecurityRolePermission, ErpSecurityUser, ErpSecurityUserRole,
    ErpSegregationRule,
    ErpCoverageGate, ErpReferenceMaster, ErpResidualBusinessRecord, ErpSourceCoverage,
    ErpPortalIdentity, ErpResidualWorkflowGate, ErpSalesTargetEvidence,
    ErpSalesWorkflowDocument, ErpShipmentRecord, ErpStockTransferDetailArtifact,
    ErpApprovalDecision, ErpApprovalRequest, ErpAuthPrincipal,
    ErpRuntimeActivationGate, ErpRuntimeModule, ErpWorkflowDefinition,
)


def reconcile_snapshot(session: Session, snapshot_name: str) -> dict:
    snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == snapshot_name))
    if not snapshot:
        raise ValueError(f"Unknown snapshot: {snapshot_name}")

    generated_codes = (
        "DUPLICATE_DOCUMENT_NUMBER", "NEGATIVE_STOCK", "MISSING_STOCK_LOCATION",
        "ORPHAN_PAYMENT_PARENT", "ORPHAN_RETURN_PARENT", "DETAIL_HEADER_DRIFT",
        "AMBIGUOUS_RELATIONSHIP", "MASTER_SNAPSHOT_DRIFT",
    )
    session.execute(delete(ReconciliationException).where(
        ReconciliationException.snapshot_id == snapshot.id,
        ReconciliationException.code.in_(generated_codes),
    ))
    raw_counts = dict(session.execute(
        select(RawFileManifest.entity_type, func.sum(RawFileManifest.source_record_count))
        .where(RawFileManifest.snapshot_id == snapshot.id)
        .group_by(RawFileManifest.entity_type)
    ).all())
    business_counts = dict(session.execute(
        select(RawFileManifest.entity_type, func.count(RawRecord.id))
        .join(RawRecord)
        .where(RawFileManifest.snapshot_id == snapshot.id, RawRecord.is_presentation_row.is_(False))
        .group_by(RawFileManifest.entity_type)
    ).all())

    duplicates: dict[str, dict[str, int]] = {}
    for entity in ("sale", "purchase"):
        keys = session.scalars(
            select(RawRecord.source_document_number)
            .join(RawFileManifest)
            .where(
                RawFileManifest.snapshot_id == snapshot.id,
                RawFileManifest.entity_type == entity,
                RawRecord.is_presentation_row.is_(False),
                RawRecord.source_document_number.is_not(None),
            )
        ).all()
        repeated = {key: count for key, count in Counter(keys).items() if count > 1}
        duplicates[entity] = repeated
        for key, count in repeated.items():
            session.add(ReconciliationException(
                snapshot_id=snapshot.id,
                code="DUPLICATE_DOCUMENT_NUMBER",
                severity="critical",
                entity_type=entity,
                source_key=key,
                details={"occurrences": count},
            ))

    presentation_rows = session.scalar(
        select(func.count(RawRecord.id))
        .join(RawFileManifest)
        .where(RawFileManifest.snapshot_id == snapshot.id, RawRecord.is_presentation_row.is_(True))
    ) or 0

    typed_models = {
        "contact": StgContact, "product": StgProduct, "sale": StgSale,
        "purchase": StgPurchase, "payment": StgPayment, "return": StgReturn,
        "stock_balance": StgStockBalance, "stock_transfer": StgStockTransfer,
        "document_line": StgDocumentLine,
        "sale_line": StgSaleLine, "purchase_line": StgPurchaseLine,
        "item_trace": StgItemTrace, "entity_link": StgEntityLink,
        "document_reconciliation": StgDocumentReconciliation,
        "inventory_movement": StgInventoryMovement,
        "tax_evidence": StgTaxEvidence, "financial_allocation": StgFinancialAllocation,
        "payment_account": StgPaymentAccount, "cash_flow_entry": StgCashFlowEntry,
        "trial_balance_entry": StgTrialBalanceEntry, "accounting_control": StgAccountingControl,
        "coa_account": StgCoaAccount, "journal_blueprint": StgJournalBlueprint,
        "inventory_opening_control": StgInventoryOpeningControl,
        "erp_organization": ErpOrganization, "erp_location": ErpLocation,
        "erp_fiscal_period": ErpFiscalPeriod, "erp_number_sequence": ErpNumberSequence,
        "erp_module_policy": ErpModulePolicy, "erp_source_key_registry": ErpSourceKeyRegistry,
        "erp_approval_policy": ErpApprovalPolicy, "erp_migration_batch": ErpMigrationBatch,
        "erp_audit_event": ErpAuditEvent,
        "erp_party": ErpParty, "erp_product_master": ErpProductMaster,
        "erp_uom_master": ErpUomMaster, "erp_product_uom": ErpProductUom,
        "erp_tax_profile": ErpTaxProfile, "erp_opening_balance_queue": ErpOpeningBalanceQueue,
        "erp_transaction_document": ErpTransactionDocument,
        "erp_transaction_line": ErpTransactionLine,
        "erp_transaction_payment": ErpTransactionPayment,
        "erp_inventory_movement": ErpInventoryMovement,
        "erp_migration_exception_queue": ErpMigrationExceptionQueue,
        "erp_gl_account": ErpGlAccount, "erp_journal_blueprint": ErpJournalBlueprint,
        "erp_subledger_control": ErpSubledgerControl,
        "erp_tax_ledger_evidence": ErpTaxLedgerEvidence,
        "erp_cash_ledger_evidence": ErpCashLedgerEvidence,
        "erp_trial_balance_evidence": ErpTrialBalanceEvidence,
        "erp_financial_activation_gate": ErpFinancialActivationGate,
        "erp_security_role": ErpSecurityRole, "erp_security_permission": ErpSecurityPermission,
        "erp_security_user": ErpSecurityUser, "erp_security_location_scope": ErpSecurityLocationScope,
        "erp_segregation_rule": ErpSegregationRule, "erp_security_policy": ErpSecurityPolicy,
        "erp_security_activation_gate": ErpSecurityActivationGate,
        "erp_reference_master": ErpReferenceMaster,
        "erp_residual_business_record": ErpResidualBusinessRecord,
        "erp_source_coverage": ErpSourceCoverage, "erp_coverage_gate": ErpCoverageGate,
        "erp_portal_identity": ErpPortalIdentity,
        "erp_sales_workflow_document": ErpSalesWorkflowDocument,
        "erp_shipment_record": ErpShipmentRecord,
        "erp_sales_target_evidence": ErpSalesTargetEvidence,
        "erp_stock_transfer_detail_artifact": ErpStockTransferDetailArtifact,
        "erp_residual_workflow_gate": ErpResidualWorkflowGate,
        "erp_auth_principal": ErpAuthPrincipal,
        "erp_workflow_definition": ErpWorkflowDefinition,
        "erp_runtime_module": ErpRuntimeModule,
        "erp_runtime_activation_gate": ErpRuntimeActivationGate,
        "erp_approval_request": ErpApprovalRequest,
    }
    typed_counts = {
        name: session.scalar(select(func.count(model.id)).where(model.snapshot_id == snapshot.id)) or 0
        for name, model in typed_models.items()
    }
    batch_entity_count = session.scalar(select(func.count(ErpMigrationBatchEntity.id)).join(
        ErpMigrationBatch, ErpMigrationBatchEntity.batch_id == ErpMigrationBatch.id
    ).where(ErpMigrationBatch.snapshot_id == snapshot.id)) or 0
    typed_counts["erp_migration_batch_entity"] = batch_entity_count
    typed_counts["erp_journal_blueprint_line"] = session.scalar(select(func.count(ErpJournalBlueprintLine.id)).join(
        ErpJournalBlueprint, ErpJournalBlueprintLine.journal_id == ErpJournalBlueprint.id
    ).where(ErpJournalBlueprint.snapshot_id == snapshot.id)) or 0
    typed_counts["erp_security_role_permission"] = session.scalar(select(func.count(ErpSecurityRolePermission.id)).join(
        ErpSecurityRole, ErpSecurityRolePermission.role_id == ErpSecurityRole.id
    ).where(ErpSecurityRole.snapshot_id == snapshot.id)) or 0
    typed_counts["erp_security_user_role"] = session.scalar(select(func.count(ErpSecurityUserRole.id)).join(
        ErpSecurityUser, ErpSecurityUserRole.user_id == ErpSecurityUser.id
    ).where(ErpSecurityUser.snapshot_id == snapshot.id)) or 0
    typed_counts["erp_approval_role_binding"] = session.scalar(select(func.count(ErpApprovalRoleBinding.id)).join(
        ErpApprovalStep, ErpApprovalRoleBinding.approval_step_id == ErpApprovalStep.id
    ).join(ErpApprovalPolicy, ErpApprovalStep.policy_id == ErpApprovalPolicy.id).where(
        ErpApprovalPolicy.snapshot_id == snapshot.id)) or 0
    typed_counts["erp_approval_decision"] = session.scalar(select(func.count(ErpApprovalDecision.id)).join(
        ErpApprovalRequest, ErpApprovalDecision.approval_request_id == ErpApprovalRequest.id
    ).where(ErpApprovalRequest.snapshot_id == snapshot.id)) or 0

    negative_stock = session.scalars(select(StgStockBalance).where(
        StgStockBalance.snapshot_id == snapshot.id, StgStockBalance.available_quantity < 0
    )).all()
    missing_location = session.scalars(select(StgStockBalance).where(
        StgStockBalance.snapshot_id == snapshot.id,
        or_(StgStockBalance.location.is_(None), StgStockBalance.location == ""),
    )).all()
    for row in negative_stock:
        session.add(ReconciliationException(snapshot_id=snapshot.id, code="NEGATIVE_STOCK", severity="high", entity_type="stock_balance", source_key=row.sku, details={"raw_record_id": row.raw_record_id, "product": row.product_name, "location": row.location, "quantity": str(row.available_quantity)}))
    for row in missing_location:
        session.add(ReconciliationException(snapshot_id=snapshot.id, code="MISSING_STOCK_LOCATION", severity="high", entity_type="stock_balance", source_key=row.sku, details={"raw_record_id": row.raw_record_id, "product": row.product_name, "quantity": str(row.available_quantity)}))

    sale_docs = set(session.scalars(select(StgSale.document_no).where(StgSale.snapshot_id == snapshot.id)))
    purchase_docs = set(session.scalars(select(StgPurchase.document_no).where(StgPurchase.snapshot_id == snapshot.id)))
    orphan_payments = []
    for payment in session.scalars(select(StgPayment).where(StgPayment.snapshot_id == snapshot.id)):
        parents = sale_docs if payment.direction == "sale" else purchase_docs
        if payment.parent_document_no and payment.parent_document_no not in parents:
            orphan_payments.append(payment)
            session.add(ReconciliationException(snapshot_id=snapshot.id, code="ORPHAN_PAYMENT_PARENT", severity="high", entity_type=f"{payment.direction}_payment", source_key=payment.reference_no, details={"raw_record_id": payment.raw_record_id, "parent_document_no": payment.parent_document_no}))

    orphan_returns = []
    for returned in session.scalars(select(StgReturn).where(StgReturn.snapshot_id == snapshot.id)):
        parents = sale_docs if returned.direction == "sale" else purchase_docs
        if returned.parent_document_no and returned.parent_document_no not in parents:
            orphan_returns.append(returned)
            session.add(ReconciliationException(snapshot_id=snapshot.id, code="ORPHAN_RETURN_PARENT", severity="high", entity_type=f"{returned.direction}_return", source_key=returned.document_no, details={"raw_record_id": returned.raw_record_id, "parent_document_no": returned.parent_document_no}))

    drift: dict[str, list[str]] = {}
    header_sets = {
        "sales_return": set(session.scalars(select(StgReturn.document_no).where(StgReturn.snapshot_id == snapshot.id, StgReturn.direction == "sale"))),
        "purchase_return": set(session.scalars(select(StgReturn.document_no).where(StgReturn.snapshot_id == snapshot.id, StgReturn.direction == "purchase"))),
        "stock_transfer": set(session.scalars(select(StgStockTransfer.document_no).where(StgStockTransfer.snapshot_id == snapshot.id))),
    }
    for entity, headers in header_sets.items():
        detail_docs = set(session.scalars(select(StgDocumentLine.parent_document_no).where(StgDocumentLine.snapshot_id == snapshot.id, StgDocumentLine.source_entity == entity, StgDocumentLine.parent_document_no.is_not(None))))
        later = sorted(detail_docs - headers)
        if later:
            drift[entity] = later
            for document in later:
                session.add(ReconciliationException(snapshot_id=snapshot.id, code="DETAIL_HEADER_DRIFT", severity="critical", entity_type=entity, source_key=document, details={"detail_without_header_in_earlier_snapshot": True}))

    unmatched_sale_line_ids = session.scalars(select(StgEntityLink.source_id).where(
        StgEntityLink.snapshot_id == snapshot.id, StgEntityLink.source_kind == "sale_line",
        StgEntityLink.target_kind == "sale", StgEntityLink.status == "unmatched",
    )).all()
    later_sale_documents = sorted(set(session.scalars(select(StgSaleLine.document_no).where(StgSaleLine.id.in_(unmatched_sale_line_ids))))) if unmatched_sale_line_ids else []
    if later_sale_documents:
        drift["sale"] = later_sale_documents
        for document in later_sale_documents:
            session.add(ReconciliationException(snapshot_id=snapshot.id, code="DETAIL_HEADER_DRIFT", severity="critical", entity_type="sale", source_key=document, details={"sales_lines_without_header_in_earlier_snapshot": True}))

    ambiguous_links = session.scalars(select(StgEntityLink).where(
        StgEntityLink.snapshot_id == snapshot.id, StgEntityLink.status == "ambiguous",
    )).all()
    for link in ambiguous_links:
        payment = session.get(StgPayment, link.source_id) if link.source_kind == "payment" else None
        source_key = payment.reference_no if payment else str(link.source_id)
        session.add(ReconciliationException(snapshot_id=snapshot.id, code="AMBIGUOUS_RELATIONSHIP", severity="critical", entity_type=link.source_kind, source_key=source_key, details={"target_kind": link.target_kind, "candidate_count": link.candidate_count, "match_method": link.match_method, "parent_document_no": payment.parent_document_no if payment else None}))

    unmatched_stock_links = session.scalars(select(StgEntityLink).where(
        StgEntityLink.snapshot_id == snapshot.id, StgEntityLink.source_kind == "stock_balance",
        StgEntityLink.target_kind == "product", StgEntityLink.status == "unmatched",
    )).all()
    for link in unmatched_stock_links:
        stock = session.get(StgStockBalance, link.source_id)
        session.add(ReconciliationException(snapshot_id=snapshot.id, code="MASTER_SNAPSHOT_DRIFT", severity="critical", entity_type="product", source_key=stock.sku if stock else str(link.source_id), details={"stock_record_without_product_in_earlier_master_snapshot": True, "product": stock.product_name if stock else None}))
    session.commit()
    return {
        "snapshot": snapshot.name,
        "atomic": snapshot.is_atomic,
        "raw_record_counts": raw_counts,
        "business_record_counts": business_counts,
        "duplicate_document_numbers": duplicates,
        "presentation_rows_quarantined": presentation_rows,
        "typed_counts": typed_counts,
        "stock_exceptions": {"negative": len(negative_stock), "missing_location": len(missing_location)},
        "orphan_relationships": {"payments": len(orphan_payments), "returns": len(orphan_returns)},
        "detail_header_drift": drift,
        "ambiguous_relationships": len(ambiguous_links),
        "master_snapshot_drift": len(unmatched_stock_links),
    }
