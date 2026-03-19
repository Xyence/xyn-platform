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
  - v1 validation explicitly rejects `cron` (reserved for future implementation)
- `graph.py`
  - dependency graph representation
  - topological ordering and ready-job resolution
  - `only_if_upstream_changed` gating support
- `interfaces.py`
  - repository interface, executor interface, notifier interface
  - run creation and execution context contracts
- `service.py`
  - orchestration service seam for run creation and rerun entry point
  - exponential backoff utility
- `repository.py`
  - Django ORM repository implementation for durable runs, attempts, outputs
- `lifecycle.py`
  - guarded run/job transitions and attempt/output persistence
- `engine.py`
  - scheduler/orchestration runtime components:
    - `DueJobScanner` (due schedule polling)
    - `RunPlanner` (scheduled run materialization + partition fanout)
    - `DependencyResolver` (deterministic dependency readiness)
    - `ConcurrencyGuard` (global/pipeline/job/partition dispatch limits)
    - `RunDispatcher` (executor dispatch + success/fail/skip handling)
    - `StaleRunDetector` (queued/running stale reconciliation)
    - `OrchestrationEngine` (single tick loop composing all steps)
- `registration.py`
  - app-facing typed DSL for job definition and pipeline composition
  - pipeline validation and registry for handlers + pipeline templates
- `examples.py`
  - generic sample pipeline (`refresh_source` -> `emit_notifications`) for app onboarding
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
  - v1 runtime support is intentionally limited to `manual` and `interval`
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
1. Define jobs/pipelines with the registration API (`define_job`, `compose_pipeline`, `OrchestrationRegistry`).
2. Use `JobOrchestrationService.create_run(...)` for manual or scheduled triggers.
3. Provide executor implementations keyed by `handler_key`.
4. Store artifacts/change tokens in job-run outputs.
5. Use dependency graph readiness to drive downstream execution.

See [Platform Job Authoring Guide](./platform-job-authoring-guide.md) for examples.
See [Orchestration Operator API](./orchestration-operator-api.md) for runtime visibility and intervention endpoints.
See [Platform Orchestration v1](./platform-orchestration-v1.md) for production runtime and hardening notes.

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

## Runtime execution flow
1. `DueJobScanner` polls enabled schedule rows with `next_fire_at <= now`.
2. `RunPlanner` creates workspace-scoped `OrchestrationRun` rows (with correlation/chain ids and partition scope) and advances schedule fire times.
3. `DependencyResolver` evaluates dependencies and transitions ready `OrchestrationJobRun` rows to `queued`.
4. `RunDispatcher` applies concurrency guard checks, starts job runs, invokes registered executors, and records success/failure/skip outputs.
5. Retryable failures move to `waiting_retry` with exponential backoff; dispatch re-queues them when `next_attempt_at` is due.
6. `StaleRunDetector` marks long-stuck queued/running jobs as `stale`.
7. Run status is recomputed from job-run state at each lifecycle transition.

Future apps (including Deal Finder) should only provide pipeline definitions + handlers, not custom orchestration infrastructure.

## Current TODOs
- TODO: implement production-safe cron scheduling (parser + timezone semantics) before enabling `cron` in v2.
- TODO: add optional automatic stale-retry/failure escalation policy hooks.
- TODO: integrate engine tick with the platform worker/queue cadence.
- TODO: add API endpoints/UI surfaces for run status visibility, manual rerun, and scoped rerun.
- TODO: add richer change-detection policy helpers for upstream diff semantics beyond output tokens.
- TODO: add workspace-level recipient resolution for failure notifications.
