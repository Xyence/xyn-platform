from dataclasses import dataclass


@dataclass(frozen=True)
class CapabilityPathStep:
    capability_id: str


@dataclass(frozen=True)
class CapabilityPath:
    id: str
    name: str
    description: str
    contexts: list[str]
    steps: list[CapabilityPathStep]


CAPABILITY_PATHS = [
    CapabilityPath(
        id="build_application",
        name="Build an Application",
        description="Create the application draft, continue design, monitor execution, and open the workspace.",
        contexts=["landing", "console"],
        steps=[
            CapabilityPathStep(capability_id="build_application"),
            CapabilityPathStep(capability_id="continue_application_draft"),
            CapabilityPathStep(capability_id="view_execution_status"),
            CapabilityPathStep(capability_id="open_application_workspace"),
        ],
    ),
    CapabilityPath(
        id="artifact_review",
        name="Review an Artifact",
        description="Inspect the current artifact and branch out into related artifact work.",
        contexts=["artifact_detail"],
        steps=[
            CapabilityPathStep(capability_id="view_artifact_details"),
            CapabilityPathStep(capability_id="explore_artifacts"),
        ],
    ),
    CapabilityPath(
        id="workspace_exploration",
        name="Explore the Workspace",
        description="Continue the application workspace and inspect related goals and artifacts.",
        contexts=["application_workspace", "artifact_registry"],
        steps=[
            CapabilityPathStep(capability_id="open_application_workspace"),
            CapabilityPathStep(capability_id="inspect_application_goals"),
            CapabilityPathStep(capability_id="explore_artifacts"),
        ],
    ),
]


def get_paths_for_context(context_id: str) -> list[CapabilityPath]:
    return [path for path in CAPABILITY_PATHS if context_id in path.contexts]
