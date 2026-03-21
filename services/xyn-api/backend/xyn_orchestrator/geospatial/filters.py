from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from .utils import BBox, Point, extract_bbox, normalize_geometry


@dataclass(frozen=True)
class RadiusFilter:
    center: Point
    radius_meters: float

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "RadiusFilter":
        if not isinstance(payload, dict):
            raise ValueError("radius filter must be an object")
        point_payload = payload.get("point")
        if not isinstance(point_payload, dict):
            raise ValueError("radius.point must be an object")
        try:
            lon = float(point_payload.get("lon"))
            lat = float(point_payload.get("lat"))
        except (TypeError, ValueError) as exc:
            raise ValueError("radius.point.lon and radius.point.lat must be numeric") from exc
        if lon < -180.0 or lon > 180.0:
            raise ValueError("radius.point.lon must be within [-180, 180]")
        if lat < -90.0 or lat > 90.0:
            raise ValueError("radius.point.lat must be within [-90, 90]")
        center = Point(lon=lon, lat=lat)
        try:
            radius_meters = float(payload.get("meters"))
        except (TypeError, ValueError) as exc:
            raise ValueError("radius.meters must be numeric") from exc
        if radius_meters <= 0:
            raise ValueError("radius.meters must be greater than zero")
        return cls(center=center, radius_meters=radius_meters)


@dataclass(frozen=True)
class SpatialFilter:
    bbox: BBox | None = None
    polygon: Dict[str, Any] | None = None
    radius: RadiusFilter | None = None

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "SpatialFilter":
        if not isinstance(payload, dict):
            raise ValueError("Spatial filter payload must be an object")

        bbox: BBox | None = None
        if payload.get("bbox") is not None:
            raw_bbox = payload.get("bbox")
            if not isinstance(raw_bbox, dict):
                raise ValueError("bbox must be an object")
            bbox = BBox(
                west=float(raw_bbox.get("west")),
                south=float(raw_bbox.get("south")),
                east=float(raw_bbox.get("east")),
                north=float(raw_bbox.get("north")),
            )
            _validate_bbox(bbox)

        polygon: Dict[str, Any] | None = None
        if payload.get("polygon") is not None:
            polygon = normalize_geometry(payload.get("polygon"))
            poly_bbox = extract_bbox(polygon)
            _validate_bbox(poly_bbox)

        radius: RadiusFilter | None = None
        if payload.get("radius") is not None:
            radius = RadiusFilter.from_payload(payload.get("radius"))

        if not any([bbox, polygon, radius]):
            raise ValueError("At least one spatial filter is required: bbox, polygon, or radius")
        return cls(bbox=bbox, polygon=polygon, radius=radius)

    def as_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if self.bbox:
            payload["bbox"] = self.bbox.as_dict()
        if self.polygon:
            payload["polygon"] = self.polygon
        if self.radius:
            payload["radius"] = {
                "point": {"lon": self.radius.center.lon, "lat": self.radius.center.lat},
                "meters": self.radius.radius_meters,
            }
        return payload


def _validate_bbox(bbox: BBox) -> None:
    if bbox.west > bbox.east:
        raise ValueError("bbox.west must be less than or equal to bbox.east")
    if bbox.south > bbox.north:
        raise ValueError("bbox.south must be less than or equal to bbox.north")
    if bbox.west < -180.0 or bbox.east > 180.0:
        raise ValueError("bbox longitude values must be within [-180, 180]")
    if bbox.south < -90.0 or bbox.north > 90.0:
        raise ValueError("bbox latitude values must be within [-90, 90]")
