from __future__ import annotations

from typing import Any, Dict

from django.db.models import QuerySet

from .django_adapter import (
    filter_queryset_by_bbox,
    filter_queryset_by_distance,
    filter_queryset_by_polygon,
    filter_queryset_contains_point,
    filter_queryset_intersects,
)
from .policy import DEFAULT_GEOMETRY_FIELD_NAME
from .service import GeospatialService
from .utils import BBox, Point


def filter_by_bbox(
    queryset: QuerySet,
    bbox: BBox,
    *,
    prefix: str = "geometry",
    service: GeospatialService | None = None,
) -> QuerySet:
    return filter_queryset_by_bbox(
        queryset,
        bbox=bbox,
        service=service,
        geometry_field=f"{prefix}_geojson",
        srid_field=f"{prefix}_srid",
    )


def filter_contains_point(
    queryset: QuerySet,
    point: Point,
    *,
    geometry_field: str = DEFAULT_GEOMETRY_FIELD_NAME,
    prefix: str = "geometry",
    service: GeospatialService | None = None,
) -> QuerySet:
    return filter_queryset_contains_point(
        queryset,
        point=point,
        service=service,
        geometry_field=geometry_field,
        srid_field=f"{prefix}_srid",
    )


def filter_by_polygon(
    queryset: QuerySet,
    polygon: Dict[str, Any],
    *,
    geometry_field: str = DEFAULT_GEOMETRY_FIELD_NAME,
    prefix: str = "geometry",
    service: GeospatialService | None = None,
) -> QuerySet:
    return filter_queryset_by_polygon(
        queryset,
        polygon_geojson=polygon,
        service=service,
        geometry_field=geometry_field,
        srid_field=f"{prefix}_srid",
    )


def intersects(
    queryset: QuerySet,
    geometry: Dict[str, Any],
    *,
    geometry_field: str = DEFAULT_GEOMETRY_FIELD_NAME,
    prefix: str = "geometry",
    service: GeospatialService | None = None,
) -> QuerySet:
    return filter_queryset_intersects(
        queryset,
        geometry_geojson=geometry,
        service=service,
        geometry_field=geometry_field,
        srid_field=f"{prefix}_srid",
    )


def filter_by_distance(
    queryset: QuerySet,
    point: Point,
    radius_meters: float,
    *,
    prefix: str = "geometry",
    service: GeospatialService | None = None,
) -> QuerySet:
    return filter_queryset_by_distance(
        queryset,
        point=point,
        radius_meters=radius_meters,
        service=service,
        geometry_field=f"{prefix}_geojson",
        srid_field=f"{prefix}_srid",
    )
