from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from klen_clone.goods_receipts import create_goods_receipt, transition_goods_receipt
from klen_clone.operational import OperationalFiscalPeriod, initialize_operational_database, make_operational_engine
from klen_clone.payments import create_payment, transition_payment
from klen_clone.posting_integration import (
    OperationalIntegratedJournalLine, OperationalIntegratedPostingBatch,
    OperationalIntegratedSubledgerEntry, execute_integrated_posting,
    execute_integrated_reversal,
)
from klen_clone.procurement import OperationalPurchaseOrder, OperationalPurchaseOrderLine
from klen_clone.procurement_matching import (
    approve_invoice_tolerance, create_supplier_adjustment, create_supplier_invoice,
    decide_policy_change, decide_supplier_invoice, evaluate_invoice_match, match_policy,
    rehearse_supplier_adjustment_posting, rehearse_supplier_invoice_posting,
    request_policy_change, transition_supplier_adjustment,
    validate_po_receipt,
)
from klen_clone.purchase_returns import create_purchase_return


def matching_session(tmp_path) -> tuple[Session, OperationalPurchaseOrder]:
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'matching.db'}")
    initialize_operational_database(engine)
    session = Session(engine)
    order = OperationalPurchaseOrder(purchase_order_key="po-key", purchase_order_no="PO-TEST-1",
        quotation_id=1, supplier_code="SUP-1", location_code="SHJ", expected_on=date.today(),
        currency_code="AED", subtotal=100, tax_amount=5, total_amount=105,
        status="approved", posting_enabled=False, created_by="buyer")
    session.add(order); session.flush()
    session.add(OperationalPurchaseOrderLine(purchase_order_id=order.id, line_no=1,
        sku="SKU-1", product_name_snapshot="Product One", quantity=10, uom="Piece",
        factor_to_base_snapshot=1, quantity_base=10, unit_price=10, tax_rate=5,
        net_amount=100, tax_amount=5, gross_amount=105))
    session.commit()
    return session, order


def receipt_line(quantity="10") -> dict:
    return {"sku": "SKU-1", "product_name_snapshot": "Product One",
        "ordered_quantity": Decimal("10"), "received_quantity": Decimal(quantity),
        "accepted_quantity": Decimal(quantity), "rejected_quantity": Decimal("0"),
        "uom": "Piece", "canonical_uom": "piece", "factor_to_base_snapshot": Decimal("1"),
        "unit_cost_snapshot": Decimal("10"), "batch_no": None, "expiry_date": None,
        "rejection_reason": None}


def tax_document(**overrides) -> dict:
    values = {"document_type": "tax_invoice", "supply_date": date.today(),
        "supplier_name": "Supplier One LLC", "supplier_address": "Sharjah, UAE",
        "supplier_trn": "100000000000001", "recipient_name": "Asas General Trading LLC",
        "recipient_address": "Sharjah, UAE", "recipient_trn": "100000000000002"}
    values.update(overrides)
    return values


def accepted_receipt(session: Session, quantity="10"):
    receipt = create_goods_receipt(session, supplier_code="SUP-1", supplier_name_snapshot="Supplier One",
        location_code="SHJ", purchase_reference="PO-TEST-1", supplier_delivery_note="DN-1",
        received_on=date.today(), notes=None, actor="receiver", lines=[receipt_line(quantity)])
    receipt = transition_goods_receipt(session, receipt, expected_revision=1, action="submit", actor="receiver")
    return transition_goods_receipt(session, receipt, expected_revision=2, action="accept", actor="inspector")


def test_po_receipt_binding_blocks_supplier_cost_and_over_receipt(tmp_path):
    session, _ = matching_session(tmp_path)
    valid = receipt_line("6")
    validate_po_receipt(session, purchase_reference="PO-TEST-1", supplier_code="SUP-1",
                        location_code="SHJ", lines=[valid])
    accepted_receipt(session, "6")
    with pytest.raises(ValueError, match="exceeds PO quantity"):
        validate_po_receipt(session, purchase_reference="PO-TEST-1", supplier_code="SUP-1",
                            location_code="SHJ", lines=[receipt_line("5")])
    wrong_cost = receipt_line("4"); wrong_cost["unit_cost_snapshot"] = Decimal("11")
    with pytest.raises(ValueError, match="UOM and cost"):
        validate_po_receipt(session, purchase_reference="PO-TEST-1", supplier_code="SUP-1",
                            location_code="SHJ", lines=[wrong_cost])


def test_three_way_match_requires_accepted_quantity_and_independent_approval(tmp_path):
    session, order = matching_session(tmp_path)
    mismatch = create_supplier_invoice(session, purchase_order_key=order.purchase_order_key,
        supplier_invoice_no="INV-EXCEPTION", invoice_date=date.today(), due_date=date.today() + timedelta(days=30),
        currency_code="AED", lines=[{"sku": "SKU-1", "quantity": 10, "unit_price": 11, "tax_rate": 5}],
        actor="ap-maker", **tax_document())
    result = evaluate_invoice_match(session, mismatch, actor="ap-maker")
    assert result["passed"] is False
    assert {message.split(": ", 1)[1] for message in result["exceptions"]} == {
        "invoice quantity exceeds accepted uninvoiced receipt quantity",
        "unit price differs from PO beyond approved tolerance"}
    with pytest.raises(ValueError, match="Only a passed"):
        decide_supplier_invoice(session, mismatch, action="approve", expected_revision=2,
                                note="Should remain blocked", actor="finance-approver")
    session.rollback()

    accepted_receipt(session)
    invoice = create_supplier_invoice(session, purchase_order_key=order.purchase_order_key,
        supplier_invoice_no="INV-MATCHED", invoice_date=date.today(), due_date=date.today() + timedelta(days=30),
        currency_code="AED", lines=[{"sku": "SKU-1", "quantity": 10, "unit_price": 10, "tax_rate": 5}],
        actor="ap-maker", **tax_document())
    result = evaluate_invoice_match(session, invoice, actor="ap-maker")
    assert result == {"passed": True, "requires_tolerance_review": False,
                      "exceptions": [], "tolerance_reviews": []}
    with pytest.raises(ValueError, match="maker cannot"):
        decide_supplier_invoice(session, invoice, action="approve", expected_revision=2,
                                note="Self approval prohibited", actor="ap-maker")
    session.rollback()
    invoice = decide_supplier_invoice(session, invoice, action="approve", expected_revision=2,
                                      note="Three-way match independently approved", actor="finance-approver")
    assert invoice.status == "approved"
    assert invoice.posting_enabled is False


def approved_invoice(session: Session, order: OperationalPurchaseOrder):
    accepted_receipt(session)
    invoice = create_supplier_invoice(session, purchase_order_key=order.purchase_order_key,
        supplier_invoice_no="INV-APPROVED", invoice_date=date.today(), due_date=None,
        currency_code="AED", lines=[{"sku": "SKU-1", "quantity": 10, "unit_price": 10, "tax_rate": 5}],
        actor="ap-maker", **tax_document())
    evaluate_invoice_match(session, invoice, actor="ap-maker")
    return decide_supplier_invoice(session, invoice, action="approve", expected_revision=2,
                                   note="Matched invoice approved", actor="finance-approver")


def test_tolerance_policy_requires_independent_approval_and_invoice_escalation(tmp_path):
    session, order = matching_session(tmp_path)
    policy = match_policy(session)
    policy = request_policy_change(session, price_tolerance_pct=Decimal("2"),
        amount_tolerance=Decimal("0"), expected_revision=policy.revision,
        note="Allow controlled low price variance", actor="controller")
    with pytest.raises(ValueError, match="maker cannot"):
        decide_policy_change(session, action="approve", expected_revision=policy.revision,
                             note="Self approval blocked", actor="controller")
    session.rollback()
    policy = decide_policy_change(session, action="approve", expected_revision=policy.revision,
                                  note="Tolerance independently approved", actor="cfo")
    assert policy.price_tolerance_pct == 2

    accepted_receipt(session)
    invoice = create_supplier_invoice(session, purchase_order_key=order.purchase_order_key,
        supplier_invoice_no="INV-TOLERANCE", invoice_date=date.today(), due_date=None,
        currency_code="AED", lines=[{"sku": "SKU-1", "quantity": 10,
                                      "unit_price": Decimal("10.10"), "tax_rate": 5}], actor="ap-maker",
        **tax_document())
    result = evaluate_invoice_match(session, invoice, actor="ap-maker")
    assert result["passed"] is False and result["requires_tolerance_review"] is True
    assert invoice.status == "exception"
    invoice = approve_invoice_tolerance(session, invoice, expected_revision=2,
        note="Variance is within approved policy", actor="cfo")
    assert invoice.status == "matched" and invoice.match_status == "passed"
    invoice = decide_supplier_invoice(session, invoice, action="approve", expected_revision=3,
        note="Escalation and match reviewed", actor="finance-approver")
    assert invoice.status == "approved" and invoice.posting_enabled is False


def test_supplier_credit_and_debit_notes_are_controlled_and_non_posting(tmp_path):
    session, order = matching_session(tmp_path)
    invoice = approved_invoice(session, order)
    credit = create_supplier_adjustment(session, invoice_key=invoice.invoice_key,
        adjustment_type="credit_note", supplier_reference="CN-1", adjustment_date=date.today(),
        reason="Six units returned to supplier", lines=[{"sku": "SKU-1", "quantity": 6}], actor="ap-maker")
    credit = transition_supplier_adjustment(session, credit, action="submit", expected_revision=1,
                                            note="Credit note ready", actor="ap-maker")
    with pytest.raises(ValueError, match="maker cannot"):
        transition_supplier_adjustment(session, credit, action="approve", expected_revision=2,
                                       note="Self approval blocked", actor="ap-maker")
    session.rollback()
    credit = transition_supplier_adjustment(session, credit, action="approve", expected_revision=2,
        note="Supplier credit independently approved", actor="finance-approver")
    assert credit.status == "approved" and credit.posting_enabled is False
    with pytest.raises(ValueError, match="exceeds invoice quantity"):
        create_supplier_adjustment(session, invoice_key=invoice.invoice_key,
            adjustment_type="credit_note", supplier_reference="CN-2", adjustment_date=date.today(),
            reason="Would exceed original invoice", lines=[{"sku": "SKU-1", "quantity": 5}], actor="ap-maker")
    session.rollback()
    debit = create_supplier_adjustment(session, invoice_key=invoice.invoice_key,
        adjustment_type="debit_note", supplier_reference="DN-1", adjustment_date=date.today(),
        reason="Supplier approved additional freight", lines=[{"sku": "SKU-1", "quantity": 1,
        "unit_price": Decimal("2"), "tax_rate": 5}], actor="ap-maker")
    assert debit.adjustment_type == "debit_note" and debit.total_amount == Decimal("2.10")


def test_tax_document_blocks_match_and_rehearsal_is_balanced_idempotent(tmp_path):
    session, order = matching_session(tmp_path)
    accepted_receipt(session)
    invalid = create_supplier_invoice(session, purchase_order_key=order.purchase_order_key,
        supplier_invoice_no="INV-BAD-TRN", invoice_date=date.today(), due_date=None,
        currency_code="AED", lines=[{"sku": "SKU-1", "quantity": 10, "unit_price": 10, "tax_rate": 5}],
        actor="ap-maker", **tax_document(supplier_trn="INVALID"))
    result = evaluate_invoice_match(session, invalid, actor="ap-maker")
    assert result["passed"] is False
    assert any("supplier TRN must contain exactly 15 digits" in item for item in result["exceptions"])

    valid_path = tmp_path / "valid"
    valid_path.mkdir()
    session, order = matching_session(valid_path)
    invoice = approved_invoice(session, order)
    session.add(OperationalFiscalPeriod(period_key="FY-TEST",
        starts_on=date.today() - timedelta(days=1), ends_on=date.today() + timedelta(days=1),
        status="open", rehearsal_enabled=True, approval_reference="TEST-ONLY",
        configured_by="test"))
    session.commit()
    plan = rehearse_supplier_invoice_posting(session, invoice, actor="ap-maker")
    assert plan["debit"] == plan["credit"] == Decimal("105.00")
    assert plan["posting_enabled"] is False
    assert [line["account_code"] for line in plan["journal"]] == ["GRNI", "1320", "2100"]
    replay = rehearse_supplier_invoice_posting(session, invoice, actor="ap-maker")
    assert replay["idempotent_replay"] is True
    assert replay["posting_fingerprint"] == plan["posting_fingerprint"]


def test_supplier_invoice_posts_atomically_and_reversal_blocks_dependencies(tmp_path):
    session, order = matching_session(tmp_path)
    invoice = approved_invoice(session, order)
    session.add(OperationalFiscalPeriod(period_key="FY-POST",
        starts_on=date.today() - timedelta(days=1), ends_on=date.today() + timedelta(days=1),
        status="open", rehearsal_enabled=True, approval_reference="POST-TEST",
        configured_by="controller"))
    session.commit()
    plan = rehearse_supplier_invoice_posting(session, invoice, actor="finance-approver")

    with pytest.raises(ValueError, match="maker cannot execute"):
        execute_integrated_posting(session, resource_type="supplier_invoice",
            resource_key=invoice.invoice_key, idempotency_key=plan["idempotency_key"], actor="ap-maker")

    posted = execute_integrated_posting(session, resource_type="supplier_invoice",
        resource_key=invoice.invoice_key, idempotency_key=plan["idempotency_key"], actor="posting-controller")
    assert posted["batch_kind"] == "posting" and invoice.status == "posted"
    assert execute_integrated_posting(session, resource_type="supplier_invoice",
        resource_key=invoice.invoice_key, idempotency_key=plan["idempotency_key"],
        actor="posting-controller")["idempotent_replay"] is True
    batch = session.scalar(select(OperationalIntegratedPostingBatch).where(
        OperationalIntegratedPostingBatch.batch_key == posted["batch_key"]))
    lines = list(session.scalars(select(OperationalIntegratedJournalLine).where(
        OperationalIntegratedJournalLine.batch_id == batch.id)))
    assert [row.account_code for row in lines] == ["GRNI", "1320", "2100"]
    assert sum((row.debit for row in lines), Decimal("0")) == Decimal("105.00")
    assert sum((row.credit for row in lines), Decimal("0")) == Decimal("105.00")
    payable = session.scalar(select(OperationalIntegratedSubledgerEntry).where(
        OperationalIntegratedSubledgerEntry.batch_id == batch.id))
    assert payable.entry_type == "payable_invoice" and payable.amount == Decimal("105.00")

    payment = create_payment(session, actor="cashier", payment_type="supplier_payment",
        party_code=invoice.supplier_code, party_name_snapshot="Supplier One", location_code="SHJ",
        payment_date=date.today(), payment_method="bank_transfer", cash_bank_account_code="Bank - AED",
        reference_no="PAY-INV", amount=Decimal("105"), notes=None,
        lines=[{"source_type": "invoice", "source_reference_key": invoice.supplier_invoice_no,
            "source_document_date": invoice.invoice_date, "source_outstanding_snapshot": Decimal("105"),
            "allocation_amount": Decimal("105")}])
    payment = transition_payment(session, payment, expected_revision=1, action="submit", actor="cashier",
                                 note="Submit dependency test payment")
    with pytest.raises(ValueError, match="payment allocation"):
        execute_integrated_reversal(session, batch, actor="controller", reason="Invoice entered twice")
    transition_payment(session, payment, expected_revision=2, action="cancel", actor="cashier",
                       note="Cancel dependency test payment")

    adjustment = create_supplier_adjustment(session, invoice_key=invoice.invoice_key,
        adjustment_type="credit_note", supplier_reference="CN-AFTER-POST", adjustment_date=date.today(),
        reason="Post-invoice supplier correction", lines=[{"sku": "SKU-1", "quantity": 1}],
        actor="ap-maker")
    with pytest.raises(ValueError, match="adjustment activity"):
        execute_integrated_reversal(session, batch, actor="controller", reason="Invoice entered twice")
    transition_supplier_adjustment(session, adjustment, action="cancel", expected_revision=1,
                                   note="Cancel dependency test adjustment", actor="ap-maker")
    reversed_result = execute_integrated_reversal(session, batch, actor="controller",
                                                  reason="Invoice entered twice")
    assert reversed_result["batch_kind"] == "reversal" and invoice.status == "reversed"
    assert session.scalar(select(func.count(OperationalIntegratedJournalLine.id))) == 6
    assert session.scalar(select(func.count(OperationalIntegratedSubledgerEntry.id))) == 2


def test_supplier_credit_note_posts_atomically_and_reverses_with_payable_link(tmp_path):
    session, order = matching_session(tmp_path)
    invoice = approved_invoice(session, order)
    session.add(OperationalFiscalPeriod(period_key="FY-ADJUST",
        starts_on=date.today() - timedelta(days=1), ends_on=date.today() + timedelta(days=1),
        status="open", rehearsal_enabled=True, approval_reference="ADJUST-TEST",
        configured_by="controller"))
    session.commit()
    invoice_plan = rehearse_supplier_invoice_posting(session, invoice, actor="finance-approver")
    execute_integrated_posting(session, resource_type="supplier_invoice", resource_key=invoice.invoice_key,
                               idempotency_key=invoice_plan["idempotency_key"], actor="posting-controller")

    credit = create_supplier_adjustment(session, invoice_key=invoice.invoice_key,
        adjustment_type="credit_note", accounting_treatment="price_variance",
        supplier_reference="CN-POST-1", adjustment_date=date.today(),
        reason="Approved purchase price reduction", lines=[{"sku": "SKU-1", "quantity": 2}],
        actor="ap-maker")
    credit = transition_supplier_adjustment(session, credit, action="submit", expected_revision=1,
                                            note="Submit credit", actor="ap-maker")
    credit = transition_supplier_adjustment(session, credit, action="approve", expected_revision=2,
        note="Independent credit approval", actor="finance-approver")
    plan = rehearse_supplier_adjustment_posting(session, credit, actor="finance-approver")
    assert plan["debit"] == plan["credit"] == Decimal("21.00")
    assert [line["account_code"] for line in plan["journal"]] == ["2100", "1320", "5110"]
    assert rehearse_supplier_adjustment_posting(session, credit,
        actor="finance-approver")["idempotent_replay"] is True
    with pytest.raises(ValueError, match="maker cannot execute"):
        execute_integrated_posting(session, resource_type="supplier_adjustment",
            resource_key=credit.adjustment_key, idempotency_key=plan["idempotency_key"], actor="ap-maker")
    posted = execute_integrated_posting(session, resource_type="supplier_adjustment",
        resource_key=credit.adjustment_key, idempotency_key=plan["idempotency_key"], actor="posting-controller")
    assert credit.status == "posted"
    batch = session.scalar(select(OperationalIntegratedPostingBatch).where(
        OperationalIntegratedPostingBatch.batch_key == posted["batch_key"]))
    payable = session.scalar(select(OperationalIntegratedSubledgerEntry).where(
        OperationalIntegratedSubledgerEntry.batch_id == batch.id))
    assert payable.entry_type == "payable_credit_note"
    assert payable.source_reference_key == invoice.supplier_invoice_no
    assert payable.amount == Decimal("-21.00")

    payment = create_payment(session, actor="cashier", payment_type="supplier_payment",
        party_code=invoice.supplier_code, party_name_snapshot="Supplier One", location_code="SHJ",
        payment_date=date.today(), payment_method="bank_transfer", cash_bank_account_code="Bank - AED",
        reference_no="PAY-AFTER-CREDIT", amount=Decimal("10"), notes=None,
        lines=[{"source_type": "invoice", "source_reference_key": invoice.supplier_invoice_no,
            "source_document_date": invoice.invoice_date, "source_outstanding_snapshot": Decimal("84"),
            "allocation_amount": Decimal("10")}])
    payment = transition_payment(session, payment, expected_revision=1, action="submit", actor="cashier",
                                 note="Payment after credit")
    with pytest.raises(ValueError, match="later supplier payment"):
        execute_integrated_reversal(session, batch, actor="controller", reason="Reverse posted credit")
    transition_payment(session, payment, expected_revision=2, action="cancel", actor="cashier",
                       note="Cancel dependency")
    reversal = execute_integrated_reversal(session, batch, actor="controller", reason="Reverse posted credit")
    assert reversal["batch_kind"] == "reversal" and credit.status == "reversed"


def test_supplier_credit_is_blocked_when_purchase_return_controls_same_invoice_item(tmp_path):
    session, order = matching_session(tmp_path)
    invoice = approved_invoice(session, order)
    purchase_return = create_purchase_return(session, supplier_code=invoice.supplier_code,
        supplier_name_snapshot="Supplier One", location_code=invoice.location_code,
        source_reference_type="purchase_invoice", source_reference_key=invoice.supplier_invoice_no,
        return_date=date.today(), reason_code="quality", notes=None, actor="warehouse-maker",
        lines=[{"sku": "SKU-1", "product_name_snapshot": "Product One",
            "source_received_quantity": Decimal("10"), "quantity": Decimal("2"),
            "supplier_return_quantity": Decimal("2"), "internal_writeoff_quantity": Decimal("0"),
            "uom": "Piece", "canonical_uom": "piece", "factor_to_base_snapshot": Decimal("1"),
            "unit_price": Decimal("10"), "tax_rate": Decimal("5"),
            "unit_cost_snapshot": Decimal("10"), "disposition_reason": None}])
    purchase_return.status = "submitted"
    session.commit()
    with pytest.raises(ValueError, match="purchase return already controls"):
        create_supplier_adjustment(session, invoice_key=invoice.invoice_key,
            adjustment_type="credit_note", accounting_treatment="price_variance",
            supplier_reference="CN-DUPLICATE", adjustment_date=date.today(),
            reason="Duplicate goods-return credit", lines=[{"sku": "SKU-1", "quantity": 2}],
            actor="ap-maker")
