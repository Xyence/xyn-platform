from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .definitions import RetryPolicy
from .interfaces import FailureNotifier, JobExecutionResult, OrchestrationRepository, RunCreateRequest


@dataclass(frozen=True)
class BackoffSchedule:
    attempt: int
    delay_seconds: int


def exponential_backoff_seconds(*, attempt: int, policy: RetryPolicy) -> int:
    normalized_attempt = max(1, int(attempt or 1))
    base = max(1, int(policy.initial_backoff_seconds or 1))
    ceiling = max(base, int(policy.max_backoff_seconds or base))
    multiplier = float(policy.multiplier or 1.0)
    computed = int(base * (multiplier ** (normalized_attempt - 1)))
    return max(base, min(ceiling, computed))


class JobOrchestrationService:
    """Service seam for orchestration run lifecycle management.

    TODO: wire to scheduler worker loop and persistence-backed dependency evaluation.
    """

    def __init__(
        self,
        *,
        repository: OrchestrationRepository,
        failure_notifier: FailureNotifier | None = None,
    ):
        self._repository = repository
        self._failure_notifier = failure_notifier

    def create_run(self, request: RunCreateRequest) -> dict[str, Any]:
        pipeline = self._repository.get_pipeline_definition(
            workspace_id=request.workspace_id,
            pipeline_key=request.pipeline_key,
        )
        if pipeline is None:
            raise ValueError("pipeline definition not found")
        return self._repository.create_run(request)

    def mark_job_failure(
        self,
        *,
        workspace_id: str,
        run_id: str,
        pipeline_key: str,
        job_key: str,
        result: JobExecutionResult,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self._failure_notifier is None:
            return
        self._failure_notifier.notify_run_failure(
            workspace_id=workspace_id,
            run_id=run_id,
            pipeline_key=pipeline_key,
            job_key=job_key,
            error_text=result.error_text or result.summary,
            metadata=metadata or {},
        )

    def detect_and_mark_stale_runs(self, *, now: datetime | None = None) -> list[str]:
        checked_at = now or datetime.now(timezone.utc)
        stale_rows = self._repository.list_stale_running_jobs(now=checked_at)
        stale_job_run_ids: list[str] = []
        for row in stale_rows:
            self._repository.mark_job_stale(
                job_run_id=row.job_run_id,
                stale_at=checked_at,
                reason="heartbeat_timeout",
            )
            stale_job_run_ids.append(row.job_run_id)
            # TODO: propagate stale terminal state to dependent jobs in the same run.
            self.mark_job_failure(
                workspace_id=row.workspace_id,
                run_id=row.run_id,
                pipeline_key=row.pipeline_key,
                job_key=row.job_key,
                result=JobExecutionResult(status="stale", summary="Job marked stale", error_text="Job heartbeat timed out"),
                metadata={"reason": "heartbeat_timeout", "stale_at": checked_at.isoformat()},
            )
        return stale_job_run_ids

    def rerun(self, *, run_id: str, requested_by_id: str = "") -> dict[str, Any]:
        # TODO: support rerun scopes (failed-only, selected stage, selected job).
        return self._repository.create_manual_rerun(run_id=run_id, requested_by_id=requested_by_id)
