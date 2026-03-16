from ..capability_registry import get_capability_by_id
from .capability_paths import get_paths_for_context
from .context_nodes import normalize_context_id


def get_capability_paths_for_context(context: str | None = None, entity_id: str | None = None, workspace_id: str | None = None):
    resolved_context = normalize_context_id(context)
    paths = []
    for path in get_paths_for_context(resolved_context):
        steps = []
        for step in path.steps:
            capability = get_capability_by_id(step.capability_id)
            if capability is None:
                continue
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
                }
            )
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
