from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from django.db import transaction

from xyn_orchestrator.models import OrchestrationJobRun, OrchestrationRun

from .definitions import RetryPolicy
from .interfaces import RunCreateRequest
from .repository import DjangoOrchestrationRepository
from .service import exponential_backoff_seconds

RUN_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"queued", "running", "cancelled", "skipped", "stale"},
    "queued": {"running", "cancelled", "skipped", "stale"},
    "running": {"succeeded", "failed", "cancelled", "skipped", "stale"},
    "failed": {"queued", "running"},
    "succeeded": set(),
    "cancelled": set(),
    "skipped": set(),
    "stale": set(),
}

JOB_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"queued", "running", "skipped", "cancelled", "stale"},
    "queued": {"running", "skipped", "cancelled", "stale"},
    "running": {"succeeded", "failed", "skipped", "cancelled", "stale"},
    "failed": {"waiting_retry", "queued", "cancelled", "stale"},
    "waiting_retry": {"queued", "running", "cancelled", "stale"},
    "succeeded": set(),
    "skipped": set(),
    "cancelled": set(),
    "stale": set(),
}


@dataclass(frozen=True)
class OutputRecord:
    output_key: str
    output_type: str = "generic"
    output_uri: str = ""
    output_change_token: str = ""
    artifact_id: str = ""
    metadata: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None


class OrchestrationLifecycleService:
    def __init__(self, *, repository: DjangoOrchestrationRepository | None = None):
        self._repository = repository or DjangoOrchestrationRepository()

    def _now(self, now: datetime | None = None) -> datetime:
        return now or datetime.now(timezone.utc)

    def _assert_run_transition(self, current: str, nxt: str) -> None:
        if current == nxt:
            return
        allowed = RUN_ALLOWED_TRANSITIONS.get(str(current or "").strip().lower(), set())
        if nxt not in allowed:
            raise ValueError(f"illegal run transition: {current} -> {nxt}")

    def _assert_job_transition(self, current: str, nxt: str) -> None:
        if current == nxt:
            return
        allowed = JOB_ALLOWED_TRANSITIONS.get(str(current or "").strip().lower(), set())
        if nxt not in allowed:
            raise ValueError(f"illegal job transition: {current} -> {nxt}")

    @transaction.atomic
    def mark_job_queued(self, *, job_run_id: str, now: datetime | None = None, summary: str = "") -> OrchestrationJobRun:
        ts = self._now(now)
        job_run = self._repository.get_job_run_for_update(job_run_id=job_run_id)
        self._assert_job_transition(job_run.status, "queued")
        job_run.status = "queued"
        job_run.queued_at = job_run.queued_at or ts
        if summary:
            job_run.summary = summary[:240]
        self._repository.save_job_run(job_run=job_run, update_fields=["status", "queued_at", "summary"])
        run = job_run.run
        self._assert_run_transition(run.status, "queued")
        self._repository.update_run_state(run=run, status="queued", now=ts)
        return job_run

    @transaction.atomic
    def mark_job_running(self, *, job_run_id: str, now: datetime | None = None, summary: str = "") -> OrchestrationJobRun:
        ts = self._now(now)
        job_run = self._repository.get_job_run_for_update(job_run_id=job_run_id)
        previous_status = str(job_run.status or "")
        if job_run.status == "pending":
            self._assert_job_transition(job_run.status, "queued")
            job_run.status = "queued"
            job_run.queued_at = job_run.queued_at or ts
        self._assert_job_transition(job_run.status, "running")
        job_run.status = "running"
        job_run.started_at = job_run.started_at or ts
        job_run.heartbeat_at = ts
        if previous_status in {"pending", "queued", "waiting_retry"}:
            job_run.attempt_count = max(0, int(job_run.attempt_count or 0)) + 1
        else:
            job_run.attempt_count = max(1, int(job_run.attempt_count or 0))
        if summary:
            job_run.summary = summary[:240]
        self._repository.save_job_run(
            job_run=job_run,
            update_fields=["status", "queued_at", "started_at", "heartbeat_at", "attempt_count", "summary"],
        )

        attempt = self._repository.latest_attempt(job_run=job_run)
        if attempt is None or attempt.status in {"succeeded", "failed", "skipped", "cancelled", "stale"}:
            attempt = self._repository.create_attempt(job_run=job_run, status="running", queued_at=job_run.queued_at or ts)
        else:
            attempt.status = "running"
            attempt.started_at = attempt.started_at or ts
            attempt.heartbeat_at = ts
            self._repository.save_attempt(attempt=attempt, update_fields=["status", "started_at", "heartbeat_at"])

        run = job_run.run
        if run.status in {"pending", "queued"}:
            self._assert_run_transition(run.status, "running")
            self._repository.update_run_state(run=run, status="running", now=ts)
        elif run.status != "running":
            self._assert_run_transition(run.status, "running")
            self._repository.update_run_state(run=run, status="running", now=ts)
        return job_run

    @transaction.atomic
    def mark_job_succeeded(
        self,
        *,
        job_run_id: str,
        now: datetime | None = None,
        summary: str = "",
        metrics: dict[str, Any] | None = None,
        outputs: list[OutputRecord] | None = None,
        output_change_token: str = "",
    ) -> OrchestrationJobRun:
        ts = self._now(now)
        job_run = self._repository.get_job_run_for_update(job_run_id=job_run_id)
        self._assert_job_transition(job_run.status, "succeeded")
        job_run.status = "succeeded"
        job_run.completed_at = ts
        job_run.heartbeat_at = ts
        if summary:
            job_run.summary = summary[:240]
        if isinstance(metrics, dict):
            job_run.metrics_json = metrics
        if output_change_token:
            job_run.output_change_token = str(output_change_token).strip()
        self._repository.save_job_run(
            job_run=job_run,
            update_fields=["status", "completed_at", "heartbeat_at", "summary", "metrics_json", "output_change_token"],
        )

        attempt = self._repository.latest_attempt(job_run=job_run)
        if attempt is None:
            attempt = self._repository.create_attempt(job_run=job_run, status="succeeded", queued_at=job_run.queued_at or ts)
        attempt.status = "succeeded"
        attempt.completed_at = ts
        attempt.heartbeat_at = ts
        if summary:
            attempt.summary = summary[:240]
        if isinstance(metrics, dict):
            attempt.metrics_json = metrics
        self._repository.save_attempt(
            attempt=attempt,
            update_fields=["status", "completed_at", "heartbeat_at", "summary", "metrics_json"],
        )

        for output in outputs or []:
            self._repository.record_output(
                job_run=job_run,
                attempt=attempt,
                output_key=output.output_key,
                output_type=output.output_type,
                output_uri=output.output_uri,
                output_change_token=output.output_change_token or job_run.output_change_token,
                artifact_id=output.artifact_id,
                metadata=output.metadata,
                payload=output.payload,
            )

        self._repository.recompute_run_status(run=job_run.run, now=ts)
        return job_run

    @transaction.atomic
    def mark_job_failed(
        self,
        *,
        job_run_id: str,
        now: datetime | None = None,
        summary: str = "",
        error_text: str = "",
        error_details: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        retryable: bool = True,
    ) -> OrchestrationJobRun:
        ts = self._now(now)
        job_run = self._repository.get_job_run_for_update(job_run_id=job_run_id)
        self._assert_job_transition(job_run.status, "failed")

        attempt = self._repository.latest_attempt(job_run=job_run)
        if attempt is None:
            attempt = self._repository.create_attempt(job_run=job_run, status="failed", queued_at=job_run.queued_at or ts)
        attempt.status = "failed"
        attempt.completed_at = ts
        attempt.heartbeat_at = ts
        attempt.summary = summary[:240] if summary else attempt.summary
        attempt.error_text = error_text
        attempt.error_details_json = error_details if isinstance(error_details, dict) else attempt.error_details_json
        if isinstance(metrics, dict):
            attempt.metrics_json = metrics
        attempt.retryable = bool(retryable)
        self._repository.save_attempt(
            attempt=attempt,
            update_fields=["status", "completed_at", "heartbeat_at", "summary", "error_text", "error_details_json", "metrics_json", "retryable"],
        )

        if retryable and int(job_run.attempt_count or 0) < int(job_run.max_attempts or 1):
            policy = RetryPolicy(
                max_attempts=int(job_run.max_attempts or 1),
                initial_backoff_seconds=max(1, int(job_run.job_definition.backoff_initial_seconds or 1)),
                max_backoff_seconds=max(1, int(job_run.job_definition.backoff_max_seconds or 1)),
                multiplier=float(job_run.job_definition.backoff_multiplier or 1.0),
            )
            delay = exponential_backoff_seconds(attempt=max(1, int(job_run.attempt_count or 1)), policy=policy)
            self._assert_job_transition(job_run.status, "waiting_retry")
            job_run.status = "waiting_retry"
            job_run.next_attempt_at = ts + timedelta(seconds=delay)
            job_run.summary = summary[:240] if summary else job_run.summary
            job_run.error_text = error_text
            job_run.error_details_json = error_details if isinstance(error_details, dict) else job_run.error_details_json
            if isinstance(metrics, dict):
                job_run.metrics_json = metrics
            self._repository.save_job_run(
                job_run=job_run,
                update_fields=["status", "next_attempt_at", "summary", "error_text", "error_details_json", "metrics_json"],
            )
            self._repository.recompute_run_status(run=job_run.run, now=ts)
            return job_run

        job_run.status = "failed"
        job_run.completed_at = ts
        job_run.error_text = error_text
        job_run.error_details_json = error_details if isinstance(error_details, dict) else job_run.error_details_json
        if summary:
            job_run.summary = summary[:240]
        if isinstance(metrics, dict):
            job_run.metrics_json = metrics
        self._repository.save_job_run(
            job_run=job_run,
            update_fields=["status", "completed_at", "summary", "error_text", "error_details_json", "metrics_json"],
        )
        self._repository.recompute_run_status(run=job_run.run, now=ts)
        return job_run

    @transaction.atomic
    def mark_job_stale(self, *, job_run_id: str, now: datetime | None = None, reason: str = "heartbeat_timeout") -> OrchestrationJobRun:
        ts = self._now(now)
        job_run = self._repository.get_job_run_for_update(job_run_id=job_run_id)
        self._assert_job_transition(job_run.status, "stale")
        job_run.status = "stale"
        job_run.stale_at = ts
        job_run.stale_reason = str(reason or "stale").strip()[:120]
        job_run.completed_at = ts
        self._repository.save_job_run(
            job_run=job_run,
            update_fields=["status", "stale_at", "stale_reason", "completed_at"],
        )

        attempt = self._repository.latest_attempt(job_run=job_run)
        if attempt:
            attempt.status = "stale"
            attempt.stale_at = ts
            attempt.completed_at = ts
            attempt.error_text = attempt.error_text or "Job marked stale"
            self._repository.save_attempt(attempt=attempt, update_fields=["status", "stale_at", "completed_at", "error_text"])
        self._repository.recompute_run_status(run=job_run.run, now=ts)
        return job_run

    @transaction.atomic
    def mark_job_skipped(self, *, job_run_id: str, now: datetime | None = None, reason: str = "", summary: str = "") -> OrchestrationJobRun:
        ts = self._now(now)
        job_run = self._repository.get_job_run_for_update(job_run_id=job_run_id)
        self._assert_job_transition(job_run.status, "skipped")
        job_run.status = "skipped"
        job_run.skipped_reason = str(reason or "").strip()[:240]
        job_run.summary = (summary or job_run.summary)[:240]
        job_run.completed_at = ts
        self._repository.save_job_run(
            job_run=job_run,
            update_fields=["status", "skipped_reason", "summary", "completed_at"],
        )

        attempt = self._repository.latest_attempt(job_run=job_run)
        if attempt:
            attempt.status = "skipped"
            attempt.summary = (summary or attempt.summary)[:240]
            attempt.completed_at = ts
            self._repository.save_attempt(attempt=attempt, update_fields=["status", "summary", "completed_at"])
        self._repository.recompute_run_status(run=job_run.run, now=ts)
        return job_run

    def create_run(self, request: RunCreateRequest) -> OrchestrationRun:
        return self._repository.create_run(request)

    def request_rerun(self, *, run_id: str, requested_by_id: str = "") -> OrchestrationRun:
        return self._repository.create_manual_rerun(run_id=run_id, requested_by_id=requested_by_id)
