from __future__ import annotations


def allowed_transition(definition, current_state: str, target_state: str) -> bool:
    return any(item.get("from") == current_state and item.get("to") == target_state
               for item in (definition.transitions or []))


def validate_transition(definition, current_state: str, target_state: str) -> None:
    if current_state not in definition.states or target_state not in definition.states:
        raise ValueError("Workflow state is not defined")
    if not allowed_transition(definition, current_state, target_state):
        raise ValueError(f"Transition is not allowed: {current_state} -> {target_state}")
    if not definition.execution_enabled:
        raise RuntimeError("Workflow execution is disabled")
