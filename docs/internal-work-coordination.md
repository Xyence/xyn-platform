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
