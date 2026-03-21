# Platform Geocoding Enrichment Primitive

The geocoding enrichment primitive provides a reusable, provider-backed address enrichment layer that runs after source adaptation and before app-specific parcel/business logic.

## What It Is

- Durable geocode result sets (`GeocodeEnrichmentResult`) keyed to workspace/source/run/adapted-record scope
- Durable candidate rows (`GeocodeEnrichmentCandidate`) with scores, geometry, and provider attributes
- Provider abstraction seam (`xyn_orchestrator.geocoding.interfaces.GeocodeProvider`)
- ArcGIS REST geocoder provider implementation (`ArcGisGeocoderProvider`)
- Reusable execution service (`xyn_orchestrator.geocoding.service.GeocodingService`)

## What It Is Not

- Not a replacement for source adapters or source mapping
- Not parcel identity resolution itself
- Not app-specific scoring/business logic

## Execution Contract

1. Input boundary is `IngestAdaptedRecord`.
2. Address input is extracted from adapted payload using connector config hints.
3. Address is normalized using the platform normalization seam.
4. Configured provider is invoked.
5. All candidates are persisted; one selected candidate is chosen deterministically (`highest_score_then_rank`).
6. Failures/no-candidate/unconfigured outcomes are persisted as inspectable statuses.

Durable statuses:
- `selected`
- `no_selection`
- `no_candidates`
- `invalid_input`
- `provider_not_configured`
- `provider_error`
- `shape_error`

## Idempotency and Replay

Each result set stores an idempotency key/fingerprint derived from:
- adapted record identity
- normalized address
- provider identity
- provider endpoint/config params

Replays with the same fingerprint return existing results instead of duplicating rows.

## Provenance

Canonical provenance links are emitted:
- `ingest_adapted_record` -> `geocode_enrichment_result` (`geocode_enrichment_from_adapted`)
- `geocode_enrichment_result` -> `geocode_enrichment_candidate` (`geocode_selected_candidate`) when selected

Parcel crosswalk resolution may reference selected geocode evidence without invoking geocoding inline.

## Provider Configuration

Provider settings live on `SourceConnector.configuration_json`:

```json
{
  "geocoding": {
    "provider_kind": "arcgis_rest_geocoder",
    "url": "https://.../findAddressCandidates",
    "address_fields": ["record.address", "attributes.SITEADDR"],
    "params": { "outFields": "*" },
    "timeout_seconds": 15
  }
}
```

## API Surfaces

- `GET /xyn/api/geocoding/results`
- `GET /xyn/api/geocoding/results/{result_id}`
- `POST /xyn/api/geocoding/resolve-adapted`
- `POST /xyn/api/geocoding/resolve-source`

## Known Limits (Current Pass)

- ArcGIS REST geocoder is the first provider; additional providers are deferred.
- Selection policy is deterministic and simple; manual-review workflows are deferred.
- Provider authentication strategies beyond basic configured params are deferred.
