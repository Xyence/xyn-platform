import io
import json
import os
import tempfile
import zipfile
from xml.sax.saxutils import escape
from unittest import mock

from django.conf import settings
from django.test import TestCase

from xyn_orchestrator import models
from xyn_orchestrator.ingestion.archive import ZipArchiveExpander
from xyn_orchestrator.ingestion.classification import classify_file
from xyn_orchestrator.ingestion.coordinator import IngestionCoordinator
from xyn_orchestrator.ingestion.fetch import HttpArtifactFetcher
from xyn_orchestrator.ingestion.interfaces import (
    FILE_KIND_FILE_GDB,
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


class _CmdResult:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeShape:
    def __init__(self, geom):
        self.__geo_interface__ = geom


class _FakeShapeRecord:
    def __init__(self, geom, record):
        self.shape = _FakeShape(geom)
        self.record = record


class _FakeShapefileReader:
    def __init__(self, records):
        self.fields = [("DeletionFlag", "C", 1, 0), ("id", "N", 18, 0), ("owner", "C", 60, 0)]
        self._records = records

    def shapeRecords(self):
        return self._records


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

    def _xlsx_bytes(self, *, sheets: list[tuple[str, list[list[str]]]]) -> bytes:
        workbook_sheets = []
        workbook_rels = []
        sheet_xml = {}
        for index, (name, rows) in enumerate(sheets, start=1):
            rid = f"rId{index}"
            workbook_sheets.append(f'<sheet name="{escape(name)}" sheetId="{index}" r:id="{rid}"/>')
            workbook_rels.append(
                f'<Relationship Id="{rid}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                f'Target="worksheets/sheet{index}.xml"/>'
            )
            row_parts: list[str] = []
            for row_number, row in enumerate(rows, start=1):
                cell_parts: list[str] = []
                for col_number, value in enumerate(row, start=1):
                    col = chr(ord("A") + col_number - 1)
                    cell_parts.append(f'<c r="{col}{row_number}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
                row_parts.append(f'<row r="{row_number}">{"".join(cell_parts)}</row>')
            sheet_xml[index] = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f'<sheetData>{"".join(row_parts)}</sheetData>'
                "</worksheet>"
            )

        workbook_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets>{"".join(workbook_sheets)}</sheets>'
            "</workbook>"
        )
        rels_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'{"".join(workbook_rels)}'
            "</Relationships>"
        )
        content_types = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            + "".join(
                f'<Override PartName="/xl/worksheets/sheet{idx}.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                for idx in sheet_xml.keys()
            )
            + "</Types>"
        )

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types)
            archive.writestr("_rels/.rels", "")
            archive.writestr("xl/workbook.xml", workbook_xml)
            archive.writestr("xl/_rels/workbook.xml.rels", rels_xml)
            for idx, xml in sheet_xml.items():
                archive.writestr(f"xl/worksheets/sheet{idx}.xml", xml)
        return buf.getvalue()

    def test_file_classification_matrix(self):
        self.assertEqual(classify_file(filename="bundle.zip").kind, FILE_KIND_ZIP)
        self.assertEqual(classify_file(filename="rows.csv").kind, FILE_KIND_CSV)
        self.assertEqual(classify_file(filename="shape.shp").kind, FILE_KIND_SHP)
        self.assertEqual(classify_file(filename="map.geojson").kind, FILE_KIND_GEOJSON)
        self.assertEqual(classify_file(filename="county.gdb").kind, FILE_KIND_FILE_GDB)
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

    def test_ingestion_fetch_is_blocked_by_governance_precheck(self):
        self.source.governance_json = {"legal_status": "prohibited"}
        self.source.save(update_fields=["governance_json", "updated_at"])
        result = IngestionCoordinator().ingest_from_url(
            source_connector=self.source,
            source_url="https://example.com/data.csv",
            jurisdiction="tx-travis-county",
            source_scope="county",
        )
        run = models.OrchestrationRun.objects.get(id=result.run_id)
        self.assertEqual(run.status, "failed")
        self.assertEqual(result.parsed_record_count, 0)
        self.assertEqual(result.artifact_record_id, "")
        ingestion_meta = (run.metadata_json or {}).get("ingestion", {})
        self.assertEqual((ingestion_meta.get("governance_decision") or {}).get("reason_code"), "governance.legal_prohibited")

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

    def test_grouped_shapefile_bundle_parses_features_with_grouped_provenance(self):
        records = [
            _FakeShapeRecord({"type": "Point", "coordinates": [-97.0, 30.0]}, [1, "Alpha LLC"]),
            _FakeShapeRecord({"type": "Point", "coordinates": [-97.1, 30.1]}, [2, "Beta LLC"]),
        ]
        fake_module = type("FakeShapefile", (), {"Reader": lambda **kwargs: _FakeShapefileReader(records)})
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("parcel/blocks.shp", b"fake-shp")
            archive.writestr("parcel/blocks.dbf", b"fake-dbf")
            archive.writestr("parcel/blocks.shx", b"fake-shx")
            archive.writestr("parcel/blocks.prj", "PROJCS[...]")
        with (
            mock.patch("xyn_orchestrator.ingestion.fetch.requests.get") as mocked_get,
            mock.patch("xyn_orchestrator.ingestion.parsers._load_pyshp_module", return_value=fake_module),
        ):
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
        self.assertEqual(result.parsed_record_count, 2)
        parsed_rows = list(models.IngestParsedRecord.objects.filter(orchestration_run_id=result.run_id, status="ok").order_by("record_index"))
        self.assertEqual(len(parsed_rows), 2)
        self.assertEqual(parsed_rows[0].provenance_json.get("target_type"), "grouped")
        self.assertTrue(parsed_rows[0].provenance_json.get("group_member_ids"))
        self.assertEqual(parsed_rows[0].normalized_payload_json.get("attributes", {}).get("owner"), "Alpha LLC")

    def test_grouped_shapefile_incomplete_bundle_is_invalid_grouped_input(self):
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("parcel/blocks.shp", b"fake-shp")
            archive.writestr("parcel/blocks.dbf", b"fake-dbf")
        with mock.patch("xyn_orchestrator.ingestion.fetch.requests.get") as mocked_get:
            mocked_get.return_value = _MockHttpResponse(
                url="https://example.com/parcel-incomplete.zip",
                headers={"content-type": "application/zip", "content-length": str(len(zip_buf.getvalue()))},
                chunks=[zip_buf.getvalue()],
            )
            result = IngestionCoordinator().ingest_from_url(
                source_connector=self.source,
                source_url="https://example.com/parcel-incomplete.zip",
                jurisdiction="tx-travis-county",
                source_scope="county",
            )
        parsed_warning = models.IngestParsedRecord.objects.filter(orchestration_run_id=result.run_id, status="warning").first()
        self.assertIsNotNone(parsed_warning)
        self.assertEqual(parsed_warning.warnings_json[0]["category"], "invalid_grouped_input")
        self.assertIn("missing required", parsed_warning.failure_reason)

    def test_grouped_shapefile_missing_prj_is_warning_not_failure(self):
        records = [_FakeShapeRecord({"type": "Point", "coordinates": [-97.0, 30.0]}, [1, "Alpha LLC"])]
        fake_module = type("FakeShapefile", (), {"Reader": lambda **kwargs: _FakeShapefileReader(records)})
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("parcel/blocks.shp", b"fake-shp")
            archive.writestr("parcel/blocks.dbf", b"fake-dbf")
            archive.writestr("parcel/blocks.shx", b"fake-shx")
        with (
            mock.patch("xyn_orchestrator.ingestion.fetch.requests.get") as mocked_get,
            mock.patch("xyn_orchestrator.ingestion.parsers._load_pyshp_module", return_value=fake_module),
        ):
            mocked_get.return_value = _MockHttpResponse(
                url="https://example.com/parcel-no-prj.zip",
                headers={"content-type": "application/zip", "content-length": str(len(zip_buf.getvalue()))},
                chunks=[zip_buf.getvalue()],
            )
            result = IngestionCoordinator().ingest_from_url(
                source_connector=self.source,
                source_url="https://example.com/parcel-no-prj.zip",
                jurisdiction="tx-travis-county",
                source_scope="county",
            )
        row = models.IngestParsedRecord.objects.filter(orchestration_run_id=result.run_id, status="ok").first()
        self.assertIsNotNone(row)
        codes = [entry.get("code") for entry in (row.warnings_json or [])]
        self.assertIn("shapefile.missing_prj", codes)

    def test_xlsx_parsing_via_coordinator_with_sheet_row_provenance(self):
        payload = self._xlsx_bytes(
            sheets=[
                ("Parcels", [["parcel_id", "owner"], ["101", "Alpha LLC"], ["102", "Beta Trust"]]),
                ("Notes", [["id", "text"], ["1", "hello"]]),
            ]
        )
        with mock.patch("xyn_orchestrator.ingestion.fetch.requests.get") as mocked_get:
            mocked_get.return_value = _MockHttpResponse(
                url="https://example.com/data.xlsx",
                headers={"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
                chunks=[payload],
            )
            result = IngestionCoordinator().ingest_from_url(
                source_connector=self.source,
                source_url="https://example.com/data.xlsx",
                jurisdiction="tx-travis-county",
                source_scope="county",
            )
        rows = models.IngestParsedRecord.objects.filter(orchestration_run_id=result.run_id).order_by("record_index", "created_at")
        self.assertEqual(rows.count(), 3)
        first = rows.first()
        self.assertEqual(first.provenance_json.get("sheet"), "Parcels")
        self.assertEqual(first.provenance_json.get("row_number"), 2)
        self.assertEqual(first.normalized_payload_json.get("fields", {}).get("owner"), "Alpha LLC")

    def test_xlsx_malformed_payload_is_persisted_as_parse_error(self):
        with mock.patch("xyn_orchestrator.ingestion.fetch.requests.get") as mocked_get:
            mocked_get.return_value = _MockHttpResponse(
                url="https://example.com/bad.xlsx",
                headers={"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
                chunks=[b"not-a-zip"],
            )
            result = IngestionCoordinator().ingest_from_url(
                source_connector=self.source,
                source_url="https://example.com/bad.xlsx",
                jurisdiction="tx-travis-county",
                source_scope="county",
            )
        self.assertEqual(result.parsed_record_count, 0)
        warning = models.IngestParsedRecord.objects.filter(orchestration_run_id=result.run_id).first()
        self.assertIsNotNone(warning)
        self.assertEqual(warning.status, "error")
        self.assertEqual(warning.warnings_json[0]["category"], "parse_error")
        self.assertEqual(warning.warnings_json[0]["code"], "xlsx.invalid_zip")

    def test_xls_remains_explicit_not_implemented(self):
        with mock.patch("xyn_orchestrator.ingestion.fetch.requests.get") as mocked_get:
            mocked_get.return_value = _MockHttpResponse(
                url="https://example.com/data.xls",
                headers={"content-type": "application/octet-stream"},
                chunks=[b"binary-xls"],
            )
            result = IngestionCoordinator().ingest_from_url(
                source_connector=self.source,
                source_url="https://example.com/data.xls",
                jurisdiction="tx-travis-county",
                source_scope="county",
            )
        warning = models.IngestParsedRecord.objects.filter(orchestration_run_id=result.run_id, status="warning").first()
        self.assertIsNotNone(warning)
        self.assertEqual(warning.warnings_json[0]["category"], "not_implemented")

    def test_access_parser_not_installed_is_explicit(self):
        with (
            mock.patch("xyn_orchestrator.ingestion.fetch.requests.get") as mocked_get,
            mock.patch("xyn_orchestrator.ingestion.parsers._mdb_tools_available", return_value=False),
        ):
            mocked_get.return_value = _MockHttpResponse(
                url="https://example.com/parcel.mdb",
                headers={"content-type": "application/octet-stream"},
                chunks=[b"binary-mdb"],
            )
            result = IngestionCoordinator().ingest_from_url(
                source_connector=self.source,
                source_url="https://example.com/parcel.mdb",
                jurisdiction="tx-travis-county",
                source_scope="county",
            )
        warning = models.IngestParsedRecord.objects.filter(orchestration_run_id=result.run_id, status="warning").first()
        self.assertIsNotNone(warning)
        self.assertEqual(warning.warnings_json[0]["category"], "parser_not_installed")

    def test_access_parser_parses_single_and_multiple_tables(self):
        cmd_results = [
            _CmdResult(stdout="parcels\nowners\n"),
            _CmdResult(stdout="id,address\n1,100 Main\n"),
            _CmdResult(stdout="id,name\n1,Alpha LLC\n2,Beta LLC\n"),
        ]
        with (
            mock.patch("xyn_orchestrator.ingestion.fetch.requests.get") as mocked_get,
            mock.patch("xyn_orchestrator.ingestion.parsers._mdb_tools_available", return_value=True),
            mock.patch("xyn_orchestrator.ingestion.parsers._run_mdb_command", side_effect=cmd_results),
        ):
            mocked_get.return_value = _MockHttpResponse(
                url="https://example.com/parcel.accdb",
                headers={"content-type": "application/octet-stream"},
                chunks=[b"binary-access"],
            )
            result = IngestionCoordinator().ingest_from_url(
                source_connector=self.source,
                source_url="https://example.com/parcel.accdb",
                jurisdiction="tx-travis-county",
                source_scope="county",
            )
        self.assertEqual(result.parsed_record_count, 3)
        rows = list(models.IngestParsedRecord.objects.filter(orchestration_run_id=result.run_id, status="ok").order_by("record_index"))
        self.assertEqual(rows[0].provenance_json.get("table"), "parcels")
        self.assertEqual(rows[1].provenance_json.get("table"), "owners")

    def test_access_parser_partial_table_failure_still_emits_successful_rows(self):
        cmd_results = [
            _CmdResult(stdout="parcels\nowners\n"),
            _CmdResult(returncode=1, stderr="failed owners export"),
            _CmdResult(stdout="id,address\n1,100 Main\n"),
        ]
        with (
            mock.patch("xyn_orchestrator.ingestion.fetch.requests.get") as mocked_get,
            mock.patch("xyn_orchestrator.ingestion.parsers._mdb_tools_available", return_value=True),
            mock.patch("xyn_orchestrator.ingestion.parsers._run_mdb_command", side_effect=cmd_results),
        ):
            mocked_get.return_value = _MockHttpResponse(
                url="https://example.com/partial.mdb",
                headers={"content-type": "application/octet-stream"},
                chunks=[b"binary-partial"],
            )
            result = IngestionCoordinator().ingest_from_url(
                source_connector=self.source,
                source_url="https://example.com/partial.mdb",
                jurisdiction="tx-travis-county",
                source_scope="county",
            )
        self.assertEqual(result.parsed_record_count, 1)
        row = models.IngestParsedRecord.objects.filter(orchestration_run_id=result.run_id, status="ok").first()
        self.assertIsNotNone(row)
        codes = [entry.get("code") for entry in (row.warnings_json or [])]
        self.assertIn("access.table_export_failed", codes)

    def test_xml_and_file_gdb_emit_explicit_unsupported_or_not_implemented(self):
        fixtures = [
            ("data.xml", b"<root><item>1</item></root>", "unsupported_format"),
            ("county.gdb", b"gdb", "not_implemented"),
        ]
        for filename, payload, expected_category in fixtures:
            with self.subTest(filename=filename):
                with mock.patch("xyn_orchestrator.ingestion.fetch.requests.get") as mocked_get:
                    mocked_get.return_value = _MockHttpResponse(
                        url=f"https://example.com/{filename}",
                        headers={"content-type": "application/octet-stream"},
                        chunks=[payload],
                    )
                    result = IngestionCoordinator().ingest_from_url(
                        source_connector=self.source,
                        source_url=f"https://example.com/{filename}",
                        jurisdiction="tx-travis-county",
                        source_scope="county",
                    )
                warning = models.IngestParsedRecord.objects.filter(orchestration_run_id=result.run_id, status="warning").first()
                self.assertIsNotNone(warning)
                self.assertEqual(warning.warnings_json[0]["category"], expected_category)

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

    def test_unchanged_artifact_results_in_skipped_no_op_run(self):
        with mock.patch("xyn_orchestrator.ingestion.fetch.requests.get") as mocked_get:
            mocked_get.return_value = _MockHttpResponse(
                url="https://example.com/data.csv",
                headers={"content-type": "text/csv"},
                chunks=[b"id,name\n1,alpha\n"],
            )
            first = IngestionCoordinator().ingest_from_url(
                source_connector=self.source,
                source_url="https://example.com/data.csv",
                jurisdiction="tx-travis-county",
                source_scope="county",
            )
            second = IngestionCoordinator().ingest_from_url(
                source_connector=self.source,
                source_url="https://example.com/data.csv",
                jurisdiction="tx-travis-county",
                source_scope="county",
            )
        self.assertEqual(first.parsed_record_count, 1)
        self.assertEqual(second.parsed_record_count, 0)
        second_run = models.OrchestrationRun.objects.get(id=second.run_id)
        self.assertEqual(second_run.status, "skipped")
        self.assertEqual(second_run.metadata_json.get("ingestion", {}).get("outcome"), "no_op")
        self.assertFalse(second_run.metadata_json.get("ingestion", {}).get("content_changed", True))
        self.assertEqual(second_run.metrics_json.get("ingestion", {}).get("parse_targets"), 0)

    def test_repeated_identical_run_does_not_duplicate_parsed_records(self):
        with mock.patch("xyn_orchestrator.ingestion.fetch.requests.get") as mocked_get:
            mocked_get.return_value = _MockHttpResponse(
                url="https://example.com/data.csv",
                headers={"content-type": "text/csv"},
                chunks=[b"id,name\n1,alpha\n2,beta\n"],
            )
            first = IngestionCoordinator().ingest_from_url(
                source_connector=self.source,
                source_url="https://example.com/data.csv",
                jurisdiction="tx-travis-county",
                source_scope="county",
            )
            second = IngestionCoordinator().ingest_from_url(
                source_connector=self.source,
                source_url="https://example.com/data.csv",
                jurisdiction="tx-travis-county",
                source_scope="county",
            )
        self.assertEqual(first.parsed_record_count, 2)
        self.assertEqual(second.parsed_record_count, 0)
        self.assertEqual(
            models.IngestParsedRecord.objects.filter(source_connector=self.source, parser_name="csv_tsv_parser").count(),
            2,
        )

    def test_partial_run_with_mixed_success_and_unsupported_outcomes(self):
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("bundle/rows.csv", "id,name\n1,alpha\n")
            archive.writestr("bundle/shape.shp", b"fake-shp")
            archive.writestr("bundle/shape.dbf", b"fake-dbf")
            archive.writestr("bundle/shape.shx", b"fake-shx")
        with (
            mock.patch("xyn_orchestrator.ingestion.fetch.requests.get") as mocked_get,
            mock.patch("xyn_orchestrator.ingestion.parsers._load_pyshp_module", return_value=None),
        ):
            mocked_get.return_value = _MockHttpResponse(
                url="https://example.com/mixed.zip",
                headers={"content-type": "application/zip"},
                chunks=[zip_buf.getvalue()],
            )
            result = IngestionCoordinator().ingest_from_url(
                source_connector=self.source,
                source_url="https://example.com/mixed.zip",
                jurisdiction="tx-travis-county",
                source_scope="county",
            )
        run = models.OrchestrationRun.objects.get(id=result.run_id)
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(run.metadata_json.get("ingestion", {}).get("outcome"), "partial")
        self.assertEqual(run.metrics_json.get("ingestion", {}).get("parsed_records_created"), 1)
        self.assertGreaterEqual(run.metrics_json.get("ingestion", {}).get("unsupported_outcomes"), 1)

    def test_parsed_provenance_marks_direct_member_and_grouped_targets(self):
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
        direct = models.IngestParsedRecord.objects.filter(orchestration_run_id=result.run_id, status="ok").first()
        self.assertEqual(direct.provenance_json.get("target_type"), "file")

        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("parcel/blocks.shp", b"fake-shp")
            archive.writestr("parcel/blocks.dbf", b"fake-dbf")
            archive.writestr("parcel/blocks.shx", b"fake-shx")
        with (
            mock.patch("xyn_orchestrator.ingestion.fetch.requests.get") as mocked_get,
            mock.patch("xyn_orchestrator.ingestion.parsers._load_pyshp_module", return_value=None),
        ):
            mocked_get.return_value = _MockHttpResponse(
                url="https://example.com/parcel.zip",
                headers={"content-type": "application/zip"},
                chunks=[zip_buf.getvalue()],
            )
            grouped_result = IngestionCoordinator().ingest_from_url(
                source_connector=self.source,
                source_url="https://example.com/parcel.zip",
                jurisdiction="tx-travis-county",
                source_scope="county",
            )
        grouped = models.IngestParsedRecord.objects.filter(orchestration_run_id=grouped_result.run_id, status="warning").first()
        self.assertEqual(grouped.provenance_json.get("target_type"), "grouped")
        self.assertTrue(grouped.provenance_json.get("group_member_ids"))
