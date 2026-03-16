from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .graph.context_nodes import normalize_context_id


@dataclass(frozen=True)
class CapabilityEvent:
    type: str
    entity_id: Optional[str] = None
    workspace_id: Optional[str] = None


def _normalize_event_type(value: str | None) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def contexts_for_event(event: CapabilityEvent) -> List[str]:
    event_type = _normalize_event_type(event.type)
    if event_type == "execution_started":
        return [normalize_context_id(context) for context in ["app_intent_draft", "application_workspace", "console"]]
    if event_type == "execution_completed":
        return [normalize_context_id(context) for context in ["app_intent_draft", "artifact_detail", "application_workspace", "console"]]
    if event_type == "draft_state_changed":
        return [normalize_context_id(context) for context in ["app_intent_draft", "console"]]
    if event_type == "artifact_created":
        return [normalize_context_id(context) for context in ["artifact_detail", "artifact_registry", "application_workspace", "console"]]
    if event_type == "workspace_initialized":
        return [normalize_context_id(context) for context in ["application_workspace", "artifact_registry", "console"]]
    return []
