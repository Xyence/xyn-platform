import io
import json
import os
import tempfile
import zipfile
from unittest import mock

from django.conf import settings
from django.test import TestCase

from xyn_orchestrator import models
from xyn_orchestrator.ingestion.archive import ZipArchiveExpander
from xyn_orchestrator.ingestion.classification import classify_file
from xyn_orchestrator.ingestion.coordinator import IngestionCoordinator
from xyn_orchestrator.ingestion.fetch import HttpArtifactFetcher
from xyn_orchestrator.ingestion.interfaces import (
    FILE_KIND_CSV,
    FILE_KIND_GEOJSON,
    FILE_KIND_SHP,
    FILE_KIND_UNKNOWN_BINARY,
    FILE_KIND_ZIP,
)
from xyn_orchestrator.storage import IngestStorageService, RetentionClass, SnapshotType


class _MockHttpResponse:
    def __init__(self, *, url: str, status_code: int = 200, headers: dict | None = None, chunks: list[bytes] | None = None):
        self.url = url
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = chunks or []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http error {self.status_code}")

    def iter_content(self, chunk_size=1024):
        for chunk in self._chunks:
            yield chunk


class IngestionRuntimeTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._prior_workspace_root = os.environ.get("XYN_WORKSPACE_ROOT")
        self._prior_artifact_provider = os.environ.get("XYN_PLATFORM_DURABLE_ARTIFACT_PROVIDER")
        self._prior_artifact_root = os.environ.get("XYN_ARTIFACT_ROOT")
        self._prior_media_root = getattr(settings, "MEDIA_ROOT", "")
        os.environ["XYN_WORKSPACE_ROOT"] = self._tmp.name
        os.environ["XYN_PLATFORM_DURABLE_ARTIFACT_PROVIDER"] = "local"
        os.environ["XYN_ARTIFACT_ROOT"] = os.path.join(self._tmp.name, "artifacts")
        settings.MEDIA_ROOT = os.path.join(self._tmp.name, "media")
        self.addCleanup(self._restore_env)
        self.workspace = models.Workspace.objects.create(slug="ingest-runtime", name="Ingestion Runtime")
        self.source = models.SourceConnector.objects.create(
            workspace=self.workspace,
            key="county-feed",
            name="County Feed",
            source_type="generic",
            source_mode="remote_url",
        )

    def _restore_env(self):
        if self._prior_workspace_root is None:
            os.environ.pop("XYN_WORKSPACE_ROOT", None)
        else:
            os.environ["XYN_WORKSPACE_ROOT"] = self._prior_workspace_root
        if self._prior_artifact_provider is None:
            os.environ.pop("XYN_PLATFORM_DURABLE_ARTIFACT_PROVIDER", None)
        else:
            os.environ["XYN_PLATFORM_DURABLE_ARTIFACT_PROVIDER"] = self._prior_artifact_provider
        if self._prior_artifact_root is None:
            os.environ.pop("XYN_ARTIFACT_ROOT", None)
        else:
            os.environ["XYN_ARTIFACT_ROOT"] = self._prior_artifact_root
        settings.MEDIA_ROOT = self._prior_media_root

    def test_file_classification_matrix(self):
        self.assertEqual(classify_file(filename="bundle.zip").kind, FILE_KIND_ZIP)
        self.assertEqual(classify_file(filename="rows.csv").kind, FILE_KIND_CSV)
        self.assertEqual(classify_file(filename="shape.shp").kind, FILE_KIND_SHP)
        self.assertEqual(classify_file(filename="map.geojson").kind, FILE_KIND_GEOJSON)
        self.assertEqual(classify_file(filename="blob.bin").kind, FILE_KIND_UNKNOWN_BINARY)

    def test_http_fetch_metadata_capture_and_raw_artifact_persistence(self):
        coordinator = IngestionCoordinator()
        run = coordinator.create_ingest_run(
            workspace=self.workspace,
            source_connector=self.source,
            jurisdiction="tx-travis-county",
            source_scope="county",
        )
        fetcher = HttpArtifactFetcher()
        with mock.patch("xyn_orchestrator.ingestion.fetch.requests.get") as mocked_get:
            mocked_get.return_value = _MockHttpResponse(
                url="https://cdn.example.com/data.csv",
                status_code=200,
                headers={
                    "content-type": "text/csv",
                    "content-length": "12",
                    "etag": "abc123",
                    "last-modified": "Tue, 01 Jan 2026 00:00:00 GMT",
                },
                chunks=[b"a,b\n1,2\n"],
            )
            result = fetcher.fetch_to_artifact(
                workspace=self.workspace,
                source_connector=self.source,
                orchestration_run=run,
                scope_jurisdiction="tx-travis-county",
                scope_source="county",
                request=type("Req", (), {"source_url": "https://example.com/data.csv", "timeout_seconds": 30, "connect_timeout_seconds": 5, "headers": {}})(),
            )
        row = models.IngestArtifactRecord.objects.get(id=result.artifact_record_id)
        self.assertEqual(row.source_url, "https://example.com/data.csv")
        self.assertEqual(row.final_url, "https://cdn.example.com/data.csv")
        self.assertEqual(row.etag, "abc123")
        self.assertEqual(row.last_modified, "Tue, 01 Jan 2026 00:00:00 GMT")
        self.assertEqual(row.response_status, 200)
        self.assertTrue(row.sha256)
        self.assertTrue(os.path.exists(result.local_path))

    def test_zip_expansion_tracks_members_and_blocks_zip_slip(self):
        storage = IngestStorageService()
        parent = storage.store_snapshot_bytes(
            workspace=self.workspace,
            name="bundle.zip",
            content_type="application/zip",
            content=b"zip",
            snapshot_type=SnapshotType.RAW,
            retention_class=RetentionClass.SNAPSHOT,
            source_connector=self.source,
            scope_jurisdiction="tx-travis-county",
            scope_source="county",
        ).record
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("a/data.csv", "id,name\n1,alpha\n")
            archive.writestr("a/data.geojson", '{"type":"FeatureCollection","features":[]}')
        members = ZipArchiveExpander().expand(parent_artifact=parent, zip_bytes=buf.getvalue())
        self.assertEqual(len(members), 2)
        self.assertEqual(models.IngestArtifactMember.objects.filter(parent_artifact=parent).count(), 2)

        slip = io.BytesIO()
        with zipfile.ZipFile(slip, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("../evil.txt", "oops")
        with self.assertRaises(ValueError):
            ZipArchiveExpander().expand(parent_artifact=parent, zip_bytes=slip.getvalue())

    def test_csv_parsing_via_coordinator(self):
        with mock.patch("xyn_orchestrator.ingestion.fetch.requests.get") as mocked_get:
            mocked_get.return_value = _MockHttpResponse(
                url="https://example.com/data.csv",
                headers={"content-type": "text/csv", "content-length": "20"},
                chunks=[b"id,name\n1,alpha\n2,beta\n"],
            )
            result = IngestionCoordinator().ingest_from_url(
                source_connector=self.source,
                source_url="https://example.com/data.csv",
                jurisdiction="tx-travis-county",
                source_scope="county",
            )
        self.assertEqual(result.parsed_record_count, 2)
        rows = models.IngestParsedRecord.objects.filter(orchestration_run_id=result.run_id).order_by("record_index")
        self.assertEqual(rows.count(), 2)
        self.assertEqual(rows.first().provenance_json.get("row_number"), 1)

    def test_geojson_parsing_via_coordinator_preserves_feature_payload(self):
        payload = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"id": 1, "name": "alpha"},
                    "geometry": {"type": "Point", "coordinates": [-97.0, 30.0]},
                }
            ],
        }
        with mock.patch("xyn_orchestrator.ingestion.fetch.requests.get") as mocked_get:
            mocked_get.return_value = _MockHttpResponse(
                url="https://example.com/data.geojson",
                headers={"content-type": "application/geo+json", "content-length": "100"},
                chunks=[json.dumps(payload).encode("utf-8")],
            )
            result = IngestionCoordinator().ingest_from_url(
                source_connector=self.source,
                source_url="https://example.com/data.geojson",
                jurisdiction="tx-travis-county",
                source_scope="county",
            )
        self.assertEqual(result.parsed_record_count, 1)
        row = models.IngestParsedRecord.objects.filter(orchestration_run_id=result.run_id).first()
        self.assertEqual(row.source_payload_json.get("type"), "Feature")
        self.assertEqual(row.normalized_payload_json.get("properties", {}).get("name"), "alpha")

    def test_grouped_shapefile_bundle_routes_to_explicit_unsupported(self):
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("parcel/blocks.shp", b"fake-shp")
            archive.writestr("parcel/blocks.dbf", b"fake-dbf")
            archive.writestr("parcel/blocks.shx", b"fake-shx")
        with mock.patch("xyn_orchestrator.ingestion.fetch.requests.get") as mocked_get:
            mocked_get.return_value = _MockHttpResponse(
                url="https://example.com/parcel.zip",
                headers={"content-type": "application/zip", "content-length": str(len(zip_buf.getvalue()))},
                chunks=[zip_buf.getvalue()],
            )
            result = IngestionCoordinator().ingest_from_url(
                source_connector=self.source,
                source_url="https://example.com/parcel.zip",
                jurisdiction="tx-travis-county",
                source_scope="county",
            )
        self.assertEqual(result.parsed_record_count, 0)
        parsed_warning = models.IngestParsedRecord.objects.filter(orchestration_run_id=result.run_id, status="warning").first()
        self.assertIsNotNone(parsed_warning)
        self.assertIn("group_member_ids", parsed_warning.provenance_json)
        members = models.IngestArtifactMember.objects.filter(orchestration_run_id=result.run_id)
        self.assertTrue(all(row.status == "unsupported" for row in members))

    def test_parsed_records_link_back_with_provenance(self):
        with mock.patch("xyn_orchestrator.ingestion.fetch.requests.get") as mocked_get:
            mocked_get.return_value = _MockHttpResponse(
                url="https://example.com/data.csv",
                headers={"content-type": "text/csv"},
                chunks=[b"id,name\n1,alpha\n"],
            )
            result = IngestionCoordinator().ingest_from_url(
                source_connector=self.source,
                source_url="https://example.com/data.csv",
                jurisdiction="tx-travis-county",
                source_scope="county",
            )
        parsed = models.IngestParsedRecord.objects.filter(orchestration_run_id=result.run_id).first()
        self.assertIsNotNone(parsed)
        link = models.ProvenanceLink.objects.filter(
            workspace=self.workspace,
            relationship_type="ingest_parsed_from",
            target_ref_json__object_family="ingest_parsed_record",
            target_ref_json__object_id=str(parsed.id),
        ).first()
        self.assertIsNotNone(link)
