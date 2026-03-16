from dataclasses import dataclass


@dataclass(frozen=True)
class ContextNode:
    id: str
    name: str
    description: str


CONTEXT_NODES = {
    "landing": ContextNode(id="landing", name="Landing", description="Top-level workspace landing guidance."),
    "artifact_detail": ContextNode(id="artifact_detail", name="Artifact Detail", description="Artifact detail and inspection surfaces."),
    "app_intent_draft": ContextNode(id="app_intent_draft", name="Application Draft", description="Application intent draft working context."),
    "application_workspace": ContextNode(id="application_workspace", name="Application Workspace", description="Application workbench and composer context."),
    "artifact_registry": ContextNode(id="artifact_registry", name="Artifact Registry", description="Workspace artifact browsing and installation context."),
    "console": ContextNode(id="console", name="Console", description="Console and workbench command surface."),
    "plan_review": ContextNode(id="plan_review", name="Plan Review", description="Plan inspection and review context."),
    "unknown": ContextNode(id="unknown", name="Unknown", description="Fallback when the current UI context is not recognized."),
}

CONTEXT_ALIASES = {
    "artifact_draft": "artifact_detail",
    "workspace": "application_workspace",
}


def normalize_context_id(context_id: str | None) -> str:
    normalized = str(context_id or "").strip().lower()
    if not normalized:
        return "landing"
    normalized = CONTEXT_ALIASES.get(normalized, normalized)
    return normalized if normalized in CONTEXT_NODES else "unknown"
