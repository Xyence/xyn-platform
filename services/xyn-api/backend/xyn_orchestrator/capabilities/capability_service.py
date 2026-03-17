from .capability_registry import get_capabilities_for_context
from .context_resolver import resolve_context


def get_capabilities(context=None, artifact_id=None, application_id=None):
    resolved = resolve_context(artifact_id=artifact_id, application_id=application_id, context=context)
    capabilities = get_capabilities_for_context(resolved)
    return {
        "context": resolved,
        "capabilities": [
            {
                "id": capability.id,
                "name": capability.name,
                "description": capability.description,
                "prompt_template": capability.prompt_template,
                "visibility": capability.visibility,
                "priority": capability.priority,
            }
            for capability in capabilities
        ],
    }
