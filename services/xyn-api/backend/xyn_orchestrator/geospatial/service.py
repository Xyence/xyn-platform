from __future__ import annotations

from typing import Any

from .policy import DEFAULT_SRID
from .repository import GeospatialRepository, SpatialTableRef
from .utils import BBox, Point, ensure_srid, normalize_geometry


class GeospatialService:
    """
    Framework-neutral geospatial service boundary.

    DTO validation and SRID policy live here, with execution delegated to a
    repository implementation (PostGIS canonical, framework adapters optional).
    """

    def __init__(self, *, repository: GeospatialRepository, default_srid: int = DEFAULT_SRID):
        self._repository = repository
        self._default_srid = int(default_srid or DEFAULT_SRID)

    def postgis_status(self):
        return self._repository.postgis_status()

    def filter_ids_by_bbox(self, *, table: SpatialTableRef, bbox: BBox, srid: int = DEFAULT_SRID, limit: int | None = None) -> list[Any]:
        self._validate_srid(srid)
        self._validate_bbox(bbox)
        return self._repository.filter_ids_by_bbox(table=table, bbox=bbox, srid=srid, limit=limit)

    def filter_ids_by_polygon(
        self,
        *,
        table: SpatialTableRef,
        polygon_geojson: dict[str, Any],
        srid: int = DEFAULT_SRID,
        limit: int | None = None,
    ) -> list[Any]:
        self._validate_srid(srid)
        normalized = normalize_geometry(polygon_geojson)
        if normalized.get("type") not in {"Polygon", "MultiPolygon"}:
            raise ValueError("polygon filter requires Polygon or MultiPolygon geometry")
        return self._repository.filter_ids_by_polygon(table=table, polygon_geojson=normalized, srid=srid, limit=limit)

    def filter_ids_by_distance(
        self,
        *,
        table: SpatialTableRef,
        point: Point,
        radius_meters: float,
        srid: int = DEFAULT_SRID,
        limit: int | None = None,
    ) -> list[Any]:
        self._validate_srid(srid)
        if radius_meters <= 0:
            raise ValueError("radius_meters must be greater than zero")
        self._validate_point(point)
        return self._repository.filter_ids_by_distance(
            table=table,
            point=point,
            radius_meters=float(radius_meters),
            srid=srid,
            limit=limit,
        )

    def filter_ids_contains_point(
        self,
        *,
        table: SpatialTableRef,
        point: Point,
        srid: int = DEFAULT_SRID,
        limit: int | None = None,
    ) -> list[Any]:
        self._validate_srid(srid)
        self._validate_point(point)
        return self._repository.filter_ids_contains_point(table=table, point=point, srid=srid, limit=limit)

    def filter_ids_intersects(
        self,
        *,
        table: SpatialTableRef,
        geometry_geojson: dict[str, Any],
        srid: int = DEFAULT_SRID,
        limit: int | None = None,
    ) -> list[Any]:
        self._validate_srid(srid)
        normalized = normalize_geometry(geometry_geojson)
        return self._repository.filter_ids_intersects(table=table, geometry_geojson=normalized, srid=srid, limit=limit)

    def compute_centroid(self, *, table: SpatialTableRef, record_id: Any, srid: int = DEFAULT_SRID) -> Point | None:
        self._validate_srid(srid)
        return self._repository.compute_centroid(table=table, record_id=record_id, srid=srid)

    def _validate_srid(self, srid: int) -> None:
        ensure_srid({"type": "Point", "coordinates": [0.0, 0.0]}, srid=srid, default_srid=self._default_srid)

    @staticmethod
    def _validate_point(point: Point) -> None:
        if point.lon < -180.0 or point.lon > 180.0:
            raise ValueError("Point longitude must be within [-180, 180]")
        if point.lat < -90.0 or point.lat > 90.0:
            raise ValueError("Point latitude must be within [-90, 90]")

    @staticmethod
    def _validate_bbox(bbox: BBox) -> None:
        if bbox.west > bbox.east:
            raise ValueError("bbox.west must be less than or equal to bbox.east")
        if bbox.south > bbox.north:
            raise ValueError("bbox.south must be less than or equal to bbox.north")

