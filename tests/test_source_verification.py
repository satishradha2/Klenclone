from sqlalchemy.orm import Session

from klen_clone.operational import initialize_operational_database, make_operational_engine
from klen_clone.source_verification import source_verification_counts, verify_source_records


def test_checksum_registry_verifies_every_raw_record_and_replays_idempotently():
    engine = make_operational_engine("sqlite:///:memory:")
    initialize_operational_database(engine)
    records = [
        {"source_raw_record_id": 1, "entity_type": "sale", "source_file": "sales.csv",
         "source_ordinal": 1, "manifest_sha256": "a" * 64, "payload": {"id": 1, "total": "10.00"}},
        {"source_raw_record_id": 2, "entity_type": "product", "source_file": "products.csv",
         "source_ordinal": 1, "manifest_sha256": "b" * 64, "payload": {"sku": "SKU-1"}},
    ]
    with Session(engine) as session:
        result = verify_source_records(session, source_system="BizModo V7.5.1",
            source_snapshot_name="snapshot-1", source_manifest_checksum="c" * 64,
            records=records, actor="business-owner", verification_basis="Explicit bulk approval")
        session.commit()
        replay = verify_source_records(session, source_system="BizModo V7.5.1",
            source_snapshot_name="snapshot-1", source_manifest_checksum="c" * 64,
            records=records, actor="business-owner", verification_basis="Explicit bulk approval")
        assert result["verified_records"] == 2
        assert replay["idempotent_replay"] is True
        assert source_verification_counts(session) == {"batches": 1, "verified_records": 2, "revoked_records": 0}
