from types import SimpleNamespace

from klen_clone.transactions import movement_readiness, transaction_readiness


def test_transaction_readiness_requires_parent_and_product():
    assert transaction_readiness(True, True) == "migration_locked_ready"
    assert transaction_readiness(False, True) == "review_required_relationship"
    assert transaction_readiness(True, False) == "review_required_relationship"


def test_movement_readiness_never_uses_source_posted_as_target_activation():
    ready = SimpleNamespace(posting_status="posted", quantity_base=1)
    assert movement_readiness(ready, True, True) == "migration_locked_ready"
    assert movement_readiness(ready, True, False) == "review_required_location"
    pending = SimpleNamespace(posting_status="pending_not_posted", quantity_base=1)
    assert movement_readiness(pending, True, True) == "review_required_source_header"
