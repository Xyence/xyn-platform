from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import Any

from django.db import transaction
from django.db.models import Q

from xyn_orchestrator.models import (
    OrchestrationJobDependency,
    OrchestrationJobDefinition,
    OrchestrationJobRun,
    OrchestrationJobSchedule,
    OrchestrationPipeline,
    OrchestrationRun,
)

from .interfaces import ExecutionScope, JobExecutionContext, JobExecutionResult, JobExecutor, RunCreateRequest, RunTrigger
from .lifecycle import OrchestrationLifecycleService, OutputRecord
from .repository import DjangoOrchestrationRepository

logger = logging.getLogger(__name__)

TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled", "skipped", "stale"}
BLOCKED_BY_FAILURE_STATUSES = {"failed", "cancelled", "stale"}


@dataclass(frozen=True)
class DueScheduleItem:
    schedule_id: str
    workspace_id: str
    pipeline_key: str
    pipeline_id: str
    job_definition_id: str
    job_key: str
    trigger_key: str
    schedule_kind: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class DispatchDecision:
    job_run_id: str
    allowed: bool
    reason: str


class DueJobScanner:
    def __init__(self, *, default_lookahead_seconds: int = 5):
        self._default_lookahead_seconds = max(0, int(default_lookahead_seconds))

    def scan_due_schedules(self, *, now: datetime | None = None, limit: int = 200) -> list[DueScheduleItem]:
        ts = now or datetime.now(timezone.utc)
        horizon = ts + timedelta(seconds=self._default_lookahead_seconds)
        rows = (
            OrchestrationJobSchedule.objects.select_related("job_definition", "job_definition__pipeline", "job_definition__pipeline__workspace")
            .filter(enabled=True)
            .filter(job_definition__enabled=True, job_definition__pipeline__enabled=True)
            .filter(next_fire_at__isnull=False, next_fire_at__lte=horizon)
            .order_by("next_fire_at", "created_at")[: max(1, int(limit or 1))]
        )
        due_items: list[DueScheduleItem] = []
        for row in rows:
            metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
            due_items.append(
                DueScheduleItem(
                    schedule_id=str(row.id),
                    workspace_id=str(row.job_definition.pipeline.workspace_id),
                    pipeline_key=str(row.job_definition.pipeline.key),
                    pipeline_id=str(row.job_definition.pipeline_id),
                    job_definition_id=str(row.job_definition_id),
                    job_key=str(row.job_definition.job_key),
                    trigger_key=str(row.schedule_key),
                    schedule_kind=str(row.schedule_kind),
                    metadata=metadata,
                )
            )
        return due_items


class RunPlanner:
    def __init__(
        self,
        *,
        lifecycle: OrchestrationLifecycleService | None = None,
        repository: DjangoOrchestrationRepository | None = None,
    ):
        self._repository = repository or DjangoOrchestrationRepository()
        self._lifecycle = lifecycle or OrchestrationLifecycleService(repository=self._repository)

    def _partition_values(self, *, metadata: dict[str, Any], job_definition: OrchestrationJobDefinition) -> list[tuple[str, str]]:
        if not isinstance(metadata, dict):
            metadata = {}
        jurisdictions = metadata.get("jurisdictions") if isinstance(metadata.get("jurisdictions"), list) else []
        sources = metadata.get("sources") if isinstance(metadata.get("sources"), list) else []
        normalized_jurisdictions = [str(value or "").strip() for value in jurisdictions if str(value or "").strip()]
        normalized_sources = [str(value or "").strip() for value in sources if str(value or "").strip()]

        jurisdiction_values = normalized_jurisdictions if (job_definition.runs_per_jurisdiction and normalized_jurisdictions) else [""]
        source_values = normalized_sources if (job_definition.runs_per_source and normalized_sources) else [""]

        return list(itertools.product(jurisdiction_values, source_values))

    @transaction.atomic
    def create_runs_for_due_schedule(self, *, due: DueScheduleItem, now: datetime | None = None) -> list[OrchestrationRun]:
        ts = now or datetime.now(timezone.utc)
        schedule = OrchestrationJobSchedule.objects.select_for_update().select_related("job_definition", "job_definition__pipeline").get(id=due.schedule_id)
        if not schedule.enabled:
            return []
        if schedule.next_fire_at and schedule.next_fire_at > ts:
            return []

        job_def = schedule.job_definition
        created_runs: list[OrchestrationRun] = []
        for jurisdiction, source in self._partition_values(metadata=due.metadata, job_definition=job_def):
            correlation_id = str(due.metadata.get("correlation_id") or "").strip() or f"sched:{due.schedule_id}:{ts.isoformat()}"
            chain_id = str(due.metadata.get("chain_id") or "").strip() or correlation_id
            dedupe_key = ":".join([token for token in ["sched", due.schedule_id, jurisdiction, source, ts.strftime("%Y%m%d%H%M")] if token])
            run = self._lifecycle.create_run(
                RunCreateRequest(
                    workspace_id=due.workspace_id,
                    pipeline_key=due.pipeline_key,
                    trigger=RunTrigger(trigger_cause="scheduled", trigger_key=due.trigger_key),
                    scope=self._repository_scope(jurisdiction=jurisdiction, source=source),
                    metadata={
                        "schedule_id": due.schedule_id,
                        "schedule_kind": due.schedule_kind,
                        "scheduled_at": ts.isoformat(),
                        "correlation_id": correlation_id,
                        "chain_id": chain_id,
                        "dedupe_key": dedupe_key,
                        "idempotency_key": dedupe_key,
                    },
                )
            )
            created_runs.append(run)

        schedule.last_fired_at = ts
        if schedule.schedule_kind == "interval" and int(schedule.interval_seconds or 0) > 0:
            schedule.next_fire_at = ts + timedelta(seconds=int(schedule.interval_seconds))
        elif schedule.schedule_kind == "cron":
            # TODO: add robust cron parser; current behavior advances by one hour for scaffold runtime.
            schedule.next_fire_at = ts + timedelta(hours=1)
        else:
            schedule.next_fire_at = None
        schedule.save(update_fields=["last_fired_at", "next_fire_at", "updated_at"])

        logger.info(
            "orchestration.schedule.materialized",
            extra={
                "schedule_id": due.schedule_id,
                "workspace_id": due.workspace_id,
                "pipeline_key": due.pipeline_key,
                "created_run_count": len(created_runs),
            },
        )
        return created_runs

    @staticmethod
    def _repository_scope(*, jurisdiction: str, source: str):
        from .interfaces import ExecutionScope

        return ExecutionScope(jurisdiction=jurisdiction, source=source)


class DependencyResolver:
    def __init__(self, *, lifecycle: OrchestrationLifecycleService | None = None, repository: DjangoOrchestrationRepository | None = None):
        self._repository = repository or DjangoOrchestrationRepository()
        self._lifecycle = lifecycle or OrchestrationLifecycleService(repository=self._repository)

    def _dependency_map(self, *, pipeline: OrchestrationPipeline) -> dict[str, list[str]]:
        edges = OrchestrationJobDependency.objects.filter(pipeline=pipeline).select_related("upstream_job", "downstream_job")
        mapping: dict[str, list[str]] = {}
        for edge in edges:
            mapping.setdefault(str(edge.downstream_job.job_key), []).append(str(edge.upstream_job.job_key))
        return mapping

    @transaction.atomic
    def queue_ready_jobs(self, *, run: OrchestrationRun, now: datetime | None = None) -> list[str]:
        ts = now or datetime.now(timezone.utc)
        job_runs = list(
            OrchestrationJobRun.objects.select_for_update()
            .select_related("job_definition")
            .filter(run=run)
            .order_by("job_definition__stage_key", "job_definition__job_key", "created_at")
        )
        by_key = {str(row.job_definition.job_key): row for row in job_runs}
        dependency_map = self._dependency_map(pipeline=run.pipeline)

        queued_ids: list[str] = []
        for row in job_runs:
            if row.status not in {"pending", "waiting_retry"}:
                continue

            dependencies = dependency_map.get(str(row.job_definition.job_key), [])
            if not dependencies and row.status == "pending":
                self._lifecycle.mark_job_queued(job_run_id=str(row.id), now=ts, summary="ready: no dependencies")
                queued_ids.append(str(row.id))
                continue
            if not dependencies and row.status == "waiting_retry":
                # Retry readiness is time-gated by next_attempt_at and handled by the dispatcher.
                continue

            upstream_rows = [by_key.get(dep) for dep in dependencies if by_key.get(dep) is not None]
            if len(upstream_rows) != len(dependencies):
                continue

            upstream_statuses = {str(item.status) for item in upstream_rows}
            if any(status not in TERMINAL_JOB_STATUSES for status in upstream_statuses):
                continue

            if upstream_statuses.intersection(BLOCKED_BY_FAILURE_STATUSES):
                self._lifecycle.mark_job_skipped(
                    job_run_id=str(row.id),
                    now=ts,
                    reason="upstream_failed",
                    summary="Skipped because an upstream dependency failed.",
                )
                continue

            if row.job_definition.only_if_upstream_changed:
                changed = any(bool(str(item.output_change_token or "").strip()) for item in upstream_rows)
                if not changed:
                    self._lifecycle.mark_job_skipped(
                        job_run_id=str(row.id),
                        now=ts,
                        reason="upstream_unchanged",
                        summary="Skipped because upstream did not report changes.",
                    )
                    continue

            self._lifecycle.mark_job_queued(job_run_id=str(row.id), now=ts, summary="ready: dependencies satisfied")
            queued_ids.append(str(row.id))
        return queued_ids


class ConcurrencyGuard:
    def __init__(self, *, global_limit: int = 20):
        self._global_limit = max(1, int(global_limit or 1))

    def evaluate(self, *, job_run: OrchestrationJobRun) -> DispatchDecision:
        global_running = OrchestrationJobRun.objects.filter(status="running").count()
        if global_running >= self._global_limit:
            return DispatchDecision(job_run_id=str(job_run.id), allowed=False, reason="global_limit")

        pipeline_running = OrchestrationJobRun.objects.filter(pipeline=job_run.pipeline, status="running").count()
        if pipeline_running >= max(1, int(job_run.pipeline.max_concurrency or 1)):
            return DispatchDecision(job_run_id=str(job_run.id), allowed=False, reason="pipeline_limit")

        job_running = OrchestrationJobRun.objects.filter(job_definition=job_run.job_definition, status="running").count()
        if job_running >= max(1, int(job_run.job_definition.concurrency_limit or 1)):
            return DispatchDecision(job_run_id=str(job_run.id), allowed=False, reason="job_limit")

        metadata = job_run.job_definition.metadata_json if isinstance(job_run.job_definition.metadata_json, dict) else {}
        policy = metadata.get("job_concurrency_policy") if isinstance(metadata.get("job_concurrency_policy"), dict) else {}
        try:
            per_partition_limit = max(1, int(policy.get("per_partition_limit") or 1))
        except (TypeError, ValueError):
            per_partition_limit = 1

        if job_run.job_definition.runs_per_jurisdiction and str(job_run.scope_jurisdiction or "").strip():
            per_jurisdiction_running = OrchestrationJobRun.objects.filter(
                job_definition=job_run.job_definition,
                status="running",
                scope_jurisdiction=job_run.scope_jurisdiction,
            ).count()
            if per_jurisdiction_running >= per_partition_limit:
                return DispatchDecision(job_run_id=str(job_run.id), allowed=False, reason="partition_jurisdiction_limit")

        if job_run.job_definition.runs_per_source and str(job_run.scope_source or "").strip():
            per_source_running = OrchestrationJobRun.objects.filter(
                job_definition=job_run.job_definition,
                status="running",
                scope_source=job_run.scope_source,
            ).count()
            if per_source_running >= per_partition_limit:
                return DispatchDecision(job_run_id=str(job_run.id), allowed=False, reason="partition_source_limit")

        return DispatchDecision(job_run_id=str(job_run.id), allowed=True, reason="allowed")


class RunDispatcher:
    def __init__(
        self,
        *,
        executors: dict[str, JobExecutor],
        lifecycle: OrchestrationLifecycleService | None = None,
        repository: DjangoOrchestrationRepository | None = None,
        concurrency_guard: ConcurrencyGuard | None = None,
    ):
        self._repository = repository or DjangoOrchestrationRepository()
        self._lifecycle = lifecycle or OrchestrationLifecycleService(repository=self._repository)
        self._executors = executors
        self._concurrency_guard = concurrency_guard or ConcurrencyGuard()

    def _to_output_records(self, *, payload: dict[str, Any] | None, default_change_token: str = "") -> list[OutputRecord]:
        body = payload if isinstance(payload, dict) else {}
        outputs = body.get("outputs") if isinstance(body.get("outputs"), list) else []
        records: list[OutputRecord] = []
        for item in outputs:
            if not isinstance(item, dict):
                continue
            output_key = str(item.get("output_key") or item.get("key") or "").strip() or "default"
            records.append(
                OutputRecord(
                    output_key=output_key,
                    output_type=str(item.get("output_type") or item.get("type") or "generic").strip() or "generic",
                    output_uri=str(item.get("output_uri") or item.get("uri") or "").strip(),
                    output_change_token=str(item.get("output_change_token") or default_change_token or "").strip(),
                    artifact_id=str(item.get("artifact_id") or "").strip(),
                    metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                    payload=item.get("payload") if isinstance(item.get("payload"), dict) else {},
                )
            )
        if records:
            return records
        if body:
            return [OutputRecord(output_key="default", output_type="generic", output_change_token=default_change_token, payload=body)]
        return []

    @transaction.atomic
    def _claim_dispatchable_job(self, *, job_run_id: str, now: datetime) -> tuple[OrchestrationJobRun, JobExecutor] | None:
        row = (
            OrchestrationJobRun.objects.select_for_update(skip_locked=True)
            .select_related("job_definition", "run", "pipeline")
            .filter(id=job_run_id)
            .filter(Q(status="queued") | Q(status="waiting_retry", next_attempt_at__lte=now))
            .first()
        )
        if row is None:
            return None

        decision = self._concurrency_guard.evaluate(job_run=row)
        if not decision.allowed:
            return None

        executor = self._executors.get(str(row.job_definition.handler_key))
        if executor is None:
            self._lifecycle.mark_job_failed(
                job_run_id=str(row.id),
                now=now,
                summary="No executor registered",
                error_text=f"Missing executor for handler_key={row.job_definition.handler_key}",
                retryable=False,
            )
            return None

        self._lifecycle.mark_job_running(job_run_id=str(row.id), now=now, summary="dispatching")
        row.refresh_from_db()
        return row, executor

    def dispatch_once(self, *, now: datetime | None = None, limit: int = 20) -> list[str]:
        ts = now or datetime.now(timezone.utc)
        candidate_rows = list(
            OrchestrationJobRun.objects.select_related("job_definition", "run", "pipeline")
            .filter(Q(status="queued") | Q(status="waiting_retry", next_attempt_at__lte=ts))
            .order_by("next_attempt_at", "queued_at", "created_at")[: max(1, int(limit or 1))]
        )
        blocked_reasons: dict[str, int] = defaultdict(int)
        dispatched: list[str] = []
        for candidate in candidate_rows:
            claimed = self._claim_dispatchable_job(job_run_id=str(candidate.id), now=ts)
            if claimed is None:
                decision = self._concurrency_guard.evaluate(job_run=candidate)
                if not decision.allowed:
                    blocked_reasons[decision.reason] += 1
                else:
                    blocked_reasons["skipped_locked_or_missing_executor"] += 1
                continue
            row, executor = claimed
            context = JobExecutionContext(
                workspace_id=str(row.workspace_id),
                run_id=str(row.run_id),
                job_run_id=str(row.id),
                pipeline_key=str(row.pipeline.key),
                job_key=str(row.job_definition.job_key),
                attempt_count=max(1, int(row.attempt_count or 0)),
                scope=ExecutionScope(
                    jurisdiction=str(row.scope_jurisdiction or ""),
                    source=str(row.scope_source or ""),
                ),
                metadata={
                    "correlation_id": str(row.correlation_id or ""),
                    "chain_id": str(row.chain_id or ""),
                    "run_metadata": row.run.metadata_json if isinstance(row.run.metadata_json, dict) else {},
                },
            )

            try:
                result = executor.execute(context)
            except Exception as exc:  # pragma: no cover - defensive execution wrapper
                logger.exception(
                    "orchestration.dispatch.executor_exception",
                    extra={
                        "job_run_id": str(row.id),
                        "job_key": str(row.job_definition.job_key),
                        "pipeline_key": str(row.pipeline.key),
                        "attempt_count": int(row.attempt_count or 0),
                    },
                )
                result = JobExecutionResult(
                    status="failed",
                    summary="Executor raised exception",
                    error_text=f"{exc.__class__.__name__}: {exc}",
                    retryable=True,
                )

            if str(result.status or "").lower() in {"succeeded", "success", "completed"}:
                self._lifecycle.mark_job_succeeded(
                    job_run_id=str(row.id),
                    now=ts,
                    summary=result.summary,
                    metrics=result.output_payload.get("metrics") if isinstance(result.output_payload, dict) else {},
                    outputs=self._to_output_records(payload=result.output_payload, default_change_token=result.output_change_token),
                    output_change_token=result.output_change_token,
                )
            elif str(result.status or "").lower() == "skipped":
                self._lifecycle.mark_job_skipped(
                    job_run_id=str(row.id),
                    now=ts,
                    reason="executor_skipped",
                    summary=result.summary or "Skipped by executor",
                )
            else:
                self._lifecycle.mark_job_failed(
                    job_run_id=str(row.id),
                    now=ts,
                    summary=result.summary or "Job failed",
                    error_text=result.error_text,
                    error_details=result.output_payload if isinstance(result.output_payload, dict) else {},
                    retryable=bool(result.retryable),
                )
            dispatched.append(str(row.id))
        if blocked_reasons:
            logger.info("orchestration.dispatch.blocked_summary", extra={"blocked_reasons": dict(blocked_reasons)})
        return dispatched


class StaleRunDetector:
    def __init__(self, *, lifecycle: OrchestrationLifecycleService | None = None, default_timeout_seconds: int = 3600):
        self._lifecycle = lifecycle or OrchestrationLifecycleService()
        self._default_timeout_seconds = max(60, int(default_timeout_seconds or 60))

    def detect_and_mark_stale(self, *, now: datetime | None = None, limit: int = 200) -> list[str]:
        ts = now or datetime.now(timezone.utc)
        candidates = list(
            OrchestrationJobRun.objects.select_related("run", "pipeline")
            .filter(status__in=["queued", "running"])
            .order_by("created_at")[: max(1, int(limit or 1))]
        )
        marked: list[str] = []
        for row in candidates:
            timeout_seconds = int(row.pipeline.stale_run_timeout_seconds or self._default_timeout_seconds)
            anchor = row.heartbeat_at or row.started_at or row.queued_at or row.created_at
            computed_deadline = anchor + timedelta(seconds=max(60, timeout_seconds))
            deadline = row.stale_deadline_at or computed_deadline
            if computed_deadline > deadline:
                deadline = computed_deadline
                row.stale_deadline_at = deadline
                row.save(update_fields=["stale_deadline_at", "updated_at"])
            if deadline > ts:
                continue
            fresh_row = OrchestrationJobRun.objects.select_related("pipeline").filter(id=row.id).first()
            if fresh_row is None or fresh_row.status not in {"queued", "running"}:
                continue
            fresh_anchor = fresh_row.heartbeat_at or fresh_row.started_at or fresh_row.queued_at or fresh_row.created_at
            fresh_timeout_seconds = int(fresh_row.pipeline.stale_run_timeout_seconds or self._default_timeout_seconds)
            fresh_deadline = (fresh_row.stale_deadline_at or (fresh_anchor + timedelta(seconds=max(60, fresh_timeout_seconds))))
            if fresh_anchor + timedelta(seconds=max(60, fresh_timeout_seconds)) > fresh_deadline:
                fresh_deadline = fresh_anchor + timedelta(seconds=max(60, fresh_timeout_seconds))
                fresh_row.stale_deadline_at = fresh_deadline
                fresh_row.save(update_fields=["stale_deadline_at", "updated_at"])
            if fresh_deadline <= ts:
                self._lifecycle.mark_job_stale(job_run_id=str(fresh_row.id), now=ts, reason="stale_timeout")
                marked.append(str(fresh_row.id))
        return marked


class OrchestrationEngine:
    def __init__(
        self,
        *,
        executors: dict[str, JobExecutor],
        scanner: DueJobScanner | None = None,
        planner: RunPlanner | None = None,
        resolver: DependencyResolver | None = None,
        dispatcher: RunDispatcher | None = None,
        stale_detector: StaleRunDetector | None = None,
        lifecycle: OrchestrationLifecycleService | None = None,
    ):
        self._lifecycle = lifecycle or OrchestrationLifecycleService()
        self._scanner = scanner or DueJobScanner()
        self._planner = planner or RunPlanner(lifecycle=self._lifecycle)
        self._resolver = resolver or DependencyResolver(lifecycle=self._lifecycle)
        self._dispatcher = dispatcher or RunDispatcher(executors=executors, lifecycle=self._lifecycle)
        self._stale_detector = stale_detector or StaleRunDetector(lifecycle=self._lifecycle)

    def tick(self, *, now: datetime | None = None, schedule_limit: int = 100, dispatch_limit: int = 100) -> dict[str, Any]:
        ts = now or datetime.now(timezone.utc)
        due_items = self._scanner.scan_due_schedules(now=ts, limit=schedule_limit)

        created_runs: list[str] = []
        for due in due_items:
            runs = self._planner.create_runs_for_due_schedule(due=due, now=ts)
            created_runs.extend([str(run.id) for run in runs])

        active_runs = list(
            OrchestrationRun.objects.filter(status__in=["pending", "queued", "running"]).order_by("created_at")
        )
        queued_jobs: list[str] = []
        for run in active_runs:
            queued_jobs.extend(self._resolver.queue_ready_jobs(run=run, now=ts))

        dispatched_jobs = self._dispatcher.dispatch_once(now=ts, limit=dispatch_limit)
        stale_jobs = self._stale_detector.detect_and_mark_stale(now=ts)

        summary = {
            "due_schedules": len(due_items),
            "created_runs": len(created_runs),
            "queued_jobs": len(queued_jobs),
            "dispatched_jobs": len(dispatched_jobs),
            "stale_jobs": len(stale_jobs),
            "created_run_ids": created_runs,
            "queued_job_run_ids": queued_jobs,
            "dispatched_job_run_ids": dispatched_jobs,
            "stale_job_run_ids": stale_jobs,
        }
        logger.info("orchestration.engine.tick", extra=summary)
        return summary

    def request_manual_rerun(self, *, run_id: str, requested_by_id: str = "") -> OrchestrationRun:
        return self._lifecycle.request_rerun(run_id=run_id, requested_by_id=requested_by_id)
