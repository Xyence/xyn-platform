from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional
import hashlib
import json

from pydantic import BaseModel, Field
from django.contrib.auth import get_user_model
from django.utils.text import slugify

from .development_targets import resolve_development_target
from .execution_briefs import build_execution_brief
from .goal_progress import compute_goal_progress, compute_thread_progress
from .models import CoordinationThread, DevTask, Goal
from .xco import THREAD_PRIORITY_ORDER, derive_work_queue


GOAL_STATUS_TRANSITIONS = {
    "proposed": {"decomposed", "in_progress", "canceled"},
    "decomposed": {"in_progress", "completed", "canceled", "proposed"},
    "in_progress": {"completed", "canceled", "decomposed"},
    "completed": set(),
    "canceled": {"proposed"},
}


def valid_goal_transition(current_status: str, next_status: str) -> bool:
    current = str(current_status or "").strip().lower()
    nxt = str(next_status or "").strip().lower()
    if current == nxt:
        return True
    return nxt in GOAL_STATUS_TRANSITIONS.get(current, set())


class GoalThreadDefinition(BaseModel):
    title: str
    description: str = ""
    priority: str = "normal"
    domain: Optional[str] = None
    sequence: int = 1


class GoalWorkItemDefinition(BaseModel):
    thread_title: str
    title: str
    description: str = ""
    priority: str = "normal"
    sequence: int = 1
    dependency_work_item_refs: List[str] = Field(default_factory=list)


class GoalPlanningOutput(BaseModel):
    goal_id: str
    planning_summary: str
    threads: List[GoalThreadDefinition] = Field(default_factory=list)
    work_items: List[GoalWorkItemDefinition] = Field(default_factory=list)
    resolution_notes: List[str] = Field(default_factory=list)


@dataclass(frozen=True)
class GoalRecommendationWorkItem:
    id: str
    title: str
    thread_id: Optional[str]
    thread_title: str


@dataclass(frozen=True)
class GoalQueueSuggestion:
    action_type: str
    thread_id: Optional[str]
    work_item_id: Optional[str]
    reason: str
    summary: str


@dataclass(frozen=True)
class RecommendationAction:
    type: str
    label: str
    target_work_item: Optional[str]
    target_thread: Optional[str]
    queueable: bool


@dataclass(frozen=True)
class GoalRecommendation:
    recommendation_id: Optional[str]
    goal_id: str
    thread_id: Optional[str]
    thread_title: str
    work_item_id: Optional[str]
    work_item_title: str
    recommended_work_items: List[GoalRecommendationWorkItem]
    queue_suggestion: Optional[GoalQueueSuggestion]
    actions: List[RecommendationAction]
    reasoning_summary: str
    summary: str


def build_recommendation_id(
    *,
    goal_id: str,
    thread_id: Optional[str],
    work_item_id: Optional[str],
    queue_action_type: Optional[str],
    recommended_work_items: Iterable[GoalRecommendationWorkItem],
) -> Optional[str]:
    normalized_goal_id = str(goal_id or "").strip()
    normalized_thread_id = str(thread_id or "").strip()
    normalized_work_item_id = str(work_item_id or "").strip()
    normalized_queue_action = str(queue_action_type or "").strip()
    recommended_ids = [str(item.id or "").strip() for item in recommended_work_items if str(item.id or "").strip()]
    if not normalized_goal_id or not (normalized_queue_action or normalized_thread_id or normalized_work_item_id or recommended_ids):
        return None
    payload = {
        "goal_id": normalized_goal_id,
        "thread_id": normalized_thread_id,
        "work_item_id": normalized_work_item_id,
        "queue_action_type": normalized_queue_action,
        "recommended_work_item_ids": recommended_ids,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:12]
    return (
        f"rec:v1:{normalized_goal_id}:{normalized_thread_id or '-'}:{normalized_work_item_id or '-'}:"
        f"{normalized_queue_action or '-'}:{digest}"
    )


def parse_recommendation_id(recommendation_id: Optional[str]) -> Dict[str, Optional[str]]:
    text = str(recommendation_id or "").strip()
    if not text:
        return {"goal_id": None, "thread_id": None, "work_item_id": None, "queue_action_type": None}
    parts = text.split(":")
    if len(parts) < 7 or parts[0] != "rec" or parts[1] != "v1":
        return {"goal_id": None, "thread_id": None, "work_item_id": None, "queue_action_type": None}
    _, _, goal_id, thread_id, work_item_id, queue_action_type, _digest = parts[:7]
    return {
        "goal_id": goal_id or None,
        "thread_id": None if thread_id == "-" else thread_id,
        "work_item_id": None if work_item_id == "-" else work_item_id,
        "queue_action_type": None if queue_action_type == "-" else queue_action_type,
    }


def _finalize_recommendation(recommendation: GoalRecommendation) -> GoalRecommendation:
    recommendation_id = build_recommendation_id(
        goal_id=recommendation.goal_id,
        thread_id=recommendation.thread_id,
        work_item_id=recommendation.work_item_id,
        queue_action_type=recommendation.queue_suggestion.action_type if recommendation.queue_suggestion else None,
        recommended_work_items=recommendation.recommended_work_items,
    )
    return GoalRecommendation(
        recommendation_id=recommendation_id,
        goal_id=recommendation.goal_id,
        thread_id=recommendation.thread_id,
        thread_title=recommendation.thread_title,
        work_item_id=recommendation.work_item_id,
        work_item_title=recommendation.work_item_title,
        recommended_work_items=recommendation.recommended_work_items,
        queue_suggestion=recommendation.queue_suggestion,
        actions=recommendation.actions,
        reasoning_summary=recommendation.reasoning_summary,
        summary=recommendation.summary,
    )


def _build_recommendation_actions(
    *,
    queue_suggestion: Optional[GoalQueueSuggestion],
    thread_id: Optional[str],
    work_item_id: Optional[str],
) -> List[RecommendationAction]:
    actions: List[RecommendationAction] = []
    if queue_suggestion:
        action_type = str(queue_suggestion.action_type or "").strip()
        if action_type == "resume_thread":
            actions.append(
                RecommendationAction(
                    type="resume_thread",
                    label="Resume Thread",
                    target_work_item=None,
                    target_thread=thread_id or queue_suggestion.thread_id,
                    queueable=False,
                )
            )
        elif action_type in {"queue_first_slice", "queue_next_slice"}:
            actions.append(
                RecommendationAction(
                    type="approve_and_queue",
                    label="Approve and Queue",
                    target_work_item=work_item_id or queue_suggestion.work_item_id,
                    target_thread=thread_id or queue_suggestion.thread_id,
                    queueable=True,
                )
            )
            actions.append(
                RecommendationAction(
                    type=action_type,
                    label="Queue First Slice" if action_type == "queue_first_slice" else "Queue Next Slice",
                    target_work_item=work_item_id or queue_suggestion.work_item_id,
                    target_thread=thread_id or queue_suggestion.thread_id,
                    queueable=True,
                )
            )
    if thread_id:
        actions.append(
            RecommendationAction(
                type="review_thread",
                label="Review Thread",
                target_work_item=None,
                target_thread=thread_id,
                queueable=False,
            )
        )
    return actions


def infer_goal_type(title: str, description: str = "") -> str:
    text = f"{title} {description}".strip().lower()
    if any(token in text for token in {"investigate", "diagnose", "why is", "failure", "incident"}):
        return "investigate_problem"
    if any(token in text for token in {"stabilize", "harden", "cleanup", "reliability"}):
        return "stabilize_system"
    if any(token in text for token in {"extend", "add to", "enhance", "expand"}):
        return "extend_system"
    return "build_system"


def _generic_seed(goal: Goal) -> GoalPlanningOutput:
    threads = [
        GoalThreadDefinition(
            title="Core Domain Slice",
            description="Define the first durable domain model and the smallest working operational flow.",
            priority="high",
            domain="application",
            sequence=1,
        ),
        GoalThreadDefinition(
            title="Operational Surface",
            description="Expose the first inspectable list/detail surfaces and runtime observability for the MVP.",
            priority="normal",
            domain="ui",
            sequence=2,
        ),
        GoalThreadDefinition(
            title="Stabilization",
            description="Validate execution, tests, and artifact inspection for the initial slice.",
            priority="normal",
            domain="quality",
            sequence=3,
        ),
    ]
    work_items = [
        GoalWorkItemDefinition(
            thread_title="Core Domain Slice",
            title="Define the minimum durable model for the first working slice",
            description="Model the first end-to-end slice as durable Xyn records.",
            priority="high",
            sequence=1,
        ),
        GoalWorkItemDefinition(
            thread_title="Core Domain Slice",
            title="Implement the first executable vertical slice",
            description="Deliver the smallest runnable slice that proves the system works end-to-end.",
            priority="high",
            sequence=2,
        ),
        GoalWorkItemDefinition(
            thread_title="Operational Surface",
            title="Expose list/detail inspection for the first slice",
            description="Make the first slice observable in Xyn panels and conversation summaries.",
            priority="normal",
            sequence=3,
        ),
        GoalWorkItemDefinition(
            thread_title="Stabilization",
            title="Validate the first slice with tests and runtime observability",
            description="Add tests and ensure outputs are inspectable before expanding the plan.",
            priority="normal",
            sequence=4,
        ),
    ]
    return GoalPlanningOutput(
        goal_id=str(goal.id),
        planning_summary="Start with one vertical slice that creates durable domain state and exposes inspection surfaces before broadening the system.",
        threads=threads,
        work_items=work_items,
        resolution_notes=[
            "Prefer a small runnable slice over a broad component inventory.",
            "Use panel- and conversation-visible outputs as proof of progress.",
        ],
    )


def decompose_goal(goal: Goal) -> GoalPlanningOutput:
    return _generic_seed(goal)


def serialize_goal_summary(goal: Goal) -> Dict[str, Any]:
    progress = compute_goal_progress(goal)
    return {
        "id": str(goal.id),
        "application_id": str(goal.application_id) if getattr(goal, "application_id", None) else None,
        "workspace_id": str(goal.workspace_id),
        "title": goal.title,
        "description": goal.description or "",
        "source_conversation_id": goal.source_conversation_id or None,
        "requested_by": str(goal.requested_by_id) if goal.requested_by_id else None,
        "goal_type": goal.goal_type,
        "planning_status": goal.planning_status,
        "priority": goal.priority,
        "planning_summary": goal.planning_summary or "",
        "resolution_notes": goal.resolution_notes_json if isinstance(goal.resolution_notes_json, list) else [],
        "thread_count": goal.threads.count(),
        "work_item_count": goal.work_items.count(),
        "goal_progress_status": progress.goal_progress_status,
        "completed_work_items": progress.completed_work_items,
        "active_work_items": progress.active_work_items,
        "blocked_work_items": progress.blocked_work_items,
        "created_at": goal.created_at,
        "updated_at": goal.updated_at,
    }


def _thread_priority_for_plan(priority: str) -> str:
    value = str(priority or "normal").strip().lower()
    if value in {"critical", "high", "normal", "low"}:
        return value
    return "normal"


def _task_priority_for_sequence(sequence: int, priority: str) -> int:
    rank = THREAD_PRIORITY_ORDER.get(_thread_priority_for_plan(priority), THREAD_PRIORITY_ORDER["normal"])
    return rank * 100 + max(0, int(sequence or 0))


def persist_goal_plan(goal: Goal, plan: GoalPlanningOutput, *, user) -> Dict[str, Any]:
    if goal.threads.exists() or goal.work_items.exists():
        return {
            "goal": goal,
            "threads": list(goal.threads.order_by("created_at", "id")),
            "work_items": list(goal.work_items.order_by("priority", "created_at", "id")),
        }
    user_model = get_user_model()
    target = resolve_development_target(goal=goal)
    target_repo = str(target.repository_slug or "").strip()
    target_branch = str(target.branch or "").strip() or "develop"
    created_threads: Dict[str, CoordinationThread] = {}
    for thread_def in sorted(plan.threads, key=lambda item: (item.sequence, item.title.lower())):
        thread = CoordinationThread.objects.create(
            workspace=goal.workspace,
            goal=goal,
            title=thread_def.title,
            description=thread_def.description,
            owner=goal.requested_by,
            priority=_thread_priority_for_plan(thread_def.priority),
            status="queued",
            domain=str(thread_def.domain or "").strip(),
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id=goal.source_conversation_id or "",
        )
        created_threads[thread_def.title] = thread
    created_tasks: Dict[str, DevTask] = {}
    for work_item_def in sorted(plan.work_items, key=lambda item: (item.sequence, item.title.lower())):
        thread = created_threads.get(work_item_def.thread_title)
        if thread is None:
            continue
        execution_brief = build_execution_brief(
            summary=work_item_def.title,
            objective=work_item_def.description or goal.planning_summary or goal.description or goal.title,
            implementation_intent=work_item_def.description or work_item_def.title,
            target=target,
            allowed_areas=[thread.domain] if str(thread.domain or "").strip() else [],
            acceptance_criteria=[],
            validation_commands=[],
            boundaries=[
                "Keep changes scoped to this work item and thread.",
                "Do not broaden implementation beyond the stated request without review.",
            ],
            source_context={
                "planning_source": "goal_plan",
                "goal_id": str(goal.id),
                "goal_title": goal.title,
                "thread_id": str(thread.id),
                "thread_title": thread.title,
                "work_item_title": work_item_def.title,
                "work_item_sequence": int(work_item_def.sequence or 0),
                "dependency_work_item_refs": list(work_item_def.dependency_work_item_refs),
                "resolution_notes": list(plan.resolution_notes),
            },
            revision=1,
            revision_reason="initial_plan",
        )
        task = DevTask.objects.create(
            title=work_item_def.title[:240],
            description=work_item_def.description,
            task_type="codegen",
            status="queued",
            priority=_task_priority_for_sequence(work_item_def.sequence, work_item_def.priority),
            max_attempts=3,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id=goal.source_conversation_id or "",
            intent_type="goal_planning",
            target_repo=target_repo,
            target_branch=target_branch,
            execution_brief=execution_brief,
            execution_brief_history=[],
            execution_brief_review_state="draft",
            execution_policy={"require_brief_approval": True},
            goal=goal,
            coordination_thread=thread,
            work_item_id=f"goal-{goal.id.hex[:8]}-{slugify(work_item_def.title)[:60]}",
            dependency_work_item_ids=[],
            context_purpose="goal",
            created_by=user if isinstance(user, user_model) else None,
            updated_by=user if isinstance(user, user_model) else None,
        )
        created_tasks[work_item_def.title] = task
    for work_item_def in plan.work_items:
        task = created_tasks.get(work_item_def.title)
        if task is None:
            continue
        dependency_ids = []
        for reference in work_item_def.dependency_work_item_refs:
            dep = created_tasks.get(reference)
            if dep and dep.work_item_id:
                dependency_ids.append(dep.work_item_id)
        if dependency_ids:
            task.dependency_work_item_ids = dependency_ids
            task.save(update_fields=["dependency_work_item_ids", "updated_at"])
    goal.planning_summary = plan.planning_summary
    goal.resolution_notes_json = list(plan.resolution_notes)
    goal.planning_status = "decomposed"
    goal.save(update_fields=["planning_summary", "resolution_notes_json", "planning_status", "updated_at"])
    return {
        "goal": goal,
        "threads": list(created_threads.values()),
        "work_items": list(created_tasks.values()),
    }


def recommend_next_slice(goal: Goal) -> GoalRecommendation:
    progress = compute_goal_progress(goal)
    if progress.goal_progress_status == "completed" or str(goal.planning_status or "").strip().lower() == "completed":
        return _finalize_recommendation(GoalRecommendation(
            recommendation_id=None,
            goal_id=str(goal.id),
            thread_id=None,
            thread_title="",
            work_item_id=None,
            work_item_title="",
            recommended_work_items=[],
            queue_suggestion=None,
            actions=[],
            reasoning_summary=f"{goal.title} is completed. No additional executable slice is recommended.",
            summary=f"{goal.title} is completed. No additional executable slice is recommended.",
        ))
    thread_qs = goal.threads.prefetch_related("work_items").all()
    queue = derive_work_queue(
        threads=thread_qs,
        status_lookup=lambda task: task.status,
        task_lookup=lambda work_item_id: goal.work_items.filter(work_item_id=work_item_id).first(),
    )
    if queue:
        entry = queue[0]
        task = goal.work_items.filter(id=entry.task_id).select_related("coordination_thread").first()
        thread = task.coordination_thread if task else None
        blocked_threads = [
            thread_item.title
            for thread_item in goal.threads.all().order_by("created_at", "id")
            if compute_thread_progress(thread_item).thread_status == "blocked"
        ]
        reasoning = (
            f"Selected {task.title if task else entry.work_item_id} from {thread.title if thread else entry.thread_title} "
            f"because it is the first ready unblocked slice in deterministic queue order."
        )
        if blocked_threads:
            reasoning += f" Blocked threads waiting for dependencies or review: {', '.join(blocked_threads)}."
        return _finalize_recommendation(GoalRecommendation(
            recommendation_id=None,
            goal_id=str(goal.id),
            thread_id=str(thread.id) if thread else entry.thread_id,
            thread_title=str(thread.title) if thread else entry.thread_title,
            work_item_id=str(task.id) if task else None,
            work_item_title=str(task.title) if task else "",
            recommended_work_items=[
                GoalRecommendationWorkItem(
                    id=str(task.id) if task else entry.task_id,
                    title=str(task.title) if task else entry.work_item_id,
                    thread_id=str(thread.id) if thread else entry.thread_id,
                    thread_title=str(thread.title) if thread else entry.thread_title,
                )
            ],
            queue_suggestion=GoalQueueSuggestion(
                action_type="queue_next_slice"
                if goal.work_items.filter(status__in=["running", "completed", "awaiting_review"]).exists()
                else "queue_first_slice",
                thread_id=str(thread.id) if thread else entry.thread_id,
                work_item_id=str(task.id) if task else None,
                reason="The selected slice is the first ready unblocked queue candidate under current durable state.",
                summary=(
                    f"Suggest queue_next_slice for {task.title if task else entry.work_item_id}."
                    if goal.work_items.filter(status__in=["running", "completed", "awaiting_review"]).exists()
                    else f"Suggest queue_first_slice for {task.title if task else entry.work_item_id}."
                ),
            ),
            actions=_build_recommendation_actions(
                queue_suggestion=GoalQueueSuggestion(
                    action_type="queue_next_slice"
                    if goal.work_items.filter(status__in=["running", "completed", "awaiting_review"]).exists()
                    else "queue_first_slice",
                    thread_id=str(thread.id) if thread else entry.thread_id,
                    work_item_id=str(task.id) if task else None,
                    reason="The selected slice is the first ready unblocked queue candidate under current durable state.",
                    summary=(
                        f"Suggest queue_next_slice for {task.title if task else entry.work_item_id}."
                        if goal.work_items.filter(status__in=["running", "completed", "awaiting_review"]).exists()
                        else f"Suggest queue_first_slice for {task.title if task else entry.work_item_id}."
                    ),
                ),
                thread_id=str(thread.id) if thread else entry.thread_id,
                work_item_id=str(task.id) if task else None,
            ),
            reasoning_summary=reasoning,
            summary=f"Queue the next smallest slice from {thread.title if thread else entry.thread_title}: {task.title if task else entry.work_item_id}.",
        ))
    paused_thread = (
        goal.threads.filter(status="paused")
        .prefetch_related("work_items")
        .order_by("created_at", "id")
        .first()
    )
    if paused_thread and paused_thread.work_items.filter(status="queued").exists():
        return _finalize_recommendation(GoalRecommendation(
            recommendation_id=None,
            goal_id=str(goal.id),
            thread_id=str(paused_thread.id),
            thread_title=str(paused_thread.title),
            work_item_id=None,
            work_item_title="",
            recommended_work_items=[],
            queue_suggestion=GoalQueueSuggestion(
                action_type="resume_thread",
                thread_id=str(paused_thread.id),
                work_item_id=None,
                reason="The earliest paused thread still has queued work and must be resumed before more slices can run.",
                summary=f"Suggest resume_thread for {paused_thread.title}.",
            ),
            actions=_build_recommendation_actions(
                queue_suggestion=GoalQueueSuggestion(
                    action_type="resume_thread",
                    thread_id=str(paused_thread.id),
                    work_item_id=None,
                    reason="The earliest paused thread still has queued work and must be resumed before more slices can run.",
                    summary=f"Suggest resume_thread for {paused_thread.title}.",
                ),
                thread_id=str(paused_thread.id),
                work_item_id=None,
            ),
            reasoning_summary=(
                f"{paused_thread.title} is paused with queued work. Resume it before queueing additional slices."
            ),
            summary=f"Resume {paused_thread.title} before queueing more work.",
        ))
    fallback_task = (
        goal.work_items.filter(status="queued", coordination_thread__status__in=["active", "queued"])
        .select_related("coordination_thread")
        .order_by("coordination_thread__created_at", "coordination_thread__id", "priority", "created_at", "id")
        .first()
    )
    fallback_thread = fallback_task.coordination_thread if fallback_task and fallback_task.coordination_thread_id else None
    if fallback_task and fallback_thread:
        reasoning = (
            f"Selected {fallback_task.title} from {fallback_thread.title} as the smallest reviewable slice. "
            "It is not queue-ready yet, but it is the earliest MVP thread with queued work."
        )
        return _finalize_recommendation(GoalRecommendation(
            recommendation_id=None,
            goal_id=str(goal.id),
            thread_id=str(fallback_thread.id),
            thread_title=str(fallback_thread.title),
            work_item_id=str(fallback_task.id),
            work_item_title=str(fallback_task.title),
            recommended_work_items=[
                GoalRecommendationWorkItem(
                    id=str(fallback_task.id),
                    title=str(fallback_task.title),
                    thread_id=str(fallback_thread.id),
                    thread_title=str(fallback_thread.title),
                )
            ],
            queue_suggestion=GoalQueueSuggestion(
                action_type="queue_first_slice" if goal.planning_status != "in_progress" else "queue_next_slice",
                thread_id=str(fallback_thread.id),
                work_item_id=str(fallback_task.id),
                reason="The selected slice is reviewable and is the earliest queued work in the MVP-first thread order.",
                summary=(
                    f"Suggest queue_first_slice for {fallback_task.title}."
                    if goal.planning_status != "in_progress"
                    else f"Suggest queue_next_slice for {fallback_task.title}."
                ),
            ),
            actions=_build_recommendation_actions(
                queue_suggestion=GoalQueueSuggestion(
                    action_type="queue_first_slice" if goal.planning_status != "in_progress" else "queue_next_slice",
                    thread_id=str(fallback_thread.id),
                    work_item_id=str(fallback_task.id),
                    reason="The selected slice is reviewable and is the earliest queued work in the MVP-first thread order.",
                    summary=(
                        f"Suggest queue_first_slice for {fallback_task.title}."
                        if goal.planning_status != "in_progress"
                        else f"Suggest queue_next_slice for {fallback_task.title}."
                    ),
                ),
                thread_id=str(fallback_thread.id),
                work_item_id=str(fallback_task.id),
            ),
            reasoning_summary=reasoning,
            summary=f"Start with the smallest queued slice from {fallback_thread.title}: {fallback_task.title}.",
        ))
    blocked_thread_objects = [
        thread_item
        for thread_item in goal.threads.all().order_by("created_at", "id")
        if compute_thread_progress(thread_item).thread_status == "blocked"
    ]
    blocked_threads = [thread_item.title for thread_item in blocked_thread_objects]
    first_blocked = blocked_thread_objects[0] if blocked_thread_objects else None
    return _finalize_recommendation(GoalRecommendation(
        recommendation_id=None,
        goal_id=str(goal.id),
        thread_id=None,
        thread_title="",
        work_item_id=None,
        work_item_title="",
        recommended_work_items=[],
        queue_suggestion=None,
        actions=_build_recommendation_actions(
            queue_suggestion=None,
            thread_id=str(first_blocked.id) if first_blocked else None,
            work_item_id=None,
        ),
        reasoning_summary=(
            f"No executable slice is ready yet. Blocked threads: {', '.join(blocked_threads)}."
            if blocked_threads
            else "No executable slice is ready yet. Review the first thread and queue its first work item when ready."
        ),
        summary=(
            f"No executable slice is ready yet. Blocked threads: {', '.join(blocked_threads)}."
            if blocked_threads
            else "No executable slice is ready yet. Review the first thread and queue its first work item when ready."
        ),
    ))
