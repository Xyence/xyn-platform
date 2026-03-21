from __future__ import annotations

from typing import Any

from django.db import connections
from django.db.models import QuerySet

from .policy import DEFAULT_GEOMETRY_FIELD_NAME, DEFAULT_GEOMETRY_SRID_FIELD_NAME, DEFAULT_SRID
from .repository import PostgisGeospatialRepository, SpatialTableRef
from .service import GeospatialService
from .utils import BBox, Point


def django_postgis_repository(*, using: str = "default") -> PostgisGeospatialRepository:
    return PostgisGeospatialRepository(cursor_provider=lambda: connections[using].cursor())


def django_geospatial_service(*, using: str = "default") -> GeospatialService:
    return GeospatialService(repository=django_postgis_repository(using=using), default_srid=DEFAULT_SRID)


def table_ref_from_queryset(
    queryset: QuerySet,
    *,
    geometry_field: str = DEFAULT_GEOMETRY_FIELD_NAME,
    srid_field: str = DEFAULT_GEOMETRY_SRID_FIELD_NAME,
) -> SpatialTableRef:
    model = queryset.model
    return SpatialTableRef(
        table_name=str(model._meta.db_table),
        id_column=str(model._meta.pk.column),
        geometry_geojson_column=str(geometry_field),
        geometry_srid_column=str(srid_field),
    )


def queryset_from_ids(queryset: QuerySet, *, ids: list[Any]) -> QuerySet:
    if not ids:
        return queryset.none()
    return queryset.filter(pk__in=ids)


def filter_queryset_by_bbox(
    queryset: QuerySet,
    *,
    bbox: BBox,
    srid: int = DEFAULT_SRID,
    service: GeospatialService | None = None,
    geometry_field: str = DEFAULT_GEOMETRY_FIELD_NAME,
    srid_field: str = DEFAULT_GEOMETRY_SRID_FIELD_NAME,
    limit: int | None = None,
) -> QuerySet:
    svc = service or django_geospatial_service(using=str(queryset.db))
    ids = svc.filter_ids_by_bbox(
        table=table_ref_from_queryset(queryset, geometry_field=geometry_field, srid_field=srid_field),
        bbox=bbox,
        srid=srid,
        limit=limit,
    )
    return queryset_from_ids(queryset, ids=ids)


def filter_queryset_by_polygon(
    queryset: QuerySet,
    *,
    polygon_geojson: dict[str, Any],
    srid: int = DEFAULT_SRID,
    service: GeospatialService | None = None,
    geometry_field: str = DEFAULT_GEOMETRY_FIELD_NAME,
    srid_field: str = DEFAULT_GEOMETRY_SRID_FIELD_NAME,
    limit: int | None = None,
) -> QuerySet:
    svc = service or django_geospatial_service(using=str(queryset.db))
    ids = svc.filter_ids_by_polygon(
        table=table_ref_from_queryset(queryset, geometry_field=geometry_field, srid_field=srid_field),
        polygon_geojson=polygon_geojson,
        srid=srid,
        limit=limit,
    )
    return queryset_from_ids(queryset, ids=ids)


def filter_queryset_contains_point(
    queryset: QuerySet,
    *,
    point: Point,
    srid: int = DEFAULT_SRID,
    service: GeospatialService | None = None,
    geometry_field: str = DEFAULT_GEOMETRY_FIELD_NAME,
    srid_field: str = DEFAULT_GEOMETRY_SRID_FIELD_NAME,
    limit: int | None = None,
) -> QuerySet:
    svc = service or django_geospatial_service(using=str(queryset.db))
    ids = svc.filter_ids_contains_point(
        table=table_ref_from_queryset(queryset, geometry_field=geometry_field, srid_field=srid_field),
        point=point,
        srid=srid,
        limit=limit,
    )
    return queryset_from_ids(queryset, ids=ids)


def filter_queryset_by_distance(
    queryset: QuerySet,
    *,
    point: Point,
    radius_meters: float,
    srid: int = DEFAULT_SRID,
    service: GeospatialService | None = None,
    geometry_field: str = DEFAULT_GEOMETRY_FIELD_NAME,
    srid_field: str = DEFAULT_GEOMETRY_SRID_FIELD_NAME,
    limit: int | None = None,
) -> QuerySet:
    svc = service or django_geospatial_service(using=str(queryset.db))
    ids = svc.filter_ids_by_distance(
        table=table_ref_from_queryset(queryset, geometry_field=geometry_field, srid_field=srid_field),
        point=point,
        radius_meters=radius_meters,
        srid=srid,
        limit=limit,
    )
    return queryset_from_ids(queryset, ids=ids)


def filter_queryset_intersects(
    queryset: QuerySet,
    *,
    geometry_geojson: dict[str, Any],
    srid: int = DEFAULT_SRID,
    service: GeospatialService | None = None,
    geometry_field: str = DEFAULT_GEOMETRY_FIELD_NAME,
    srid_field: str = DEFAULT_GEOMETRY_SRID_FIELD_NAME,
    limit: int | None = None,
) -> QuerySet:
    svc = service or django_geospatial_service(using=str(queryset.db))
    ids = svc.filter_ids_intersects(
        table=table_ref_from_queryset(queryset, geometry_field=geometry_field, srid_field=srid_field),
        geometry_geojson=geometry_geojson,
        srid=srid,
        limit=limit,
    )
    return queryset_from_ids(queryset, ids=ids)

