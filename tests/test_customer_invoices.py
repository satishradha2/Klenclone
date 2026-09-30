from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from klen_clone.customer_invoices import (
    OperationalCustomerInvoice, OperationalCustomerInvoicePostingRehearsal,
    OperationalCustomerInvoiceWorkflowEvent, create_customer_invoice,
    rehearse_customer_invoice, transition_customer_invoice,
)
from klen_clone.delivery_fulfillment import (
    OperationalDeliveryStockMovement, allocate_sales_order, transition_delivery,
)
from klen_clone.operational import (
    OperationalFiscalPeriod, OperationalJournalBatch, OperationalStockPosition,
    initialize_operational_database, make_operational_engine,
)
from klen_clone.payments import (
    OperationalPaymentPostingRehearsal, create_payment,
    customer_invoice_open_items, customer_invoice_settlement,
    rehearse_payment_posting, transition_payment,
)
from klen_clone.financial_reports import build_ageing_report, build_customer_statement
from klen_clone.models import Base as CloneBase, SourceSnapshot
from klen_clone.credit_management import customer_exposure
from klen_clone.posting_integration import (
    OperationalIntegratedPostingBatch, OperationalIntegratedJournalLine,
    OperationalIntegratedStockEntry, OperationalIntegratedSubledgerEntry,
    execute_integrated_posting, execute_integrated_reversal, posting_preview,
)
from klen_clone.sales_returns import (
    create_sales_return, rehearse_sales_return_posting, sales_return_control_counts,
    target_invoice_evidence_hash,
    target_return_cost, target_return_credit, target_return_settlement_split,
    transition_sales_return,
)
from klen_clone.sales_orders import (
    accept_sales_quotation, convert_sales_quotation, create_sales_quotation,
    transition_sales_quotation,
)
from klen_clone.vat_control import _vat_sources, create_vat_period


@pytest.fixture()
def session():
    engine = make_operational_engine("sqlite:///:memory:")
    initialize_operational_database(engine)
    with Session(engine) as value:
        value.add(OperationalFiscalPeriod(
            period_key="FY-2026", starts_on=date(2026, 1, 1), ends_on=date(2026, 12, 31),
            status="open", rehearsal_enabled=True, revision=1,
            approval_reference="customer-invoice-test", configured_by="finance"))
        value.add(OperationalStockPosition(
            location_code="MAIN", sku="SKU-1", canonical_uom="piece",
            quantity_on_hand=Decimal("10"), quantity_reserved=Decimal("0"),
            average_unit_cost=Decimal("4"), revision=1, source_batch_key="test",
            source_status="operational", availability_enabled=True))
        value.commit()
        yield value
    engine.dispose()


def delivered_order(session: Session):
    quote = create_sales_quotation(
        session, customer_code="C-1", customer_name_snapshot="Customer One",
        location_code="MAIN", quotation_date=date(2026, 9, 19),
        valid_until=date(2026, 10, 19), discount_amount=Decimal("1.00"),
        payment_terms="30 days", delivery_terms="Delivered", notes=None,
        actor="sales-maker", lines=[{
            "sku": "SKU-1", "product_name_snapshot": "Product One",
            "quantity": Decimal("2"), "uom": "Pieces", "canonical_uom": "piece",
            "factor_to_base_snapshot": Decimal("1"), "quantity_base": Decimal("2"),
            "unit_price": Decimal("10"), "tax_rate": Decimal("5"),
            "net_amount": Decimal("20"), "tax_amount": Decimal("1"),
            "gross_amount": Decimal("21"),
        }])
    quote = transition_sales_quotation(session, quote, expected_revision=1,
        action="submit", actor="sales-maker")
    quote = transition_sales_quotation(session, quote, expected_revision=2,
        action="approve", actor="sales-checker", note="Commercial approval")
    quote = accept_sales_quotation(session, quote, expected_revision=3,
        actor="sales-maker", acceptance_reference="Customer email")
    order = convert_sales_quotation(session, quote, expected_revision=4, actor="sales-maker")
    delivery = allocate_sales_order(session, order, actor="warehouse",
        note="Allocate customer order")
    delivery = transition_delivery(session, delivery, expected_revision=1, action="pick",
        actor="picker", note="Picked and checked")
    delivery = transition_delivery(session, delivery, expected_revision=2, action="dispatch",
        actor="dispatcher", note="Loaded and dispatched")
    return order, delivery


def test_partial_return_cost_allocates_every_original_issue_cent():
    portions = [target_return_cost(Decimal("0.01"), Decimal("3"), Decimal(prior), Decimal("1"))
                for prior in (0, 1, 2)]
    assert portions == [Decimal("0.00"), Decimal("0.01"), Decimal("0.00")]
    assert sum(portions) == Decimal("0.01")


def test_target_return_settlement_never_overcredits_ar_or_pays_cash():
    assert target_return_settlement_split(Decimal("19.95"), Decimal("19.95"),
        Decimal("0"), Decimal("9.98")) == {
            "receipt_amount": Decimal("19.95"), "prior_credit": Decimal("0"),
            "receivable_credit": Decimal("0.00"), "refund_payable": Decimal("9.98")}
    with pytest.raises(ValueError, match="exceed the original invoice"):
        target_return_settlement_split(Decimal("19.95"), Decimal("6"),
            Decimal("15"), Decimal("5"))


def test_invoice_requires_pod_and_copies_immutable_delivered_order(session):
    order, delivery = delivered_order(session)
    with pytest.raises(ValueError, match="delivered order"):
        create_customer_invoice(session, delivery, actor="sales-maker",
            invoice_date=date(2026, 9, 19), due_date=date(2026, 10, 19))
    delivery = transition_delivery(session, delivery, expected_revision=3, action="deliver",
        actor="pod-checker", note="Signed POD verified", received_by="Customer Receiver",
        pod_reference="POD-001")
    invoice_date = delivery.delivered_at.date()
    invoice = create_customer_invoice(session, delivery, actor="sales-maker",
        invoice_date=invoice_date, due_date=invoice_date + timedelta(days=30),
        notes="Delivery-backed test invoice")
    assert invoice.sales_order_id == order.id
    assert invoice.delivery_note_no_snapshot == delivery.delivery_note_no
    assert invoice.pod_reference_snapshot == "POD-001"
    assert invoice.customer_name_snapshot == "Customer One"
    assert invoice.total_amount == order.total_amount == Decimal("19.95")
    assert invoice.lines[0].discount_amount == order.lines[0].discount_amount == Decimal("1.00")
    assert invoice.lines[0].gross_amount == invoice.total_amount
    assert invoice.lines[0].quantity_base == delivery.lines[0].delivered_quantity_base
    assert create_customer_invoice(session, delivery, actor="sales-maker",
        invoice_date=invoice_date, due_date=invoice_date + timedelta(days=30)) is invoice
    assert session.scalar(select(func.count(OperationalCustomerInvoice.id))) == 1


def test_unallocated_legacy_order_cannot_be_invoiced(session):
    order, delivery = delivered_order(session)
    delivery = transition_delivery(session, delivery, expected_revision=3, action="deliver",
        actor="pod-checker", note="Signed POD verified", received_by="Customer Receiver",
        pod_reference="POD-LEGACY")
    order.lines[0].discount_amount = Decimal("0")
    session.commit()
    invoice_date = delivery.delivered_at.date()
    with pytest.raises(ValueError, match="do not reconcile"):
        create_customer_invoice(session, delivery, actor="sales-maker",
            invoice_date=invoice_date, due_date=invoice_date + timedelta(days=30))


def test_invoice_maker_checker_and_accounting_only_rehearsal(session):
    _, delivery = delivered_order(session)
    delivery = transition_delivery(session, delivery, expected_revision=3, action="deliver",
        actor="pod-checker", note="Signed POD verified", received_by="Customer Receiver",
        pod_reference="POD-002")
    invoice_date = delivery.delivered_at.date()
    invoice = create_customer_invoice(session, delivery, actor="sales-maker",
        invoice_date=invoice_date, due_date=invoice_date + timedelta(days=30))
    invoice = transition_customer_invoice(session, invoice, expected_revision=1,
        action="submit", actor="sales-maker", note="Ready for approval")
    with pytest.raises(PermissionError, match="Maker-checker"):
        transition_customer_invoice(session, invoice, expected_revision=2,
            action="approve", actor="sales-maker", note="Self approval")
    invoice = transition_customer_invoice(session, invoice, expected_revision=2,
        action="approve", actor="sales-manager", note="POD and totals verified")
    stock_movements_before = session.scalar(select(func.count(OperationalDeliveryStockMovement.id)))
    plan = rehearse_customer_invoice(session, invoice, actor="sales-manager")
    assert plan["debit"] == plan["credit"] == Decimal("27.95")
    assert [line["account_code"] for line in plan["journal"]] == ["1200", "4000", "2120", "5000", "1300"]
    assert plan["inventory_movements"] == []
    assert plan["stock_issue_source"] == delivery.delivery_note_no
    assert plan["posting_enabled"] is False and plan["posting_performed"] is False
    replay = rehearse_customer_invoice(session, invoice, actor="sales-manager")
    assert replay["idempotent_replay"] is True
    assert session.scalar(select(func.count(OperationalCustomerInvoicePostingRehearsal.id))) == 1
    assert session.scalar(select(func.count(OperationalDeliveryStockMovement.id))) == stock_movements_before == 1
    assert session.scalar(select(func.count(OperationalJournalBatch.id))) == 0
    assert session.scalar(select(func.count(OperationalCustomerInvoiceWorkflowEvent.id))) == 2


def test_invoice_cost_uses_dispatch_snapshot_not_later_average(session):
    _, delivery = delivered_order(session)
    movement = session.scalar(select(OperationalDeliveryStockMovement))
    assert movement.unit_cost_snapshot == Decimal("4")
    assert movement.issue_value_snapshot == Decimal("8")
    position = session.scalar(select(OperationalStockPosition))
    position.average_unit_cost = Decimal("9")
    session.commit()
    delivery = transition_delivery(session, delivery, expected_revision=3, action="deliver",
        actor="pod-checker", note="POD verified", received_by="Customer Receiver",
        pod_reference="POD-COST")
    invoice_date = delivery.delivered_at.date()
    invoice = create_customer_invoice(session, delivery, actor="sales-maker",
        invoice_date=invoice_date, due_date=invoice_date + timedelta(days=30))
    invoice = transition_customer_invoice(session, invoice, expected_revision=1,
        action="submit", actor="sales-maker")
    invoice = transition_customer_invoice(session, invoice, expected_revision=2,
        action="approve", actor="sales-checker", note="POD checked")
    plan = rehearse_customer_invoice(session, invoice, actor="finance-checker")
    assert plan["journal"][3]["debit"] == Decimal("8.00")
    assert plan["journal"][4]["credit"] == Decimal("8.00")
    assert session.scalar(select(OperationalStockPosition).where(OperationalStockPosition.sku == "SKU-1")).quantity_on_hand == 8
    movement.movement_key = "tampered-dispatch-evidence"
    session.commit()
    with pytest.raises(ValueError, match="posting evidence changed"):
        rehearse_customer_invoice(session, invoice, actor="finance-checker")


def test_legacy_unvalued_dispatch_cannot_rehearse_invoice(session):
    _, delivery = delivered_order(session)
    movement = session.scalar(select(OperationalDeliveryStockMovement))
    movement.unit_cost_snapshot = None
    movement.issue_value_snapshot = None
    session.commit()
    delivery = transition_delivery(session, delivery, expected_revision=3, action="deliver",
        actor="pod-checker", note="POD verified", received_by="Customer Receiver",
        pod_reference="POD-LEGACY-COST")
    invoice_date = delivery.delivered_at.date()
    invoice = create_customer_invoice(session, delivery, actor="sales-maker",
        invoice_date=invoice_date, due_date=invoice_date + timedelta(days=30))
    invoice = transition_customer_invoice(session, invoice, expected_revision=1,
        action="submit", actor="sales-maker")
    invoice = transition_customer_invoice(session, invoice, expected_revision=2,
        action="approve", actor="sales-checker", note="POD checked")
    with pytest.raises(ValueError, match="valuation is missing"):
        rehearse_customer_invoice(session, invoice, actor="finance-checker")


def test_zero_cost_dispatch_requires_evidence_before_invoice_rehearsal(session):
    _, delivery = delivered_order(session)
    movement = session.scalar(select(OperationalDeliveryStockMovement))
    movement.unit_cost_snapshot = Decimal("0")
    movement.issue_value_snapshot = Decimal("0")
    session.commit()
    delivery = transition_delivery(session, delivery, expected_revision=3, action="deliver",
        actor="pod-checker", note="POD verified", received_by="Customer Receiver",
        pod_reference="POD-ZERO-COST")
    invoice_date = delivery.delivered_at.date()
    invoice = create_customer_invoice(session, delivery, actor="sales-maker",
        invoice_date=invoice_date, due_date=invoice_date + timedelta(days=30))
    invoice = transition_customer_invoice(session, invoice, expected_revision=1,
        action="submit", actor="sales-maker")
    invoice = transition_customer_invoice(session, invoice, expected_revision=2,
        action="approve", actor="sales-checker", note="POD checked")
    with pytest.raises(ValueError, match="cost.*zero"):
        rehearse_customer_invoice(session, invoice, actor="finance-checker")


def test_delivery_backed_invoice_posts_accounting_once_and_reverses_without_reissuing_stock(session):
    _, delivery = delivered_order(session)
    delivery = transition_delivery(session, delivery, expected_revision=3, action="deliver",
        actor="pod-checker", note="POD verified", received_by="Customer Receiver",
        pod_reference="POD-INVOICE-POST")
    invoice_date = delivery.delivered_at.date()
    invoice = create_customer_invoice(session, delivery, actor="sales-maker",
        invoice_date=invoice_date, due_date=invoice_date + timedelta(days=30))
    invoice = transition_customer_invoice(session, invoice, expected_revision=1,
        action="submit", actor="sales-maker")
    invoice = transition_customer_invoice(session, invoice, expected_revision=2,
        action="approve", actor="sales-checker", note="POD and totals checked")
    plan = posting_preview(session, resource_type="customer_invoice",
        resource_key=invoice.invoice_key, actor="finance-controller")
    with pytest.raises(ValueError, match="maker cannot"):
        execute_integrated_posting(session, resource_type="customer_invoice",
            resource_key=invoice.invoice_key, idempotency_key=plan["idempotency_key"],
            actor="sales-maker")
    posted = execute_integrated_posting(session, resource_type="customer_invoice",
        resource_key=invoice.invoice_key, idempotency_key=plan["idempotency_key"],
        actor="finance-controller")
    session.refresh(invoice)
    assert invoice.status == "posted"
    assert posted["status"] == "posted"
    batch = session.scalar(select(OperationalIntegratedPostingBatch).where(
        OperationalIntegratedPostingBatch.batch_key == posted["batch_key"]))
    journal = list(session.scalars(select(OperationalIntegratedJournalLine).where(
        OperationalIntegratedJournalLine.batch_id == batch.id).order_by(
        OperationalIntegratedJournalLine.line_no)))
    assert [(row.account_code, row.debit, row.credit) for row in journal] == [
        ("1200", Decimal("19.95"), Decimal("0")),
        ("4000", Decimal("0"), Decimal("19")),
        ("2120", Decimal("0"), Decimal("0.95")),
        ("5000", Decimal("8"), Decimal("0")),
        ("1300", Decimal("0"), Decimal("8")),
    ]
    assert session.scalar(select(func.count(OperationalIntegratedStockEntry.id))) == 0
    subledger = session.scalar(select(OperationalIntegratedSubledgerEntry).where(
        OperationalIntegratedSubledgerEntry.batch_id == batch.id))
    assert (subledger.party_code, subledger.source_reference_key, subledger.amount) == (
        "C-1", invoice.invoice_no, Decimal("19.95"))
    assert session.scalar(select(OperationalStockPosition).where(
        OperationalStockPosition.sku == "SKU-1")).quantity_on_hand == Decimal("8")
    assert customer_invoice_open_items(session, "C-1")[0]["available_outstanding"] == Decimal("19.95")
    assert build_customer_statement(session, party_code="C-1", party_name="Customer One",
        as_of=invoice_date)["closing_balance"] == Decimal("19.95")
    assert customer_exposure(session, "C-1", as_of=invoice_date)["receivable_exposure"] == Decimal("19.95")
    replay = execute_integrated_posting(session, resource_type="customer_invoice",
        resource_key=invoice.invoice_key, idempotency_key=plan["idempotency_key"],
        actor="finance-controller")
    assert replay["idempotent_replay"] is True
    assert session.scalar(select(func.count(OperationalIntegratedPostingBatch.id))) == 1
    period = session.scalar(select(OperationalFiscalPeriod).where(OperationalFiscalPeriod.period_key == "FY-2026"))
    period.status = "locked"
    session.commit()
    with pytest.raises(ValueError, match="closed fiscal period"):
        execute_integrated_reversal(session, batch, actor="finance-controller",
            reason="Cannot reverse across a locked period")
    period = session.scalar(select(OperationalFiscalPeriod).where(OperationalFiscalPeriod.period_key == "FY-2026"))
    period.status = "open"
    session.commit()
    reversed_batch = execute_integrated_reversal(session, batch, actor="finance-controller",
        reason="Synthetic invoice reversal before receipt or return")
    session.refresh(invoice)
    assert reversed_batch["batch_kind"] == "reversal" and invoice.status == "reversed"
    assert customer_invoice_open_items(session, "C-1") == []
    assert customer_exposure(session, "C-1", as_of=invoice_date)["receivable_exposure"] == Decimal("0.00")
    assert session.scalar(select(OperationalStockPosition).where(
        OperationalStockPosition.sku == "SKU-1")).quantity_on_hand == Decimal("8")
    reversed_receipt = create_payment(session, actor="ar-maker", payment_type="customer_receipt",
        party_code="C-1", party_name_snapshot="Customer One", location_code="MAIN",
        payment_date=invoice_date, payment_method="bank_transfer",
        cash_bank_account_code="Bank - AED", reference_no="BANK-REVERSED-INVOICE",
        amount=Decimal("1"), notes=None, lines=[{
            "source_type": "invoice", "source_reference_key": invoice.invoice_no,
            "source_document_date": invoice.invoice_date,
            "source_outstanding_snapshot": invoice.total_amount,
            "allocation_amount": Decimal("1"),
        }])
    with pytest.raises(ValueError, match="not eligible for receipt allocation"):
        transition_payment(session, reversed_receipt, expected_revision=1,
            action="submit", actor="ar-maker")
    session.rollback()


def test_customer_invoice_reversal_blocked_by_receipt_allocation(session):
    _, delivery = delivered_order(session)
    delivery = transition_delivery(session, delivery, expected_revision=3, action="deliver",
        actor="pod-checker", note="POD verified", received_by="Customer Receiver",
        pod_reference="POD-INVOICE-DEPENDENCY")
    invoice_date = delivery.delivered_at.date()
    invoice = create_customer_invoice(session, delivery, actor="sales-maker",
        invoice_date=invoice_date, due_date=invoice_date + timedelta(days=30))
    invoice = transition_customer_invoice(session, invoice, expected_revision=1,
        action="submit", actor="sales-maker")
    invoice = transition_customer_invoice(session, invoice, expected_revision=2,
        action="approve", actor="sales-checker", note="POD and totals checked")
    plan = posting_preview(session, resource_type="customer_invoice",
        resource_key=invoice.invoice_key, actor="finance-controller")
    posted = execute_integrated_posting(session, resource_type="customer_invoice",
        resource_key=invoice.invoice_key, idempotency_key=plan["idempotency_key"],
        actor="finance-controller")
    receipt = create_payment(session, actor="ar-maker", payment_type="customer_receipt",
        party_code="C-1", party_name_snapshot="Customer One", location_code="MAIN",
        payment_date=invoice_date, payment_method="bank_transfer",
        cash_bank_account_code="Bank - AED", reference_no="BANK-INVOICE-DEPENDENCY",
        amount=Decimal("6"), notes=None, lines=[{
            "source_type": "invoice", "source_reference_key": invoice.invoice_no,
            "source_document_date": invoice.invoice_date,
            "source_outstanding_snapshot": invoice.total_amount,
            "allocation_amount": Decimal("6"),
        }])
    transition_payment(session, receipt, expected_revision=1, action="submit", actor="ar-maker")
    batch = session.scalar(select(OperationalIntegratedPostingBatch).where(
        OperationalIntegratedPostingBatch.batch_key == posted["batch_key"]))
    with pytest.raises(ValueError, match="receipt allocation"):
        execute_integrated_reversal(session, batch, actor="finance-controller",
            reason="Must not erase invoice under a receipt")
    session.refresh(invoice)
    assert invoice.status == "posted"
    assert customer_invoice_settlement(session, invoice)["outstanding_amount"] == Decimal("19.95")


def test_customer_invoice_reversal_blocked_by_target_return(session):
    _, delivery = delivered_order(session)
    delivery = transition_delivery(session, delivery, expected_revision=3, action="deliver",
        actor="pod-checker", note="POD verified", received_by="Customer Receiver",
        pod_reference="POD-INVOICE-RETURN")
    invoice_date = delivery.delivered_at.date()
    invoice = create_customer_invoice(session, delivery, actor="sales-maker",
        invoice_date=invoice_date, due_date=invoice_date + timedelta(days=30))
    invoice = transition_customer_invoice(session, invoice, expected_revision=1,
        action="submit", actor="sales-maker")
    invoice = transition_customer_invoice(session, invoice, expected_revision=2,
        action="approve", actor="sales-checker", note="POD and totals checked")
    plan = posting_preview(session, resource_type="customer_invoice",
        resource_key=invoice.invoice_key, actor="finance-controller")
    posted = execute_integrated_posting(session, resource_type="customer_invoice",
        resource_key=invoice.invoice_key, idempotency_key=plan["idempotency_key"],
        actor="finance-controller")
    credited_net, credited_tax = target_return_credit(invoice.lines[0], Decimal("0"), Decimal("1"))
    returned = create_sales_return(session, customer_code="C-1",
        customer_name_snapshot="Customer One", location_code="MAIN",
        original_invoice_reference=invoice.invoice_no, return_date=invoice_date,
        reason_code="customer_return", notes=None, actor="return-maker",
        original_invoice_source_record_id=0,
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
            "credit_net_amount": credited_net, "credit_tax_amount": credited_tax,
            "disposition_reason": None}])
    assert returned.status == "draft"
    batch = session.scalar(select(OperationalIntegratedPostingBatch).where(
        OperationalIntegratedPostingBatch.batch_key == posted["batch_key"]))
    with pytest.raises(ValueError, match="dependent sales return"):
        execute_integrated_reversal(session, batch, actor="finance-controller",
            reason="Must not orphan the target return")
    session.refresh(invoice)
    assert invoice.status == "posted"


def test_posted_target_invoice_two_partial_returns_recover_original_cost_and_credit(session):
    _, delivery = delivered_order(session)
    delivery = transition_delivery(session, delivery, expected_revision=3, action="deliver",
        actor="pod-checker", note="POD verified", received_by="Customer Receiver",
        pod_reference="POD-POSTED-RETURN")
    invoice_date = delivery.delivered_at.date()
    invoice = create_customer_invoice(session, delivery, actor="sales-maker",
        invoice_date=invoice_date, due_date=invoice_date + timedelta(days=30))
    invoice = transition_customer_invoice(session, invoice, expected_revision=1,
        action="submit", actor="sales-maker")
    invoice = transition_customer_invoice(session, invoice, expected_revision=2,
        action="approve", actor="sales-checker", note="POD and totals checked")
    plan = posting_preview(session, resource_type="customer_invoice",
        resource_key=invoice.invoice_key, actor="finance-controller")
    execute_integrated_posting(session, resource_type="customer_invoice",
        resource_key=invoice.invoice_key, idempotency_key=plan["idempotency_key"],
        actor="finance-controller")
    position = session.scalar(select(OperationalStockPosition).where(OperationalStockPosition.sku == "SKU-1"))
    position.average_unit_cost = Decimal("9")
    session.commit()
    returns = []
    for prior in (Decimal("0"), Decimal("1")):
        net, vat = target_return_credit(invoice.lines[0], prior, Decimal("1"))
        restock_quantity = Decimal("1") if prior == 0 else Decimal("0")
        writeoff_quantity = Decimal("0") if prior == 0 else Decimal("1")
        returned = create_sales_return(session, customer_code="C-1",
            customer_name_snapshot="Customer One", location_code="MAIN",
            original_invoice_reference=invoice.invoice_no, return_date=invoice_date,
            reason_code="customer_return", notes=None, actor="return-maker",
            original_invoice_source_record_id=0,
            original_invoice_total_snapshot=invoice.total_amount,
            original_invoice_evidence_hash=target_invoice_evidence_hash(invoice),
            original_invoice_origin="target_erp", original_invoice_target_key=invoice.invoice_key,
            lines=[{"sku": "SKU-1", "product_name_snapshot": "Product One",
                "quantity": Decimal("1"), "restock_quantity": restock_quantity,
                "writeoff_quantity": writeoff_quantity, "uom": invoice.lines[0].uom,
                "canonical_uom": invoice.lines[0].canonical_uom,
                "factor_to_base_snapshot": invoice.lines[0].factor_to_base_snapshot,
                "unit_price": invoice.lines[0].unit_price, "tax_rate": invoice.lines[0].tax_rate,
                "unit_cost_snapshot": Decimal("4"),
                "original_invoice_quantity_snapshot": invoice.lines[0].quantity,
                "original_invoice_unit_price_snapshot": invoice.lines[0].unit_price,
                "credit_net_amount": net, "credit_tax_amount": vat,
                "disposition_reason": "Damaged goods rejected by quality" if writeoff_quantity else None}])
        returned = transition_sales_return(session, returned, expected_revision=1,
            action="submit", actor="return-maker")
        returned = transition_sales_return(session, returned, expected_revision=2,
            action="approve", actor="return-checker")
        return_plan = rehearse_sales_return_posting(session, returned, actor="finance-controller")
        assert return_plan["restock_cost"] == (Decimal("4.00") if restock_quantity else Decimal("0"))
        assert return_plan["writeoff_cost"] == (Decimal("4.00") if writeoff_quantity else Decimal("0"))
        if restock_quantity:
            assert return_plan["movements"][0]["unit_cost"] == Decimal("4")
            assert return_plan["movements"][0]["value_delta"] == Decimal("4.00")
        else:
            assert return_plan["movements"] == []
        posted = execute_integrated_posting(session, resource_type="sales_return",
            resource_key=returned.return_key, idempotency_key=return_plan["idempotency_key"],
            actor="finance-controller")
        session.refresh(returned)
        assert returned.status == "posted" and returned.credit_note.status == "posted"
        batch = session.scalar(select(OperationalIntegratedPostingBatch).where(
            OperationalIntegratedPostingBatch.batch_key == posted["batch_key"]))
        subledger = session.scalar(select(OperationalIntegratedSubledgerEntry).where(
            OperationalIntegratedSubledgerEntry.batch_id == batch.id))
        assert subledger.source_type == "customer_invoice"
        assert subledger.source_reference_key == invoice.invoice_no
        assert subledger.amount == -returned.total_amount
        returns.append((returned, batch))
    assert [row[0].total_amount for row in returns] == [Decimal("9.98"), Decimal("9.97")]
    assert sum((row[0].total_amount for row in returns)) == invoice.total_amount
    session.refresh(position)
    assert position.quantity_on_hand == Decimal("9")
    assert customer_invoice_open_items(session, "C-1") == []
    assert customer_invoice_settlement(session, invoice)["outstanding_amount"] == Decimal("0.00")
    vat_period = create_vat_period(session, period_code="VAT-TARGET-RETURN-2026",
        starts_on=date(2026, 1, 1), ends_on=date(2026, 12, 31),
        due_on=date(2027, 1, 31), company_trn="100000000000003", actor="tax-maker")
    vat_rows = [row for row in _vat_sources(session, vat_period)
                if row["source_type"] in ("customer_invoice", "sales_credit_note")]
    assert sum((row["output_vat"] for row in vat_rows), Decimal("0.00")) == Decimal("0.00")
    assert sorted(row["output_vat"] for row in vat_rows if row["source_type"] == "sales_credit_note") == [
        Decimal("-0.48"), Decimal("-0.47")]
    with pytest.raises(ValueError, match="later target return"):
        execute_integrated_reversal(session, returns[0][1], actor="finance-controller",
            reason="Must preserve later partial cost allocation")
    execute_integrated_reversal(session, returns[1][1], actor="finance-controller",
        reason="Reverse synthetic written-off second return")
    assert customer_invoice_settlement(session, invoice)["outstanding_amount"] == Decimal("9.97")
    execute_integrated_reversal(session, returns[0][1], actor="finance-controller",
        reason="Reverse synthetic restocked first return")
    session.refresh(position)
    assert position.quantity_on_hand == Decimal("8")
    assert customer_invoice_settlement(session, invoice)["outstanding_amount"] == Decimal("19.95")
    assert sum((row["output_vat"] for row in _vat_sources(session, vat_period)
                if row["source_type"] in ("customer_invoice", "sales_credit_note")),
               Decimal("0.00")) == Decimal("0.95")
    original_batch = session.scalar(select(OperationalIntegratedPostingBatch).where(
        OperationalIntegratedPostingBatch.resource_type == "customer_invoice",
        OperationalIntegratedPostingBatch.resource_key == invoice.invoice_key,
        OperationalIntegratedPostingBatch.batch_kind == "posting"))
    execute_integrated_reversal(session, original_batch, actor="finance-controller",
        reason="Reverse synthetic invoice after both credits are reversed")
    session.refresh(invoice)
    assert invoice.status == "reversed"
    assert [row for row in _vat_sources(session, vat_period)
            if row["source_type"] in ("customer_invoice", "sales_credit_note")] == []


def test_invoice_rejects_dates_before_delivery_or_due_before_invoice(session):
    _, delivery = delivered_order(session)
    delivery = transition_delivery(session, delivery, expected_revision=3, action="deliver",
        actor="pod-checker", note="Signed POD verified", received_by="Customer Receiver",
        pod_reference="POD-003")
    delivery.delivered_at = delivery.delivered_at.replace(year=2026, month=9, day=19)
    session.commit()
    with pytest.raises(ValueError, match="earlier than the proof"):
        create_customer_invoice(session, delivery, actor="sales-maker",
            invoice_date=date(2026, 9, 18), due_date=date(2026, 10, 18))
    with pytest.raises(ValueError, match="due date"):
        create_customer_invoice(session, delivery, actor="sales-maker",
            invoice_date=date(2026, 9, 19), due_date=date(2026, 9, 18))


def test_approved_invoice_becomes_receivable_and_partial_receipt_reduces_outstanding(session):
    _, delivery = delivered_order(session)
    delivery = transition_delivery(session, delivery, expected_revision=3, action="deliver",
        actor="pod-checker", note="Signed POD verified", received_by="Customer Receiver",
        pod_reference="POD-AR-001")
    invoice_date = delivery.delivered_at.date()
    invoice = create_customer_invoice(session, delivery, actor="sales-maker",
        invoice_date=invoice_date, due_date=invoice_date + timedelta(days=30))
    invoice = transition_customer_invoice(session, invoice, expected_revision=1,
        action="submit", actor="sales-maker", note="Ready for approval")
    invoice = transition_customer_invoice(session, invoice, expected_revision=2,
        action="approve", actor="sales-manager", note="POD and totals verified")
    open_items = customer_invoice_open_items(session, "C-1")
    assert len(open_items) == 1
    assert open_items[0]["source_reference_key"] == invoice.invoice_no
    assert open_items[0]["available_outstanding"] == Decimal("19.95")
    assert open_items[0]["source_origin"] == "target_erp"

    receipt = create_payment(session, actor="ar-maker", payment_type="customer_receipt",
        party_code="C-1", party_name_snapshot="Customer One", location_code="MAIN",
        payment_date=invoice_date, payment_method="bank_transfer",
        cash_bank_account_code="Bank - AED", reference_no="BANK-AR-001",
        amount=Decimal("6.00"), notes="Partial customer receipt", lines=[{
            "source_type": "invoice", "source_reference_key": invoice.invoice_no,
            "source_document_date": invoice.invoice_date,
            "source_outstanding_snapshot": invoice.total_amount,
            "allocation_amount": Decimal("6.00"),
        }])
    receipt = transition_payment(session, receipt, expected_revision=1,
        action="submit", actor="ar-maker", note="Bank receipt matched")
    receipt = transition_payment(session, receipt, expected_revision=2,
        action="approve", actor="finance-approver", note="Receipt evidence verified")
    plan = rehearse_payment_posting(session, receipt, actor="finance-approver")
    assert plan["debit"] == plan["credit"] == Decimal("6.00")
    assert plan["posting_enabled"] is False
    assert session.scalar(select(func.count(OperationalPaymentPostingRehearsal.id))) == 1
    remaining = customer_invoice_open_items(session, "C-1")
    assert remaining[0]["available_outstanding"] == Decimal("13.95")
    assert customer_invoice_settlement(session, invoice) == {
        "settlement_status": "partially_paid",
        "paid_amount": Decimal("6.00"),
        "pending_allocation_amount": Decimal("0.00"),
        "outstanding_amount": Decimal("13.95"),
        "available_outstanding": Decimal("13.95"),
    }

    excess = create_payment(session, actor="ar-maker", payment_type="customer_receipt",
        party_code="C-1", party_name_snapshot="Customer One", location_code="MAIN",
        payment_date=invoice_date, payment_method="cash",
        cash_bank_account_code="Cash - AED", reference_no=None,
        amount=Decimal("15.00"), notes="Excess allocation test", lines=[{
            "source_type": "invoice", "source_reference_key": invoice.invoice_no,
            "source_document_date": invoice.invoice_date,
            "source_outstanding_snapshot": invoice.total_amount,
            "allocation_amount": Decimal("15.00"),
        }])
    with pytest.raises(ValueError, match="remaining outstanding"):
        transition_payment(session, excess, expected_revision=1,
            action="submit", actor="ar-maker", note="Must not over-allocate")
    session.rollback()

    final_receipt = create_payment(session, actor="ar-maker", payment_type="customer_receipt",
        party_code="C-1", party_name_snapshot="Customer One", location_code="MAIN",
        payment_date=invoice_date, payment_method="cash",
        cash_bank_account_code="Cash - AED", reference_no=None,
        amount=Decimal("13.95"), notes="Final customer receipt", lines=[{
            "source_type": "invoice", "source_reference_key": invoice.invoice_no,
            "source_document_date": invoice.invoice_date,
            "source_outstanding_snapshot": invoice.total_amount,
            "allocation_amount": Decimal("13.95"),
        }])
    final_receipt = transition_payment(session, final_receipt, expected_revision=1,
        action="submit", actor="ar-maker", note="Final allocation")
    final_receipt = transition_payment(session, final_receipt, expected_revision=2,
        action="approve", actor="finance-approver", note="Receipt verified")
    assert customer_invoice_settlement(session, invoice)["settlement_status"] == "paid"
    assert customer_invoice_settlement(session, invoice)["outstanding_amount"] == Decimal("0.00")
    assert customer_invoice_open_items(session, "C-1") == []
    statement = build_customer_statement(session, party_code="C-1",
        party_name="Customer One", as_of=invoice_date)
    assert statement["invoice_total"] == statement["receipt_total"] == Decimal("19.95")
    assert statement["closing_balance"] == Decimal("0.00")
    assert [row["entry_type"] for row in statement["entries"]] == [
        "customer_invoice", "customer_receipt", "customer_receipt"]


def test_posted_partial_receipt_stays_in_settlement_statement_and_exposure(session):
    _, delivery = delivered_order(session)
    delivery = transition_delivery(session, delivery, expected_revision=3, action="deliver",
        actor="pod-checker", note="Signed POD verified", received_by="Customer Receiver",
        pod_reference="POD-POSTED-AR")
    invoice_date = delivery.delivered_at.date()
    invoice = create_customer_invoice(session, delivery, actor="sales-maker",
        invoice_date=invoice_date, due_date=invoice_date + timedelta(days=30))
    invoice = transition_customer_invoice(session, invoice, expected_revision=1,
        action="submit", actor="sales-maker")
    invoice = transition_customer_invoice(session, invoice, expected_revision=2,
        action="approve", actor="sales-manager", note="POD and totals verified")
    receipt_date = invoice_date + timedelta(days=1)
    receipt = create_payment(session, actor="ar-maker", payment_type="customer_receipt",
        party_code="C-1", party_name_snapshot="Customer One", location_code="MAIN",
        payment_date=receipt_date, payment_method="bank_transfer",
        cash_bank_account_code="Bank - AED", reference_no="BANK-POSTED-AR",
        amount=Decimal("6.00"), notes=None, lines=[{
            "source_type": "invoice", "source_reference_key": invoice.invoice_no,
            "source_document_date": invoice.invoice_date,
            "source_outstanding_snapshot": invoice.total_amount,
            "allocation_amount": Decimal("6.00"),
        }])
    receipt = transition_payment(session, receipt, expected_revision=1,
        action="submit", actor="ar-maker")
    receipt = transition_payment(session, receipt, expected_revision=2,
        action="approve", actor="finance-approver")
    plan = rehearse_payment_posting(session, receipt, actor="finance-approver")
    posted = execute_integrated_posting(session, resource_type="payment", resource_key=receipt.payment_key,
        idempotency_key=plan["idempotency_key"], actor="finance-approver")
    session.refresh(receipt)
    assert receipt.status == "posted"
    settlement = customer_invoice_settlement(session, invoice)
    assert settlement["paid_amount"] == Decimal("6.00")
    assert settlement["outstanding_amount"] == Decimal("13.95")
    assert customer_invoice_open_items(session, "C-1")[0]["available_outstanding"] == Decimal("13.95")
    statement = build_customer_statement(session, party_code="C-1",
        party_name="Customer One", as_of=receipt_date)
    assert statement["receipt_total"] == Decimal("6.00")
    assert statement["closing_balance"] == Decimal("13.95")
    assert statement["entries"][-1]["settlement_status"] == "posted"
    assert customer_exposure(session, "C-1", as_of=receipt_date)["receivable_exposure"] == Decimal("13.95")
    before_receipt = build_customer_statement(session, party_code="C-1",
        party_name="Customer One", as_of=invoice_date)
    assert before_receipt["receipt_total"] == Decimal("0.00")
    assert before_receipt["closing_balance"] == Decimal("19.95")
    assert before_receipt["entries"][0]["paid_amount"] == Decimal("0.00")
    excessive = create_payment(session, actor="ar-maker", payment_type="customer_receipt",
        party_code="C-1", party_name_snapshot="Customer One", location_code="MAIN",
        payment_date=receipt_date, payment_method="cash", cash_bank_account_code="Cash - AED",
        reference_no=None, amount=Decimal("14.00"), notes=None, lines=[{
            "source_type": "invoice", "source_reference_key": invoice.invoice_no,
            "source_document_date": invoice.invoice_date,
            "source_outstanding_snapshot": invoice.total_amount,
            "allocation_amount": Decimal("14.00"),
        }])
    with pytest.raises(ValueError, match="remaining outstanding"):
        transition_payment(session, excessive, expected_revision=1,
            action="submit", actor="ar-maker")
    session.rollback()
    batch = session.scalar(select(OperationalIntegratedPostingBatch).where(
        OperationalIntegratedPostingBatch.batch_key == posted["batch_key"]))
    execute_integrated_reversal(session, batch, actor="finance-controller",
        reason="Synthetic receipt reversal test")
    assert customer_invoice_settlement(session, invoice)["outstanding_amount"] == Decimal("19.95")
    reversed_statement = build_customer_statement(session, party_code="C-1",
        party_name="Customer One", as_of=receipt_date)
    assert reversed_statement["receipt_total"] == Decimal("0.00")
    assert reversed_statement["closing_balance"] == Decimal("19.95")


def test_target_invoice_partial_credits_conserve_discounted_net_and_vat(session):
    _, delivery = delivered_order(session)
    delivery = transition_delivery(session, delivery, expected_revision=3, action="deliver",
        actor="pod-checker", note="Signed POD verified", received_by="Customer Receiver",
        pod_reference="POD-TARGET-RETURN")
    invoice_date = delivery.delivered_at.date()
    invoice = create_customer_invoice(session, delivery, actor="sales-maker",
        invoice_date=invoice_date, due_date=invoice_date + timedelta(days=30))
    invoice = transition_customer_invoice(session, invoice, expected_revision=1,
        action="submit", actor="sales-maker")
    invoice = transition_customer_invoice(session, invoice, expected_revision=2,
        action="approve", actor="sales-manager", note="POD and totals verified")
    assert invoice.total_amount == Decimal("19.95")
    amounts = []
    for prior in (Decimal("0"), Decimal("1")):
        credited_net, credited_tax = target_return_credit(invoice.lines[0], prior, Decimal("1"))
        returned = create_sales_return(session, customer_code="C-1",
            customer_name_snapshot="Customer One", location_code="MAIN",
            original_invoice_reference=invoice.invoice_no, return_date=invoice_date,
            reason_code="customer_return", notes=None, actor="return-maker",
            original_invoice_source_record_id=0,
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
                "credit_net_amount": credited_net, "credit_tax_amount": credited_tax,
                "disposition_reason": None}])
        returned = transition_sales_return(session, returned, expected_revision=1,
            action="submit", actor="return-maker")
        returned = transition_sales_return(session, returned, expected_revision=2,
            action="approve", actor="return-checker")
        with pytest.raises(ValueError, match="posting is held"):
            rehearse_sales_return_posting(session, returned, actor="return-checker")
        amounts.append((returned.subtotal, returned.tax_amount, returned.total_amount))
        if prior == 0:
            assert customer_invoice_open_items(session, "C-1")[0]["available_outstanding"] == Decimal("9.97")
            excessive = create_payment(session, actor="ar-maker", payment_type="customer_receipt",
                party_code="C-1", party_name_snapshot="Customer One", location_code="MAIN",
                payment_date=invoice_date, payment_method="cash", cash_bank_account_code="Cash - AED",
                reference_no=None, amount=Decimal("9.98"), notes=None, lines=[{
                    "source_type": "invoice", "source_reference_key": invoice.invoice_no,
                    "source_document_date": invoice.invoice_date,
                    "source_outstanding_snapshot": invoice.total_amount,
                    "allocation_amount": Decimal("9.98"),
                }])
            with pytest.raises(ValueError, match="remaining outstanding"):
                transition_payment(session, excessive, expected_revision=1,
                    action="submit", actor="ar-maker")
            session.rollback()
    assert amounts == [(Decimal("9.50"), Decimal("0.48"), Decimal("9.98")),
                       (Decimal("9.50"), Decimal("0.47"), Decimal("9.97"))]
    assert customer_invoice_settlement(session, invoice)["outstanding_amount"] == Decimal("0.00")
    assert customer_invoice_open_items(session, "C-1") == []
    statement = build_customer_statement(session, party_code="C-1",
        party_name="Customer One", as_of=invoice_date)
    assert statement["invoice_total"] == statement["credit_total"] == Decimal("19.95")
    assert statement["closing_balance"] == Decimal("0.00")
    assert customer_exposure(session, "C-1", as_of=invoice_date)["receivable_exposure"] == Decimal("0.00")
    CloneBase.metadata.create_all(session.bind)
    snapshot = SourceSnapshot(name="synthetic-return-report", source_system="synthetic",
        source_url="https://example.invalid", is_atomic=False)
    session.add(snapshot)
    session.commit()
    ageing = build_ageing_report(session, session, snapshot_id=snapshot.id,
        ledger_kind="receivable", as_of=invoice_date)
    row = next(item for item in ageing["items"] if item["party_code"] == "C-1")
    assert row["target_erp_invoiced"] == row["target_erp_credited"] == Decimal("19.95")
    assert row["control_outstanding"] == row["invoice_evidence_outstanding"] == Decimal("0.00")


def test_posted_receipt_and_target_credit_reconcile_without_implicit_refund(session):
    _, delivery = delivered_order(session)
    delivery = transition_delivery(session, delivery, expected_revision=3, action="deliver",
        actor="pod-checker", note="Signed POD verified", received_by="Customer Receiver",
        pod_reference="POD-RECEIPT-RETURN")
    invoice_date = delivery.delivered_at.date()
    invoice = create_customer_invoice(session, delivery, actor="sales-maker",
        invoice_date=invoice_date, due_date=invoice_date + timedelta(days=30))
    invoice = transition_customer_invoice(session, invoice, expected_revision=1,
        action="submit", actor="sales-maker")
    invoice = transition_customer_invoice(session, invoice, expected_revision=2,
        action="approve", actor="sales-manager", note="POD and totals verified")
    invoice_plan = posting_preview(session, resource_type="customer_invoice",
        resource_key=invoice.invoice_key, actor="finance-controller")
    execute_integrated_posting(session, resource_type="customer_invoice",
        resource_key=invoice.invoice_key, idempotency_key=invoice_plan["idempotency_key"],
        actor="finance-controller")
    receipt = create_payment(session, actor="ar-maker", payment_type="customer_receipt",
        party_code="C-1", party_name_snapshot="Customer One", location_code="MAIN",
        payment_date=invoice_date, payment_method="bank_transfer",
        cash_bank_account_code="Bank - AED", reference_no="BANK-RETURN-001",
        amount=Decimal("6.00"), notes=None, lines=[{
            "source_type": "invoice", "source_reference_key": invoice.invoice_no,
            "source_document_date": invoice.invoice_date,
            "source_outstanding_snapshot": invoice.total_amount,
            "allocation_amount": Decimal("6.00"),
        }])
    receipt = transition_payment(session, receipt, expected_revision=1,
        action="submit", actor="ar-maker")
    receipt = transition_payment(session, receipt, expected_revision=2,
        action="approve", actor="finance-approver")
    plan = rehearse_payment_posting(session, receipt, actor="finance-approver")
    receipt_posted = execute_integrated_posting(session, resource_type="payment", resource_key=receipt.payment_key,
        idempotency_key=plan["idempotency_key"], actor="finance-approver")

    def make_return(prior):
        net, tax = target_return_credit(invoice.lines[0], Decimal(prior), Decimal("1"))
        return create_sales_return(session, customer_code="C-1",
            customer_name_snapshot="Customer One", location_code="MAIN",
            original_invoice_reference=invoice.invoice_no, return_date=invoice_date,
            reason_code="customer_return", notes=None, actor="return-maker",
            original_invoice_source_record_id=0,
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

    returned = make_return("0")
    returned = transition_sales_return(session, returned, expected_revision=1,
        action="submit", actor="return-maker")
    transition_sales_return(session, returned, expected_revision=2,
        action="approve", actor="return-checker")
    first_plan = rehearse_sales_return_posting(session, returned, actor="finance-controller")
    assert first_plan["receivable_credit"] == Decimal("9.98")
    assert first_plan["refund_payable"] == Decimal("0.00")
    execute_integrated_posting(session, resource_type="sales_return",
        resource_key=returned.return_key, idempotency_key=first_plan["idempotency_key"],
        actor="finance-controller")
    assert customer_invoice_settlement(session, invoice)["outstanding_amount"] == Decimal("3.97")
    assert customer_invoice_open_items(session, "C-1")[0]["available_outstanding"] == Decimal("3.97")
    statement = build_customer_statement(session, party_code="C-1",
        party_name="Customer One", as_of=invoice_date)
    assert (statement["invoice_total"], statement["credit_total"],
            statement["receipt_total"], statement["closing_balance"]) == (
                Decimal("19.95"), Decimal("9.98"), Decimal("6.00"), Decimal("3.97"))
    assert customer_exposure(session, "C-1", as_of=invoice_date)["receivable_exposure"] == Decimal("3.97")
    stock = session.scalar(select(OperationalStockPosition).where(
        OperationalStockPosition.location_code == "MAIN", OperationalStockPosition.sku == "SKU-1"))
    assert stock.quantity_on_hand == Decimal("9")  # Only the posted first credit has restocked.
    excessive = make_return("1")
    excessive = transition_sales_return(session, excessive, expected_revision=1,
        action="submit", actor="return-maker")
    excessive = transition_sales_return(session, excessive, expected_revision=2,
        action="approve", actor="return-checker")
    refund_plan = rehearse_sales_return_posting(session, excessive, actor="finance-controller")
    assert refund_plan["receivable_credit"] == Decimal("3.97")
    assert refund_plan["refund_payable"] == Decimal("6.00")
    assert sum((row["credit"] for row in refund_plan["journal"]), Decimal("0")) == refund_plan["debit"]
    posted_refund = execute_integrated_posting(session, resource_type="sales_return",
        resource_key=excessive.return_key, idempotency_key=refund_plan["idempotency_key"],
        actor="finance-controller")
    refund_batch = session.scalar(select(OperationalIntegratedPostingBatch).where(
        OperationalIntegratedPostingBatch.batch_key == posted_refund["batch_key"]))
    subledgers = list(session.scalars(select(OperationalIntegratedSubledgerEntry).where(
        OperationalIntegratedSubledgerEntry.batch_id == refund_batch.id).order_by(
        OperationalIntegratedSubledgerEntry.line_no)))
    assert [(row.entry_type, row.amount) for row in subledgers] == [
        ("receivable_credit", Decimal("-3.97")),
        ("customer_refund_payable", Decimal("6.00"))]
    settlement = customer_invoice_settlement(session, invoice)
    assert settlement["outstanding_amount"] == Decimal("0.00")
    assert settlement["settlement_status"] == "refund_due"
    assert settlement["refundable_amount"] == Decimal("6.00")
    assert sales_return_control_counts(session)["refund_payable"] == Decimal("6.00")
    receipt_batch = session.scalar(select(OperationalIntegratedPostingBatch).where(
        OperationalIntegratedPostingBatch.batch_key == receipt_posted["batch_key"]))
    with pytest.raises(ValueError, match="posted target return depends on this receipt"):
        execute_integrated_reversal(session, receipt_batch, actor="finance-controller",
            reason="Must reverse dependent credits first")
    execute_integrated_reversal(session, refund_batch, actor="finance-controller",
        reason="Reverse synthetic refund liability and restock")
    assert sales_return_control_counts(session)["refund_payable"] == Decimal("0.00")
    assert customer_invoice_settlement(session, invoice)["outstanding_amount"] == Decimal("3.97")


def test_target_return_posting_waits_for_pending_receipt(session):
    _, delivery = delivered_order(session)
    delivery = transition_delivery(session, delivery, expected_revision=3, action="deliver",
        actor="pod-checker", note="POD verified", received_by="Customer Receiver",
        pod_reference="POD-PENDING-REFUND")
    invoice_date = delivery.delivered_at.date()
    invoice = create_customer_invoice(session, delivery, actor="sales-maker",
        invoice_date=invoice_date, due_date=invoice_date + timedelta(days=30))
    invoice = transition_customer_invoice(session, invoice, expected_revision=1,
        action="submit", actor="sales-maker")
    invoice = transition_customer_invoice(session, invoice, expected_revision=2,
        action="approve", actor="sales-manager", note="POD and totals verified")
    invoice_plan = posting_preview(session, resource_type="customer_invoice",
        resource_key=invoice.invoice_key, actor="finance-controller")
    execute_integrated_posting(session, resource_type="customer_invoice",
        resource_key=invoice.invoice_key, idempotency_key=invoice_plan["idempotency_key"],
        actor="finance-controller")
    receipt = create_payment(session, actor="ar-maker", payment_type="customer_receipt",
        party_code="C-1", party_name_snapshot="Customer One", location_code="MAIN",
        payment_date=invoice_date, payment_method="bank_transfer",
        cash_bank_account_code="Bank - AED", reference_no="BANK-PENDING-REFUND",
        amount=Decimal("6.00"), notes=None, lines=[{
            "source_type": "invoice", "source_reference_key": invoice.invoice_no,
            "source_document_date": invoice.invoice_date,
            "source_outstanding_snapshot": invoice.total_amount,
            "allocation_amount": Decimal("6.00")}])
    receipt = transition_payment(session, receipt, expected_revision=1,
        action="submit", actor="ar-maker")
    receipt = transition_payment(session, receipt, expected_revision=2,
        action="approve", actor="finance-approver")
    net, tax = target_return_credit(invoice.lines[0], Decimal("0"), Decimal("1"))
    returned = create_sales_return(session, customer_code="C-1",
        customer_name_snapshot="Customer One", location_code="MAIN",
        original_invoice_reference=invoice.invoice_no, return_date=invoice_date,
        reason_code="customer_return", notes=None, actor="return-maker",
        original_invoice_source_record_id=0,
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
    with pytest.raises(ValueError, match="Pending customer receipt allocations"):
        rehearse_sales_return_posting(session, returned, actor="finance-controller")
    session.rollback()
    receipt_plan = rehearse_payment_posting(session, receipt, actor="finance-approver")
    execute_integrated_posting(session, resource_type="payment", resource_key=receipt.payment_key,
        idempotency_key=receipt_plan["idempotency_key"], actor="finance-approver")
    assert rehearse_sales_return_posting(session, returned, actor="finance-controller")[
        "receivable_credit"] == Decimal("9.98")
