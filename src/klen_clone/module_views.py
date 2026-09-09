from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    ErpAuditEvent,
    ErpCashLedgerEvidence,
    ErpCoverageGate,
    ErpGlAccount,
    ErpInventoryMovement,
    ErpJournalBlueprint,
    ErpMigrationExceptionQueue,
    ErpOpeningBalanceQueue,
    ErpParty,
    ErpPortalIdentity,
    ErpProductMaster,
    ErpProductUom,
    ErpSalesTargetEvidence,
    ErpSalesWorkflowDocument,
    ErpShipmentRecord,
    ErpStockTransferDetailArtifact,
    ErpSubledgerControl,
    ErpTaxLedgerEvidence,
    ErpTransactionDocument,
    ErpTransactionLine,
    ErpTransactionPayment,
    ErpTrialBalanceEvidence,
    ErpUomMaster,
    SourceSnapshot,
)


MODULES = {
    "sales": ("Sales assurance", "Sales, POS, returns, payments and pre-order evidence"),
    "purchasing": ("Purchasing assurance", "Purchases, returns, suppliers and payable evidence"),
    "inventory": ("Inventory assurance", "Products, UOM conversions, receipts, issues and transfers"),
    "accounting": ("Accounting assurance", "Non-posting journals, subledgers, tax and trial-balance evidence"),
    "crm": ("CRM assurance", "Customer, supplier, portal and sales-target evidence"),
    "delivery": ("Delivery assurance", "Shipment and stock-transfer relationship evidence"),
    "reports": ("Reporting assurance", "Coverage, exception and immutable audit controls"),
}


def _count(session: Session, model, snapshot_id: int, *conditions) -> int:
    return session.scalar(select(func.count(model.id)).where(model.snapshot_id == snapshot_id, *conditions)) or 0


def _sum(session: Session, column, model, snapshot_id: int, *conditions) -> Decimal:
    return session.scalar(select(func.coalesce(func.sum(column), 0)).where(model.snapshot_id == snapshot_id, *conditions)) or Decimal("0")


def _breakdown(session: Session, model, column, snapshot_id: int, *conditions) -> list[dict]:
    rows = session.execute(select(column, func.count(model.id)).where(
        model.snapshot_id == snapshot_id, *conditions).group_by(column).order_by(func.count(model.id).desc())).all()
    return [{"label": row[0] or "Unspecified", "count": row[1]} for row in rows]


def _exceptions(session: Session, snapshot_id: int, source_kinds: tuple[str, ...] | None = None) -> list[dict]:
    query = select(
        ErpMigrationExceptionQueue.exception_code,
        ErpMigrationExceptionQueue.severity,
        func.count(ErpMigrationExceptionQueue.id),
    ).where(ErpMigrationExceptionQueue.snapshot_id == snapshot_id)
    if source_kinds:
        query = query.where(ErpMigrationExceptionQueue.source_kind.in_(source_kinds))
    rows = session.execute(query.group_by(
        ErpMigrationExceptionQueue.exception_code,
        ErpMigrationExceptionQueue.severity,
    ).order_by(func.count(ErpMigrationExceptionQueue.id).desc()).limit(8)).all()
    return [{"label": row[0].replace("_", " ").title(), "status": row[1], "count": row[2]} for row in rows]


def _card(label: str, value, value_format: str = "number") -> dict:
    return {"label": label, "value": value, "format": value_format}


def build_module_workspace(session: Session, snapshot: SourceSnapshot, module_code: str) -> dict:
    if module_code not in MODULES:
        raise KeyError(module_code)
    sid = snapshot.id
    title, subtitle = MODULES[module_code]

    if module_code == "sales":
        kinds = ("sale", "sale_return")
        cards = [
            _card("Sales documents", _count(session, ErpTransactionDocument, sid, ErpTransactionDocument.source_kind == "sale")),
            _card("Recorded sales value", _sum(session, ErpTransactionDocument.total_amount, ErpTransactionDocument, sid,
                                                ErpTransactionDocument.source_kind == "sale"), "amount"),
            _card("Sales returns", _count(session, ErpTransactionDocument, sid, ErpTransactionDocument.source_kind == "sale_return")),
            _card("Recorded amount due", _sum(session, ErpTransactionDocument.due_amount, ErpTransactionDocument, sid,
                                               ErpTransactionDocument.source_kind == "sale"), "amount"),
            _card("Sales lines", _count(session, ErpTransactionLine, sid, ErpTransactionLine.source_kind == "sale_line")),
            _card("Payment evidence", _count(session, ErpTransactionPayment, sid)),
        ]
        breakdowns = [
            {"title": "Document types", "items": _breakdown(session, ErpTransactionDocument, ErpTransactionDocument.source_kind, sid,
                                                              ErpTransactionDocument.source_kind.in_(kinds))},
            {"title": "Migration status", "items": _breakdown(session, ErpTransactionDocument, ErpTransactionDocument.migration_status, sid,
                                                                ErpTransactionDocument.source_kind.in_(kinds))},
            {"title": "Pre-order workflows", "items": _breakdown(session, ErpSalesWorkflowDocument,
                                                                   ErpSalesWorkflowDocument.workflow_kind, sid)},
        ]
        blockers = _exceptions(session, sid, ("sale_line",))
    elif module_code == "purchasing":
        kinds = ("purchase", "purchase_return")
        cards = [
            _card("Purchase documents", _count(session, ErpTransactionDocument, sid, ErpTransactionDocument.source_kind == "purchase")),
            _card("Recorded purchase value", _sum(session, ErpTransactionDocument.total_amount, ErpTransactionDocument, sid,
                                                   ErpTransactionDocument.source_kind == "purchase"), "amount"),
            _card("Purchase returns", _count(session, ErpTransactionDocument, sid,
                                              ErpTransactionDocument.source_kind == "purchase_return")),
            _card("Recorded amount due", _sum(session, ErpTransactionDocument.due_amount, ErpTransactionDocument, sid,
                                               ErpTransactionDocument.source_kind == "purchase"), "amount"),
            _card("Purchase lines", _count(session, ErpTransactionLine, sid, ErpTransactionLine.source_kind == "purchase_line")),
            _card("Suppliers", _count(session, ErpParty, sid, ErpParty.party_kind == "supplier")),
        ]
        breakdowns = [
            {"title": "Document types", "items": _breakdown(session, ErpTransactionDocument, ErpTransactionDocument.source_kind, sid,
                                                              ErpTransactionDocument.source_kind.in_(kinds))},
            {"title": "Migration status", "items": _breakdown(session, ErpTransactionDocument, ErpTransactionDocument.migration_status, sid,
                                                                ErpTransactionDocument.source_kind.in_(kinds))},
            {"title": "Supplier master status", "items": _breakdown(session, ErpParty, ErpParty.master_status, sid,
                                                                      ErpParty.party_kind == "supplier")},
        ]
        blockers = _exceptions(session, sid, ("purchase_line",))
    elif module_code == "inventory":
        cards = [
            _card("Products", _count(session, ErpProductMaster, sid)),
            _card("Inventory movements", _count(session, ErpInventoryMovement, sid)),
            _card("Base quantity net", _sum(session, ErpInventoryMovement.quantity_base, ErpInventoryMovement, sid), "quantity"),
            _card("UOM masters", _count(session, ErpUomMaster, sid)),
            _card("Product UOM profiles", _count(session, ErpProductUom, sid)),
            _card("Transfer documents", _count(session, ErpTransactionDocument, sid,
                                                ErpTransactionDocument.source_kind == "stock_transfer")),
        ]
        breakdowns = [
            {"title": "Movement types", "items": _breakdown(session, ErpInventoryMovement,
                                                              ErpInventoryMovement.movement_type, sid)},
            {"title": "Movement readiness", "items": _breakdown(session, ErpInventoryMovement,
                                                                  ErpInventoryMovement.migration_status, sid)},
            {"title": "Product master status", "items": _breakdown(session, ErpProductMaster,
                                                                     ErpProductMaster.master_status, sid)},
        ]
        blockers = _exceptions(session, sid, ("inventory_movement",))
    elif module_code == "accounting":
        cards = [
            _card("Journal blueprints", _count(session, ErpJournalBlueprint, sid)),
            _card("Blueprint debits", _sum(session, ErpJournalBlueprint.debit_total, ErpJournalBlueprint, sid), "amount"),
            _card("Blueprint credits", _sum(session, ErpJournalBlueprint.credit_total, ErpJournalBlueprint, sid), "amount"),
            _card("GL accounts", _count(session, ErpGlAccount, sid)),
            _card("Subledger controls", _count(session, ErpSubledgerControl, sid)),
            _card("Opening controls", _count(session, ErpOpeningBalanceQueue, sid)),
        ]
        breakdowns = [
            {"title": "Journal readiness", "items": _breakdown(session, ErpJournalBlueprint,
                                                                 ErpJournalBlueprint.migration_status, sid)},
            {"title": "Subledger reconciliation", "items": _breakdown(session, ErpSubledgerControl,
                                                                        ErpSubledgerControl.reconciliation_status, sid)},
            {"title": "Evidence registers", "items": [
                {"label": "Tax ledger", "count": _count(session, ErpTaxLedgerEvidence, sid)},
                {"label": "Cash ledger", "count": _count(session, ErpCashLedgerEvidence, sid)},
                {"label": "Trial balance", "count": _count(session, ErpTrialBalanceEvidence, sid)},
            ]},
        ]
        blockers = _exceptions(session, sid, ("financial_allocation", "reconciliation_exception", "payment"))
    elif module_code == "crm":
        cards = [
            _card("Customers", _count(session, ErpParty, sid, ErpParty.party_kind == "customer")),
            _card("Suppliers", _count(session, ErpParty, sid, ErpParty.party_kind == "supplier")),
            _card("Portal identities", _count(session, ErpPortalIdentity, sid)),
            _card("Active portal logins", _count(session, ErpPortalIdentity, sid,
                                                  ErpPortalIdentity.authentication_enabled.is_(True))),
            _card("Sales target evidence", _count(session, ErpSalesTargetEvidence, sid)),
            _card("Operational parties", _count(session, ErpParty, sid, ErpParty.operational_enabled.is_(True))),
        ]
        breakdowns = [
            {"title": "Party types", "items": _breakdown(session, ErpParty, ErpParty.party_kind, sid)},
            {"title": "Party master status", "items": _breakdown(session, ErpParty, ErpParty.master_status, sid)},
            {"title": "Portal relationship status", "items": _breakdown(session, ErpPortalIdentity,
                                                                          ErpPortalIdentity.party_link_status, sid)},
        ]
        blockers = _exceptions(session, sid, ("customer", "supplier", "contact_login", "sales_target"))
    elif module_code == "delivery":
        cards = [
            _card("Shipment evidence", _count(session, ErpShipmentRecord, sid)),
            _card("Linked shipments", _count(session, ErpShipmentRecord, sid,
                                              ErpShipmentRecord.sale_document_id.is_not(None))),
            _card("Transfer documents", _count(session, ErpTransactionDocument, sid,
                                                ErpTransactionDocument.source_kind == "stock_transfer")),
            _card("Transfer detail artifacts", _count(session, ErpStockTransferDetailArtifact, sid)),
            _card("Transfer-in movements", _count(session, ErpInventoryMovement, sid,
                                                   ErpInventoryMovement.movement_type == "transfer_in")),
            _card("Transfer-out movements", _count(session, ErpInventoryMovement, sid,
                                                    ErpInventoryMovement.movement_type == "transfer_out")),
        ]
        breakdowns = [
            {"title": "Shipment relationships", "items": _breakdown(session, ErpShipmentRecord,
                                                                      ErpShipmentRecord.relationship_status, sid)},
            {"title": "Transfer detail parse", "items": _breakdown(session, ErpStockTransferDetailArtifact,
                                                                     ErpStockTransferDetailArtifact.parse_status, sid)},
            {"title": "Transfer readiness", "items": _breakdown(session, ErpTransactionDocument,
                                                                  ErpTransactionDocument.migration_status, sid,
                                                                  ErpTransactionDocument.source_kind == "stock_transfer")},
        ]
        blockers = _exceptions(session, sid, ("shipment", "stock_transfer", "stock_transfer_detail"))
    else:
        cards = [
            _card("Source entities", _count(session, ErpCoverageGate, sid)),
            _card("Source rows", _sum(session, ErpCoverageGate.source_row_count, ErpCoverageGate, sid)),
            _card("Structured rows", _sum(session, ErpCoverageGate.structured_count, ErpCoverageGate, sid)),
            _card("Residual rows", _sum(session, ErpCoverageGate.residual_count, ErpCoverageGate, sid)),
            _card("Exceptions", _count(session, ErpMigrationExceptionQueue, sid)),
            _card("Audit events", _count(session, ErpAuditEvent, sid)),
        ]
        breakdowns = [
            {"title": "Coverage gate status", "items": _breakdown(session, ErpCoverageGate,
                                                                   ErpCoverageGate.gate_status, sid)},
            {"title": "Exception severity", "items": _breakdown(session, ErpMigrationExceptionQueue,
                                                                  ErpMigrationExceptionQueue.severity, sid)},
            {"title": "Exception queue status", "items": _breakdown(session, ErpMigrationExceptionQueue,
                                                                      ErpMigrationExceptionQueue.queue_status, sid)},
        ]
        blockers = _exceptions(session, sid)

    return {
        "module": module_code,
        "title": title,
        "subtitle": subtitle,
        "snapshot": snapshot.name,
        "cards": cards,
        "breakdowns": breakdowns,
        "blockers": blockers,
        "mode": "aggregate_read_only",
        "operational_enabled": False,
        "posting_enabled": False,
        "confidential_rows_exposed": False,
    }
