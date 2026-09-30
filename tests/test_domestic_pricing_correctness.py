from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from klen_clone.operational import (
    OperationalFiscalPeriod,
    OperationalStockPosition,
    create_draft,
    initialize_operational_database,
    make_operational_engine,
    price_draft_lines,
    replace_draft,
    transition_draft,
)
from klen_clone.posting_integration import (
    OperationalIntegratedJournalLine,
    OperationalIntegratedPostingBatch,
    OperationalIntegratedSubledgerEntry,
    execute_integrated_posting,
)
from klen_clone.sales_invoices import rehearse_sales_invoice_posting


def line(**overrides):
    value = {
        "sku": "PACK-1", "product_name_snapshot": "Test pack",
        "quantity": Decimal("0.5"), "uom": "Carton", "canonical_uom": "Pack",
        "factor_to_base_snapshot": Decimal("6"), "quantity_base": Decimal("3"),
        "unit_price": Decimal("24"), "tax_rate": Decimal("5"),
        "net_amount": Decimal("999"), "tax_amount": Decimal("999"),
        "gross_amount": Decimal("999"), "unit_cost_snapshot": Decimal("2.35"),
        "cost_amount": Decimal("999"),
    }
    value.update(overrides)
    return value


def test_fractional_uom_discount_reprices_client_amounts_and_vat():
    priced, subtotal, vat, total = price_draft_lines([line()], Decimal("1.20"))
    assert (subtotal, vat, total) == (Decimal("12.00"), Decimal("0.54"), Decimal("11.34"))
    assert priced[0]["quantity_base"] == Decimal("3")
    assert priced[0]["cost_amount"] == Decimal("7.05")
    assert priced[0]["gross_amount"] == Decimal("11.34")


def test_discount_allocation_is_deterministic_and_balances():
    lines = [line(quantity=Decimal("1"), factor_to_base_snapshot=Decimal("1"),
                  quantity_base=Decimal("1"), unit_price=Decimal("10"), sku=sku)
             for sku in ("A", "B")]
    priced, subtotal, vat, total = price_draft_lines(lines, Decimal("2.00"))
    assert (subtotal, vat, total) == (Decimal("20.00"), Decimal("0.90"), Decimal("18.90"))
    assert [row["gross_amount"] for row in priced] == [Decimal("9.45"), Decimal("9.45")]


@pytest.mark.parametrize("change, discount, message", [
    ({"quantity_base": Decimal("4")}, Decimal("0"), "base quantity"),
    ({}, Decimal("12.01"), "exceed"),
    ({}, Decimal("0.001"), "cent precision"),
    ({"unit_cost_snapshot": Decimal("-1")}, Decimal("0"), "unit cost"),
])
def test_invalid_pricing_is_rejected(change, discount, message):
    with pytest.raises(ValueError, match=message):
        price_draft_lines([line(**change)], discount)


def test_create_and_replace_draft_persist_repriced_values():
    engine = make_operational_engine("sqlite:///:memory:")
    initialize_operational_database(engine)
    with Session(engine) as session:
        draft = create_draft(
            session, document_type="sale", party_code="C1", party_name="Customer",
            location_code="MAIN", discount_amount=Decimal("1.20"), notes=None,
            actor="maker", lines=[line()],
        )
        assert (draft.subtotal, draft.discount_amount, draft.tax_amount, draft.total_amount) == (
            Decimal("12.00"), Decimal("1.20"), Decimal("0.54"), Decimal("11.34"))
        assert (draft.lines[0].net_amount, draft.lines[0].tax_amount,
                draft.lines[0].gross_amount, draft.lines[0].cost_amount) == (
                    Decimal("12.00"), Decimal("0.54"), Decimal("11.34"), Decimal("7.05"))
        edited = replace_draft(
            session, draft, expected_revision=1, party_code="C1", party_name="Customer",
            location_code="MAIN", discount_amount=Decimal("2.00"), notes=None,
            actor="maker", lines=[line()],
        )
        assert (edited.tax_amount, edited.total_amount) == (Decimal("0.50"), Decimal("10.50"))
        assert edited.lines[0].gross_amount == Decimal("10.50")


def test_discounted_fractional_uom_invoice_posts_balanced_stock_and_receivable():
    engine = make_operational_engine("sqlite:///:memory:")
    initialize_operational_database(engine)
    with Session(engine) as session:
        session.add(OperationalFiscalPeriod(
            period_key="2026", starts_on=date(2026, 1, 1), ends_on=date(2026, 12, 31),
            status="open", rehearsal_enabled=True, revision=1,
            approval_reference="domestic-correctness-test", configured_by="finance"))
        session.add(OperationalStockPosition(
            location_code="MAIN", sku="PACK-1", canonical_uom="Pack",
            quantity_on_hand=Decimal("9"), quantity_reserved=Decimal("0"),
            average_unit_cost=Decimal("2.35"), revision=1,
            source_status="test", availability_enabled=True))
        session.commit()
        invoice = create_draft(
            session, document_type="sale", party_code="C1", party_name="Customer",
            location_code="MAIN", discount_amount=Decimal("1.20"), notes=None,
            actor="maker", lines=[line()],
        )
        invoice = transition_draft(session, invoice, expected_revision=1, action="submit", actor="maker")
        invoice = transition_draft(session, invoice, expected_revision=2, action="approve", actor="approver")
        plan = rehearse_sales_invoice_posting(session, invoice, actor="approver")
        assert plan["debit"] == plan["credit"] == Decimal("18.39")
        result = execute_integrated_posting(
            session, resource_type="sales_invoice", resource_key=invoice.draft_key,
            idempotency_key=plan["idempotency_key"], actor="approver")
        assert result["status"] == "posted"
        assert execute_integrated_posting(
            session, resource_type="sales_invoice", resource_key=invoice.draft_key,
            idempotency_key=plan["idempotency_key"], actor="approver")["idempotent_replay"]
        stock = session.scalar(select(OperationalStockPosition).where(
            OperationalStockPosition.location_code == "MAIN", OperationalStockPosition.sku == "PACK-1"))
        assert stock.quantity_on_hand == Decimal("6")
        batch = session.scalar(select(OperationalIntegratedPostingBatch).where(
            OperationalIntegratedPostingBatch.batch_key == result["batch_key"]))
        journal = {row.account_code: row for row in session.scalars(select(OperationalIntegratedJournalLine).where(
            OperationalIntegratedJournalLine.batch_id == batch.id))}
        assert (journal["1200"].debit, journal["4000"].credit,
                journal["2120"].credit, journal["5000"].debit) == (
                    Decimal("11.34"), Decimal("10.80"), Decimal("0.54"), Decimal("7.05"))
        subledger = session.scalar(select(OperationalIntegratedSubledgerEntry).where(
            OperationalIntegratedSubledgerEntry.batch_id == batch.id))
        assert subledger.amount == Decimal("11.34")
