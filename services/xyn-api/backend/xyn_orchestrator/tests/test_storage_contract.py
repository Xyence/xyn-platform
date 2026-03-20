import os
import tempfile
import uuid

from django.test import TestCase, override_settings

from xyn_orchestrator.models import ProvenanceLink, SourceConnector, Workspace
from xyn_orchestrator.storage import IngestStorageService, IngestWorkspaceManager, LocalDurableArtifactStore, RetentionClass, SnapshotType


class StorageContractTests(TestCase):
    def setUp(self):
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
