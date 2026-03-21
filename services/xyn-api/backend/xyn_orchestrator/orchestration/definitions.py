from __future__ import annotations

from dataclasses import dataclass, field

from .scheduling import ScheduledTrigger

STAGE_SOURCE_REFRESH = "source_refresh"
STAGE_SOURCE_NORMALIZATION = "source_normalization"
STAGE_PROPERTY_GRAPH_REBUILD = "property_graph_rebuild"
STAGE_SIGNAL_MATCHING = "signal_matching"
STAGE_RULE_EVALUATION = "rule_evaluation"
STAGE_NOTIFICATION_EMISSION = "notification_emission"


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    initial_backoff_seconds: int = 30
    max_backoff_seconds: int = 1800
    multiplier: float = 2.0


@dataclass(frozen=True)
class JobOutputSpec:
    produces_artifact: bool = False
    artifact_kind: str = ""


@dataclass(frozen=True)
class JobDefinition:
    key: str
    stage_key: str
    name: str
    handler_key: str
    dependencies: tuple[str, ...] = ()
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    concurrency_limit: int = 1
    only_if_upstream_changed: bool = False
    runs_per_jurisdiction: bool = False
    runs_per_source: bool = False
    output_spec: JobOutputSpec = field(default_factory=JobOutputSpec)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PipelineDefinition:
    key: str
    name: str
    jobs: tuple[JobDefinition, ...]
    triggers: tuple[ScheduledTrigger, ...] = ()
    max_concurrency: int = 1
    stale_run_timeout_seconds: int = 3600
    metadata: dict[str, object] = field(default_factory=dict)
