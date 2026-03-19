# Platform Job Orchestration Primitive (Scaffolding)

## Intent
This introduces a platform-level, workspace-scoped orchestration primitive for reusable scheduled pipelines.
It is intentionally lightweight and composable, and is not an Airflow replacement.

Cron scheduling is intentionally unsupported in orchestration v1.
Do not use or imply cron scheduling until platform cron support is explicitly implemented and accepted.

## Why this location
The primitive lives in `services/xyn-api/backend/xyn_orchestrator` because that package already owns:
- workspace-scoped durable platform models (`Campaign`, `Goal`, notifications, and orchestration run history)
- orchestration-adjacent queue/recovery logic (`execution_queue.py`, `execution_recovery.py`, `xco.py`)
- API/worker integration points used by platform primitives

`Run` in legacy/runtime seams remains compatibility scope; `OrchestrationRun` is the canonical run-history model for new data-processing orchestration flows.

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
- `publication.py`
  - durable stage publication markers for changed-data readiness
  - explicit reconciled-state publication boundary checks for downstream evaluation
- `domain_events.py`
  - thin durable outbox-style domain events emitted from stage publication transitions
  - idempotent event recording/query helpers for downstream consumers
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
  - normalized run contract fields for platform reuse:
    - `run_type`
    - `target_ref_json`
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
- `OrchestrationStagePublication`
  - durable stage publication/readiness markers scoped by workspace/pipeline/partition
  - separates normalization completion from reconciliation publication readiness
  - stores normalized snapshot markers, reconciled state version, and signal set version
- `PlatformDomainEvent`
  - durable outbox-style domain event rows emitted from explicit publication transitions
  - event types include `source_normalized`, `reconciled_state_published`, `signal_set_published`, `evaluation_ready`
  - replay-safe idempotency keys and partition/version query indexes

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

## Operator readiness/troubleshooting endpoints

- `GET /xyn/api/orchestration/publication-readiness`
  - returns latest Stage B/C/D publication markers for workspace/pipeline/partition
  - returns evaluation readiness (`ready`, `reason`, reconciled/signal versions)
  - returns recent blocked/deferred gating decisions (`reason_code`)
- `GET /xyn/api/orchestration/domain-events`
  - returns recent domain events filtered by workspace/pipeline/partition/version/correlation
- `GET /xyn/api/orchestration/runs/<run_id>`
  - includes per-job `skipped_reason`, `gating_decision`, `stage_publication`, and `domain_events`
  - includes run-scoped `publication_readiness` and `latest_scope_publications`

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
8. Stage publication markers are recorded on successful stage jobs; Stage E evaluation paths require Stage C publication readiness.

## Changed Data Triggering Contract

See [Changed Data Triggering Contract](./changed-data-triggering-contract.md).
See [Platform Domain Events Primitive](./platform-domain-events-primitive.md).

Key enforced rule in v1:
- `rule_evaluation` (Stage E) is skipped when no reconciled publication (`property_graph_rebuild`) exists for the same workspace/pipeline/partition.
- `rule_evaluation` (Stage E) is skipped when signal publication references a reconciled version that is not published for the same workspace/pipeline/partition.
- `notification_emission` (Stage F) is skipped when Stage E produced no durable outputs.
- API-driven watch evaluation is deferred (409) when reconciled publication readiness is absent.

## Manual trigger replay contract (v1 hardening)

- `POST /xyn/api/orchestration/runs` accepts optional top-level `idempotency_key`.
- when present, this key is forwarded into run metadata and enforced by run idempotency constraints (`workspace + pipeline + idempotency_key`).
- replaying the same manual trigger key returns the existing run instead of creating duplicate runs.

Future apps (including Deal Finder) should only provide pipeline definitions + handlers, not custom orchestration infrastructure.

## Current TODOs
- TODO: implement production-safe cron scheduling (parser + timezone semantics) before enabling `cron` in v2.
- TODO: add optional automatic stale-retry/failure escalation policy hooks.
- TODO: integrate engine tick with the platform worker/queue cadence.
- TODO: add API endpoints/UI surfaces for run status visibility, manual rerun, and scoped rerun.
- TODO: add richer change-detection policy helpers for upstream diff semantics beyond output tokens.
- TODO: add workspace-level recipient resolution for failure notifications.
- TODO: publish a unified platform-facing run-history contract that maps orchestration vs legacy/runtime seams unambiguously.
- TODO: define a staged retirement/migration plan for legacy `Run` usage where orchestration run history is now the default for new data-processing work.
- TODO: add operator/API cross-links so runtime proxy run views and orchestration run views can be navigated without seam ambiguity.
- TODO: define provenance alignment conventions between `target_ref_json`, orchestration outputs, and downstream derived artifacts.
- TODO: align orchestration run identifiers with record-matching evaluation provenance conventions (`run_id`, `correlation_id`, `chain_id`) for cross-primitive operator debugging.
- TODO: align source connector execution contracts (`SourceConnector` run_type/target_ref/scope_source) with orchestration trigger templates so source activation can safely schedule refresh runs without app-local glue.
- TODO: extend real handler integrations so Stage B/C/D publication markers are populated from domain payloads beyond fallback tokens.
- TODO: add operator API index/list endpoint for partition-scoped stage publication readiness snapshots.
- TODO: add operator/API list endpoint for partition/version-scoped domain event outbox browsing.
- TODO: add optional deferred replay queue for Stage E requests that fail readiness with `reconciled_state_not_published` / `reconciled_state_version_not_published`.
- TODO: add schema-validated Stage E output contract checks before Stage F dispatch (beyond presence checks).

## Lifecycle Primitive TODOs
- TODO: migrate additional object adapters (campaign/source connector/workflow-like entities) onto the canonical lifecycle primitive contract and durable `LifecycleTransition` history rows.
- TODO: add a shared API/serializer seam for transition history visibility across object families without duplicating object-specific endpoints.

## Audit/Provenance TODOs
- TODO: align orchestration operator actions with canonical `PlatformAuditEvent` emission patterns for trigger/rerun/cancel/ack paths.
- TODO: add first-party provenance links from orchestration job outputs/artifacts to downstream records and notifications.

## Canonical-Boundary Guardrail TODOs
- TODO: wire `scripts/check_canonical_boundaries.py` into CI default backend validation (not only targeted/manual runs).
- TODO: add cross-repo guard checks that assert `xyn/core` compatibility seams do not regain canonical platform-primitive ownership.
