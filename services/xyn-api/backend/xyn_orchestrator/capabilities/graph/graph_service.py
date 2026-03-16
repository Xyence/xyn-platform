from ..capability_registry import get_capability_by_id
from .capability_graph import get_capability_ids_for_context
from .context_nodes import normalize_context_id


def get_capabilities_for_context(context: str | None = None, entity_id: str | None = None, workspace_id: str | None = None):
    resolved_context = normalize_context_id(context)
    capabilities = []
    for capability_id in get_capability_ids_for_context(resolved_context):
        capability = get_capability_by_id(capability_id)
        if capability is None:
            continue
        capabilities.append(
            {
                "id": capability.id,
                "name": capability.name,
                "description": capability.description,
                "prompt_template": capability.prompt_template,
                "visibility": capability.visibility,
                "priority": capability.priority,
                "action_type": capability.action_type or "prompt",
                "action_target": capability.action_target,
            }
        )
    return {
        "context": resolved_context,
        "entityId": str(entity_id or "").strip() or None,
        "workspaceId": str(workspace_id or "").strip() or None,
        "capabilities": capabilities,
    }
