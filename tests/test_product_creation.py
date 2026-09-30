from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from klen_clone.operational import initialize_operational_database, make_operational_engine
from klen_clone.operational_masters import OperationalProductMaster
from klen_clone.product_creation import (
    ProductEditor, barcode_taken, decide_product, duplicate_key, ean13, generate_barcode,
    product_record, propose_product, propose_product_status,
)
from klen_clone.product_taxonomy import (
    OperationalProductCategory, OperationalUomMaster, backfill_product_taxonomy,
    create_product_taxonomy_value,
)
from klen_clone.warehouse_controls import OperationalBarcodeIdentity, resolve_product_uom


def product(**changes):
    body = {
        "sku": "TST-BOX", "name": "Test box", "category_name": "Packaging", "base_uom": "PCS",
        "barcode": "2000000000008", "specifications": [{"specification_type": "Capacity", "specification_value": "500", "unit_label": "ml"}],
        "uom_conversions": [{"uom": "BOX", "factor_to_base": "12", "pack_level": "outer",
            "barcode": "2300000000009", "is_default_purchase": True, "is_default_sale": True}],
    }
    body.update(changes)
    return ProductEditor.model_validate(body)


def configure_product_choices(session):
    create_product_taxonomy_value(session, "category", "Packaging", actor="setup")
    create_product_taxonomy_value(session, "uom", "PCS", actor="setup")
    create_product_taxonomy_value(session, "uom", "BOX", actor="setup")


def test_product_creation_is_inactive_until_independent_approval(tmp_path):
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'products.db'}")
    initialize_operational_database(engine)
    with Session(engine) as session:
        configure_product_choices(session)
        payload = product()
        request = propose_product(session, payload, actor="maker")
        assert not session.scalar(select(OperationalProductMaster).where(OperationalProductMaster.sku == payload.sku))
        with pytest.raises(ValueError, match="Maker cannot"):
            decide_product(session, request.change_key, actor="maker", action="approve", note="Self approval")
        approved = decide_product(session, request.change_key, actor="reviewer", action="approve", note="Verified product")
        assert approved.status == "approved"
        record = product_record(session, payload.sku)
        assert record["status"] == "active"
        assert record["uom_conversions"][0]["factor_to_base"] == "12.000000"
        assert resolve_product_uom(session, sku=payload.sku, uom="BOX").factor_to_base == Decimal("12")
        assert session.scalar(select(OperationalBarcodeIdentity).where(OperationalBarcodeIdentity.barcode_value == payload.barcode))
        assert barcode_taken(session, payload.uom_conversions[0].barcode)


def test_product_duplicate_and_barcode_immutability(tmp_path):
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'products.db'}")
    initialize_operational_database(engine)
    with Session(engine) as session:
        configure_product_choices(session)
        first = product()
        assert len(generate_barcode(session, sku=first.sku, name=first.name)) == 13
        assert duplicate_key(first) == duplicate_key(product(sku="OTHER", name="Another name"))
        request = propose_product(session, first, actor="maker")
        with pytest.raises(ValueError, match="pending product change"):
            propose_product(session, product(sku="OTHER", name="Other", barcode=None,
                uom_conversions=[{"uom": "BOX", "factor_to_base": "12", "pack_level": "outer"}]), actor="maker")
        decide_product(session, request.change_key, actor="reviewer", action="approve", note="Verified product")
        with pytest.raises(ValueError, match="immutable"):
            propose_product(session, product(barcode=ean13("other master", "20")), actor="maker", expected_revision=1)
        with pytest.raises(ValueError, match="immutable"):
            propose_product(session, product(uom_conversions=[{"uom": "BOX", "factor_to_base": "24",
                "pack_level": "outer", "barcode": "2300000000009"}]), actor="maker", expected_revision=1)
        with pytest.raises(ValueError, match="Duplicate product structure"):
            propose_product(session, product(sku="OTHER", name="Other", barcode=None,
                uom_conversions=[{"uom": "BOX", "factor_to_base": "12", "pack_level": "outer"}]), actor="maker")


def test_rejected_product_does_not_create_active_master(tmp_path):
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'products.db'}")
    initialize_operational_database(engine)
    with Session(engine) as session:
        configure_product_choices(session)
        request = propose_product(session, product(), actor="maker")
        decide_product(session, request.change_key, actor="reviewer", action="reject", note="Invalid classification")
        assert not product_record(session, "TST-BOX")


def test_status_change_is_pending_until_independent_decision(tmp_path):
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'products.db'}")
    initialize_operational_database(engine)
    with Session(engine) as session:
        configure_product_choices(session)
        request = propose_product(session, product(), actor="maker")
        decide_product(session, request.change_key, actor="reviewer", action="approve", note="Verified product")
        status = propose_product_status(session, "TST-BOX", actor="maker", action="deactivate",
            expected_revision=1, note="Discontinued product")
        assert product_record(session, "TST-BOX")["status"] == "active"
        decide_product(session, status.change_key, actor="reviewer", action="approve", note="Discontinuation reviewed")
        assert product_record(session, "TST-BOX")["status"] == "inactive"


def test_promoted_product_editor_defaults_preserve_stock_and_vat(tmp_path):
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'products.db'}")
    initialize_operational_database(engine)
    with Session(engine) as session:
        session.add(OperationalProductMaster(product_key="P-LEGACY", sku="LEGACY", name="Promoted product",
            category_name="Packaging", base_uom="Box", canonical_base_uom="box", factor_to_base=1,
            purchase_price=2, selling_price=3, tax_rate=Decimal("5.0000"), status="active",
            source_promoted=True, source_snapshot_name="test", source_checksum="a" * 64,
            created_by="migration", updated_by="migration"))
        session.commit()
        record = product_record(session, "LEGACY")
        assert record["is_stock_item"] is True
        assert record["sales_vat_rate"] == "5"
        assert record["purchase_vat_rate"] == "5"


def test_product_requires_saved_category_and_every_saved_unit(tmp_path):
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'choices.db'}")
    initialize_operational_database(engine)
    with Session(engine) as session:
        with pytest.raises(ValueError, match="saved product category"):
            propose_product(session, product(), actor="maker")
        create_product_taxonomy_value(session, "category", "Packaging", actor="setup")
        with pytest.raises(ValueError, match="not saved"):
            propose_product(session, product(), actor="maker")
        create_product_taxonomy_value(session, "uom", "PCS", actor="setup")
        with pytest.raises(ValueError, match="BOX.*not saved"):
            propose_product(session, product(), actor="maker")
        create_product_taxonomy_value(session, "uom", "BOX", actor="setup")
        assert propose_product(session, product(), actor="maker").status == "pending"
        with pytest.raises(ValueError, match="already exists"):
            create_product_taxonomy_value(session, "category", " packaging ", actor="setup")


def test_existing_operational_products_backfill_category_and_uom_tables(tmp_path):
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'backfill.db'}")
    initialize_operational_database(engine)
    with Session(engine) as session:
        session.add(OperationalProductMaster(product_key="P-OLD", sku="OLD", name="Old box",
            category_name="Cleaning Supplies", base_uom="Box", canonical_base_uom="box", factor_to_base=1,
            purchase_price=1, selling_price=2, tax_rate=5, status="active", source_promoted=True,
            source_snapshot_name="test", source_checksum="b" * 64, created_by="migration", updated_by="migration"))
        session.commit()
        assert backfill_product_taxonomy(session) == {"categories": 1, "units": 1}
        session.commit()
        assert backfill_product_taxonomy(session) == {"categories": 0, "units": 0}
        assert session.scalar(select(OperationalProductCategory.name)) == "Cleaning Supplies"
        assert session.scalar(select(OperationalUomMaster.name)) == "Box"
