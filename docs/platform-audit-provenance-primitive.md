# Platform Audit / Provenance Primitive

## What this is

The audit/provenance primitive provides a reusable platform seam for:

- durable audit events (`what happened`, `to which object`, `why`, `by whom/what`)
- durable provenance links (`this object/result was derived from these sources`)

It is built for cross-primitive reuse by orchestration, matching, watches, source connectors, rules, and future platform modules.

## What this is not

- not a generic log sink
- not a full lineage graph engine
- not a replacement for run history or lifecycle history tables

## Core concepts

- `PlatformAuditEvent`:
  - workspace-scoped
  - typed event (`event_type`)
  - subject object reference
  - optional actor and cause references
  - summary/reason/metadata
  - optional `run_id`, `correlation_id`, `chain_id`
- `ProvenanceLink`:
  - workspace-scoped source -> target relationship
  - `relationship_type`
  - optional reason/explanation/metadata
  - optional `origin_event_id`, `run_id`, `correlation_id`, `chain_id`

## Normalized object reference contract

References are normalized to:

- `object_family`
- `object_id`
- optional `workspace_id`
- optional `namespace`
- optional `attributes`

This contract is shared across audit events and provenance links.

## Service contract

The canonical service is `xyn_orchestrator.provenance.ProvenanceService`:

- `record_audit_event(...)`
- `record_provenance_link(...)`
- `record_audit_with_provenance(...)`
- `audit_history(workspace_id, object_type, object_id)`
- `provenance_for_object(workspace_id, object_type, object_id, direction)`

## API visibility

- `GET /xyn/api/audit-events`
- `GET /xyn/api/provenance-links`

Both endpoints are workspace-scoped and support object-centric query patterns.

## Integration examples in v1

- record matching evaluation emits:
  - audit event `record_matching.evaluated`
  - provenance links from candidate records to `record_match_evaluation`
- watch evaluation emits:
  - audit event `watch.evaluated`
  - provenance link from `watch_definition` to `watch_match_event`
  - optional provenance link from event object to `watch_match_event`
- source connector lifecycle actions emit audit events:
  - `source_connector.activated`
  - `source_connector.paused`
  - `source_connector.health_updated`

## Relationship to adjacent primitives

- run history:
  - orchestration run models remain canonical for execution history
  - audit/provenance can reference run IDs for causal traceability
- lifecycle:
  - lifecycle transition rows track state transitions
  - audit/provenance adds broader actor/cause/derived-from context
- record matching and watches:
  - existing explanation payloads remain subsystem-local
  - audit/provenance links cross-primitive causality explicitly

## Current TODOs

- TODO: add optional retention/compaction policy for high-volume audit/provenance rows.
- TODO: add operator drill-down UI for object-centric provenance exploration.
- TODO: add deeper path traversal helpers (bounded-depth lineage walk) without introducing a graph subsystem.
- TODO: broaden integrations for orchestration operator actions and lifecycle transition persistence events.
- TODO: provide export/reporting endpoints for compliance/audit snapshots.
