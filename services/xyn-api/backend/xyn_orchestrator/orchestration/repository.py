from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db import transaction
from django.db.models import Max

from xyn_orchestrator.models import (
    OrchestrationJobRun,
    OrchestrationJobRunAttempt,
    OrchestrationJobRunOutput,
    OrchestrationPipeline,
    OrchestrationRun,
    UserIdentity,
    Workspace,
)

from .definitions import JobDefinition, JobOutputSpec, PipelineDefinition, RetryPolicy
from .interfaces import ExecutionScope, RunCreateRequest, RunTrigger
from .schedule_policy import CRON_UNSUPPORTED_MESSAGE, is_supported_schedule_kind
from .scheduling import ScheduledTrigger


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


class DjangoOrchestrationRepository:
    """ORM-backed orchestration repository.

    TODO: add optimistic lock version checks if concurrent workers start writing the same run records.
    """

    def get_pipeline_definition(self, *, workspace_id: str, pipeline_key: str) -> PipelineDefinition | None:
        pipeline = (
            OrchestrationPipeline.objects.filter(workspace_id=workspace_id, key=pipeline_key, enabled=True)
            .prefetch_related("job_definitions", "job_definitions__schedules", "job_dependencies")
            .first()
        )
        if pipeline is None:
            return None
        dependency_map: dict[str, list[str]] = {}
        for edge in pipeline.job_dependencies.all():
            dependency_map.setdefault(str(edge.downstream_job.job_key), []).append(str(edge.upstream_job.job_key))
        jobs: list[JobDefinition] = []
        for job in pipeline.job_definitions.all():
            if not job.enabled:
                continue
            for schedule_row in job.schedules.all():
                kind = str(schedule_row.schedule_kind or "").strip()
                if not is_supported_schedule_kind(kind):
                    if kind == "cron":
                        raise ValueError(CRON_UNSUPPORTED_MESSAGE)
                    raise ValueError(f"Unsupported schedule_kind '{kind}' in orchestration v1.")
            schedules = tuple(
                ScheduledTrigger(
                    key=str(schedule.schedule_key or "").strip(),
                    kind=str(schedule.schedule_kind or "manual").strip(),
                    enabled=bool(schedule.enabled),
                    cron_expression=str(schedule.cron_expression or "").strip(),
                    interval_seconds=int(schedule.interval_seconds or 0),
                    timezone_name=str(schedule.timezone_name or "UTC").strip() or "UTC",
                    description=str(_as_dict(schedule.metadata_json).get("description") or "").strip(),
                )
                for schedule in job.schedules.all()
                if bool(schedule.enabled)
            )
            metadata = _as_dict(job.metadata_json)
            metadata["schedules"] = [
                {
                    "schedule_key": schedule.key,
                    "kind": schedule.kind,
                    "cron_expression": schedule.cron_expression,
                    "interval_seconds": schedule.interval_seconds,
                    "timezone_name": schedule.timezone_name,
                }
                for schedule in schedules
            ]
            jobs.append(
                JobDefinition(
                    key=str(job.job_key),
                    stage_key=str(job.stage_key),
                    name=str(job.name),
                    handler_key=str(job.handler_key),
                    dependencies=tuple(dependency_map.get(str(job.job_key), [])),
                    retry_policy=RetryPolicy(
                        max_attempts=int(job.retry_max_attempts or 1),
                        initial_backoff_seconds=int(job.backoff_initial_seconds or 1),
                        max_backoff_seconds=int(job.backoff_max_seconds or 1),
                        multiplier=float(job.backoff_multiplier or 1.0),
                    ),
                    concurrency_limit=max(1, int(job.concurrency_limit or 1)),
                    only_if_upstream_changed=bool(job.only_if_upstream_changed),
                    runs_per_jurisdiction=bool(job.runs_per_jurisdiction),
                    runs_per_source=bool(job.runs_per_source),
                    output_spec=JobOutputSpec(
                        produces_artifact=bool(job.produces_artifact),
                        artifact_kind=str(job.artifact_kind or ""),
                    ),
                    metadata=metadata,
                )
            )
        return PipelineDefinition(
            key=str(pipeline.key),
            name=str(pipeline.name),
            jobs=tuple(jobs),
            triggers=tuple(),
            max_concurrency=max(1, int(pipeline.max_concurrency or 1)),
            stale_run_timeout_seconds=max(1, int(pipeline.stale_run_timeout_seconds or 1)),
            metadata=_as_dict(pipeline.metadata_json),
        )

    @transaction.atomic
    def create_run(self, request: RunCreateRequest) -> OrchestrationRun:
        workspace = Workspace.objects.get(id=request.workspace_id)
        pipeline = OrchestrationPipeline.objects.get(workspace=workspace, key=request.pipeline_key)
        initiated_by = UserIdentity.objects.filter(id=request.initiated_by_id).first() if request.initiated_by_id else None

        if request.rerun_of_run_id:
            rerun_of = OrchestrationRun.objects.filter(id=request.rerun_of_run_id, workspace=workspace).first()
        else:
            rerun_of = None

        existing = None
        idempotency_key = str(request.metadata.get("idempotency_key") or "").strip() if isinstance(request.metadata, dict) else ""
        if idempotency_key:
            existing = OrchestrationRun.objects.filter(
                workspace=workspace,
                pipeline=pipeline,
                idempotency_key=idempotency_key,
            ).first()
        if existing is not None:
            return existing

        correlation_id = str(request.metadata.get("correlation_id") or "").strip() if isinstance(request.metadata, dict) else ""
        chain_id = str(request.metadata.get("chain_id") or "").strip() if isinstance(request.metadata, dict) else ""
        dedupe_key = str(request.metadata.get("dedupe_key") or "").strip() if isinstance(request.metadata, dict) else ""
        run = OrchestrationRun.objects.create(
            workspace=workspace,
            pipeline=pipeline,
            status="pending",
            trigger_cause=request.trigger.trigger_cause,
            trigger_key=str(request.trigger.trigger_key or "").strip(),
            correlation_id=correlation_id,
            chain_id=chain_id,
            idempotency_key=idempotency_key,
            dedupe_key=dedupe_key,
            initiated_by=initiated_by,
            rerun_of=rerun_of,
            scope_jurisdiction=str(request.scope.jurisdiction or "").strip(),
            scope_source=str(request.scope.source or "").strip(),
            metadata_json=request.metadata if isinstance(request.metadata, dict) else {},
        )

        job_defs = list(pipeline.job_definitions.filter(enabled=True).order_by("stage_key", "job_key", "created_at"))
        OrchestrationJobRun.objects.bulk_create(
            [
                OrchestrationJobRun(
                    workspace=workspace,
                    pipeline=pipeline,
                    run=run,
                    job_definition=job,
                    status="pending",
                    trigger_cause=request.trigger.trigger_cause,
                    trigger_key=str(request.trigger.trigger_key or "").strip(),
                    correlation_id=correlation_id,
                    chain_id=chain_id,
                    scope_jurisdiction=str(request.scope.jurisdiction or "").strip(),
                    scope_source=str(request.scope.source or "").strip(),
                    idempotency_key=(f"{idempotency_key}:{job.job_key}" if idempotency_key else ""),
                    dedupe_key=(f"{dedupe_key}:{job.job_key}" if dedupe_key else ""),
                    max_attempts=max(1, int(job.retry_max_attempts or 1)),
                    metadata_json={},
                )
                for job in job_defs
            ]
        )
        return run

    @transaction.atomic
    def get_job_run_for_update(self, *, job_run_id: str) -> OrchestrationJobRun:
        return OrchestrationJobRun.objects.select_for_update().select_related("run", "job_definition", "pipeline", "workspace").get(id=job_run_id)

    def save_job_run(self, *, job_run: OrchestrationJobRun, update_fields: list[str]) -> None:
        normalized = [field for field in update_fields if field]
        if "updated_at" not in normalized:
            normalized.append("updated_at")
        job_run.save(update_fields=normalized)

    def create_attempt(self, *, job_run: OrchestrationJobRun, status: str, queued_at: datetime | None = None) -> OrchestrationJobRunAttempt:
        current = (
            OrchestrationJobRunAttempt.objects.filter(job_run=job_run)
            .aggregate(max_attempt=Max("attempt_number"))
            .get("max_attempt")
        ) or 0
        return OrchestrationJobRunAttempt.objects.create(
            job_run=job_run,
            attempt_number=int(current) + 1,
            status=status,
            queued_at=queued_at,
        )

    def latest_attempt(self, *, job_run: OrchestrationJobRun) -> OrchestrationJobRunAttempt | None:
        return OrchestrationJobRunAttempt.objects.filter(job_run=job_run).order_by("-attempt_number", "-created_at").first()

    def save_attempt(self, *, attempt: OrchestrationJobRunAttempt, update_fields: list[str]) -> None:
        normalized = [field for field in update_fields if field]
        if "updated_at" not in normalized:
            normalized.append("updated_at")
        attempt.save(update_fields=normalized)

    def record_output(
        self,
        *,
        job_run: OrchestrationJobRun,
        attempt: OrchestrationJobRunAttempt | None,
        output_key: str,
        output_type: str,
        output_uri: str = "",
        output_change_token: str = "",
        artifact_id: str = "",
        metadata: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> OrchestrationJobRunOutput:
        output, _created = OrchestrationJobRunOutput.objects.update_or_create(
            job_run=job_run,
            output_key=str(output_key or "").strip() or "default",
            defaults={
                "attempt": attempt,
                "output_type": str(output_type or "generic").strip() or "generic",
                "output_uri": str(output_uri or "").strip(),
                "output_change_token": str(output_change_token or "").strip(),
                "artifact_id": str(artifact_id or "").strip() or None,
                "metadata_json": metadata if isinstance(metadata, dict) else {},
                "payload_json": payload if isinstance(payload, dict) else {},
            },
        )
        return output

    def update_run_state(self, *, run: OrchestrationRun, status: str, summary: str = "", error_text: str = "", now: datetime | None = None) -> None:
        run.status = status
        if summary:
            run.summary = summary[:240]
        if error_text:
            run.error_text = error_text
        timestamp = now
        if status == "queued" and run.queued_at is None:
            run.queued_at = timestamp
        if status == "running":
            if run.started_at is None:
                run.started_at = timestamp
            run.heartbeat_at = timestamp
        if status in {"succeeded", "failed", "cancelled", "stale", "skipped"}:
            run.completed_at = timestamp
        run.save(update_fields=["status", "summary", "error_text", "queued_at", "started_at", "heartbeat_at", "completed_at", "updated_at"])

    def recompute_run_status(self, *, run: OrchestrationRun, now: datetime | None = None) -> str:
        statuses = list(run.job_runs.values_list("status", flat=True))
        if not statuses:
            return run.status
        next_status = run.status
        if any(status == "running" for status in statuses):
            next_status = "running"
        elif any(status in {"queued", "pending", "waiting_retry"} for status in statuses):
            next_status = "queued"
        elif any(status == "failed" for status in statuses):
            next_status = "failed"
        elif any(status == "stale" for status in statuses):
            next_status = "stale"
        elif any(status == "cancelled" for status in statuses):
            next_status = "cancelled"
        elif all(status in {"succeeded", "skipped"} for status in statuses):
            next_status = "succeeded"
        if next_status != run.status:
            self.update_run_state(run=run, status=next_status, now=now)
        return next_status

    def create_manual_rerun(self, *, run_id: str, requested_by_id: str = "") -> OrchestrationRun:
        run = OrchestrationRun.objects.select_related("workspace", "pipeline", "initiated_by").get(id=run_id)
        chain_id = str(run.chain_id or "").strip() or str(run.id)
        request = RunCreateRequest(
            workspace_id=str(run.workspace_id),
            pipeline_key=str(run.pipeline.key),
            trigger=RunTrigger(trigger_cause="retry", trigger_key="manual_rerun"),
            initiated_by_id=requested_by_id or (str(run.initiated_by_id) if run.initiated_by_id else ""),
            rerun_of_run_id=str(run.id),
            scope=ExecutionScope(jurisdiction=str(run.scope_jurisdiction or ""), source=str(run.scope_source or "")),
            metadata={
                "chain_id": chain_id,
                "correlation_id": str(run.correlation_id or "") or str(run.id),
                "rerun_requested_for": str(run.id),
            },
        )
        return self.create_run(request)
