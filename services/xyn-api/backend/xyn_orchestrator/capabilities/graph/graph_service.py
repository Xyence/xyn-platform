from typing import Any, Dict

from ..capability_registry import CAPABILITIES, get_capability_by_id
from .capability_context import build_context_attributes
from .guards import evaluate_capability_availability
from .capability_paths import CAPABILITY_PATHS
from .capability_graph import get_capability_ids_for_context
from .context_nodes import CONTEXT_NODES, normalize_context_id


def get_capabilities_for_context(
    context: str | None = None,
    entity_id: str | None = None,
    workspace_id: str | None = None,
    entity_state: Dict[str, Any] | None = None,
    include_unavailable: bool = False,
):
    resolved_context = normalize_context_id(context)
    capabilities = []
    resolved_state = entity_state if isinstance(entity_state, dict) else {}
    for capability_id in get_capability_ids_for_context(resolved_context):
        capability = get_capability_by_id(capability_id)
        if capability is None:
            continue
        availability = evaluate_capability_availability(capability, resolved_state)
        if not availability["available"] and not include_unavailable:
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
                "available": availability["available"],
                "failure_code": availability["failure_code"],
                "failure_message": availability["failure_message"],
            }
        )
    return {
        "context": resolved_context,
        "attributes": build_context_attributes(resolved_state),
        "entityId": str(entity_id or "").strip() or None,
        "workspaceId": str(workspace_id or "").strip() or None,
        "capabilities": capabilities,
    }


def get_capability_graph_introspection():
    return {
        "contexts": [
            {
                "id": node.id,
                "name": node.name,
                "description": node.description,
            }
            for node in CONTEXT_NODES.values()
        ],
        "capabilities": [
            {
                "id": capability.id,
                "name": capability.name,
                "description": capability.description,
                "contexts": list(capability.contexts),
                "action_type": capability.action_type or "prompt",
                "preconditions": [
                    {
                        "guard_type": precondition.guard_type,
                        "guard_target": precondition.guard_target,
                        "failure_code": precondition.failure_code,
                        "failure_message": precondition.failure_message,
                    }
                    for precondition in capability.preconditions
                ],
            }
            for capability in CAPABILITIES
        ],
        "paths": [
            {
                "id": path.id,
                "name": path.name,
                "description": path.description,
                "contexts": list(path.contexts),
                "steps": [step.capability_id for step in path.steps],
            }
            for path in CAPABILITY_PATHS
        ],
    }
