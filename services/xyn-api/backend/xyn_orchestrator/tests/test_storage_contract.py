import json
import os
import tempfile
import uuid

from django.test import RequestFactory, TestCase, override_settings
from unittest import mock

from xyn_orchestrator.models import (
    OrchestrationJobDefinition,
    OrchestrationPipeline,
    OrchestrationRun,
    ProvenanceLink,
    SourceConnector,
    Workspace,
)
from xyn_orchestrator.orchestration.interfaces import ExecutionScope, RunCreateRequest, RunTrigger
from xyn_orchestrator.orchestration.lifecycle import OrchestrationLifecycleService
from xyn_orchestrator.storage import (
    IngestStorageService,
    IngestWorkspaceManager,
    LocalDurableArtifactStore,
    RetentionClass,
    SnapshotType,
    snapshot_output_record,
)
from xyn_orchestrator.xyn_api import ingest_artifact_detail, ingest_artifacts_collection


class StorageContractTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        suffix = uuid.uuid4().hex[:6]
        self.workspace = Workspace.objects.create(slug=f"storage-{suffix}", name="Storage Workspace")
        self.source = SourceConnector.objects.create(
            workspace=self.workspace,
            key=f"source-{suffix}",
            name="County Feed",
            source_type="records_feed",
            source_mode="file_upload",
            refresh_cadence_seconds=0,
            configuration_json={},
            lifecycle_state="registered",
            health_status="unknown",
        )

    def test_ingest_workspace_lifecycle(self):
        with tempfile.TemporaryDirectory() as temp_root:
            os.environ["XYN_WORKSPACE_ROOT"] = temp_root
            manager = IngestWorkspaceManager()
            workspace = manager.create(
                workspace_id=str(self.workspace.id),
                source_key="county",
                run_key="run-1",
                retention_class=RetentionClass.EPHEMERAL.value,
            )
            self.assertTrue(workspace.path.exists())
            resolved = manager.resolve(workspace, "extracted", "data.shp")
            self.assertTrue(str(resolved).endswith("extracted/data.shp"))
            self.assertTrue(manager.cleanup(workspace))
            self.assertFalse(workspace.path.exists())

    def test_ingest_workspace_cleanup_for_run(self):
        with tempfile.TemporaryDirectory() as temp_root:
            os.environ["XYN_WORKSPACE_ROOT"] = temp_root
            manager = IngestWorkspaceManager()
            workspace = manager.create(
                workspace_id=str(self.workspace.id),
                source_key="county",
                run_key="run-2",
                retention_class=RetentionClass.EPHEMERAL.value,
            )
            self.assertTrue(workspace.path.exists())
            removed = manager.cleanup_for_run(
                workspace_id=str(self.workspace.id),
                source_key="county",
                run_key="run-2",
                retention_class=RetentionClass.EPHEMERAL.value,
            )
            self.assertTrue(removed)
            self.assertFalse(workspace.path.exists())

    def test_store_snapshot_records_metadata_and_provenance(self):
        with tempfile.TemporaryDirectory() as temp_root:
            with override_settings(MEDIA_ROOT=temp_root):
                service = IngestStorageService(durable_store=LocalDurableArtifactStore())
                result = service.store_snapshot_bytes(
                    workspace=self.workspace,
                    name="county.zip",
                    content_type="application/zip",
                    content=b"zipdata",
                    snapshot_type=SnapshotType.RAW,
                    retention_class=RetentionClass.SNAPSHOT,
                    source_connector=self.source,
                    metadata={"format": "shapefile"},
                )

        record = result.record
        self.assertEqual(record.workspace_id, self.workspace.id)
        self.assertEqual(record.source_connector_id, self.source.id)
        self.assertEqual(record.snapshot_type, SnapshotType.RAW.value)
        self.assertEqual(record.retention_class, RetentionClass.SNAPSHOT.value)
        self.assertTrue(record.sha256)
        self.assertEqual(record.metadata_json.get("format"), "shapefile")

        link = ProvenanceLink.objects.filter(workspace=self.workspace, relationship_type="ingest_snapshot").first()
        self.assertIsNotNone(link)
        self.assertEqual(link.source_type, "source_connector")
        self.assertEqual(link.target_type, "runtime_artifact")

    def test_snapshot_output_change_token_and_provenance_chain(self):
        pipeline = OrchestrationPipeline.objects.create(
            workspace=self.workspace,
            key=f"ingest-{uuid.uuid4().hex[:6]}",
            name="Ingest Pipeline",
            stale_run_timeout_seconds=900,
        )
        job = OrchestrationJobDefinition.objects.create(
            pipeline=pipeline,
            job_key="source_refresh",
            stage_key="source_refresh",
            name="Source Refresh",
            handler_key="jobs.source.refresh",
        )
        lifecycle = OrchestrationLifecycleService()
        run = lifecycle.create_run(
            RunCreateRequest(
                workspace_id=str(self.workspace.id),
                pipeline_key=pipeline.key,
                trigger=RunTrigger(trigger_cause="manual", trigger_key="test"),
                run_type="ingest.source_refresh",
                target_ref={"target_type": "source_connector", "target_id": str(self.source.id), "source_key": self.source.key},
                initiated_by_id="",
                scope=ExecutionScope(jurisdiction="", source=self.source.key),
                metadata={"correlation_id": "corr"},
            )
        )
        job_run = run.job_runs.first()
        self.assertIsNotNone(job_run)

        with tempfile.TemporaryDirectory() as temp_root:
            with override_settings(MEDIA_ROOT=temp_root):
                service = IngestStorageService(durable_store=LocalDurableArtifactStore())
                stored = service.store_snapshot_bytes(
                    workspace=self.workspace,
                    name="raw.zip",
                    content_type="application/zip",
                    content=b"rawdata",
                    snapshot_type=SnapshotType.RAW,
                    retention_class=RetentionClass.SNAPSHOT,
                    source_connector=self.source,
                    orchestration_run=run,
                    scope_source=self.source.key,
                )

        output = snapshot_output_record(stored=stored, output_key="raw_snapshot")
        lifecycle.mark_job_running(job_run_id=str(job_run.id))
        lifecycle.mark_job_succeeded(job_run_id=str(job_run.id), outputs=[output])
        job_run.refresh_from_db()
        output_row = job_run.outputs.first()
        self.assertIsNotNone(output_row)
        self.assertEqual(output_row.output_change_token, stored.record.sha256)
        self.assertIsNone(output_row.artifact_id)
        self.assertEqual(output_row.metadata_json.get("runtime_artifact_id"), str(stored.record.artifact_id))

        artifact_link = ProvenanceLink.objects.filter(
            workspace=self.workspace,
            relationship_type="ingest_snapshot_output",
            source_type="runtime_artifact",
            target_type="orchestration_job_output",
        ).first()
        self.assertIsNotNone(artifact_link)

    def test_ingest_artifact_api_listing(self):
        with tempfile.TemporaryDirectory() as temp_root:
            with override_settings(MEDIA_ROOT=temp_root):
                service = IngestStorageService(durable_store=LocalDurableArtifactStore())
                stored = service.store_snapshot_bytes(
                    workspace=self.workspace,
                    name="raw.zip",
                    content_type="application/zip",
                    content=b"rawdata",
                    snapshot_type=SnapshotType.RAW,
                    retention_class=RetentionClass.SNAPSHOT,
                    source_connector=self.source,
                    scope_source=self.source.key,
                )
        request = self.factory.get(
            "/xyn/api/ingest-artifacts",
            data={"workspace_id": str(self.workspace.id), "source_id": str(self.source.id)},
        )
        request.user = mock.Mock(is_authenticated=True)
        with (
            mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=mock.Mock()),
            mock.patch("xyn_orchestrator.xyn_api._orchestration_workspace", return_value=self.workspace),
            mock.patch("xyn_orchestrator.xyn_api._require_workspace_capabilities", return_value=True),
        ):
            response = ingest_artifacts_collection(request)
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(len(payload["artifacts"]), 1)
        self.assertEqual(payload["artifacts"][0]["artifact_id"], str(stored.record.artifact_id))

        detail_request = self.factory.get(
            f"/xyn/api/ingest-artifacts/{stored.record.id}",
            data={"workspace_id": str(self.workspace.id)},
        )
        detail_request.user = mock.Mock(is_authenticated=True)
        with (
            mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=mock.Mock()),
            mock.patch("xyn_orchestrator.xyn_api._orchestration_workspace", return_value=self.workspace),
            mock.patch("xyn_orchestrator.xyn_api._require_workspace_capabilities", return_value=True),
        ):
            detail_response = ingest_artifact_detail(detail_request, str(stored.record.id))
        self.assertEqual(detail_response.status_code, 200)
        detail_payload = json.loads(detail_response.content)
        self.assertEqual(detail_payload["artifact_id"], str(stored.record.artifact_id))
