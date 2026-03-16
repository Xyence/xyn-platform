from dataclasses import dataclass
from typing import Dict, List, Optional


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
