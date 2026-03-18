# Platform Job Orchestration Primitive (Scaffolding)

## Intent
This introduces a platform-level, workspace-scoped orchestration primitive for reusable scheduled pipelines.
It is intentionally lightweight and composable, and is not an Airflow replacement.

## Why this location
The primitive lives in `services/xyn-api/backend/xyn_orchestrator` because that package already owns:
- workspace-scoped durable platform models (`Campaign`, `Goal`, `Run`, notifications)
- orchestration-adjacent queue/recovery logic (`execution_queue.py`, `execution_recovery.py`, `xco.py`)
- API/worker integration points used by platform primitives

New module: `xyn_orchestrator/orchestration/`

## Module boundaries
- `definitions.py`
  - typed pipeline/job domain definitions
  - retry policy and output contracts
  - stage constants for common orchestration phases
- `scheduling.py`
  - trigger representation (`manual`, `interval`, `cron`, `event`)
- `graph.py`
  - dependency graph representation
  - topological ordering and ready-job resolution
  - `only_if_upstream_changed` gating support
- `interfaces.py`
  - repository interface, executor interface, notifier interface
  - run creation and execution context contracts
- `service.py`
  - service seam for run creation, stale detection, rerun entry point
  - exponential backoff utility
- `notifiers.py`
  - adapter to existing AppNotification infrastructure for failure notifications

## Persistence scaffolding
New ORM models in `models.py` and migrations `0125_orchestration_scaffolding.py` + `0126_orchestration_lifecycle_persistence.py`:
- `OrchestrationPipeline`
  - workspace-scoped pipeline definition
  - pipeline-level concurrency and stale timeout
- `OrchestrationJobDefinition`
  - job-level retry/backoff, concurrency, scope flags, output/artifact declaration
- `OrchestrationJobSchedule`
  - durable schedule rows per job definition (`manual`/`interval`/`cron`/`event`)
  - poll-friendly `enabled + next_fire_at` index
- `OrchestrationJobDependency`
  - explicit upstream/downstream edges
- `OrchestrationRun`
  - run trigger cause (`scheduled`/`upstream_change`/`manual`/`retry`/`backfill`/`system`)
  - scope partitions (`jurisdiction`, `source`)
  - correlation and chain ids
  - optional idempotency/dedupe keys
  - status, stale fields, summary, metrics, structured error details
- `OrchestrationJobRun`
  - per-job durable state with retry scheduling and stale fields
  - query dimensions for status, partition, correlation/chain, and time range
  - optional idempotency/dedupe keys
  - structured metrics and error details
- `OrchestrationJobRunAttempt`
  - explicit per-attempt timeline and status
  - retryability, structured metrics/error payload
- `OrchestrationJobRunOutput`
  - generic output records per job run (URI, change token, optional artifact ref, metadata/payload)

All records are workspace-confined either directly (`OrchestrationPipeline`, `OrchestrationRun`) or transitively through pipeline/run relationships.

## How apps consume this primitive
Apps should:
1. Register or persist pipeline/job definitions for a workspace.
2. Use `JobOrchestrationService.create_run(...)` for manual or scheduled triggers.
3. Provide executor implementations keyed by `handler_key`.
4. Store artifacts/change tokens in job-run outputs.
5. Use dependency graph readiness to drive downstream execution.

## Run lifecycle service
`xyn_orchestrator/orchestration/lifecycle.py` provides guarded transitions:
- `create_run`
- `mark_job_queued`
- `mark_job_running`
- `mark_job_succeeded`
- `mark_job_failed`
- `mark_job_stale`
- `mark_job_skipped`
- `request_rerun`

Illegal transitions raise `ValueError` (for example, `pending -> succeeded` without running).
The lifecycle service writes attempt rows and output rows, and recomputes parent run status from job-run state.

Future apps (including Deal Finder) should only provide pipeline definitions + handlers, not custom orchestration infrastructure.

## Current TODOs
- TODO: add repository implementation backed by new ORM models.
- TODO: add scheduler loop to materialize scheduled triggers.
- TODO: add dispatcher worker to execute ready job runs with per-pipeline/per-job concurrency enforcement.
- TODO: add run-state aggregation and terminal propagation on failure/skip/stale.
- TODO: add API endpoints/UI surfaces for run status visibility, manual rerun, and scoped rerun.
- TODO: add change-detection policy helpers for upstream diff/change-token semantics.
- TODO: add workspace-level recipient resolution for failure notifications.
