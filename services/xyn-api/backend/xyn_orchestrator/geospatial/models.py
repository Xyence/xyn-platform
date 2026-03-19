from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models

from .policy import (
    DEFAULT_GEOMETRY_BBOX_FIELDS,
    DEFAULT_GEOMETRY_CENTROID_FIELDS,
    DEFAULT_GEOMETRY_FIELD_NAME,
    DEFAULT_GEOMETRY_SRID_FIELD_NAME,
    DEFAULT_GEOMETRY_TYPE_FIELD_NAME,
    DEFAULT_SRID,
)
from .utils import compute_centroid, ensure_srid, extract_bbox, normalize_geometry


class SpatialModelMixin(models.Model):
    """
    Thin platform convention for spatial-enabled records in v1.

    Stores canonical geometry as GeoJSON in SRID 4326 plus derived centroid and bbox
    fields for portable query support without requiring PostGIS-specific model fields.
    """

    geometry_geojson = models.JSONField(default=dict, blank=True)
    geometry_srid = models.PositiveIntegerField(default=DEFAULT_SRID)
    geometry_type = models.CharField(max_length=32, blank=True, default="")
    geometry_bbox_west = models.FloatField(null=True, blank=True)
    geometry_bbox_south = models.FloatField(null=True, blank=True)
    geometry_bbox_east = models.FloatField(null=True, blank=True)
    geometry_bbox_north = models.FloatField(null=True, blank=True)
    geometry_centroid_lon = models.FloatField(null=True, blank=True)
    geometry_centroid_lat = models.FloatField(null=True, blank=True)

    class Meta:
        abstract = True
        indexes = [
            models.Index(
                fields=[
                    DEFAULT_GEOMETRY_BBOX_FIELDS["west"],
                    DEFAULT_GEOMETRY_BBOX_FIELDS["south"],
                    DEFAULT_GEOMETRY_BBOX_FIELDS["east"],
                    DEFAULT_GEOMETRY_BBOX_FIELDS["north"],
                ],
                name="%(app_label)s_%(class)s_bbox_window",
            ),
            models.Index(
                fields=[
                    DEFAULT_GEOMETRY_CENTROID_FIELDS["lat"],
                    DEFAULT_GEOMETRY_CENTROID_FIELDS["lon"],
                ],
                name="%(app_label)s_%(class)s_centroid",
            ),
            models.Index(fields=[DEFAULT_GEOMETRY_TYPE_FIELD_NAME], name="%(app_label)s_%(class)s_geom_type"),
        ]

    def clean(self) -> None:
        super().clean()
        geo = getattr(self, DEFAULT_GEOMETRY_FIELD_NAME, None)
        if not geo:
            return
        try:
            normalized = normalize_geometry(geo)
            ensure_srid(normalized, srid=int(getattr(self, DEFAULT_GEOMETRY_SRID_FIELD_NAME) or DEFAULT_SRID))
            bbox = extract_bbox(normalized)
            centroid = compute_centroid(normalized)
        except ValueError as exc:
            raise ValidationError({DEFAULT_GEOMETRY_FIELD_NAME: str(exc)}) from exc

        setattr(self, DEFAULT_GEOMETRY_FIELD_NAME, normalized)
        setattr(self, DEFAULT_GEOMETRY_TYPE_FIELD_NAME, str(normalized.get("type") or ""))
        setattr(self, DEFAULT_GEOMETRY_BBOX_FIELDS["west"], bbox.west)
        setattr(self, DEFAULT_GEOMETRY_BBOX_FIELDS["south"], bbox.south)
        setattr(self, DEFAULT_GEOMETRY_BBOX_FIELDS["east"], bbox.east)
        setattr(self, DEFAULT_GEOMETRY_BBOX_FIELDS["north"], bbox.north)
        setattr(self, DEFAULT_GEOMETRY_CENTROID_FIELDS["lon"], centroid.lon)
        setattr(self, DEFAULT_GEOMETRY_CENTROID_FIELDS["lat"], centroid.lat)

    def save(self, *args, **kwargs):  # type: ignore[override]
        self.full_clean()
        return super().save(*args, **kwargs)
