# Platform Access Control Model (Canonical v1)

This is the canonical role/capability model for DealFinder-era platform/app authorization.

## Canonical home

- Canonical implementation: `services/xyn-api/backend/xyn_orchestrator/app_authorization.py`
- Canonical enforcement seam: workspace-scoped capability checks in `xyn_orchestrator.xyn_api`

`xyn/core` access helpers are compatibility/runtime-only for `xyn` surfaces and are not the source of truth for new platform primitives.

## Canonical roles

- `application_admin`
- `campaign_operator`
- `read_only_analyst`

## Capability-first enforcement

Use capabilities at endpoint/service boundaries instead of role-name conditionals.

Primary capability families:

- Source/admin operations: `app.sources.manage`, `app.jurisdictions.manage`, `app.mappings.inspect`, `app.refreshes.run`, `app.datasets.publish`
- Campaign/watch operations: `app.campaigns.manage`, `app.watches.manage`, `app.subscribers.manage`, `app.notification_targets.manage`
- Read/review operations: `app.read`, `app.ingest_runs.read`, `app.failures.read`, `app.matches.review`, `app.signals.review`, `app.notifications.read`, `app.campaign_history.read`

## Scope model

- Workspace membership role maps to default app role.
- Platform roles can elevate app role.
- Explicit role bindings at `workspace` or `application` scope can directly assign canonical app roles.
- Notification target + preference management uses a workspace context for capability checks while preserving owner-scoped target storage.

## Role mapping defaults

- Workspace role mapping:
  - `admin`/`publisher`/`moderator` -> `application_admin`
  - `contributor` -> `campaign_operator`
  - `reader` -> `read_only_analyst`
- Platform role mapping:
  - `platform_owner`/`platform_admin`/`platform_architect` -> `application_admin`
  - `platform_operator` -> `campaign_operator`
  - `app_user` -> `read_only_analyst`

## Follow-up TODOs

## Post-DealFinder Authorization Follow-ons (Non-blocking)

- UI capability source of truth: surface canonical capability payloads to the UI and replace workspace-role heuristics with capability-driven gating.
- UI validation/build: clean up root-owned `tsconfig.tsbuildinfo` in `apps/xyn-ui` and run full `npm run build` in CI.
- Notification target model evolution: consider shared/team-scoped delivery targets instead of owner-only targets (optional enhancement).
- Finer-grained authorization: add row/partition/jurisdiction-level policy checks in service/repository paths (post-testing hardening).
- Role assignment/identity integration: persist role assignments, add UI management, and map IdP/OIDC claims to canonical roles (post-testing hardening).
- Legacy endpoint alignment: migrate remaining ad hoc auth patterns (for example legacy runtime run APIs) onto canonical capabilities (post-testing hardening).
