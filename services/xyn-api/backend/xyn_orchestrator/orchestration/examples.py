from __future__ import annotations

from .definitions import (
    RetryPolicy,
    STAGE_NOTIFICATION_EMISSION,
    STAGE_PROPERTY_GRAPH_REBUILD,
    STAGE_RULE_EVALUATION,
    STAGE_SOURCE_NORMALIZATION,
    STAGE_SOURCE_REFRESH,
)
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
    composer.add_job(evaluate_rules, depends_on=("rebuild_entities",))
    composer.add_job(emit_notifications, depends_on=("evaluate_rules",))
    return composer.compose()


def register_sample_data_pipeline(registry: OrchestrationRegistry) -> None:
    pipeline = build_sample_data_pipeline()
    registry.register_pipeline(pipeline)
