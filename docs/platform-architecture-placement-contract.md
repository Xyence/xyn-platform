# Platform Architecture Placement Contract (v1)

This contract defines how Xyn places new capability during self-development.

Policy version: `xyn.architecture_placement.v1`

## Purpose

Prevent core-code bloat by keeping provider-specific implementations out of
core when a capability is provider-extensible.

## Canonical placement rules

1. Core MAY contain:
- orchestration/state-machine coordination
- provider-neutral interfaces and lifecycle contracts
- artifact discovery, activation, and binding coordination
- shared schema/model contracts

2. Core MUST NOT accumulate provider-specific implementation logic for
provider-extensible capability domains.

3. Provider-specific behavior SHOULD live in provider artifacts/modules, behind
provider-neutral core seams.

4. Placement decision order for new extensible capability:
- extend existing provider-neutral abstraction
- create a minimal provider-neutral abstraction in core if missing
- implement provider behavior in artifact/module boundary

## Deployment/provider test case

Deployment is the first enforced domain:
- provider-neutral coordination remains in core
- provider-specific deployment/provisioning/DNS logic should move to provider
  artifacts/modules over time
- current legacy core execution remains allowed only in approved boundary files
  until decomposition completes

## Machine-usable hooks

The backend exposes placement helpers for planner/self-development workflows:
- `xyn_orchestrator.architecture_placement.evaluate_architectural_placement`
- `xyn_orchestrator.architecture_placement.deployment_provider_contract_summary`

Impacted-artifact analysis now includes `placement_guidance` so planners and
operator contracts can consume this policy without UI-specific logic.
