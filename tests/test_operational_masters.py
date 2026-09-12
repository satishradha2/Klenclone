from sqlalchemy import func, select
from sqlalchemy.orm import Session

from klen_clone.db import Base, make_engine
from klen_clone.models import ErpLocation, ErpOrganization, ErpParty, ErpProductMaster, RawFileManifest, RawRecord, SourceSnapshot, StgContact, StgProduct
from klen_clone.operational import initialize_operational_database, make_operational_engine
from klen_clone.operational_masters import OperationalLocationMaster, OperationalPartyMaster, OperationalProductMaster, promote_operational_masters
from klen_clone.data_governance import OperationalPromotionBatch, OperationalSourceLineage


def test_promotes_clone_masters_atomically_and_idempotently(tmp_path):
    clone_engine = make_engine(f"sqlite:///{tmp_path / 'clone.db'}")
    Base.metadata.create_all(clone_engine)
    operational_engine = make_operational_engine(f"sqlite:///{tmp_path / 'operational.db'}")
    initialize_operational_database(operational_engine)
    with Session(clone_engine) as clone:
        snapshot = SourceSnapshot(name="snapshot", source_system="BizModo V7.5.1", source_url="https://example.invalid", is_atomic=False)
        clone.add(snapshot); clone.flush()
        manifest = RawFileManifest(snapshot_id=snapshot.id, relative_path="masters.csv", entity_type="masters", sha256="a" * 64, byte_length=1, media_type="text/csv", source_record_count=2)
        clone.add(manifest); clone.flush()
        raw = RawRecord(manifest_id=manifest.id, ordinal=1, source_record_id="1", payload={})
        clone.add(raw); clone.flush()
        product_source = StgProduct(snapshot_id=snapshot.id, raw_record_id=raw.id, sku="SKU-1", name="Product")
        party_source = StgContact(snapshot_id=snapshot.id, raw_record_id=raw.id, kind="customer", contact_id="CO-1", business_name="Customer")
        clone.add_all([product_source, party_source]); clone.flush()
        org = ErpOrganization(snapshot_id=snapshot.id, source_key="org", legal_name="Asas", currency_code="AED", timezone_name="Asia/Dubai", inventory_cost_method="weighted_average", operational_status="preview", posting_enabled=False)
        clone.add(org); clone.flush()
        clone.add(ErpLocation(snapshot_id=snapshot.id, organization_id=org.id, source_key="SHJ", code="SHJ", name="Sharjah", operational_status="preview", posting_enabled=False))
        clone.add(ErpProductMaster(snapshot_id=snapshot.id, source_product_id=product_source.id, source_raw_record_id=raw.id, sku="SKU-1", name="Product", purchase_price_evidence=2, selling_price_evidence=3, master_status="ready", operational_enabled=False))
        clone.add(ErpParty(snapshot_id=snapshot.id, source_contact_id=party_source.id, source_raw_record_id=raw.id, party_code="CO-1", party_kind="customer", legal_or_business_name="Customer", master_status="ready", operational_enabled=False))
        clone.commit()
        snapshot = clone.scalar(select(SourceSnapshot).where(SourceSnapshot.name == "snapshot"))
        with Session(operational_engine) as operational:
            result = promote_operational_masters(clone, operational, snapshot, None, actor="controller")
            assert result["mapped_records"] == 3 and result["posting_enabled"] is False
            replay = promote_operational_masters(clone, operational, snapshot, None, actor="controller")
            assert replay["idempotent_replay"] is True
            assert operational.scalar(select(func.count(OperationalProductMaster.id))) == 1
            assert operational.scalar(select(func.count(OperationalPartyMaster.id))) == 1
            assert operational.scalar(select(func.count(OperationalLocationMaster.id))) == 1
            assert operational.scalar(select(func.count(OperationalSourceLineage.id))) == 3
            assert operational.scalar(select(OperationalPromotionBatch.status)) == "executed"
