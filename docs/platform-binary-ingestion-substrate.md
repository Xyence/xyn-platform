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

## Archive expansion

`ZipArchiveExpander` validates member paths to prevent traversal (`..` / zip-slip), stores each member as a durable artifact, and records `IngestArtifactMember` rows.

Grouped member support is based on shared basename (`group_key`) so multi-file formats (for example shapefile bundles) can route as a logical parse target.

## Parser registry contract

`ParserRegistry` routes by classified file kind.

Current built-ins:

- CSV/TSV parser
- GeoJSON parser
- grouped shapefile placeholder parser (explicit unsupported warning)

Unsupported formats are explicit and observable (member/status and warning outputs), never silent.

## Parsed output contract

`IngestParsedRecord` persists generic envelopes:

- `source_payload_json`
- `normalized_payload_json`
- `source_schema_json`
- `provenance_json`

This remains ingestion-scoped and intentionally app/domain-neutral.

## Adding new parsers

Add a parser class implementing `parse(target, stream) -> ParseOutcome`, register it in `build_default_registry()`, and include parser name/version plus normalization version in outputs.

No coordinator redesign should be needed for additional formats.
