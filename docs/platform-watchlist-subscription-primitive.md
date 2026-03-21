# Platform Watchlist / Subscription Primitive

## What this is

The watchlist primitive is a thin platform abstraction for:

- defining workspace-scoped watches over target sets
- associating subscribers/recipients to each watch
- evaluating events/objects against watch criteria
- storing explainable match history

This is platform infrastructure intended for reuse by campaigns, domain apps, and operational features.

## What this is not

- not a full campaign engine
- not a full notification delivery system
- not a workflow/orchestration replacement

The primitive emits notification intent metadata for downstream notification systems, but does not send notifications directly.

## Core model

- `WatchDefinition`: workspace-scoped watch contract (`key`, `name`, `target_kind`, `target_ref`, `filter_criteria`, lifecycle, metadata, optional `linked_campaign`)
- `WatchSubscriber`: subscriber associations (`subscriber_type`, `subscriber_ref`, destination/preferences, enabled)
- `WatchMatchEvent`: durable evaluation output (`matched`, `score`, reason/explanation, event reference, optional run/correlation/chain linkage)

Lifecycle states in v1:

- `draft`
- `active`
- `paused`
- `archived`

Subscriber types in v1:

- `user_identity`
- `delivery_target`
- `external_endpoint`

## API surface (v1)

- `POST /xyn/api/watches`
- `GET /xyn/api/watches`
- `GET/PATCH /xyn/api/watches/{watch_id}`
- `POST /xyn/api/watches/{watch_id}/activate`
- `POST /xyn/api/watches/{watch_id}/pause`
- `POST/GET /xyn/api/watches/{watch_id}/subscribers`
- `POST /xyn/api/watches/matches/evaluate`
- `GET /xyn/api/watches/matches`

All endpoints are workspace-scoped and enforce workspace membership.

## Evaluation behavior

Evaluation is explainable and deterministic:

- target-kind compatibility check
- `target_ref` key/value checks against incoming event reference
- `filter_criteria` checks with explicit operators (`eq`, `in`, `contains`, `gte`, `lte`)
- durable `WatchMatchEvent` persistence when `persist=true`

When a match succeeds, a `notification_intent` payload is attached for downstream delivery handling.

Replay/idempotency behavior in v1 hardening:

- `POST /xyn/api/watches/matches/evaluate` accepts optional `idempotency_key`.
- If omitted, the service derives a deterministic replay key from workspace/watch/event payload scope.
- Replayed evaluations return/reuse the existing `WatchMatchEvent` row instead of appending duplicates.
- Provenance/audit fan-out for replayed match events is deduped using the same logical replay scope.

## Relationship to other primitives

- campaigns: watches may optionally link to a campaign (`linked_campaign`) as a light integration seam
- notifications: watch matches emit notification intent metadata, but notification sending remains in notification subsystems
- orchestration/run history: watch matches can record `run_id`, `correlation_id`, and `chain_id` for operator traceability
- rules: rules engines can call watch evaluation service or the evaluate API as a reusable match gate

## Current TODOs

- TODO: add richer subscriber preference policy (digest windows, per-event-type settings, and quiet hours).
- TODO: add configurable throttling windows on top of deterministic idempotency for intentionally noisy event streams.
- TODO: define retention policy and archival/compaction strategy for `WatchMatchEvent` rows.
- TODO: provide campaign-on-watch adapter helpers for progressive campaign simplification.
- TODO: add operator UI surfaces for watch inspection and match drill-down beyond API-first visibility.
