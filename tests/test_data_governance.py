from sqlalchemy import select
from sqlalchemy.orm import Session

from klen_clone.data_governance import (
    OperationalPromotionBatch,
    OperationalPromotionException,
    OperationalSourceLineage,
    lifecycle_actions,
    plan_historical_promotion,
    promotion_control_counts,
    resolve_promotion_exception,
)
from klen_clone.operational import OperationalAuditEvent, initialize_operational_database, make_operational_engine


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


def test_historical_promotion_plan_is_nonposting_and_idempotent(tmp_path):
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'history-plan.db'}")
    initialize_operational_database(engine)
    exceptions = [{"source_exception_id": 7, "source_kind": "payment",
                   "reason_code": "PAYMENT_PARENT_RELATIONSHIP",
                   "detail": {"relation_status": "review_required"}}]
    with Session(engine) as session:
        result = plan_historical_promotion(session, source_system="BizModo V7.5.1",
            source_snapshot_name="snapshot-1", source_manifest_checksum="a" * 64,
            expected_records=100, exceptions=exceptions, actor="migration-controller")
        session.commit()
        replay = plan_historical_promotion(session, source_system="BizModo V7.5.1",
            source_snapshot_name="snapshot-1", source_manifest_checksum="a" * 64,
            expected_records=100, exceptions=exceptions, actor="migration-controller")
        assert result["status"] == "planned" and result["posting_enabled"] is False
        assert result["exception_records"] == 1
        assert replay["idempotent_replay"] is True
        assert promotion_control_counts(session) == {"batches": 1, "mapped_records": 0, "open_exceptions": 1}


def test_exception_resolution_preserves_source_detail_and_writes_audit(tmp_path):
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'exception-resolution.db'}")
    initialize_operational_database(engine)
    exceptions = [{"source_exception_id": 7, "source_kind": "sale",
                   "reason_code": "DETAIL_HEADER_DRIFT",
                   "detail": {"document_no": "AK2026-03607", "original": True}}]
    with Session(engine) as session:
        result = plan_historical_promotion(session, source_system="BizModo V7.5.1",
            source_snapshot_name="snapshot-1", source_manifest_checksum="a" * 64,
            expected_records=100, exceptions=exceptions, actor="migration-controller")
        session.flush()
        exception = session.scalar(select(OperationalPromotionException))
        original_detail = exception.detail
        resolved = resolve_promotion_exception(session, batch_key=result["batch_key"],
            source_exception_id=7, actor="evidence-resolver",
            resolution_code="LATER_CAPTURE_RELATIONSHIP_PROVEN",
            evidence={"document_no": "AK2026-03607", "header_rows": 1, "line_rows": 7})
        session.commit()

        session.refresh(exception)
        audit = session.scalar(select(OperationalAuditEvent).where(
            OperationalAuditEvent.event_type == "promotion.exception.resolved"))
        assert resolved["posting_enabled"] is False
        assert exception.status == "resolved" and exception.detail == original_detail
        assert exception.resolved_by == "evidence-resolver" and exception.resolved_at is not None
        assert '"source_exception_modified": false' in audit.detail
        assert promotion_control_counts(session)["open_exceptions"] == 0
        replay = resolve_promotion_exception(session, batch_key=result["batch_key"],
            source_exception_id=7, actor="evidence-resolver",
            resolution_code="LATER_CAPTURE_RELATIONSHIP_PROVEN",
            evidence={"document_no": "AK2026-03607"})
        assert replay["idempotent_replay"] is True
