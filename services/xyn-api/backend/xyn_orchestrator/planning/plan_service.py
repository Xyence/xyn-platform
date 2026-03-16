from ..capabilities.capability_registry import CAPABILITIES
from .plan_summary_builder import build_plan_summary


def get_plan_for_capability(capability_id: str):
    normalized = str(capability_id or "").strip()
    capability = next((entry for entry in CAPABILITIES if entry.id == normalized), None)
    if capability is None:
        raise ValueError("Unknown capability")
    plan = build_plan_summary(capability)
    return plan.__dict__
