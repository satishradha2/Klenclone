from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from klen_clone.inventory_operations import (
    OperationalInventoryReservation,
    create_inventory_document,
    rehearse_inventory_posting,
    transition_inventory_document,
)
from klen_clone.goods_receipts import create_goods_receipt, rehearse_goods_receipt_posting, transition_goods_receipt
from klen_clone.operational import OperationalFiscalPeriod, OperationalStockPosition, initialize_operational_database, make_operational_engine
from klen_clone.payments import OperationalPaymentAllocationClaim, create_payment, rehearse_payment_posting, transition_payment
from klen_clone.purchase_returns import create_purchase_return, rehearse_purchase_return_posting, transition_purchase_return
from klen_clone.sales_returns import create_sales_return, rehearse_sales_return_posting, transition_sales_return
from klen_clone.posting_integration import (
    OperationalIntegratedJournalLine,
    OperationalIntegratedPostingBatch,
    OperationalIntegratedStockEntry,
    OperationalIntegratedSubledgerEntry,
    execute_integrated_posting,
    execute_integrated_reversal,
)


def posting_session(tmp_path) -> Session:
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'posting.db'}")
    initialize_operational_database(engine)
    session = Session(engine)
    session.add_all([
        OperationalFiscalPeriod(period_key="2026-09", starts_on=date(2026, 9, 1), ends_on=date(2026, 9, 30),
            status="open", rehearsal_enabled=True, approval_reference="test", configured_by="controller"),
        OperationalStockPosition(location_code="SHJ", sku="SKU-1", canonical_uom="piece",
            quantity_on_hand=Decimal("20"), quantity_reserved=Decimal("0"), average_unit_cost=Decimal("7.65"),
            availability_enabled=True, source_status="test_reconciled"),
        OperationalStockPosition(location_code="DXB", sku="SKU-1", canonical_uom="piece",
            quantity_on_hand=Decimal("5"), quantity_reserved=Decimal("0"), average_unit_cost=Decimal("8.00"),
            availability_enabled=True, source_status="test_reconciled"),
    ])
    session.commit()
    return session


def test_transfer_posts_idempotently_and_reverses_with_immutable_counter_batch(tmp_path):
    session = posting_session(tmp_path)
    document = create_inventory_document(session, document_type="transfer", location_code="SHJ",
        destination_location_code="DXB", adjustment_direction=None, reason_code="replenishment", notes=None,
        actor="maker", lines=[{"sku": "SKU-1", "product_name_snapshot": "Product One",
            "quantity": Decimal("4"), "uom": "Piece", "canonical_uom": "piece",
            "factor_to_base_snapshot": Decimal("1"), "unit_cost_snapshot": Decimal("7.65")}])
    document = transition_inventory_document(session, document, expected_revision=1, action="submit", actor="maker")
    document = transition_inventory_document(session, document, expected_revision=2, action="approve", actor="approver")
    plan = rehearse_inventory_posting(session, document, actor="approver")
    posted = execute_integrated_posting(session, resource_type="inventory_document",
        resource_key=document.document_key, idempotency_key=plan["idempotency_key"], actor="approver")
    assert posted["batch_kind"] == "posting" and posted["fiscal_period_key"] == "2026-09"
    assert execute_integrated_posting(session, resource_type="inventory_document",
        resource_key=document.document_key, idempotency_key=plan["idempotency_key"],
        actor="approver")["idempotent_replay"] is True
    positions = {(row.location_code, row.sku): row for row in session.scalars(select(OperationalStockPosition))}
    assert positions[("SHJ", "SKU-1")].quantity_on_hand == 16
    assert positions[("DXB", "SKU-1")].quantity_on_hand == 9
    assert positions[("SHJ", "SKU-1")].quantity_reserved == 0
    original = session.scalar(select(OperationalIntegratedPostingBatch).where(
        OperationalIntegratedPostingBatch.batch_key == posted["batch_key"]))
    reversed_result = execute_integrated_reversal(session, original, actor="controller", reason="Approved test reversal")
    assert reversed_result["batch_kind"] == "reversal"
    assert original.status == "reversed" and original.reversed_by_batch_id
    session.refresh(positions[("SHJ", "SKU-1")])
    session.refresh(positions[("DXB", "SKU-1")])
    assert positions[("SHJ", "SKU-1")].quantity_on_hand == 20
    assert positions[("DXB", "SKU-1")].quantity_on_hand == 5
    assert session.scalar(select(OperationalInventoryReservation)).status == "released"
    assert session.scalar(select(func.count(OperationalIntegratedPostingBatch.id))) == 2
    assert session.scalar(select(func.count(OperationalIntegratedStockEntry.id))) == 4


def test_payment_posting_and_reversal_create_balanced_journal_and_subledger_counters(tmp_path):
    session = posting_session(tmp_path)
    payment = create_payment(session, actor="maker", payment_type="customer_receipt", party_code="CUS-1",
        party_name_snapshot="Customer One", location_code="SHJ", payment_date=date(2026, 9, 9),
        payment_method="bank_transfer", cash_bank_account_code="Bank - AED", reference_no="BANK-1",
        amount=Decimal("75"), notes=None, lines=[{"source_type": "invoice",
            "source_reference_key": "INV-1", "source_document_date": date(2026, 9, 1),
            "source_outstanding_snapshot": Decimal("100"), "allocation_amount": Decimal("60")}])
    payment = transition_payment(session, payment, expected_revision=1, action="submit", actor="maker")
    payment = transition_payment(session, payment, expected_revision=2, action="approve", actor="approver")
    plan = rehearse_payment_posting(session, payment, actor="approver")
    posted = execute_integrated_posting(session, resource_type="payment", resource_key=payment.payment_key,
        idempotency_key=plan["idempotency_key"], actor="approver")
    batch = session.scalar(select(OperationalIntegratedPostingBatch).where(
        OperationalIntegratedPostingBatch.batch_key == posted["batch_key"]))
    lines = list(session.scalars(select(OperationalIntegratedJournalLine).where(
        OperationalIntegratedJournalLine.batch_id == batch.id)))
    assert sum((row.debit for row in lines), Decimal("0")) == sum((row.credit for row in lines), Decimal("0")) == 75
    assert session.scalar(select(func.count(OperationalIntegratedSubledgerEntry.id))) == 2
    assert session.scalar(select(OperationalPaymentAllocationClaim)).status == "consumed"
    reversal = execute_integrated_reversal(session, batch, actor="controller", reason="Bank receipt was duplicated")
    reverse_batch = session.scalar(select(OperationalIntegratedPostingBatch).where(
        OperationalIntegratedPostingBatch.batch_key == reversal["batch_key"]))
    reverse_lines = list(session.scalars(select(OperationalIntegratedJournalLine).where(
        OperationalIntegratedJournalLine.batch_id == reverse_batch.id)))
    assert sum((row.debit for row in reverse_lines), Decimal("0")) == 75
    assert sum((row.credit for row in reverse_lines), Decimal("0")) == 75
    amounts = list(session.scalars(select(OperationalIntegratedSubledgerEntry.amount).order_by(
        OperationalIntegratedSubledgerEntry.id)))
    assert amounts == [Decimal("60.00"), Decimal("15.00"), Decimal("-60.00"), Decimal("-15.00")]
    assert session.scalar(select(OperationalPaymentAllocationClaim)).status == "released"
    assert execute_integrated_reversal(session, batch, actor="controller",
        reason="Bank receipt was duplicated")["idempotent_replay"] is True


def test_posting_failure_can_be_rolled_back_without_partial_ledgers(tmp_path):
    session = posting_session(tmp_path)
    document = create_inventory_document(session, document_type="transfer", location_code="SHJ",
        destination_location_code="DXB", adjustment_direction=None, reason_code="replenishment", notes=None,
        actor="maker", lines=[{"sku": "SKU-1", "product_name_snapshot": "Product One",
            "quantity": Decimal("4"), "uom": "Piece", "canonical_uom": "piece",
            "factor_to_base_snapshot": Decimal("1"), "unit_cost_snapshot": Decimal("7.65")}])
    document = transition_inventory_document(session, document, expected_revision=1, action="submit", actor="maker")
    document = transition_inventory_document(session, document, expected_revision=2, action="approve", actor="approver")
    plan = rehearse_inventory_posting(session, document, actor="approver")
    source = session.scalar(select(OperationalStockPosition).where(OperationalStockPosition.location_code == "SHJ"))
    source.quantity_reserved = 0
    session.commit()
    with pytest.raises(ValueError, match="Reserved stock is insufficient"):
        execute_integrated_posting(session, resource_type="inventory_document", resource_key=document.document_key,
            idempotency_key=plan["idempotency_key"], actor="approver")
    assert session.scalar(select(func.count(OperationalIntegratedPostingBatch.id))) == 0
    assert session.scalar(select(func.count(OperationalIntegratedJournalLine.id))) == 0
    assert session.scalar(select(func.count(OperationalIntegratedStockEntry.id))) == 0


def test_receipt_and_both_return_types_post_and_reverse_through_the_same_control_path(tmp_path):
    session = posting_session(tmp_path)
    receipt = create_goods_receipt(session, supplier_code="SUP-1", supplier_name_snapshot="Supplier One",
        location_code="SHJ", purchase_reference="PO-1", supplier_delivery_note="DN-1",
        received_on=date(2026, 9, 9), notes=None, actor="maker", lines=[{"sku": "SKU-1",
            "product_name_snapshot": "Product One", "ordered_quantity": Decimal("2"),
            "received_quantity": Decimal("2"), "accepted_quantity": Decimal("2"),
            "rejected_quantity": Decimal("0"), "uom": "Piece", "canonical_uom": "piece",
            "factor_to_base_snapshot": Decimal("1"), "unit_cost_snapshot": Decimal("8"),
            "batch_no": None, "expiry_date": None, "rejection_reason": None}])
    receipt = transition_goods_receipt(session, receipt, expected_revision=1, action="submit", actor="maker")
    receipt = transition_goods_receipt(session, receipt, expected_revision=2, action="accept", actor="approver")
    receipt_plan = rehearse_goods_receipt_posting(session, receipt, actor="approver")
    receipt_result = execute_integrated_posting(session, resource_type="goods_receipt", resource_key=receipt.receipt_key,
        idempotency_key=receipt_plan["idempotency_key"], actor="approver")
    receipt_batch = session.scalar(select(OperationalIntegratedPostingBatch).where(
        OperationalIntegratedPostingBatch.batch_key == receipt_result["batch_key"]))
    execute_integrated_reversal(session, receipt_batch, actor="controller", reason="Receipt test rollback")
    assert receipt.status == "reversed"

    sales_return = create_sales_return(session, customer_code="CUS-1", customer_name_snapshot="Customer One",
        location_code="SHJ", original_invoice_reference="INV-1", return_date=date(2026, 9, 9),
        reason_code="customer_return", notes=None, actor="maker", lines=[{"sku": "SKU-1",
            "product_name_snapshot": "Product One", "quantity": Decimal("2"), "restock_quantity": Decimal("2"),
            "writeoff_quantity": Decimal("0"), "uom": "Piece", "canonical_uom": "piece",
            "factor_to_base_snapshot": Decimal("1"), "unit_price": Decimal("10"), "tax_rate": Decimal("5"),
            "unit_cost_snapshot": Decimal("7.65"), "disposition_reason": None}])
    sales_return = transition_sales_return(session, sales_return, expected_revision=1, action="submit", actor="maker")
    sales_return = transition_sales_return(session, sales_return, expected_revision=2, action="approve", actor="approver")
    sales_plan = rehearse_sales_return_posting(session, sales_return, actor="approver")
    sales_result = execute_integrated_posting(session, resource_type="sales_return", resource_key=sales_return.return_key,
        idempotency_key=sales_plan["idempotency_key"], actor="approver")
    sales_batch = session.scalar(select(OperationalIntegratedPostingBatch).where(
        OperationalIntegratedPostingBatch.batch_key == sales_result["batch_key"]))
    execute_integrated_reversal(session, sales_batch, actor="controller", reason="Sales return test rollback")
    assert sales_return.status == "reversed" and sales_return.credit_note.status == "reversed"

    purchase_return = create_purchase_return(session, supplier_code="SUP-1", supplier_name_snapshot="Supplier One",
        location_code="SHJ", source_reference_type="goods_receipt", source_reference_key="GRN-1",
        return_date=date(2026, 9, 9), reason_code="quality", notes=None, actor="maker",
        lines=[{"sku": "SKU-1", "product_name_snapshot": "Product One", "source_received_quantity": Decimal("10"),
            "quantity": Decimal("4"), "supplier_return_quantity": Decimal("4"),
            "internal_writeoff_quantity": Decimal("0"), "uom": "Piece", "canonical_uom": "piece",
            "factor_to_base_snapshot": Decimal("1"), "unit_price": Decimal("8"), "tax_rate": Decimal("5"),
            "unit_cost_snapshot": Decimal("7.65"), "disposition_reason": None}])
    purchase_return = transition_purchase_return(session, purchase_return, expected_revision=1, action="submit", actor="maker")
    purchase_return = transition_purchase_return(session, purchase_return, expected_revision=2, action="approve", actor="approver")
    purchase_plan = rehearse_purchase_return_posting(session, purchase_return, actor="approver")
    purchase_result = execute_integrated_posting(session, resource_type="purchase_return",
        resource_key=purchase_return.return_key, idempotency_key=purchase_plan["idempotency_key"], actor="approver")
    purchase_batch = session.scalar(select(OperationalIntegratedPostingBatch).where(
        OperationalIntegratedPostingBatch.batch_key == purchase_result["batch_key"]))
    execute_integrated_reversal(session, purchase_batch, actor="controller", reason="Purchase return test rollback")
    assert purchase_return.status == "reversed" and purchase_return.debit_note.status == "reversed"
    assert session.scalar(select(OperationalStockPosition).where(
        OperationalStockPosition.location_code == "SHJ")).quantity_on_hand == 20
