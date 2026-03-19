# Platform Lifecycle Primitive

## Canonical home

The canonical platform lifecycle/state-machine primitive lives in `xyn-platform` under:
- `services/xyn-api/backend/xyn_orchestrator/lifecycle_primitive/`
- `xyn_orchestrator.models.LifecycleTransition`

`xyn/core` may retain temporary compatibility/integration code for kernel-local objects, but it is not the source of truth for platform lifecycle semantics.

## Scope

This primitive is intentionally lightweight:
- lifecycle definitions (states, initial state, legal transitions)
- transition validation
- durable transition history model (`LifecycleTransition`)

It is not a BPM engine and does not replace orchestration.

## Built-in lifecycle definitions (v1)

- `draft`: `draft -> ready/submitted/archived`, `ready -> draft/submitted/archived`, `submitted -> archived`
- `job`: `queued -> running/failed`, `running -> succeeded/failed`, `failed -> queued`

## Usage pattern

- Validate transitions using `xyn_orchestrator.lifecycle_primitive.validate_transition(...)`.
- Persist durable transition history in `LifecycleTransition`.
- Keep object-specific wiring in the owning subsystem (for example, source connectors, campaigns, drafts/jobs) while reusing the shared lifecycle contract.

## Boundary guidance

- New generic platform lifecycle logic should be added in this module, not in `xyn/core`.
- `xyn/core` lifecycle code should remain compatibility/integration only until fully retired.
