from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Callable, ContextManager, Protocol

from .policy import DEFAULT_SRID
from .utils import BBox, Point

_IDENTIFIER_PART_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PostgisUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class SpatialTableRef:
    table_name: str
    id_column: str = "id"
    geometry_geojson_column: str = "geometry_geojson"
    geometry_srid_column: str = "geometry_srid"


@dataclass(frozen=True)
class PostgisStatus:
    installed: bool
    version: str = ""


class GeospatialRepository(Protocol):
    def postgis_status(self) -> PostgisStatus: ...

    def filter_ids_by_bbox(
        self,
        *,
        table: SpatialTableRef,
        bbox: BBox,
        srid: int = DEFAULT_SRID,
        limit: int | None = None,
    ) -> list[Any]: ...

    def filter_ids_by_polygon(
        self,
        *,
        table: SpatialTableRef,
        polygon_geojson: dict[str, Any],
        srid: int = DEFAULT_SRID,
        limit: int | None = None,
    ) -> list[Any]: ...

    def filter_ids_by_distance(
        self,
        *,
        table: SpatialTableRef,
        point: Point,
        radius_meters: float,
        srid: int = DEFAULT_SRID,
        limit: int | None = None,
    ) -> list[Any]: ...

    def filter_ids_contains_point(
        self,
        *,
        table: SpatialTableRef,
        point: Point,
        srid: int = DEFAULT_SRID,
        limit: int | None = None,
    ) -> list[Any]: ...

    def filter_ids_intersects(
        self,
        *,
        table: SpatialTableRef,
        geometry_geojson: dict[str, Any],
        srid: int = DEFAULT_SRID,
        limit: int | None = None,
    ) -> list[Any]: ...

    def compute_centroid(
        self,
        *,
        table: SpatialTableRef,
        record_id: Any,
        srid: int = DEFAULT_SRID,
    ) -> Point | None: ...


def _quote_ident(identifier: str) -> str:
    token = str(identifier or "").strip()
    if not token:
        raise ValueError("identifier is required")
    if "." in token:
        return ".".join(_quote_ident(part) for part in token.split("."))
    if not _IDENTIFIER_PART_PATTERN.match(token):
        raise ValueError(f"unsafe SQL identifier '{token}'")
    return f'"{token}"'


class PostgisGeospatialRepository:
    """
    Canonical PostGIS-backed geospatial implementation.

    This implementation is framework-neutral at the contract boundary and uses SQL
    directly so callers from Django or non-Django services can share semantics.
    """

    def __init__(self, *, cursor_provider: Callable[[], ContextManager[Any]]):
        self._cursor_provider = cursor_provider

    def postgis_status(self) -> PostgisStatus:
        with self._cursor_provider() as cursor:
            cursor.execute(
                "SELECT extversion FROM pg_extension WHERE extname = 'postgis' LIMIT 1"
            )
            row = cursor.fetchone()
        if not row:
            return PostgisStatus(installed=False, version="")
        return PostgisStatus(installed=True, version=str(row[0] or ""))

    def _require_postgis(self) -> None:
        status = self.postgis_status()
        if not status.installed:
            raise PostgisUnavailableError(
                "PostGIS extension is not installed on this database. "
                "Install/enable PostGIS before using the canonical geospatial repository."
            )

    def _geom_expr(self, table: SpatialTableRef, alias: str = "t") -> str:
        geo_col = _quote_ident(table.geometry_geojson_column)
        srid_col = _quote_ident(table.geometry_srid_column)
        return (
            f"ST_SetSRID(ST_GeomFromGeoJSON({alias}.{geo_col}::text), "
            f"COALESCE({alias}.{srid_col}, %s))"
        )

    def _base_select_ids_sql(self, table: SpatialTableRef) -> str:
        table_name = _quote_ident(table.table_name)
        id_column = _quote_ident(table.id_column)
        geo_col = _quote_ident(table.geometry_geojson_column)
        return (
            f"SELECT t.{id_column} "
            f"FROM {table_name} t "
            f"WHERE t.{geo_col} IS NOT NULL "
        )

    def _execute_id_query(self, sql_text: str, params: list[Any], limit: int | None = None) -> list[Any]:
        if limit is not None:
            sql_text = f"{sql_text} ORDER BY 1 LIMIT %s"
            params = [*params, int(limit)]
        with self._cursor_provider() as cursor:
            cursor.execute(sql_text, params)
            rows = cursor.fetchall()
        return [row[0] for row in rows]

    def filter_ids_by_bbox(
        self,
        *,
        table: SpatialTableRef,
        bbox: BBox,
        srid: int = DEFAULT_SRID,
        limit: int | None = None,
    ) -> list[Any]:
        self._require_postgis()
        geom = self._geom_expr(table)
        sql_text = (
            f"{self._base_select_ids_sql(table)} "
            f"AND ST_Intersects({geom}, ST_MakeEnvelope(%s, %s, %s, %s, %s))"
        )
        params = [srid, bbox.west, bbox.south, bbox.east, bbox.north, srid]
        return self._execute_id_query(sql_text, params, limit=limit)

    def filter_ids_by_polygon(
        self,
        *,
        table: SpatialTableRef,
        polygon_geojson: dict[str, Any],
        srid: int = DEFAULT_SRID,
        limit: int | None = None,
    ) -> list[Any]:
        self._require_postgis()
        geom = self._geom_expr(table)
        sql_text = (
            f"{self._base_select_ids_sql(table)} "
            f"AND ST_Intersects({geom}, ST_SetSRID(ST_GeomFromGeoJSON(%s), %s))"
        )
        params = [srid, json.dumps(polygon_geojson), srid]
        return self._execute_id_query(sql_text, params, limit=limit)

    def filter_ids_by_distance(
        self,
        *,
        table: SpatialTableRef,
        point: Point,
        radius_meters: float,
        srid: int = DEFAULT_SRID,
        limit: int | None = None,
    ) -> list[Any]:
        self._require_postgis()
        geom = self._geom_expr(table)
        sql_text = (
            f"{self._base_select_ids_sql(table)} "
            f"AND ST_DWithin("
            f"ST_Transform({geom}, 3857), "
            f"ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), %s), 3857), "
            f"%s)"
        )
        params = [srid, point.lon, point.lat, srid, float(radius_meters)]
        return self._execute_id_query(sql_text, params, limit=limit)

    def filter_ids_contains_point(
        self,
        *,
        table: SpatialTableRef,
        point: Point,
        srid: int = DEFAULT_SRID,
        limit: int | None = None,
    ) -> list[Any]:
        self._require_postgis()
        geom = self._geom_expr(table)
        sql_text = (
            f"{self._base_select_ids_sql(table)} "
            f"AND ST_Contains({geom}, ST_SetSRID(ST_MakePoint(%s, %s), %s))"
        )
        params = [srid, point.lon, point.lat, srid]
        return self._execute_id_query(sql_text, params, limit=limit)

    def filter_ids_intersects(
        self,
        *,
        table: SpatialTableRef,
        geometry_geojson: dict[str, Any],
        srid: int = DEFAULT_SRID,
        limit: int | None = None,
    ) -> list[Any]:
        self._require_postgis()
        geom = self._geom_expr(table)
        sql_text = (
            f"{self._base_select_ids_sql(table)} "
            f"AND ST_Intersects({geom}, ST_SetSRID(ST_GeomFromGeoJSON(%s), %s))"
        )
        params = [srid, json.dumps(geometry_geojson), srid]
        return self._execute_id_query(sql_text, params, limit=limit)

    def compute_centroid(
        self,
        *,
        table: SpatialTableRef,
        record_id: Any,
        srid: int = DEFAULT_SRID,
    ) -> Point | None:
        self._require_postgis()
        table_name = _quote_ident(table.table_name)
        id_column = _quote_ident(table.id_column)
        geom = self._geom_expr(table)
        sql_text = (
            f"SELECT ST_X(ST_Centroid({geom})), ST_Y(ST_Centroid({geom})) "
            f"FROM {table_name} t WHERE t.{id_column} = %s LIMIT 1"
        )
        with self._cursor_provider() as cursor:
            cursor.execute(sql_text, [srid, record_id])
            row = cursor.fetchone()
        if not row or row[0] is None or row[1] is None:
            return None
        return Point(lon=float(row[0]), lat=float(row[1]))

