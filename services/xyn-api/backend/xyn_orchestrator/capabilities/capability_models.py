from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class CapabilityPrecondition:
    guard_type: str
    guard_target: Optional[str] = None
    failure_code: Optional[str] = None
    failure_message: Optional[str] = None


@dataclass(frozen=True)
class Capability:
    id: str
    name: str
    description: str
    contexts: List[str]
    prompt_template: Optional[str]
    visibility: str
    priority: int
    default_assumptions: Optional[Dict[str, str]] = None
    default_dependencies: Optional[List[str]] = None
    default_components: Optional[List[str]] = None
    generated_artifacts: Optional[List[str]] = None
    action_type: Optional[str] = None
    action_target: Optional[str] = None
    guard_type: Optional[str] = None
    guard_target: Optional[str] = None
    preconditions: List[CapabilityPrecondition] = field(default_factory=list)
