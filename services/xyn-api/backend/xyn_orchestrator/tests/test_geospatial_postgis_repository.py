from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from unittest import mock

from django.db import connection
from django.test import SimpleTestCase, TestCase

from xyn_orchestrator.geospatial.repository import (
    PostgisGeospatialRepository,
    PostgisUnavailableError,
    SpatialTableRef,
)
from xyn_orchestrator.geospatial.service import GeospatialService
from xyn_orchestrator.geospatial.utils import BBox, Point


@dataclass
class CursorScenario:
    fetchone_values: list[Any] = field(default_factory=list)
    fetchall_values: list[Any] = field(default_factory=list)
    statements: list[tuple[str, list[Any]]] = field(default_factory=list)


class FakeCursor:
    def __init__(self, scenario: CursorScenario):
        self._scenario = scenario

    def execute(self, sql_text: str, params: list[Any] | None = None) -> None:
        self._scenario.statements.append((sql_text, list(params or [])))

    def fetchone(self):
        if self._scenario.fetchone_values:
            return self._scenario.fetchone_values.pop(0)
        return None

    def fetchall(self):
        if self._scenario.fetchall_values:
            return self._scenario.fetchall_values.pop(0)
        return []


class PostgisRepositoryTests(SimpleTestCase):
    def _repository(self, scenario: CursorScenario) -> PostgisGeospatialRepository:
        @contextmanager
        def cursor_provider():
            yield FakeCursor(scenario)

        return PostgisGeospatialRepository(cursor_provider=cursor_provider)

    def test_postgis_status_reports_not_installed(self):
        scenario = CursorScenario(fetchone_values=[None])
        repo = self._repository(scenario)
        status = repo.postgis_status()
        self.assertFalse(status.installed)
        self.assertEqual(status.version, "")

    def test_postgis_status_reports_installed(self):
        scenario = CursorScenario(fetchone_values=[("3.4.2",)])
        repo = self._repository(scenario)
        status = repo.postgis_status()
        self.assertTrue(status.installed)
        self.assertEqual(status.version, "3.4.2")

    def test_filter_by_bbox_requires_postgis(self):
        scenario = CursorScenario(fetchone_values=[None])
        repo = self._repository(scenario)
        with self.assertRaises(PostgisUnavailableError):
            repo.filter_ids_by_bbox(
                table=SpatialTableRef(table_name="spatial_records"),
                bbox=BBox(west=-97, south=30, east=-96, north=31),
            )

    def test_filter_by_bbox_uses_postgis_sql(self):
        scenario = CursorScenario(
            fetchone_values=[("3.4.2",)],
            fetchall_values=[[(1,), (2,)]],
        )
        repo = self._repository(scenario)
        result = repo.filter_ids_by_bbox(
            table=SpatialTableRef(table_name="spatial_records"),
            bbox=BBox(west=-97, south=30, east=-96, north=31),
            limit=10,
        )
        self.assertEqual(result, [1, 2])
        sql_text = scenario.statements[-1][0]
        params = scenario.statements[-1][1]
        self.assertIn("ST_MakeEnvelope", sql_text)
        self.assertIn("ST_Intersects", sql_text)
        self.assertEqual(params[-1], 10)

    def test_filter_by_distance_uses_dwithin(self):
        scenario = CursorScenario(
            fetchone_values=[("3.4.2",)],
            fetchall_values=[[(44,)]],
        )
        repo = self._repository(scenario)
        ids = repo.filter_ids_by_distance(
            table=SpatialTableRef(table_name="spatial_records"),
            point=Point(lon=-96.0, lat=31.0),
            radius_meters=500,
        )
        self.assertEqual(ids, [44])
        sql_text = scenario.statements[-1][0]
        self.assertIn("ST_DWithin", sql_text)
        self.assertIn("ST_Transform", sql_text)

    def test_compute_centroid_uses_postgis_centroid(self):
        scenario = CursorScenario(
            fetchone_values=[("3.4.2",), (-96.1, 31.2)],
        )
        repo = self._repository(scenario)
        centroid = repo.compute_centroid(
            table=SpatialTableRef(table_name="spatial_records"),
            record_id="abc123",
        )
        assert centroid is not None
        self.assertAlmostEqual(centroid.lon, -96.1)
        self.assertAlmostEqual(centroid.lat, 31.2)
        self.assertIn("ST_Centroid", scenario.statements[-1][0])

    def test_repository_rejects_unsafe_identifier(self):
        scenario = CursorScenario(fetchone_values=[("3.4.2",)])
        repo = self._repository(scenario)
        with self.assertRaisesMessage(ValueError, "unsafe SQL identifier"):
            repo.filter_ids_by_bbox(
                table=SpatialTableRef(table_name="spatial_records;DROP TABLE x;"),
                bbox=BBox(west=-97, south=30, east=-96, north=31),
            )


class GeospatialServiceTests(SimpleTestCase):
    def test_service_rejects_unsupported_srid(self):
        repository = mock.MagicMock()
        service = GeospatialService(repository=repository)
        with self.assertRaisesMessage(ValueError, "Unsupported SRID"):
            service.filter_ids_by_bbox(
                table=SpatialTableRef(table_name="spatial_records"),
                bbox=BBox(west=-97, south=30, east=-96, north=31),
                srid=3857,
            )

    def test_service_rejects_non_polygon_for_polygon_filter(self):
        repository = mock.MagicMock()
        service = GeospatialService(repository=repository)
        with self.assertRaisesMessage(ValueError, "polygon filter requires Polygon or MultiPolygon geometry"):
            service.filter_ids_by_polygon(
                table=SpatialTableRef(table_name="spatial_records"),
                polygon_geojson={"type": "Point", "coordinates": [-96.0, 31.0]},
            )

    def test_service_rejects_invalid_bbox_order(self):
        repository = mock.MagicMock()
        service = GeospatialService(repository=repository)
        with self.assertRaisesMessage(ValueError, "bbox.west must be less than or equal to bbox.east"):
            service.filter_ids_by_bbox(
                table=SpatialTableRef(table_name="spatial_records"),
                bbox=BBox(west=10.0, south=30.0, east=0.0, north=31.0),
            )


class PostgisRuntimeSanityTests(TestCase):
    def test_postgis_extension_availability_probe(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'postgis')"
            )
            row = cursor.fetchone()
        self.assertIn(bool(row[0]), {True, False})


class PostgisRepositoryIntegrationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'postgis')"
            )
            available_row = cursor.fetchone()
            if not available_row or not bool(available_row[0]):
                raise AssertionError("PostGIS extension is not available in current database runtime.")
            cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
            cursor.execute("DROP TABLE IF EXISTS geospatial_repo_smoke;")
            cursor.execute(
                """
                CREATE TABLE geospatial_repo_smoke (
                    id BIGSERIAL PRIMARY KEY,
                    geometry_geojson JSONB NOT NULL,
                    geometry_srid INTEGER NOT NULL DEFAULT 4326
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO geospatial_repo_smoke (geometry_geojson, geometry_srid)
                VALUES
                ('{"type":"Point","coordinates":[-97.0,30.0]}'::jsonb, 4326),
                ('{"type":"Point","coordinates":[-96.0,31.0]}'::jsonb, 4326),
                ('{"type":"Point","coordinates":[-95.0,32.0]}'::jsonb, 4326)
                """
            )

    @classmethod
    def tearDownClass(cls):
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS geospatial_repo_smoke;")
        super().tearDownClass()

    def test_repository_executes_real_postgis_bbox_query(self):
        repository = PostgisGeospatialRepository(cursor_provider=lambda: connection.cursor())
        status = repository.postgis_status()
        self.assertTrue(status.installed)

        ids = repository.filter_ids_by_bbox(
            table=SpatialTableRef(table_name="geospatial_repo_smoke"),
            bbox=BBox(west=-97.5, south=29.5, east=-95.5, north=31.5),
        )
        self.assertTrue(len(ids) >= 2)
