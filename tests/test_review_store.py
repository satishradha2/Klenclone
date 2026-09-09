import sqlite3

import pytest

from klen_clone.review_store import UatReviewStore


def test_review_store_is_append_only_and_versions_proposals(tmp_path):
    path = tmp_path / "reviews.db"
    store = UatReviewStore(str(path))
    first = store.add_proposal(snapshot_name="snapshot", exception_id=4,
                               resolution_code="request_source_evidence", proposed_value={},
                               rationale="Need supporting evidence", proposed_by="uat.reader",
                               source_exception_fingerprint="a" * 64)
    second = store.add_proposal(snapshot_name="snapshot", exception_id=4,
                                resolution_code="link_document", proposed_value={"document_id": 12},
                                rationale="Supported target relationship", proposed_by="uat.reader",
                                source_exception_fingerprint="a" * 64)
    assert first["proposal_version"] == 1
    assert second["proposal_version"] == 2
    assert store.proposals_for("snapshot", [4])[4][0]["id"] == second["id"]

    with sqlite3.connect(path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute("UPDATE discrepancy_proposals SET rationale='changed' WHERE id=?", (first["id"],))
    with sqlite3.connect(path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute("DELETE FROM discrepancy_proposals WHERE id=?", (first["id"],))


def test_governance_assignments_are_versioned_and_append_only(tmp_path):
    path = tmp_path / "governance.db"
    store = UatReviewStore(str(path))
    first = store.add_governance_assignment(
        function_code="finance_controller", display_name="UAT Finance Controller",
        login_alias="uat.finance.controller", location_codes=["MAIN"],
        threshold_rule="All values", delegation_rule="No delegation")
    second = store.add_governance_assignment(
        function_code="finance_controller", display_name="UAT Finance Controller v2",
        login_alias="uat.finance.controller.v2", location_codes=["MAIN"],
        threshold_rule="All values", delegation_rule="No delegation")
    assert first["assignment_version"] == 1
    assert second["assignment_version"] == 2
    assert store.latest_governance_assignments()["finance_controller"]["id"] == second["id"]
    with sqlite3.connect(path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute("DELETE FROM governance_assignments WHERE id=?", (first["id"],))


def test_business_review_decisions_are_versioned_synthetic_and_append_only(tmp_path):
    path = tmp_path / "business-reviews.db"
    store = UatReviewStore(str(path))
    first = store.add_business_review_decision(
        snapshot_name="snapshot", module_code="inventory", package_sha256="a" * 64,
        decision_code="evidence_requested", rationale="Need evidence for incomplete quantities",
        decided_by="uat.reader", location_codes=["MAIN"])
    second = store.add_business_review_decision(
        snapshot_name="snapshot", module_code="inventory", package_sha256="a" * 64,
        decision_code="conditionally_accepted_for_uat",
        rationale="Accepted only for continued UAT with blockers retained",
        decided_by="uat.reader", location_codes=["MAIN"])
    assert first["decision_version"] == 1
    assert second["decision_version"] == 2
    assert second["synthetic_only"] is True
    assert second["production_signoff"] is False
    assert store.latest_business_review_decisions("snapshot")[0]["id"] == second["id"]
    with sqlite3.connect(path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute("UPDATE business_review_decisions SET rationale='changed' WHERE id=?",
                           (first["id"],))
    with sqlite3.connect(path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute("DELETE FROM business_review_events WHERE decision_id=?", (first["id"],))
