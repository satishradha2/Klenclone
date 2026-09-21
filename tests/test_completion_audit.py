from klen_clone.completion_audit import IMPLEMENTED_CAPABILITIES, completion_audit_payload


def test_completion_audit_requires_every_declared_operational_route():
    routes = {route for _, _, expected in IMPLEMENTED_CAPABILITIES for route in expected}
    payload = completion_audit_payload(routes)

    assert payload["assessment"] == "incomplete"
    assert payload["summary"]["implemented_staging_capabilities"] == len(IMPLEMENTED_CAPABILITIES)
    assert payload["summary"]["route_regressions"] == 0
    assert payload["summary"]["critical_gaps"] >= 1
    assert payload["scope"] == {
        "hrm_included": True,
        "payroll_excluded": True,
        "bizmodo_read_only": True,
        "test_data_only": True,
        "permanent_posting_enabled": False,
        "production_enabled": False,
    }


def test_completion_audit_never_counts_a_permission_or_label_as_implementation():
    payload = completion_audit_payload(set())

    assert payload["summary"]["implemented_staging_capabilities"] == 0
    assert payload["summary"]["route_regressions"] == len(IMPLEMENTED_CAPABILITIES)
    gaps = {item["capability"]: item["gap"] for item in payload["remaining_gaps"]}
    assert "POS and counter sales" not in gaps
    assert any(item[0] == "pos_counter" for item in IMPLEMENTED_CAPABILITIES)
    assert "Van sales and offline field operation" not in gaps
    assert any(item[0] == "van_sales" for item in IMPLEMENTED_CAPABILITIES)
    pos = next(item for item in payload["implemented"] if item["key"] == "pos_counter")
    assert pos["missing_routes"] == ["/api/v1/pos"]
    assert "Complete employee lifecycle" not in gaps
