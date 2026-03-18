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
from .scheduling import ScheduledTrigger, TriggerKind
from .service import JobOrchestrationService, exponential_backoff_seconds

try:
    from .lifecycle import OrchestrationLifecycleService, OutputRecord
    from .repository import DjangoOrchestrationRepository
except Exception:  # pragma: no cover - allows importing pure orchestration helpers without Django runtime
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
    "DependencySnapshot",
    "AppNotificationFailureNotifier",
    "DjangoOrchestrationRepository",
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
