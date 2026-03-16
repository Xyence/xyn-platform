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
    active_work_items: int
    blocked_work_items: int
    artifact_production_count: int
    recent_execution_count: int
    coordination_priority: GoalPrioritySignal


@dataclass(frozen=True)
class PortfolioInsight:
    key: str
    summary: str
    evidence: List[str]
    goal_ids: List[str]


@dataclass(frozen=True)
class GoalPortfolioRecommendation:
    goal_id: str
    title: str
    coordination_priority: str
    summary: str
    reasoning: str
    thread_id: Optional[str]
    work_item_id: Optional[str]
    queue_action_type: Optional[str]


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
        active_work_items=progress.active_work_items,
        blocked_work_items=progress.blocked_work_items,
        artifact_production_count=progress.artifact_production_count,
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
        active_work_items=row.active_work_items,
        blocked_work_items=row.blocked_work_items,
        artifact_production_count=row.artifact_production_count,
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


def compute_portfolio_insights(
    goals: Iterable[Goal],
    *,
    runtime_detail_lookup: Optional[Callable[[DevTask], Optional[Dict[str, Any]]]] = None,
) -> List[PortfolioInsight]:
    goal_list = list(goals)
    rows = build_goal_portfolio_state(goal_list, runtime_detail_lookup=runtime_detail_lookup)
    if not rows:
        return []

    insights: List[PortfolioInsight] = []
    by_goal_id = {row.goal_id: row for row in rows}

    blocked_goal_ids = [
        row.goal_id
        for row in rows
        if row.goal_progress_status == "stalled" or (row.blocked_threads > 0 and row.active_threads == 0)
    ]
    if blocked_goal_ids:
        blocked_titles = [by_goal_id[goal_id].title for goal_id in blocked_goal_ids]
        insights.append(
            PortfolioInsight(
                key="blocked_goals",
                summary=(
                    f"Blocked progress is concentrated in {', '.join(blocked_titles[:3])}."
                    if len(blocked_titles) <= 3
                    else f"{len(blocked_titles)} goals are currently blocked."
                ),
                evidence=[
                    f"{by_goal_id[goal_id].title} has {by_goal_id[goal_id].blocked_threads} blocked thread(s) and {by_goal_id[goal_id].blocked_work_items} blocked work item(s)."
                    for goal_id in blocked_goal_ids[:3]
                ],
                goal_ids=blocked_goal_ids,
            )
        )

    total_recent_execution = sum(row.recent_execution_count for row in rows)
    dominant = max(rows, key=lambda row: (row.recent_execution_count, row.artifact_production_count, row.goal_id))
    other_recent_execution = total_recent_execution - dominant.recent_execution_count
    if dominant.recent_execution_count > 0 and dominant.recent_execution_count > max(1, other_recent_execution):
        insights.append(
            PortfolioInsight(
                key="dominant_goal",
                summary=f"{dominant.title} currently dominates recent execution activity.",
                evidence=[
                    f"{dominant.recent_execution_count} recent execution event(s) were observed for {dominant.title}.",
                    f"Other goals account for {other_recent_execution} recent execution event(s).",
                ],
                goal_ids=[dominant.goal_id],
            )
        )

    starved_rows = [
        row
        for row in rows
        if (row.active_threads > 0 or row.active_work_items > 0) and row.recent_execution_count == 0 and total_recent_execution > 0
    ]
    if starved_rows:
        insights.append(
            PortfolioInsight(
                key="starved_goals",
                summary=(
                    f"{starved_rows[0].title} appears idle despite queueable or active work."
                    if len(starved_rows) == 1
                    else f"{len(starved_rows)} goals appear idle despite queueable or active work."
                ),
                evidence=[
                    f"{row.title} has {row.active_threads} active thread(s) and {row.active_work_items} active or ready work item(s) with no recent execution activity."
                    for row in starved_rows[:3]
                ],
                goal_ids=[row.goal_id for row in starved_rows],
            )
        )

    churn_rows = [
        row
        for row in rows
        if row.artifact_production_count >= 4 and row.progress_percent < 50
    ]
    if churn_rows:
        insights.append(
            PortfolioInsight(
                key="artifact_churn",
                summary=(
                    f"Artifact churn is concentrated in {churn_rows[0].title}."
                    if len(churn_rows) == 1
                    else "Artifact churn is concentrated in a small set of active goals."
                ),
                evidence=[
                    f"{row.title} produced {row.artifact_production_count} artifact(s) while progress is {row.progress_percent}%."
                    for row in churn_rows[:3]
                ],
                goal_ids=[row.goal_id for row in churn_rows],
            )
        )

    if not insights:
        healthiest = max(rows, key=lambda row: (row.progress_percent, -row.blocked_threads, row.goal_id))
        insights.append(
            PortfolioInsight(
                key="steady_progress",
                summary=f"Portfolio activity is balanced with {healthiest.title} showing the strongest current forward progress.",
                evidence=[
                    f"{healthiest.title} is at {healthiest.progress_percent}% progress with {healthiest.active_threads} active thread(s)."
                ],
                goal_ids=[healthiest.goal_id],
            )
        )

    return insights


def recommend_portfolio_goal(
    goals: Iterable[Goal],
    *,
    runtime_detail_lookup: Optional[Callable[[DevTask], Optional[Dict[str, Any]]]] = None,
) -> Optional[GoalPortfolioRecommendation]:
    from .goal_planning import recommend_next_slice

    ordered_goals = list(goals)
    rows = {
        row.goal_id: row
        for row in build_goal_portfolio_state(ordered_goals, runtime_detail_lookup=runtime_detail_lookup)
    }
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    candidates: List[tuple[int, int, str, Goal, Any]] = []
    for index, goal in enumerate(ordered_goals):
        recommendation = recommend_next_slice(goal)
        queue_suggestion = getattr(recommendation, "queue_suggestion", None)
        actionable = bool(queue_suggestion or getattr(recommendation, "thread_id", None))
        if not actionable:
            continue
        row = rows.get(str(goal.id))
        if row is None:
            continue
        candidates.append(
            (
                priority_rank.get(row.coordination_priority.value, 99),
                0 if queue_suggestion else 1,
                index,
                goal,
                recommendation,
            )
        )
    if not candidates:
        return None

    _, _, _, goal, recommendation = min(candidates)
    row = rows[str(goal.id)]
    queue_suggestion = getattr(recommendation, "queue_suggestion", None)
    action_type = getattr(queue_suggestion, "action_type", None) if queue_suggestion else None
    reasoning = getattr(recommendation, "reasoning_summary", "") or ""
    if not reasoning:
        reasoning = row.coordination_priority.reasons[0] if row.coordination_priority.reasons else "This goal has the strongest current advisory priority."
    return GoalPortfolioRecommendation(
        goal_id=str(goal.id),
        title=str(goal.title or ""),
        coordination_priority=row.coordination_priority.value,
        summary=str(getattr(recommendation, "summary", "") or ""),
        reasoning=reasoning,
        thread_id=str(getattr(recommendation, "thread_id", "") or "") or None,
        work_item_id=str(getattr(recommendation, "work_item_id", "") or "") or None,
        queue_action_type=str(action_type or "") or None,
    )
