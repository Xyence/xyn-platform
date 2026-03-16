from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class ExecutionPlan:
    capability_id: str
    architecture: Dict
    defaults: Dict
    dependencies: List[str]
    components: List[str]
    generated_commands: List[str]
    artifacts: List[str]
