from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from klen_clone.operational import (
    OperationalDraft,
    OperationalFiscalPeriod,
    OperationalStockPosition,
    OperationalStockReservation,
    create_draft,
    initialize_operational_database,
    make_operational_engine,
    transition_draft,
)
from klen_clone.posting_integration import (
    OperationalIntegratedJournalLine,
    OperationalIntegratedPostingBatch,
    OperationalIntegratedStockEntry,
    OperationalIntegratedSubledgerEntry,
    execute_integrated_posting,
    execute_integrated_reversal,
)
from klen_clone.payments import create_payment, transition_payment
from klen_clone.sales_invoices import (
    OperationalSalesInvoicePostingRehearsal,
    rehearse_sales_invoice_posting,
)


@pytest.fixture
def session():
    engine = make_operational_engine("sqlite:///:memory:")
    initialize_operational_database(engine)
    with Session(engine) as value:
        value.add(OperationalFiscalPeriod(
            period_key="FY-2026", starts_on=date(2026, 1, 1), ends_on=date(2026, 12, 31),
            status="open", rehearsal_enabled=True, revision=1,
            approval_reference="sales-invoice-test", configured_by="finance",
        ))
        value.add(OperationalStockPosition(
            location_code="DXB", sku="93431", canonical_uom="bundle",
            quantity_on_hand=Decimal("10"), quantity_reserved=Decimal("0"),
            average_unit_cost=Decimal("33.6"), revision=1,
            source_status="test", availability_enabled=True,
        ))
        value.commit()
        yield value


def approved_invoice(session: Session) -> OperationalDraft:
    invoice = create_draft(
        session, document_type="sale", party_code="CO0872", party_name="Customer",
        location_code="DXB", discount_amount=Decimal("0"), notes="controlled test",
        actor="sales-maker", lines=[{
            "sku": "93431", "product_name_snapshot": "Autocut-AC08",
            "quantity": Decimal("1"), "uom": "Bundle", "canonical_uom": "bundle",
            "factor_to_base_snapshot": Decimal("1"), "quantity_base": Decimal("1"),
            "unit_price": Decimal("36"), "tax_rate": Decimal("5"),
            "net_amount": Decimal("36"), "tax_amount": Decimal("1.8"),
            "gross_amount": Decimal("37.8"), "unit_cost_snapshot": Decimal("33.6"),
            "cost_amount": Decimal("33.6"),
        }],
    )
    invoice = transition_draft(session, invoice, expected_revision=1, action="submit", actor="sales-maker")
    return transition_draft(session, invoice, expected_revision=2, action="approve", actor="sales-approver")


def test_sales_invoice_rehearsal_is_persistent_balanced_and_idempotent(session):
    invoice = approved_invoice(session)
    plan = rehearse_sales_invoice_posting(session, invoice, actor="sales-approver")
    assert plan["debit"] == plan["credit"] == Decimal("71.40")
    assert [row["account_code"] for row in plan["journal"]] == ["1200", "4000", "2120", "5000", "1300"]
    assert plan["movements"] == plan["inventory"]
    assert plan["movements"][0]["quantity_base"] == Decimal("-1")
    assert plan["movements"][0]["value_delta"] == Decimal("-33.60")
    assert plan["reversal"]["movements"][0]["quantity_base"] == Decimal("1")
    assert plan["posting_enabled"] is False and plan["posting_performed"] is False
    replay = rehearse_sales_invoice_posting(session, invoice, actor="sales-approver")
    assert replay["idempotent_replay"] is True
    assert replay["idempotency_key"] == plan["idempotency_key"]
    assert session.scalar(select(func.count(OperationalSalesInvoicePostingRehearsal.id))) == 1


def test_sales_invoice_atomic_posting_and_exact_reversal(session):
    invoice = approved_invoice(session)
    plan = rehearse_sales_invoice_posting(session, invoice, actor="sales-approver")
    with pytest.raises(ValueError, match="maker cannot execute"):
        execute_integrated_posting(session, resource_type="sales_invoice", resource_key=invoice.draft_key,
                                   idempotency_key=plan["idempotency_key"], actor="sales-maker")
    result = execute_integrated_posting(
        session, resource_type="sales_invoice", resource_key=invoice.draft_key,
        idempotency_key=plan["idempotency_key"], actor="sales-approver",
    )
    assert result["status"] == "posted"
    assert execute_integrated_posting(
        session, resource_type="sales_invoice", resource_key=invoice.draft_key,
        idempotency_key=plan["idempotency_key"], actor="sales-approver",
    )["idempotent_replay"] is True
    session.refresh(invoice)
    position = session.scalar(select(OperationalStockPosition).where(
        OperationalStockPosition.location_code == "DXB", OperationalStockPosition.sku == "93431"))
    reservation = session.scalar(select(OperationalStockReservation).where(
        OperationalStockReservation.draft_id == invoice.id))
    assert invoice.status == "posted"
    assert position.quantity_on_hand == Decimal("9") and position.quantity_reserved == Decimal("0")
    assert reservation.status == "consumed"
    batch = session.scalar(select(OperationalIntegratedPostingBatch).where(
        OperationalIntegratedPostingBatch.batch_key == result["batch_key"]))
    assert session.scalar(select(func.count(OperationalIntegratedJournalLine.id)).where(
        OperationalIntegratedJournalLine.batch_id == batch.id)) == 5
    assert session.scalar(select(func.count(OperationalIntegratedStockEntry.id)).where(
        OperationalIntegratedStockEntry.batch_id == batch.id)) == 1
    subledger = session.scalar(select(OperationalIntegratedSubledgerEntry).where(
        OperationalIntegratedSubledgerEntry.batch_id == batch.id))
    assert subledger.entry_type == "receivable_invoice"
    assert subledger.source_reference_key == invoice.draft_no
    assert subledger.amount == Decimal("37.80")

    receipt = create_payment(
        session, actor="receipt-maker", payment_type="customer_receipt",
        party_code="CO0872", party_name_snapshot="Customer", location_code="DXB",
        payment_date=date(2026, 9, 19), payment_method="cash",
        cash_bank_account_code="1000", reference_no=None, amount=Decimal("10"),
        notes="dependent receipt", lines=[{
            "source_type": "invoice", "source_reference_key": invoice.draft_no,
            "source_document_date": date(2026, 9, 19),
            "source_outstanding_snapshot": Decimal("37.80"),
            "allocation_amount": Decimal("10"),
        }],
    )
    receipt = transition_payment(session, receipt, expected_revision=1, action="submit", actor="receipt-maker")
    with pytest.raises(ValueError, match="customer receipt allocation"):
        execute_integrated_reversal(session, batch, actor="finance-controller",
                                    reason="Controlled browser validation reversal")
    transition_payment(session, receipt, expected_revision=2, action="cancel", actor="receipt-maker")
    reversed_result = execute_integrated_reversal(session, batch, actor="finance-controller",
                                                  reason="Controlled browser validation reversal")
    session.refresh(invoice); session.refresh(position); session.refresh(reservation)
    assert reversed_result["batch_kind"] == "reversal"
    assert invoice.status == "reversed"
    assert position.quantity_on_hand == Decimal("10") and position.quantity_reserved == Decimal("0")
    assert reservation.status == "released"
    assert session.scalar(select(func.count(OperationalIntegratedPostingBatch.id))) == 2
