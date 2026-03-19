from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from .policy import DEFAULT_SRID, SUPPORTED_GEOMETRY_TYPES


@dataclass(frozen=True)
class BBox:
    west: float
    south: float
    east: float
    north: float

    def as_dict(self) -> Dict[str, float]:
        return {
            "west": self.west,
            "south": self.south,
            "east": self.east,
            "north": self.north,
        }


@dataclass(frozen=True)
class Point:
    lon: float
    lat: float

    def as_geojson(self) -> Dict[str, Any]:
        return {"type": "Point", "coordinates": [self.lon, self.lat]}


def to_geojson(geometry: Dict[str, Any]) -> Dict[str, Any]:
    return normalize_geometry(geometry)


def from_geojson(payload: Dict[str, Any]) -> Dict[str, Any]:
    return normalize_geometry(payload)


def _as_float(value: Any, *, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc


def _validate_lon_lat(lon: float, lat: float, *, field_name: str) -> None:
    if lon < -180.0 or lon > 180.0:
        raise ValueError(f"{field_name} longitude must be within [-180, 180]")
    if lat < -90.0 or lat > 90.0:
        raise ValueError(f"{field_name} latitude must be within [-90, 90]")


def _normalize_position(raw: Sequence[Any], *, field_name: str) -> List[float]:
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        raise ValueError(f"{field_name} must be [lon, lat]")
    lon = _as_float(raw[0], field_name=f"{field_name}[0]")
    lat = _as_float(raw[1], field_name=f"{field_name}[1]")
    _validate_lon_lat(lon, lat, field_name=field_name)
    return [lon, lat]


def _normalize_linestring(raw: Sequence[Any], *, field_name: str) -> List[List[float]]:
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        raise ValueError(f"{field_name} must contain at least two positions")
    return [_normalize_position(item, field_name=f"{field_name}[{idx}]") for idx, item in enumerate(raw)]


def _normalize_ring(raw: Sequence[Any], *, field_name: str) -> List[List[float]]:
    if not isinstance(raw, (list, tuple)) or len(raw) < 4:
        raise ValueError(f"{field_name} must contain at least four positions")
    ring = [_normalize_position(item, field_name=f"{field_name}[{idx}]") for idx, item in enumerate(raw)]
    if ring[0] != ring[-1]:
        ring.append([ring[0][0], ring[0][1]])
    if len(ring) < 4:
        raise ValueError(f"{field_name} must contain at least four positions")
    return ring


def _normalize_polygon(raw: Sequence[Any], *, field_name: str) -> List[List[List[float]]]:
    if not isinstance(raw, (list, tuple)) or len(raw) == 0:
        raise ValueError(f"{field_name} must contain one or more linear rings")
    normalized = [_normalize_ring(ring, field_name=f"{field_name}[{idx}]") for idx, ring in enumerate(raw)]
    return normalized


def _iter_positions(geometry: Dict[str, Any]) -> Iterable[Tuple[float, float]]:
    geo_type = geometry["type"]
    coords = geometry["coordinates"]
    if geo_type == "Point":
        yield (float(coords[0]), float(coords[1]))
        return
    if geo_type == "LineString":
        for item in coords:
            yield (float(item[0]), float(item[1]))
        return
    if geo_type == "Polygon":
        for ring in coords:
            for item in ring:
                yield (float(item[0]), float(item[1]))
        return
    if geo_type == "MultiPolygon":
        for polygon in coords:
            for ring in polygon:
                for item in ring:
                    yield (float(item[0]), float(item[1]))
        return
    raise ValueError(f"Unsupported geometry type '{geo_type}'")


def normalize_geometry(geometry: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(geometry, dict):
        raise ValueError("Geometry must be an object")
    geo_type = str(geometry.get("type") or "").strip()
    if geo_type not in SUPPORTED_GEOMETRY_TYPES:
        raise ValueError(f"Unsupported geometry type '{geo_type}'")
    coordinates = geometry.get("coordinates")
    if geo_type == "Point":
        normalized_coords: Any = _normalize_position(coordinates, field_name="coordinates")
    elif geo_type == "LineString":
        normalized_coords = _normalize_linestring(coordinates, field_name="coordinates")
    elif geo_type == "Polygon":
        normalized_coords = _normalize_polygon(coordinates, field_name="coordinates")
    else:
        if not isinstance(coordinates, (list, tuple)) or len(coordinates) == 0:
            raise ValueError("coordinates must contain one or more polygons for MultiPolygon")
        normalized_coords = [
            _normalize_polygon(polygon, field_name=f"coordinates[{idx}]") for idx, polygon in enumerate(coordinates)
        ]
    return {"type": geo_type, "coordinates": normalized_coords}


def ensure_srid(geometry: Dict[str, Any], *, srid: int = DEFAULT_SRID, default_srid: int = DEFAULT_SRID) -> int:
    if srid != default_srid:
        raise ValueError(f"Unsupported SRID '{srid}'. Only SRID {default_srid} is supported in geospatial v1.")
    normalize_geometry(geometry)
    return srid


def extract_bbox(geometry: Dict[str, Any]) -> BBox:
    normalized = normalize_geometry(geometry)
    lons: List[float] = []
    lats: List[float] = []
    for lon, lat in _iter_positions(normalized):
        lons.append(lon)
        lats.append(lat)
    return BBox(west=min(lons), south=min(lats), east=max(lons), north=max(lats))


def _polygon_centroid_from_ring(ring: List[List[float]]) -> Point:
    area2 = 0.0
    cx_acc = 0.0
    cy_acc = 0.0
    for idx in range(len(ring) - 1):
        x1, y1 = ring[idx]
        x2, y2 = ring[idx + 1]
        cross = (x1 * y2) - (x2 * y1)
        area2 += cross
        cx_acc += (x1 + x2) * cross
        cy_acc += (y1 + y2) * cross
    if math.isclose(area2, 0.0):
        lon = sum(point[0] for point in ring[:-1]) / max(1, len(ring) - 1)
        lat = sum(point[1] for point in ring[:-1]) / max(1, len(ring) - 1)
        return Point(lon=lon, lat=lat)
    factor = 1.0 / (3.0 * area2)
    return Point(lon=cx_acc * factor, lat=cy_acc * factor)


def compute_centroid(geometry: Dict[str, Any]) -> Point:
    normalized = normalize_geometry(geometry)
    geo_type = normalized["type"]
    coords = normalized["coordinates"]
    if geo_type == "Point":
        return Point(lon=float(coords[0]), lat=float(coords[1]))
    if geo_type == "LineString":
        lon = sum(point[0] for point in coords) / len(coords)
        lat = sum(point[1] for point in coords) / len(coords)
        return Point(lon=lon, lat=lat)
    if geo_type == "Polygon":
        return _polygon_centroid_from_ring(coords[0])
    centroids = [_polygon_centroid_from_ring(polygon[0]) for polygon in coords]
    lon = sum(item.lon for item in centroids) / len(centroids)
    lat = sum(item.lat for item in centroids) / len(centroids)
    return Point(lon=lon, lat=lat)


def point_in_polygon(point: Point, polygon_geometry: Dict[str, Any]) -> bool:
    normalized = normalize_geometry(polygon_geometry)
    geo_type = normalized["type"]
    if geo_type == "Polygon":
        polygons = [normalized["coordinates"]]
    elif geo_type == "MultiPolygon":
        polygons = normalized["coordinates"]
    else:
        raise ValueError("point_in_polygon requires Polygon or MultiPolygon geometry")
    for polygon in polygons:
        outer = polygon[0]
        if _point_in_ring(point, outer) and not any(_point_in_ring(point, hole) for hole in polygon[1:]):
            return True
    return False


def _point_in_ring(point: Point, ring: List[List[float]]) -> bool:
    inside = False
    x = point.lon
    y = point.lat
    for idx in range(len(ring) - 1):
        x1, y1 = ring[idx]
        x2, y2 = ring[idx + 1]
        intersects = ((y1 > y) != (y2 > y)) and (
            x < ((x2 - x1) * (y - y1) / ((y2 - y1) if not math.isclose(y2, y1) else 1e-12)) + x1
        )
        if intersects:
            inside = not inside
    return inside


def polygon_intersects(left_geometry: Dict[str, Any], right_geometry: Dict[str, Any]) -> bool:
    left = normalize_geometry(left_geometry)
    right = normalize_geometry(right_geometry)
    left_bbox = extract_bbox(left).as_dict()
    right_bbox = extract_bbox(right).as_dict()
    if (
        left_bbox["west"] > right_bbox["east"]
        or left_bbox["east"] < right_bbox["west"]
        or left_bbox["south"] > right_bbox["north"]
        or left_bbox["north"] < right_bbox["south"]
    ):
        return False
    left_polygons = _to_polygons(left)
    right_polygons = _to_polygons(right)
    for left_polygon in left_polygons:
        for right_polygon in right_polygons:
            if _rings_intersect(left_polygon[0], right_polygon[0]):
                return True
            if point_in_polygon(Point(*left_polygon[0][0]), {"type": "Polygon", "coordinates": right_polygon}):
                return True
            if point_in_polygon(Point(*right_polygon[0][0]), {"type": "Polygon", "coordinates": left_polygon}):
                return True
    return False


def _to_polygons(geometry: Dict[str, Any]) -> List[List[List[List[float]]]]:
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiPolygon":
        return geometry["coordinates"]
    raise ValueError("polygon_intersects requires Polygon or MultiPolygon geometries")


def _rings_intersect(left_ring: List[List[float]], right_ring: List[List[float]]) -> bool:
    for idx in range(len(left_ring) - 1):
        left_seg = (left_ring[idx], left_ring[idx + 1])
        for jdx in range(len(right_ring) - 1):
            right_seg = (right_ring[jdx], right_ring[jdx + 1])
            if _segments_intersect(left_seg[0], left_seg[1], right_seg[0], right_seg[1]):
                return True
    return False


def _segments_intersect(
    a1: Sequence[float],
    a2: Sequence[float],
    b1: Sequence[float],
    b2: Sequence[float],
) -> bool:
    def orientation(p: Sequence[float], q: Sequence[float], r: Sequence[float]) -> float:
        return (q[1] - p[1]) * (r[0] - q[0]) - (q[0] - p[0]) * (r[1] - q[1])

    def on_segment(p: Sequence[float], q: Sequence[float], r: Sequence[float]) -> bool:
        return min(p[0], r[0]) <= q[0] <= max(p[0], r[0]) and min(p[1], r[1]) <= q[1] <= max(p[1], r[1])

    o1 = orientation(a1, a2, b1)
    o2 = orientation(a1, a2, b2)
    o3 = orientation(b1, b2, a1)
    o4 = orientation(b1, b2, a2)

    if (o1 > 0 > o2 or o1 < 0 < o2) and (o3 > 0 > o4 or o3 < 0 < o4):
        return True
    if math.isclose(o1, 0.0) and on_segment(a1, b1, a2):
        return True
    if math.isclose(o2, 0.0) and on_segment(a1, b2, a2):
        return True
    if math.isclose(o3, 0.0) and on_segment(b1, a1, b2):
        return True
    if math.isclose(o4, 0.0) and on_segment(b1, a2, b2):
        return True
    return False

