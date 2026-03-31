# Installable Solution Bundles (v1)

`xyn-platform` now supports an installable solution bundle contract for durable restore/install of Solution + Artifact composition into a workspace.

## Bundle schema

`schema_version: xyn.solution_bundle.v1`

Top-level fields:

- `solution`: durable solution identity (`slug`, `name`, optional `description`)
- `artifacts.primary_app`: pinned primary app artifact revision (`type=application`, `slug`, optional `version`)
- `artifacts.policy`: optional pinned policy artifact (`type=policy_bundle`)
- `artifacts.supporting[]`: optional supporting artifacts
- membership role per artifact (`role`, defaults: `primary_ui` for app, `supporting` otherwise)
- optional `package_source` per artifact (`package://<id>`, file path, `s3://bucket/key`) for missing-artifact install
- optional `bootstrap` settings:
  - `bind_workspace_artifacts` (default `true`)
  - `enable_bindings` (default `true`)
  - `application_status` (default `active`)
  - `source_factory_key` (default `solution_bundle_install`)
  - `metadata` (optional)

## Install behavior

Install path is idempotent and additive:

1. Normalize and validate bundle.
2. Resolve/create `Application`.
3. Resolve/install artifacts (from workspace, or package source if absent).
4. Upsert `ApplicationArtifactMembership`.
5. Upsert `WorkspaceArtifactBinding` when enabled.

Policy compatibility behavior remains backward compatible:

- if policy artifact resolves: `policy_source=artifact`
- if policy is missing/optional: `policy_source=reconstructed` with warnings

Activation semantics for installed solutions:

- solution activation picks a primary application artifact membership deterministically
  - role precedence: `primary_ui`, then `primary_api`, then stable membership order
- when the pinned policy artifact is present and valid, activation uses it directly (`policy_source=artifact`)
- when policy is absent/unavailable/invalid, activation falls back to reconstruction (`policy_source=reconstructed`)
- activation responses include observability fields:
  - `solution_slug`
  - `artifact_ref`
  - `policy_artifact_ref`
  - `policy_source`
  - `install_source`

## Sources

- Local file: `/path/to/bundle.json` or `file:///path/to/bundle.json`
- Artifact package store: `package://<artifact_package_id>`
- S3: `s3://bucket/key` (JSON bundle payload)

## API and command

- API: `POST /xyn/api/solutions/install-bundle`
  - accepts `{ "bundle": { ... } }` or `{ "source": "<uri>" }`
- Command: `python manage.py install_solution_bundle --workspace-slug <slug> --source <uri>`
  - supports repeated `--source`
  - supports env list: `--from-env` + `XYN_SOLUTION_BUNDLE_SOURCES`

## Startup bootstrap from `.env`

Automatic startup install/reinstall is supported through env vars:

- `XYN_BOOTSTRAP_INSTALL_SOLUTIONS`
  - comma-separated solution slugs (for example: `deal-finder,claims-hub`)
- `XYN_BOOTSTRAP_SOLUTION_SOURCE`
  - `local` or `s3`
- `XYN_BOOTSTRAP_SOLUTION_BUCKET`
  - required when source is `s3`
- `XYN_BOOTSTRAP_SOLUTION_PREFIX`
  - local directory path (`local`) or key prefix (`s3`)
- `XYN_BOOTSTRAP_SOLUTION_VERSION` (optional)
  - pin startup installs to `<solution>/<version>/manifest.json`
- `XYN_BOOTSTRAP_IF_MISSING_ONLY`
  - `true` (default): only install when solution missing
  - `false`: always reinstall/update on startup
- `XYN_BOOTSTRAP_SOLUTION_WORKSPACE_SLUG` (optional)
  - target workspace slug for bootstrap installs (defaults to `XYN_WORKSPACE_SLUG` or `development`)

### Local dev example

```bash
XYN_BOOTSTRAP_INSTALL_SOLUTIONS=deal-finder
XYN_BOOTSTRAP_SOLUTION_SOURCE=local
XYN_BOOTSTRAP_SOLUTION_PREFIX=/app/.xyn/solution-bundles
XYN_BOOTSTRAP_IF_MISSING_ONLY=true
XYN_BOOTSTRAP_SOLUTION_WORKSPACE_SLUG=development
```

Expected local bundle path for `deal-finder`:

- default: `/app/.xyn/solution-bundles/deal-finder/manifest.json`
- legacy compatibility: `/app/.xyn/solution-bundles/deal-finder.json`

### S3 example

```bash
XYN_BOOTSTRAP_INSTALL_SOLUTIONS=deal-finder
XYN_BOOTSTRAP_SOLUTION_SOURCE=s3
XYN_BOOTSTRAP_SOLUTION_BUCKET=my-xyn-bundles
XYN_BOOTSTRAP_SOLUTION_PREFIX=solutions
XYN_BOOTSTRAP_SOLUTION_VERSION=v2026-03-31
XYN_BOOTSTRAP_IF_MISSING_ONLY=true
XYN_BOOTSTRAP_SOLUTION_WORKSPACE_SLUG=development
```

Expected manifest key:

`s3://my-xyn-bundles/solutions/deal-finder/v2026-03-31/manifest.json`

### Example S3 layout

```text
s3://my-xyn-bundles/solutions/
  deal-finder/
    v2026-03-31/
      manifest.json
      app-package.tgz
      policy-package.tgz
      supporting/
        supporting-analytics.tgz
```

Package payload keys in `manifest.json` can be relative (for example `app-package.tgz`). The loader resolves these against the manifest directory and fetches bytes from S3; installer logic then idempotently imports package bytes and upserts `Application`/`ApplicationArtifactMembership`/workspace bindings.

## Operational expectations

- Rebuild/redeploy:
  - bundle bootstrap re-runs safely; installs are idempotent by solution slug + artifact memberships
- Reinstall:
  - set `XYN_BOOTSTRAP_IF_MISSING_ONLY=false` to force reinstall/update on startup
- Activation after reinstall:
  - activation keeps using pinned composition when available and reports `install_source` for auditability
- Stale runtime target recreation:
  - activation reuse is liveness-gated; stale runtime targets are rejected and queued for recovery/provisioning
