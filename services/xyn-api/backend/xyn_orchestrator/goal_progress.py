from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .models import CoordinationThread, DevTask, Goal
from .xco import work_item_is_blocked


COMPLETED_WORK_ITEM_STATUSES = {"completed", "succeeded"}
ACTIVE_WORK_ITEM_STATUSES = {"running"}
UNFINISHED_WORK_ITEM_STATUSES = {"queued", "running", "awaiting_review", "failed", "canceled"}


@dataclass(frozen=True)
class GoalProgressSnapshot:
    goal_progress_status: str
    completed_work_items: int
    active_work_items: int
    blocked_work_items: int


@dataclass(frozen=True)
class ThreadProgressSnapshot:
    thread_status: str
    work_items_completed: int
    work_items_ready: int
    work_items_blocked: int


@dataclass(frozen=True)
class DevelopmentLoopThreadSummary:
    thread_id: str
    title: str
    thread_status: str


@dataclass(frozen=True)
class DevelopmentLoopRecentResult:
    work_item_id: str
    title: str
    status: str
    run_id: Optional[str]


@dataclass(frozen=True)
class GoalDevelopmentLoopSummary:
    goal_status: str
    threads: List[DevelopmentLoopThreadSummary]
    recent_work_results: List[DevelopmentLoopRecentResult]
    recommended_next_slice: Optional[Dict[str, object]]


def _task_lookup_for_goal(goal: Goal) -> Callable[[str], Optional[DevTask]]:
    task_map: Dict[str, DevTask] = {}
    for task in goal.work_items.all():
        key = str(task.work_item_id or "").strip()
        if key:
            task_map[key] = task
    return lambda work_item_id: task_map.get(str(work_item_id or "").strip())


def _task_lookup_for_thread(thread: CoordinationThread) -> Callable[[str], Optional[DevTask]]:
    task_map: Dict[str, DevTask] = {}
    tasks = thread.goal.work_items.all() if thread.goal_id else thread.work_items.all()
    for task in tasks:
        key = str(task.work_item_id or "").strip()
        if key:
            task_map[key] = task
    return lambda work_item_id: task_map.get(str(work_item_id or "").strip())


def _is_ready(task: DevTask, *, task_lookup: Callable[[str], Optional[DevTask]]) -> bool:
    return str(task.status or "").strip().lower() == "queued" and not work_item_is_blocked(
        task,
        status_lookup=lambda candidate: str(getattr(candidate, "status", "") or ""),
        task_lookup=task_lookup,
    )


def compute_thread_progress(thread: CoordinationThread) -> ThreadProgressSnapshot:
    tasks = list(thread.work_items.all())
    if not tasks:
        return ThreadProgressSnapshot(
            thread_status="not_started",
            work_items_completed=0,
            work_items_ready=0,
            work_items_blocked=0,
        )

    task_lookup = _task_lookup_for_thread(thread)
    completed = 0
    ready = 0
    blocked = 0
    unfinished = 0

    for task in tasks:
        status = str(task.status or "").strip().lower()
        if status in COMPLETED_WORK_ITEM_STATUSES:
            completed += 1
            continue
        if status in UNFINISHED_WORK_ITEM_STATUSES:
            unfinished += 1
        if status in ACTIVE_WORK_ITEM_STATUSES or _is_ready(task, task_lookup=task_lookup):
            ready += 1
            continue
        blocked += 1

    if unfinished == 0:
        thread_status = "completed"
    elif ready > 0:
        thread_status = "active"
    elif blocked > 0:
        thread_status = "blocked"
    else:
        thread_status = "not_started"

    return ThreadProgressSnapshot(
        thread_status=thread_status,
        work_items_completed=completed,
        work_items_ready=ready,
        work_items_blocked=blocked,
    )


def compute_goal_progress(goal: Goal) -> GoalProgressSnapshot:
    tasks = list(goal.work_items.select_related("coordination_thread").all())
    if not tasks:
        return GoalProgressSnapshot(
            goal_progress_status="not_started",
            completed_work_items=0,
            active_work_items=0,
            blocked_work_items=0,
        )

    task_lookup = _task_lookup_for_goal(goal)
    completed = 0
    active = 0
    blocked = 0
    unfinished = 0

    for task in tasks:
        status = str(task.status or "").strip().lower()
        if status in COMPLETED_WORK_ITEM_STATUSES:
            completed += 1
            continue
        if status in UNFINISHED_WORK_ITEM_STATUSES:
            unfinished += 1
        if status in ACTIVE_WORK_ITEM_STATUSES or _is_ready(task, task_lookup=task_lookup):
            active += 1
            continue
        blocked += 1

    if unfinished == 0:
        goal_status = "completed"
    elif active == 0 and blocked > 0:
        goal_status = "stalled"
    elif completed > 0 and completed / max(len(tasks), 1) >= 0.8 and unfinished <= 2:
        goal_status = "nearing_completion"
    else:
        goal_status = "in_progress"

    return GoalProgressSnapshot(
        goal_progress_status=goal_status,
        completed_work_items=completed,
        active_work_items=active,
        blocked_work_items=blocked,
    )


def compute_goal_development_loop_summary(goal: Goal, *, recommendation: Optional[object] = None) -> GoalDevelopmentLoopSummary:
    thread_rows = [
        DevelopmentLoopThreadSummary(
            thread_id=str(thread.id),
            title=str(thread.title),
            thread_status=compute_thread_progress(thread).thread_status,
        )
        for thread in goal.threads.all().order_by("created_at", "id")
    ]
    recent_results: List[DevelopmentLoopRecentResult] = []
    for task in goal.work_items.all().order_by("-updated_at", "-created_at")[:5]:
        status = str(task.status or "").strip().lower()
        if status not in COMPLETED_WORK_ITEM_STATUSES | {"running", "awaiting_review", "failed", "canceled"}:
            continue
        recent_results.append(
            DevelopmentLoopRecentResult(
                work_item_id=str(task.work_item_id or task.id),
                title=str(task.title),
                status=status,
                run_id=str(task.runtime_run_id) if task.runtime_run_id else None,
            )
        )
    recommended_next_slice = None
    if recommendation is not None:
        recommended_next_slice = {
            "recommendation_id": getattr(recommendation, "recommendation_id", None),
            "goal_id": getattr(recommendation, "goal_id", ""),
            "thread_id": getattr(recommendation, "thread_id", None),
            "thread_title": getattr(recommendation, "thread_title", ""),
            "work_item_id": getattr(recommendation, "work_item_id", None),
            "work_item_title": getattr(recommendation, "work_item_title", ""),
            "recommended_work_items": [
                {
                    "id": getattr(item, "id", None),
                    "title": getattr(item, "title", ""),
                    "thread_id": getattr(item, "thread_id", None),
                    "thread_title": getattr(item, "thread_title", ""),
                }
                for item in getattr(recommendation, "recommended_work_items", [])
            ],
            "summary": getattr(recommendation, "summary", ""),
            "reasoning_summary": getattr(recommendation, "reasoning_summary", ""),
        }
    return GoalDevelopmentLoopSummary(
        goal_status=compute_goal_progress(goal).goal_progress_status,
        threads=thread_rows,
        recent_work_results=recent_results,
        recommended_next_slice=recommended_next_slice,
    )
