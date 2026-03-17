from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional
import uuid

from django.db.models import QuerySet

from .models import CoordinationEvent, CoordinationThread, DevTask


THREAD_PRIORITY_ORDER = {
    "critical": 0,
    "high": 1,
    "normal": 2,
    "low": 3,
}

THREAD_STATUS_TRANSITIONS = {
    "queued": {"active", "archived"},
    "active": {"paused", "completed", "archived"},
    "paused": {"active", "archived", "completed"},
    "completed": {"archived", "active"},
    "archived": set(),
}

TERMINAL_WORK_ITEM_STATUSES = {"completed", "succeeded", "failed", "canceled"}
ACTIVE_WORK_ITEM_STATUSES = {"queued", "running", "awaiting_review"}


@dataclass(frozen=True)
class QueueEntry:
    thread_id: str
    work_item_id: str
    task_id: str
    priority_rank: int
    thread_priority: str
    thread_title: str
    sort_key: tuple[Any, ...]


def effective_thread_policy(thread: CoordinationThread) -> Dict[str, Any]:
    stored = thread.execution_policy if isinstance(thread.execution_policy, dict) else {}
    max_runs = int(stored.get("max_concurrent_runs") or thread.work_in_progress_limit or 1)
    return {
        "max_concurrent_runs": max(1, max_runs),
        "pause_on_failure": bool(stored.get("pause_on_failure")),
        "auto_resume": bool(stored.get("auto_resume")),
        "review_required": bool(stored.get("review_required")),
    }


def valid_thread_transition(current_status: str, next_status: str) -> bool:
    current = str(current_status or "").strip().lower()
    nxt = str(next_status or "").strip().lower()
    if current == nxt:
        return True
    return nxt in THREAD_STATUS_TRANSITIONS.get(current, set())


def record_thread_event(
    *,
    thread: CoordinationThread,
    event_type: str,
    work_item: Optional[DevTask] = None,
    run_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> CoordinationEvent:
    normalized_run_id: Optional[str] = None
    if run_id:
        candidate = str(run_id).strip()
        if candidate:
            try:
                normalized_run_id = str(uuid.UUID(candidate))
            except (ValueError, TypeError, AttributeError):
                normalized_run_id = None
    return CoordinationEvent.objects.create(
        thread=thread,
        work_item=work_item,
        run_id=normalized_run_id,
        event_type=str(event_type or "").strip(),
        payload_json=payload or {},
    )


def transition_thread_status(
    thread: CoordinationThread,
    next_status: str,
    *,
    work_item: Optional[DevTask] = None,
    run_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> CoordinationThread:
    if not valid_thread_transition(thread.status, next_status):
        raise ValueError(f"invalid thread status transition: {thread.status} -> {next_status}")
    previous = thread.status
    thread.status = next_status
    thread.save(update_fields=["status", "updated_at"])
    if previous != next_status:
        record_thread_event(
            thread=thread,
            event_type=f"thread_{next_status}",
            work_item=work_item,
            run_id=run_id,
            payload={**(payload or {}), "previous_status": previous, "status": next_status},
        )
    return thread


def active_run_count(
    thread: CoordinationThread,
    *,
    status_lookup: Optional[Callable[[DevTask], str]] = None,
) -> int:
    count = 0
    for task in thread.work_items.all():
        status = status_lookup(task) if callable(status_lookup) else str(task.status or "")
        if str(status).strip().lower() == "running":
            count += 1
    return count


def has_review_block(thread: CoordinationThread, *, status_lookup: Optional[Callable[[DevTask], str]] = None) -> bool:
    for task in thread.work_items.all():
        status = status_lookup(task) if callable(status_lookup) else str(task.status or "")
        if str(status).strip().lower() == "awaiting_review":
            return True
    return False


def eligible_threads(
    threads: Iterable[CoordinationThread],
    *,
    status_lookup: Optional[Callable[[DevTask], str]] = None,
) -> List[CoordinationThread]:
    eligible: List[CoordinationThread] = []
    for thread in threads:
        policy = effective_thread_policy(thread)
        if thread.status not in {"active", "queued"}:
            continue
        if active_run_count(thread, status_lookup=status_lookup) >= policy["max_concurrent_runs"]:
            continue
        if policy.get("review_required") and has_review_block(thread, status_lookup=status_lookup):
            continue
        eligible.append(thread)
    return eligible


def work_item_is_blocked(
    task: DevTask,
    *,
    status_lookup: Optional[Callable[[DevTask], str]] = None,
    task_lookup: Optional[Callable[[str], Optional[DevTask]]] = None,
) -> bool:
    status = (status_lookup(task) if callable(status_lookup) else task.status or "").strip().lower()
    if status != "queued":
        return True
    thread = task.coordination_thread
    if thread is None or thread.status not in {"active", "queued"}:
        return True
    if effective_thread_policy(thread).get("review_required"):
        return True
    dependency_ids = task.dependency_work_item_ids if isinstance(task.dependency_work_item_ids, list) else []
    for reference in dependency_ids:
        dep = task_lookup(str(reference)) if callable(task_lookup) else None
        dep_status = str((status_lookup(dep) if callable(status_lookup) and dep else getattr(dep, "status", "")) or "").strip().lower()
        if dep is None or dep_status not in {"completed", "succeeded"}:
            return True
    return False


def derive_work_queue(
    *,
    threads: QuerySet[CoordinationThread] | Iterable[CoordinationThread],
    status_lookup: Optional[Callable[[DevTask], str]] = None,
    task_lookup: Optional[Callable[[str], Optional[DevTask]]] = None,
) -> List[QueueEntry]:
    ordered_threads = sorted(
        eligible_threads(list(threads), status_lookup=status_lookup),
        key=lambda thread: (
            THREAD_PRIORITY_ORDER.get(str(thread.priority or "normal").strip().lower(), 99),
            thread.created_at,
            str(thread.id),
        ),
    )
    entries: List[QueueEntry] = []
    for thread in ordered_threads:
        candidates = []
        for task in thread.work_items.all().order_by("priority", "created_at", "id"):
            if work_item_is_blocked(task, status_lookup=status_lookup, task_lookup=task_lookup):
                continue
            candidates.append(task)
        if not candidates:
            continue
        task = candidates[0]
        entry = QueueEntry(
            thread_id=str(thread.id),
            work_item_id=str(task.work_item_id or task.id),
            task_id=str(task.id),
            priority_rank=THREAD_PRIORITY_ORDER.get(str(thread.priority or "normal").strip().lower(), 99),
            thread_priority=str(thread.priority or "normal"),
            thread_title=str(thread.title or ""),
            sort_key=(
                THREAD_PRIORITY_ORDER.get(str(thread.priority or "normal").strip().lower(), 99),
                thread.created_at,
                task.priority,
                task.created_at,
                str(task.id),
            ),
        )
        entries.append(entry)
    entries.sort(key=lambda item: item.sort_key)
    return entries
