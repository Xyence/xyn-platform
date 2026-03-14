from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

from .execution_briefs import execution_brief_readiness
from .models import DevTask
from .xco import QueueEntry


QUEUE_DISPATCHABLE_TASK_TYPES = {"codegen"}
QUEUE_TERMINAL_STATUSES = {"completed", "succeeded", "failed", "canceled", "blocked"}
QUEUE_ACTIVE_STATUSES = {"queued", "running"}


@dataclass(frozen=True)
class DevTaskQueueState:
    queue_ready: bool
    dispatchable: bool
    dispatched: bool
    blocked: bool
    status: str
    reason: Optional[str]
    message: str


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def evaluate_dev_task_queue_state(
    task: DevTask,
    *,
    normalized_status: Optional[str] = None,
    work_item: Optional[Dict[str, Any]] = None,
) -> DevTaskQueueState:
    status = _clean_text(normalized_status or task.status).lower() or "queued"
    task_type = _clean_text(task.task_type).lower()
    if task_type not in QUEUE_DISPATCHABLE_TASK_TYPES:
        return DevTaskQueueState(
            queue_ready=False,
            dispatchable=False,
            dispatched=False,
            blocked=True,
            status="not_dispatchable",
            reason="unsupported_task_type",
            message="Task is not a coding task and cannot enter the execution queue.",
        )
    if task.runtime_run_id and status in QUEUE_ACTIVE_STATUSES:
        return DevTaskQueueState(
            queue_ready=False,
            dispatchable=False,
            dispatched=True,
            blocked=False,
            status="dispatched",
            reason="in_flight",
            message="Task has already been dispatched and is in progress.",
        )
    if status == "running":
        return DevTaskQueueState(
            queue_ready=False,
            dispatchable=False,
            dispatched=True,
            blocked=False,
            status="dispatched",
            reason="in_flight",
            message="Task is already running.",
        )
    if status == "awaiting_review":
        return DevTaskQueueState(
            queue_ready=False,
            dispatchable=False,
            dispatched=False,
            blocked=True,
            status="blocked",
            reason="awaiting_review",
            message="Task is awaiting review before it can re-enter the execution queue.",
        )
    if status in QUEUE_TERMINAL_STATUSES:
        return DevTaskQueueState(
            queue_ready=False,
            dispatchable=False,
            dispatched=False,
            blocked=False,
            status="terminal",
            reason=f"status_{status}",
            message=f"Task is {status} and is no longer dispatchable.",
        )
    readiness = execution_brief_readiness(task, work_item=work_item)
    if not readiness.executable:
        return DevTaskQueueState(
            queue_ready=False,
            dispatchable=False,
            dispatched=False,
            blocked=True,
            status="blocked",
            reason=readiness.reason,
            message=readiness.message,
        )
    if status != "queued":
        return DevTaskQueueState(
            queue_ready=False,
            dispatchable=False,
            dispatched=False,
            blocked=True,
            status="blocked",
            reason=f"status_{status or 'unknown'}",
            message=f"Task is {status or 'unknown'} and is not ready for queue dispatch.",
        )
    return DevTaskQueueState(
        queue_ready=True,
        dispatchable=True,
        dispatched=False,
        blocked=False,
        status="queue_ready",
        reason=None,
        message=(
            "Task is approved and ready for queue dispatch."
            if readiness.structured_brief
            else "Task is ready for queue dispatch."
        ),
    )


def serialize_dev_task_queue_state(
    task: DevTask,
    *,
    normalized_status: Optional[str] = None,
    work_item: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    state = evaluate_dev_task_queue_state(task, normalized_status=normalized_status, work_item=work_item)
    return {
        "queue_ready": state.queue_ready,
        "dispatchable": state.dispatchable,
        "dispatched": state.dispatched,
        "blocked": state.blocked,
        "status": state.status,
        "reason": state.reason,
        "message": state.message,
    }


def select_next_dispatchable_queue_entry(
    entries: Iterable[QueueEntry],
    *,
    task_lookup: Callable[[str], Optional[DevTask]],
    status_lookup: Callable[[DevTask], str],
) -> Optional[Tuple[QueueEntry, DevTask, DevTaskQueueState]]:
    for entry in entries:
        task = task_lookup(entry.task_id)
        if task is None:
            continue
        state = evaluate_dev_task_queue_state(task, normalized_status=status_lookup(task))
        if state.dispatchable:
            return entry, task, state
    return None
