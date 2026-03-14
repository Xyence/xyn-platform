import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from xyn_orchestrator.execution_publish import ExecutionPublishError, publish_dev_task, task_publish_branch
from xyn_orchestrator.managed_storage import managed_workspace_path
from xyn_orchestrator.models import DevTask, ManagedRepository, UserIdentity, Workspace, WorkspaceMembership
from xyn_orchestrator.xyn_api import dev_task_detail, dev_task_publish


class ExecutionPublishTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="publish-admin", email="publish@example.com", password="password")
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example.com",
            subject="publish-admin",
            email="publish@example.com",
        )
        self.workspace = Workspace.objects.create(name="Execution Publish", slug="execution-publish")
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user_identity=self.identity,
            role="admin",
            termination_authority=True,
        )
        self.remote = Path(self.tempdir.name) / "remote.git"
        subprocess.run(["git", "init", "--bare", self.remote], check=True, capture_output=True, text=True)
        self.repository = ManagedRepository.objects.create(
            slug="xyn-platform",
            display_name="Xyn Platform",
            remote_url=str(self.remote),
            default_branch="develop",
            is_active=True,
            auth_mode="local",
        )
        self.task = DevTask.objects.create(
            title="Publish scheduler workspace",
            task_type="codegen",
            status="completed",
            priority=0,
            max_attempts=3,
            source_entity_type="blueprint",
            source_entity_id=uuid.uuid4(),
            work_item_id="wi-publish",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_brief={"schema_version": "v1", "summary": "Publish scheduler seam"},
            created_by=self.user,
            updated_by=self.user,
        )

    def _request(self, path: str, *, method: str = "post"):
        request = getattr(self.factory, method.lower())(path)
        request.user = self.user
        return request

    def _auth_patches(self):
        return (
            mock.patch("xyn_orchestrator.xyn_api._require_staff", return_value=None),
            mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity),
            mock.patch("xyn_orchestrator.xyn_api._resolve_workspace_for_identity", return_value=self.workspace),
        )

    def _workspace_repo(self, *, with_change: bool) -> Path:
        repo_dir = managed_workspace_path("codegen", "tasks", self.task.id, "repos", "xyn-platform")
        repo_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "remote", "add", "origin", str(self.remote)], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "checkout", "-B", "develop"], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "publish@example.com"], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.name", "Publish Test"], cwd=repo_dir, check=True, capture_output=True, text=True)
        (repo_dir / "scheduler.py").write_text("value = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "scheduler.py"], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_dir, check=True, capture_output=True, text=True)
        if with_change:
            (repo_dir / "scheduler.py").write_text("value = 2\n", encoding="utf-8")
        return repo_dir

    def test_publish_commit_creates_deterministic_task_branch(self):
        with mock.patch.dict(os.environ, {"XYN_WORKSPACE_ROOT": self.tempdir.name}, clear=False):
            repo_dir = self._workspace_repo(with_change=True)
            result = publish_dev_task(self.task, user=self.user, push=False)
        self.task.refresh_from_db()
        self.assertEqual(result["status"], "committed")
        self.assertEqual(result["branch"], task_publish_branch(self.task))
        self.assertEqual(subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir, check=True, capture_output=True, text=True).stdout.strip(), task_publish_branch(self.task))
        self.assertTrue(result["commit"])
        log = subprocess.run(["git", "log", "-1", "--pretty=%s"], cwd=repo_dir, check=True, capture_output=True, text=True).stdout.strip()
        self.assertIn(f"Xyn task {self.task.id}", log)
        self.assertEqual((self.task.execution_policy or {}).get("publish", {}).get("push_status"), "not_pushed")

    def test_publish_pushes_task_branch_to_remote(self):
        with mock.patch.dict(os.environ, {"XYN_WORKSPACE_ROOT": self.tempdir.name}, clear=False):
            self._workspace_repo(with_change=True)
            result = publish_dev_task(self.task, user=self.user, push=True)
        self.assertEqual(result["status"], "pushed")
        branch_ref = subprocess.run(
            ["git", "for-each-ref", "--format=%(refname:short)", f"refs/heads/{task_publish_branch(self.task)}"],
            cwd=self.remote,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(branch_ref, task_publish_branch(self.task))

    def test_publish_no_change_is_graceful(self):
        with mock.patch.dict(os.environ, {"XYN_WORKSPACE_ROOT": self.tempdir.name}, clear=False):
            self._workspace_repo(with_change=False)
            result = publish_dev_task(self.task, user=self.user, push=False)
        self.assertEqual(result["status"], "no_changes")
        self.assertIn("No changes to publish", result["message"])
        self.assertIsNone(result["commit"])

    def test_publish_push_failure_surfaces_cleanly(self):
        with mock.patch.dict(os.environ, {"XYN_WORKSPACE_ROOT": self.tempdir.name}, clear=False):
            self._workspace_repo(with_change=True)
            self.repository.remote_url = str(Path(self.tempdir.name) / "missing" / "remote.git")
            self.repository.save(update_fields=["remote_url", "updated_at"])
            with self.assertRaises(ExecutionPublishError):
                publish_dev_task(self.task, user=self.user, push=True)
        self.task.refresh_from_db()
        publish = (self.task.execution_policy or {}).get("publish", {})
        self.assertEqual(publish.get("status"), "push_failed")
        self.assertEqual(publish.get("push_status"), "failed")
        self.assertTrue(publish.get("commit"))

    def test_publish_endpoint_returns_publish_state(self):
        with mock.patch.dict(os.environ, {"XYN_WORKSPACE_ROOT": self.tempdir.name}, clear=False):
            self._workspace_repo(with_change=True)
            request = self._request(f"/xyn/api/dev-tasks/{self.task.id}/publish?push=1")
            with self._auth_patches()[0], self._auth_patches()[1], self._auth_patches()[2]:
                response = dev_task_publish(request, str(self.task.id))
                detail = dev_task_detail(self._request(f"/xyn/api/dev-tasks/{self.task.id}", method="get"), str(self.task.id))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["status"], "pushed")
        self.assertEqual(payload["work_item"]["publish_state"]["push_status"], "pushed")
        detail_payload = json.loads(detail.content)
        self.assertEqual(detail_payload["publish_state"]["branch"], task_publish_branch(self.task))
        self.assertTrue(detail_payload["publish_state"]["commit"])
