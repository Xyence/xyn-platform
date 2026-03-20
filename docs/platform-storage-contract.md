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

Use the canonical helper `prepare_ingest_run_metadata(...)` to attach this metadata. It will create the ingest workspace and return the metadata payload expected by the cleanup hooks.

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

Jurisdiction keys must use canonical, collision-safe format:
- lowercase, hyphen-separated
- explicit city vs county suffix (`-city`, `-county`)
- examples: `mo-stl-city`, `mo-stl-county`, `tx-travis-county`
- metadata/provenance payload

The durable metadata record is stored in `IngestArtifactRecord` and linked to provenance where possible.

## Provenance Expectation

When a source connector is present, the storage service records a provenance link:

- `source_connector -> runtime_artifact` (`relationship_type=ingest_snapshot`)

Downstream orchestration outputs should reference the artifact ID and change token where applicable.
The canonical snapshot contract is:

- `output_change_token = sha256(raw_snapshot)`
- `artifact_id` points at the durable runtime artifact
- output metadata includes `ingest_artifact_id` and `source_connector_id`

The orchestration lifecycle records provenance links for snapshot outputs:

- `runtime_artifact -> orchestration_job_output` (`relationship_type=ingest_snapshot_output`)
- `source_connector -> orchestration_job_output` when the source connector is known

## Inspectability

The control-plane API exposes ingest artifact metadata for operators:

- `GET /xyn/api/ingest-artifacts?workspace_id=...`
- `GET /xyn/api/ingest-artifacts/<id>?workspace_id=...`

These endpoints are gated by `app.ingest_runs.read` and return the durable metadata stored in `IngestArtifactRecord`.

## Follow-ons (Non-blocking)

These are intentionally deferred and tracked here to avoid scope creep:

- Multipart upload support for very large artifacts (beyond current streaming support)
- Explicit retention enforcement policies per retention class
- Expanded artifact browsing/UI for ingest artifacts
- Shared/team-level target storage scopes
- Cross-service artifact lifecycle management
