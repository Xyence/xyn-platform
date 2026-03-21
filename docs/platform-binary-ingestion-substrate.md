# Platform Binary Ingestion Substrate

## Purpose

This runtime provides a generic ingestion substrate for file- and archive-based sources.

It supports:

- HTTP fetch with explicit timeout behavior
- raw artifact persistence with remote metadata capture
- ZIP archive expansion with zip-slip protection
- durable archive member tracking
- file classification and parser routing
- generic normalized parsed-record persistence
- provenance links from parsed records back to artifacts/members/runs

## Durable entities

The substrate extends existing ingestion durability patterns.

- `IngestArtifactRecord`
  - includes fetch metadata: `source_url`, `final_url`, `response_status`, `etag`, `last_modified`, `original_filename`, `fetched_at`, `sha256`
- `IngestArtifactMember`
  - one row per extracted archive member
  - captures `member_path`, `group_key`, extension/classification, status/failure
  - links parent artifact to member artifact
- `IngestParsedRecord`
  - generic normalized output envelope
  - links run/source/artifact/member/parser/normalization version
  - stores source payload, normalized payload, schema and provenance metadata

## Fetch behavior

`HttpArtifactFetcher` streams bytes to a temporary file, computes sha256 during streaming, and persists the raw artifact through `IngestStorageService`.

Timeouts are explicit and split into:

- connect timeout
- read timeout

Failures are surfaced as exceptions and run failure metadata in coordinator flows.

## Ingest run lifecycle semantics

The ingestion coordinator writes durable run-level semantics on `OrchestrationRun`:

- `status=running` when fetch begins
- `status=skipped` when fetch succeeded but artifact content hash is unchanged (`no_op`)
- `status=succeeded` for complete or partial parse success
- `status=failed` for fatal fetch/parse execution failures

`metadata_json.ingestion` and `metrics_json.ingestion` capture:

- whether fetch was attempted
- artifact id and sha256 observed
- whether content changed
- whether parsing ran
- parse target count, parsed row count, warning/error counts, unsupported outcome count
- final ingestion outcome (`succeeded`, `partial`, `failed`, `no_op`)

This keeps unchanged-content checks and partial/deferred parse outcomes inspectable without introducing a second run model.

## Archive expansion

`ZipArchiveExpander` validates member paths to prevent traversal (`..` / zip-slip), stores each member as a durable artifact, and records `IngestArtifactMember` rows.

Grouped member support is based on shared basename (`group_key`) so multi-file formats (for example shapefile bundles) can route as a logical parse target.

## Parser registry contract

`ParserRegistry` routes by classified file kind.

The parser contract supports both single-file and grouped parse targets:

- `target_type=file` for direct artifacts or extracted members
- `target_type=grouped` for logical grouped bundles (for example shared-basename shapefile members)

Current built-ins:

- CSV/TSV parser
- GeoJSON parser
- XLSX parser (sheet/row provenance in parsed-record metadata)
- grouped shapefile parser (`.shp/.dbf/.shx` with optional `.prj/.cpg`)
- Access parser for `.mdb/.accdb` via dependency-aware `mdbtools` integration
- explicit unsupported handlers for `.xls`, `.xml`, file geodatabase classifications

Unsupported outcomes are explicit and observable (member/status and parsed warning/error rows), never silent.

Issue categories are machine-readable and persisted in `IngestParsedRecord.warnings_json`:

- `unsupported_format`
- `parser_not_installed`
- `not_implemented`
- `invalid_grouped_input`
- `parse_error`

### Dependency-aware behavior

- **Shapefile parser**
  - primary backend: `pyshp` (Python-native dependency)
  - if unavailable: emits `parser_not_installed` (does not crash run execution)
  - missing `.prj` is warning-only (`parse_error` warning code), parsing continues

- **Access parser**
  - backend: `mdbtools` CLI (`mdb-tables`, `mdb-export`)
  - commands are executed with argument lists (`shell=False` semantics) to avoid injection risk
  - if tools are missing: emits `parser_not_installed`
  - per-table export failures are warning-level `parse_error` issues (partial outputs preserved)
  - total table listing/read failure emits error-level `parse_error`

## Parsed output contract

`IngestParsedRecord` persists generic envelopes:

- `source_payload_json`
- `normalized_payload_json`
- `source_schema_json`
- `provenance_json`

For grouped parse targets, `provenance_json` includes grouped member ids/paths so one logical parse target can be traced back to all contributing members.

Idempotency behavior:

- parsed output rows use deterministic idempotency keys based on source connector, artifact content hash, member path/file name, parser name, record index, and normalized payload hash
- repeated runs with unchanged content do not create duplicate parsed rows
- unsupported/deferred/error outcomes persist deterministic warning/error rows with machine-readable issue categories

### Supported format matrix (current runtime)

- **Parsed**
  - `.csv`, `.tsv`
  - `.geojson`, JSON feature payloads
  - `.xlsx`
  - grouped shapefile bundles (`.shp + .dbf + .shx`, optional `.prj/.cpg`)
  - `.mdb`, `.accdb` (when `mdbtools` is installed)

- **Classified but not parsed**
  - `.xls` (`not_implemented`)
  - `.xml` (`unsupported_format`)
  - file geodatabase kinds (`not_implemented`)

This remains ingestion-scoped and intentionally app/domain-neutral.

## Adding new parsers

Add a parser class implementing `parse(target, stream) -> ParseOutcome`, register it in `build_default_registry()`, and include parser name/version plus normalization version in outputs.

No coordinator redesign should be needed for additional formats.
