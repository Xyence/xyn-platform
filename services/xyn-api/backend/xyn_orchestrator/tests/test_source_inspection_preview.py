import uuid

from django.test import TestCase

from xyn_orchestrator.models import SourceConnector, SourceInspectionProfile, Workspace
from xyn_orchestrator.sources.service import serialize_source_inspection


class SourceInspectionPreviewTests(TestCase):
    def setUp(self):
        suffix = uuid.uuid4().hex[:6]
        self.workspace = Workspace.objects.create(slug=f"preview-{suffix}", name="Preview Workspace")
        self.source = SourceConnector.objects.create(
            workspace=self.workspace,
            key=f"source-{suffix}",
            name="Preview Source",
            source_type="records_feed",
            source_mode="file_upload",
            refresh_cadence_seconds=0,
            configuration_json={},
            lifecycle_state="registered",
            health_status="unknown",
        )

    def test_serialization_with_sample_rows_only(self):
        inspection = SourceInspectionProfile.objects.create(
            source_connector=self.source,
            status="ok",
            detected_format="csv",
            discovered_fields_json=[{"name": "id", "type": "string"}, {"name": "city", "type": "string"}],
            sample_metadata_json={"row_count": 120, "sample_rows": [{"id": "1", "city": "Austin"}]},
            validation_findings_json=[],
        )
        payload = serialize_source_inspection(inspection)
        sample = payload["sample_metadata"]
        self.assertEqual(sample["profile_summary"]["row_count"], 120)
        self.assertEqual(sample["profile_summary"]["discovered_fields_count"], 2)
        self.assertTrue(sample["profile_summary"]["has_sample_rows"])
        self.assertFalse(sample["profile_summary"]["has_geometry"])
        self.assertNotIn("geometry_summary", sample)

    def test_serialization_with_geometry_summary(self):
        inspection = SourceInspectionProfile.objects.create(
            source_connector=self.source,
            status="ok",
            detected_format="geojson",
            discovered_fields_json=[{"name": "geometry", "type": "geometry"}],
            sample_metadata_json={
                "sample_rows": [
                    {"geometry": {"type": "Point", "coordinates": [-96.0, 31.0]}},
                    {"geometry": {"type": "Point", "coordinates": [-96.2, 30.8]}},
                ]
            },
            validation_findings_json=[],
        )
        payload = serialize_source_inspection(inspection)
        geometry_summary = payload["sample_metadata"]["geometry_summary"]
        self.assertTrue(geometry_summary["present"])
        self.assertIn("Point", geometry_summary["geometry_types"])
        self.assertIsNotNone(geometry_summary["bbox"])
        self.assertIsNotNone(geometry_summary["centroid"])

    def test_serialization_without_geometry(self):
        inspection = SourceInspectionProfile.objects.create(
            source_connector=self.source,
            status="ok",
            detected_format="csv",
            discovered_fields_json=[{"name": "id", "type": "string"}],
            sample_metadata_json={"sample_rows": [{"id": "1"}]},
            validation_findings_json=[],
        )
        payload = serialize_source_inspection(inspection)
        self.assertNotIn("geometry_summary", payload["sample_metadata"])

    def test_missing_sample_rows_defaults_to_empty(self):
        inspection = SourceInspectionProfile.objects.create(
            source_connector=self.source,
            status="ok",
            detected_format="csv",
            discovered_fields_json=[{"name": "id", "type": "string"}],
            sample_metadata_json={"row_count": 5},
            validation_findings_json=[],
        )
        payload = serialize_source_inspection(inspection)
        sample = payload["sample_metadata"]
        self.assertEqual(sample["sample_rows"], [])
        self.assertFalse(sample["profile_summary"]["has_sample_rows"])

    def test_malformed_geometry_is_non_fatal(self):
        inspection = SourceInspectionProfile.objects.create(
            source_connector=self.source,
            status="ok",
            detected_format="geojson",
            discovered_fields_json=[{"name": "geometry", "type": "geometry"}],
            sample_metadata_json={"geometry": {"type": "BadType", "coordinates": [1, 2]}},
            validation_findings_json=[],
        )
        payload = serialize_source_inspection(inspection)
        geometry_summary = payload["sample_metadata"]["geometry_summary"]
        self.assertFalse(geometry_summary["present"])
        self.assertTrue(geometry_summary.get("errors"))
        finding = payload["validation_findings"][-1]
        self.assertEqual(finding.get("type"), "geometry_summary_error")
