from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class Capability:
    id: str
    name: str
    description: str
    contexts: List[str]
    prompt_template: Optional[str]
    visibility: str
    priority: int
