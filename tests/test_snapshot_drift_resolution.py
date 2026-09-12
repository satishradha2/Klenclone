from pathlib import Path

from klen_clone.resolve_snapshot_drift import build_resolution_evidence, resolution_code


def test_builds_only_checksum_proven_snapshot_relationship_resolutions():
    evidence = build_resolution_evidence(Path("source_exports"))

    assert len(evidence) == 39
    assert evidence[26]["document_no"] == "AK2026-03609"
    assert evidence[26]["location"] == "RAK"
    assert evidence[36]["document_no"] == "AK2026-03607"
    assert evidence[36]["location"] == "SHJ"
    assert evidence[56]["direction"] == "transfer_out"
    assert evidence[57]["direction"] == "transfer_in"
    assert evidence[188]["location_quantity"] == evidence[188]["master_quantity"] == "1.00"
    assert evidence[66]["paid_aed"] == evidence[66]["header_total_aed"] == "29.50"
    assert evidence[107]["due_aed"] == "0.00"
    assert resolution_code(26) == "DETERMINISTIC_MOVEMENT_MAPPING_PROVEN"
    assert resolution_code(103) == "TAX_DOCUMENT_RELATIONSHIP_PROVEN"
    assert resolution_code(66) == "LATER_CAPTURE_SETTLEMENT_RECONCILED"
