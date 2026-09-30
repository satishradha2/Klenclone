from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from klen_clone.cash_management import (create_cash_account, create_statement_batch,
    decide_cash_account, match_recovery_statement_line,
    match_refund_statement_line, transition_statement_batch)
from klen_clone.customer_invoices import create_customer_invoice, transition_customer_invoice
from klen_clone.customer_price_credits import (create_price_credit, price_credit_posting_plan,
    transition_price_credit)
from klen_clone.customer_refunds import (create_recovery, create_refund,
    recovery_posting_plan, refund_available, refund_posting_plan,
    transition_recovery, transition_refund)
from klen_clone.delivery_fulfillment import transition_delivery
from klen_clone.financial_reports import build_customer_statement
from klen_clone.operational import OperationalStockPosition
from klen_clone.payments import (create_payment, customer_invoice_settlement,
    rehearse_payment_posting, transition_payment)
from klen_clone.posting_integration import (OperationalIntegratedPostingBatch,
    OperationalIntegratedStockEntry, execute_integrated_posting, posting_preview)
from test_customer_invoices import delivered_order, session


def test_no_stock_price_credit_can_be_paid_and_traced(session):
    _, delivery = delivered_order(session)
    delivery = transition_delivery(session, delivery, expected_revision=3, action="deliver",
        actor="pod-checker", note="POD verified", received_by="Customer Receiver",
        pod_reference="POD-PRICE-CREDIT")
    today = delivery.delivered_at.date()
    invoice = create_customer_invoice(session, delivery, actor="sales-maker",
        invoice_date=today, due_date=today + timedelta(days=30))
    invoice = transition_customer_invoice(session, invoice, expected_revision=1,
        action="submit", actor="sales-maker")
    invoice = transition_customer_invoice(session, invoice, expected_revision=2,
        action="approve", actor="sales-checker", note="Verified invoice")
    plan = posting_preview(session, resource_type="customer_invoice",
        resource_key=invoice.invoice_key, actor="finance-poster")
    execute_integrated_posting(session, resource_type="customer_invoice",
        resource_key=invoice.invoice_key, idempotency_key=plan["idempotency_key"],
        actor="finance-poster")
    receipt = create_payment(session, actor="ar-maker", payment_type="customer_receipt",
        party_code=invoice.customer_code, party_name_snapshot=invoice.customer_name_snapshot,
        location_code=invoice.location_code, payment_date=today,
        payment_method="bank_transfer", cash_bank_account_code="Bank - AED",
        reference_no="PRICE-CREDIT-RECEIPT", amount=invoice.total_amount,
        notes=None, lines=[{"source_type": "invoice", "source_reference_key": invoice.invoice_no,
            "source_document_date": invoice.invoice_date,
            "source_outstanding_snapshot": invoice.total_amount,
            "allocation_amount": invoice.total_amount}])
    receipt = transition_payment(session, receipt, expected_revision=1,
        action="submit", actor="ar-maker")
    receipt = transition_payment(session, receipt, expected_revision=2,
        action="approve", actor="finance-checker")
    receipt_plan = rehearse_payment_posting(session, receipt, actor="finance-checker")
    execute_integrated_posting(session, resource_type="payment",
        resource_key=receipt.payment_key, idempotency_key=receipt_plan["idempotency_key"],
        actor="finance-checker")
    original_effective = ((Decimal(invoice.lines[0].net_amount) -
        Decimal(invoice.lines[0].discount_amount)) / Decimal(invoice.lines[0].quantity))
    corrected = (original_effective / 2).quantize(Decimal("0.0001"))
    credit = create_price_credit(session, invoice=invoice, line_no=invoice.lines[0].line_no,
        credit_date=today, quantity=invoice.lines[0].quantity,
        corrected_unit_net=corrected, reason="Approved customer price reduction",
        actor="credit-maker")
    credit = transition_price_credit(session, credit, expected_revision=1,
        action="submit", actor="credit-maker")
    with pytest.raises(PermissionError, match="self-approval"):
        transition_price_credit(session, credit, expected_revision=2,
            action="approve", actor="credit-maker", note="Own credit")
    credit = transition_price_credit(session, credit, expected_revision=2,
        action="approve", actor="finance-checker", note="Invoice price evidence verified")
    credit_plan = price_credit_posting_plan(session, credit)
    assert credit_plan["movements"] == []
    assert credit_plan["refund_payable"] == credit.total_amount
    assert credit_plan["receivable_credit"] == 0
    assert {row["account"] for row in credit_plan["journal"]} == {"4010", "2120", "1200", "2130"}
    stock = session.scalar(select(OperationalStockPosition).where(
        OperationalStockPosition.location_code == invoice.location_code,
        OperationalStockPosition.sku == invoice.lines[0].sku))
    stock_before = Decimal(stock.quantity_on_hand)
    credit_post = execute_integrated_posting(session, resource_type="customer_price_credit",
        resource_key=credit.credit_key, idempotency_key=credit_plan["idempotency_key"],
        actor="treasury-poster")
    credit_batch = session.scalar(select(OperationalIntegratedPostingBatch).where(
        OperationalIntegratedPostingBatch.batch_key == credit_post["batch_key"]))
    assert Decimal(stock.quantity_on_hand) == stock_before
    assert list(session.scalars(select(OperationalIntegratedStockEntry).where(
        OperationalIntegratedStockEntry.batch_id == credit_batch.id))) == []
    duplicate = create_price_credit(session, invoice=invoice,
        line_no=invoice.lines[0].line_no, credit_date=today,
        quantity=invoice.lines[0].quantity,
        corrected_unit_net=corrected, reason="Duplicate discount attempt",
        actor="credit-maker")
    with pytest.raises(ValueError, match="Cumulative credits|already has an active pricing correction"):
        transition_price_credit(session, duplicate, expected_revision=1,
            action="submit", actor="credit-maker")
    assert refund_available(session, credit) == credit.total_amount
    account = create_cash_account(session, account_code="BANK-PRICE", account_name="Bank",
        account_type="bank", bank_name="Bank", identifier="1234", gl_account_code="1110",
        location_code="MAIN", reason="Price credit refund", actor="treasury-maker")
    account = decide_cash_account(session, account, action="approve", expected_revision=1,
        actor="treasury-checker", note="Bank verified")
    refund = create_refund(session, price_credit=credit, cash_account_code=account.account_code,
        refund_date=today, amount=credit.total_amount, actor="ar-maker")
    refund = transition_refund(session, refund, expected_revision=1,
        action="submit", actor="ar-maker")
    refund = transition_refund(session, refund, expected_revision=2,
        action="approve", actor="finance-checker", note="Price credit payable verified")
    statement = create_statement_batch(session, account=account,
        statement_reference="PRICE-CREDIT-BANK", statement_start=today, statement_end=today,
        opening_balance=Decimal("100"), closing_balance=Decimal("100")-credit.total_amount,
        source_file_name="synthetic-price-refund.csv", actor="treasury-maker",
        lines=[{"external_id": "PRICE-CREDIT-DEBIT", "transaction_date": today,
            "reference": refund.refund_no, "description": "Price credit refund",
            "debit_amount": credit.total_amount, "credit_amount": Decimal("0")}])
    match_refund_statement_line(session, statement, statement.lines[0], refund,
        actor="bank-preparer")
    statement = transition_statement_batch(session, statement, action="submit",
        expected_revision=1, actor="treasury-maker")
    transition_statement_batch(session, statement, action="approve",
        expected_revision=2, actor="bank-checker", note="Debit verified")
    payout = refund_posting_plan(session, refund)
    execute_integrated_posting(session, resource_type="customer_refund",
        resource_key=refund.refund_key, idempotency_key=payout["idempotency_key"],
        actor="treasury-poster")
    settlement = customer_invoice_settlement(session, invoice)
    assert settlement["refunded_amount"] == credit.total_amount
    assert settlement["settlement_status"] == "refunded"
    statement = build_customer_statement(session, party_code=invoice.customer_code,
        party_name=invoice.customer_name_snapshot, as_of=today)
    assert statement["refund_total"] == credit.total_amount
    assert statement["credit_total"] == credit.total_amount
    assert statement["closing_balance"] == Decimal("0.00")
    recovery = create_recovery(session, refund=refund, recovery_date=today,
        amount=Decimal("1.00"), reason="Customer repaid part of the bank refund",
        actor="ar-maker")
    recovery = transition_recovery(session, recovery, expected_revision=1,
        action="submit", actor="ar-maker")
    with pytest.raises(PermissionError, match="self-approval"):
        transition_recovery(session, recovery, expected_revision=2,
            action="approve", actor="ar-maker", note="Own recovery")
    recovery = transition_recovery(session, recovery, expected_revision=2,
        action="approve", actor="finance-checker", note="Bank repayment evidence verified")
    with pytest.raises(ValueError, match="bank credit"):
        recovery_posting_plan(session, recovery)
    credit_statement = create_statement_batch(session, account=account,
        statement_reference="PRICE-CREDIT-RECOVERY-BANK",
        statement_start=today, statement_end=today,
        opening_balance=Decimal("100"), closing_balance=Decimal("101"),
        source_file_name="synthetic-recovery.csv", actor="treasury-maker",
        lines=[{"external_id": "RECOVERY-CREDIT", "transaction_date": today,
            "reference": recovery.recovery_no, "description": "Refund repayment",
            "debit_amount": Decimal("0"), "credit_amount": Decimal("1.00")}])
    match_recovery_statement_line(session, credit_statement, credit_statement.lines[0],
        recovery, actor="bank-preparer")
    with pytest.raises(ValueError, match="approved matching bank credit"):
        recovery_posting_plan(session, recovery)
    credit_statement = transition_statement_batch(session, credit_statement,
        action="submit", expected_revision=1, actor="treasury-maker")
    transition_statement_batch(session, credit_statement, action="approve",
        expected_revision=2, actor="bank-checker", note="Bank credit verified")
    recovery_plan = recovery_posting_plan(session, recovery)
    assert recovery_plan["journal"] == [
        {"account": "1110", "debit": Decimal("1.00"), "credit": Decimal("0")},
        {"account": "2130", "debit": Decimal("0"), "credit": Decimal("1.00")}]
    receipt_post = execute_integrated_posting(session, resource_type="customer_refund_recovery",
        resource_key=recovery.recovery_key,
        idempotency_key=recovery_plan["idempotency_key"], actor="treasury-poster")
    assert execute_integrated_posting(session, resource_type="customer_refund_recovery",
        resource_key=recovery.recovery_key,
        idempotency_key=recovery_plan["idempotency_key"],
        actor="treasury-poster")["idempotent_replay"] is True
    assert receipt_post["status"] == "posted"
    with pytest.raises(ValueError, match="unrecovered payout"):
        create_recovery(session, refund=refund, recovery_date=today,
            amount=credit.total_amount, reason="Duplicate recovery attempt",
            actor="ar-maker")
    assert refund_available(session, credit) == Decimal("1.00")
    assert customer_invoice_settlement(session, invoice)["refundable_amount"] == Decimal("1.00")
    final_statement = build_customer_statement(session, party_code=invoice.customer_code,
        party_name=invoice.customer_name_snapshot, as_of=today)
    assert final_statement["recovery_total"] == Decimal("1.00")
    assert final_statement["closing_balance"] == Decimal("-1.00")
