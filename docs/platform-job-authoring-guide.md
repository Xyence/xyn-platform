# Platform Job Authoring Guide

This guide covers the app-facing API for defining orchestrated jobs and composing pipelines without writing app-local orchestration glue.

## How to define a platform job

Use `define_job(...)` from `xyn_orchestrator.orchestration.registration`.

```python
from xyn_orchestrator.orchestration import (
    ArtifactDeclaration,
    ConcurrencyPolicy,
    PartitionStrategy,
    RetryPolicy,
    ScheduledTrigger,
    StalePolicy,
    define_job,
)

refresh = define_job(
    key="refresh_source",
    stage_key="source_refresh",
    display_name="Refresh Source",
    description="Refreshes upstream datasets.",
    handler_key="platform.jobs.refresh_source",
    schedules=(
        ScheduledTrigger(key="hourly", kind="interval", interval_seconds=3600),
    ),
    retry_policy=RetryPolicy(max_attempts=4, initial_backoff_seconds=30, max_backoff_seconds=900, multiplier=2.0),
    concurrency_policy=ConcurrencyPolicy(max_concurrency=2, per_partition_limit=1),
    stale_policy=StalePolicy(timeout_seconds=1800),
    artifacts=(
        ArtifactDeclaration(key="raw_snapshot", output_type="dataset_snapshot", required=True),
    ),
    partition_strategy=PartitionStrategy(per_jurisdiction=True, per_source=True),
)
```

v1 schedule support:
- `interval` and `manual` are supported.
- `cron` definitions are rejected until v2 cron semantics are implemented.
- Cron scheduling is intentionally unsupported in orchestration v1.
- Do not use or imply cron scheduling until platform cron support is explicitly implemented and accepted.

## How to define a dependency chain

Use `compose_pipeline(...)` and add jobs in sequence with `depends_on`.

```python
from xyn_orchestrator.orchestration import compose_pipeline, define_job

composer = compose_pipeline(key="sample_data_sync", display_name="Sample Data Sync")
composer.add_job(define_job(key="refresh_source", stage_key="source_refresh", display_name="Refresh", handler_key="h.refresh"))
composer.add_job(
    define_job(
        key="normalize_source",
        stage_key="source_normalization",
        display_name="Normalize",
        handler_key="h.normalize",
        only_if_upstream_changed=True,
    ),
    depends_on=("refresh_source",),
)
pipeline = composer.compose()
```

Validation catches:
- missing job keys / stage keys / handler keys
- duplicate job keys
- unknown dependencies
- cyclic dependencies
- invalid retry/concurrency/stale policies
- invalid schedule definitions
- missing handlers (when validated against a registry)

## How to manually trigger a run

Manual trigger parameters are declared on the pipeline:

```python
composer.add_manual_parameter(key="force_refresh", required=False, default_value="false")
composer.add_manual_parameter(key="target_source", required=False)
```

At runtime, callers pass these values through run metadata when creating manual runs using the existing run APIs (`RunCreateRequest`).
The orchestration primitive preserves these parameters in pipeline metadata for API/UI consumption.

## How partitioned jobs work

Partition behavior is declared per job with `PartitionStrategy`:

- `per_jurisdiction=True` means one run per jurisdiction partition.
- `per_source=True` means one run per source partition.
- both enabled means partition fanout by `(jurisdiction, source)` tuples.

During scheduled materialization, partition values come from schedule metadata:
- `jurisdictions`: list of jurisdiction keys
- `sources`: list of source keys

When partition lists are omitted, jobs execute unpartitioned for that dimension.

## Registry usage

Use `OrchestrationRegistry` to register handlers and pipelines:

```python
registry = OrchestrationRegistry()
registry.register_handler(handler_key="platform.jobs.refresh_source", executor=my_executor)
registry.register_pipeline(pipeline)  # validates handlers/dependencies/schedules
```

Use `build_sample_data_pipeline()` for a generic reference pipeline:
- `refresh_source`
- `normalize_source`
- `rebuild_entities`
- `match_signals`
- `evaluate_rules`
- `emit_notifications`

## Handler idempotency requirements

Handlers should be idempotent because retries and reruns are expected.

- Treat `(run_id, job_run_id, partition)` as the idempotency scope.
- Use deterministic output keys and external idempotency keys.
- Ensure retries do not duplicate external side effects.
