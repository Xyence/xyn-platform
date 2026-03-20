# Changed Data Triggering Contract

This contract defines the required publication boundary for downstream evaluation in changed-data workflows.

## Stage Model

- Stage A: `source_refresh`
- Stage B: `source_normalization`
- Stage C: `property_graph_rebuild` (reconciliation + publication boundary)
- Stage D: `signal_matching`
- Stage E: `rule_evaluation` / watch evaluation
- Stage F: `notification_emission`

## Publication Markers

The platform persists stage publication markers through orchestration stage publication records:

- `normalized_snapshot_ref`
- `normalized_change_token`
- `reconciled_state_version`
- `signal_set_version`

Markers are partition-aware (`workspace`, `pipeline`, `jurisdiction`, `source`).

### Jurisdiction key format

Jurisdiction values must use canonical keys (lowercase, hyphen-separated, explicitly city vs county):
- `mo-stl-city`
- `mo-stl-county`
- `tx-travis-county`

Do not use ambiguous tokens like `stl` or `tx`; canonical keys are required for partition safety.

Current published reconciled state is anchored by a dedicated pointer:

- `ReconciledStateCurrentPointer` records the single current `reconciled_state_version` per workspace/pipeline/partition.
- Promotion to current is an atomic pointer update; historical publications remain intact.

## Required Boundary Rules

1. Stage B completion does not imply evaluation-readiness.
2. Stage C is the mandatory publish boundary for Stage E.
3. Stage E must only run when a reconciled publication exists for the same workspace/partition.
4. Stage D signal publication should be linked to the reconciled state version.
5. Stage F must run only from Stage E outputs.
6. API-driven watch/rule evaluation must reject/defer when reconciled publication readiness is absent.
7. If API-driven evaluation supplies a `reconciled_state_version`, that exact version must be published for the same workspace/pipeline/partition.

## Implementation Notes (v1)

- Orchestration dependency gating still uses `only_if_upstream_changed`, but Stage E adds an explicit reconciled-publication readiness check.
- Stage E readiness enforces reconciled-state version consistency when a signal publication references an explicit reconciled version.
- Stage F notification emission is skipped when Stage E has no durable outputs.
- Reconciled publication readiness is durable and queryable through stage publication records.
- `output_change_token` is a change signal, not a substitute for the Stage C publish boundary.
- Downstream readers should resolve the current reconciled version via `ReconciledStateCurrentPointer` unless an explicit version is requested.
- Historical published versions remain inspectable via stage publication history; promotion only updates the current pointer.
- Operator/read APIs expose `current_pointer` and `publication_history` for partition-scoped inspection.

## Domain Events (v1)

The platform records durable domain events from publication transitions:

- Stage B: `source_normalized`
- Stage C: `reconciled_state_published`, `evaluation_ready`
- Stage D: `signal_set_published`

`evaluation_ready` is emitted only after Stage C has published reconciled state for the same workspace/pipeline/partition.

## Suppression reason codes (v1)

- `reconciled_state_not_published`: no Stage C publication exists for the workspace/pipeline/partition.
- `reconciled_state_version_not_published`: a required reconciled version is not published for the workspace/pipeline/partition.
- `evaluation_output_missing`: Stage F notification emission was blocked because Stage E produced no durable outputs.
