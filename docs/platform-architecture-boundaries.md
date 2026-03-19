# Platform Architecture Boundaries (Drift Guard)

This is the concise boundary reference for platform primitives that are most vulnerable to accidental parallel implementations.

## Canonical seams

- Orchestration/scheduler: `xyn_orchestrator.orchestration` + orchestration models/APIs.
- Run history for new data-processing work: `OrchestrationRun` and related orchestration run models.
- Lifecycle/state-machine: `xyn_orchestrator.lifecycle_primitive` + `LifecycleTransition`.
- Geospatial: `xyn_orchestrator.geospatial` (PostGIS-backed repository + framework-neutral DTO/service contract).
- Record matching: `xyn_orchestrator.matching` + `RecordMatchEvaluation`.
- Source/import contracts: `xyn_orchestrator.sources` + source connector models.
- Watch/subscription: `xyn_orchestrator.watching` + watch models/APIs.
- Audit/provenance: `xyn_orchestrator.provenance` + `PlatformAuditEvent` and `ProvenanceLink`.

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

## Do not reintroduce

- New app-local lifecycle engines or parallel transition tables.
- New generic run-history tables for data-processing work that bypass orchestration runs.
- App-local matching scoring engines outside `xyn_orchestrator.matching`.
- Raw PostGIS query logic outside `xyn_orchestrator.geospatial` repository seams.
- App-local watch/subscription abstractions that bypass `xyn_orchestrator.watching`.
- Alternate audit/provenance object-reference shapes that diverge from canonical object refs.

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

- TODO: Add schema coverage for canonical watch/source/matching/audit objects in `services/xyn-api/backend/schemas`.
- TODO: Keep cross-doc wording synchronized when legacy `Run`/`WorkflowRun` docs are updated.
- TODO: Add stronger UI terminology parity for watch/subscriber/notification-target surfaces when those pages are introduced.
