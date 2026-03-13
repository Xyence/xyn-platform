from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional

from .execution_observability import ThreadTimelineEntry
from .goal_progress import ThreadExecutionMetrics, ThreadProgressSnapshot
from .models import CoordinationThread


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
