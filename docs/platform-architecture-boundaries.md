# Platform Architecture Boundaries (Drift Guard)

This is the concise boundary reference for platform primitives that are most vulnerable to accidental parallel implementations.

For core-vs-artifact placement decisions (especially provider-extensible
domains such as deployment providers), see:
`docs/platform-architecture-placement-contract.md`.

## Canonical seams

- Orchestration/scheduler: `xyn_orchestrator.orchestration` + orchestration models/APIs.
- Run history for new data-processing work: `OrchestrationRun` and related orchestration run models.
- Lifecycle/state-machine: `xyn_orchestrator.lifecycle_primitive` + `LifecycleTransition`.
- Geospatial: `xyn_orchestrator.geospatial` (PostGIS-backed repository + framework-neutral DTO/service contract).
- Record matching: `xyn_orchestrator.matching` + `RecordMatchEvaluation`.
- Parcel identity/crosswalk: `xyn_orchestrator.parcel_identity` + `ParcelCanonicalIdentity` / `ParcelIdentifierAlias` / `ParcelCrosswalkMapping`.
- Source/import contracts: `xyn_orchestrator.sources` + source connector models.
- Watch/subscription: `xyn_orchestrator.watching` + watch models/APIs.
- Audit/provenance: `xyn_orchestrator.provenance` + `PlatformAuditEvent` and `ProvenanceLink`.
- Changed-data domain events: `PlatformDomainEvent` + `xyn_orchestrator.orchestration.domain_events`.
- DealFinder-era app authorization: `xyn_orchestrator.app_authorization` + capability checks in `xyn_api`.

## Adjacent seams that still exist

- Legacy/core runtime run seams remain for compatibility in their own context.
- Campaigns remain first-class but are not the only watch abstraction.
- Legacy `AuditLog` remains historical/utility logging, not canonical provenance linkage.

## Canonical terminology guardrails

- `Campaign` != `WatchDefinition`.
- `WatchSubscriber` != `DeliveryTarget`.
- `NotificationRecipient` (in-app recipient row) != `DeliveryTarget` (delivery endpoint).
- `SourceConnector` != `SourceMapping`.
- `SourceInspectionProfile` != `SourceMapping`.
- `OrchestrationRun` != legacy `Run`.
- `OrchestrationRun` != `WorkflowRun`.
- `MatchSignal` means matching-evidence signal, not a generic domain signal object.
- `Source dataset` is a derived output/read-model concept (for example orchestration outputs), not a source definition.
- `normalized_change_token` is not the same as `reconciled_state_version`; Stage C reconciliation publication is the downstream evaluation boundary.
- `PlatformDomainEvent` (publish-boundary event outbox) != `PlatformAuditEvent` (actor/action audit trail) != `ProvenanceLink` (derived-from linkage).

## Rules Boundary (Platform Contract)

This platform separates **fixed logic**, **business rules**, and **orchestration/config**. The goal is to prevent app invariants or execution behavior from leaking into policy bundles and to keep rules focused on tunable decision logic.

### A. Fixed Logic (App Invariants)

Use **fixed logic** for constraints that must always be true:
- Required fields and validation
- Enablement constraints (e.g., campaign must have name + area before enable)
- Authorization / permissions
- Referential integrity / immutable relationships
- Lifecycle constraints (e.g., publish must be atomic)

**Rule:** These MUST NOT be implemented using policy bundles or rule evaluation stages.

### B. Business Rules (Policy / Tunable Logic)

Use **business rules** for decisions that can be tuned without changing code:
- Scoring logic
- Classification thresholds
- Alert/notification triggers
- Tunable weighting or prioritization

**Rule:** These MAY be implemented using policy bundles and evaluated in Stage E (`rule_evaluation`).

### C. Orchestration / Config

Use **orchestration/config** for how work runs:
- Scheduling (refresh cadence)
- Retry policies
- Pipeline sequencing
- Execution gating and readiness
- Queue/concurrency behavior

**Rule:** These MUST NOT be implemented as business rules.

### Anti-patterns (Do Not Do)

- “campaign must have name before enable” implemented as a rule → ❌
- scheduling or retry logic implemented as rules → ❌
- scoring logic hardcoded in services when intended to be tunable → ❌

### Platform seams and where they belong

- **Policy bundles**: visibility + optional enforcement for business rules
- **Stage E (`rule_evaluation`)**: execution point for business rules
- **Service/domain logic**: invariants
- **Orchestration config**: execution behavior

### Decision guide

- “Does this always have to be true?” → Fixed logic  
- “Could a product owner tune this?” → Business rule  
- “Is this about when/how something runs?” → Orchestration/config  

## Do not reintroduce

- New app-local lifecycle engines or parallel transition tables.
- New generic run-history tables for data-processing work that bypass orchestration runs.
- App-local matching scoring engines outside `xyn_orchestrator.matching`.
- App-local parcel crosswalk tables or one-off parcel join heuristics outside `xyn_orchestrator.parcel_identity`.
- Raw PostGIS query logic outside `xyn_orchestrator.geospatial` repository seams.
- App-local watch/subscription abstractions that bypass `xyn_orchestrator.watching`.
- Alternate audit/provenance object-reference shapes that diverge from canonical object refs.
- Changed-data evaluation paths that bypass Stage C publication readiness checks.
- Parallel app-local publish-boundary event/outbox tables that bypass `PlatformDomainEvent`.
- New app-role/capability catalogs outside `xyn_orchestrator.app_authorization` for DealFinder-era primitives.

## Lightweight automated guard

Run the canonical drift check:

```bash
cd services/xyn-api/backend
python scripts/check_canonical_boundaries.py
```

The check is heuristic and intentionally lightweight. If a finding is intentional, update the allowlist with a code-review note rather than bypassing silently.

## Canonical schema artifacts

Machine-readable object schemas for canonical primitives live in:

- `services/xyn-api/backend/schemas/watch_definition.v1.schema.json`
- `services/xyn-api/backend/schemas/watch_subscriber.v1.schema.json`
- `services/xyn-api/backend/schemas/watch_match_event.v1.schema.json`
- `services/xyn-api/backend/schemas/source_connector.v1.schema.json`
- `services/xyn-api/backend/schemas/source_inspection_profile.v1.schema.json`
- `services/xyn-api/backend/schemas/source_mapping.v1.schema.json`
- `services/xyn-api/backend/schemas/record_match_evaluation.v1.schema.json`
- `services/xyn-api/backend/schemas/platform_audit_event.v1.schema.json`
- `services/xyn-api/backend/schemas/provenance_link.v1.schema.json`

## Current TODOs

- TODO: Keep cross-doc wording synchronized when legacy `Run`/`WorkflowRun` docs are updated.
- TODO: Add stronger UI terminology parity for watch/subscriber/notification-target surfaces when those pages are introduced.
- TODO: add CI checks that require idempotency-key coverage tests for externally triggerable write endpoints in canonical primitives.
- TODO: define a shared docs matrix for replay semantics (`idempotency_key`, deterministic fingerprint, uniqueness backstop) across watch/matching/source/notification flows.
- TODO: add lightweight operator/event-consumer documentation for polling `PlatformDomainEvent` by partition/version.
- TODO: add durable app-role assignment management APIs/UI for `application_admin` / `campaign_operator` / `read_only_analyst`.
- TODO: add stronger parcel crosswalk conflict-resolution flows (supersede/merge/manual review) for cases where one alias appears to map to multiple canonical parcels.
- TODO: add geospatial fallback resolver integration in parcel identity once canonical geospatial candidate scoring is ready.
