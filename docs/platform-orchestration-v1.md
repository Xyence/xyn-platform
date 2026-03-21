# Platform Orchestration v1 (Production Baseline)

This document describes the first production-ready baseline for the platform scheduler/job orchestration primitive.

Cron scheduling is intentionally unsupported in orchestration v1.
Do not use or imply cron scheduling until platform cron support is explicitly implemented and accepted.

For new platform data-processing run history, orchestration run models are the canonical substrate.
See [Platform Run History Boundaries](./platform-run-history-boundaries.md).

## What this ships

- Workspace-scoped orchestration persistence:
  - pipelines
  - job definitions
  - schedules
  - dependencies
  - runs
  - job runs
  - attempts
  - outputs/artifacts metadata
  - stage publication/readiness markers (`OrchestrationStagePublication`)
  - domain event outbox rows (`PlatformDomainEvent`) emitted from publication transitions
- Scheduler/runtime engine:
  - due schedule polling
  - partition-aware run materialization (`jurisdiction`, `source`)
  - dependency resolution
  - queue/dispatch
  - retry with exponential backoff and max attempts
  - stale detection
  - manual rerun
- Schedule support in v1:
  - `interval` (poll-driven)
  - `manual` (API/operator initiated)
  - `cron` is explicitly unsupported and rejected in v1
- App-facing authoring API:
  - typed job/pipeline DSL
  - registry and validation
  - example generic data pipeline
- Operator API:
  - job/schedule/dependency inspection
  - run list/detail filters
  - manual trigger/rerun/cancel
  - failed/stale acknowledgement

## Runtime model

1. `DueJobScanner` finds due schedules by `enabled + next_fire_at` horizon.
2. `RunPlanner` creates runs idempotently from schedule metadata and advances schedule fire time.
3. `DependencyResolver` transitions ready jobs to `queued` when upstream jobs are terminal and valid.
   - Stage E (`rule_evaluation`) additionally requires Stage C (`property_graph_rebuild`) reconciled publication readiness for the same workspace/pipeline/partition.
4. `RunDispatcher` claims jobs, enforces concurrency, invokes executor handlers, records attempts/outputs.
5. Retryable failures move to `waiting_retry` with `next_attempt_at` using exponential backoff.
6. `StaleRunDetector` marks stale queued/running jobs when deadlines are truly exceeded.
7. Publication transitions emit durable domain events:
   - Stage B: `source_normalized`
   - Stage C: `reconciled_state_published`, `evaluation_ready`
   - Stage D: `signal_set_published`

Timezone note:
- v1 scheduler timing uses persisted UTC timestamps (`next_fire_at`) for polling/advancement.
- Cron timezone semantics are not enabled in v1.

## Idempotency expectations

The orchestration runtime provides dedupe/idempotency keys at run/job-run storage level, but handler logic must still be idempotent.

Handler requirements:
- Safe re-entry for the same logical work unit.
- No duplicate side effects when retrying the same attempt domain.
- Output artifacts should be overwrite-safe or versioned deterministically.
- External writes should use stable idempotency keys derived from:
  - `run_id`
  - `job_run_id`
  - partition scope (`jurisdiction`, `source`)

## Hardening notes

- Attempt counting is monotonic and increments per dispatch attempt.
- Retry transitions stop at `max_attempts` and then hard-fail.
- Downstream dependency resolution blocks while upstream is retrying; it resumes once upstream succeeds.
- Dispatch claims are lock-safe using row-level `select_for_update(skip_locked=True)` semantics.
- Stale detection refreshes heartbeat-derived deadlines before marking stale to avoid stale false positives.
- Structured logs include:
  - schedule materialization
  - dispatch blocked summaries
  - executor exceptions with context
  - tick summaries

## Complete generic example pipeline

The built-in sample pipeline (`sample_data_sync`) demonstrates:

- Stages:
  - `refresh_source`
  - `normalize_source`
  - `rebuild_entities`
  - `match_signals`
  - `evaluate_rules`
  - `emit_notifications`
- Partition-aware execution:
  - per source
  - per jurisdiction
- Dependency chain from refresh through notification emission.
- `only_if_upstream_changed` gating on downstream stages.
- explicit publication/readiness boundary:
  - Stage B normalization writes change markers but does not make evaluation ready.
  - Stage C reconciliation/publish is the required boundary for Stage E.
- Retry/backoff demonstration via `simulate_retry_once` manual parameter.
- Stage outputs with artifacts/metrics metadata per execution.
- Manual rerun support through run API.

Reference code:
- `xyn_orchestrator/orchestration/examples.py`
- `xyn_orchestrator/orchestration/publication.py`

See [Changed Data Triggering Contract](./changed-data-triggering-contract.md).
See [Platform Domain Events Primitive](./platform-domain-events-primitive.md).

## Performance/indexing

Polling/dispatch queries align to indexed dimensions:
- schedules: `enabled, next_fire_at`
- runs/job-runs: workspace + status + partition + time
- retries: `status, next_attempt_at`
- stale scanning: `pipeline, stale_deadline_at, status`

These indexes support scheduler polling, status visibility, and dependency-driven dispatch workflows.

## v2 items (not in v1)

- Robust cron parser and timezone-aware cron next-fire calculation (required before enabling `cron` schedule kind).
- Automatic stale escalation policy (auto-retry vs terminal failure policy hooks).
- Push-based trigger/event integration beyond polling.
- Multi-worker fairness and throughput tuning under very high queue pressure.
- UI-level operator screens beyond API surfaces.
- Policy-driven notification routing (on-call rotation, escalation rules).
- Unified platform-facing run-history contract across orchestration, legacy runtime `Run`, and workflow-specific seams.
- Legacy seam migration/deprecation plan for run-history usage where orchestration is now the default for new data-processing work.
- Operator/API navigation unification across runtime proxy runs and orchestration runs.
- Provenance alignment guidance for `run_type`/`target_ref_json` and downstream artifact lineage.
