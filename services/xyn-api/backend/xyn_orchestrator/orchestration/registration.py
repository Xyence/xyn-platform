from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from .definitions import JobDefinition, JobOutputSpec, PipelineDefinition, RetryPolicy
from .graph import JobDependencyGraph
from .interfaces import JobExecutor
from .scheduling import ScheduledTrigger


@dataclass(frozen=True)
class ArtifactDeclaration:
    key: str
    output_type: str = "generic"
    description: str = ""
    required: bool = False


@dataclass(frozen=True)
class PartitionStrategy:
    per_jurisdiction: bool = False
    per_source: bool = False


@dataclass(frozen=True)
class ConcurrencyPolicy:
    max_concurrency: int = 1
    per_partition_limit: int = 1


@dataclass(frozen=True)
class StalePolicy:
    timeout_seconds: int = 3600


@dataclass(frozen=True)
class ManualTriggerParameter:
    key: str
    description: str = ""
    required: bool = False
    default_value: str = ""


@dataclass(frozen=True)
class RegisteredJob:
    key: str
    stage_key: str
    display_name: str
    handler_key: str
    description: str = ""
    dependencies: tuple[str, ...] = ()
    schedules: tuple[ScheduledTrigger, ...] = ()
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    concurrency_policy: ConcurrencyPolicy = field(default_factory=ConcurrencyPolicy)
    stale_policy: StalePolicy = field(default_factory=StalePolicy)
    artifacts: tuple[ArtifactDeclaration, ...] = ()
    partition_strategy: PartitionStrategy = field(default_factory=PartitionStrategy)
    only_if_upstream_changed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_dependencies(self, *job_keys: str) -> "RegisteredJob":
        normalized = tuple(str(key or "").strip() for key in job_keys if str(key or "").strip())
        return replace(self, dependencies=normalized)

    def as_runtime_job(self) -> JobDefinition:
        metadata = dict(self.metadata)
        metadata["job_description"] = self.description
        metadata["job_schedules"] = [
            {
                "key": trigger.key,
                "kind": trigger.kind,
                "enabled": trigger.enabled,
                "cron_expression": trigger.cron_expression,
                "interval_seconds": trigger.interval_seconds,
                "timezone_name": trigger.timezone_name,
                "description": trigger.description,
            }
            for trigger in self.schedules
        ]
        metadata["job_artifacts"] = [
            {
                "key": artifact.key,
                "output_type": artifact.output_type,
                "description": artifact.description,
                "required": artifact.required,
            }
            for artifact in self.artifacts
        ]
        metadata["job_stale_timeout_seconds"] = int(self.stale_policy.timeout_seconds or 3600)
        metadata["job_partition_strategy"] = {
            "per_jurisdiction": bool(self.partition_strategy.per_jurisdiction),
            "per_source": bool(self.partition_strategy.per_source),
        }
        metadata["job_concurrency_policy"] = {
            "max_concurrency": int(self.concurrency_policy.max_concurrency or 1),
            "per_partition_limit": int(self.concurrency_policy.per_partition_limit or 1),
        }
        return JobDefinition(
            key=self.key,
            stage_key=self.stage_key,
            name=self.display_name,
            handler_key=self.handler_key,
            dependencies=self.dependencies,
            retry_policy=self.retry_policy,
            concurrency_limit=max(1, int(self.concurrency_policy.max_concurrency or 1)),
            only_if_upstream_changed=bool(self.only_if_upstream_changed),
            runs_per_jurisdiction=bool(self.partition_strategy.per_jurisdiction),
            runs_per_source=bool(self.partition_strategy.per_source),
            output_spec=JobOutputSpec(
                produces_artifact=bool(self.artifacts),
                artifact_kind=self.artifacts[0].output_type if self.artifacts else "",
            ),
            metadata=metadata,
        )


@dataclass(frozen=True)
class PipelineRegistration:
    key: str
    display_name: str
    description: str = ""
    jobs: tuple[RegisteredJob, ...] = ()
    manual_trigger_parameters: tuple[ManualTriggerParameter, ...] = ()
    max_concurrency: int = 1
    stale_run_timeout_seconds: int = 3600
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_runtime_pipeline(self) -> PipelineDefinition:
        pipeline_metadata = dict(self.metadata)
        pipeline_metadata["pipeline_description"] = self.description
        pipeline_metadata["manual_trigger_parameters"] = [
            {
                "key": param.key,
                "description": param.description,
                "required": param.required,
                "default_value": param.default_value,
            }
            for param in self.manual_trigger_parameters
        ]
        pipeline_metadata["registered_jobs"] = [job.key for job in self.jobs]
        return PipelineDefinition(
            key=self.key,
            name=self.display_name,
            jobs=tuple(job.as_runtime_job() for job in self.jobs),
            triggers=(),
            max_concurrency=max(1, int(self.max_concurrency or 1)),
            stale_run_timeout_seconds=max(60, int(self.stale_run_timeout_seconds or 60)),
            metadata=pipeline_metadata,
        )


def define_job(
    *,
    key: str,
    stage_key: str,
    display_name: str,
    handler_key: str,
    description: str = "",
    dependencies: tuple[str, ...] = (),
    schedules: tuple[ScheduledTrigger, ...] = (),
    retry_policy: RetryPolicy | None = None,
    concurrency_policy: ConcurrencyPolicy | None = None,
    stale_policy: StalePolicy | None = None,
    artifacts: tuple[ArtifactDeclaration, ...] = (),
    partition_strategy: PartitionStrategy | None = None,
    only_if_upstream_changed: bool = False,
    metadata: dict[str, Any] | None = None,
) -> RegisteredJob:
    return RegisteredJob(
        key=str(key or "").strip(),
        stage_key=str(stage_key or "").strip(),
        display_name=str(display_name or "").strip(),
        handler_key=str(handler_key or "").strip(),
        description=str(description or "").strip(),
        dependencies=tuple(str(value or "").strip() for value in dependencies if str(value or "").strip()),
        schedules=schedules,
        retry_policy=retry_policy or RetryPolicy(),
        concurrency_policy=concurrency_policy or ConcurrencyPolicy(),
        stale_policy=stale_policy or StalePolicy(),
        artifacts=artifacts,
        partition_strategy=partition_strategy or PartitionStrategy(),
        only_if_upstream_changed=bool(only_if_upstream_changed),
        metadata=metadata if isinstance(metadata, dict) else {},
    )


class PipelineComposer:
    def __init__(
        self,
        *,
        key: str,
        display_name: str,
        description: str = "",
        max_concurrency: int = 1,
        stale_run_timeout_seconds: int = 3600,
        metadata: dict[str, Any] | None = None,
    ):
        self._key = str(key or "").strip()
        self._display_name = str(display_name or "").strip()
        self._description = str(description or "").strip()
        self._max_concurrency = max(1, int(max_concurrency or 1))
        self._stale_run_timeout_seconds = max(60, int(stale_run_timeout_seconds or 60))
        self._metadata = metadata if isinstance(metadata, dict) else {}
        self._jobs: dict[str, RegisteredJob] = {}
        self._manual_trigger_parameters: dict[str, ManualTriggerParameter] = {}

    def add_manual_parameter(
        self,
        *,
        key: str,
        description: str = "",
        required: bool = False,
        default_value: str = "",
    ) -> "PipelineComposer":
        param = ManualTriggerParameter(
            key=str(key or "").strip(),
            description=str(description or "").strip(),
            required=bool(required),
            default_value=str(default_value or "").strip(),
        )
        self._manual_trigger_parameters[param.key] = param
        return self

    def add_job(self, job: RegisteredJob, *, depends_on: tuple[str, ...] = ()) -> "PipelineComposer":
        merged_dependencies = tuple(dict.fromkeys(tuple(job.dependencies) + tuple(depends_on)))
        self._jobs[job.key] = replace(job, dependencies=merged_dependencies)
        return self

    def compose(self) -> PipelineRegistration:
        return PipelineRegistration(
            key=self._key,
            display_name=self._display_name,
            description=self._description,
            jobs=tuple(self._jobs.values()),
            manual_trigger_parameters=tuple(self._manual_trigger_parameters.values()),
            max_concurrency=self._max_concurrency,
            stale_run_timeout_seconds=self._stale_run_timeout_seconds,
            metadata=dict(self._metadata),
        )


def compose_pipeline(
    *,
    key: str,
    display_name: str,
    description: str = "",
    max_concurrency: int = 1,
    stale_run_timeout_seconds: int = 3600,
    metadata: dict[str, Any] | None = None,
) -> PipelineComposer:
    return PipelineComposer(
        key=key,
        display_name=display_name,
        description=description,
        max_concurrency=max_concurrency,
        stale_run_timeout_seconds=stale_run_timeout_seconds,
        metadata=metadata,
    )


def validate_pipeline_registration(
    *,
    pipeline: PipelineRegistration,
    handler_keys: set[str] | None = None,
) -> None:
    if not str(pipeline.key or "").strip():
        raise ValueError("pipeline key is required")
    if not str(pipeline.display_name or "").strip():
        raise ValueError("pipeline display_name is required")
    if int(pipeline.max_concurrency or 0) <= 0:
        raise ValueError("pipeline max_concurrency must be > 0")
    if int(pipeline.stale_run_timeout_seconds or 0) <= 0:
        raise ValueError("pipeline stale_run_timeout_seconds must be > 0")

    manual_params_seen: set[str] = set()
    for param in pipeline.manual_trigger_parameters:
        key = str(param.key or "").strip()
        if not key:
            raise ValueError("manual trigger parameter key is required")
        if key in manual_params_seen:
            raise ValueError(f"duplicate manual trigger parameter key: {key}")
        manual_params_seen.add(key)

    job_keys_seen: set[str] = set()
    for job in pipeline.jobs:
        if not str(job.key or "").strip():
            raise ValueError("job key is required")
        if job.key in job_keys_seen:
            raise ValueError(f"duplicate job key: {job.key}")
        job_keys_seen.add(job.key)
        if not str(job.display_name or "").strip():
            raise ValueError(f"job {job.key} display_name is required")
        if not str(job.stage_key or "").strip():
            raise ValueError(f"job {job.key} stage_key is required")
        if not str(job.handler_key or "").strip():
            raise ValueError(f"job {job.key} handler_key is required")
        if int(job.retry_policy.max_attempts or 0) <= 0:
            raise ValueError(f"job {job.key} retry max_attempts must be > 0")
        if int(job.retry_policy.initial_backoff_seconds or 0) <= 0:
            raise ValueError(f"job {job.key} retry initial_backoff_seconds must be > 0")
        if int(job.retry_policy.max_backoff_seconds or 0) <= 0:
            raise ValueError(f"job {job.key} retry max_backoff_seconds must be > 0")
        if float(job.retry_policy.multiplier or 0.0) < 1.0:
            raise ValueError(f"job {job.key} retry multiplier must be >= 1.0")
        if int(job.concurrency_policy.max_concurrency or 0) <= 0:
            raise ValueError(f"job {job.key} concurrency max_concurrency must be > 0")
        if int(job.concurrency_policy.per_partition_limit or 0) <= 0:
            raise ValueError(f"job {job.key} concurrency per_partition_limit must be > 0")
        if int(job.stale_policy.timeout_seconds or 0) <= 0:
            raise ValueError(f"job {job.key} stale timeout_seconds must be > 0")

        schedule_keys_seen: set[str] = set()
        for schedule in job.schedules:
            schedule.validate()
            schedule_key = str(schedule.key or "").strip()
            if schedule_key in schedule_keys_seen:
                raise ValueError(f"job {job.key} has duplicate schedule key: {schedule_key}")
            schedule_keys_seen.add(schedule_key)

        artifact_keys_seen: set[str] = set()
        for artifact in job.artifacts:
            artifact_key = str(artifact.key or "").strip()
            if not artifact_key:
                raise ValueError(f"job {job.key} has artifact with empty key")
            if artifact_key in artifact_keys_seen:
                raise ValueError(f"job {job.key} has duplicate artifact key: {artifact_key}")
            artifact_keys_seen.add(artifact_key)

    graph = JobDependencyGraph(tuple(job.as_runtime_job() for job in pipeline.jobs))
    graph.topological_order()

    if handler_keys is not None:
        for job in pipeline.jobs:
            if job.handler_key not in handler_keys:
                raise ValueError(f"job {job.key} references unknown handler: {job.handler_key}")


class OrchestrationRegistry:
    def __init__(self):
        self._handlers: dict[str, JobExecutor] = {}
        self._pipelines: dict[str, PipelineRegistration] = {}

    def register_handler(self, *, handler_key: str, executor: JobExecutor) -> None:
        key = str(handler_key or "").strip()
        if not key:
            raise ValueError("handler_key is required")
        self._handlers[key] = executor

    def register_pipeline(self, pipeline: PipelineRegistration, *, validate: bool = True) -> None:
        if validate:
            validate_pipeline_registration(pipeline=pipeline, handler_keys=set(self._handlers.keys()))
        self._pipelines[pipeline.key] = pipeline

    def get_pipeline(self, *, pipeline_key: str) -> PipelineRegistration | None:
        return self._pipelines.get(str(pipeline_key or "").strip())

    def list_pipelines(self) -> tuple[PipelineRegistration, ...]:
        return tuple(sorted(self._pipelines.values(), key=lambda pipeline: pipeline.key))

    def resolve_executor(self, *, handler_key: str) -> JobExecutor | None:
        return self._handlers.get(str(handler_key or "").strip())

    def handler_keys(self) -> set[str]:
        return set(self._handlers.keys())
