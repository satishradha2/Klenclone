from sqlalchemy.orm import Session

from klen_clone.data_governance import (
    OperationalPromotionBatch,
    OperationalPromotionException,
    OperationalSourceLineage,
    lifecycle_actions,
    promotion_control_counts,
)
from klen_clone.operational import initialize_operational_database, make_operational_engine


def test_lifecycle_policy_protects_promoted_masters_and_posted_history():
    assert lifecycle_actions("master", "active", referenced=True, source_promoted=True) == ("edit", "deactivate")
    assert lifecycle_actions("master", "active", referenced=False, source_promoted=False) == ("edit", "deactivate", "delete")
    assert lifecycle_actions("master", "inactive") == ("reactivate", "edit")
    assert lifecycle_actions("transaction", "draft") == ("edit", "cancel", "delete")
    assert lifecycle_actions("transaction", "posted") == ("reverse",)
    assert lifecycle_actions("transaction", "historical") == ("view",)


def test_promotion_registry_tracks_mapping_and_exceptions(tmp_path):
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'promotion.db'}")
    initialize_operational_database(engine)
    with Session(engine) as session:
        batch = OperationalPromotionBatch(batch_key="PROMO-1", source_system="BizModo V7.5.1",
            source_snapshot_name="snapshot-1", source_manifest_checksum="a" * 64,
            status="validated", posting_enabled=False, expected_records=2, mapped_records=1,
            exception_records=1, created_by="migration-controller")
        session.add(batch)
        session.flush()
        session.add(OperationalSourceLineage(batch_id=batch.id, source_system="BizModo V7.5.1",
            source_snapshot_name="snapshot-1", entity_type="product", source_record_key="SKU-1",
            source_checksum="b" * 64, operational_table="operational_products",
            operational_record_key="SKU-1", promoted_checksum="b" * 64,
            promotion_status="promoted", lifecycle_status="active"))
        session.add(OperationalPromotionException(batch_id=batch.id, entity_type="product",
            source_record_key="SKU-2", reason_code="missing_uom", detail="UOM approval required"))
        session.commit()
        assert promotion_control_counts(session) == {"batches": 1, "mapped_records": 1, "open_exceptions": 1}
