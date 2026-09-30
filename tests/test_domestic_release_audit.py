from sqlalchemy import func, select
from sqlalchemy.orm import Session

from klen_clone.db import Base, make_engine
from klen_clone.domestic_release_audit import build_audit, disposition, source_reference
from klen_clone.models import ErpMigrationExceptionQueue, ReconciliationException, SourceSnapshot


def test_disposition_keeps_uncertain_source_links_and_uom_factors_for_review():
    assert "Recapture" in disposition("INVENTORY_MOVEMENT_READINESS", {
        "migration_status": "review_required_source_header"})[2]
    assert "product-specific" in disposition("INVENTORY_MOVEMENT_READINESS", {
        "migration_status": "review_required_uom_conversion"})[2]
    assert "do not match on name alone" in disposition("TRANSACTION_LINE_RELATIONSHIP", {
        "document_id": 1, "product_id": None})[2]


def test_domestic_release_audit_is_read_only_and_does_not_double_count_findings(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'audit.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        snapshot = SourceSnapshot(name="synthetic-audit", source_url="https://synthetic.invalid/",
                                  is_atomic=False)
        session.add(snapshot)
        session.flush()
        session.add(ErpMigrationExceptionQueue(
            snapshot_id=snapshot.id, source_kind="inventory_movement", source_id=42,
            exception_code="INVENTORY_MOVEMENT_READINESS", severity="critical",
            queue_status="open", activation_blocked=True,
            evidence={"migration_status": "review_required_source_header"}))
        session.add(ReconciliationException(
            snapshot_id=snapshot.id, code="INVENTORY_MOVEMENT_READINESS",
            severity="critical", entity_type="inventory_movement", source_key="42",
            details={}, status="open"))
        session.commit()
        summary, rows = build_audit(session, "synthetic-audit")
        assert summary["blocked_migration_items"] == 1
        assert summary["open_reconciliation_findings"] == 1
        assert summary["counts_are_not_additive"] is True
        assert summary["by_area"] == {"Inventory and UOM": 1}
        assert rows[0]["source_id"] == 42
        assert rows[0]["source_reference"] == ""
        assert "Recapture" in rows[0]["required_action"]
        assert session.scalar(select(func.count(ErpMigrationExceptionQueue.id))) == 1


def test_source_reference_keeps_existing_reconciliation_key_without_inference(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'source-reference.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        snapshot = SourceSnapshot(name="reference-audit", source_url="https://synthetic.invalid/",
                                  is_atomic=False)
        session.add(snapshot)
        session.flush()
        finding = ReconciliationException(
            snapshot_id=snapshot.id, code="MISSING_STOCK_LOCATION", severity="critical",
            entity_type="stock", source_key="SOURCE-123", details={}, status="open")
        session.add(finding)
        session.flush()
        item = ErpMigrationExceptionQueue(
            snapshot_id=snapshot.id, source_kind="reconciliation_exception", source_id=finding.id,
            exception_code="MISSING_STOCK_LOCATION", severity="critical",
            queue_status="open", activation_blocked=True, evidence={})
        session.add(item)
        session.flush()
        assert source_reference(session, snapshot.id, item)["source_reference"] == "SOURCE-123"
        summary, rows = build_audit(session, snapshot.name)
        assert summary["blocked_migration_items"] == 1
        assert rows[0]["source_reference"] == "SOURCE-123"
