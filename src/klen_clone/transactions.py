from __future__ import annotations

from collections import Counter, defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .blueprint import location_key
from .models import (
    ErpAuditEvent, ErpInventoryMovement, ErpLocation, ErpMigrationExceptionQueue,
    ErpParty, ErpProductMaster, ErpTransactionDocument, ErpTransactionLine,
    ErpTransactionPayment, ReconciliationException, SourceSnapshot,
    StgEntityLink, StgFinancialAllocation, StgInventoryMovement, StgPayment,
    StgProduct, StgPurchase, StgPurchaseLine, StgReturn, StgSale, StgSaleLine,
    StgStockTransfer, StgDocumentLine,
)


def transaction_readiness(parent_resolved: bool, product_resolved: bool = True) -> str:
    return "migration_locked_ready" if parent_resolved and product_resolved else "review_required_relationship"


def movement_readiness(movement: StgInventoryMovement, product_resolved: bool, location_resolved: bool) -> str:
    if movement.posting_status != "posted":
        return "review_required_source_header"
    if movement.quantity_base is None:
        return "review_required_uom_conversion"
    if not product_resolved:
        return "review_required_product"
    if not location_resolved:
        return "review_required_location"
    return "migration_locked_ready"


def _cache(session: Session, model, key_fields: tuple[str, ...], snapshot_id: int) -> dict[tuple, object]:
    rows = session.scalars(select(model).where(model.snapshot_id == snapshot_id)).all()
    return {tuple(getattr(row, field) for field in key_fields): row for row in rows}


def _ensure(session: Session, model, cache: dict, key: tuple, key_fields: tuple[str, ...], values: dict):
    row = cache.get(key)
    if row:
        for field, expected in values.items():
            if getattr(row, field) != expected:
                raise RuntimeError(f"Immutable transaction mismatch: {model.__name__}.{field} key={key}")
        return row, False
    row = model(**dict(zip(key_fields, key)), **values)
    session.add(row)
    cache[key] = row
    return row, True


def build_canonical_transactions(session: Session, snapshot_name: str) -> dict:
    snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == snapshot_name))
    if not snapshot:
        raise ValueError(f"Unknown snapshot: {snapshot_name}")
    parties = {row.source_contact_id: row for row in session.scalars(select(ErpParty).where(ErpParty.snapshot_id == snapshot.id))}
    products = {row.source_product_id: row for row in session.scalars(select(ErpProductMaster).where(ErpProductMaster.snapshot_id == snapshot.id))}
    if not parties or not products:
        raise RuntimeError("Canonical masters must be built before transactions")
    locations = {location_key(row.name): row for row in session.scalars(select(ErpLocation).where(ErpLocation.snapshot_id == snapshot.id))}

    links = {(row.source_kind, row.source_id, row.target_kind): row for row in session.scalars(
        select(StgEntityLink).where(StgEntityLink.snapshot_id == snapshot.id))}
    allocations = {(row.document_kind, row.header_id): row for row in session.scalars(
        select(StgFinancialAllocation).where(StgFinancialAllocation.snapshot_id == snapshot.id))}
    doc_fields = ("snapshot_id", "source_kind", "source_id")
    docs = _cache(session, ErpTransactionDocument, doc_fields, snapshot.id)
    line_fields = ("snapshot_id", "source_kind", "source_id")
    lines = _cache(session, ErpTransactionLine, line_fields, snapshot.id)
    payment_fields = ("snapshot_id", "source_payment_id")
    payments = _cache(session, ErpTransactionPayment, payment_fields, snapshot.id)
    movement_fields = ("snapshot_id", "source_movement_id")
    movements = _cache(session, ErpInventoryMovement, movement_fields, snapshot.id)
    exception_fields = ("snapshot_id", "source_kind", "source_id", "exception_code")
    exceptions = _cache(session, ErpMigrationExceptionQueue, exception_fields, snapshot.id)
    created = Counter()
    document_statuses = Counter()

    def linked_party(source_kind: str, source_id: int, target_kind: str):
        link = links.get((source_kind, source_id, target_kind))
        return parties.get(link.target_id) if link and link.status == "resolved" else None

    def linked_product(source_kind: str, source_id: int):
        link = links.get((source_kind, source_id, "product"))
        return products.get(link.target_id) if link and link.status == "resolved" else None

    def add_document(source_kind: str, source, party, location_name: str | None, counterparty_name: str | None,
                     total, paid, due, return_due, source_status: str | None, migration_status: str, evidence: dict):
        key = (snapshot.id, source_kind, source.id)
        row, was_created = _ensure(session, ErpTransactionDocument, docs, key, doc_fields,
            {"source_raw_record_id": source.raw_record_id, "document_no": source.document_no,
             "occurred_at": source.transaction_at, "party_id": party.id if party else None,
             "location_id": locations.get(location_key(location_name)).id if locations.get(location_key(location_name)) else None,
             "counterparty_location_id": locations.get(location_key(counterparty_name)).id if locations.get(location_key(counterparty_name)) else None,
             "parent_document_id": None, "total_amount": total, "paid_amount": paid, "due_amount": due,
             "return_due_amount": return_due, "source_status": source_status, "migration_status": migration_status,
             "operational_enabled": False, "posting_enabled": False, "evidence": evidence})
        created["documents"] += was_created
        document_statuses[migration_status] += 1
        return row

    for sale in session.scalars(select(StgSale).where(StgSale.snapshot_id == snapshot.id).order_by(StgSale.id)):
        allocation = allocations.get(("sale", sale.id))
        status = "migration_locked_ready" if allocation and allocation.status == "balanced" else "review_required_financial"
        add_document("sale", sale, linked_party("sale", sale.id, "customer"), sale.location, None,
                     sale.total_amount, sale.total_paid, sale.amount_due, sale.return_due,
                     sale.payment_status, status, {"allocation_id": allocation.id if allocation else None,
                     "allocation_status": allocation.status if allocation else "missing", "added_by": sale.added_by,
                     "source_payment_method": sale.payment_method})

    for purchase in session.scalars(select(StgPurchase).where(StgPurchase.snapshot_id == snapshot.id).order_by(StgPurchase.id)):
        allocation = allocations.get(("purchase", purchase.id))
        status = "migration_locked_ready" if allocation and allocation.status == "balanced" else "review_required_financial"
        add_document("purchase", purchase, linked_party("purchase", purchase.id, "supplier"), purchase.location, None,
                     purchase.total_amount, None, purchase.amount_due, None,
                     purchase.purchase_status, status, {"allocation_id": allocation.id if allocation else None,
                     "allocation_status": allocation.status if allocation else "missing", "payment_status": purchase.payment_status,
                     "supplier_reference": purchase.supplier_reference, "added_by": purchase.added_by})

    for transfer in session.scalars(select(StgStockTransfer).where(StgStockTransfer.snapshot_id == snapshot.id).order_by(StgStockTransfer.id)):
        add_document("stock_transfer", transfer, None, transfer.location_from, transfer.location_to,
                     transfer.total_amount, None, None, None, transfer.status, "migration_locked_ready",
                     {"shipping_charge": str(transfer.shipping_charge) if transfer.shipping_charge is not None else None,
                      "notes": transfer.notes})
    session.flush()

    core_doc_map = {(kind, source_id): row for (_, kind, source_id), row in docs.items()}
    return_docs_by_number: dict[tuple[str, str], list[ErpTransactionDocument]] = defaultdict(list)
    for returned in session.scalars(select(StgReturn).where(StgReturn.snapshot_id == snapshot.id).order_by(StgReturn.id)):
        link = links.get(("return", returned.id, returned.direction))
        parent = core_doc_map.get((returned.direction, link.target_id)) if link and link.status == "resolved" else None
        party = None
        if parent and parent.party_id:
            party = next((row for row in parties.values() if row.id == parent.party_id), None)
        status = "migration_locked_ready" if parent or (link and link.status == "not_applicable") else "review_required_relationship"
        source_kind = f"{returned.direction}_return"
        key = (snapshot.id, source_kind, returned.id)
        row, was_created = _ensure(session, ErpTransactionDocument, docs, key, doc_fields,
            {"source_raw_record_id": returned.raw_record_id, "document_no": returned.document_no,
             "occurred_at": returned.transaction_at, "party_id": party.id if party else None,
             "location_id": locations.get(location_key(returned.location)).id if locations.get(location_key(returned.location)) else None,
             "counterparty_location_id": None, "parent_document_id": parent.id if parent else None,
             "total_amount": returned.total_amount, "paid_amount": None, "due_amount": returned.amount_due,
             "return_due_amount": None, "source_status": returned.payment_status, "migration_status": status,
             "operational_enabled": False, "posting_enabled": False,
             "evidence": {"source_parent_document_no": returned.parent_document_no, "source_contact_name": returned.contact_name,
                          "relationship_status": link.status if link else "missing"}})
        created["documents"] += was_created
        document_statuses[status] += 1
        return_docs_by_number[(source_kind, returned.document_no)].append(row)
    session.flush()
    core_doc_map = {(kind, source_id): row for (_, kind, source_id), row in docs.items()}

    line_statuses = Counter()
    line_to_doc: dict[tuple[str, int], ErpTransactionDocument | None] = {}
    line_sources = [
        ("sale_line", StgSaleLine, "sale", lambda x: (x.quantity, x.unit, x.unit_price, x.total,
          {"document_no": x.document_no, "discount": str(x.discount) if x.discount is not None else None,
           "tax_amount": str(x.tax_amount) if x.tax_amount is not None else None, "gross_profit": str(x.gross_profit) if x.gross_profit is not None else None})),
        ("purchase_line", StgPurchaseLine, "purchase", lambda x: (x.quantity, x.unit, x.unit_price, x.subtotal,
          {"document_no": x.document_no, "adjusted_quantity": str(x.adjusted_quantity) if x.adjusted_quantity is not None else None,
           "supplier_reference": x.supplier_reference})),
    ]
    for source_kind, model, parent_kind, unpack in line_sources:
        for source in session.scalars(select(model).where(model.snapshot_id == snapshot.id).order_by(model.id)):
            parent_link = links.get((source_kind, source.id, parent_kind))
            parent = core_doc_map.get((parent_kind, parent_link.target_id)) if parent_link and parent_link.status == "resolved" else None
            product = linked_product(source_kind, source.id)
            quantity, uom, unit_price, subtotal, evidence = unpack(source)
            status = transaction_readiness(parent is not None, product is not None)
            key = (snapshot.id, source_kind, source.id)
            _, was_created = _ensure(session, ErpTransactionLine, lines, key, line_fields,
                {"source_raw_record_id": source.raw_record_id, "document_id": parent.id if parent else None,
                 "product_id": product.id if product else None, "source_line_no": None,
                 "entered_quantity": quantity, "entered_uom": uom, "unit_price": unit_price, "subtotal": subtotal,
                 "relation_status": status, "operational_enabled": False, "posting_enabled": False,
                 "evidence": {**evidence, "product_name": source.product_name,
                              "parent_link_status": parent_link.status if parent_link else "missing"}})
            line_to_doc[(source_kind, source.id)] = parent
            created["lines"] += was_created
            line_statuses[status] += 1

    for source in session.scalars(select(StgDocumentLine).where(StgDocumentLine.snapshot_id == snapshot.id).order_by(StgDocumentLine.id)):
        if source.source_entity == "stock_transfer":
            parent_link = links.get(("document_line", source.id, "stock_transfer"))
            parent = core_doc_map.get(("stock_transfer", parent_link.target_id)) if parent_link and parent_link.status == "resolved" else None
        else:
            source_kind_for_doc = "sale_return" if source.source_entity == "sales_return" else "purchase_return"
            candidates = return_docs_by_number.get((source_kind_for_doc, source.parent_document_no or ""), [])
            parent = candidates[0] if len(candidates) == 1 else None
            parent_link = None
        product = linked_product("document_line", source.id)
        status = transaction_readiness(parent is not None, product is not None)
        key = (snapshot.id, "document_line", source.id)
        _, was_created = _ensure(session, ErpTransactionLine, lines, key, line_fields,
            {"source_raw_record_id": source.raw_record_id, "document_id": parent.id if parent else None,
             "product_id": product.id if product else None, "source_line_no": source.line_no,
             "entered_quantity": source.quantity, "entered_uom": source.unit, "unit_price": source.unit_price,
             "subtotal": source.subtotal, "relation_status": status, "operational_enabled": False,
             "posting_enabled": False, "evidence": {"source_entity": source.source_entity,
             "source_parent_document_no": source.parent_document_no, "product_name": source.product_name,
             "parent_link_status": parent_link.status if parent_link else ("resolved_by_unique_document" if parent else "unresolved")}})
        line_to_doc[("document_line", source.id)] = parent
        created["lines"] += was_created
        line_statuses[status] += 1

    payment_statuses = Counter()
    for source in session.scalars(select(StgPayment).where(StgPayment.snapshot_id == snapshot.id).order_by(StgPayment.id)):
        link = links.get(("payment", source.id, source.direction))
        parent = core_doc_map.get((source.direction, link.target_id)) if link and link.status == "resolved" else None
        status = transaction_readiness(parent is not None)
        key = (snapshot.id, source.id)
        _, was_created = _ensure(session, ErpTransactionPayment, payments, key, payment_fields,
            {"source_raw_record_id": source.raw_record_id, "document_id": parent.id if parent else None,
             "reference_no": source.reference_no, "paid_at": source.paid_at, "method": source.method,
             "amount": source.amount, "relation_status": status, "operational_enabled": False,
             "posting_enabled": False, "evidence": {"direction": source.direction,
             "source_parent_document_no": source.parent_document_no, "source_contact_name": source.contact_name,
             "parent_link_status": link.status if link else "missing"}})
        created["payments"] += was_created
        payment_statuses[status] += 1

    movement_statuses = Counter()
    for source in session.scalars(select(StgInventoryMovement).where(StgInventoryMovement.snapshot_id == snapshot.id).order_by(StgInventoryMovement.id)):
        product = products.get(source.product_id)
        location = locations.get(location_key(source.location))
        document = line_to_doc.get((source.source_kind, source.source_id))
        status = movement_readiness(source, product is not None, location is not None)
        key = (snapshot.id, source.id)
        _, was_created = _ensure(session, ErpInventoryMovement, movements, key, movement_fields,
            {"product_id": product.id if product else None, "document_id": document.id if document else None,
             "location_id": location.id if location else None, "movement_type": source.movement_type,
             "occurred_at": source.movement_at, "entered_quantity": source.source_quantity,
             "entered_uom": source.source_uom, "factor_to_base_snapshot": source.factor_to_base_snapshot,
             "quantity_base": source.quantity_base, "canonical_uom": source.canonical_uom,
             "source_posting_status": source.posting_status, "migration_status": status,
             "posting_enabled": False, "evidence": {"source_kind": source.source_kind,
             "source_id": source.source_id, "document_no": source.document_no,
             "conversion_status": source.conversion_status, "source_location": source.location,
             "counterparty_location": source.counterparty_location}})
        created["inventory_movements"] += was_created
        movement_statuses[status] += 1

    def queue(source_kind: str, source_id: int, code: str, severity: str, evidence: dict):
        key = (snapshot.id, source_kind, source_id, code)
        _, was_created = _ensure(session, ErpMigrationExceptionQueue, exceptions, key, exception_fields,
            {"severity": severity, "queue_status": "open", "activation_blocked": True, "evidence": evidence})
        created["exceptions"] += was_created

    for (_, source_kind, source_id), row in lines.items():
        if row.relation_status != "migration_locked_ready":
            queue(source_kind, source_id, "TRANSACTION_LINE_RELATIONSHIP", "critical",
                  {"relation_status": row.relation_status, "document_id": row.document_id, "product_id": row.product_id})
    for (_, source_id), row in payments.items():
        if row.relation_status != "migration_locked_ready":
            queue("payment", source_id, "PAYMENT_PARENT_RELATIONSHIP", "critical",
                  {"relation_status": row.relation_status, "reference_no": row.reference_no})
    for (_, source_id), row in movements.items():
        if row.migration_status != "migration_locked_ready":
            queue("inventory_movement", source_id, "INVENTORY_MOVEMENT_READINESS", "critical",
                  {"migration_status": row.migration_status, "source_posting_status": row.source_posting_status})
    for allocation in allocations.values():
        if allocation.status != "balanced":
            queue("financial_allocation", allocation.id, "FINANCIAL_DOCUMENT_REVIEW", "critical",
                  {"document_kind": allocation.document_kind, "document_no": allocation.document_no,
                   "allocation_status": allocation.status})
    for source in session.scalars(select(ReconciliationException).where(ReconciliationException.snapshot_id == snapshot.id)):
        queue("reconciliation_exception", source.id, source.code, source.severity,
              {"entity_type": source.entity_type, "source_key": source.source_key, "details": source.details})

    audit_key = f"canonical-transactions:{sum(document_statuses.values())}:{sum(line_statuses.values())}:{sum(payment_statuses.values())}:{sum(movement_statuses.values())}"
    existing_audit = session.scalar(select(ErpAuditEvent).where(
        ErpAuditEvent.snapshot_id == snapshot.id, ErpAuditEvent.event_key == audit_key))
    if not existing_audit:
        session.add(ErpAuditEvent(snapshot_id=snapshot.id, event_key=audit_key,
            event_type="canonical_transactions_registered", actor_type="migration_service",
            details={"documents": sum(document_statuses.values()), "lines": sum(line_statuses.values()),
                     "payments": sum(payment_statuses.values()), "inventory_movements": sum(movement_statuses.values()),
                     "source_mutated": False, "operational_enabled": False, "posting_enabled": False}))
        created["audit_events"] += 1
    session.commit()

    enabled = sum(session.scalar(select(func.count(model.id)).where(
        model.snapshot_id == snapshot.id, model.posting_enabled.is_(True))) or 0
        for model in (ErpTransactionDocument, ErpTransactionLine, ErpTransactionPayment, ErpInventoryMovement))
    return {"snapshot": snapshot.name, "documents": sum(document_statuses.values()),
            "document_status": dict(document_statuses), "lines": sum(line_statuses.values()),
            "line_status": dict(line_statuses), "payments": sum(payment_statuses.values()),
            "payment_status": dict(payment_statuses), "inventory_movements": sum(movement_statuses.values()),
            "movement_status": dict(movement_statuses), "exception_queue": len(exceptions),
            "posting_enabled_records": enabled, "new_records": dict(created)}
