# Internal Work Coordination Artifact

Epic H formalizes Xyn's durable coordination seam without introducing a second execution system.

## Ownership Boundary

- Conversation expresses intent and supervisory commands.
- WorkItem stores durable system work over time.
- Runtime Run / RunStep / RunArtifact store execution attempts and outputs.
- Panels inspect those same durable objects.

No work should exist only in conversation history, transient runtime memory, or panel-local UI state once it has been created.

## Canonical Artifact Mapping

Xyn reuses existing durable models instead of duplicating them:

- `DevTask` is the current WorkItem backing store.
- `xyn-core Run` is the canonical execution attempt for the work-coordination/runtime seam in this document.
- `xyn-core Step` is the canonical RunStep for that seam.
- `xyn-core Artifact` with `run_id` is the canonical RunArtifact for that seam.

For new platform data-processing ingest/import/normalize/reconcile/rule-evaluation/dispatch workflows, use orchestration run history (`OrchestrationRun` and related models) as the canonical substrate.
`OrchestrationRun` is not interchangeable with legacy/runtime `Run` for this purpose.

The platform exposes WorkItem-focused aliases so conversation and panels can use work-coordination terminology without creating a parallel persistence model.

## Lifecycle

```text
conversation
  -> ConversationAction
  -> WorkItem (DevTask)
  -> Run submission to xyn-core
  -> Run / Step / Artifact updates
  -> WorkItem status resolution
  -> workbench panels / activity / thread context
```

### Status flow

- WorkItem starts as `queued`.
- Active runtime execution projects WorkItem status to `running`.
- Failed or blocked runs resolve WorkItem status to `awaiting_review`.
- Successful runs resolve WorkItem status to `completed`, unless policy later requires explicit review on success.

## Provenance

RunArtifact provenance is recoverable through:

```text
RunArtifact -> Run -> WorkItem -> conversation/thread
```

Runtime artifact panel loads are expected to carry:

- `run_id`
- `artifact_id`
- `thread_id` where conversation context is involved

## Thread Context

Thread-scoped conversation context derives active work from durable IDs:

- `current_work_item_id`
- `current_run_id`
- `recent_artifacts`
- `recent_entities`

This keeps shorthand supervision commands tied to stored objects rather than workspace-global transient state.

## Panel Expectations

Epic G/H workbench panels should inspect these durable objects directly:

- Work Item panel -> `GET /xyn/api/work-items/{id}`
- Active Runs panel -> `GET /xyn/api/runtime/runs`
- Run Detail panel -> `GET /xyn/api/runtime/runs/{id}`
- Run Artifact detail -> `GET /xyn/api/runtime/runs/{run_id}/artifacts/{artifact_id}`

## Developer Guidance

When introducing a new work-producing flow:

1. create or reuse a WorkItem before dispatch
2. submit a Run before runtime execution begins
3. record worker progress as RunStep updates
4. register outputs as RunArtifacts
5. expose the same durable IDs through conversation activity and workbench panels

Do not add a second ad hoc work tracker in conversation or UI state.

## Follow-up TODOs

- TODO: expose partition-scoped Stage C publication readiness in operator surfaces to make deferred Stage E/watch evaluation states directly inspectable.
- TODO: add operator/event-consumer polling guidance for `PlatformDomainEvent` (`reconciled_state_published` and `evaluation_ready`) so downstream integrations do not infer readiness from raw job status.
- TODO: add operator visibility for Stage F skips caused by missing Stage E outputs (`evaluation_output_missing`) so notification suppression is diagnosable.
- TODO: add dedicated workbench panel for publication readiness and gating decisions (current support is API-first).

## Outstanding Platform Follow-ups — Data Preview & Versioning

Required hardening:
- Enforce immutability of published versions
  Add DB-level or model-level immutability guards for `OrchestrationStagePublication`.
  Current behavior relies on convention/tests; prefer a hard guard (admin restriction, model validation, or DB constraint where practical).
- Sample rows default contract hardening
  Ensure `sample_metadata.sample_rows` always defaults to `[]` when omitted.
  Keep backend test coverage for this behavior explicit.
- UI test stability (act warnings)
  Eliminate remaining React `act(...)` warnings in Source Inspection review tests by awaiting async state updates.
  Keep tests resilient to async fetch timing.

Optional improvements:
- Router future-flag warnings (non-blocking)
  Address React Router future warnings globally when convenient.
- Extended publication history access
  Add optional API support for querying publication history beyond the last N (currently 10).
  Full history is retained; surface for deeper inspection when needed.
- Geometry summary robustness
  Expand validation/normalization for geometry detection in sample metadata.
  Keep malformed geometry handling non-fatal and consistent.
- Documentation alignment
  Standardize terminology across docs: “current published reconciled version”, “published pointer”, “publication history”.
  Remove ambiguous “latest” language when it could conflict with pointer semantics.
