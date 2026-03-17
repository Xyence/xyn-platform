import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from xyn_orchestrator.blueprints import _write_run_artifact
from xyn_orchestrator.managed_storage import (
    codegen_task_workspace,
    load_local_artifact_json,
    managed_workspace_path,
    stale_workspace_candidates,
    store_local_artifact,
)
from xyn_orchestrator.models import Run
from xyn_orchestrator.worker_tasks import _write_artifact


class ManagedStorageTests(SimpleTestCase):
    @override_settings(MEDIA_URL="/media/")
    def test_store_local_artifact_round_trips_through_managed_artifact_root(self):
        with tempfile.TemporaryDirectory() as tempdir, override_settings(MEDIA_ROOT=tempdir):
            stored = store_local_artifact("run_artifacts", "run-1", "summary.json", {"ok": True})
            self.assertEqual(stored.provider, "local")
            self.assertTrue(stored.path.startswith(tempdir))
            self.assertEqual(stored.key, "run_artifacts/run-1/summary.json")
            self.assertEqual(load_local_artifact_json(storage_path=stored.path), {"ok": True})

    def test_codegen_task_workspace_is_idempotent_and_sanitized(self):
        with tempfile.TemporaryDirectory() as tempdir, mock.patch.dict(
            "os.environ",
            {"XYN_WORKSPACE_ROOT": tempdir},
            clear=False,
        ):
            first = codegen_task_workspace("../Task 42", reset=True)
            second = codegen_task_workspace("../Task 42")
            self.assertEqual(first, second)
            self.assertTrue(str(first).startswith(tempdir))
            self.assertEqual(first, managed_workspace_path("codegen", "tasks", "../Task 42"))
            self.assertTrue((first / ".xyn-workspace.json").exists())

    def test_stale_workspace_candidates_respect_retention_hint(self):
        with tempfile.TemporaryDirectory() as tempdir, mock.patch.dict(
            "os.environ",
            {"XYN_WORKSPACE_ROOT": tempdir, "XYN_WORKSPACE_RETENTION_DAYS": "3"},
            clear=False,
        ):
            workspace = codegen_task_workspace("stale-task", reset=True)
            old = datetime.now(timezone.utc) - timedelta(days=5)
            old_ts = old.timestamp()
            import os

            os.utime(workspace, (old_ts, old_ts))
            os.utime(workspace / ".xyn-workspace.json", (old_ts, old_ts))
            candidates = stale_workspace_candidates(now=datetime.now(timezone.utc))
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].relative_path, "codegen/tasks/stale-task")


class ManagedStorageIntegrationTests(TestCase):
    def test_write_run_artifact_uses_managed_artifact_root(self):
        with tempfile.TemporaryDirectory() as artifact_root, override_settings(MEDIA_ROOT=artifact_root, MEDIA_URL="/media/"):
            run = Run.objects.create(
                entity_type="goal",
                entity_id=uuid.uuid4(),
                status="running",
                summary="artifact test",
            )
            artifact = _write_run_artifact(run, "implementation_plan.json", {"ok": True}, "implementation_plan")
            self.assertEqual((artifact.metadata_json or {}).get("provider"), "local")
            self.assertTrue(str((artifact.metadata_json or {}).get("path") or "").startswith(artifact_root))
            self.assertTrue(Path((artifact.metadata_json or {}).get("path")).exists())
            self.assertEqual(load_local_artifact_json(storage_path=(artifact.metadata_json or {}).get("path") or ""), {"ok": True})

    def test_worker_write_artifact_uses_managed_artifact_root(self):
        with tempfile.TemporaryDirectory() as artifact_root, override_settings(MEDIA_ROOT=artifact_root, MEDIA_URL="/media/"):
            url = _write_artifact("run-2", "stdout.log", "hello")
            self.assertEqual(url, "/media/run_artifacts/run-2/stdout.log")
            self.assertTrue(Path(artifact_root, "run_artifacts", "run-2", "stdout.log").exists())
