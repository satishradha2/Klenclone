from types import SimpleNamespace

from klen_clone.residuals import unique_match, workflow_datetime


def test_unique_match_refuses_ambiguous_identity():
    first = SimpleNamespace(id=1)
    second = SimpleNamespace(id=2)
    assert unique_match({"acme": [first]}, "Acme") is first
    assert unique_match({"acme": [first, second]}, "Acme") is None
    assert unique_match({}, "Unknown") is None


def test_workflow_datetime_is_storage_stable():
    assert workflow_datetime("09/08/2026 19:19").tzinfo is None
