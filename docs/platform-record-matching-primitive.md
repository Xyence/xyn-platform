# Platform Record Matching Primitive

## What It Is

The platform record matching primitive is a reusable, explainable matching layer for identifying records that likely represent the same real-world entity across inconsistent sources.

It provides:

- reusable strategy registration (`exact_identifier`, normalized exact, fuzzy, weighted composite)
- deterministic scoring with explicit thresholds
- durable match evaluation storage with explanation/provenance
- workspace-scoped API visibility for operators and app developers

## What It Is Not

This is not a full MDM/entity-master product.

Out of scope in v1:

- survivorship/merge policy engines
- canonical golden-record materialization
- full manual review queue UI
- active-learning model tuning

## Core Concepts

- `MatchableRecordRef`: generic source record pointer
  - `source_namespace`, `source_record_type`, `source_record_id`, optional `attributes`
- `RecordMatchEvaluation`: durable result row for one evaluated record pair
  - candidate refs, strategy, score, decision, confidence
  - `pair_fingerprint` (order-independent candidate identity fingerprint)
  - `idempotency_key` for replay-safe persistence
  - explanation signals and metadata
  - optional linkage to `OrchestrationRun` (`run_id`, `correlation_id`, `chain_id`)

Signal boundary:
- `MatchSignal` means matching evidence used to justify a score/decision.
- It is not a generic platform domain-signal entity and should not be conflated with orchestration stage labels such as `match_signals`.

## Built-In Strategies

- `exact_identifier`
- `normalized_text_exact`
- `address_normalized_exact`
- `fuzzy_text_similarity`
- `weighted_composite` (aggregates component scores with explicit weights)

## Address/Owner/Parcel Normalization Expectations

Matching and reconciliation should consume normalized fields, not raw strings.

- **Addresses**
  - Normalize to a deterministic string with common suffix/directional standardization.
  - Extract house number, directional, street name, suffix, and unit when possible.
  - Persist `address_normalized` alongside the raw address.
- **Owner names**
  - Normalize entity suffixes (LLC/INC/TRUST/etc) and strip punctuation.
  - Normalize comma‑style names into a stable order.
  - Persist `owner_name_normalized` alongside the raw owner name.
  - Helper returns `quality` (`ok|bad`) for quick guardrails.
- **Parcel identifiers**
  - Normalize by stripping punctuation/whitespace into `parcel_id_normalized`.
  - Allow jurisdiction‑specific adapters to emit alternate forms.
  - Helper returns `quality` (`ok|bad`) for quick guardrails.

Normalization helpers live in `xyn_orchestrator.matching.normalization` and are deterministic and non‑external (no USPS/CASS). Built-in strategies call `normalize_field_value(...)` so address/owner/parcel fields are normalized consistently at match time even when normalized fields are not persisted yet.

## Confidence/Decision Model

By default:

- `exact_match`: score >= 0.99
- `probable_match`: score >= 0.85
- `possible_match`: score >= 0.65
- `needs_review`: score >= 0.50
- `non_match`: score < 0.50

Thresholds are explicit in `DecisionThresholds` and can be overridden by callers.

## API Surface

- `POST /xyn/api/record-matching/evaluate`
  - evaluates candidate A/B
  - optionally persists result (default true)
  - optional `idempotency_key` for explicit replay-safe writes
- `GET /xyn/api/record-matching/results`
  - list/filter persisted results by workspace
- `GET /xyn/api/record-matching/results/{result_id}`
  - inspect one persisted result

All endpoints are workspace-scoped and use existing membership/auth checks.

Replay/idempotency behavior in v1 hardening:

- Replayed evaluate requests with the same logical idempotency scope return the existing `RecordMatchEvaluation`.
- If callers omit explicit `idempotency_key`, service/repository derive one from workspace + strategy + order-independent pair fingerprint + run/correlation scope.
- A/B and B/A evaluate to the same `pair_fingerprint` and dedupe as one logical evaluation in the same replay scope.
- Matching audit/provenance fan-out is deduped for replayed evaluations.

## How Apps Should Consume It

1. Build `MatchableRecordRef` for the records being compared.
2. Call `RecordMatchingService.evaluate_pair(...)` or `evaluate_candidates(...)`.
3. Use result decision/confidence as an explainable signal in app workflows.
4. Persist and inspect results via API or repository methods.

Apps should not copy matching logic into app-local utilities when this primitive covers the use case.

## Relationship To Other Platform Primitives

- run history: match evaluations can be tied to orchestration runs (`run_id`, `correlation_id`, `chain_id`)
- business rules: matching output can feed rule evaluation as an upstream signal
- geospatial primitive: future strategies may include spatial overlap/proximity without changing core model shape

## Current TODOs

- add candidate blocking/index helpers for high-volume matching workflows
- add manual review workflow/panel on top of `needs_review` outcomes
- define survivorship/merge policy seam for teams that need entity consolidation
- add optional geospatial matching strategy integration backed by PostGIS distance/overlap
- add optional threshold calibration workflow from operator feedback
