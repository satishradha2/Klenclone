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
    StgDocumentLine,
    StgEntityLink,
    StgInventoryMovement,
    StgProduct,
    StgProductUomProfile,
    StgPurchase,
    StgPurchaseLine,
    StgReturn,
    StgSale,
    StgSaleLine,
    StgStockTransfer,
    StgUomDefinition,
)
from .derived import clear_blueprint_outputs

FACTOR_PATTERN = re.compile(r"^(.*?)\s+\((\d+(?:\.\d+)?)\s*([^()]+(?:\([^()]*\))?)\)\s*$")
ALIASES = {
    "pc": "piece", "pcs": "piece", "pc(s)": "piece", "piece": "piece", "pieces": "piece",
    "kg": "kg", "kilogram": "kg", "kilograms": "kg",
    "ctn": "carton", "carton": "carton", "cartons": "carton",
    "pack": "pack", "packs": "pack", "packet": "pack", "packets": "pack",
    "box": "box", "boxes": "box", "dozen": "dozen",
}


def clean_uom(value: str | None) -> str | None:
    text = re.sub(r"\s+", " ", (value or "").replace("\xa0", " ").strip())
    return text or None


def canonical_uom(value: str | None) -> str | None:
    text = clean_uom(value)
    if not text:
        return None
    compact = text.casefold().replace(" ", "")
    if compact in ("pc", "pcs", "pc(s)", "piece", "pieces"):
        return "piece"
    return ALIASES.get(text.casefold(), text.casefold())


def uom_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


def uom_family(value: str | None) -> str | None:
    text = clean_uom(value)
    if not text:
        return None
    return canonical_uom(re.split(r"\s*\(", text, maxsplit=1)[0])


def parse_uom_definition(name: str | None, short_name: str | None) -> dict:
    source_name = clean_uom(name)
    short = clean_uom(short_name)
    result = {
        "canonical_uom": canonical_uom(short or source_name),
        "contained_quantity": None,
        "contained_uom": None,
        "parse_status": "base_only",
        "details": {},
    }
    match = FACTOR_PATTERN.match(source_name or "")
    if not match:
        return result
    factor = Decimal(match.group(2))
    contained = canonical_uom(match.group(3))
    result.update(
        contained_quantity=factor,
        contained_uom=contained,
        parse_status="parsed",
        details={"display_base": clean_uom(match.group(1)), "contained_source_uom": clean_uom(match.group(3))},
    )
    return result


def _resolved_link_map(session: Session, snapshot_id: int, source_kind: str, target_kind: str) -> dict[int, int]:
    return dict(session.execute(select(StgEntityLink.source_id, StgEntityLink.target_id).where(
        StgEntityLink.snapshot_id == snapshot_id,
        StgEntityLink.source_kind == source_kind,
        StgEntityLink.target_kind == target_kind,
        StgEntityLink.status == "resolved",
    )).all())


def build_inventory_snapshot(session: Session, snapshot_name: str) -> dict:
    snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == snapshot_name))
    if not snapshot:
        raise ValueError(f"Unknown snapshot: {snapshot_name}")

    clear_blueprint_outputs(session, snapshot.id)
    session.execute(delete(StgInventoryMovement).where(StgInventoryMovement.snapshot_id == snapshot.id))
    session.execute(delete(StgProductUomProfile).where(StgProductUomProfile.snapshot_id == snapshot.id))
    session.execute(delete(StgUomDefinition).where(StgUomDefinition.snapshot_id == snapshot.id))
    session.execute(delete(ReconciliationException).where(
        ReconciliationException.snapshot_id == snapshot.id,
        ReconciliationException.code.in_(("UOM_REGISTRY_CONFLICT", "UOM_CONVERSION_UNRESOLVED")),
    ))

    unit_rows = session.execute(select(RawRecord).join(RawFileManifest).where(
        RawFileManifest.snapshot_id == snapshot.id,
        RawFileManifest.entity_type == "unit",
        RawRecord.is_presentation_row.is_(False),
    ).order_by(RawRecord.id)).scalars().all()
    definitions: dict[tuple[str, str], set[Decimal]] = defaultdict(set)
    aliases: dict[str, list[dict]] = defaultdict(list)
    for raw in unit_rows:
        payload = raw.payload or {}
        parsed = parse_uom_definition(payload.get("Name"), payload.get("Short name"))
        row = StgUomDefinition(
            snapshot_id=snapshot.id,
            raw_record_id=raw.id,
            source_name=clean_uom(payload.get("Name")) or f"RAW-{raw.id}",
            source_short_name=clean_uom(payload.get("Short name")),
            allow_decimal=True if payload.get("Allow decimal") == "Yes" else False if payload.get("Allow decimal") == "No" else None,
            **parsed,
        )
        session.add(row)
        aliases[parsed["canonical_uom"]].append(parsed)
        if parsed["contained_quantity"] is not None and parsed["canonical_uom"] and parsed["contained_uom"]:
            for source_alias in (payload.get("Name"), payload.get("Short name")):
                if uom_key(source_alias):
                    definitions[(uom_key(source_alias), parsed["contained_uom"])].add(parsed["contained_quantity"])

    conflict_aliases = {}
    for alias, rows in aliases.items():
        signatures = sorted({(str(r["contained_quantity"]), r["contained_uom"]) for r in rows if r["contained_quantity"] is not None})
        if len(signatures) > 1:
            conflict_aliases[alias] = signatures
            session.add(ReconciliationException(
                snapshot_id=snapshot.id, code="UOM_REGISTRY_CONFLICT", severity="critical",
                entity_type="unit", source_key=alias,
                details={"definitions": signatures, "source_rows": len(rows)},
            ))

    products = session.scalars(select(StgProduct).where(StgProduct.snapshot_id == snapshot.id)).all()
    product_by_id = {row.id: row for row in products}
    product_links = {
        kind: _resolved_link_map(session, snapshot.id, kind, "product")
        for kind in ("sale_line", "purchase_line", "document_line")
    }
    sale_headers = {row.id: row for row in session.scalars(select(StgSale).where(StgSale.snapshot_id == snapshot.id))}
    purchase_headers = {row.id: row for row in session.scalars(select(StgPurchase).where(StgPurchase.snapshot_id == snapshot.id))}
    sale_header_links = _resolved_link_map(session, snapshot.id, "sale_line", "sale")
    purchase_header_links = _resolved_link_map(session, snapshot.id, "purchase_line", "purchase")
    transfer_header_links = _resolved_link_map(session, snapshot.id, "document_line", "stock_transfer")
    transfer_headers = {row.id: row for row in session.scalars(select(StgStockTransfer).where(StgStockTransfer.snapshot_id == snapshot.id))}
    returns_by_key = defaultdict(list)
    for row in session.scalars(select(StgReturn).where(StgReturn.snapshot_id == snapshot.id)):
        returns_by_key[(row.direction, row.document_no)].append(row)

    sale_lines = session.scalars(select(StgSaleLine).where(StgSaleLine.snapshot_id == snapshot.id)).all()
    purchase_lines = session.scalars(select(StgPurchaseLine).where(StgPurchaseLine.snapshot_id == snapshot.id)).all()
    document_lines = session.scalars(select(StgDocumentLine).where(
        StgDocumentLine.snapshot_id == snapshot.id,
        StgDocumentLine.source_entity.in_(("sales_return", "purchase_return", "stock_transfer")),
    )).all()
    product_factor_hints: dict[tuple[int, str, str], set[Decimal]] = defaultdict(set)
    for source_kind, rows in (
        ("sale_line", sale_lines),
        ("purchase_line", purchase_lines),
        ("document_line", document_lines),
    ):
        for line in rows:
            product_id = product_links[source_kind].get(line.id)
            product = product_by_id.get(product_id)
            source_family = uom_family(line.unit)
            base_canonical = canonical_uom(product.stock_unit) if product else None
            if not product or not source_family or not base_canonical:
                continue
            if source_family == uom_family(product.stock_unit):
                factor = Decimal("1")
            else:
                candidates = definitions.get((uom_key(line.unit), base_canonical), set())
                if len(candidates) != 1:
                    continue
                factor = next(iter(candidates))
            product_factor_hints[(product.id, source_family, base_canonical)].add(factor)

    observed: dict[int, set[str]] = defaultdict(set)
    unresolved_pairs: Counter[tuple[str | None, str | None]] = Counter()
    movement_counts: Counter[str] = Counter()
    conversion_counts: Counter[str] = Counter()
    posting_counts: Counter[str] = Counter()
    excluded_detail_counts: Counter[str] = Counter()

    def add_movement(*, source_kind: str, source_id: int, document_no: str | None, product_id: int | None,
                     sku: str | None, movement_at, movement_type: str, location: str | None,
                     counterparty_location: str | None, quantity: Decimal | None, unit: str | None,
                     multiplier: Decimal, posting_status: str, details: dict) -> None:
        product = product_by_id.get(product_id)
        source_canonical = canonical_uom(unit)
        base_canonical = canonical_uom(product.stock_unit) if product else None
        factor = None
        conversion_status = "product_unresolved" if not product else "missing_uom"
        if product and source_canonical and base_canonical:
            observed[product.id].add(clean_uom(unit) or source_canonical)
            source_family = uom_family(unit)
            base_family = uom_family(product.stock_unit)
            if source_canonical == base_canonical:
                factor = Decimal("1")
                conversion_status = "identity"
            elif source_family == base_family:
                factor = Decimal("1")
                conversion_status = "identity_family"
            else:
                candidates = definitions.get((uom_key(unit), base_canonical), set())
                if len(candidates) == 1:
                    factor = next(iter(candidates))
                    conversion_status = "explicit_registry"
                else:
                    hints = product_factor_hints.get((product.id, source_family, base_canonical), set())
                    if len(hints) == 1:
                        factor = next(iter(hints))
                        conversion_status = "product_observed"
                    elif len(candidates) > 1:
                        conversion_status = "ambiguous_registry"
                    elif len(hints) > 1:
                        conversion_status = "ambiguous_product_observed"
                    else:
                        conversion_status = "no_conversion_definition"
                if factor is None:
                    unresolved_pairs[(source_canonical, base_canonical)] += 1
        quantity_base = quantity * factor * multiplier if quantity is not None and factor is not None else None
        session.add(StgInventoryMovement(
            snapshot_id=snapshot.id, source_kind=source_kind, source_id=source_id,
            document_no=document_no, product_id=product_id, sku=sku,
            movement_at=movement_at, movement_type=movement_type, location=location,
            counterparty_location=counterparty_location, source_quantity=quantity,
            source_uom=clean_uom(unit), canonical_uom=base_canonical,
            factor_to_base_snapshot=factor, quantity_base=quantity_base,
            conversion_status=conversion_status, posting_status=posting_status,
            details={**details, "direction_multiplier": str(multiplier), "source_canonical_uom": source_canonical},
        ))
        movement_counts[movement_type] += 1
        conversion_counts[conversion_status] += 1
        posting_counts[posting_status] += 1

    for line in sale_lines:
        header = sale_headers.get(sale_header_links.get(line.id))
        add_movement(source_kind="sale_line", source_id=line.id, document_no=line.document_no,
                     product_id=product_links["sale_line"].get(line.id), sku=line.sku,
                     movement_at=line.transaction_at, movement_type="sale_issue",
                     location=header.location if header else None, counterparty_location=None,
                     quantity=line.quantity, unit=line.unit, multiplier=Decimal("-1"),
                     posting_status="posted" if header else "unposted_header_unresolved",
                     details={"header_id": header.id if header else None})

    for line in purchase_lines:
        header = purchase_headers.get(purchase_header_links.get(line.id))
        add_movement(source_kind="purchase_line", source_id=line.id, document_no=line.document_no,
                     product_id=product_links["purchase_line"].get(line.id), sku=line.sku,
                     movement_at=line.transaction_at, movement_type="purchase_receipt",
                     location=header.location if header else None, counterparty_location=None,
                     quantity=line.quantity, unit=line.unit, multiplier=Decimal("1"),
                     posting_status="posted" if header else "unposted_header_unresolved",
                     details={"header_id": header.id if header else None, "adjusted_quantity": str(line.adjusted_quantity) if line.adjusted_quantity is not None else None})

    for line in document_lines:
        product_id = product_links["document_line"].get(line.id)
        if line.source_entity == "stock_transfer":
            header = transfer_headers.get(transfer_header_links.get(line.id))
            status = "posted" if header and (header.status or "").casefold() == "completed" else "pending_not_posted" if header else "unposted_header_unresolved"
            when = header.transaction_at if header else None
            for movement_type, location, counterparty, multiplier in (
                ("transfer_out", line.location_from, line.location_to, Decimal("-1")),
                ("transfer_in", line.location_to, line.location_from, Decimal("1")),
            ):
                add_movement(source_kind="document_line", source_id=line.id, document_no=line.parent_document_no,
                             product_id=product_id, sku=line.sku, movement_at=when,
                             movement_type=movement_type, location=location, counterparty_location=counterparty,
                             quantity=line.quantity, unit=line.unit, multiplier=multiplier,
                             posting_status=status, details={"source_status": header.status if header else None})
        else:
            direction = "sale" if line.source_entity == "sales_return" else "purchase"
            if line.quantity is None or line.quantity == 0:
                excluded_detail_counts[f"{line.source_entity}_zero_or_blank_quantity"] += 1
                continue
            headers = returns_by_key.get((direction, line.parent_document_no), [])
            header = headers[0] if len(headers) == 1 else None
            add_movement(source_kind="document_line", source_id=line.id, document_no=line.parent_document_no,
                         product_id=product_id, sku=line.sku,
                         movement_at=header.transaction_at if header else None,
                         movement_type="sale_return_receipt" if direction == "sale" else "purchase_return_issue",
                         location=header.location if header else None, counterparty_location=None,
                         quantity=line.quantity, unit=line.unit,
                         multiplier=Decimal("1") if direction == "sale" else Decimal("-1"),
                         posting_status="posted" if header else "unposted_header_unresolved",
                         details={"return_header_id": header.id if header else None})

    for product in products:
        units = sorted(observed.get(product.id, set()), key=str.casefold)
        base = canonical_uom(product.stock_unit)
        statuses = set()
        for unit in units:
            source = canonical_uom(unit)
            if source == base:
                statuses.add("identity")
            elif len(definitions.get((uom_key(unit), base), set())) == 1:
                statuses.add("explicit_registry")
            else:
                statuses.add("unresolved")
        profile_status = "unobserved" if not units else "resolved" if "unresolved" not in statuses else "partially_resolved" if len(statuses) > 1 else "unresolved"
        session.add(StgProductUomProfile(
            snapshot_id=snapshot.id, product_id=product.id, sku=product.sku,
            source_base_uom=product.stock_unit, canonical_base_uom=base,
            observed_uoms=units, conversion_status=profile_status,
            details={"conversion_modes": sorted(statuses)},
        ))

    for (source_uom, base_uom), count in sorted(unresolved_pairs.items(), key=lambda row: (str(row[0][0]), str(row[0][1]))):
        session.add(ReconciliationException(
            snapshot_id=snapshot.id, code="UOM_CONVERSION_UNRESOLVED", severity="critical",
            entity_type="inventory_movement", source_key=f"{source_uom or '<missing>'}->{base_uom or '<missing>'}",
            details={"movement_count": count, "source_uom": source_uom, "base_uom": base_uom},
        ))

    session.commit()
    return {
        "uom_definitions": len(unit_rows),
        "uom_conflicting_aliases": len(conflict_aliases),
        "product_uom_profiles": len(products),
        "movement_total": sum(movement_counts.values()),
        "movement_types": dict(movement_counts),
        "conversion_status": dict(conversion_counts),
        "posting_status": dict(posting_counts),
        "excluded_non_movement_details": dict(excluded_detail_counts),
        "unresolved_conversion_pairs": len(unresolved_pairs),
        "posted_quantity_base_available": session.scalar(select(func.count(StgInventoryMovement.id)).where(
            StgInventoryMovement.snapshot_id == snapshot.id,
            StgInventoryMovement.posting_status == "posted",
            StgInventoryMovement.quantity_base.is_not(None),
        )) or 0,
    }
