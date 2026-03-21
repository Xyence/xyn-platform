# Platform Source Connector / Import Pipeline Primitive

## What It Is

A reusable platform primitive for registering and operating data sources used by imports/refresh workflows across apps.

It provides durable source lifecycle, inspection/profile storage, mapping metadata, activation controls, and health visibility.

## What It Is Not

- Not a full ETL orchestration suite
- Not a universal parser library
- Not a replacement for orchestration scheduling/execution

## Core Models

- `SourceConnector`
  - workspace-scoped source definition
  - mode (`file_upload`, `remote_url`, `api_polling`, `manual`)
  - lifecycle (`registered`, `inspected`, `mapped`, `validated`, `active`, `failing`, `paused`)
  - health (`unknown`, `healthy`, `warning`, `failing`, `paused`)
  - refresh cadence, config, provenance, and latest health/run timestamps
- `SourceInspectionProfile`
  - durable inspection/profile result
  - detected format, discovered fields, sample metadata, validation findings
  - `inspection_fingerprint` + optional `idempotency_key` for replay-safe inspection persistence
  - optional orchestration run linkage
- `SourceMapping`
  - versioned mapping metadata
  - field mapping, transformation hints, validation state
  - `mapping_hash` + optional `idempotency_key` for replay-safe mapping persistence
  - current mapping pointer and validation metadata

## API Surface (v1)

- `POST /xyn/api/source-connectors`
- `GET /xyn/api/source-connectors`
- `GET/PATCH /xyn/api/source-connectors/{source_id}`
- `POST/GET /xyn/api/source-connectors/{source_id}/inspections`
- `POST/GET /xyn/api/source-connectors/{source_id}/mappings`
- `POST /xyn/api/source-connectors/{source_id}/activate`
- `POST /xyn/api/source-connectors/{source_id}/pause`
- `POST /xyn/api/source-connectors/{source_id}/health`

## Readiness and Activation

A source is activation-ready when:

- at least one inspection exists
- current mapping exists and is `validated` or `active`
- remote/API sources have `refresh_cadence_seconds > 0`

Activation does not create a scheduler loop; it marks the source as ready/active for orchestration-driven refresh execution.

## Source Governance Contract

`SourceConnector.governance_json` is the typed governance declaration for execution invariants. This is intentionally separate from policy bundles/rules.

Supported fields:

- `allowed_ingestion_methods`: `download | api | upload | browser_automation | manual`
- `browser_automation_allowed`: boolean, defaults to `false` when omitted
- `review_required`: boolean
- `legal_status`: `allowed | restricted | prohibited`
- `legal_notes`: optional text
- `legal_reference_urls`: optional list of URLs
- `expected_refresh_interval_seconds`: optional freshness expectation
- `notes`: optional operator/governance notes

Safe defaults:

- browser automation is denied unless explicitly allowed
- `legal_status=prohibited` blocks activation/run/fetch/automation
- sources without governance metadata remain backward-compatible and evaluate as `legal_status=allowed`

Enforcement points:

- source activation (`POST /source-connectors/{id}/activate`)
- run trigger (`POST /orchestration/runs`) when a source connector context is present
- ingestion fetch pre-check (`IngestionCoordinator.ingest_from_url`)

Decision outputs are explicit and inspectable:

- `decision`: `allow | deny | defer`
- `reason_code`: machine-readable governance reason
- `message`: operator-friendly text
- `freshness`: `fresh | stale | unknown` based on `last_success_at` + expected refresh interval

Review gate:

- `review_required=true` defers execution until source review approval is set (`review_approved`, `review_approved_at`, `review_approved_by`)

Audit taxonomy:

- `source_governance.denied_run`
- `source_governance.deferred_run`
- `source_governance.denied_fetch`
- `source_governance.deferred_fetch`
- `source_governance.denied_activation`
- `source_governance.deferred_activation`
- `source_governance.denied_browser_automation`
- `source_governance.review_state_changed`

## Replay/idempotency behavior

- inspection and mapping POST flows accept optional `idempotency_key`.
- repeated requests with the same key return/reuse the existing row.
- mapping updates compute a deterministic `mapping_hash`; replay with unchanged semantics avoids creating a duplicate new version.
- version allocation is lock-safe (`max(version)+1` under transaction) to reduce replay/concurrency collisions.

## Source Dataset Boundary

`SourceConnector` is the source definition and lifecycle object.
Derived datasets produced by source processing are output/read-model artifacts (for example orchestration outputs and artifacts), not interchangeable source-definition objects in v1.

## Storage Contract

Ingest artifacts (raw snapshots, normalized outputs, retained parser results) must use the canonical storage contract defined in `docs/platform-storage-contract.md`.
Source connectors should not persist blob/file data directly on the source model.

## Inspection Preview Contract (UI)

The inspection preview UI is metadata-only and read-only. The backend serializes preview-friendly metadata via `sample_metadata`:

- `sample_metadata.sample_rows`: optional list of row objects for preview
- `sample_metadata.profile_summary`:
  - `row_count`
  - `discovered_fields_count`
  - `has_sample_rows`
  - `has_geometry`
- `sample_metadata.geometry_summary` (when geometry is present or errors occur):
  - `present`
  - `geometry_types`
  - `bbox` `[minx, miny, maxx, maxy]`
  - `centroid` `{ x, y }`
  - `errors` (non-fatal)

This contract is additive and does not imply an interactive map or data explorer.

## Relationship to Other Platform Primitives

- source adapters: parsed ingestion outputs should flow through the canonical source adapter layer (`IngestAdaptedRecord`) before app/domain mapping; source mapping targets adapted contracts, not raw parser-specific payload shapes.
- orchestration: source execution contracts can produce orchestration run requests (`run_type` + `target_ref` + `scope_source`)
- run history: source health can link to `OrchestrationRun` (`last_run`)
- record matching: source outputs can flow into matching pipelines without source-specific matching code
- geospatial: source mappings can carry geometry fields for downstream geospatial processing

## Plugin Boundary for Future Connectors/Parsers

This primitive defines stable registration/lifecycle/mapping contracts.

Future work should plug in:

- source-specific fetch adapters
- format parsers and profiling enrichers
- drift detectors and mapping assist tooling

without changing core source lifecycle semantics.

### Adapter Config Notes (JSON / ArcGIS REST)

For JSON-backed sources, adapter behavior can be steered via existing connector configuration:

- `configuration_json.json_adapter.record_path` for generic JSON record extraction
- `configuration_json.json_adapter.adapter_kind = "arcgis_rest_json"` to force ArcGIS adapter selection when payload shape is ambiguous
- `configuration_json.json_adapter.features_path` to override where ArcGIS features are read from

## Current TODOs

- add connector credential secret reference patterns and rotation workflows
- add explicit reviewer workflows/UI around `review_required` approvals and revocations
- add scheduler-time governance checks for all automated trigger paths
- extend adapter coverage for deferred formats (ArcGIS REST JSON, standalone DBF parser flow, file geodatabase)
- add schema drift detection and mapping impact warnings
- add incremental import cursor/checkpoint tracking
- add bulk import throughput optimizations and chunk-level diagnostics
- formalize a first-party source-dataset read-model contract for consumers that need stable dataset semantics beyond generic orchestration outputs
