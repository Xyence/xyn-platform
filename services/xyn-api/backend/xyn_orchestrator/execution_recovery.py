from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .execution_briefs import execution_brief_readiness
from .models import DevTask


RECOVERY_SUPPORTED_TASK_TYPES = {"codegen"}
RECOVERY_ACTIVE_STATES = {"queued", "running"}
RECOVERY_FAILURE_STATES = {"failed"}


@dataclass(frozen=True)
class DevTaskRecoveryState:
    retryable: bool
    requeueable: bool
    in_flight: bool
    failed: bool
    blocked: bool
    status: str
    reason: Optional[str]
    message: str
    available_actions: tuple[str, ...]
    last_failure: Optional[Dict[str, Any]]


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _stored_failure_snapshot(task: DevTask) -> Optional[Dict[str, Any]]:
    policy = task.execution_policy if isinstance(task.execution_policy, dict) else {}
    recovery = policy.get("recovery") if isinstance(policy.get("recovery"), dict) else {}
    failure = recovery.get("last_failure") if isinstance(recovery.get("last_failure"), dict) else None
    if not failure:
        return None
    return {
        "run_id": _clean_text(failure.get("run_id")) or None,
        "source": _clean_text(failure.get("source")) or None,
        "state": _clean_text(failure.get("state")) or None,
        "summary": _clean_text(failure.get("summary")) or None,
        "error": _clean_text(failure.get("error")) or None,
        "finished_at": failure.get("finished_at"),
        "recorded_at": failure.get("recorded_at"),
        "action": _clean_text(failure.get("action")) or None,
    }


def snapshot_execution_failure(
    *,
    execution_summary: Optional[Dict[str, Any]],
    action: str = "",
    recorded_at: str | None = None,
) -> Optional[Dict[str, Any]]:
    summary = execution_summary if isinstance(execution_summary, dict) else {}
    state = _clean_text(summary.get("state")).lower()
    if state not in RECOVERY_FAILURE_STATES and state not in {"awaiting_review"}:
        return None
    error = _clean_text(summary.get("error"))
    summary_text = _clean_text(summary.get("summary"))
    if not error and not summary_text:
        return None
    return {
        "run_id": _clean_text(summary.get("run_id")) or None,
        "source": _clean_text(summary.get("source")) or None,
        "state": state,
        "summary": summary_text or None,
        "error": error or None,
        "finished_at": summary.get("finished_at"),
        "recorded_at": recorded_at,
        "action": _clean_text(action) or None,
    }


def record_execution_failure_snapshot(
    task: DevTask,
    *,
    execution_summary: Optional[Dict[str, Any]],
    action: str,
    recorded_at: str | None = None,
) -> bool:
    snapshot = snapshot_execution_failure(execution_summary=execution_summary, action=action, recorded_at=recorded_at)
    if not snapshot:
        return False
    policy = dict(task.execution_policy or {}) if isinstance(task.execution_policy, dict) else {}
    recovery = dict(policy.get("recovery") or {}) if isinstance(policy.get("recovery"), dict) else {}
    recovery["last_failure"] = snapshot
    policy["recovery"] = recovery
    task.execution_policy = policy
    return True


def evaluate_dev_task_recovery_state(
    task: DevTask,
    *,
    execution_summary: Optional[Dict[str, Any]] = None,
) -> DevTaskRecoveryState:
    task_type = _clean_text(task.task_type).lower()
    state = _clean_text((execution_summary or {}).get("state")).lower() or _clean_text(task.status).lower() or "not_started"
    current_failure = snapshot_execution_failure(execution_summary=execution_summary)
    last_failure = current_failure or _stored_failure_snapshot(task)

    if task_type not in RECOVERY_SUPPORTED_TASK_TYPES:
        return DevTaskRecoveryState(
            retryable=False,
            requeueable=False,
            in_flight=False,
            failed=False,
            blocked=True,
            status="unsupported",
            reason="unsupported_task_type",
            message="Task type does not support execution recovery actions.",
            available_actions=(),
            last_failure=last_failure,
        )
    if state in RECOVERY_ACTIVE_STATES:
        return DevTaskRecoveryState(
            retryable=False,
            requeueable=False,
            in_flight=True,
            failed=False,
            blocked=True,
            status="in_flight",
            reason="in_flight",
            message="Execution is already in progress and cannot be retried or requeued.",
            available_actions=(),
            last_failure=last_failure,
        )
    if state == "completed":
        return DevTaskRecoveryState(
            retryable=False,
            requeueable=False,
            in_flight=False,
            failed=False,
            blocked=False,
            status="completed",
            reason="completed",
            message="Execution has already completed successfully.",
            available_actions=(),
            last_failure=last_failure,
        )
    if state == "awaiting_review":
        return DevTaskRecoveryState(
            retryable=False,
            requeueable=False,
            in_flight=False,
            failed=False,
            blocked=True,
            status="review_blocked",
            reason="awaiting_review",
            message="Execution is awaiting review and cannot be retried or requeued yet.",
            available_actions=(),
            last_failure=last_failure,
        )
    if state in RECOVERY_FAILURE_STATES or _clean_text(task.status).lower() == "canceled":
        readiness = execution_brief_readiness(task)
        if not readiness.executable:
            return DevTaskRecoveryState(
                retryable=False,
                requeueable=False,
                in_flight=False,
                failed=True,
                blocked=True,
                status="blocked",
                reason=readiness.reason,
                message=readiness.message,
                available_actions=(),
                last_failure=last_failure,
            )
        return DevTaskRecoveryState(
            retryable=True,
            requeueable=True,
            in_flight=False,
            failed=True,
            blocked=False,
            status="retryable",
            reason=None,
            message="Execution failed and can be retried now or returned to the queue.",
            available_actions=("retry_now", "requeue"),
            last_failure=last_failure,
        )
    if _clean_text(task.status).lower() == "queued" and last_failure:
        return DevTaskRecoveryState(
            retryable=False,
            requeueable=False,
            in_flight=False,
            failed=False,
            blocked=False,
            status="requeued",
            reason="requeued",
            message="Task has been returned to the execution queue after a failed run.",
            available_actions=(),
            last_failure=last_failure,
        )
    return DevTaskRecoveryState(
        retryable=False,
        requeueable=False,
        in_flight=False,
        failed=False,
        blocked=False,
        status="not_applicable",
        reason="not_failed",
        message="No failed execution is available to recover.",
        available_actions=(),
        last_failure=last_failure,
    )


def serialize_dev_task_recovery_state(
    task: DevTask,
    *,
    execution_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    state = evaluate_dev_task_recovery_state(task, execution_summary=execution_summary)
    return {
        "retryable": state.retryable,
        "requeueable": state.requeueable,
        "in_flight": state.in_flight,
        "failed": state.failed,
        "blocked": state.blocked,
        "status": state.status,
        "reason": state.reason,
        "message": state.message,
        "available_actions": list(state.available_actions),
        "last_failure": state.last_failure,
    }
