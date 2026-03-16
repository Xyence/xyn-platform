from __future__ import annotations

from typing import Any, Dict

from ..capability_models import Capability, CapabilityPrecondition


def _token(value: Any) -> str:
    return str(value or "").strip().lower()


def _tokens(value: Any) -> set[str]:
    raw = str(value or "").strip()
    if not raw:
        return set()
    return {_token(part) for part in raw.split(",") if _token(part)}


def _attribute_value(state: Dict[str, Any], key: str) -> str:
    attributes = state.get("attributes")
    if isinstance(attributes, dict) and key in attributes:
        return _token(attributes.get(key))
    return _token(state.get(key))


def evaluate_capability_guard(capability: Capability, entity_state: Dict[str, Any] | None = None) -> bool:
    guard_type = _token(capability.guard_type)
    if not guard_type:
        return True

    state = entity_state if isinstance(entity_state, dict) else {}
    guard_target = capability.guard_target

    if guard_type == "draft_state":
        allowed = _tokens(guard_target)
        return bool(allowed) and _token(state.get("draft_state")) in allowed

    if guard_type == "execution_state":
        execution_state = _token(state.get("execution_state"))
        if _token(guard_target) in {"exists", "any"}:
            return bool(execution_state)
        allowed = _tokens(guard_target)
        return bool(allowed) and execution_state in allowed

    if guard_type == "application_exists":
        return bool(state.get("application_exists"))

    if guard_type == "workspace_state":
        return bool(state.get("workspace_available"))

    if guard_type == "attribute_equals":
        key, _, raw_value = str(guard_target or "").partition(":")
        return bool(key and raw_value) and _attribute_value(state, key) == _token(raw_value)

    if guard_type == "attribute_in":
        key, _, raw_value = str(guard_target or "").partition(":")
        return bool(key and raw_value) and _attribute_value(state, key) in _tokens(raw_value)

    return False


def evaluate_precondition(
    precondition: CapabilityPrecondition,
    entity_state: Dict[str, Any] | None = None,
) -> bool:
    shadow_capability = Capability(
        id="__precondition__",
        name="",
        description="",
        contexts=[],
        prompt_template=None,
        visibility="secondary",
        priority=0,
        guard_type=precondition.guard_type,
        guard_target=precondition.guard_target,
    )
    return evaluate_capability_guard(shadow_capability, entity_state)


def evaluate_capability_availability(
    capability: Capability,
    entity_state: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    state = entity_state if isinstance(entity_state, dict) else {}
    preconditions = list(capability.preconditions or [])
    if not preconditions:
        available = evaluate_capability_guard(capability, state)
        return {
            "available": available,
            "failure_code": None,
            "failure_message": None,
        }

    for precondition in preconditions:
        if evaluate_precondition(precondition, state):
            continue
        return {
            "available": False,
            "failure_code": precondition.failure_code,
            "failure_message": precondition.failure_message,
        }

    return {
        "available": True,
        "failure_code": None,
        "failure_message": None,
    }


def evaluate_path_condition(condition: str | None, entity_state: Dict[str, Any] | None = None) -> bool:
    token = _token(condition)
    if not token:
        return False

    state = entity_state if isinstance(entity_state, dict) else {}
    draft_state = _token(state.get("draft_state"))
    execution_state = _token(state.get("execution_state"))

    if token == "draft_completed":
        return draft_state == "completed"

    if token == "execution_running":
        return execution_state in {"submitted", "queued", "executing"}

    if token == "execution_completed":
        return execution_state == "completed"

    if token == "artifact_exists":
        return bool(state.get("application_exists") or state.get("artifact_exists"))

    if token == "workspace_initialized":
        return bool(state.get("workspace_initialized"))

    return False
