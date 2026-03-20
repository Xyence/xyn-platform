# Platform Storage Contract (Ingest + Snapshots)

This document defines the canonical storage and file-handling contract for DealFinder-era ingest workflows.

## Scope

This is a thin, reusable storage abstraction for:

- durable ingest artifacts (raw snapshots, normalized outputs, retained parser results)
- ingest-scoped temporary workspaces (extract/transform scratch)
- metadata/provenance linkage between sources, runs, and artifacts

This is not a full ETL framework or a replacement for orchestration/run history.

## Canonical Durable Store

Durable ingest artifacts must be stored through the runtime artifact store (xyn-core), with local FS only as a dev fallback.

Uploads are streamed to the artifact store to avoid full-memory buffering for large files.

Implementation entrypoint:
- `xyn_orchestrator.storage.get_durable_artifact_store`
- `xyn_orchestrator.storage.IngestStorageService`

Configuration:
- `XYN_PLATFORM_DURABLE_ARTIFACT_PROVIDER=core|local` (default: `core`)
- `XYN_CORE_BASE_URL` controls the runtime artifact API base URL.

## Ingest-Scoped Workspaces

Ingest workspaces are always created under the managed workspace root and are eligible for cleanup.

Implementation entrypoint:
- `xyn_orchestrator.storage.IngestWorkspaceManager`

If orchestration should automatically clean up a workspace on run completion, include metadata on the run:

```
"ingest_workspace": {
  "source_key": "<source-identifier>",
  "run_key": "<run-id>",
  "retention_class": "ephemeral"
}
```

Retention classes other than `ephemeral` skip automatic cleanup.

## Metadata Contract

Every ingest artifact persisted through the storage service records:

- workspace id
- source connector id (optional)
- orchestration run/job-run (optional)
- content type, byte length, sha256
- storage provider + key + URI
- snapshot type (`raw`, `normalized`, `reconciled`, `signals`, `derived`)
- retention class (`ephemeral`, `snapshot`, `published`)
- partition scope (`jurisdiction`, `source`)
- metadata/provenance payload

The durable metadata record is stored in `IngestArtifactRecord` and linked to provenance where possible.

## Provenance Expectation

When a source connector is present, the storage service records a provenance link:

- `source_connector -> runtime_artifact` (`relationship_type=ingest_snapshot`)

Downstream orchestration outputs should reference the artifact ID and change token where applicable.

## Follow-ons (Non-blocking)

These are intentionally deferred and tracked here to avoid scope creep:

- Streamed upload support in xyn-core (avoid loading full payload into memory)
- Explicit retention enforcement policies per retention class
- Expanded artifact browsing/UI for ingest artifacts
- Shared/team-level target storage scopes
- Cross-service artifact lifecycle management
