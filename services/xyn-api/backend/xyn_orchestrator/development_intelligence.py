from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set

from .execution_observability import ThreadTimelineEntry, build_thread_timeline, serialize_thread_timeline
from .goal_progress import (
    GoalExecutionMetrics,
    GoalHealthIndicators,
    GoalProgressSnapshot,
    ThreadExecutionMetrics,
    ThreadProgressSnapshot,
    compute_goal_execution_metrics,
    compute_goal_health_indicators,
    compute_goal_progress,
    compute_thread_execution_metrics,
    compute_thread_progress,
)
from .models import CoordinationThread, DevTask, Goal


SUPERVISED_APPROVAL_EVENT_TYPES = {
    "approval_recommendation",
    "approval_queue_first_slice",
    "approval_queue_next_slice",
    "approval_thread_resume",
}
SUPERVISED_QUEUE_EVENT_TYPES = {"work_item_promoted", "run_dispatched_from_queue"}
TERMINAL_FAILURE_STATUSES = {"failed", "blocked", "awaiting_review"}


@dataclass(frozen=True)
class ProvenanceAssessment:
    provenance_status: str
    supervised_queue_evidence: bool
    ambiguous_runtime_evidence: bool
    evidence: List[str]
    summary: str


@dataclass(frozen=True)
class ThreadDiagnostic:
    status: str
    observations: List[str]
    likely_causes: List[str]
    evidence: List[str]
    suggested_human_review_action: Optional[str]
    provenance: ProvenanceAssessment


@dataclass(frozen=True)
class GoalDiagnosticThread:
    thread_id: str
    title: str
    status: str


@dataclass(frozen=True)
class GoalDiagnostic:
    status: str
    observations: List[str]
    contributing_threads: List[GoalDiagnosticThread]
    evidence: List[str]
    suggested_human_review_focus: Optional[str]


@dataclass(frozen=True)
class ArtifactAnalysis:
    artifact_identity: str
    version_count: int
    recent_activity_count: int
    status: str
    observations: List[str]
    evidence: List[str]
    suggested_human_review_focus: Optional[str]
    provenance: ProvenanceAssessment


def _assess_thread_provenance(
    thread: CoordinationThread,
    *,
    timeline: List[ThreadTimelineEntry],
) -> ProvenanceAssessment:
    event_types = {str(event.event_type or "").strip() for event in thread.events.all()}
    supervised_run_ids = {
        str(event.run_id or "").strip()
        for event in thread.events.all()
        if str(event.event_type or "").strip() == "run_dispatched_from_queue" and str(event.run_id or "").strip()
    }
    runtime_run_ids = {
        str(entry.run_id or "").strip()
        for entry in timeline
        if entry.source == "run" and str(entry.run_id or "").strip()
    }
    supervised_queue_evidence = bool(event_types & (SUPERVISED_APPROVAL_EVENT_TYPES | SUPERVISED_QUEUE_EVENT_TYPES))
    ambiguous_runtime_evidence = bool(runtime_run_ids) and not bool(runtime_run_ids & supervised_run_ids)

    evidence: List[str] = []
    if supervised_run_ids:
        evidence.append(f"{len(supervised_run_ids)} run(s) have explicit queue dispatch events.")
    elif supervised_queue_evidence:
        evidence.append("Approval or queue promotion events are present for this thread.")
    if ambiguous_runtime_evidence:
        evidence.append("Runtime execution history exists without explicit supervised queue dispatch evidence.")

    if supervised_run_ids:
        status = "supervised_queue_proven"
        summary = "Supervised queue dispatch is proven for at least part of this thread."
    elif ambiguous_runtime_evidence:
        status = "runtime_provenance_ambiguous"
        summary = "Runtime execution history exists, but supervised queue provenance is not fully attributable from durable signals."
    else:
        status = "no_runtime_evidence"
        summary = "No runtime execution history is currently visible for this thread."

    return ProvenanceAssessment(
        provenance_status=status,
        supervised_queue_evidence=supervised_queue_evidence,
        ambiguous_runtime_evidence=ambiguous_runtime_evidence,
        evidence=evidence,
        summary=summary,
    )


def compute_thread_diagnostic(
    thread: CoordinationThread,
    *,
    progress: ThreadProgressSnapshot,
    metrics: ThreadExecutionMetrics,
    timeline: List[ThreadTimelineEntry],
    recent_runs: List[Dict[str, object]],
    recent_artifacts: List[Dict[str, object]],
) -> ThreadDiagnostic:
    provenance = _assess_thread_provenance(thread, timeline=timeline)
    observations: List[str] = []
    likely_causes: List[str] = []
    evidence: List[str] = list(provenance.evidence)
    suggested_action: Optional[str] = None

    recent_failure_count = sum(
        1
        for row in recent_runs[:5]
        if str((row or {}).get("status") or "").strip().lower() in {"failed", "blocked"}
    )
    family_counts = Counter(
        (
            str(row.get("artifact_type") or "").strip().lower(),
            str(row.get("label") or "").strip().lower(),
        )
        for row in recent_artifacts
        if isinstance(row, dict)
    )
    highest_artifact_family_count = max(family_counts.values(), default=0)

    status = "healthy"
    if recent_failure_count >= 2 or metrics.failed_work_items >= 2:
        status = "unstable"
        observations.append("Recent execution history shows repeated failures.")
        likely_causes.append("The thread is retrying or re-entering failure states without stabilizing.")
        evidence.append(f"{recent_failure_count or metrics.failed_work_items} recent failed or blocked run/result state(s) were observed.")
        suggested_action = "Inspect the most recent failing runs and associated artifacts before queueing more work."
    elif progress.thread_status == "blocked" or progress.work_items_blocked > 0:
        status = "blocked"
        observations.append("This thread has unfinished work that cannot currently proceed.")
        likely_causes.append("Dependencies or review-required work are blocking queue-ready progress.")
        evidence.append(f"{progress.work_items_blocked} blocked work item(s) are currently recorded.")
        suggested_action = "Review blocked work items and their dependency or review state."
    elif metrics.average_run_duration_seconds >= 1800:
        status = "slow"
        observations.append("Recent successful execution is taking longer than the baseline threshold.")
        likely_causes.append("Long-running implementation or validation steps are slowing the thread.")
        evidence.append(f"Average run duration is {metrics.average_run_duration_seconds} seconds.")
        suggested_action = "Review recent runs and artifacts to identify the slowest execution stage."
    elif progress.work_items_ready > 0 and metrics.total_completed_work_items == 0 and not recent_runs:
        status = "stalled"
        observations.append("Queueable work exists, but there is little or no durable execution progress yet.")
        likely_causes.append("Ready work is not progressing into visible runtime execution.")
        evidence.append(f"{progress.work_items_ready} ready work item(s) are available without recent runs.")
        suggested_action = "Confirm whether the next slice has been approved and queued."
    elif highest_artifact_family_count >= 3:
        status = "unstable"
        observations.append("Artifacts show rapid revision churn in the same logical family.")
        likely_causes.append("The thread may be iterating repeatedly without stabilizing outputs.")
        evidence.append(f"The most active artifact family has {highest_artifact_family_count} recent revisions.")
        suggested_action = "Review the repeated artifact revisions before approving another slice."
    elif not recent_runs and not recent_artifacts and metrics.total_completed_work_items == 0:
        status = "low_signal"
        observations.append("There is not enough recent runtime or artifact history to explain thread behavior confidently.")
        likely_causes.append("The thread may be newly created or have sparse durable execution evidence.")
        evidence.append("No recent runs or artifacts were found for this thread.")
        suggested_action = "Inspect the queued work items and approvals before drawing conclusions."
    else:
        observations.append("The thread shows recent progress without an obvious operational issue.")
        evidence.append(
            f"Completed work items: {metrics.total_completed_work_items}, failed work items: {metrics.failed_work_items}, blocked work items: {metrics.blocked_work_items}."
        )
        suggested_action = "Continue supervising the next slice through the normal approval loop."

    return ThreadDiagnostic(
        status=status,
        observations=observations,
        likely_causes=likely_causes,
        evidence=evidence,
        suggested_human_review_action=suggested_action,
        provenance=provenance,
    )


def build_thread_observability_bundle(
    thread: CoordinationThread,
    *,
    runtime_detail_lookup: Optional[Callable[[DevTask], Optional[Dict[str, Any]]]] = None,
) -> Dict[str, object]:
    progress = compute_thread_progress(thread)
    metrics = compute_thread_execution_metrics(thread, runtime_detail_lookup=runtime_detail_lookup)
    recent_artifacts: List[Dict[str, Any]] = []
    recent_runs: List[Dict[str, Any]] = []
    seen_run_ids: set[str] = set()
    for task in thread.work_items.all().order_by("-updated_at", "-created_at")[:20]:
        detail = runtime_detail_lookup(task) if callable(runtime_detail_lookup) else None
        if not isinstance(detail, dict):
            continue
        run_payload = {
            "id": str(detail.get("id") or detail.get("run_id") or ""),
            "status": detail.get("status"),
            "summary": detail.get("summary"),
            "failure_reason": detail.get("failure_reason"),
            "escalation_reason": detail.get("escalation_reason"),
            "started_at": detail.get("started_at"),
            "completed_at": detail.get("completed_at"),
        }
        run_id = str(run_payload.get("id") or "").strip()
        if run_id and run_id not in seen_run_ids:
            recent_runs.append(run_payload)
            seen_run_ids.add(run_id)
        artifacts = detail.get("artifacts") if isinstance(detail.get("artifacts"), list) else []
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            recent_artifacts.append(
                {
                    "id": str(artifact.get("artifact_id") or artifact.get("id") or "").strip(),
                    "run_id": run_id or None,
                    "work_item_id": str(task.work_item_id or task.id),
                    "artifact_type": str(artifact.get("artifact_type") or artifact.get("kind") or "").strip() or None,
                    "label": str(artifact.get("label") or artifact.get("name") or artifact.get("artifact_type") or "artifact"),
                    "uri": str(artifact.get("uri") or "").strip() or None,
                    "created_at": artifact.get("created_at"),
                    "metadata": artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {},
                }
            )
            if len(recent_artifacts) >= 20:
                break
        if len(recent_artifacts) >= 20 and len(recent_runs) >= 10:
            break
    timeline_entries = build_thread_timeline(thread, runtime_detail_lookup=runtime_detail_lookup)
    diagnostic = compute_thread_diagnostic(
        thread,
        progress=progress,
        metrics=metrics,
        timeline=timeline_entries,
        recent_runs=recent_runs,
        recent_artifacts=recent_artifacts,
    )
    return {
        "progress": progress,
        "metrics": metrics,
        "recent_runs": recent_runs,
        "recent_artifacts": recent_artifacts,
        "timeline_entries": timeline_entries,
        "timeline": serialize_thread_timeline(timeline_entries)[-100:],
        "diagnostic": diagnostic,
    }


def compute_goal_diagnostic(
    goal: Goal,
    *,
    runtime_detail_lookup: Optional[Callable[[DevTask], Optional[Dict[str, Any]]]] = None,
) -> GoalDiagnostic:
    progress = compute_goal_progress(goal)
    metrics = compute_goal_execution_metrics(goal, runtime_detail_lookup=runtime_detail_lookup)
    health = compute_goal_health_indicators(goal, runtime_detail_lookup=runtime_detail_lookup)
    thread_bundles = [
        (thread, build_thread_observability_bundle(thread, runtime_detail_lookup=runtime_detail_lookup))
        for thread in goal.threads.all().order_by("created_at", "id")
    ]
    observations: List[str] = []
    evidence: List[str] = []
    contributing_threads: List[GoalDiagnosticThread] = []
    suggested_focus: Optional[str] = None

    slow_threads = [
        thread
        for thread, bundle in thread_bundles
        if getattr(bundle["diagnostic"], "status", "") == "slow"
    ]
    blocked_threads = [
        thread
        for thread, bundle in thread_bundles
        if getattr(bundle["diagnostic"], "status", "") == "blocked"
    ]
    ambiguous_threads = [
        thread
        for thread, bundle in thread_bundles
        if getattr(bundle["diagnostic"], "provenance").ambiguous_runtime_evidence
    ]

    status = "healthy"
    if progress.goal_progress_status == "completed":
        status = "completed"
        observations.append("All currently tracked work for this goal is complete.")
        evidence.append(f"{progress.completed_work_items} work item(s) are completed and no unfinished work remains.")
    elif blocked_threads or progress.goal_progress_status == "stalled":
        status = "blocked"
        observations.append("Blocked thread state is preventing smooth forward progress on the goal.")
        evidence.append(f"{health.blocked_threads} blocked thread(s) and {progress.blocked_work_items} blocked work item(s) are present.")
        contributing_threads = [
            GoalDiagnosticThread(thread_id=str(thread.id), title=str(thread.title), status="blocked")
            for thread in blocked_threads[:5]
        ]
        suggested_focus = "Review the blocked threads and clear dependency or review constraints before approving more work."
    elif health.active_threads >= 3 and progress.completed_work_items <= 1:
        status = "fragmented"
        observations.append("Work is spread across several active threads with limited completed output.")
        evidence.append(f"{health.active_threads} active thread(s) are in progress with only {progress.completed_work_items} completed work item(s).")
        contributing_threads = [
            GoalDiagnosticThread(thread_id=str(thread.id), title=str(thread.title), status=str(bundle["progress"].thread_status))
            for thread, bundle in thread_bundles[:5]
        ]
        suggested_focus = "Reduce fragmentation by finishing one active thread before widening concurrency."
    elif health.recent_artifacts >= 4 and progress.completed_work_items <= 1:
        status = "high_activity_low_progress"
        observations.append("Recent artifact activity is high relative to completed work.")
        evidence.append(f"{health.recent_artifacts} recent artifact(s) were observed with only {progress.completed_work_items} completed work item(s).")
        suggested_focus = "Inspect recent artifacts to see whether the thread is revising outputs without landing completed work."
    elif slow_threads:
        status = "slow"
        observations.append("At least one active thread is running slower than the baseline threshold.")
        evidence.append(f"{len(slow_threads)} slow thread(s) were detected from execution duration metrics.")
        contributing_threads = [
            GoalDiagnosticThread(thread_id=str(thread.id), title=str(thread.title), status="slow")
            for thread in slow_threads[:5]
        ]
        suggested_focus = "Inspect the slow threads before approving broader parallel work."
    elif not goal.threads.exists() or (metrics.total_completed_work_items == 0 and not health.recent_artifacts):
        status = "low_signal"
        observations.append("There is not enough execution evidence yet to explain this goal confidently.")
        evidence.append("The goal has sparse thread, run, or artifact history.")
        suggested_focus = "Review the initial thread and work-item structure before interpreting progress."
    else:
        observations.append("The goal shows active development without a dominant diagnostic issue.")
        evidence.append(
            f"{metrics.total_completed_work_items} work item(s) completed across {health.active_threads} active and {health.blocked_threads} blocked thread(s)."
        )
        suggested_focus = "Continue supervising the next recommended slice."

    if ambiguous_threads:
        evidence.append(
            f"{len(ambiguous_threads)} thread(s) include runtime history whose supervised queue provenance is not fully attributable from durable signals."
        )
        if not contributing_threads:
            contributing_threads = [
                GoalDiagnosticThread(thread_id=str(thread.id), title=str(thread.title), status="runtime_provenance_ambiguous")
                for thread in ambiguous_threads[:5]
            ]

    return GoalDiagnostic(
        status=status,
        observations=observations,
        contributing_threads=contributing_threads,
        evidence=evidence,
        suggested_human_review_focus=suggested_focus,
    )


def serialize_thread_diagnostic(diagnostic: ThreadDiagnostic) -> Dict[str, object]:
    return {
        "status": diagnostic.status,
        "observations": diagnostic.observations,
        "likely_causes": diagnostic.likely_causes,
        "evidence": diagnostic.evidence,
        "suggested_human_review_action": diagnostic.suggested_human_review_action,
        "provenance": {
            "provenance_status": diagnostic.provenance.provenance_status,
            "supervised_queue_evidence": diagnostic.provenance.supervised_queue_evidence,
            "ambiguous_runtime_evidence": diagnostic.provenance.ambiguous_runtime_evidence,
            "evidence": diagnostic.provenance.evidence,
            "summary": diagnostic.provenance.summary,
        },
    }


def serialize_goal_diagnostic(diagnostic: GoalDiagnostic) -> Dict[str, object]:
    return {
        "status": diagnostic.status,
        "observations": diagnostic.observations,
        "contributing_threads": [
            {
                "thread_id": item.thread_id,
                "title": item.title,
                "status": item.status,
            }
            for item in diagnostic.contributing_threads
        ],
        "evidence": diagnostic.evidence,
        "suggested_human_review_focus": diagnostic.suggested_human_review_focus,
    }


def build_artifact_analysis_context(
    *,
    workspace,
    evolution: List[Dict[str, Any]],
    runtime_detail_lookup: Optional[Callable[[DevTask], Optional[Dict[str, Any]]]] = None,
) -> Dict[str, object]:
    work_item_ids = {
        str(row.get("work_item_id") or "").strip()
        for row in evolution
        if isinstance(row, dict) and str(row.get("work_item_id") or "").strip()
    }
    tasks = (
        DevTask.objects.select_related("coordination_thread")
        .filter(runtime_workspace_id=workspace.id, work_item_id__in=work_item_ids)
        .order_by("created_at", "id")
    )
    run_status_by_run_id: Dict[str, str] = {}
    supervised_run_ids: Set[str] = set()
    for task in tasks:
        detail = runtime_detail_lookup(task) if callable(runtime_detail_lookup) else None
        if not isinstance(detail, dict):
            continue
        run_id = str(detail.get("run_id") or detail.get("id") or "").strip()
        if not run_id:
            continue
        status = str(detail.get("status") or task.status or "").strip().lower()
        if status:
            run_status_by_run_id[run_id] = status
        thread = getattr(task, "coordination_thread", None)
        if thread is None:
            continue
        if thread.events.filter(event_type="run_dispatched_from_queue", run_id=run_id).exists():
            supervised_run_ids.add(run_id)
    return {
        "run_status_by_run_id": run_status_by_run_id,
        "supervised_run_ids": supervised_run_ids,
    }


def compute_artifact_analysis(
    *,
    current_artifact: Dict[str, Any],
    evolution: List[Dict[str, Any]],
    run_status_by_run_id: Optional[Dict[str, str]] = None,
    supervised_run_ids: Optional[Set[str]] = None,
) -> ArtifactAnalysis:
    rows = [row for row in evolution if isinstance(row, dict)]
    run_status_by_run_id = run_status_by_run_id or {}
    supervised_run_ids = supervised_run_ids or set()

    artifact_identity = str(
        current_artifact.get("label")
        or current_artifact.get("artifact_type")
        or current_artifact.get("artifact_id")
        or "artifact"
    ).strip()
    version_count = len(rows)
    recent_activity_count = min(version_count, 5)
    observations: List[str] = []
    evidence: List[str] = []
    suggested_focus: Optional[str] = None

    failed_revision_count = 0
    missing_lineage = False
    run_ids: Set[str] = set()
    for row in rows:
        run_id = str(row.get("run_id") or "").strip()
        if run_id:
            run_ids.add(run_id)
        else:
            missing_lineage = True
        if not row.get("created_at"):
            missing_lineage = True
        status = str(run_status_by_run_id.get(run_id) or "").strip().lower()
        if status in TERMINAL_FAILURE_STATUSES:
            failed_revision_count += 1

    supervised_queue_evidence = bool(run_ids & supervised_run_ids)
    ambiguous_runtime_evidence = bool(run_ids) and not supervised_queue_evidence
    provenance_evidence: List[str] = []
    if supervised_queue_evidence:
        provenance_evidence.append("At least one artifact revision is linked to an explicit supervised queue dispatch event.")
        provenance_status = "supervised_queue_proven"
        provenance_summary = "Supervised queue provenance is proven for at least part of this artifact history."
    elif ambiguous_runtime_evidence:
        provenance_evidence.append("Artifact revisions have runtime execution history without explicit supervised queue dispatch evidence.")
        provenance_status = "runtime_provenance_ambiguous"
        provenance_summary = "Artifact history includes runtime execution, but supervised queue provenance is not fully attributable from durable signals."
    else:
        provenance_status = "no_runtime_evidence"
        provenance_summary = "No runtime execution history is currently visible for this artifact family."

    status = "stable_progression"
    if failed_revision_count >= 2:
        status = "repeated_failed_revisions"
        observations.append("Recent artifact revisions are linked to repeated failed or blocked execution results.")
        evidence.append(f"{failed_revision_count} recent revision(s) are linked to failed or blocked run states.")
        suggested_focus = "Inspect the failing revisions and linked run outputs before approving another iteration."
    elif version_count >= 4:
        status = "high_churn"
        observations.append("This artifact family has been revised frequently in recent history.")
        evidence.append(f"{version_count} total revisions were observed for this artifact family.")
        suggested_focus = "Review whether recent revisions are converging on a stable output before queueing more work."
    elif version_count <= 1 or missing_lineage:
        status = "sparse_history"
        observations.append("Artifact lineage is sparse or partially linked.")
        evidence.append("There is too little or too incomplete version history to infer a strong revision pattern.")
        suggested_focus = "Inspect the surrounding thread and run history before drawing conclusions from this artifact family."
    else:
        observations.append("Artifact history shows steady progression without repeated failed revisions.")
        evidence.append(f"{version_count} revision(s) are present without repeated failure-linked churn.")
        suggested_focus = "Continue reviewing later revisions for substantive changes."

    evidence.extend(provenance_evidence)
    return ArtifactAnalysis(
        artifact_identity=artifact_identity,
        version_count=version_count,
        recent_activity_count=recent_activity_count,
        status=status,
        observations=observations,
        evidence=evidence,
        suggested_human_review_focus=suggested_focus,
        provenance=ProvenanceAssessment(
            provenance_status=provenance_status,
            supervised_queue_evidence=supervised_queue_evidence,
            ambiguous_runtime_evidence=ambiguous_runtime_evidence,
            evidence=provenance_evidence,
            summary=provenance_summary,
        ),
    )


def serialize_artifact_analysis(analysis: ArtifactAnalysis) -> Dict[str, object]:
    return {
        "artifact_identity": analysis.artifact_identity,
        "version_count": analysis.version_count,
        "recent_activity_count": analysis.recent_activity_count,
        "status": analysis.status,
        "observations": analysis.observations,
        "evidence": analysis.evidence,
        "suggested_human_review_focus": analysis.suggested_human_review_focus,
        "provenance": {
            "provenance_status": analysis.provenance.provenance_status,
            "supervised_queue_evidence": analysis.provenance.supervised_queue_evidence,
            "ambiguous_runtime_evidence": analysis.provenance.ambiguous_runtime_evidence,
            "evidence": analysis.provenance.evidence,
            "summary": analysis.provenance.summary,
        },
    }
