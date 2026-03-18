from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol

from .definitions import PipelineDefinition

if TYPE_CHECKING:
    from xyn_orchestrator.models import OrchestrationJobRun, OrchestrationRun

TriggerCause = Literal["scheduled", "upstream_change", "manual", "retry", "backfill", "system"]


@dataclass(frozen=True)
class ExecutionScope:
    jurisdiction: str = ""
    source: str = ""


@dataclass(frozen=True)
class RunTrigger:
    trigger_cause: TriggerCause
    trigger_key: str = ""


@dataclass(frozen=True)
class RunCreateRequest:
    workspace_id: str
    pipeline_key: str
    trigger: RunTrigger
    initiated_by_id: str = ""
    rerun_of_run_id: str = ""
    scope: ExecutionScope = field(default_factory=ExecutionScope)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class JobExecutionContext:
    workspace_id: str
    run_id: str
    job_run_id: str
    pipeline_key: str
    job_key: str
    attempt_count: int
    scope: ExecutionScope = field(default_factory=ExecutionScope)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class JobExecutionResult:
    status: str
    summary: str = ""
    output_payload: dict[str, Any] = field(default_factory=dict)
    output_artifact_id: str = ""
    output_change_token: str = ""
    retryable: bool = False
    error_text: str = ""


@dataclass(frozen=True)
class StaleRunRecord:
    job_run_id: str
    run_id: str
    workspace_id: str
    pipeline_key: str
    job_key: str


class OrchestrationRepository(Protocol):
    def get_pipeline_definition(self, *, workspace_id: str, pipeline_key: str) -> PipelineDefinition | None: ...

    def create_run(self, request: RunCreateRequest) -> "OrchestrationRun": ...

    def list_dispatchable_job_runs(self, *, now: datetime, limit: int = 50) -> list[dict[str, Any]]: ...

    def mark_job_running(self, *, job_run_id: str, started_at: datetime) -> None: ...

    def mark_job_completed(self, *, job_run_id: str, result: JobExecutionResult, completed_at: datetime) -> None: ...

    def mark_job_failed(self, *, job_run_id: str, result: JobExecutionResult, completed_at: datetime) -> None: ...

    def mark_job_stale(self, *, job_run_id: str, stale_at: datetime, reason: str) -> None: ...

    def list_stale_running_jobs(self, *, now: datetime, limit: int = 200) -> list[StaleRunRecord]: ...

    def touch_job_heartbeat(self, *, job_run_id: str, heartbeat_at: datetime) -> None: ...

    def mark_run_terminal_if_finished(self, *, run_id: str, completed_at: datetime) -> None: ...

    def create_manual_rerun(self, *, run_id: str, requested_by_id: str = "") -> "OrchestrationRun": ...

    def get_job_run_for_update(self, *, job_run_id: str) -> "OrchestrationJobRun": ...

    def save_job_run(self, *, job_run: "OrchestrationJobRun", update_fields: list[str]) -> None: ...


class JobExecutor(Protocol):
    def execute(self, context: JobExecutionContext) -> JobExecutionResult: ...


class FailureNotifier(Protocol):
    def notify_run_failure(
        self,
        *,
        workspace_id: str,
        run_id: str,
        pipeline_key: str,
        job_key: str,
        error_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...
