KNOWN_CONTEXTS = {"landing", "artifact_draft", "application_workspace", "plan_review", "unknown"}


def resolve_context(artifact_id=None, application_id=None, context=None):
    normalized = str(context or "").strip().lower()
    if normalized:
        return normalized if normalized in KNOWN_CONTEXTS else "unknown"
    if artifact_id:
        return "artifact_draft"
    if application_id:
        return "application_workspace"
    return "landing"
