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
New ORM models in `models.py` and migration `0125_orchestration_scaffolding.py`:
- `OrchestrationPipeline`
  - workspace-scoped pipeline definition
  - pipeline-level concurrency and stale timeout
- `OrchestrationJobDefinition`
  - job-level retry/backoff, concurrency, scope flags, output/artifact declaration
- `OrchestrationJobDependency`
  - explicit upstream/downstream edges
- `OrchestrationRun`
  - run trigger (`manual`/`scheduled`/`rerun`/`event`), scope (`jurisdiction`, `source`), status/heartbeat
- `OrchestrationJobRun`
  - per-job run state, retries, stale markers, skip reason, output payload/artifact/change token

All records are workspace-confined either directly (`OrchestrationPipeline`, `OrchestrationRun`) or transitively through pipeline/run relationships.

## How apps consume this primitive
Apps should:
1. Register or persist pipeline/job definitions for a workspace.
2. Use `JobOrchestrationService.create_run(...)` for manual or scheduled triggers.
3. Provide executor implementations keyed by `handler_key`.
4. Store artifacts/change tokens in job-run outputs.
5. Use dependency graph readiness to drive downstream execution.

Future apps (including Deal Finder) should only provide pipeline definitions + handlers, not custom orchestration infrastructure.

## Current TODOs
- TODO: add repository implementation backed by new ORM models.
- TODO: add scheduler loop to materialize scheduled triggers.
- TODO: add dispatcher worker to execute ready job runs with per-pipeline/per-job concurrency enforcement.
- TODO: add run-state aggregation and terminal propagation on failure/skip/stale.
- TODO: add API endpoints/UI surfaces for run status visibility, manual rerun, and scoped rerun.
- TODO: add change-detection policy helpers for upstream diff/change-token semantics.
- TODO: add workspace-level recipient resolution for failure notifications.
