from __future__ import annotations

from typing import Optional

from .definitions import get_lifecycle_definition
from .interfaces import TransitionRequest


class LifecycleError(ValueError):
    """Base lifecycle transition validation error."""


class UnknownLifecycleError(LifecycleError):
    """Raised when a lifecycle definition is not registered."""


class InvalidTransitionError(LifecycleError):
    """Raised when a transition is not allowed."""


class MissingStateError(LifecycleError):
    """Raised when transition request omits required state."""


def normalize_state(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


def validate_transition(request: TransitionRequest) -> None:
    try:
        definition = get_lifecycle_definition(request.lifecycle)
    except KeyError as exc:
        raise UnknownLifecycleError(str(exc)) from exc

    if not str(request.object_type or "").strip():
        raise MissingStateError("object_type is required")
    if not str(request.object_id or "").strip():
        raise MissingStateError("object_id is required")

    target = normalize_state(request.to_state)
    if not target:
        raise MissingStateError("to_state is required")

    from_state = normalize_state(request.from_state)
    if not definition.allows(from_state, target):
        from_label = from_state or "<none>"
        raise InvalidTransitionError(
            f"Illegal transition for lifecycle '{definition.name}': {from_label} -> {target}"
        )
