from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    ErpCashLedgerEvidence, ErpJournalBlueprint, ErpParty, ErpTaxLedgerEvidence,
    ErpTransactionDocument, ErpTrialBalanceEvidence,
)
from .operational import MONEY, OperationalOpeningPartyBalance
from .payments import (
    OperationalPayment, OperationalPaymentAllocationClaim,
    customer_invoice_settlement,
)
from .customer_invoices import OperationalCustomerInvoice


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(MONEY, rounding=ROUND_HALF_UP)


def ageing_bucket(document_date: date | None, as_of: date) -> str:
    if document_date is None:
        return "undated"
    days = max(0, (as_of - document_date).days)
    if days <= 30:
        return "days_0_30"
    if days <= 60:
        return "days_31_60"
    if days <= 90:
        return "days_61_90"
    return "days_91_plus"


def build_ageing_report(clone_session: Session, operational_session: Session, *, snapshot_id: int,
                        ledger_kind: str, as_of: date, query: str = "", limit: int = 100,
                        offset: int = 0) -> dict:
    if ledger_kind not in {"receivable", "payable"}:
        raise ValueError("Ledger kind must be receivable or payable")
    party_kind = "customer" if ledger_kind == "receivable" else "supplier"
    source_kind = "sale" if ledger_kind == "receivable" else "purchase"
    payment_type = "customer_receipt" if ledger_kind == "receivable" else "supplier_payment"
    advance_type = "customer_advance" if ledger_kind == "receivable" else "supplier_advance"

    parties: dict[str, dict] = {}
    for party in clone_session.execute(select(ErpParty.party_code, ErpParty.legal_or_business_name).where(
            ErpParty.snapshot_id == snapshot_id,
            ErpParty.party_kind.in_((party_kind, "both")))).all():
        parties[party.party_code] = {"party_code": party.party_code, "party_name": party.legal_or_business_name}

    controls = defaultdict(Decimal)
    source_advances = defaultdict(Decimal)
    for opening in operational_session.scalars(select(OperationalOpeningPartyBalance).where(
            OperationalOpeningPartyBalance.party_type == party_kind,
            OperationalOpeningPartyBalance.balance_type.in_((ledger_kind, advance_type)))):
        parties.setdefault(opening.party_code, {"party_code": opening.party_code,
                                               "party_name": opening.party_name_snapshot})
        target = controls if opening.balance_type == ledger_kind else source_advances
        target[opening.party_code] += _money(opening.amount)

    claim_by_source = defaultdict(Decimal)
    submitted = defaultdict(Decimal)
    approved = defaultdict(Decimal)
    for claim, payment_status in operational_session.execute(select(
            OperationalPaymentAllocationClaim, OperationalPayment.status).join(
                OperationalPayment, OperationalPayment.id == OperationalPaymentAllocationClaim.payment_id).where(
                    OperationalPayment.payment_type == payment_type,
                    OperationalPaymentAllocationClaim.status == "active")):
        parties.setdefault(claim.party_code, {"party_code": claim.party_code, "party_name": claim.party_code})
        claim_by_source[(claim.party_code, claim.source_type, claim.source_reference_key)] += _money(claim.amount)
        (approved if payment_status == "approved" else submitted)[claim.party_code] += _money(claim.amount)

    submitted_advances = defaultdict(Decimal)
    approved_advances = defaultdict(Decimal)
    for payment in operational_session.scalars(select(OperationalPayment).where(
            OperationalPayment.payment_type == payment_type,
            OperationalPayment.status.in_(("submitted", "approved")),
            OperationalPayment.unallocated_amount > 0)):
        parties.setdefault(payment.party_code, {"party_code": payment.party_code,
                                                "party_name": payment.party_name_snapshot})
        (approved_advances if payment.status == "approved" else submitted_advances)[payment.party_code] += _money(payment.unallocated_amount)

    invoice_totals = defaultdict(Decimal)
    target_erp_invoiced = defaultdict(Decimal)
    buckets = defaultdict(lambda: defaultdict(Decimal))
    invoice_rows = clone_session.execute(select(
        ErpParty.party_code, ErpTransactionDocument.document_no, ErpTransactionDocument.occurred_at,
        ErpTransactionDocument.total_amount, ErpTransactionDocument.paid_amount,
        ErpTransactionDocument.due_amount).join(
            ErpParty, ErpParty.id == ErpTransactionDocument.party_id).where(
                ErpTransactionDocument.snapshot_id == snapshot_id,
                ErpTransactionDocument.source_kind == source_kind,
                ErpParty.party_kind.in_((party_kind, "both"))))
    for invoice in invoice_rows:
        due = _money(invoice.due_amount if invoice.due_amount is not None else
                     (invoice.total_amount or 0) - (invoice.paid_amount or 0))
        claimed = claim_by_source[(invoice.party_code, "invoice", invoice.document_no)]
        remaining = max(Decimal("0.00"), due - claimed)
        if remaining <= 0:
            continue
        invoice_totals[invoice.party_code] += remaining
        document_date = invoice.occurred_at.date() if invoice.occurred_at else None
        buckets[invoice.party_code][ageing_bucket(document_date, as_of)] += remaining

    if ledger_kind == "receivable":
        for invoice in operational_session.scalars(select(OperationalCustomerInvoice).where(
                OperationalCustomerInvoice.status == "approved")):
            parties.setdefault(invoice.customer_code, {
                "party_code": invoice.customer_code,
                "party_name": invoice.customer_name_snapshot,
            })
            gross = _money(invoice.total_amount)
            target_erp_invoiced[invoice.customer_code] += gross
            claimed = claim_by_source[(invoice.customer_code, "invoice", invoice.invoice_no)]
            remaining = max(Decimal("0.00"), gross - claimed)
            if remaining > 0:
                invoice_totals[invoice.customer_code] += remaining
                buckets[invoice.customer_code][ageing_bucket(invoice.invoice_date, as_of)] += remaining

    rows = []
    for party_code, party in parties.items():
        opening = _money(controls[party_code])
        target_invoiced = _money(target_erp_invoiced[party_code])
        reserved_submitted = _money(submitted[party_code])
        reserved_approved = _money(approved[party_code])
        control_remaining = max(Decimal("0.00"), opening + target_invoiced - reserved_submitted - reserved_approved)
        invoice_outstanding = _money(invoice_totals[party_code])
        source_advance = _money(source_advances[party_code])
        pending_advance = _money(submitted_advances[party_code])
        approved_advance = _money(approved_advances[party_code])
        control_variance = _money(control_remaining - invoice_outstanding)
        row = {**party, "opening_control": opening, "target_erp_invoiced": target_invoiced,
               "submitted_allocation": reserved_submitted, "approved_unposted_allocation": reserved_approved,
               "control_outstanding": control_remaining, "invoice_evidence_outstanding": invoice_outstanding,
               "control_variance": control_variance, "source_advance": source_advance,
               "submitted_advance": pending_advance, "approved_unposted_advance": approved_advance,
               "net_exposure": _money(control_remaining - source_advance - pending_advance - approved_advance),
               "days_0_30": _money(buckets[party_code]["days_0_30"]),
               "days_31_60": _money(buckets[party_code]["days_31_60"]),
               "days_61_90": _money(buckets[party_code]["days_61_90"]),
               "days_91_plus": _money(buckets[party_code]["days_91_plus"]),
               "undated": _money(buckets[party_code]["undated"]),
               "reconciliation_status": "reconciled" if control_variance == 0 else "review_required"}
        if any(row[key] != 0 for key in ("opening_control", "target_erp_invoiced", "invoice_evidence_outstanding", "source_advance",
                                          "submitted_allocation", "approved_unposted_allocation",
                                          "submitted_advance", "approved_unposted_advance")):
            rows.append(row)
    needle = query.strip().casefold()
    if needle:
        rows = [row for row in rows if needle in row["party_code"].casefold() or needle in row["party_name"].casefold()]
    rows.sort(key=lambda row: (-abs(row["net_exposure"]), row["party_code"]))
    totals = {key: _money(sum((row[key] for row in rows), Decimal("0"))) for key in (
        "opening_control", "target_erp_invoiced", "submitted_allocation", "approved_unposted_allocation", "control_outstanding",
        "invoice_evidence_outstanding", "control_variance", "source_advance", "submitted_advance",
        "approved_unposted_advance", "net_exposure", "days_0_30", "days_31_60", "days_61_90",
        "days_91_plus", "undated")}
    return {"ledger_kind": ledger_kind, "party_kind": party_kind, "as_of": as_of,
            "age_basis": "invoice_date", "due_date_available": False,
            "authoritative_total": "approved_opening_control_plus_target_erp_invoices_less_active_allocations",
            "total": len(rows), "limit": limit, "offset": offset,
            "items": rows[offset:offset + limit], "totals": totals,
            "reconciled_parties": sum(row["reconciliation_status"] == "reconciled" for row in rows),
            "review_required_parties": sum(row["reconciliation_status"] == "review_required" for row in rows),
            "posting_enabled": False}


def build_customer_statement(operational_session: Session, *, party_code: str,
                             party_name: str, as_of: date) -> dict:
    """Build an auditable statement from opening controls and target-ERP activity."""
    opening_receivable = _money(operational_session.scalar(select(func.coalesce(
        func.sum(OperationalOpeningPartyBalance.amount), 0)).where(
            OperationalOpeningPartyBalance.party_type == "customer",
            OperationalOpeningPartyBalance.party_code == party_code,
            OperationalOpeningPartyBalance.balance_type == "receivable")) or 0)
    opening_advance = _money(operational_session.scalar(select(func.coalesce(
        func.sum(OperationalOpeningPartyBalance.amount), 0)).where(
            OperationalOpeningPartyBalance.party_type == "customer",
            OperationalOpeningPartyBalance.party_code == party_code,
            OperationalOpeningPartyBalance.balance_type == "customer_advance")) or 0)

    entries = []
    invoice_total = Decimal("0.00")
    invoices = operational_session.scalars(select(OperationalCustomerInvoice).where(
        OperationalCustomerInvoice.customer_code == party_code,
        OperationalCustomerInvoice.status == "approved",
        OperationalCustomerInvoice.invoice_date <= as_of,
    ).order_by(OperationalCustomerInvoice.invoice_date,
               OperationalCustomerInvoice.invoice_no)).all()
    for invoice in invoices:
        settlement = customer_invoice_settlement(operational_session, invoice)
        amount = _money(invoice.total_amount)
        invoice_total += amount
        entries.append({
            "entry_date": invoice.invoice_date,
            "entry_type": "customer_invoice",
            "reference": invoice.invoice_no,
            "source_reference": invoice.delivery_note_no_snapshot,
            "description": f"POD-backed invoice; due {invoice.due_date.isoformat()}",
            "debit": amount, "credit": Decimal("0.00"),
            **settlement,
        })

    receipt_total = Decimal("0.00")
    receipts = operational_session.scalars(select(OperationalPayment).where(
        OperationalPayment.payment_type == "customer_receipt",
        OperationalPayment.party_code == party_code,
        OperationalPayment.status == "approved",
        OperationalPayment.payment_date <= as_of,
    ).order_by(OperationalPayment.payment_date, OperationalPayment.payment_no)).all()
    for receipt in receipts:
        amount = _money(receipt.amount)
        receipt_total += amount
        sources = ", ".join(line.source_reference_key for line in receipt.allocations)
        entries.append({
            "entry_date": receipt.payment_date,
            "entry_type": "customer_receipt",
            "reference": receipt.payment_no,
            "source_reference": sources or "Customer advance",
            "description": f"{receipt.payment_method.replace('_', ' ')} receipt",
            "debit": Decimal("0.00"), "credit": amount,
            "settlement_status": "approved",
        })

    type_order = {"customer_invoice": 0, "customer_receipt": 1}
    entries.sort(key=lambda row: (row["entry_date"], type_order[row["entry_type"]], row["reference"]))
    running = _money(opening_receivable - opening_advance)
    for entry in entries:
        running = _money(running + entry["debit"] - entry["credit"])
        entry["running_balance"] = running

    pending_receipts = _money(operational_session.scalar(select(func.coalesce(
        func.sum(OperationalPayment.amount), 0)).where(
            OperationalPayment.payment_type == "customer_receipt",
            OperationalPayment.party_code == party_code,
            OperationalPayment.status == "submitted",
            OperationalPayment.payment_date <= as_of)) or 0)
    closing = _money(opening_receivable - opening_advance + invoice_total - receipt_total)
    return {
        "party_code": party_code, "party_name": party_name, "as_of": as_of,
        "currency_code": "AED", "opening_receivable": opening_receivable,
        "opening_advance": opening_advance,
        "opening_balance": _money(opening_receivable - opening_advance),
        "invoice_total": _money(invoice_total), "receipt_total": _money(receipt_total),
        "pending_receipts": pending_receipts, "closing_balance": closing,
        "entries": entries, "posting_enabled": False,
        "scope_note": "Authoritative opening control plus approved target-ERP invoices and receipts",
    }


def build_accounting_summary(clone_session: Session, operational_session: Session, *, snapshot_id: int) -> dict:
    trial = clone_session.execute(select(
        func.count(ErpTrialBalanceEvidence.id), func.coalesce(func.sum(ErpTrialBalanceEvidence.debit), 0),
        func.coalesce(func.sum(ErpTrialBalanceEvidence.credit), 0)).where(
            ErpTrialBalanceEvidence.snapshot_id == snapshot_id)).one()
    journal = clone_session.execute(select(
        func.count(ErpJournalBlueprint.id), func.coalesce(func.sum(ErpJournalBlueprint.debit_total), 0),
        func.coalesce(func.sum(ErpJournalBlueprint.credit_total), 0)).where(
            ErpJournalBlueprint.snapshot_id == snapshot_id)).one()
    cash = clone_session.execute(select(
        func.count(ErpCashLedgerEvidence.id), func.coalesce(func.sum(ErpCashLedgerEvidence.debit), 0),
        func.coalesce(func.sum(ErpCashLedgerEvidence.credit), 0)).where(
            ErpCashLedgerEvidence.snapshot_id == snapshot_id)).one()
    tax = clone_session.execute(select(
        func.count(ErpTaxLedgerEvidence.id), func.coalesce(func.sum(ErpTaxLedgerEvidence.vat_amount), 0)).where(
            ErpTaxLedgerEvidence.snapshot_id == snapshot_id)).one()
    pipeline = [dict(row._mapping) for row in operational_session.execute(select(
        OperationalPayment.payment_type, OperationalPayment.status,
        func.count(OperationalPayment.id).label("documents"),
        func.coalesce(func.sum(OperationalPayment.amount), 0).label("amount"),
        func.coalesce(func.sum(OperationalPayment.allocated_amount), 0).label("allocated"),
        func.coalesce(func.sum(OperationalPayment.unallocated_amount), 0).label("advance")
    ).group_by(OperationalPayment.payment_type, OperationalPayment.status).order_by(
        OperationalPayment.payment_type, OperationalPayment.status)).all()]
    return {"trial_balance": {"rows": trial[0], "debit": _money(trial[1]), "credit": _money(trial[2]),
                              "difference": _money(trial[1] - trial[2]),
                              "status": "balanced" if _money(trial[1] - trial[2]) == 0 else "review_required"},
            "journal_blueprints": {"rows": journal[0], "debit": _money(journal[1]), "credit": _money(journal[2]),
                                   "difference": _money(journal[1] - journal[2])},
            "cash_evidence": {"rows": cash[0], "debit": _money(cash[1]), "credit": _money(cash[2]),
                              "net": _money(cash[1] - cash[2])},
            "tax_evidence": {"rows": tax[0], "vat_amount": _money(tax[1])},
            "operational_payment_pipeline": pipeline,
            "source_evidence_only": True, "posting_enabled": False}
