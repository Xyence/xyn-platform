# Panel-First UI Guardrails

Xyn capability UX is **panel-first**:

1. palette command
2. panel intent resolution
3. FlexLayout/workbench panel render

## Deprecated pattern

Legacy standalone route/page ownership (direct `AppShell` route + page business logic)
is deprecated for new capability work.

## Compatibility routes

Compatibility routes are allowed only as thin redirects into workbench panel state.
They must not own API loading, mutations, or workflow orchestration logic.

## Current focus areas

- Solutions / multi-artifact self-development
- Composer / planning flow
- Generated app shell surfaces

For these areas, add/extend:
- panel types/keys in workspace panel model/registry/factory
- palette command intent mappings
- panel-hosted components in workbench

before introducing any new route-level page behavior.
