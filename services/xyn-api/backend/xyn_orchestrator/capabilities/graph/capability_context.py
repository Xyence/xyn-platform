from __future__ import annotations

from typing import Any, Dict


def _token(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_artifact_type(value: Any) -> str | None:
    token = _token(value)
    if not token:
        return None
    if token in {"application", "article", "explainer_video"}:
        return token
    if token == "workflow":
        return "application"
    if token in {"video", "video_render", "explainer"}:
        return "explainer_video"
    return token


def build_context_attributes(entity_state: Dict[str, Any] | None = None) -> Dict[str, str | bool | None]:
    state = entity_state if isinstance(entity_state, dict) else {}
    artifact_type = normalize_artifact_type(state.get("artifact_type"))
    draft_state = _token(state.get("draft_state")) or None
    execution_state = _token(state.get("execution_state")) or None

    workspace_state = "initialized" if state.get("workspace_initialized") or state.get("workspace_available") else "empty"
    entity_exists = bool(state.get("entity_exists"))

    return {
        "artifact_type": artifact_type,
        "draft_state": draft_state,
        "execution_state": execution_state,
        "workspace_state": workspace_state,
        "entity_exists": entity_exists,
    }
