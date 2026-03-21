from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .definitions import (
    RetryPolicy,
    STAGE_NOTIFICATION_EMISSION,
    STAGE_PROPERTY_GRAPH_REBUILD,
    STAGE_RULE_EVALUATION,
    STAGE_SIGNAL_MATCHING,
    STAGE_SOURCE_NORMALIZATION,
    STAGE_SOURCE_REFRESH,
)
from .interfaces import JobExecutionContext, JobExecutionResult
from .registration import (
    ArtifactDeclaration,
    ConcurrencyPolicy,
    OrchestrationRegistry,
    PartitionStrategy,
    PipelineRegistration,
    StalePolicy,
    compose_pipeline,
    define_job,
)
from .scheduling import ScheduledTrigger


def _stage_output_payload(
    *,
    output_key: str,
    output_type: str,
    context: JobExecutionContext,
    records: int,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "metrics": {
            "records": int(records),
            "attempt_count": int(context.attempt_count),
            "jurisdiction": str(context.scope.jurisdiction or ""),
            "source": str(context.scope.source or ""),
        },
        "outputs": [
            {
                "output_key": output_key,
                "output_type": output_type,
                "output_uri": f"xyn://runs/{context.run_id}/{output_key}",
                "output_change_token": f"{output_key}:{context.run_id}:{context.attempt_count}",
                "payload": {
                    "records": int(records),
                    "job_key": context.job_key,
                    "pipeline_key": context.pipeline_key,
                },
            }
        ],
    }
    if isinstance(extra, dict):
        payload.update(extra)
    return payload


@dataclass
class _DemoPipelineExecutor:
    job_key: str
    output_key: str
    output_type: str
    records: int
    retry_once_flag: str = ""

    def execute(self, context: JobExecutionContext) -> JobExecutionResult:
        run_metadata = context.metadata.get("run_metadata") if isinstance(context.metadata.get("run_metadata"), dict) else {}
        manual_params = run_metadata.get("manual_parameters") if isinstance(run_metadata.get("manual_parameters"), dict) else {}
        retry_once = str(manual_params.get(self.retry_once_flag) or "").strip().lower() in {"1", "true", "yes"} if self.retry_once_flag else False
        if retry_once and int(context.attempt_count or 1) == 1:
            return JobExecutionResult(
                status="failed",
                summary=f"{self.job_key} transient failure",
                error_text=f"{self.job_key} requested one retry for demo",
                retryable=True,
            )
        payload = _stage_output_payload(
            output_key=self.output_key,
            output_type=self.output_type,
            context=context,
            records=self.records,
        )
        return JobExecutionResult(
            status="succeeded",
            summary=f"{self.job_key} completed",
            output_payload=payload,
            output_change_token=f"{self.output_key}:{context.run_id}:{context.attempt_count}",
            retryable=False,
        )


def build_sample_data_pipeline() -> PipelineRegistration:
    composer = compose_pipeline(
        key="sample_data_sync",
        display_name="Sample Data Sync Pipeline",
        description="Generic source refresh and processing pipeline for platform consumers.",
        max_concurrency=4,
        stale_run_timeout_seconds=3600,
    )
    composer.add_manual_parameter(
        key="force_refresh",
        description="When true, bypasses source-side cache checks.",
        required=False,
        default_value="false",
    )
    composer.add_manual_parameter(
        key="target_jurisdiction",
        description="Optional jurisdiction override for manual runs.",
        required=False,
        default_value="",
    )
    composer.add_manual_parameter(
        key="target_source",
        description="Optional source override for manual runs.",
        required=False,
        default_value="",
    )
    composer.add_manual_parameter(
        key="simulate_retry_once",
        description="If true, normalize stage fails once to demonstrate retry/backoff.",
        required=False,
        default_value="false",
    )

    refresh_source = define_job(
        key="refresh_source",
        stage_key=STAGE_SOURCE_REFRESH,
        display_name="Refresh Source",
        description="Refreshes upstream raw datasets from external sources.",
        handler_key="platform.jobs.refresh_source",
        schedules=(
            ScheduledTrigger(
                key="hourly_refresh",
                kind="interval",
                interval_seconds=3600,
                description="Run source refresh every hour.",
            ),
        ),
        retry_policy=RetryPolicy(max_attempts=4, initial_backoff_seconds=30, max_backoff_seconds=900, multiplier=2.0),
        concurrency_policy=ConcurrencyPolicy(max_concurrency=2, per_partition_limit=1),
        stale_policy=StalePolicy(timeout_seconds=1800),
        artifacts=(
            ArtifactDeclaration(
                key="raw_snapshot",
                output_type="dataset_snapshot",
                description="Raw snapshot created during refresh.",
                required=True,
            ),
        ),
        partition_strategy=PartitionStrategy(per_jurisdiction=True, per_source=True),
    )
    normalize_source = define_job(
        key="normalize_source",
        stage_key=STAGE_SOURCE_NORMALIZATION,
        display_name="Normalize Source",
        description="Normalizes refreshed source payloads into stable records.",
        handler_key="platform.jobs.normalize_source",
        retry_policy=RetryPolicy(max_attempts=3, initial_backoff_seconds=20, max_backoff_seconds=600, multiplier=2.0),
        concurrency_policy=ConcurrencyPolicy(max_concurrency=2, per_partition_limit=1),
        stale_policy=StalePolicy(timeout_seconds=1800),
        artifacts=(
            ArtifactDeclaration(
                key="normalized_records",
                output_type="normalized_records",
                description="Normalized source records.",
                required=True,
            ),
        ),
        partition_strategy=PartitionStrategy(per_jurisdiction=True, per_source=True),
        only_if_upstream_changed=True,
    )
    rebuild_entities = define_job(
        key="rebuild_entities",
        stage_key=STAGE_PROPERTY_GRAPH_REBUILD,
        display_name="Rebuild Entities",
        description="Rebuilds platform entity graph from normalized records.",
        handler_key="platform.jobs.rebuild_entities",
        retry_policy=RetryPolicy(max_attempts=2, initial_backoff_seconds=15, max_backoff_seconds=300, multiplier=2.0),
        concurrency_policy=ConcurrencyPolicy(max_concurrency=1, per_partition_limit=1),
        stale_policy=StalePolicy(timeout_seconds=2400),
        artifacts=(
            ArtifactDeclaration(
                key="entity_graph_delta",
                output_type="graph_delta",
                description="Graph update payload.",
                required=False,
            ),
        ),
        partition_strategy=PartitionStrategy(per_jurisdiction=True, per_source=True),
        only_if_upstream_changed=True,
    )
    match_signals = define_job(
        key="match_signals",
        stage_key=STAGE_SIGNAL_MATCHING,
        display_name="Match Signals",
        description="Matches generated entities against platform signal sets.",
        handler_key="platform.jobs.match_signals",
        retry_policy=RetryPolicy(max_attempts=2, initial_backoff_seconds=10, max_backoff_seconds=240, multiplier=2.0),
        concurrency_policy=ConcurrencyPolicy(max_concurrency=2, per_partition_limit=1),
        stale_policy=StalePolicy(timeout_seconds=1500),
        artifacts=(
            ArtifactDeclaration(
                key="signal_matches",
                output_type="signal_matches",
                description="Matched signal events.",
                required=False,
            ),
        ),
        partition_strategy=PartitionStrategy(per_jurisdiction=True, per_source=True),
        only_if_upstream_changed=True,
    )
    # Rules here represent business policy evaluation, not app invariants or orchestration behavior.
    evaluate_rules = define_job(
        key="evaluate_rules",
        stage_key=STAGE_RULE_EVALUATION,
        display_name="Evaluate Rules",
        description="Evaluates platform rules against updated entities.",
        handler_key="platform.jobs.evaluate_rules",
        retry_policy=RetryPolicy(max_attempts=2, initial_backoff_seconds=10, max_backoff_seconds=180, multiplier=2.0),
        concurrency_policy=ConcurrencyPolicy(max_concurrency=2, per_partition_limit=1),
        stale_policy=StalePolicy(timeout_seconds=1200),
        artifacts=(
            ArtifactDeclaration(
                key="rule_evaluation_summary",
                output_type="rule_summary",
                description="Rule evaluation summary output.",
                required=False,
            ),
        ),
        partition_strategy=PartitionStrategy(per_jurisdiction=True, per_source=True),
        only_if_upstream_changed=True,
    )
    emit_notifications = define_job(
        key="emit_notifications",
        stage_key=STAGE_NOTIFICATION_EMISSION,
        display_name="Emit Notifications",
        description="Emits notifications for rule outcomes.",
        handler_key="platform.jobs.emit_notifications",
        retry_policy=RetryPolicy(max_attempts=2, initial_backoff_seconds=30, max_backoff_seconds=300, multiplier=2.0),
        concurrency_policy=ConcurrencyPolicy(max_concurrency=2, per_partition_limit=1),
        stale_policy=StalePolicy(timeout_seconds=900),
        artifacts=(
            ArtifactDeclaration(
                key="notification_receipts",
                output_type="notification_receipts",
                description="Notification delivery metadata.",
                required=False,
            ),
        ),
        partition_strategy=PartitionStrategy(per_jurisdiction=True, per_source=True),
        only_if_upstream_changed=True,
    )

    composer.add_job(refresh_source)
    composer.add_job(normalize_source, depends_on=("refresh_source",))
    composer.add_job(rebuild_entities, depends_on=("normalize_source",))
    composer.add_job(match_signals, depends_on=("rebuild_entities",))
    composer.add_job(evaluate_rules, depends_on=("match_signals",))
    composer.add_job(emit_notifications, depends_on=("evaluate_rules",))
    return composer.compose()


def build_sample_data_pipeline_demo_executors() -> dict[str, _DemoPipelineExecutor]:
    return {
        "platform.jobs.refresh_source": _DemoPipelineExecutor(
            job_key="refresh_source",
            output_key="raw_snapshot",
            output_type="dataset_snapshot",
            records=240,
        ),
        "platform.jobs.normalize_source": _DemoPipelineExecutor(
            job_key="normalize_source",
            output_key="normalized_records",
            output_type="normalized_records",
            records=180,
            retry_once_flag="simulate_retry_once",
        ),
        "platform.jobs.rebuild_entities": _DemoPipelineExecutor(
            job_key="rebuild_entities",
            output_key="entity_graph_delta",
            output_type="graph_delta",
            records=95,
        ),
        "platform.jobs.match_signals": _DemoPipelineExecutor(
            job_key="match_signals",
            output_key="signal_matches",
            output_type="signal_matches",
            records=41,
        ),
        "platform.jobs.evaluate_rules": _DemoPipelineExecutor(
            job_key="evaluate_rules",
            output_key="rule_evaluation_summary",
            output_type="rule_summary",
            records=27,
        ),
        "platform.jobs.emit_notifications": _DemoPipelineExecutor(
            job_key="emit_notifications",
            output_key="notification_receipts",
            output_type="notification_receipts",
            records=12,
        ),
    }


def register_sample_data_pipeline(registry: OrchestrationRegistry) -> None:
    pipeline = build_sample_data_pipeline()
    registry.register_pipeline(pipeline)


def register_sample_data_pipeline_with_demo_handlers(registry: OrchestrationRegistry) -> None:
    for handler_key, executor in build_sample_data_pipeline_demo_executors().items():
        registry.register_handler(handler_key=handler_key, executor=executor)
    register_sample_data_pipeline(registry)
