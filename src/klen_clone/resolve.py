from __future__ import annotations

import re
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .finance import settlement_residual_with_return_due
from .models import (
    SourceSnapshot, StgContact, StgDocumentLine, StgDocumentReconciliation,
    StgEntityLink, StgItemTrace, StgPayment, StgProduct, StgPurchase,
    StgPurchaseLine, StgReturn, StgSale, StgSaleLine, StgStockBalance,
    StgStockTransfer,
)

ZERO = Decimal("0")


def normalize_name(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def _add_link(session: Session, snapshot_id: int, source_kind: str, source_id: int, target_kind: str, candidates: list[int], method: str, details: dict | None = None) -> int | None:
    unique = list(dict.fromkeys(candidates))
    status = "resolved" if len(unique) == 1 else "unmatched" if not unique else "ambiguous"
    target_id = unique[0] if status == "resolved" else None
    session.add(StgEntityLink(snapshot_id=snapshot_id, source_kind=source_kind, source_id=source_id, target_kind=target_kind, target_id=target_id, status=status, match_method=method, candidate_count=len(unique), details=details or {}))
    return target_id


def resolve_snapshot(session: Session, snapshot_name: str) -> dict:
    snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == snapshot_name))
    if not snapshot:
        raise ValueError(f"Unknown snapshot: {snapshot_name}")
    session.execute(delete(StgDocumentReconciliation).where(StgDocumentReconciliation.snapshot_id == snapshot.id))
    session.execute(delete(StgEntityLink).where(StgEntityLink.snapshot_id == snapshot.id))

    products = session.scalars(select(StgProduct).where(StgProduct.snapshot_id == snapshot.id)).all()
    product_by_sku: dict[str, list[int]] = defaultdict(list)
    for product in products:
        if product.sku:
            product_by_sku[product.sku.strip().casefold()].append(product.id)

    contacts = session.scalars(select(StgContact).where(StgContact.snapshot_id == snapshot.id)).all()
    contact_by_id: dict[str, list[int]] = defaultdict(list)
    contact_by_name: dict[tuple[str, str], list[int]] = defaultdict(list)
    for contact in contacts:
        if contact.contact_id:
            contact_by_id[contact.contact_id.casefold()].append(contact.id)
        names = {normalize_name(contact.name), normalize_name(contact.business_name)}
        if contact.name and contact.business_name:
            names.add(normalize_name(f"{contact.business_name}, {contact.name}"))
        for name in names - {""}:
            contact_by_name[(contact.kind, name)].append(contact.id)

    sales = session.scalars(select(StgSale).where(StgSale.snapshot_id == snapshot.id)).all()
    purchases = session.scalars(select(StgPurchase).where(StgPurchase.snapshot_id == snapshot.id)).all()
    sales_by_doc: dict[str, list[StgSale]] = defaultdict(list)
    purchases_by_doc: dict[str, list[StgPurchase]] = defaultdict(list)
    for row in sales: sales_by_doc[row.document_no].append(row)
    for row in purchases: purchases_by_doc[row.document_no].append(row)

    link_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    sale_lines = session.scalars(select(StgSaleLine).where(StgSaleLine.snapshot_id == snapshot.id)).all()
    purchase_lines = session.scalars(select(StgPurchaseLine).where(StgPurchaseLine.snapshot_id == snapshot.id)).all()
    sale_lines_by_header: dict[int, list[StgSaleLine]] = defaultdict(list)
    purchase_lines_by_header: dict[int, list[StgPurchaseLine]] = defaultdict(list)

    for line in sale_lines:
        candidates = sales_by_doc.get(line.document_no, [])
        if len(candidates) > 1 and line.transaction_at:
            dated = [row for row in candidates if row.transaction_at == line.transaction_at]
            candidates = dated or candidates
        if len(candidates) > 1 and line.customer_name:
            named = [row for row in candidates if normalize_name(row.customer_name) == normalize_name(line.customer_name)]
            candidates = named or candidates
        target = _add_link(session, snapshot.id, "sale_line", line.id, "sale", [row.id for row in candidates], "document_date_customer")
        link_counts["sale_line_to_sale"]["resolved" if target else "ambiguous" if candidates else "unmatched"] += 1
        if target: sale_lines_by_header[target].append(line)
        product_candidates = product_by_sku.get((line.sku or "").casefold(), [])
        product_target = _add_link(session, snapshot.id, "sale_line", line.id, "product", product_candidates, "sku_exact")
        link_counts["sale_line_to_product"]["resolved" if product_target else "ambiguous" if product_candidates else "unmatched"] += 1
        contact_candidates = contact_by_id.get((line.contact_id or "").casefold(), [])
        contact_target = _add_link(session, snapshot.id, "sale_line", line.id, "customer", contact_candidates, "contact_id_exact")
        link_counts["sale_line_to_customer"]["resolved" if contact_target else "ambiguous" if contact_candidates else "unmatched"] += 1

    for line in purchase_lines:
        candidates = purchases_by_doc.get(line.document_no, [])
        if len(candidates) > 1 and line.transaction_at:
            dated = [row for row in candidates if row.transaction_at and row.transaction_at.date() == line.transaction_at.date()]
            candidates = dated or candidates
        if len(candidates) > 1 and line.supplier_name:
            named = [row for row in candidates if normalize_name(row.supplier_name) == normalize_name(line.supplier_name)]
            candidates = named or candidates
        target = _add_link(session, snapshot.id, "purchase_line", line.id, "purchase", [row.id for row in candidates], "document_date_supplier")
        link_counts["purchase_line_to_purchase"]["resolved" if target else "ambiguous" if candidates else "unmatched"] += 1
        if target: purchase_lines_by_header[target].append(line)
        product_candidates = product_by_sku.get((line.sku or "").casefold(), [])
        product_target = _add_link(session, snapshot.id, "purchase_line", line.id, "product", product_candidates, "sku_exact")
        link_counts["purchase_line_to_product"]["resolved" if product_target else "ambiguous" if product_candidates else "unmatched"] += 1
        supplier_candidates = contact_by_name.get(("supplier", normalize_name(line.supplier_name)), [])
        supplier_target = _add_link(session, snapshot.id, "purchase_line", line.id, "supplier", supplier_candidates, "normalized_name_exact")
        link_counts["purchase_line_to_supplier"]["resolved" if supplier_target else "ambiguous" if supplier_candidates else "unmatched"] += 1

    for sale in sales:
        contact_ids = {line.contact_id.casefold() for line in sale_lines_by_header.get(sale.id, []) if line.contact_id}
        candidates = [candidate for contact_id in contact_ids for candidate in contact_by_id.get(contact_id, [])]
        if not candidates:
            candidates = contact_by_name.get(("customer", normalize_name(sale.customer_name)), [])
        target = _add_link(session, snapshot.id, "sale", sale.id, "customer", candidates, "line_contact_id_then_name")
        link_counts["sale_to_customer"]["resolved" if target else "ambiguous" if candidates else "unmatched"] += 1

    for purchase in purchases:
        candidates = contact_by_name.get(("supplier", normalize_name(purchase.supplier_name)), [])
        target = _add_link(session, snapshot.id, "purchase", purchase.id, "supplier", candidates, "normalized_name_exact")
        link_counts["purchase_to_supplier"]["resolved" if target else "ambiguous" if candidates else "unmatched"] += 1

    payments = session.scalars(select(StgPayment).where(StgPayment.snapshot_id == snapshot.id)).all()
    payment_by_header: dict[tuple[str, int], list[StgPayment]] = defaultdict(list)
    for payment in payments:
        headers = sales_by_doc.get(payment.parent_document_no, []) if payment.direction == "sale" else purchases_by_doc.get(payment.parent_document_no, [])
        target_kind = payment.direction
        target = _add_link(session, snapshot.id, "payment", payment.id, target_kind, [row.id for row in headers], "parent_document_exact")
        link_counts[f"{payment.direction}_payment_to_header"]["resolved" if target else "ambiguous" if headers else "unmatched"] += 1
        if target: payment_by_header[(payment.direction, target)].append(payment)

    returns = session.scalars(select(StgReturn).where(StgReturn.snapshot_id == snapshot.id)).all()
    return_by_header: dict[tuple[str, int], list[StgReturn]] = defaultdict(list)
    for returned in returns:
        headers = sales_by_doc.get(returned.parent_document_no, []) if returned.direction == "sale" else purchases_by_doc.get(returned.parent_document_no, [])
        if not returned.parent_document_no:
            session.add(StgEntityLink(snapshot_id=snapshot.id, source_kind="return", source_id=returned.id, target_kind=returned.direction, target_id=None, status="not_applicable", match_method="standalone_return", candidate_count=0, details={"standalone": True}))
            link_counts[f"{returned.direction}_return_to_header"]["not_applicable"] += 1
            continue
        target = _add_link(session, snapshot.id, "return", returned.id, returned.direction, [row.id for row in headers], "parent_document_exact")
        link_counts[f"{returned.direction}_return_to_header"]["resolved" if target else "ambiguous" if headers else "unmatched"] += 1
        if target: return_by_header[(returned.direction, target)].append(returned)

    product_by_name = defaultdict(list)
    product_by_name_without_inactive = defaultdict(list)
    for product in products:
        normalized = normalize_name(product.name)
        product_by_name[normalized].append(product.id)
        without_inactive = re.sub(r"\s+inactive$", "", normalized).strip()
        product_by_name_without_inactive[without_inactive].append(product.id)

    sku_sources = (
        ("stock_balance", session.scalars(select(StgStockBalance).where(StgStockBalance.snapshot_id == snapshot.id)).all()),
        ("item_trace", session.scalars(select(StgItemTrace).where(StgItemTrace.snapshot_id == snapshot.id)).all()),
        ("document_line", session.scalars(select(StgDocumentLine).where(StgDocumentLine.snapshot_id == snapshot.id)).all()),
    )
    for kind, rows in sku_sources:
        for row in rows:
            candidates = product_by_sku.get((row.sku or "").casefold(), [])
            method = "sku_exact"
            if not candidates and kind == "document_line" and row.product_name:
                candidates = product_by_name.get(normalize_name(row.product_name), [])
                method = "product_name_exact"
            if not candidates and kind == "document_line" and row.product_name:
                candidates = product_by_name_without_inactive.get(normalize_name(row.product_name), [])
                method = "product_name_exact_ignoring_inactive_suffix"
            target = _add_link(session, snapshot.id, kind, row.id, "product", candidates, method)
            link_counts[f"{kind}_to_product"]["resolved" if target else "ambiguous" if candidates else "unmatched"] += 1

    transfer_by_doc = {row.document_no: row for row in session.scalars(select(StgStockTransfer).where(StgStockTransfer.snapshot_id == snapshot.id))}
    for line in session.scalars(select(StgDocumentLine).where(StgDocumentLine.snapshot_id == snapshot.id, StgDocumentLine.source_entity == "stock_transfer")):
        target = transfer_by_doc.get(line.parent_document_no)
        _add_link(session, snapshot.id, "document_line", line.id, "stock_transfer", [target.id] if target else [], "document_exact")
        link_counts["transfer_line_to_header"]["resolved" if target else "unmatched"] += 1

    for kind, headers, lines_by_header in (("sale", sales, sale_lines_by_header), ("purchase", purchases, purchase_lines_by_header)):
        for header in headers:
            lines = lines_by_header.get(header.id, [])
            line_total = sum(((line.total if kind == "sale" else line.subtotal) or ZERO for line in lines), ZERO)
            linked_payments = payment_by_header.get((kind, header.id), [])
            payment_total = sum((row.amount or ZERO for row in linked_payments), ZERO)
            linked_returns = return_by_header.get((kind, header.id), [])
            return_total = sum((row.total_amount or ZERO for row in linked_returns), ZERO)
            header_total = header.total_amount or ZERO
            due = header.amount_due or ZERO
            return_due = header.return_due or ZERO if kind == "sale" else ZERO
            header_line_variance = header_total - line_total
            settlement_variance = settlement_residual_with_return_due(
                header_total, payment_total, due, return_due
            )
            if not lines:
                status = "missing_lines"
            elif abs(header_line_variance) <= Decimal("0.01") and abs(settlement_variance) <= Decimal("0.01"):
                status = "balanced"
            else:
                status = "requires_adjustment_breakdown"
            session.add(StgDocumentReconciliation(snapshot_id=snapshot.id,document_kind=kind,header_id=header.id,document_no=header.document_no,header_total=header_total,line_total=line_total,payment_total=payment_total,return_total=return_total,header_line_variance=header_line_variance,settlement_variance=settlement_variance,line_count=len(lines),payment_count=len(linked_payments),return_count=len(linked_returns),status=status,details={"due": str(due), "return_due": str(return_due)}))

    session.commit()
    status_counts = dict(session.execute(select(StgEntityLink.status, func.count()).where(StgEntityLink.snapshot_id == snapshot.id).group_by(StgEntityLink.status)).all())
    reconciliation_counts = dict(session.execute(select(StgDocumentReconciliation.status, func.count()).where(StgDocumentReconciliation.snapshot_id == snapshot.id).group_by(StgDocumentReconciliation.status)).all())
    return {"links": {key: dict(value) for key, value in link_counts.items()}, "link_status_totals": status_counts, "document_reconciliations": reconciliation_counts}
