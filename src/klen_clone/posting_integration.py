from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .goods_receipts import OperationalGoodsReceipt, rehearse_goods_receipt_posting
from .inventory_operations import OperationalInventoryDocument, OperationalInventoryReservation, rehearse_inventory_posting
from .operational import (
    MONEY, OperationalAuditEvent, OperationalBase, OperationalDraft,
    OperationalStockPosition, OperationalStockReservation, utc_now,
)
from .payments import OperationalPayment, OperationalPaymentAllocationClaim, rehearse_payment_posting
from .procurement_matching import (
    OperationalSupplierAdjustment,
    OperationalSupplierInvoice,
    rehearse_supplier_adjustment_posting,
    rehearse_supplier_invoice_posting,
)
from .purchase_returns import (
    OperationalPurchaseReturn,
    OperationalPurchaseReturnPostingRehearsal,
    OperationalPurchaseReturnReservation,
    rehearse_purchase_return_posting,
)
from .sales_returns import OperationalSalesReturn, OperationalSalesReturnPostingRehearsal, rehearse_sales_return_posting
from .sales_invoices import OperationalSalesInvoicePostingRehearsal, rehearse_sales_invoice_posting

RESOURCE_TYPES = {"inventory_document", "goods_receipt", "sales_invoice", "sales_return", "purchase_return", "payment", "supplier_invoice", "supplier_adjustment"}


class OperationalIntegratedPostingBatch(OperationalBase):
    __tablename__ = "operational_integrated_posting_batches"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_integrated_posting_idempotency"),
        UniqueConstraint("resource_type", "resource_key", "posting_sequence", name="uq_integrated_posting_resource_sequence"),
        CheckConstraint("resource_type IN ('inventory_document','goods_receipt','sales_invoice','sales_return','purchase_return','payment','supplier_invoice','supplier_adjustment')", name="ck_integrated_posting_resource_type"),
        CheckConstraint("batch_kind IN ('posting','reversal')", name="ck_integrated_posting_kind"),
        CheckConstraint("status IN ('posted','reversed')", name="ck_integrated_posting_status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    resource_key: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    resource_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    posting_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    posting_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    fiscal_period_key: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    posted_by: Mapped[str] = mapped_column(String(200), nullable=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    reverses_batch_id: Mapped[int | None] = mapped_column(ForeignKey("operational_integrated_posting_batches.id"))
    reversed_by_batch_id: Mapped[int | None] = mapped_column(ForeignKey("operational_integrated_posting_batches.id"))
    reversal_reason: Mapped[str | None] = mapped_column(Text)


class OperationalIntegratedJournalLine(OperationalBase):
    __tablename__ = "operational_integrated_journal_lines"
    __table_args__ = (
        UniqueConstraint("batch_id", "line_no", name="uq_integrated_journal_line"),
        CheckConstraint("debit >= 0 AND credit >= 0 AND NOT (debit > 0 AND credit > 0)", name="ck_integrated_journal_sides"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("operational_integrated_posting_batches.id"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    account_code: Mapped[str] = mapped_column(String(80), nullable=False)
    debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)


class OperationalIntegratedStockEntry(OperationalBase):
    __tablename__ = "operational_integrated_stock_entries"
    __table_args__ = (UniqueConstraint("batch_id", "line_no", name="uq_integrated_stock_line"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("operational_integrated_posting_batches.id"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    source_line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    canonical_uom: Mapped[str] = mapped_column(String(80), nullable=False)
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    value_delta: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    prior_quantity_on_hand: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    prior_quantity_reserved: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    prior_average_unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    resulting_position_revision: Mapped[int] = mapped_column(Integer, nullable=False)


class OperationalIntegratedSubledgerEntry(OperationalBase):
    __tablename__ = "operational_integrated_subledger_entries"
    __table_args__ = (UniqueConstraint("batch_id", "line_no", name="uq_integrated_subledger_line"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("operational_integrated_posting_batches.id"), nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_type: Mapped[str] = mapped_column(String(40), nullable=False)
    party_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_type: Mapped[str | None] = mapped_column(String(30))
    source_reference_key: Mapped[str | None] = mapped_column(String(160))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(MONEY, rounding=ROUND_HALF_UP)


def _resource(session: Session, resource_type: str, resource_key: str, *, lock: bool = False):
    if resource_type == "sales_invoice":
        query = select(OperationalDraft).where(
            OperationalDraft.draft_key == resource_key,
            OperationalDraft.document_type == "sale",
        )
        return session.scalar(query.with_for_update() if lock else query)
    mapping = {
        "inventory_document": (OperationalInventoryDocument, OperationalInventoryDocument.document_key),
        "goods_receipt": (OperationalGoodsReceipt, OperationalGoodsReceipt.receipt_key),
        "sales_return": (OperationalSalesReturn, OperationalSalesReturn.return_key),
        "purchase_return": (OperationalPurchaseReturn, OperationalPurchaseReturn.return_key),
        "payment": (OperationalPayment, OperationalPayment.payment_key),
        "supplier_invoice": (OperationalSupplierInvoice, OperationalSupplierInvoice.invoice_key),
        "supplier_adjustment": (OperationalSupplierAdjustment, OperationalSupplierAdjustment.adjustment_key),
    }
    if resource_type not in mapping:
        raise ValueError("Unsupported posting resource type")
    model, key_column = mapping[resource_type]
    query = select(model).where(key_column == resource_key)
    return session.scalar(query.with_for_update() if lock else query)


def _plan(session: Session, resource_type: str, document, actor: str) -> dict:
    if resource_type == "inventory_document":
        plan = rehearse_inventory_posting(session, document, actor=actor)
        plan["subledger"] = []
    elif resource_type == "goods_receipt":
        plan = rehearse_goods_receipt_posting(session, document, actor=actor)
        plan["subledger"] = []
    elif resource_type == "sales_return":
        plan = rehearse_sales_return_posting(session, document, actor=actor)
        plan["journal"] = [{"account": row["account_code"], "debit": row["debit"], "credit": row["credit"]}
                           for row in plan["journal"]]
        plan["subledger"] = [{"entry_type": "receivable_credit", "party_code": document.customer_code,
            "source_type": "sales_invoice", "source_reference_key": document.original_invoice_reference,
            "amount": -document.total_amount}]
    elif resource_type == "sales_invoice":
        plan = rehearse_sales_invoice_posting(session, document, actor=actor)
        plan["journal"] = [{"account": row["account_code"], "debit": row["debit"], "credit": row["credit"]}
                           for row in plan["journal"]]
        plan["subledger"] = [{"entry_type": "receivable_invoice", "party_code": document.party_code,
            "source_type": "sales_invoice", "source_reference_key": document.draft_no,
            "amount": document.total_amount}]
    elif resource_type == "purchase_return":
        plan = rehearse_purchase_return_posting(session, document, actor=actor)
        plan["journal"] = [{"account": row["account_code"], "debit": row["debit"], "credit": row["credit"]}
                           for row in plan["journal"]]
        plan["subledger"] = [{"entry_type": "payable_debit", "party_code": document.supplier_code,
            "source_type": "supplier_invoice", "source_reference_key": plan["supplier_invoice_no"],
            "amount": -document.total_amount}]
    elif resource_type == "payment":
        plan = rehearse_payment_posting(session, document, actor=actor)
    elif resource_type == "supplier_invoice":
        plan = rehearse_supplier_invoice_posting(session, document, actor=actor)
        plan["journal"] = [{"account": row["account_code"], "debit": row["debit"], "credit": row["credit"]}
                           for row in plan["journal"]]
        plan["movements"] = []
        plan["subledger"] = [{"entry_type": "payable_invoice", "party_code": document.supplier_code,
            "source_type": "supplier_invoice", "source_reference_key": document.supplier_invoice_no,
            "amount": document.total_amount}]
    else:
        plan = rehearse_supplier_adjustment_posting(session, document, actor=actor)
        invoice = session.get(OperationalSupplierInvoice, document.supplier_invoice_id)
        plan["journal"] = [{"account": row["account_code"], "debit": row["debit"], "credit": row["credit"]}
                           for row in plan["journal"]]
        plan["movements"] = []
        plan["subledger"] = [{"entry_type": ("payable_credit_note" if document.adjustment_type == "credit_note"
                                               else "payable_debit_note"),
            "party_code": document.supplier_code, "source_type": "supplier_invoice",
            "source_reference_key": invoice.supplier_invoice_no,
            "amount": (-document.total_amount if document.adjustment_type == "credit_note" else document.total_amount)}]
    return plan


def posting_preview(session: Session, *, resource_type: str, resource_key: str, actor: str) -> dict:
    document = _resource(session, resource_type, resource_key)
    if not document:
        raise ValueError("Posting resource was not found")
    return _plan(session, resource_type, document, actor)


def get_posting_resource(session: Session, resource_type: str, resource_key: str):
    return _resource(session, resource_type, resource_key)


def _movement_location(row: dict) -> str:
    location = row.get("location_code") or row.get("location")
    if not location:
        raise ValueError("Stock movement location is required")
    return str(location)


def _control_rows(session: Session, resource_type: str, document, *, active_only: bool):
    model = None
    if resource_type == "inventory_document":
        model = OperationalInventoryReservation
        query = select(model).where(model.document_id == document.id)
    elif resource_type == "purchase_return":
        model = OperationalPurchaseReturnReservation
        query = select(model).where(model.purchase_return_id == document.id)
    elif resource_type == "payment":
        model = OperationalPaymentAllocationClaim
        query = select(model).where(model.payment_id == document.id)
    elif resource_type == "sales_invoice":
        model = OperationalStockReservation
        query = select(model).where(model.draft_id == document.id)
    else:
        return []
    if active_only:
        query = query.where(model.status == "active")
    return list(session.scalars(query.with_for_update()))


def _apply_movements(session: Session, batch: OperationalIntegratedPostingBatch, movements: list[dict], resource_type: str) -> None:
    indexed = list(enumerate(movements, 1))
    positions: dict[tuple[str, str], OperationalStockPosition] = {}
    for _, row in sorted(indexed, key=lambda item: (_movement_location(item[1]), str(item[1]["sku"]))):
        identity = (_movement_location(row), str(row["sku"]))
        if identity in positions:
            continue
        position = session.scalar(select(OperationalStockPosition).where(
            OperationalStockPosition.location_code == identity[0], OperationalStockPosition.sku == identity[1]).with_for_update())
        if not position and Decimal(str(row["quantity_base"])) < 0:
            raise ValueError(f"Stock position is unavailable for {identity[1]} at {identity[0]}")
        if not position:
            position = OperationalStockPosition(location_code=identity[0], sku=identity[1], canonical_uom=row["canonical_uom"],
                quantity_on_hand=0, quantity_reserved=0, average_unit_cost=0, revision=0,
                source_status=f"operational_{resource_type}", availability_enabled=True)
            session.add(position)
            session.flush()
        positions[identity] = position
    for number, row in indexed:
        location, sku = _movement_location(row), str(row["sku"])
        position = positions[(location, sku)]
        quantity, value = Decimal(str(row["quantity_base"])), _money(row["value_delta"])
        prior_quantity, prior_reserved = Decimal(position.quantity_on_hand), Decimal(position.quantity_reserved)
        prior_cost = Decimal(position.average_unit_cost)
        if position.canonical_uom.casefold() != str(row["canonical_uom"]).casefold():
            raise ValueError(f"Stock UOM mismatch for {sku} at {location}")
        if quantity < 0:
            outgoing = -quantity
            if position.quantity_on_hand < outgoing or position.quantity_reserved < outgoing:
                raise ValueError(f"Reserved stock is insufficient for posting {sku} at {location}")
            position.quantity_on_hand -= outgoing
            position.quantity_reserved -= outgoing
        elif quantity > 0:
            new_quantity = position.quantity_on_hand + quantity
            position.average_unit_cost = ((position.quantity_on_hand * position.average_unit_cost + value) / new_quantity).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            position.quantity_on_hand = new_quantity
        position.revision += 1
        position.updated_at = utc_now()
        session.flush()
        session.add(OperationalIntegratedStockEntry(batch_id=batch.id, line_no=number,
            source_line_no=int(row.get("line_no") or number), location_code=location, sku=sku,
            canonical_uom=row["canonical_uom"], quantity_delta=quantity, value_delta=value,
            prior_quantity_on_hand=prior_quantity, prior_quantity_reserved=prior_reserved,
            prior_average_unit_cost=prior_cost, resulting_position_revision=position.revision))


def _batch_payload(batch: OperationalIntegratedPostingBatch, *, idempotent_replay: bool = False) -> dict:
    return {"batch_key": batch.batch_key, "batch_kind": batch.batch_kind, "resource_type": batch.resource_type,
        "resource_key": batch.resource_key, "resource_revision": batch.resource_revision,
        "posting_fingerprint": batch.posting_fingerprint, "fiscal_period_key": batch.fiscal_period_key,
        "status": batch.status, "posted_at": batch.posted_at, "posted_by": batch.posted_by,
        "reverses_batch_id": batch.reverses_batch_id, "reversed_by_batch_id": batch.reversed_by_batch_id,
        "idempotent_replay": idempotent_replay}


def execute_integrated_posting(session: Session, *, resource_type: str, resource_key: str,
                               idempotency_key: str, actor: str) -> dict:
    existing = session.scalar(select(OperationalIntegratedPostingBatch).where(OperationalIntegratedPostingBatch.idempotency_key == idempotency_key))
    if existing:
        if existing.resource_type != resource_type or existing.resource_key != resource_key:
            raise ValueError("Idempotency key is already assigned to another resource")
        return _batch_payload(existing, idempotent_replay=True)
    document = _resource(session, resource_type, resource_key)
    if not document:
        raise ValueError("Posting resource was not found")
    expected_status = "accepted" if resource_type == "goods_receipt" else "approved"
    if document.status != expected_status:
        raise ValueError(f"Only a {expected_status} {resource_type.replace('_', ' ')} can be posted")
    if resource_type in {"sales_invoice", "supplier_invoice", "supplier_adjustment", "purchase_return", "sales_return"}:
        if document.created_by == actor:
            raise ValueError(f"The {resource_type.replace('_', '-')} maker cannot execute its posting")
    if resource_type == "supplier_invoice":
        dependent_adjustment = session.scalar(select(OperationalSupplierAdjustment.id).where(
            OperationalSupplierAdjustment.supplier_invoice_id == document.id,
            OperationalSupplierAdjustment.status.in_(("submitted", "approved"))))
        if dependent_adjustment:
            raise ValueError("Submitted or approved supplier adjustments must be resolved before invoice posting")
    revision = document.revision
    plan = _plan(session, resource_type, document, actor)
    if idempotency_key != plan["idempotency_key"]:
        raise ValueError("Posting idempotency key does not match the approved resource revision and plan")
    try:
        locked = _resource(session, resource_type, resource_key, lock=True)
        if not locked or locked.status != expected_status or locked.revision != revision:
            raise ValueError("Approved resource changed before atomic posting")
        batch = OperationalIntegratedPostingBatch(batch_key=str(uuid.uuid4()), idempotency_key=idempotency_key,
            resource_type=resource_type, resource_key=resource_key, resource_revision=revision,
            posting_sequence=1, batch_kind="posting", posting_fingerprint=plan["posting_fingerprint"],
            fiscal_period_key=str(plan["period_key"]), status="posted", posted_by=actor)
        session.add(batch)
        session.flush()
        for number, row in enumerate(plan.get("journal", []), 1):
            session.add(OperationalIntegratedJournalLine(batch_id=batch.id, line_no=number,
                account_code=row["account"], debit=_money(row["debit"]), credit=_money(row["credit"])))
        _apply_movements(session, batch, plan.get("movements", []), resource_type)
        for number, row in enumerate(plan.get("subledger", []), 1):
            session.add(OperationalIntegratedSubledgerEntry(batch_id=batch.id, line_no=number,
                entry_type=row["entry_type"], party_code=row["party_code"], source_type=row.get("source_type"),
                source_reference_key=row.get("source_reference_key"), amount=_money(row["amount"])))
        for row in _control_rows(session, resource_type, locked, active_only=True):
            row.status = "consumed"
        locked.status = "posted"
        locked.revision += 1
        locked.state_changed_at, locked.state_changed_by = utc_now(), actor
        if resource_type == "sales_return":
            locked.credit_note.status = "posted"
        if resource_type == "purchase_return":
            locked.debit_note.status = "posted"
        session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="integrated_posting.executed",
            actor=actor, resource_key=resource_key,
            detail=f"{resource_type}; batch {batch.batch_key}; fingerprint {batch.posting_fingerprint}; atomic posting"))
        session.commit()
        return _batch_payload(batch)
    except Exception:
        session.rollback()
        raise


def _reverse_stock(session: Session, original: OperationalIntegratedPostingBatch,
                   reversal: OperationalIntegratedPostingBatch) -> None:
    entries = list(session.scalars(select(OperationalIntegratedStockEntry).where(
        OperationalIntegratedStockEntry.batch_id == original.id).order_by(OperationalIntegratedStockEntry.line_no)))
    grouped: dict[tuple[str, str], list[OperationalIntegratedStockEntry]] = defaultdict(list)
    for entry in entries:
        grouped[(entry.location_code, entry.sku)].append(entry)
    positions: dict[tuple[str, str], OperationalStockPosition] = {}
    final_reserved: dict[tuple[str, str], Decimal] = {}
    for identity in sorted(grouped):
        rows = grouped[identity]
        position = session.scalar(select(OperationalStockPosition).where(
            OperationalStockPosition.location_code == identity[0], OperationalStockPosition.sku == identity[1]).with_for_update())
        if not position or position.revision != rows[-1].resulting_position_revision:
            raise ValueError(f"Later stock activity prevents exact reversal for {identity[1]} at {identity[0]}")
        target_reserved = Decimal(rows[0].prior_quantity_reserved) - sum(
            (-Decimal(row.quantity_delta) for row in rows if row.quantity_delta < 0), Decimal("0"))
        target_reserved = max(Decimal("0"), target_reserved)
        if Decimal(rows[0].prior_quantity_on_hand) < target_reserved:
            raise ValueError(f"Current reservations prevent exact reversal for {identity[1]} at {identity[0]}")
        positions[identity] = position
        final_reserved[identity] = target_reserved
    reversal_line = 0
    for identity in sorted(grouped):
        position = positions[identity]
        reverse_rows = list(reversed(grouped[identity]))
        for index, entry in enumerate(reverse_rows):
            reversal_line += 1
            prior_quantity, prior_reserved = Decimal(position.quantity_on_hand), Decimal(position.quantity_reserved)
            prior_cost = Decimal(position.average_unit_cost)
            position.quantity_on_hand = entry.prior_quantity_on_hand
            position.average_unit_cost = entry.prior_average_unit_cost
            if index == len(reverse_rows) - 1:
                position.quantity_reserved = final_reserved[identity]
            position.revision += 1
            position.updated_at = utc_now()
            session.flush()
            session.add(OperationalIntegratedStockEntry(batch_id=reversal.id, line_no=reversal_line,
                source_line_no=entry.source_line_no, location_code=entry.location_code, sku=entry.sku,
                canonical_uom=entry.canonical_uom, quantity_delta=-entry.quantity_delta,
                value_delta=-entry.value_delta, prior_quantity_on_hand=prior_quantity,
                prior_quantity_reserved=prior_reserved, prior_average_unit_cost=prior_cost,
                resulting_position_revision=position.revision))


def _execute_integrated_reversal(session: Session, batch: OperationalIntegratedPostingBatch, *, actor: str,
                                 reason: str) -> dict:
    if len(reason.strip()) < 5:
        raise ValueError("A meaningful reversal reason is required")
    locked = session.scalar(select(OperationalIntegratedPostingBatch).where(
        OperationalIntegratedPostingBatch.id == batch.id).with_for_update())
    if not locked:
        raise ValueError("Posting batch was not found")
    if locked.batch_kind != "posting":
        raise ValueError("A reversal batch cannot itself be reversed")
    if locked.status == "reversed" and locked.reversed_by_batch_id:
        return _batch_payload(session.get(OperationalIntegratedPostingBatch, locked.reversed_by_batch_id), idempotent_replay=True)
    if locked.status != "posted":
        raise ValueError("Only a posted batch can be reversed")
    document = _resource(session, locked.resource_type, locked.resource_key, lock=True)
    if not document or document.status != "posted":
        raise ValueError("The posted resource is unavailable for reversal")
    if locked.resource_type == "supplier_invoice":
        payment_dependency = session.scalar(select(OperationalPaymentAllocationClaim.id).where(
            OperationalPaymentAllocationClaim.party_code == document.supplier_code,
            OperationalPaymentAllocationClaim.source_type == "invoice",
            OperationalPaymentAllocationClaim.source_reference_key.in_((
                document.invoice_key, document.supplier_invoice_no)),
            OperationalPaymentAllocationClaim.status.in_(("active", "consumed"))))
        if payment_dependency:
            raise ValueError("A dependent supplier payment allocation prevents invoice reversal")
        adjustment_dependency = session.scalar(select(OperationalSupplierAdjustment.id).where(
            OperationalSupplierAdjustment.supplier_invoice_id == document.id,
            OperationalSupplierAdjustment.created_at >= locked.posted_at,
            OperationalSupplierAdjustment.status.not_in(("rejected", "cancelled"))))
        if adjustment_dependency:
            raise ValueError("Later supplier adjustment activity prevents invoice reversal")
    if locked.resource_type == "supplier_adjustment":
        invoice = session.get(OperationalSupplierInvoice, document.supplier_invoice_id)
        payment_dependency = session.scalar(select(OperationalPaymentAllocationClaim.id).where(
            OperationalPaymentAllocationClaim.party_code == document.supplier_code,
            OperationalPaymentAllocationClaim.source_type == "invoice",
            OperationalPaymentAllocationClaim.source_reference_key.in_((invoice.invoice_key, invoice.supplier_invoice_no)),
            OperationalPaymentAllocationClaim.created_at >= locked.posted_at,
            OperationalPaymentAllocationClaim.status.in_(("active", "consumed"))))
        if payment_dependency:
            raise ValueError("A later supplier payment allocation prevents adjustment reversal")
    if locked.resource_type == "purchase_return":
        rehearsal = session.scalar(select(OperationalPurchaseReturnPostingRehearsal).where(
            OperationalPurchaseReturnPostingRehearsal.purchase_return_id == document.id,
            OperationalPurchaseReturnPostingRehearsal.return_revision == locked.resource_revision))
        invoice = (session.get(OperationalSupplierInvoice, rehearsal.original_supplier_invoice_id)
                   if rehearsal else None)
        if invoice is None:
            raise ValueError("The original supplier-invoice link is unavailable for purchase-return reversal")
        payment_dependency = session.scalar(select(OperationalPaymentAllocationClaim.id).where(
            OperationalPaymentAllocationClaim.party_code == document.supplier_code,
            OperationalPaymentAllocationClaim.source_type == "invoice",
            OperationalPaymentAllocationClaim.source_reference_key.in_((
                invoice.invoice_key, invoice.supplier_invoice_no)),
            OperationalPaymentAllocationClaim.created_at >= locked.posted_at,
            OperationalPaymentAllocationClaim.status.in_(("active", "consumed"))))
        if payment_dependency:
            raise ValueError("A later supplier payment allocation prevents purchase-return reversal")
    if locked.resource_type == "sales_return":
        rehearsal = session.scalar(select(OperationalSalesReturnPostingRehearsal).where(
            OperationalSalesReturnPostingRehearsal.sales_return_id == document.id,
            OperationalSalesReturnPostingRehearsal.return_revision == locked.resource_revision))
        if rehearsal is None:
            raise ValueError("The original customer-invoice evidence is unavailable for sales-return reversal")
        receipt_dependency = session.scalar(select(OperationalPaymentAllocationClaim.id).where(
            OperationalPaymentAllocationClaim.party_code == document.customer_code,
            OperationalPaymentAllocationClaim.source_type == "invoice",
            OperationalPaymentAllocationClaim.source_reference_key == document.original_invoice_reference,
            OperationalPaymentAllocationClaim.created_at >= locked.posted_at,
            OperationalPaymentAllocationClaim.status.in_(("active", "consumed"))))
        if receipt_dependency:
            raise ValueError("A later customer receipt allocation prevents sales-return reversal")
    if locked.resource_type == "sales_invoice":
        rehearsal = session.scalar(select(OperationalSalesInvoicePostingRehearsal).where(
            OperationalSalesInvoicePostingRehearsal.sales_invoice_id == document.id,
            OperationalSalesInvoicePostingRehearsal.invoice_revision == locked.resource_revision))
        if rehearsal is None:
            raise ValueError("The approved sales-invoice rehearsal is unavailable for reversal")
        receipt_dependency = session.scalar(select(OperationalPaymentAllocationClaim.id).where(
            OperationalPaymentAllocationClaim.party_code == document.party_code,
            OperationalPaymentAllocationClaim.source_type == "invoice",
            OperationalPaymentAllocationClaim.source_reference_key.in_((document.draft_key, document.draft_no)),
            OperationalPaymentAllocationClaim.created_at >= locked.posted_at,
            OperationalPaymentAllocationClaim.status.in_(("active", "consumed"))))
        if receipt_dependency:
            raise ValueError("A later customer receipt allocation prevents sales-invoice reversal")
    fingerprint = hashlib.sha256(f"reverse:{locked.posting_fingerprint}".encode("ascii")).hexdigest()
    reversal = OperationalIntegratedPostingBatch(batch_key=str(uuid.uuid4()),
        idempotency_key=f"reverse:{locked.idempotency_key}", resource_type=locked.resource_type,
        resource_key=locked.resource_key, resource_revision=locked.resource_revision,
        posting_sequence=2, batch_kind="reversal", posting_fingerprint=fingerprint,
        fiscal_period_key=locked.fiscal_period_key, status="posted", posted_by=actor,
        reverses_batch_id=locked.id, reversal_reason=reason.strip())
    session.add(reversal)
    session.flush()
    original_lines = list(session.scalars(select(OperationalIntegratedJournalLine).where(
        OperationalIntegratedJournalLine.batch_id == locked.id).order_by(OperationalIntegratedJournalLine.line_no.desc())))
    for number, line in enumerate(original_lines, 1):
        session.add(OperationalIntegratedJournalLine(batch_id=reversal.id, line_no=number,
            account_code=line.account_code, debit=line.credit, credit=line.debit))
    _reverse_stock(session, locked, reversal)
    original_subledgers = list(session.scalars(select(OperationalIntegratedSubledgerEntry).where(
        OperationalIntegratedSubledgerEntry.batch_id == locked.id).order_by(OperationalIntegratedSubledgerEntry.line_no)))
    for number, entry in enumerate(original_subledgers, 1):
        session.add(OperationalIntegratedSubledgerEntry(batch_id=reversal.id, line_no=number,
            entry_type=entry.entry_type, party_code=entry.party_code, source_type=entry.source_type,
            source_reference_key=entry.source_reference_key, amount=-entry.amount))
    for row in _control_rows(session, locked.resource_type, document, active_only=False):
        row.status = "released"
        if hasattr(row, "released_at"):
            row.released_at = utc_now()
    locked.status = "reversed"
    locked.reversed_by_batch_id = reversal.id
    document.status = "reversed"
    document.revision += 1
    document.state_changed_at, document.state_changed_by = utc_now(), actor
    if locked.resource_type == "sales_return":
        document.credit_note.status = "reversed"
    if locked.resource_type == "purchase_return":
        document.debit_note.status = "reversed"
    session.add(OperationalAuditEvent(event_key=str(uuid.uuid4()), event_type="integrated_posting.reversed",
        actor=actor, resource_key=locked.resource_key,
        detail=f"batch {locked.batch_key}; reversal batch {reversal.batch_key}; {reason.strip()}"))
    session.commit()
    return _batch_payload(reversal)


def execute_integrated_reversal(session: Session, batch: OperationalIntegratedPostingBatch, *, actor: str,
                                reason: str) -> dict:
    try:
        return _execute_integrated_reversal(session, batch, actor=actor, reason=reason)
    except Exception:
        session.rollback()
        raise


def integrated_posting_counts(session: Session) -> dict:
    return {"batches": session.scalar(select(func.count(OperationalIntegratedPostingBatch.id))) or 0,
        "postings": session.scalar(select(func.count(OperationalIntegratedPostingBatch.id)).where(
            OperationalIntegratedPostingBatch.batch_kind == "posting")) or 0,
        "reversals": session.scalar(select(func.count(OperationalIntegratedPostingBatch.id)).where(
            OperationalIntegratedPostingBatch.batch_kind == "reversal")) or 0,
        "journal_lines": session.scalar(select(func.count(OperationalIntegratedJournalLine.id))) or 0,
        "stock_entries": session.scalar(select(func.count(OperationalIntegratedStockEntry.id))) or 0,
        "subledger_entries": session.scalar(select(func.count(OperationalIntegratedSubledgerEntry.id))) or 0}
