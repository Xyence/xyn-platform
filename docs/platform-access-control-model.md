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

- Add UI management for assigning canonical app roles via scoped bindings.
- Add finer row/partition policy checks where required (for example jurisdiction-level restrictions).
- Keep capability-to-endpoint coverage docs synchronized as new platform APIs are added.
- Align owner-scoped notification-target preference endpoints with workspace capability context when campaign/workspace-scoped target management UX is introduced.
