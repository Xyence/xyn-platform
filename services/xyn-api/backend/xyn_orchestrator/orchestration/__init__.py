from .definitions import (
    JobDefinition,
    JobOutputSpec,
    PipelineDefinition,
    RetryPolicy,
    STAGE_NOTIFICATION_EMISSION,
    STAGE_PROPERTY_GRAPH_REBUILD,
    STAGE_RULE_EVALUATION,
    STAGE_SIGNAL_MATCHING,
    STAGE_SOURCE_NORMALIZATION,
    STAGE_SOURCE_REFRESH,
)
from .graph import DependencySnapshot, JobDependencyGraph
from .interfaces import (
    ExecutionScope,
    FailureNotifier,
    JobExecutionContext,
    JobExecutionResult,
    JobExecutor,
    OrchestrationRepository,
    RunCreateRequest,
    RunTrigger,
    StaleRunRecord,
)
from .notifiers import AppNotificationFailureNotifier
from .registration import (
    ArtifactDeclaration,
    ConcurrencyPolicy,
    ManualTriggerParameter,
    OrchestrationRegistry,
    PartitionStrategy,
    PipelineComposer,
    PipelineRegistration,
    RegisteredJob,
    StalePolicy,
    compose_pipeline,
    define_job,
    validate_pipeline_registration,
)
from .examples import (
    build_sample_data_pipeline,
    build_sample_data_pipeline_demo_executors,
    register_sample_data_pipeline,
    register_sample_data_pipeline_with_demo_handlers,
)
from .scheduling import ScheduledTrigger, TriggerKind
from .schedule_policy import (
    CRON_UNSUPPORTED_MESSAGE,
    is_polled_schedule_kind,
    is_supported_schedule_kind,
    polled_schedule_kinds,
    supported_schedule_kinds,
    unsupported_schedule_kinds,
)
from .service import JobOrchestrationService, exponential_backoff_seconds

try:
    from .engine import ConcurrencyGuard, DependencyResolver, DueJobScanner, OrchestrationEngine, RunDispatcher, RunPlanner, StaleRunDetector
    from .lifecycle import OrchestrationLifecycleService, OutputRecord
    from .repository import DjangoOrchestrationRepository
except Exception:  # pragma: no cover - allows importing pure orchestration helpers without Django runtime
    ConcurrencyGuard = None  # type: ignore[assignment]
    DependencyResolver = None  # type: ignore[assignment]
    DueJobScanner = None  # type: ignore[assignment]
    OrchestrationEngine = None  # type: ignore[assignment]
    RunDispatcher = None  # type: ignore[assignment]
    RunPlanner = None  # type: ignore[assignment]
    StaleRunDetector = None  # type: ignore[assignment]
    OrchestrationLifecycleService = None  # type: ignore[assignment]
    OutputRecord = None  # type: ignore[assignment]
    DjangoOrchestrationRepository = None  # type: ignore[assignment]

__all__ = [
    "ExecutionScope",
    "FailureNotifier",
    "JobDefinition",
    "JobDependencyGraph",
    "JobExecutionContext",
    "JobExecutionResult",
    "JobExecutor",
    "JobOrchestrationService",
    "JobOutputSpec",
    "OrchestrationRepository",
    "PipelineDefinition",
    "RetryPolicy",
    "RunCreateRequest",
    "RunTrigger",
    "ScheduledTrigger",
    "StaleRunRecord",
    "TriggerKind",
    "CRON_UNSUPPORTED_MESSAGE",
    "supported_schedule_kinds",
    "unsupported_schedule_kinds",
    "polled_schedule_kinds",
    "is_supported_schedule_kind",
    "is_polled_schedule_kind",
    "DependencySnapshot",
    "AppNotificationFailureNotifier",
    "ArtifactDeclaration",
    "ConcurrencyPolicy",
    "DjangoOrchestrationRepository",
    "ManualTriggerParameter",
    "OrchestrationRegistry",
    "PartitionStrategy",
    "PipelineComposer",
    "PipelineRegistration",
    "RegisteredJob",
    "DueJobScanner",
    "RunPlanner",
    "DependencyResolver",
    "RunDispatcher",
    "ConcurrencyGuard",
    "StaleRunDetector",
    "OrchestrationEngine",
    "StalePolicy",
    "compose_pipeline",
    "define_job",
    "validate_pipeline_registration",
    "build_sample_data_pipeline",
    "build_sample_data_pipeline_demo_executors",
    "register_sample_data_pipeline",
    "register_sample_data_pipeline_with_demo_handlers",
    "exponential_backoff_seconds",
    "OrchestrationLifecycleService",
    "OutputRecord",
    "STAGE_SOURCE_REFRESH",
    "STAGE_SOURCE_NORMALIZATION",
    "STAGE_PROPERTY_GRAPH_REBUILD",
    "STAGE_SIGNAL_MATCHING",
    "STAGE_RULE_EVALUATION",
    "STAGE_NOTIFICATION_EMISSION",
]
