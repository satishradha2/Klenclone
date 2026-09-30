from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from klen_clone.cash_management import (create_cash_account, create_statement_batch,
    decide_cash_account, match_refund_statement_line, transition_statement_batch)
from klen_clone.customer_invoices import create_customer_invoice, transition_customer_invoice
from klen_clone.customer_refunds import (create_refund, refund_available,
    refund_posting_plan, transition_refund)
from klen_clone.delivery_fulfillment import transition_delivery
from klen_clone.financial_reports import build_customer_statement
from klen_clone.operational import OperationalStockPosition
from klen_clone.payments import (create_payment, customer_invoice_settlement,
    rehearse_payment_posting, transition_payment)
from klen_clone.posting_integration import (OperationalIntegratedJournalLine,
    OperationalIntegratedPostingBatch, OperationalIntegratedStockEntry, execute_integrated_posting,
    execute_integrated_reversal, posting_preview)
from klen_clone.sales_returns import (create_sales_return, rehearse_sales_return_posting,
    target_invoice_evidence_hash, target_return_credit, transition_sales_return)
from test_customer_invoices import delivered_order, session


def test_partial_refund_is_reserved_bank_confirmed_and_settled(session):
    _, delivery = delivered_order(session)
    delivery = transition_delivery(session, delivery, expected_revision=3, action="deliver",
        actor="pod-checker", note="POD verified", received_by="Customer Receiver",
        pod_reference="POD-REFUND-E2E")
    invoice_date = delivery.delivered_at.date()
    invoice = create_customer_invoice(session, delivery, actor="sales-maker",
        invoice_date=invoice_date, due_date=invoice_date + timedelta(days=30))
    invoice = transition_customer_invoice(session, invoice, expected_revision=1,
        action="submit", actor="sales-maker")
    invoice = transition_customer_invoice(session, invoice, expected_revision=2,
        action="approve", actor="sales-manager", note="POD and amounts verified")
    plan = posting_preview(session, resource_type="customer_invoice",
        resource_key=invoice.invoice_key, actor="finance-controller")
    execute_integrated_posting(session, resource_type="customer_invoice",
        resource_key=invoice.invoice_key, idempotency_key=plan["idempotency_key"],
        actor="finance-controller")
    receipt = create_payment(session, actor="ar-maker", payment_type="customer_receipt",
        party_code="C-1", party_name_snapshot="Customer One", location_code="MAIN",
        payment_date=invoice_date, payment_method="bank_transfer",
        cash_bank_account_code="Bank - AED", reference_no="BANK-REFUND-RECEIPT",
        amount=invoice.total_amount, notes=None, lines=[{
            "source_type": "invoice", "source_reference_key": invoice.invoice_no,
            "source_document_date": invoice.invoice_date,
            "source_outstanding_snapshot": invoice.total_amount,
            "allocation_amount": invoice.total_amount}])
    receipt = transition_payment(session, receipt, expected_revision=1,
        action="submit", actor="ar-maker")
    receipt = transition_payment(session, receipt, expected_revision=2,
        action="approve", actor="finance-approver")
    receipt_plan = rehearse_payment_posting(session, receipt, actor="finance-approver")
    execute_integrated_posting(session, resource_type="payment", resource_key=receipt.payment_key,
        idempotency_key=receipt_plan["idempotency_key"], actor="finance-approver")
    net, tax = target_return_credit(invoice.lines[0], Decimal("0"), Decimal("1"))
    stock = session.scalar(select(OperationalStockPosition).where(
        OperationalStockPosition.location_code == invoice.location_code,
        OperationalStockPosition.sku == invoice.lines[0].sku))
    quantity_before_credit = Decimal(stock.quantity_on_hand)
    returned = create_sales_return(session, customer_code="C-1", customer_name_snapshot="Customer One",
        location_code="MAIN", original_invoice_reference=invoice.invoice_no,
        return_date=invoice_date, reason_code="customer_return", notes=None,
        actor="return-maker", original_invoice_source_record_id=0,
        original_invoice_total_snapshot=invoice.total_amount,
        original_invoice_evidence_hash=target_invoice_evidence_hash(invoice),
        original_invoice_origin="target_erp", original_invoice_target_key=invoice.invoice_key,
        lines=[{"sku": "SKU-1", "product_name_snapshot": "Product One",
            "quantity": Decimal("1"), "restock_quantity": Decimal("1"),
            "writeoff_quantity": Decimal("0"), "uom": invoice.lines[0].uom,
            "canonical_uom": invoice.lines[0].canonical_uom,
            "factor_to_base_snapshot": invoice.lines[0].factor_to_base_snapshot,
            "unit_price": invoice.lines[0].unit_price, "tax_rate": invoice.lines[0].tax_rate,
            "unit_cost_snapshot": Decimal("4"),
            "original_invoice_quantity_snapshot": invoice.lines[0].quantity,
            "original_invoice_unit_price_snapshot": invoice.lines[0].unit_price,
            "credit_net_amount": net, "credit_tax_amount": tax,
            "disposition_reason": None}])
    returned = transition_sales_return(session, returned, expected_revision=1,
        action="submit", actor="return-maker")
    returned = transition_sales_return(session, returned, expected_revision=2,
        action="approve", actor="return-checker")
    assert Decimal(stock.quantity_on_hand) == quantity_before_credit
    return_plan = rehearse_sales_return_posting(session, returned, actor="finance-controller")
    assert return_plan["refund_payable"] == returned.total_amount
    assert return_plan["receivable_credit"] == Decimal("0.00")
    return_post = execute_integrated_posting(session, resource_type="sales_return",
        resource_key=returned.return_key, idempotency_key=return_plan["idempotency_key"],
        actor="finance-controller")
    assert returned.credit_note.status == "posted"
    assert Decimal(stock.quantity_on_hand) == quantity_before_credit + invoice.lines[0].factor_to_base_snapshot
    return_batch = session.scalar(select(OperationalIntegratedPostingBatch).where(
        OperationalIntegratedPostingBatch.batch_key == return_post["batch_key"]))
    stock_entries = list(session.scalars(select(OperationalIntegratedStockEntry).where(
        OperationalIntegratedStockEntry.batch_id == return_batch.id)))
    assert [(entry.location_code, entry.sku, entry.quantity_delta) for entry in stock_entries] == [
        (invoice.location_code, invoice.lines[0].sku, invoice.lines[0].factor_to_base_snapshot)]
    replay = execute_integrated_posting(session, resource_type="sales_return",
        resource_key=returned.return_key, idempotency_key=return_plan["idempotency_key"],
        actor="finance-controller")
    assert replay["idempotent_replay"] is True
    assert Decimal(stock.quantity_on_hand) == quantity_before_credit + invoice.lines[0].factor_to_base_snapshot
    assert refund_available(session, returned) == Decimal("9.98")

    account = create_cash_account(session, account_code="BANK-REFUND", account_name="Refund bank",
        account_type="bank", bank_name="Bank", identifier="1234", gl_account_code="1110",
        location_code="MAIN", reason="Controlled refunds", actor="treasury-maker")
    account = decide_cash_account(session, account, action="approve", expected_revision=1,
        actor="treasury-checker", note="Verified bank account")
    refund = create_refund(session, returned=returned, cash_account_code=account.account_code,
        refund_date=invoice_date, amount=Decimal("4.00"), actor="ar-maker")
    refund = transition_refund(session, refund, expected_revision=1,
        action="submit", actor="ar-maker")
    assert refund_available(session, returned) == Decimal("5.98")
    with pytest.raises(ValueError, match="exceeds the available"):
        create_refund(session, returned=returned, cash_account_code=account.account_code,
            refund_date=invoice_date, amount=Decimal("6.00"), actor="ar-maker")
    with pytest.raises(PermissionError, match="Maker-checker"):
        transition_refund(session, refund, expected_revision=2,
            action="approve", actor="ar-maker", note="Same person")
    refund = transition_refund(session, refund, expected_revision=2,
        action="approve", actor="finance-checker", note="Verified credit liability")
    with pytest.raises(ValueError, match="bank debit"):
        refund_posting_plan(session, refund)

    statement = create_statement_batch(session, account=account,
        statement_reference="STMT-REFUND-001", statement_start=invoice_date,
        statement_end=invoice_date, opening_balance=Decimal("100"),
        closing_balance=Decimal("96"), source_file_name="synthetic-refund.csv",
        actor="treasury-maker", lines=[{"external_id": "BANK-DEBIT-REFUND-1",
            "transaction_date": invoice_date, "reference": refund.refund_no,
            "description": "Customer refund payout", "debit_amount": Decimal("4"),
            "credit_amount": Decimal("0")}])
    match_refund_statement_line(session, statement, statement.lines[0], refund,
        actor="bank-preparer")
    with pytest.raises(ValueError, match="approved bank debit|matching imported bank debit"):
        refund_posting_plan(session, refund)
    statement = transition_statement_batch(session, statement, action="submit",
        expected_revision=1, actor="treasury-maker")
    statement = transition_statement_batch(session, statement, action="approve",
        expected_revision=2, actor="bank-checker", note="Bank debit verified")
    refund_plan = refund_posting_plan(session, refund)
    assert refund_plan["journal"] == [
        {"account": "2130", "debit": Decimal("4.00"), "credit": Decimal("0.00")},
        {"account": "1110", "debit": Decimal("0.00"), "credit": Decimal("4.00")}]
    payout = execute_integrated_posting(session, resource_type="customer_refund",
        resource_key=refund.refund_key, idempotency_key=refund_plan["idempotency_key"],
        actor="treasury-poster")
    assert execute_integrated_posting(session, resource_type="customer_refund",
        resource_key=refund.refund_key, idempotency_key=refund_plan["idempotency_key"],
        actor="treasury-poster")["idempotent_replay"] is True
    assert refund.status == "posted"
    assert refund_available(session, returned) == Decimal("5.98")
    settlement = customer_invoice_settlement(session, invoice)
    assert settlement["settlement_status"] == "refund_due"
    assert settlement["refundable_amount"] == Decimal("5.98")
    assert settlement["refunded_amount"] == Decimal("4.00")
    customer_statement = build_customer_statement(session, party_code="C-1",
        party_name="Customer One", as_of=invoice_date)
    assert customer_statement["refund_total"] == Decimal("4.00")
    assert customer_statement["closing_balance"] == Decimal("-5.98")
    payout_batch = session.scalar(select(OperationalIntegratedPostingBatch).where(
        OperationalIntegratedPostingBatch.batch_key == payout["batch_key"]))
    lines = list(session.scalars(select(OperationalIntegratedJournalLine).where(
        OperationalIntegratedJournalLine.batch_id == payout_batch.id)))
    assert {(line.account_code, line.debit, line.credit) for line in lines} == {
        ("2130", Decimal("4.00"), Decimal("0.00")),
        ("1110", Decimal("0.00"), Decimal("4.00"))}
    with pytest.raises(ValueError, match="compensating receipt"):
        execute_integrated_reversal(session, payout_batch, actor="finance-controller",
            reason="Bank-confirmed payout cannot be erased")
    original_batch = session.scalar(select(OperationalIntegratedPostingBatch).where(
        OperationalIntegratedPostingBatch.batch_key == return_post["batch_key"]))
    with pytest.raises(ValueError, match="customer refund prevents"):
        execute_integrated_reversal(session, original_batch, actor="finance-controller",
            reason="Cannot orphan a posted refund")
