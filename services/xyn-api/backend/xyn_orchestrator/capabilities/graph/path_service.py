from typing import Any, Dict

from ..capability_registry import get_capability_by_id
from .guards import evaluate_capability_guard, evaluate_path_condition
from .capability_paths import get_paths_for_context
from .context_nodes import normalize_context_id


def _step_is_completed(capability_id: str, entity_state: Dict[str, Any]) -> bool:
    draft_state = str(entity_state.get("draft_state") or "").strip().lower()
    execution_state = str(entity_state.get("execution_state") or "").strip().lower()

    if capability_id == "build_application":
        return bool(draft_state or entity_state.get("application_exists"))
    if capability_id == "continue_application_draft":
        return draft_state in {"submitted", "queued", "executing", "completed", "failed"}
    if capability_id == "view_execution_status":
        return execution_state in {"completed", "failed"}
    if capability_id == "open_application_workspace":
        return bool(entity_state.get("workspace_initialized"))
    return False


def get_capability_paths_for_context(
    context: str | None = None,
    entity_id: str | None = None,
    workspace_id: str | None = None,
    entity_state: Dict[str, Any] | None = None,
):
    resolved_context = normalize_context_id(context)
    paths = []
    resolved_state = entity_state if isinstance(entity_state, dict) else {}
    for path in get_paths_for_context(resolved_context):
        steps = []
        current_assigned = False
        ordered_steps = sorted(path.steps, key=lambda step: step.priority if step.priority is not None else 0, reverse=True)
        for step in ordered_steps:
            if evaluate_path_condition(step.skip_if, resolved_state):
                continue
            if evaluate_path_condition(step.stop_if, resolved_state):
                break
            capability = get_capability_by_id(step.capability_id)
            if capability is None:
                continue
            completed = _step_is_completed(capability.id, resolved_state)
            status = "completed"
            if not completed:
                status = "current" if not current_assigned else "pending"
                current_assigned = True
            steps.append(
                {
                    "capability_id": capability.id,
                    "name": capability.name,
                    "description": capability.description,
                    "prompt_template": capability.prompt_template,
                    "visibility": capability.visibility,
                    "priority": capability.priority,
                    "action_type": capability.action_type or "prompt",
                    "action_target": capability.action_target,
                    "available": evaluate_capability_guard(capability, resolved_state),
                    "status": status,
                }
            )
        if not steps:
            continue
        paths.append(
            {
                "id": path.id,
                "name": path.name,
                "description": path.description,
                "steps": steps,
            }
        )
    return {
        "context": resolved_context,
        "entityId": str(entity_id or "").strip() or None,
        "workspaceId": str(workspace_id or "").strip() or None,
        "paths": paths,
    }
