from dataclasses import dataclass
from typing import Optional


DRAFT = "draft"
PLAN_READY = "plan_ready"
SUBMITTED = "submitted"
QUEUED = "queued"
EXECUTING = "executing"
COMPLETED = "completed"
FAILED = "failed"


@dataclass
class DraftLifecycle:
    draft_id: str
    state: str
    plan_available: bool
    thread_id: Optional[str]
    active_run_id: Optional[str]
    last_run_status: Optional[str]
