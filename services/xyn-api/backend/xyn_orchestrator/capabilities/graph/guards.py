from __future__ import annotations

from typing import Any, Dict

from ..capability_models import Capability


def _token(value: Any) -> str:
    return str(value or "").strip().lower()


def _tokens(value: Any) -> set[str]:
    raw = str(value or "").strip()
    if not raw:
        return set()
    return {_token(part) for part in raw.split(",") if _token(part)}


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

    return False
