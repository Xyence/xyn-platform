from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from xyn_orchestrator.geospatial.filters import SpatialFilter
from xyn_orchestrator.geospatial.query import (
    filter_by_bbox,
    filter_by_distance,
    filter_by_polygon,
    filter_contains_point,
    intersects,
)
from xyn_orchestrator.geospatial.utils import (
    BBox,
    Point,
    compute_centroid,
    ensure_srid,
    extract_bbox,
    from_geojson,
    normalize_geometry,
    point_in_polygon,
    polygon_intersects,
    to_geojson,
)


class GeometryUtilityTests(SimpleTestCase):
    def test_geojson_round_trip_and_normalization(self):
        geometry = {"type": "Polygon", "coordinates": [[[-97.0, 30.0], [-96.0, 30.0], [-96.0, 31.0], [-97.0, 31.0]]]}
        normalized = normalize_geometry(geometry)
        self.assertEqual(normalized["coordinates"][0][0], normalized["coordinates"][0][-1])
        self.assertEqual(from_geojson(to_geojson(normalized)), normalized)

    def test_srid_enforcement(self):
        geometry = {"type": "Point", "coordinates": [-97.0, 30.0]}
        self.assertEqual(ensure_srid(geometry, srid=4326), 4326)
        with self.assertRaisesMessage(ValueError, "Unsupported SRID"):
            ensure_srid(geometry, srid=3857)

    def test_bbox_and_centroid(self):
        geometry = {
            "type": "Polygon",
            "coordinates": [[[-97.0, 30.0], [-95.0, 30.0], [-95.0, 32.0], [-97.0, 32.0], [-97.0, 30.0]]],
        }
        bbox = extract_bbox(geometry)
        self.assertEqual(bbox, BBox(west=-97.0, south=30.0, east=-95.0, north=32.0))
        centroid = compute_centroid(geometry)
        self.assertAlmostEqual(centroid.lon, -96.0, places=6)
        self.assertAlmostEqual(centroid.lat, 31.0, places=6)

    def test_point_in_polygon_and_polygon_intersection(self):
        polygon_a = {
            "type": "Polygon",
            "coordinates": [[[-97.0, 30.0], [-95.0, 30.0], [-95.0, 32.0], [-97.0, 32.0], [-97.0, 30.0]]],
        }
        polygon_b = {
            "type": "Polygon",
            "coordinates": [[[-96.5, 31.0], [-94.5, 31.0], [-94.5, 33.0], [-96.5, 33.0], [-96.5, 31.0]]],
        }
        inside = Point(lon=-96.2, lat=31.1)
        outside = Point(lon=-94.0, lat=29.0)
        self.assertTrue(point_in_polygon(inside, polygon_a))
        self.assertFalse(point_in_polygon(outside, polygon_a))
        self.assertTrue(polygon_intersects(polygon_a, polygon_b))


class SpatialFilterContractTests(SimpleTestCase):
    def test_spatial_filter_accepts_bbox_polygon_radius(self):
        payload = {
            "bbox": {"west": -98, "south": 29, "east": -94, "north": 33},
            "polygon": {
                "type": "Polygon",
                "coordinates": [[[-97.0, 30.0], [-95.0, 30.0], [-95.0, 32.0], [-97.0, 32.0], [-97.0, 30.0]]],
            },
            "radius": {"point": {"lon": -96.0, "lat": 31.0}, "meters": 1000},
        }
        parsed = SpatialFilter.from_payload(payload)
        serialized = parsed.as_dict()
        self.assertIn("bbox", serialized)
        self.assertIn("polygon", serialized)
        self.assertIn("radius", serialized)

    def test_spatial_filter_rejects_invalid_bbox(self):
        with self.assertRaisesMessage(ValueError, "bbox.west must be less than or equal to bbox.east"):
            SpatialFilter.from_payload({"bbox": {"west": 10, "south": 0, "east": 1, "north": 1}})

    def test_spatial_filter_rejects_invalid_radius(self):
        with self.assertRaisesMessage(ValueError, "radius.point.lon must be within [-180, 180]"):
            SpatialFilter.from_payload({"radius": {"point": {"lon": 500, "lat": 31}, "meters": 10}})


class SpatialQueryHelperTests(SimpleTestCase):
    def _queryset(self):
        queryset = mock.MagicMock()
        queryset.db = "default"
        queryset.none.return_value = "none-result"
        queryset.filter.return_value = "filtered-result"
        queryset.model = SimpleNamespace(
            _meta=SimpleNamespace(
                db_table="test_spatial_table",
                pk=SimpleNamespace(column="id"),
            )
        )
        return queryset

    def test_filter_by_bbox_calls_service_and_filters_by_ids(self):
        queryset = self._queryset()
        service = mock.MagicMock()
        service.filter_ids_by_bbox.return_value = [11, 12]
        bbox = BBox(west=-97.0, south=30.0, east=-96.0, north=31.0)
        result = filter_by_bbox(queryset, bbox, prefix="geometry", service=service)
        self.assertEqual(result, "filtered-result")
        service.filter_ids_by_bbox.assert_called_once()
        queryset.filter.assert_called_once_with(pk__in=[11, 12])

    @mock.patch("xyn_orchestrator.geospatial.django_adapter.django_geospatial_service")
    def test_filter_by_bbox_uses_default_django_service(self, service_factory):
        queryset = self._queryset()
        service = mock.MagicMock()
        service.filter_ids_by_bbox.return_value = [100]
        service_factory.return_value = service
        bbox = BBox(west=-97.0, south=30.0, east=-96.0, north=31.0)
        filter_by_bbox(queryset, bbox)
        service_factory.assert_called_once_with(using="default")

    def test_filter_contains_point_uses_service(self):
        queryset = self._queryset()
        service = mock.MagicMock()
        service.filter_ids_contains_point.return_value = [1]
        result = filter_contains_point(queryset, Point(lon=-96.0, lat=31.0), service=service)
        self.assertEqual(result, "filtered-result")
        service.filter_ids_contains_point.assert_called_once()
        queryset.filter.assert_called_once_with(pk__in=[1])

    def test_filter_by_polygon_intersection_uses_service(self):
        polygon_a = {
            "type": "Polygon",
            "coordinates": [[[-97.0, 30.0], [-95.0, 30.0], [-95.0, 32.0], [-97.0, 32.0], [-97.0, 30.0]]],
        }
        queryset = self._queryset()
        service = mock.MagicMock()
        service.filter_ids_by_polygon.return_value = [7]

        result = filter_by_polygon(queryset, polygon_a, service=service)
        self.assertEqual(result, "filtered-result")
        self.assertEqual(intersects(queryset, polygon_a, service=service), "filtered-result")
        service.filter_ids_by_polygon.assert_called_once()
        service.filter_ids_intersects.assert_called_once()

    def test_filter_by_distance_uses_service(self):
        queryset = self._queryset()
        service = mock.MagicMock()
        service.filter_ids_by_distance.return_value = [5]
        result = filter_by_distance(queryset, Point(lon=-96.0, lat=31.0), 1000.0, service=service)
        self.assertEqual(result, "filtered-result")
        service.filter_ids_by_distance.assert_called_once()
        queryset.filter.assert_called_once_with(pk__in=[5])

    def test_query_helpers_return_none_queryset_when_repository_finds_no_rows(self):
        queryset = self._queryset()
        service = mock.MagicMock()
        service.filter_ids_by_bbox.return_value = []
        result = filter_by_bbox(queryset, BBox(west=-1, south=-1, east=1, north=1), service=service)
        self.assertEqual(result, "none-result")
        queryset.none.assert_called_once_with()

    def test_query_helpers_raise_on_invalid_distance(self):
        queryset = self._queryset()
        service = mock.MagicMock()
        service.filter_ids_by_distance.side_effect = ValueError("radius_meters must be greater than zero")
        with self.assertRaisesMessage(ValueError, "radius_meters must be greater than zero"):
            filter_by_distance(queryset, Point(lon=-96.0, lat=31.0), 0.0, service=service)

    def test_query_helpers_raise_on_invalid_polygon(self):
        queryset = self._queryset()
        service = mock.MagicMock()
        service.filter_ids_by_polygon.side_effect = ValueError("polygon filter requires Polygon or MultiPolygon geometry")
        with self.assertRaisesMessage(ValueError, "polygon filter requires Polygon or MultiPolygon geometry"):
            filter_by_polygon(
                queryset,
                {"type": "Point", "coordinates": [-96.0, 31.0]},
                service=service,
            )

    def test_intersects_uses_geometry_parameter(self):
        queryset = self._queryset()
        service = mock.MagicMock()
        service.filter_ids_intersects.return_value = [9]
        geometry = {"type": "Point", "coordinates": [-96.0, 31.0]}
        result = intersects(queryset, geometry, service=service)
        self.assertEqual(result, "filtered-result")
        service.filter_ids_intersects.assert_called_once()

    def test_filter_contains_point_with_no_rows(self):
        queryset = self._queryset()
        service = mock.MagicMock()
        service.filter_ids_contains_point.return_value = []
        result = filter_contains_point(queryset, Point(lon=-96.0, lat=31.0), service=service)
        self.assertEqual(result, "none-result")
        queryset.none.assert_called_once_with()

    def test_filter_by_distance_with_empty_rows(self):
        queryset = self._queryset()
        service = mock.MagicMock()
        service.filter_ids_by_distance.return_value = []
        result = filter_by_distance(queryset, Point(lon=-96.0, lat=31.0), 1000.0, service=service)
        self.assertEqual(result, "none-result")
        queryset.none.assert_called_once_with()

    def test_intersects_with_empty_rows(self):
        queryset = self._queryset()
        service = mock.MagicMock()
        service.filter_ids_intersects.return_value = []
        result = intersects(queryset, {"type": "Point", "coordinates": [-96.0, 31.0]}, service=service)
        self.assertEqual(result, "none-result")
        queryset.none.assert_called_once_with()

    def test_filter_by_polygon_with_empty_rows(self):
        queryset = self._queryset()
        service = mock.MagicMock()
        service.filter_ids_by_polygon.return_value = []
        result = filter_by_polygon(
            queryset,
            {"type": "Polygon", "coordinates": [[[-97.0, 30.0], [-96.0, 30.0], [-96.0, 31.0], [-97.0, 31.0], [-97.0, 30.0]]]},
            service=service,
        )
        self.assertEqual(result, "none-result")
        queryset.none.assert_called_once_with()
