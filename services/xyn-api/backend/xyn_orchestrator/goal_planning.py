from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel, Field
from django.contrib.auth import get_user_model
from django.utils.text import slugify

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
class GoalRecommendation:
    goal_id: str
    thread_id: Optional[str]
    thread_title: str
    work_item_id: Optional[str]
    work_item_title: str
    recommended_work_items: List[GoalRecommendationWorkItem]
    queue_suggestion: Optional[GoalQueueSuggestion]
    reasoning_summary: str
    summary: str


def infer_goal_type(title: str, description: str = "") -> str:
    text = f"{title} {description}".strip().lower()
    if any(token in text for token in {"investigate", "diagnose", "why is", "failure", "incident"}):
        return "investigate_problem"
    if any(token in text for token in {"stabilize", "harden", "cleanup", "reliability"}):
        return "stabilize_system"
    if any(token in text for token in {"extend", "add to", "enhance", "expand"}):
        return "extend_system"
    return "build_system"


def _looks_like_real_estate_deal_finder(goal: Goal) -> bool:
    text = f"{goal.title} {goal.description}".strip().lower()
    markers = {
        "real estate",
        "deal finder",
        "listing data",
        "comparables",
        "deal scoring",
        "property",
        "opportunity review",
        "outreach workflow",
    }
    return any(marker in text for marker in markers)


def _real_estate_seed(goal: Goal) -> GoalPlanningOutput:
    threads = [
        GoalThreadDefinition(
            title="Listing Data Ingestion",
            description="Ingest the first listing source and normalize external listing records into Xyn entities.",
            priority="high",
            domain="data",
            sequence=1,
        ),
        GoalThreadDefinition(
            title="Property Model and CRUD",
            description="Define the property-centered entity model and expose CRUD/list/detail flows for core records.",
            priority="high",
            domain="application",
            sequence=2,
        ),
        GoalThreadDefinition(
            title="Comparable Analysis",
            description="Model comparable records and expose basic comparable selection/aggregation for each property.",
            priority="normal",
            domain="analysis",
            sequence=3,
        ),
        GoalThreadDefinition(
            title="Deal Scoring",
            description="Compute a first-pass opportunity score with persisted explanation fields.",
            priority="normal",
            domain="analysis",
            sequence=4,
        ),
        GoalThreadDefinition(
            title="Opportunity Review UI",
            description="Add a ranked opportunity view with drill-down into score and comp evidence.",
            priority="normal",
            domain="ui",
            sequence=5,
        ),
        GoalThreadDefinition(
            title="Lead and Outreach Workflow",
            description="Track opportunity follow-up state and outreach readiness without implementing external integrations yet.",
            priority="low",
            domain="workflow",
            sequence=6,
        ),
    ]
    work_items = [
        GoalWorkItemDefinition(
            thread_title="Listing Data Ingestion",
            title="Identify the first listing source and capture the ingestion contract",
            description="Choose one initial listing source and define the normalization fields required for the MVP.",
            priority="high",
            sequence=1,
        ),
        GoalWorkItemDefinition(
            thread_title="Listing Data Ingestion",
            title="Implement the first listing ingestion flow",
            description="Ingest sample listing records and validate normalized data lands in durable Xyn records.",
            priority="high",
            sequence=2,
        ),
        GoalWorkItemDefinition(
            thread_title="Property Model and CRUD",
            title="Define the property, source, and market entity model",
            description="Model the minimum entities needed to store listings, source metadata, and market context.",
            priority="high",
            sequence=3,
        ),
        GoalWorkItemDefinition(
            thread_title="Property Model and CRUD",
            title="Expose CRUD, list, and detail views for property records",
            description="Generate the application artifact paths needed to inspect and manage property data.",
            priority="high",
            sequence=4,
            dependency_work_item_refs=["Define the property, source, and market entity model"],
        ),
        GoalWorkItemDefinition(
            thread_title="Comparable Analysis",
            title="Define comparable selection criteria and comp record relationships",
            description="Capture the MVP rules for comparable matching and persist the comp data model.",
            priority="normal",
            sequence=5,
        ),
        GoalWorkItemDefinition(
            thread_title="Deal Scoring",
            title="Implement first-pass deal scoring with explanation fields",
            description="Persist a simple opportunity score and the factors that contributed to it.",
            priority="normal",
            sequence=6,
        ),
        GoalWorkItemDefinition(
            thread_title="Opportunity Review UI",
            title="Build the ranked opportunity review surface",
            description="Surface scored opportunities with filtering and drill-down into comp/scoring evidence.",
            priority="normal",
            sequence=7,
        ),
        GoalWorkItemDefinition(
            thread_title="Lead and Outreach Workflow",
            title="Track lead follow-up state for approved opportunities",
            description="Persist notes, status, and outreach-readiness state without external messaging integration.",
            priority="low",
            sequence=8,
        ),
    ]
    return GoalPlanningOutput(
        goal_id=str(goal.id),
        planning_summary="Start with the smallest vertical slice: ingest listings, persist property records, and make them inspectable before adding comps, scoring, and outreach workflow.",
        threads=threads,
        work_items=work_items,
        resolution_notes=[
            "Bias toward a working MVP over broad platform coverage.",
            "Begin with listing ingestion and property CRUD before comparable analysis and scoring.",
            "Keep outreach integrations future-facing until the review workflow proves valuable.",
        ],
    )


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
            description="Model the first end-to-end slice so it can be created, inspected, and executed durably.",
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
    if _looks_like_real_estate_deal_finder(goal):
        return _real_estate_seed(goal)
    return _generic_seed(goal)


def serialize_goal_summary(goal: Goal) -> Dict[str, Any]:
    progress = compute_goal_progress(goal)
    return {
        "id": str(goal.id),
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
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
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
        return GoalRecommendation(
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
            reasoning_summary=reasoning,
            summary=f"Queue the next smallest slice from {thread.title if thread else entry.thread_title}: {task.title if task else entry.work_item_id}.",
        )
    paused_thread = (
        goal.threads.filter(status="paused")
        .prefetch_related("work_items")
        .order_by("created_at", "id")
        .first()
    )
    if paused_thread and paused_thread.work_items.filter(status="queued").exists():
        return GoalRecommendation(
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
            reasoning_summary=(
                f"{paused_thread.title} is paused with queued work. Resume it before queueing additional slices."
            ),
            summary=f"Resume {paused_thread.title} before queueing more work.",
        )
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
        return GoalRecommendation(
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
            reasoning_summary=reasoning,
            summary=f"Start with the smallest queued slice from {fallback_thread.title}: {fallback_task.title}.",
        )
    blocked_threads = [
        thread_item.title
        for thread_item in goal.threads.all().order_by("created_at", "id")
        if compute_thread_progress(thread_item).thread_status == "blocked"
    ]
    return GoalRecommendation(
        goal_id=str(goal.id),
        thread_id=None,
        thread_title="",
        work_item_id=None,
        work_item_title="",
        recommended_work_items=[],
        queue_suggestion=None,
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
    )
