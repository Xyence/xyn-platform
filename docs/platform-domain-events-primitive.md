# Platform Domain Events Primitive

## Intent

A thin, durable domain-event outbox for changed-data workflows.

This primitive records explicit publish-boundary events so downstream consumers react to published domain state, not raw job success alone.

## What it is

- durable event rows (`PlatformDomainEvent`)
- emitted from explicit stage publication transitions (`OrchestrationStagePublication`)
- workspace/partition scoped (`workspace`, `jurisdiction`, `source`)
- replay-safe via deterministic idempotency keys
- queryable by type/scope/version for lightweight polling consumers

## What it is not

- not a broker platform
- not a Kafka replacement
- not audit/provenance history
- not orchestration lifecycle replacement

## Canonical event types (v1)

- `source_normalized`
- `reconciled_state_published`
- `signal_set_published`
- `evaluation_ready`

`reconciled_state_published` is the downstream boundary event for evaluation readiness.

## Emission semantics (v1)

- Stage B (`source_normalization`) emits `source_normalized` when normalized markers are written.
- Stage C (`property_graph_rebuild`) emits `reconciled_state_published` and `evaluation_ready` only when reconciled publication is durable.
- Stage D (`signal_matching`) emits `signal_set_published` when signal-set publication is durable.
- No event is emitted solely because a job reached `succeeded` if domain publication markers are absent.

## Domain events vs audit/provenance

- `PlatformDomainEvent`: downstream-readiness and process publication signals.
- `PlatformAuditEvent`: actor/action/object audit trail.
- `ProvenanceLink`: source->target derivation relationships.

Operational failure notifications (for example orchestration failure alerts) are separate from evaluation-driven domain notifications. They are not substitutes for `evaluation_ready` or Stage E outputs.

These primitives are complementary and intentionally separate.

## Query pattern

Use `DomainEventService.list_events(...)` filtering by:

- `workspace_id`
- `event_type`
- `pipeline_id`
- `jurisdiction` / `source`
- `reconciled_state_version`
- `signal_set_version`
- `correlation_id` / `chain_id`

Operator API:

- `GET /xyn/api/orchestration/domain-events`
  - filter by `workspace_id` (required)
  - optional `pipeline_key`, `jurisdiction`, `source`, `event_type`
  - optional `reconciled_state_version`, `signal_set_version`, `run_id`, `correlation_id`, `chain_id`

## Current TODOs

- TODO: add optional consumer checkpoint helpers for long-poll/outbox cursor patterns.
- TODO: add retention/compaction policy for high-volume event streams.
- TODO: add operator API list endpoint for domain events if/when operator UI needs direct event browsing.
