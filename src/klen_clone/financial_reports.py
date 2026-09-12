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
from .payments import OperationalPayment, OperationalPaymentAllocationClaim


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

    rows = []
    for party_code, party in parties.items():
        opening = _money(controls[party_code])
        reserved_submitted = _money(submitted[party_code])
        reserved_approved = _money(approved[party_code])
        control_remaining = max(Decimal("0.00"), opening - reserved_submitted - reserved_approved)
        invoice_outstanding = _money(invoice_totals[party_code])
        source_advance = _money(source_advances[party_code])
        pending_advance = _money(submitted_advances[party_code])
        approved_advance = _money(approved_advances[party_code])
        control_variance = _money(control_remaining - invoice_outstanding)
        row = {**party, "opening_control": opening,
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
        if any(row[key] != 0 for key in ("opening_control", "invoice_evidence_outstanding", "source_advance",
                                          "submitted_allocation", "approved_unposted_allocation",
                                          "submitted_advance", "approved_unposted_advance")):
            rows.append(row)
    needle = query.strip().casefold()
    if needle:
        rows = [row for row in rows if needle in row["party_code"].casefold() or needle in row["party_name"].casefold()]
    rows.sort(key=lambda row: (-abs(row["net_exposure"]), row["party_code"]))
    totals = {key: _money(sum((row[key] for row in rows), Decimal("0"))) for key in (
        "opening_control", "submitted_allocation", "approved_unposted_allocation", "control_outstanding",
        "invoice_evidence_outstanding", "control_variance", "source_advance", "submitted_advance",
        "approved_unposted_advance", "net_exposure", "days_0_30", "days_31_60", "days_61_90",
        "days_91_plus", "undated")}
    return {"ledger_kind": ledger_kind, "party_kind": party_kind, "as_of": as_of,
            "age_basis": "invoice_date", "due_date_available": False,
            "authoritative_total": "approved_opening_control_less_active_allocations",
            "total": len(rows), "limit": limit, "offset": offset,
            "items": rows[offset:offset + limit], "totals": totals,
            "reconciled_parties": sum(row["reconciliation_status"] == "reconciled" for row in rows),
            "review_required_parties": sum(row["reconciliation_status"] == "review_required" for row in rows),
            "posting_enabled": False}


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
