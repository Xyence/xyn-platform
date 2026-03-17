from ..capabilities.capability_models import Capability
from .plan_models import ExecutionPlan


def build_plan_summary(capability: Capability) -> ExecutionPlan:
    assumptions = capability.default_assumptions or {}
    return ExecutionPlan(
        capability_id=capability.id,
        architecture={
            "interface": assumptions.get("interface"),
            "database": assumptions.get("database"),
            "deployment": assumptions.get("deployment"),
        },
        defaults=assumptions,
        dependencies=list(capability.default_dependencies or []),
        components=list(capability.default_components or []),
        generated_commands=[],
        artifacts=list(capability.generated_artifacts or []),
    )
