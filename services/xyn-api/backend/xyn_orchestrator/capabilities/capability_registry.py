from .capability_models import Capability


CAPABILITIES = [
    Capability(
        id="build_application",
        name="Build an application",
        description="Create a new software application.",
        contexts=["landing"],
        prompt_template="Build an application that...",
        visibility="primary",
        priority=10,
    ),
    Capability(
        id="write_article",
        name="Write an article",
        description="Create a written article artifact.",
        contexts=["landing"],
        prompt_template="Write an article about...",
        visibility="primary",
        priority=9,
    ),
    Capability(
        id="create_explainer_video",
        name="Create an explainer video",
        description="Create a narrated explainer video artifact.",
        contexts=["landing"],
        prompt_template="Create an explainer video explaining...",
        visibility="primary",
        priority=8,
    ),
    Capability(
        id="explore_artifacts",
        name="Explore artifacts",
        description="View existing artifacts in the workspace.",
        contexts=["landing", "application_workspace"],
        prompt_template="Show my artifacts",
        visibility="secondary",
        priority=7,
    ),
    Capability(
        id="revise_draft",
        name="Revise this draft",
        description="Make a targeted change to the draft you are viewing.",
        contexts=["artifact_draft"],
        prompt_template="Revise this draft to...",
        visibility="primary",
        priority=10,
    ),
    Capability(
        id="summarize_draft",
        name="Summarize this draft",
        description="Summarize the current draft before revising it.",
        contexts=["artifact_draft"],
        prompt_template="Summarize this draft and highlight what should change.",
        visibility="secondary",
        priority=7,
    ),
    Capability(
        id="continue_application",
        name="Continue this application",
        description="Advance the current application build from its current state.",
        contexts=["application_workspace"],
        prompt_template="Continue building this application.",
        visibility="primary",
        priority=10,
    ),
    Capability(
        id="inspect_application_goals",
        name="Inspect application goals",
        description="Review the current goals and execution slices for this application.",
        contexts=["application_workspace"],
        prompt_template="Show the current goals for this application.",
        visibility="secondary",
        priority=8,
    ),
    Capability(
        id="review_plan",
        name="Review this plan",
        description="Inspect the generated plan before applying it.",
        contexts=["plan_review"],
        prompt_template="Review this application plan and highlight the next decision.",
        visibility="primary",
        priority=10,
    ),
]


def get_capabilities_for_context(context: str):
    caps = [capability for capability in CAPABILITIES if context in capability.contexts]
    return sorted(caps, key=lambda capability: capability.priority, reverse=True)
