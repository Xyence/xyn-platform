# Solution Activation Runtime Binding

This note documents the minimal additive step that makes a `Solution` (`Application`) the canonical deployable unit while preserving artifact-first compatibility.

## Canonical deployable unit

- User-facing activation is `POST /xyn/api/applications/{application_id}/activate`.
- Activation resolves Solution composition from `ApplicationArtifactMembership`:
  - primary app artifact: prefers `primary_ui`, then `primary_api`, then first `app.*` member.
  - policy artifact: first `policy_bundle` member (when present).

## Runtime binding record

- `SolutionRuntimeBinding` stores the active/pending runtime linkage per `(workspace, application)`:
  - selected `primary_app_artifact`
  - selected `policy_artifact` (optional)
  - `runtime_instance` (optional while queued)
  - `activation_mode`: `composed` (policy artifact supplied) or `reconstructed` (policy rebuilt from app spec)
  - status + runtime target snapshot + last activation metadata

## Reuse semantics

- Sibling lifecycle remains unchanged and continues to rely on revision-anchor matching.
- Solution activation delegates to existing artifact activation and then records/refreshes `SolutionRuntimeBinding`.
- Artifact activation remains backward-compatible and independent.
  - Interaction rule: solution activation records the canonical solution binding; direct artifact activation does not implicitly rebind a solution.

## Readback API

- `GET /xyn/api/applications/{application_id}/runtime-binding` returns:
  - current resolved composition (`primary_app_artifact_ref`, `policy_artifact_ref`)
  - persisted runtime binding state (if present)

## Freshness semantics

- Runtime binding readback includes:
  - `freshness`: `current | stale_composition | stale_runtime | unknown`
  - `freshness_reason`: narrow machine-readable reason
- Rules:
  - `stale_composition`: recorded composition fingerprint differs from currently resolved Solution composition.
  - `stale_runtime`: binding is marked active but runtime instance/target no longer resolves as expected.
  - `current`: composition fingerprint matches and active runtime target resolves to the same sibling/runtime instance.
  - `unknown`: insufficient evidence (for example pending/error binding state or legacy binding metadata missing fingerprint).
