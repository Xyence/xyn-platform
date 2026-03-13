from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional

from .goal_progress import compute_goal_health_indicators, compute_goal_progress
from .models import DevTask, Goal


@dataclass(frozen=True)
class GoalPrioritySignal:
    value: str
    reasons: List[str]


@dataclass(frozen=True)
class GoalPortfolioRow:
    goal_id: str
    title: str
    planning_status: str
    goal_progress_status: str
    progress_percent: int
    health_status: str
    active_threads: int
    blocked_threads: int
    recent_execution_count: int
    coordination_priority: GoalPrioritySignal


def _recent_execution_count(
    goal: Goal,
    *,
    runtime_detail_lookup: Optional[Callable[[DevTask], Optional[Dict[str, Any]]]] = None,
) -> int:
    count = 0
    for task in goal.work_items.all():
        if task.runtime_run_id:
            count += 1
            continue
        detail = runtime_detail_lookup(task) if callable(runtime_detail_lookup) else None
        if isinstance(detail, dict) and any(
            detail.get(field)
            for field in ("id", "run_id", "started_at", "completed_at", "status")
        ):
            count += 1
    return count


def _goal_health_status(
    *,
    planning_status: str,
    goal_progress_status: str,
    active_threads: int,
    blocked_threads: int,
    recent_execution_count: int,
) -> str:
    normalized_planning = str(planning_status or "").strip().lower()
    normalized_progress = str(goal_progress_status or "").strip().lower()
    if normalized_planning in {"completed", "canceled"} or normalized_progress == "completed":
        return "completed"
    if blocked_threads > 0 and active_threads == 0:
        return "blocked"
    if active_threads > 0 or recent_execution_count > 0:
        return "active"
    return "idle"


def compute_goal_priority_signal(row: GoalPortfolioRow) -> GoalPrioritySignal:
    reasons: List[str] = []
    planning_status = str(row.planning_status or "").strip().lower()
    progress_status = str(row.goal_progress_status or "").strip().lower()

    if planning_status in {"completed", "canceled"} or progress_status == "completed":
        return GoalPrioritySignal(value="low", reasons=["Goal is already complete or no longer active."])

    if row.blocked_threads > 0:
        reasons.append("Blocked threads are preventing forward progress.")
    if progress_status == "stalled":
        reasons.append("Goal progress is stalled.")
    if row.active_threads > 1 and row.progress_percent < 50:
        reasons.append("Work is spread across multiple active threads with limited completion.")

    if reasons:
        return GoalPrioritySignal(value="high", reasons=reasons)

    if row.active_threads > 0 or row.recent_execution_count > 0 or progress_status == "in_progress":
        return GoalPrioritySignal(
            value="medium",
            reasons=["Goal has active execution or queueable progress but no blocking condition."],
        )

    return GoalPrioritySignal(
        value="low",
        reasons=["Goal has little current execution activity and no urgent blocking signal."],
    )


def build_goal_portfolio_row(
    goal: Goal,
    *,
    runtime_detail_lookup: Optional[Callable[[DevTask], Optional[Dict[str, Any]]]] = None,
) -> GoalPortfolioRow:
    progress = compute_goal_progress(goal)
    health = compute_goal_health_indicators(goal, runtime_detail_lookup=runtime_detail_lookup)
    recent_execution_count = _recent_execution_count(goal, runtime_detail_lookup=runtime_detail_lookup)
    health_status = _goal_health_status(
        planning_status=str(goal.planning_status or ""),
        goal_progress_status=progress.goal_progress_status,
        active_threads=health.active_threads,
        blocked_threads=health.blocked_threads,
        recent_execution_count=recent_execution_count,
    )
    row = GoalPortfolioRow(
        goal_id=str(goal.id),
        title=str(goal.title or ""),
        planning_status=str(goal.planning_status or ""),
        goal_progress_status=progress.goal_progress_status,
        progress_percent=health.progress_percent,
        health_status=health_status,
        active_threads=health.active_threads,
        blocked_threads=health.blocked_threads,
        recent_execution_count=recent_execution_count,
        coordination_priority=GoalPrioritySignal(value="low", reasons=[]),
    )
    priority = compute_goal_priority_signal(row)
    return GoalPortfolioRow(
        goal_id=row.goal_id,
        title=row.title,
        planning_status=row.planning_status,
        goal_progress_status=row.goal_progress_status,
        progress_percent=row.progress_percent,
        health_status=row.health_status,
        active_threads=row.active_threads,
        blocked_threads=row.blocked_threads,
        recent_execution_count=row.recent_execution_count,
        coordination_priority=priority,
    )


def build_goal_portfolio_state(
    goals: Iterable[Goal],
    *,
    runtime_detail_lookup: Optional[Callable[[DevTask], Optional[Dict[str, Any]]]] = None,
) -> List[GoalPortfolioRow]:
    return [
        build_goal_portfolio_row(goal, runtime_detail_lookup=runtime_detail_lookup)
        for goal in goals
    ]
