from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from typing import Callable, Dict, List, Optional

from django.utils import timezone

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
    active_threads: int = 0
    blocked_threads: int = 0
    artifact_production_count: int = 0


@dataclass(frozen=True)
class ThreadProgressSnapshot:
    thread_status: str
    work_items_completed: int
    work_items_ready: int
    work_items_blocked: int


@dataclass(frozen=True)
class ThreadExecutionMetrics:
    average_run_duration_seconds: int
    total_completed_work_items: int
    failed_work_items: int
    blocked_work_items: int


@dataclass(frozen=True)
class GoalExecutionMetrics:
    active_threads: int
    blocked_threads: int
    total_completed_work_items: int
    artifact_production_count: int


@dataclass(frozen=True)
class GoalHealthIndicators:
    progress_percent: int
    active_threads: int
    blocked_threads: int
    recent_artifacts: int


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


def _parse_datetime(value: object) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, dt_timezone.utc)
    return parsed


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
    thread_progress_rows = [compute_thread_progress(thread) for thread in goal.threads.all()]
    metrics = compute_goal_execution_metrics(goal, precomputed_thread_progress=thread_progress_rows)
    if not tasks:
        return GoalProgressSnapshot(
            goal_progress_status="not_started",
            completed_work_items=0,
            active_work_items=0,
            blocked_work_items=0,
            active_threads=metrics.active_threads,
            blocked_threads=metrics.blocked_threads,
            artifact_production_count=metrics.artifact_production_count,
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
        active_threads=metrics.active_threads,
        blocked_threads=metrics.blocked_threads,
        artifact_production_count=metrics.artifact_production_count,
    )


def compute_thread_execution_metrics(
    thread: CoordinationThread,
    *,
    runtime_detail_lookup: Optional[Callable[[DevTask], Optional[Dict[str, object]]]] = None,
) -> ThreadExecutionMetrics:
    tasks = list(thread.work_items.all())
    completed = 0
    failed = 0
    blocked = 0
    durations: List[int] = []
    task_lookup = _task_lookup_for_thread(thread)

    for task in tasks:
        status = str(task.status or "").strip().lower()
        if status in COMPLETED_WORK_ITEM_STATUSES:
            completed += 1
        elif status in {"failed", "canceled", "awaiting_review"}:
            failed += 1
        if status == "queued" and work_item_is_blocked(
            task,
            status_lookup=lambda candidate: str(getattr(candidate, "status", "") or ""),
            task_lookup=task_lookup,
        ):
            blocked += 1
        detail = runtime_detail_lookup(task) if callable(runtime_detail_lookup) else None
        if not isinstance(detail, dict):
            continue
        started_at = _parse_datetime(detail.get("started_at"))
        finished_at = _parse_datetime(detail.get("completed_at"))
        if started_at and finished_at and finished_at >= started_at:
            durations.append(int((finished_at - started_at).total_seconds()))

    average_duration = int(sum(durations) / len(durations)) if durations else 0
    return ThreadExecutionMetrics(
        average_run_duration_seconds=average_duration,
        total_completed_work_items=completed,
        failed_work_items=failed,
        blocked_work_items=blocked,
    )


def compute_goal_execution_metrics(
    goal: Goal,
    *,
    runtime_detail_lookup: Optional[Callable[[DevTask], Optional[Dict[str, object]]]] = None,
    precomputed_thread_progress: Optional[List[ThreadProgressSnapshot]] = None,
) -> GoalExecutionMetrics:
    threads = list(goal.threads.all())
    thread_progress_rows = precomputed_thread_progress or [compute_thread_progress(thread) for thread in threads]
    active_threads = sum(1 for item in thread_progress_rows if item.thread_status == "active")
    blocked_threads = sum(1 for item in thread_progress_rows if item.thread_status == "blocked")
    total_completed_work_items = sum(item.work_items_completed for item in thread_progress_rows)

    artifact_count = 0
    if callable(runtime_detail_lookup):
        for task in goal.work_items.all():
            detail = runtime_detail_lookup(task)
            if isinstance(detail, dict):
                rows = detail.get("artifacts") if isinstance(detail.get("artifacts"), list) else []
                artifact_count += len(rows)

    return GoalExecutionMetrics(
        active_threads=active_threads,
        blocked_threads=blocked_threads,
        total_completed_work_items=total_completed_work_items,
        artifact_production_count=artifact_count,
    )


def compute_goal_health_indicators(
    goal: Goal,
    *,
    runtime_detail_lookup: Optional[Callable[[DevTask], Optional[Dict[str, object]]]] = None,
) -> GoalHealthIndicators:
    progress = compute_goal_progress(goal)
    metrics = compute_goal_execution_metrics(goal, runtime_detail_lookup=runtime_detail_lookup)
    total_work_items = max(goal.work_items.count(), 1)
    progress_percent = int(round((progress.completed_work_items / total_work_items) * 100)) if goal.work_items.exists() else 0
    return GoalHealthIndicators(
        progress_percent=progress_percent,
        active_threads=metrics.active_threads,
        blocked_threads=metrics.blocked_threads,
        recent_artifacts=metrics.artifact_production_count,
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
