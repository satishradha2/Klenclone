import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from klen_clone.data_reviews import (
    OperationalDataReview, enrich_review_source, review_payload, start_review, transaction_review_findings,
    transition_review,
)
from klen_clone.operational import OperationalAuditEvent, initialize_operational_database, make_operational_engine


def test_review_correction_preserves_source_and_requires_verification(tmp_path):
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'reviews.db'}")
    initialize_operational_database(engine)
    with Session(engine) as session:
        source = {"document_no": "INV-1", "total_amount": "100.00", "lines": []}
        review = start_review(session, entity_type="sale", source_record_key="INV-1",
                              source_status="provisional_overlay", original_payload=source, actor="maker")
        session.commit()
        assert review.promotion_eligible is False
        assert "every line" in review.promotion_blocker

        transition_review(session, review, action="flag-incorrect", expected_revision=1,
                          actor="reviewer", rationale="The amount is wrong")
        transition_review(session, review, action="correct", expected_revision=2,
                          actor="reviewer", corrected_payload={"total_amount": "95.00"})
        transition_review(session, review, action="verify", expected_revision=3, actor="reviewer")
        session.commit()

        payload = review_payload(review, posting_enabled=False)
        assert payload["original_payload"] == source
        assert payload["corrected_payload"] == {"total_amount": "95.00"}
        assert payload["status"] == "verified"
        assert payload["promotion_available"] is False
        assert session.scalar(select(OperationalDataReview).where(
            OperationalDataReview.source_record_key == "INV-1")) is review
        assert len(session.scalars(select(OperationalAuditEvent).where(
            OperationalAuditEvent.resource_key == review.review_key)).all()) == 4


def test_review_is_idempotent_and_revision_protected(tmp_path):
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'idempotent-reviews.db'}")
    initialize_operational_database(engine)
    with Session(engine) as session:
        first = start_review(session, entity_type="purchase", source_record_key="PO-1",
                             source_status="review_required", original_payload={"document_no": "PO-1"}, actor="a")
        second = start_review(session, entity_type="purchase", source_record_key="PO-1",
                              source_status="review_required", original_payload={"document_no": "PO-1"}, actor="b")
        assert first is second
        try:
            transition_review(session, first, action="verify", expected_revision=99, actor="a")
            assert False, "revision conflict expected"
        except ValueError as exc:
            assert "revision conflict" in str(exc)


def test_transaction_review_findings_prioritize_material_problems():
    negative = transaction_review_findings(
        total_amount="-0.10", paid_amount="0", due_amount="0", source_status="Paid",
        party_present=True, location_present=True, line_count=1, line_subtotal="0",
        high_value_threshold="1000",
    )
    assert negative["severity"] == "critical"
    assert "negative total" in negative["reasons"][0]

    mismatch = transaction_review_findings(
        total_amount="1000", paid_amount=None, due_amount="0", source_status="Received",
        party_present=True, location_present=True, line_count=3, line_subtotal="500",
        high_value_threshold="5000",
    )
    assert mismatch["severity"] == "high"
    assert any("item subtotal" in reason for reason in mismatch["reasons"])

    clean = transaction_review_findings(
        total_amount="100", paid_amount="100", due_amount="0", source_status="Paid",
        party_present=True, location_present=True, line_count=2, line_subtotal="100",
        high_value_threshold="1000",
    )
    assert clean is None


def test_source_enrichment_preserves_original_and_supersedes_stale_correction(tmp_path):
    engine = make_operational_engine(f"sqlite:///{tmp_path / 'enriched-reviews.db'}")
    initialize_operational_database(engine)
    with Session(engine) as session:
        original = {"document_no": "PO-1", "total_amount": "100.00"}
        review = start_review(session, entity_type="purchase", source_record_key="PO-1",
                              source_status="provisional_overlay", original_payload=original, actor="reviewer")
        transition_review(session, review, action="correct", expected_revision=1, actor="reviewer",
                          corrected_payload={**original, "total_amount": "95.00"})
        complete = {**original, "lines": [{"line_no": 1, "sku": "SKU-1", "subtotal": "100.00"}]}
        assert enrich_review_source(session, review, source_payload=complete, actor="system",
                                    note="Recovered complete baseline item lines") is True
        session.commit()

        payload = review_payload(review)
        assert payload["original_payload"] == original
        assert payload["source_payload"] == complete
        assert payload["corrected_payload"] is None
        assert json.loads(review.superseded_correction_payload)["total_amount"] == "95.00"
        assert payload["status"] == "in_review"
        assert payload["revision"] == 3
        assert enrich_review_source(session, review, source_payload=complete, actor="system",
                                    note="Recovered complete baseline item lines") is False
