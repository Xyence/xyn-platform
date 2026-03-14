import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings

from xyn_orchestrator.execution_changes import resolve_dev_task_change_set
from xyn_orchestrator.managed_storage import store_local_artifact
from xyn_orchestrator.models import DevTask, Run, RunArtifact, UserIdentity, Workspace, WorkspaceMembership
from xyn_orchestrator.xyn_api import dev_task_detail


class ExecutionChangeInspectionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="changes-admin", email="changes@example.com", password="password")
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example.com",
            subject="changes-admin",
            email="changes@example.com",
        )
        self.workspace = Workspace.objects.create(name="Execution Changes", slug="execution-changes")
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user_identity=self.identity,
            role="admin",
            termination_authority=True,
        )
        self.task = DevTask.objects.create(
            title="Inspect workspace diff",
            task_type="codegen",
            status="completed",
            priority=0,
            max_attempts=3,
            source_entity_type="blueprint",
            source_entity_id=uuid.uuid4(),
            work_item_id="wi-changes",
            target_repo="xyn-platform",
            target_branch="develop",
            created_by=self.user,
            updated_by=self.user,
        )

    def _request(self, path: str, *, method: str = "get"):
        request = getattr(self.factory, method.lower())(path)
        request.user = self.user
        return request

    def _auth_patches(self):
        return (
            mock.patch("xyn_orchestrator.xyn_api._require_staff", return_value=None),
            mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity),
            mock.patch("xyn_orchestrator.xyn_api._resolve_workspace_for_identity", return_value=self.workspace),
        )

    def _init_repo_with_change(self, *, filename: str = "service.py", initial: str = "print('old')\n", updated: str = "print('new')\n") -> Path:
        repo_dir = Path(self.tempdir.name) / "codegen" / "tasks" / str(self.task.id) / "repos" / "xyn-platform"
        repo_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "checkout", "-B", "develop"], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "changes@example.com"], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.name", "Execution Changes"], cwd=repo_dir, check=True, capture_output=True, text=True)
        (repo_dir / filename).write_text(initial, encoding="utf-8")
        subprocess.run(["git", "add", filename], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_dir, check=True, capture_output=True, text=True)
        (repo_dir / filename).write_text(updated, encoding="utf-8")
        subprocess.run(["git", "add", filename], cwd=repo_dir, check=True, capture_output=True, text=True)
        return repo_dir

    @mock.patch.dict(os.environ, {}, clear=False)
    def test_change_set_is_unavailable_without_repository_target(self):
        self.task.target_repo = ""
        self.task.save(update_fields=["target_repo", "updated_at"])
        with mock.patch.dict(os.environ, {"XYN_WORKSPACE_ROOT": self.tempdir.name}, clear=False):
            payload = resolve_dev_task_change_set(self.task, include_diff=True)
        self.assertFalse(payload["available"])
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["changed_file_count"], 0)

    def test_change_set_reads_managed_workspace_diff(self):
        with mock.patch.dict(os.environ, {"XYN_WORKSPACE_ROOT": self.tempdir.name}, clear=False):
            self._init_repo_with_change()
            payload = resolve_dev_task_change_set(self.task, include_diff=True)
        self.assertTrue(payload["available"])
        self.assertEqual(payload["source"], "workspace")
        self.assertEqual(payload["status"], "changed")
        self.assertEqual(payload["changed_file_count"], 1)
        self.assertEqual(payload["files"][0]["path"], "service.py")
        self.assertEqual(payload["files"][0]["change_type"], "modified")
        self.assertIn("diff --git a/service.py b/service.py", payload["diff_text"])

    @override_settings(MEDIA_URL="/media/")
    def test_change_set_falls_back_to_patch_artifact(self):
        result_run = Run.objects.create(
            entity_type="dev_task",
            entity_id=self.task.id,
            status="succeeded",
            summary="Generated patch",
            created_by=self.user,
        )
        diff_text = """diff --git a/api.py b/api.py
index 1111111..2222222 100644
--- a/api.py
+++ b/api.py
@@ -1 +1 @@
-print("old")
+print("new")
"""
        with mock.patch.dict(os.environ, {"XYN_WORKSPACE_ROOT": self.tempdir.name}, clear=False), override_settings(MEDIA_ROOT=self.tempdir.name):
            stored = store_local_artifact("run_artifacts", result_run.id, "codegen_patch_xyn-platform.diff", diff_text)
            RunArtifact.objects.create(
                run=result_run,
                name="codegen_patch_xyn-platform.diff",
                kind="codegen",
                url=stored.url,
                metadata_json=stored.metadata,
            )
            self.task.result_run = result_run
            self.task.save(update_fields=["result_run", "updated_at"])
            payload = resolve_dev_task_change_set(self.task, include_diff=True)
        self.assertTrue(payload["available"])
        self.assertEqual(payload["source"], "artifact")
        self.assertEqual(payload["changed_file_count"], 1)
        self.assertEqual(payload["files"][0]["path"], "api.py")
        self.assertEqual(payload["patch_artifact_name"], "codegen_patch_xyn-platform.diff")
        self.assertIn("diff --git a/api.py b/api.py", payload["diff_text"])

    def test_dev_task_detail_includes_change_set(self):
        with mock.patch.dict(os.environ, {"XYN_WORKSPACE_ROOT": self.tempdir.name}, clear=False):
            self._init_repo_with_change(filename="worker.py", initial="value = 1\n", updated="value = 2\n")
            request = self._request(f"/xyn/api/dev-tasks/{self.task.id}")
            with self._auth_patches()[0], self._auth_patches()[1], self._auth_patches()[2]:
                response = dev_task_detail(request, str(self.task.id))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["change_set"]["status"], "changed")
        self.assertEqual(payload["change_set"]["changed_file_count"], 1)
        self.assertEqual(payload["change_set"]["files"][0]["path"], "worker.py")
        self.assertIn("diff --git a/worker.py b/worker.py", payload["change_set"]["diff_text"])
