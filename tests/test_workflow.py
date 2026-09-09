from types import SimpleNamespace
import pytest

from klen_clone.workflow import allowed_transition, validate_transition


def test_workflow_requires_defined_transition_and_activation():
    definition = SimpleNamespace(states=["draft", "submitted"],
        transitions=[{"from": "draft", "to": "submitted"}], execution_enabled=False)
    assert allowed_transition(definition, "draft", "submitted")
    assert not allowed_transition(definition, "submitted", "draft")
    with pytest.raises(RuntimeError):
        validate_transition(definition, "draft", "submitted")
