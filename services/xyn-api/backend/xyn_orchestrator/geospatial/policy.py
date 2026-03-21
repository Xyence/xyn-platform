from __future__ import annotations

DEFAULT_GEOMETRY_FIELD_NAME = "geometry_geojson"
DEFAULT_GEOMETRY_SRID_FIELD_NAME = "geometry_srid"
DEFAULT_GEOMETRY_TYPE_FIELD_NAME = "geometry_type"
DEFAULT_GEOMETRY_BBOX_FIELDS = {
    "west": "geometry_bbox_west",
    "south": "geometry_bbox_south",
    "east": "geometry_bbox_east",
    "north": "geometry_bbox_north",
}
DEFAULT_GEOMETRY_CENTROID_FIELDS = {
    "lon": "geometry_centroid_lon",
    "lat": "geometry_centroid_lat",
}

DEFAULT_SRID = 4326
SUPPORTED_GEOMETRY_TYPES = {"Point", "LineString", "Polygon", "MultiPolygon"}
SUPPORTED_SPATIAL_FILTERS = ("bbox", "polygon", "radius")


def supported_geometry_types() -> tuple[str, ...]:
    return tuple(sorted(SUPPORTED_GEOMETRY_TYPES))
