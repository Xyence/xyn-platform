# Runtime Configuration Migration (Seed-Owned)

`xyn-api` now expects runtime configuration from injected process environment (owned by `xyn-seed`/compose).

## Canonical Inputs

- `XYN_ENV`
- `XYN_BASE_DOMAIN`
- `XYN_AUTH_MODE` (`simple|oidc`)
- `XYN_INTERNAL_TOKEN`
- `XYN_OIDC_ISSUER` / `XYN_OIDC_CLIENT_ID` / `XYN_OIDC_ALLOWED_DOMAINS`
- `XYN_AI_PROVIDER` / `XYN_AI_MODEL`
- `XYN_OPENAI_API_KEY` / `XYN_GEMINI_API_KEY` / `XYN_ANTHROPIC_API_KEY` (seed-owned AI key inputs)
- Optional purpose overlays:
  - `XYN_AI_PLANNING_PROVIDER` / `XYN_AI_PLANNING_MODEL` / `XYN_AI_PLANNING_API_KEY`
  - `XYN_AI_CODING_PROVIDER` / `XYN_AI_CODING_MODEL` / `XYN_AI_CODING_API_KEY`
- Managed storage roots:
  - `XYN_ARTIFACT_ROOT` for durable local artifact storage
  - `XYN_WORKSPACE_ROOT` for managed active coding/scratch workspaces
  - `XYN_WORKSPACE_RETENTION_DAYS` for stale-workspace cleanup eligibility

Current behavior:
- durable run/deployment artifacts are routed through the managed artifact root
- active codegen workspaces are materialized under the managed workspace root
- registered repository caches are materialized under `XYN_WORKSPACE_ROOT/repositories/cache`
- per-task repository working copies are materialized under the managed task workspace and cloned from that cache
- local durable artifact storage remains filesystem-backed today, with the storage seam left explicit for later object-storage support

## Compatibility Behavior

- In local/dev only, `backend/.env` is still loaded if present, with a deprecation warning.
- Legacy aliases remain supported:
  - `DOMAIN` -> `XYN_BASE_DOMAIN`
  - `XYENCE_INTERNAL_TOKEN` -> `XYN_INTERNAL_TOKEN`
  - `XYENCE_MEDIA_ROOT` / `XYENCE_ARTIFACT_ROOT` -> `XYN_ARTIFACT_ROOT`
  - `XYENCE_CODEGEN_WORKDIR` -> `XYN_WORKSPACE_ROOT`
  - other `XYENCE_*` operational variables are backfilled from canonical `XYN_*` values.

## Production Requirement

Production compose disables `env_file` loading and relies on injected env only.

## Auth Modes

- `simple` (default): no OIDC bearer verification path.
- `oidc`: OIDC bearer verification and social auth restrictions are enabled.
