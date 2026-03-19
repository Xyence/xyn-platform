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
  - optional orchestration run linkage
- `SourceMapping`
  - versioned mapping metadata
  - field mapping, transformation hints, validation state
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

## Relationship to Other Platform Primitives

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

## Current TODOs

- add connector credential secret reference patterns and rotation workflows
- add parser/profile adapters for common tabular/file formats
- add schema drift detection and mapping impact warnings
- add incremental import cursor/checkpoint tracking
- add bulk import throughput optimizations and chunk-level diagnostics
