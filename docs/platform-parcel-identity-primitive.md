# Platform Parcel Identity Primitive

The parcel identity primitive is a platform-level crosswalk layer for resolving source parcel identifiers into canonical parcel identities.

## What It Is

- Canonical parcel identity records (`ParcelCanonicalIdentity`)
- Typed alternate identifiers/aliases (`ParcelIdentifierAlias`)
- Durable source-to-canonical crosswalk outcomes (`ParcelCrosswalkMapping`)
- Resolver service (`xyn_orchestrator.parcel_identity.ParcelIdentityResolverService`) that:
  - resolves deterministically first
  - uses weaker fallback evidence when deterministic IDs are missing
  - persists unresolved/deferred outcomes for operator inspection

## What It Is Not

- Not a full domain parcel model for application business fields
- Not a replacement for `SourceMapping`
- Not a generic entity-resolution system for every object family

## Resolution Contract

Default resolver order:
1. Deterministic typed identifier match (`handle`, `parcel`, `cityblock`, `ref_id`, configured namespaces)
2. Deterministic composite match (for example `cityblock|parcel`)
3. Address-normalization fallback when an address alias already exists
4. Deferred geospatial fallback (explicitly marked deferred)
5. Unresolved (durably persisted, not dropped)

Each crosswalk stores:
- method (`resolution_method`)
- status (`resolved` / `unresolved` / `deferred` / `superseded`)
- confidence
- reason/explanation metadata
- idempotency key

## Provenance and Explainability

Crosswalk decisions are linked via canonical provenance:
- `ingest_adapted_record` -> `parcel_crosswalk_mapping` (`parcel_crosswalk_derived_from`)
- `parcel_crosswalk_mapping` -> `parcel_canonical_identity` (`parcel_crosswalk_resolved_to`) when resolved

The primitive can also reference `RecordMatchEvaluation` when pairwise match evidence is used by higher-level flows.

## Integration Boundaries

- Upstream input boundary: `IngestAdaptedRecord`
- Normalization seam: `xyn_orchestrator.matching.normalization`
- Geospatial seam: `xyn_orchestrator.geospatial` (extension point; not fully implemented in this pass)
- Provenance seam: `xyn_orchestrator.provenance`

## API Surfaces

- `GET /xyn/api/parcel-identities/lookup`
- `GET /xyn/api/parcel-identities/{parcel_id}`
- `GET /xyn/api/parcel-crosswalks`
- `POST /xyn/api/parcel-crosswalks/resolve-adapted`
- `POST /xyn/api/parcel-crosswalks/resolve-source`

## Known Limits (Current Pass)

- Geospatial fallback is represented as deferred outcome; no full geospatial resolver is added here.
- Alias conflict/supersession workflows are not fully automated yet.
- Canonical-identity merge tooling is deferred.
