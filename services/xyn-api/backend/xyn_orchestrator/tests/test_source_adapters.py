import uuid

from django.test import TestCase

from xyn_orchestrator import models
from xyn_orchestrator.source_adapters import SourceAdapterService
from xyn_orchestrator.sources.service import serialize_source_inspection


class SourceAdapterServiceTests(TestCase):
    def setUp(self):
        suffix = uuid.uuid4().hex[:8]
        self.workspace = models.Workspace.objects.create(slug=f"adapter-{suffix}", name="Adapter Workspace")
        self.source = models.SourceConnector.objects.create(
            workspace=self.workspace,
            key=f"source-{suffix}",
            name="Adapter Source",
            source_type="records_feed",
            source_mode="remote_url",
            configuration_json={},
        )
        self.pipeline = models.OrchestrationPipeline.objects.create(
            workspace=self.workspace,
            key="ingestion-runtime",
            name="Ingestion Runtime",
            enabled=True,
        )
        self.run = models.OrchestrationRun.objects.create(
            workspace=self.workspace,
            pipeline=self.pipeline,
            trigger_cause="manual",
            trigger_key="adapter-test",
            scope_jurisdiction="tx-travis-county",
            scope_source="county-feed",
        )
        self.artifact = models.IngestArtifactRecord.objects.create(
            workspace=self.workspace,
            source_connector=self.source,
            orchestration_run=self.run,
            artifact_id=uuid.uuid4(),
            original_filename="sample.csv",
            sha256="a" * 64,
        )
        self.service = SourceAdapterService()

    def _parsed_row(
        self,
        *,
        parser_name: str,
        normalized_payload: dict,
        provenance: dict,
        source_schema: dict | None = None,
        source_payload: dict | None = None,
        record_index: int | None = 1,
    ) -> models.IngestParsedRecord:
        return models.IngestParsedRecord.objects.create(
            workspace=self.workspace,
            source_connector=self.source,
            orchestration_run=self.run,
            artifact=self.artifact,
            parser_name=parser_name,
            parser_version="1",
            normalization_version="1",
            record_index=record_index,
            source_payload_json=source_payload or {},
            normalized_payload_json=normalized_payload,
            source_schema_json=source_schema or {},
            provenance_json=provenance,
            warnings_json=[],
            status="ok",
        )

    def test_csv_adapter_generates_field_hints_and_payload(self):
        parsed = self._parsed_row(
            parser_name="csv_tsv_parser",
            normalized_payload={"fields": {"id": "1", "owner": "Alpha LLC"}},
            provenance={"source_format": "csv", "row_number": 1},
            source_schema={"columns": ["id", "owner"]},
        )
        rows = self.service.adapt_parsed_record(source_connector=self.source, parsed_row=parsed)
        self.assertEqual(len(rows), 1)
        adapted = rows[0]
        self.assertEqual(adapted.adapter_kind, "csv")
        self.assertEqual(adapted.source_format, "csv")
        self.assertEqual(adapted.adapted_payload_json.get("record", {}).get("owner"), "Alpha LLC")
        self.assertEqual(adapted.source_position_json.get("row_number"), 1)
        self.assertEqual(len(adapted.field_metadata_json), 2)

    def test_shapefile_adapter_preserves_geometry_attributes_and_group_provenance(self):
        member = models.IngestArtifactMember.objects.create(
            workspace=self.workspace,
            source_connector=self.source,
            orchestration_run=self.run,
            parent_artifact=self.artifact,
            member_path="parcel/blocks.shp",
            member_basename="blocks.shp",
            group_key="parcel/blocks",
            extension="shp",
            classified_type="shp",
            status="parsed",
        )
        parsed = self._parsed_row(
            parser_name="shapefile_parser",
            normalized_payload={
                "attributes": {"parcel_id": "101", "owner": "Alpha LLC"},
                "geometry": {"type": "Point", "coordinates": [-97.0, 30.0]},
                "crs_wkt": "GEOGCS[...]",
            },
            provenance={
                "source_format": "shapefile",
                "feature_index": 2,
                "group_key": "parcel/blocks",
                "grouped_member_ids": [str(member.id)],
                "grouped_member_paths": ["parcel/blocks.shp"],
            },
            source_schema={"fields": ["parcel_id", "owner"], "source_format": "shapefile"},
            source_payload={"attributes": {"parcel_id": "101"}},
        )
        parsed.member = member
        parsed.save(update_fields=["member"])
        rows = self.service.adapt_parsed_record(source_connector=self.source, parsed_row=parsed)
        self.assertEqual(len(rows), 1)
        adapted = rows[0]
        self.assertEqual(adapted.adapter_kind, "shapefile")
        self.assertEqual(adapted.geometry_payload_json.get("type"), "Point")
        self.assertEqual(adapted.source_position_json.get("feature_index"), 2)
        self.assertTrue(adapted.provenance_json.get("grouped_member_ids"))

    def test_access_adapter_preserves_table_and_row_position(self):
        first = self._parsed_row(
            parser_name="access_parser",
            normalized_payload={"table": "parcels", "fields": {"id": "1", "owner": "Alpha LLC"}},
            provenance={"source_format": "access", "table": "parcels", "row_number": 1},
            source_schema={"columns": ["id", "owner"], "table": "parcels"},
            source_payload={"table": "parcels", "row": {"id": "1", "owner": "Alpha LLC"}},
            record_index=1,
        )
        second = self._parsed_row(
            parser_name="access_parser",
            normalized_payload={"table": "owners", "fields": {"id": "1", "name": "Alpha LLC"}},
            provenance={"source_format": "access", "table": "owners", "row_number": 1},
            source_schema={"columns": ["id", "name"], "table": "owners"},
            source_payload={"table": "owners", "row": {"id": "1", "name": "Alpha LLC"}},
            record_index=2,
        )
        rows = []
        rows.extend(self.service.adapt_parsed_record(source_connector=self.source, parsed_row=first))
        rows.extend(self.service.adapt_parsed_record(source_connector=self.source, parsed_row=second))
        self.assertEqual(len(rows), 2)
        subtypes = {row.source_subtype for row in rows}
        self.assertEqual(subtypes, {"parcels", "owners"})
        self.assertEqual(rows[0].adapter_kind, "access")

    def test_zip_candidate_adapter_persists_member_group_hints(self):
        first = models.IngestArtifactMember.objects.create(
            workspace=self.workspace,
            source_connector=self.source,
            orchestration_run=self.run,
            parent_artifact=self.artifact,
            member_path="parcel/blocks.shp",
            member_basename="blocks.shp",
            group_key="parcel/blocks",
            extension="shp",
            classified_type="shp",
            status="pending",
        )
        second = models.IngestArtifactMember.objects.create(
            workspace=self.workspace,
            source_connector=self.source,
            orchestration_run=self.run,
            parent_artifact=self.artifact,
            member_path="parcel/blocks.dbf",
            member_basename="blocks.dbf",
            group_key="parcel/blocks",
            extension="dbf",
            classified_type="dbf",
            status="pending",
        )
        third = models.IngestArtifactMember.objects.create(
            workspace=self.workspace,
            source_connector=self.source,
            orchestration_run=self.run,
            parent_artifact=self.artifact,
            member_path="parcel/blocks.shx",
            member_basename="blocks.shx",
            group_key="parcel/blocks",
            extension="shx",
            classified_type="shx",
            status="pending",
        )
        rows = self.service.persist_zip_candidates(
            source_connector=self.source,
            artifact=self.artifact,
            members=[first, second, third],
        )
        self.assertEqual(len(rows), 1)
        adapted = rows[0]
        self.assertEqual(adapted.adapter_kind, "zip")
        self.assertEqual(adapted.source_subtype, "shapefile_bundle")
        self.assertEqual(adapted.adapted_payload_json.get("member_count"), 3)

    def test_json_http_adapter_supports_record_path_extraction(self):
        self.source.configuration_json = {"json_adapter": {"record_path": "payload.items"}}
        self.source.save(update_fields=["configuration_json"])
        parsed = self._parsed_row(
            parser_name="geojson_parser",
            normalized_payload={"document": {"payload": {"items": [{"id": 1}, {"id": 2}]}}},
            provenance={"source_format": "json"},
            source_schema={"geojson_type": ""},
            source_payload={"payload": {"items": [{"id": 1}, {"id": 2}]}},
            record_index=1,
        )
        rows = self.service.adapt_parsed_record(source_connector=self.source, parsed_row=parsed)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].adapter_kind, "json_http")
        self.assertEqual(rows[0].adapted_payload_json.get("record", {}).get("id"), 1)
        self.assertEqual(rows[1].adapted_payload_json.get("record", {}).get("id"), 2)

    def test_dbf_adapter_returns_explicit_unsupported_for_missing_fields(self):
        parsed = self._parsed_row(
            parser_name="dbf_parser",
            normalized_payload={},
            provenance={"source_format": "dbf", "row_number": 1},
            source_schema={"source_format": "dbf"},
            source_payload={},
        )
        rows = self.service.adapt_parsed_record(source_connector=self.source, parsed_row=parsed)
        self.assertEqual(len(rows), 1)
        adapted = rows[0]
        self.assertEqual(adapted.adapter_kind, "dbf")
        self.assertEqual(adapted.status, "unsupported")
        self.assertIn("requires tabular", adapted.failure_reason)

    def test_preview_and_inspection_integration_surface_adapter_findings(self):
        parsed = self._parsed_row(
            parser_name="csv_tsv_parser",
            normalized_payload={"fields": {"id": "1", "city": "Austin"}},
            provenance={"source_format": "csv", "row_number": 1},
            source_schema={"columns": ["id", "city"]},
        )
        self.service.adapt_parsed_record(source_connector=self.source, parsed_row=parsed)
        self.source.last_run = self.run
        self.source.save(update_fields=["last_run"])

        inspection = models.SourceInspectionProfile.objects.create(
            source_connector=self.source,
            status="ok",
            detected_format="csv",
            discovered_fields_json=[{"name": "id", "type": "string"}],
            sample_metadata_json={"row_count": 1},
            validation_findings_json=[],
            inspection_run=self.run,
        )
        payload = serialize_source_inspection(inspection)
        self.assertGreater(payload["adapter_preview"]["record_count"], 0)
        self.assertIn("csv", payload["adapter_preview"]["adapter_kinds"])
        self.assertIn("adapter_profile_summary", payload["sample_metadata"])
