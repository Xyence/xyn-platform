# Platform Run History Boundaries (Primitive #2)

## Canonical direction for new data-processing work

For new platform and app workflows that perform ingest/import/normalize/reconcile/rule-evaluation/notification-dispatch work, use the orchestration run model as the canonical durable history substrate:

- `OrchestrationRun`
- `OrchestrationJobRun`
- `OrchestrationJobRunAttempt`
- `OrchestrationJobRunOutput`

This includes both scheduler-triggered and manually-triggered processing.

## Normalized orchestration run contract

`OrchestrationRun` is the normalized durable record for new data-processing history and includes:

- `run_type` (explicit semantic category, for example `ingest.import`, `normalize.pass`, `rules.evaluate`)
- `target_ref_json` (explicit target object/reference payload)
- `trigger_cause`, `correlation_id`, `chain_id`
- status/timestamps/summary/error details/metrics

`run_type` and `target_ref_json` are intentionally generic and must remain app-agnostic.

## Legacy model boundaries

### `Run` / `RunArtifact` / `RunCommandExecution`

These remain for legacy xyn-core/runtime execution tracking and compatibility with existing work-item/runtime seams.
Do not use this legacy model as the default for new data-processing ingest pipelines.

### `WorkflowRun` / `WorkflowRunEvent`

These remain for workflow-artifact-specific execution/event tracking.
Do not treat `WorkflowRun` as the canonical platform run-history substrate for new ingest/data pipelines.

### Runtime proxy APIs (`/api/runtime/runs`)

These proxy xyn-core runtime run views for operational runtime surfaces.
They are not a replacement for orchestration run history for new data-processing primitives.

