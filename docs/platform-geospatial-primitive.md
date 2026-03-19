# Platform Geospatial Primitive (v1)

## Purpose
`xyn_orchestrator.geospatial` is a thin platform primitive that standardizes geometry storage and reusable spatial filtering helpers.

PostgreSQL + PostGIS is the canonical spatial execution backend for v1.

It is intentionally small and composable.

## What It Is Not
- Not a full GIS platform
- Not an app-specific geospatial model
- Not a Deal Finder workflow implementation

## Architecture Contract
- Canonical contract is framework-neutral:
  - DTOs: `SpatialFilter`, `RadiusFilter`, geometry helpers
  - service: `GeospatialService`
  - repository interface: `GeospatialRepository`
- Canonical implementation: `PostgisGeospatialRepository` (SQL/PostGIS-backed)
- Django integration is adapter-level convenience:
  - `xyn_orchestrator.geospatial.django_adapter`
  - `xyn_orchestrator.geospatial.query` wrappers

Do not treat Django model field semantics as the canonical geospatial platform API.

## v1 Geometry Convention
- Canonical geometry field: `geometry_geojson` (GeoJSON object)
- Canonical SRID field: `geometry_srid`
- Default SRID: `4326`
- Canonical geometry type field: `geometry_type`
- Derived bbox fields:
  - `geometry_bbox_west`
  - `geometry_bbox_south`
  - `geometry_bbox_east`
  - `geometry_bbox_north`
- Derived centroid fields:
  - `geometry_centroid_lon`
  - `geometry_centroid_lat`

Use `SpatialModelMixin` to apply this convention for new spatial-enabled models in Django-managed persistence.

## Supported Geometry Types
- `Point`
- `LineString` (optional but supported)
- `Polygon`
- `MultiPolygon`

## SRID Policy
- v1 supports SRID `4326` only.
- Implicit reprojection is not performed.
- Unsupported SRIDs fail with an explicit validation error.

## Canonical Spatial Filter Contract
Use `SpatialFilter.from_payload(...)` for API payload parsing.

Supported shapes:
- `bbox`
```json
{
  "bbox": { "west": -98.0, "south": 29.0, "east": -94.0, "north": 33.0 }
}
```
- `polygon`
```json
{
  "polygon": { "type": "Polygon", "coordinates": [[[-97,30],[-95,30],[-95,32],[-97,32],[-97,30]]] }
}
```
- `radius`
```json
{
  "radius": { "point": { "lon": -96.0, "lat": 31.0 }, "meters": 5000 }
}
```

## Query Helpers
Framework-neutral service + repository:
- `GeospatialService.filter_ids_by_bbox(...)`
- `GeospatialService.filter_ids_contains_point(...)`
- `GeospatialService.filter_ids_by_polygon(...)`
- `GeospatialService.filter_ids_by_distance(...)`
- `GeospatialService.filter_ids_intersects(...)`

Django adapter wrappers:
- `filter_by_bbox(queryset, bbox)`
- `filter_contains_point(queryset, point)`
- `filter_by_polygon(queryset, polygon)`
- `filter_by_distance(queryset, point, radius_meters)`
- `intersects(queryset, geometry)`

These wrappers call the framework-neutral service, which delegates to PostGIS repository behavior.

## Geometry Utilities
`xyn_orchestrator.geospatial.utils` provides:
- `normalize_geometry(...)`
- `to_geojson(...)`
- `from_geojson(...)`
- `compute_centroid(...)`
- `extract_bbox(...)`
- `ensure_srid(...)`
- `point_in_polygon(...)`
- `polygon_intersects(...)`

## Indexing and Safe Query Patterns
- Spatial-enabled models should index bbox and centroid fields.
- For PostGIS-backed tables, add GiST indexes around canonical geometry expressions used in repository queries.
- Prefer service/repository helpers over per-app reimplementation.

## Runtime Readiness
- PostGIS extension must be installed and enabled in the active database.
- `PostgisGeospatialRepository` checks extension availability and fails loudly if unavailable.
- Local/dev runtime is provisioned with `postgis/postgis:16-3.4` in `xyn/compose.yml`.
- `xynctl start` now enforces PostGIS enablement (`CREATE EXTENSION IF NOT EXISTS postgis`) and verifies a spatial SQL sanity query.

### Local/Dev Enablement
From `xyn` repo:

```bash
docker compose up -d postgres
./xynctl start
```

### Verify PostGIS
```bash
docker compose exec -T postgres psql -U xyn -d xyn -c "SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name='postgis') AS postgis_available, EXISTS (SELECT 1 FROM pg_extension WHERE extname='postgis') AS postgis_installed;"
docker compose exec -T postgres psql -U xyn -d xyn -c "SELECT postgis_full_version();"
docker compose exec -T postgres psql -U xyn -d xyn -c "SELECT ST_AsText(ST_SetSRID(ST_MakePoint(0,0),4326));"
```

## TODO (v2+)
- Optional nearest-neighbor helper for large datasets.
- Optional explicit reprojection support beyond SRID 4326.
- Add migration/ops playbook for upgrading local/dev database images to PostGIS-enabled variants.
- Add optional GeoDjango convenience adapter docs (explicitly non-canonical).
- Add non-Django service adapter examples (FastAPI worker/runtime consumption) for the same contract.
