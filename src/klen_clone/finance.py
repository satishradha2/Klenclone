from __future__ import annotations

import re
from collections import Counter, defaultdict
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .models import (
    RawFileManifest,
    RawRecord,
    ReconciliationException,
    SourceSnapshot,
    StgDocumentReconciliation,
    StgFinancialAllocation,
    StgPurchase,
    StgReturn,
    StgSale,
    StgTaxEvidence,
)
from .transform import clean, datetime_value, decimal_value
from .derived import clear_blueprint_outputs

ZERO = Decimal("0")
TOLERANCE = Decimal("0.01")
ROUNDING_LIMIT = Decimal("0.10")


def normalize_party(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def local_datetime_key(value) -> tuple | None:
    if value is None:
        return None
    return value.year, value.month, value.day, value.hour, value.minute, value.second


def expected_document_total(document_kind: str, line_total: Decimal, vat: Decimal, discount: Decimal) -> Decimal:
    if document_kind == "sale":
        return line_total - discount
    if document_kind == "purchase":
        return line_total + vat - discount
    raise ValueError(f"Unsupported document kind: {document_kind}")


def controlled_return_offset(document_kind: str, raw_settlement_residual: Decimal, return_total: Decimal) -> Decimal:
    if (
        document_kind == "sale"
        and return_total != ZERO
        and abs(raw_settlement_residual) > TOLERANCE
        and abs(raw_settlement_residual + return_total) <= TOLERANCE
    ):
        return return_total
    return ZERO


def choose_line_semantics(document_kind: str, header_total: Decimal, line_total: Decimal, vat: Decimal, discount: Decimal) -> tuple[Decimal, str]:
    default = expected_document_total(document_kind, line_total, vat, discount)
    if abs(header_total - default) <= TOLERANCE:
        return default, "includes_tax" if document_kind == "sale" else "excludes_tax"
    if document_kind == "sale":
        if abs(header_total - line_total) <= TOLERANCE:
            return line_total, "includes_tax_and_header_discount"
        excludes_tax = line_total + vat - discount
        if abs(header_total - excludes_tax) <= TOLERANCE:
            return excludes_tax, "excludes_tax"
    else:
        includes_tax = line_total - discount
        if abs(header_total - includes_tax) <= TOLERANCE:
            return includes_tax, "includes_tax"
    return default, "includes_tax" if document_kind == "sale" else "excludes_tax"


def controlled_rounding_adjustment(raw_residual: Decimal, tax_control_variance: Decimal | None) -> Decimal:
    if tax_control_variance is not None and abs(tax_control_variance) <= ROUNDING_LIMIT and abs(raw_residual) <= ROUNDING_LIMIT:
        return raw_residual
    return ZERO


def controlled_settlement_rounding(residual_after_returns: Decimal) -> Decimal:
    return residual_after_returns if abs(residual_after_returns) <= ROUNDING_LIMIT else ZERO


def _candidate(kind: str, row) -> dict:
    return {
        "kind": kind,
        "id": row.id,
        "transaction_at": row.transaction_at,
        "transaction_key": local_datetime_key(row.transaction_at),
        "party": normalize_party(row.customer_name if kind == "sale" else row.supplier_name if kind == "purchase" else row.contact_name),
    }


def build_financial_allocations(session: Session, snapshot_name: str) -> dict:
    snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == snapshot_name))
    if not snapshot:
        raise ValueError(f"Unknown snapshot: {snapshot_name}")

    clear_blueprint_outputs(session, snapshot.id)
    session.execute(delete(StgFinancialAllocation).where(StgFinancialAllocation.snapshot_id == snapshot.id))
    session.execute(delete(StgTaxEvidence).where(StgTaxEvidence.snapshot_id == snapshot.id))
    session.execute(delete(ReconciliationException).where(
        ReconciliationException.snapshot_id == snapshot.id,
        ReconciliationException.code.in_((
            "FINANCIAL_ALLOCATION_RESIDUAL", "SETTLEMENT_RESIDUAL",
            "TAX_EVIDENCE_AMBIGUOUS", "TAX_EVIDENCE_UNMATCHED",
        )),
    ))

    candidates: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in session.scalars(select(StgSale).where(StgSale.snapshot_id == snapshot.id)):
        candidates[("output", row.document_no)].append(_candidate("sale", row))
    for row in session.scalars(select(StgPurchase).where(StgPurchase.snapshot_id == snapshot.id)):
        candidates[("input", row.document_no)].append(_candidate("purchase", row))
    for row in session.scalars(select(StgReturn).where(StgReturn.snapshot_id == snapshot.id)):
        candidates[("output" if row.direction == "sale" else "input", row.document_no)].append(_candidate(f"{row.direction}_return", row))

    raw_rows = session.execute(select(RawRecord, RawFileManifest.entity_type).join(RawFileManifest).where(
        RawFileManifest.snapshot_id == snapshot.id,
        RawFileManifest.entity_type.in_(("tax_output", "tax_input")),
        RawRecord.is_presentation_row.is_(False),
    ).order_by(RawRecord.id)).all()
    tax_doc_counts = Counter()
    for raw, entity in raw_rows:
        payload = raw.payload or {}
        direction = "output" if entity == "tax_output" else "input"
        document_no = clean(payload.get("Invoice No.") if direction == "output" else payload.get("Reference No"))
        tax_doc_counts[(direction, document_no)] += 1

    tax_status_counts: Counter[str] = Counter()
    for raw, entity in raw_rows:
        payload = raw.payload or {}
        direction = "output" if entity == "tax_output" else "input"
        document_no = clean(payload.get("Invoice No.") if direction == "output" else payload.get("Reference No")) or f"RAW-{raw.id}"
        transaction_at = datetime_value(payload.get("Date"))
        party_name = clean(payload.get("Customer") if direction == "output" else payload.get("Supplier"))
        amount_ex_tax = decimal_value(payload.get("Total Amount (Exc. Tax)") if direction == "output" else payload.get("Total amount"))
        amount_with_tax = decimal_value(payload.get("Total amount with tax")) if direction == "output" else None
        discount = decimal_value(payload.get("Discount"))
        vat = decimal_value(payload.get("VAT"))
        possible = list(candidates.get((direction, document_no), []))
        matched = []
        method = "document_exact"
        if possible and transaction_at:
            matched = [row for row in possible if row["transaction_key"] == local_datetime_key(transaction_at)]
            if matched:
                method = "document_datetime_exact"
        if not matched and len(possible) == 1 and tax_doc_counts[(direction, document_no)] == 1:
            matched = possible
            method = "unique_document"
        if len(matched) > 1 and party_name:
            party_matched = [row for row in matched if row["party"] == normalize_party(party_name)]
            if party_matched:
                matched = party_matched
                method += "_party_exact"
        status = "resolved" if len(matched) == 1 else "ambiguous" if matched or possible else "unmatched"
        selected = matched[0] if status == "resolved" else None
        session.add(StgTaxEvidence(
            snapshot_id=snapshot.id, raw_record_id=raw.id, direction=direction,
            document_no=document_no, transaction_at=transaction_at, party_name=party_name,
            tax_number=clean(payload.get("Tax number")), amount_ex_tax=amount_ex_tax,
            amount_with_tax=amount_with_tax, discount_amount=discount, vat_amount=vat,
            payment_method=clean(payload.get("Payment Method")),
            link_kind=selected["kind"] if selected else None, link_id=selected["id"] if selected else None,
            link_status=status, match_method=method, candidate_count=len(matched or possible),
            details={"candidate_kinds": sorted({row["kind"] for row in (matched or possible)})},
        ))
        tax_status_counts[status] += 1
        if status != "resolved":
            session.add(ReconciliationException(
                snapshot_id=snapshot.id,
                code="TAX_EVIDENCE_AMBIGUOUS" if status == "ambiguous" else "TAX_EVIDENCE_UNMATCHED",
                severity="critical" if status == "ambiguous" else "high",
                entity_type=entity, source_key=document_no,
                details={"raw_record_id": raw.id, "candidate_count": len(matched or possible), "transaction_at": str(transaction_at)},
            ))
    session.flush()

    tax_by_target: dict[tuple[str, int], list[StgTaxEvidence]] = defaultdict(list)
    for row in session.scalars(select(StgTaxEvidence).where(
        StgTaxEvidence.snapshot_id == snapshot.id, StgTaxEvidence.link_status == "resolved"
    )):
        tax_by_target[(row.link_kind, row.link_id)].append(row)

    reconciliations = session.scalars(select(StgDocumentReconciliation).where(
        StgDocumentReconciliation.snapshot_id == snapshot.id
    )).all()
    allocation_status_counts: Counter[str] = Counter()
    for rec in reconciliations:
        tax_rows = tax_by_target.get((rec.document_kind, rec.header_id), [])
        tax = tax_rows[0] if len(tax_rows) == 1 else None
        vat = tax.vat_amount if tax else None
        discount = tax.discount_amount if tax else None
        discount_value = discount or ZERO
        vat_value = vat or ZERO
        header_total = rec.header_total or ZERO
        line_total = rec.line_total or ZERO
        payment_total = rec.payment_total or ZERO
        return_total = rec.return_total or ZERO
        due = Decimal(str((rec.details or {}).get("due") or "0"))
        expected_total, line_semantics = choose_line_semantics(rec.document_kind, header_total, line_total, vat_value, discount_value)
        tax_amount_semantics = None
        if rec.document_kind == "sale":
            tax_control_variance = header_total - tax.amount_with_tax if tax and tax.amount_with_tax is not None else None
            tax_amount_semantics = "explicit_with_tax" if tax and tax.amount_with_tax is not None else None
        else:
            tax_control_total = (tax.amount_ex_tax or ZERO) + vat_value - discount_value if tax else None
            tax_amount_semantics = "excludes_tax" if tax else None
            alternative_tax_control = (tax.amount_ex_tax or ZERO) - discount_value if tax else None
            if tax and abs(header_total - tax_control_total) > TOLERANCE and abs(header_total - alternative_tax_control) <= TOLERANCE:
                tax_control_total = alternative_tax_control
                tax_amount_semantics = "includes_tax"
            tax_control_variance = header_total - tax_control_total if tax_control_total is not None else None
        raw_allocation_residual = header_total - expected_total
        rounding_adjustment = controlled_rounding_adjustment(raw_allocation_residual, tax_control_variance)
        allocation_residual = raw_allocation_residual - rounding_adjustment
        raw_settlement_residual = header_total - payment_total - due
        return_settlement_offset = controlled_return_offset(rec.document_kind, raw_settlement_residual, return_total)
        settlement_before_rounding = raw_settlement_residual + return_settlement_offset
        settlement_rounding_adjustment = controlled_settlement_rounding(settlement_before_rounding)
        settlement_residual = settlement_before_rounding - settlement_rounding_adjustment
        allocation_bad = abs(allocation_residual) > TOLERANCE
        settlement_bad = abs(settlement_residual) > TOLERANCE
        source_line_gap = rec.document_kind == "purchase" and allocation_bad and tax_control_variance is not None and abs(tax_control_variance) <= TOLERANCE
        if rec.status == "missing_lines":
            status = "missing_lines"
        elif source_line_gap and settlement_bad:
            status = "source_line_gap_and_settlement_residual"
        elif source_line_gap:
            status = "source_line_gap"
        elif allocation_bad and settlement_bad:
            status = "allocation_and_settlement_residual"
        elif allocation_bad:
            status = "allocation_residual"
        elif settlement_bad:
            status = "settlement_residual"
        else:
            status = "balanced"
        tax_link_status = "resolved" if tax else "multiple" if len(tax_rows) > 1 else "not_linked"
        session.add(StgFinancialAllocation(
            snapshot_id=snapshot.id, document_kind=rec.document_kind, header_id=rec.header_id,
            document_no=rec.document_no, header_total=header_total, line_total=line_total,
            amount_ex_tax=tax.amount_ex_tax if tax else None, vat_amount=vat,
            discount_amount=discount, payment_total=payment_total, due_amount=due,
            return_total=return_total, tax_control_variance=tax_control_variance,
            allocation_residual=allocation_residual, settlement_residual=settlement_residual,
            tax_link_status=tax_link_status, status=status,
            details={"tax_evidence_id": tax.id if tax else None, "line_semantics": line_semantics, "tax_amount_semantics": tax_amount_semantics, "tax_base_line_gap": str((tax.amount_ex_tax or ZERO) - line_total) if rec.document_kind == "purchase" and tax and tax.amount_ex_tax is not None else None, "source_line_gap": source_line_gap, "raw_allocation_residual": str(raw_allocation_residual), "rounding_adjustment": str(rounding_adjustment), "raw_settlement_residual": str(raw_settlement_residual), "return_settlement_offset": str(return_settlement_offset), "settlement_rounding_adjustment": str(settlement_rounding_adjustment), "returns_preserved_unallocated": str(return_total - return_settlement_offset)},
        ))
        allocation_status_counts[status] += 1
        if allocation_bad:
            session.add(ReconciliationException(
                snapshot_id=snapshot.id, code="FINANCIAL_ALLOCATION_RESIDUAL", severity="high",
                entity_type=rec.document_kind, source_key=rec.document_no,
                details={"header_id": rec.header_id, "residual": str(allocation_residual), "tax_link_status": tax_link_status, "classification": "source_line_gap" if source_line_gap else "unclassified_adjustment", "line_semantics": line_semantics},
            ))
        if settlement_bad:
            session.add(ReconciliationException(
                snapshot_id=snapshot.id, code="SETTLEMENT_RESIDUAL", severity="high",
                entity_type=rec.document_kind, source_key=rec.document_no,
                details={"header_id": rec.header_id, "residual": str(settlement_residual), "payment_total": str(payment_total), "due": str(due), "return_total_unallocated": str(return_total - return_settlement_offset)},
            ))

    session.commit()
    return {
        "tax_evidence": len(raw_rows),
        "tax_link_status": dict(tax_status_counts),
        "financial_allocations": len(reconciliations),
        "allocation_status": dict(allocation_status_counts),
        "allocation_residual_total": str(session.scalar(select(func.sum(StgFinancialAllocation.allocation_residual)).where(StgFinancialAllocation.snapshot_id == snapshot.id)) or ZERO),
        "settlement_residual_total": str(session.scalar(select(func.sum(StgFinancialAllocation.settlement_residual)).where(StgFinancialAllocation.snapshot_id == snapshot.id)) or ZERO),
    }
