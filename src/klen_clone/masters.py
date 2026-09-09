from __future__ import annotations

from collections import Counter
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .foundation import _add_once
from .models import (
    ErpApprovalPolicy, ErpAuditEvent, ErpOpeningBalanceQueue, ErpOrganization,
    ErpParty, ErpProductMaster, ErpProductUom, ErpTaxProfile, ErpUomMaster,
    SourceSnapshot, StgContact, StgInventoryOpeningControl, StgProduct,
    StgProductUomProfile, StgUomDefinition,
)

ZERO = Decimal("0")


def party_master_status(contact: StgContact) -> str:
    return "migration_locked_ready" if contact.contact_id and (contact.business_name or contact.name) else "review_required"


def product_master_status(product: StgProduct) -> str:
    if not product.sku or not product.name:
        return "review_required"
    return "migration_locked_ready" if product.tax_name else "review_required_tax_unassigned"


def build_canonical_masters(session: Session, snapshot_name: str) -> dict:
    snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.name == snapshot_name))
    if not snapshot:
        raise ValueError(f"Unknown snapshot: {snapshot_name}")
    organization = session.scalar(select(ErpOrganization).where(ErpOrganization.snapshot_id == snapshot.id))
    if not organization:
        raise RuntimeError("ERP foundation must be built before canonical masters")

    created = Counter()
    tax, was_created = _add_once(session, ErpTaxProfile,
        {"snapshot_id": snapshot.id, "tax_code": "AE-VAT-5"},
        {"name": "UAE VAT 5%", "rate_percent": Decimal("5"), "jurisdiction": "AE",
         "status": "migration_locked", "operational_enabled": False,
         "evidence": {"source_tax_name": "VAT", "source_default_rate_percent": 5, "requires_tax_owner_approval": True}})
    created["tax_profiles"] += was_created

    contacts = list(session.scalars(select(StgContact).where(StgContact.snapshot_id == snapshot.id).order_by(StgContact.id)))
    parties: dict[int, ErpParty] = {}
    party_statuses = Counter()
    for contact in contacts:
        status = party_master_status(contact)
        display_name = contact.business_name or contact.name or f"SOURCE-CONTACT-{contact.id}"
        party, was_created = _add_once(session, ErpParty,
            {"snapshot_id": snapshot.id, "source_contact_id": contact.id},
            {"source_raw_record_id": contact.raw_record_id, "party_code": contact.contact_id or f"RAW-{contact.raw_record_id}",
             "party_kind": contact.kind, "legal_or_business_name": display_name, "contact_name": contact.name,
             "email": contact.email, "mobile": contact.mobile, "address": contact.address, "tax_number": contact.tax_number,
             "master_status": status, "operational_enabled": False,
             "evidence": {"opening_balance": str(contact.opening_balance) if contact.opening_balance is not None else None,
                          "advance_balance": str(contact.advance_balance) if contact.advance_balance is not None else None,
                          "amount_due": str(contact.amount_due) if contact.amount_due is not None else None,
                          "return_due": str(contact.return_due) if contact.return_due is not None else None}})
        parties[contact.id] = party
        created["parties"] += was_created
        party_statuses[status] += 1

    uom_definitions = list(session.scalars(select(StgUomDefinition).where(
        StgUomDefinition.snapshot_id == snapshot.id).order_by(StgUomDefinition.id)))
    uom_statuses = Counter()
    for definition in uom_definitions:
        status = "migration_locked_ready" if definition.parse_status == "parsed" else "migration_locked_base_only"
        _, was_created = _add_once(session, ErpUomMaster,
            {"snapshot_id": snapshot.id, "source_uom_id": definition.id},
            {"source_raw_record_id": definition.raw_record_id, "uom_code": f"SRC-UOM-{definition.id:04d}",
             "source_name": definition.source_name, "source_short_name": definition.source_short_name,
             "canonical_uom": definition.canonical_uom, "allow_decimal": definition.allow_decimal,
             "contained_quantity": definition.contained_quantity, "contained_uom": definition.contained_uom,
             "master_status": status, "operational_enabled": False})
        created["uoms"] += was_created
        uom_statuses[status] += 1

    products = list(session.scalars(select(StgProduct).where(StgProduct.snapshot_id == snapshot.id).order_by(StgProduct.id)))
    product_map: dict[int, ErpProductMaster] = {}
    product_statuses = Counter()
    for product in products:
        status = product_master_status(product)
        canonical, was_created = _add_once(session, ErpProductMaster,
            {"snapshot_id": snapshot.id, "source_product_id": product.id},
            {"source_raw_record_id": product.raw_record_id, "sku": product.sku or f"RAW-{product.raw_record_id}",
             "name": product.name, "product_type": product.product_type, "category_name": product.category,
             "brand_name": product.brand, "source_location_text": product.locations,
             "purchase_price_evidence": product.purchase_price, "selling_price_evidence": product.selling_price,
             "tax_profile_id": tax.id if product.tax_name == "VAT" else None,
             "master_status": status, "operational_enabled": False,
             "evidence": {"source_tax_name": product.tax_name, "source_stock_unit": product.stock_unit,
                          "source_current_stock": str(product.current_stock) if product.current_stock is not None else None}})
        product_map[product.id] = canonical
        created["products"] += was_created
        product_statuses[status] += 1

    profiles = list(session.scalars(select(StgProductUomProfile).where(
        StgProductUomProfile.snapshot_id == snapshot.id).order_by(StgProductUomProfile.id)))
    conversion_statuses = Counter()
    for profile in profiles:
        product = product_map.get(profile.product_id)
        if not product:
            raise RuntimeError(f"Missing canonical product for UOM profile {profile.id}")
        _, was_created = _add_once(session, ErpProductUom,
            {"snapshot_id": snapshot.id, "source_profile_id": profile.id},
            {"product_id": product.id, "source_base_uom": profile.source_base_uom,
             "canonical_base_uom": profile.canonical_base_uom, "factor_to_base_snapshot": Decimal("1"),
             "conversion_status": profile.conversion_status, "operational_enabled": False,
             "evidence": {"observed_uoms": profile.observed_uoms, "source_details": profile.details,
                          "rule": "base identity only; packaging conversions remain source snapshots"}})
        created["product_uoms"] += was_created
        conversion_statuses[profile.conversion_status] += 1

    inventory_policy = session.scalar(select(ErpApprovalPolicy).where(
        ErpApprovalPolicy.snapshot_id == snapshot.id, ErpApprovalPolicy.policy_code == "inventory_opening"))
    if not inventory_policy:
        raise RuntimeError("Inventory opening approval policy is missing")
    opening_statuses = Counter()
    opening_controls = list(session.scalars(select(StgInventoryOpeningControl).where(
        StgInventoryOpeningControl.snapshot_id == snapshot.id).order_by(StgInventoryOpeningControl.id)))
    for control in opening_controls:
        queue_status = "pending_approval" if control.status == "implied_opening_requires_approval" else control.status
        target = product_map.get(control.product_id)
        _, was_created = _add_once(session, ErpOpeningBalanceQueue,
            {"snapshot_id": snapshot.id, "source_kind": "inventory_opening_control", "source_id": control.id,
             "balance_kind": "inventory_quantity"},
            {"target_kind": "product", "target_id": target.id if target else None,
             "amount": None, "quantity": control.implied_opening_quantity, "currency_code": None,
             "uom": control.canonical_uom, "queue_status": queue_status,
             "approval_policy_id": inventory_policy.id, "posting_enabled": False,
             "evidence": {"control_key": control.control_key, "source_status": control.status,
                          "location": control.location, "sub_location": control.sub_location,
                          "closing_quantity": str(control.closing_quantity) if control.closing_quantity is not None else None,
                          "net_supported_movement": str(control.net_supported_movement) if control.net_supported_movement is not None else None,
                          "unresolved_movement_count": control.unresolved_movement_count}})
        created["opening_queue"] += was_created
        opening_statuses[queue_status] += 1

    # The source party masters contain no non-zero explicit opening/advance balances.
    # Current AR/AP due values are preserved as evidence but are not mislabeled as opening balances.
    explicit_party_openings = sum(
        value not in (None, ZERO) for contact in contacts for value in (contact.opening_balance, contact.advance_balance)
    )
    event_key = f"canonical-masters:{len(contacts)}:{len(products)}:{len(uom_definitions)}:{len(opening_controls)}"
    _, was_created = _add_once(session, ErpAuditEvent,
        {"snapshot_id": snapshot.id, "event_key": event_key},
        {"event_type": "canonical_masters_registered", "actor_type": "migration_service",
         "details": {"parties": len(contacts), "products": len(products), "uoms": len(uom_definitions),
                     "product_uoms": len(profiles), "opening_queue": len(opening_controls),
                     "explicit_party_openings": explicit_party_openings, "source_mutated": False,
                     "operational_enabled": False}})
    created["audit_events"] += was_created
    session.commit()

    enabled = (
        session.scalar(select(func.count(ErpParty.id)).where(ErpParty.snapshot_id == snapshot.id, ErpParty.operational_enabled.is_(True)))
        + session.scalar(select(func.count(ErpProductMaster.id)).where(ErpProductMaster.snapshot_id == snapshot.id, ErpProductMaster.operational_enabled.is_(True)))
        + session.scalar(select(func.count(ErpUomMaster.id)).where(ErpUomMaster.snapshot_id == snapshot.id, ErpUomMaster.operational_enabled.is_(True)))
        + session.scalar(select(func.count(ErpProductUom.id)).where(ErpProductUom.snapshot_id == snapshot.id, ErpProductUom.operational_enabled.is_(True)))
        + session.scalar(select(func.count(ErpTaxProfile.id)).where(ErpTaxProfile.snapshot_id == snapshot.id, ErpTaxProfile.operational_enabled.is_(True)))
        + session.scalar(select(func.count(ErpOpeningBalanceQueue.id)).where(ErpOpeningBalanceQueue.snapshot_id == snapshot.id, ErpOpeningBalanceQueue.posting_enabled.is_(True)))
    )
    return {"snapshot": snapshot.name, "parties": len(contacts), "party_status": dict(party_statuses),
            "products": len(products), "product_status": dict(product_statuses),
            "uoms": len(uom_definitions), "uom_status": dict(uom_statuses),
            "product_uoms": len(profiles), "conversion_status": dict(conversion_statuses),
            "tax_profiles": 1, "opening_queue": len(opening_controls),
            "opening_status": dict(opening_statuses), "explicit_party_openings": explicit_party_openings,
            "enabled_or_posting_records": enabled, "new_records": dict(created)}
