from dataclasses import dataclass

from ..capability_registry import get_capability_by_id
from .context_nodes import CONTEXT_NODES, normalize_context_id


@dataclass(frozen=True)
class CapabilityNode:
    id: str


@dataclass(frozen=True)
class CapabilityEdge:
    context_id: str
    capability_id: str


_CONTEXT_CAPABILITY_IDS = {
    "landing": [
        "build_application",
        "write_article",
        "create_explainer_video",
        "explore_artifacts",
    ],
    "artifact_detail": [
        "view_artifact_details",
        "explore_artifacts",
    ],
    "app_intent_draft": [
        "continue_application_draft",
        "open_application_workspace",
        "view_execution_status",
    ],
    "application_workspace": [
        "continue_application",
        "inspect_application_goals",
        "open_application_workspace",
        "explore_artifacts",
    ],
    "artifact_registry": [
        "explore_artifacts",
        "view_artifact_details",
        "write_article",
        "create_explainer_video",
    ],
    "console": [
        "build_application",
        "explore_artifacts",
        "open_application_workspace",
    ],
    "plan_review": [
        "review_plan",
    ],
    "unknown": [],
}


def get_capability_ids_for_context(context_id: str | None) -> list[str]:
    normalized = normalize_context_id(context_id)
    return list(_CONTEXT_CAPABILITY_IDS.get(normalized, []))


def build_capability_graph() -> dict[str, list]:
    contexts = list(CONTEXT_NODES.values())
    capability_ids = []
    edges = []
    for context_id, context_capability_ids in _CONTEXT_CAPABILITY_IDS.items():
        for capability_id in context_capability_ids:
            if get_capability_by_id(capability_id) is None:
                continue
            capability_ids.append(capability_id)
            edges.append(CapabilityEdge(context_id=context_id, capability_id=capability_id))
    unique_capability_ids = sorted(set(capability_ids))
    capabilities = [CapabilityNode(id=capability_id) for capability_id in unique_capability_ids]
    return {
        "contexts": contexts,
        "capabilities": capabilities,
        "edges": edges,
    }
