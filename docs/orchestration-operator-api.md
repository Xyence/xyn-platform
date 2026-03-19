# Orchestration Operator API

This API provides operational visibility and intervention controls for platform operators.

Cron scheduling is intentionally unsupported in orchestration v1.
Do not use or imply cron scheduling until platform cron support is explicitly implemented and accepted.

Base path: `/xyn/api/orchestration`

All endpoints require authenticated user context and workspace membership.

## List job definitions

`GET /xyn/api/orchestration/jobs?workspace_id=<uuid>&pipeline_key=<key?>`

- Returns job definitions for the workspace (optionally scoped to a pipeline).
- Includes retry policy, concurrency policy fields, partition flags, artifact declaration metadata, and handler binding.

## List schedules

`GET /xyn/api/orchestration/schedules?workspace_id=<uuid>&pipeline_key=<key?>&job_key=<key?>`

- Returns schedule rows with interval/cron settings, next/last fire timestamps, and metadata.
- Response includes:
  - `supported_schedule_kinds` (`manual`, `interval`)
  - `unsupported_schedule_kinds` (`cron`)
  - per-row `supported_in_v1` boolean

## Inspect dependency graph

`GET /xyn/api/orchestration/dependency-graph?workspace_id=<uuid>&pipeline_key=<key>`

- Returns graph nodes (jobs) and edges (`upstream_job_key -> downstream_job_key`).

## View recent runs with filters

`GET /xyn/api/orchestration/runs?...`

Required:
- `workspace_id`

Optional filters:
- `pipeline_key`
- `job_key`
- `run_type`
- `status`
- `trigger_cause`
- `created_after`
- `created_before`
- `jurisdiction`
- `source`
- `correlation_id`
- `chain_id`
- `failed_or_stale=true`
- `limit` (default 100, max 500)

## Inspect a single run

`GET /xyn/api/orchestration/runs/<run_id>?workspace_id=<uuid>`

Includes:
- run summary/status/timestamps/metrics/errors
- `run_type` and `target_ref`
- dependency context map
- per-job run rows
- attempts
- output/artifact metadata

## Manual trigger

`POST /xyn/api/orchestration/runs`

Body:
```json
{
  "workspace_id": "<uuid>",
  "pipeline_key": "sample_data_sync",
  "trigger_key": "manual_operator",
  "jurisdiction": "tx",
  "source": "mls",
  "parameters": {"force_refresh": "true"},
  "metadata": {"correlation_id": "corr-1", "chain_id": "chain-1"}
}
```

Creates a manual run and emits audit event `orchestration_manual_trigger`.

## Manual rerun

`POST /xyn/api/orchestration/runs/<run_id>/rerun`

Body:
```json
{"workspace_id":"<uuid>"}
```

Creates a retry-cause child run and emits audit event `orchestration_manual_rerun`.

## Cancel a pending/queued run

`POST /xyn/api/orchestration/runs/<run_id>/cancel`

Body:
```json
{"workspace_id":"<uuid>","summary":"operator cancel"}
```

Behavior:
- allowed only when run status is `pending` or `queued`
- marks run and pending/queued job runs as `cancelled`
- emits audit event `orchestration_run_cancelled`

## Acknowledge operator-visible failure

`POST /xyn/api/orchestration/runs/<run_id>/ack-failure`

Body:
```json
{"workspace_id":"<uuid>","note":"investigating"}
```

Behavior:
- allowed for `failed` and `stale` runs
- writes operator acknowledgement metadata
- emits audit event `orchestration_failure_acknowledged`
- sends failure notification via existing app notification subsystem to workspace admin/moderator operators when recipients are available

## Operator workflow summary

1. Discover definitions/schedules/dependencies via `/jobs`, `/schedules`, `/dependency-graph`.
2. Monitor runs via `/runs` filters (including failed/stale views).
3. Inspect run internals via `/runs/<id>`.
4. Intervene with manual trigger/rerun/cancel/ack-failure endpoints as needed.
