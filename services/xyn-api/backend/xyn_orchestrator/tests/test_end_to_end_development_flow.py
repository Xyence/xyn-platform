import datetime as dt
import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from xyn_orchestrator.execution_queue import evaluate_dev_task_queue_state
from xyn_orchestrator.managed_storage import managed_workspace_path
from xyn_orchestrator.models import (
    CoordinationThread,
    DevTask,
    ManagedRepository,
    Run,
    RunArtifact,
    UserIdentity,
    Workspace,
    WorkspaceMembership,
)
from xyn_orchestrator.xyn_api import _dispatch_selected_queue_item, dev_task_detail, dev_task_publish


class EndToEndDevelopmentFlowTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)

        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="e2e-dev-admin",
            email="e2e-dev-admin@example.com",
            password="password",
        )
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])

        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example.com",
            subject="e2e-dev-admin",
            email="e2e-dev-admin@example.com",
        )
        self.workspace = Workspace.objects.create(name="E2E Development", slug="e2e-development")
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user_identity=self.identity,
            role="admin",
            termination_authority=True,
        )
        self.thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            title="End-to-End Development",
            description="",
            owner=self.identity,
            priority="high",
            status="queued",
            domain="development",
            execution_policy={"auto_resume": True},
            work_in_progress_limit=1,
            source_conversation_id="thread-e2e",
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
            title="Implement end-to-end scheduler flow",
            task_type="codegen",
            status="queued",
            priority=0,
            max_attempts=3,
            source_entity_type="blueprint",
            source_entity_id=uuid.uuid4(),
            work_item_id="wi-e2e-flow",
            target_repo="xyn-platform",
            target_branch="develop",
            runtime_workspace_id=self.workspace.id,
            execution_brief={
                "schema_version": "v1",
                "summary": "Implement scheduler queue and publish flow",
                "objective": "Ship a narrow scheduler improvement end to end.",
            },
            execution_brief_review_state="approved",
            execution_policy={"require_brief_approval": True},
            coordination_thread=self.thread,
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

    def _workspace_repo(self) -> Path:
        repo_dir = managed_workspace_path("codegen", "tasks", self.task.id, "repos", "xyn-platform")
        repo_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "remote", "add", "origin", str(self.remote)], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "checkout", "-B", "develop"], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "e2e-dev-admin@example.com"], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.name", "E2E Development"], cwd=repo_dir, check=True, capture_output=True, text=True)
        (repo_dir / "scheduler.py").write_text("value = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "scheduler.py"], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_dir, check=True, capture_output=True, text=True)
        (repo_dir / "scheduler.py").write_text("value = 2\n", encoding="utf-8")
        subprocess.run(["git", "add", "scheduler.py"], cwd=repo_dir, check=True, capture_output=True, text=True)
        return repo_dir

    def test_end_to_end_development_flow_from_approval_to_publish(self):
        with mock.patch.dict(os.environ, {"XYN_WORKSPACE_ROOT": self.tempdir.name}, clear=False):
            repo_dir = self._workspace_repo()

            queue_state = evaluate_dev_task_queue_state(self.task)
            self.assertTrue(queue_state.queue_ready)
            self.assertTrue(queue_state.dispatchable)

            with mock.patch(
                "xyn_orchestrator.xyn_api._submit_dev_task_runtime_run",
                return_value={"run_id": "run-e2e", "status": "queued", "work_item_id": self.task.work_item_id},
            ):
                dispatch = _dispatch_selected_queue_item(
                    workspace=self.workspace,
                    task=self.task,
                    user=self.user,
                    identity=self.identity,
                )

            self.assertEqual(dispatch["run_id"], "run-e2e")
            self.thread.refresh_from_db()
            self.assertEqual(self.thread.status, "active")

            result_run = Run.objects.create(
                entity_type="dev_task",
                entity_id=self.task.id,
                status="succeeded",
                summary="Implemented scheduler queue and publish flow",
                created_by=self.user,
                started_at=dt.datetime(2026, 3, 15, 10, 0, tzinfo=dt.timezone.utc),
                finished_at=dt.datetime(2026, 3, 15, 10, 5, tzinfo=dt.timezone.utc),
            )
            RunArtifact.objects.create(
                run=result_run,
                name="final_summary.md",
                kind="summary",
                url="https://example.com/final_summary.md",
                metadata_json={},
            )
            self.task.result_run = result_run
            self.task.status = "completed"
            self.task.save(update_fields=["result_run", "status", "updated_at"])

            detail_request = self._request(f"/xyn/api/dev-tasks/{self.task.id}", method="get")
            with self._auth_patches()[0], self._auth_patches()[1], self._auth_patches()[2]:
                detail_response = dev_task_detail(detail_request, str(self.task.id))
            self.assertEqual(detail_response.status_code, 200)
            detail_payload = json.loads(detail_response.content)
            self.assertEqual(detail_payload["execution_run"]["state"], "completed")
            self.assertEqual(detail_payload["execution_run"]["summary"], "Implemented scheduler queue and publish flow")
            self.assertEqual(detail_payload["change_set"]["status"], "changed")
            self.assertEqual(detail_payload["change_set"]["changed_file_count"], 1)
            self.assertEqual(detail_payload["change_set"]["files"][0]["path"], "scheduler.py")
            self.assertIn("diff --git a/scheduler.py b/scheduler.py", detail_payload["change_set"]["diff_text"])

            publish_request = self._request(f"/xyn/api/dev-tasks/{self.task.id}/publish?push=1", method="post")
            with self._auth_patches()[0], self._auth_patches()[1], self._auth_patches()[2]:
                publish_response = dev_task_publish(publish_request, str(self.task.id))
                post_publish_detail = dev_task_detail(self._request(f"/xyn/api/dev-tasks/{self.task.id}"), str(self.task.id))

            self.assertEqual(publish_response.status_code, 200, publish_response.content.decode())
            publish_payload = json.loads(publish_response.content)
            self.assertEqual(publish_payload["status"], "pushed")
            self.assertEqual(publish_payload["work_item"]["publish_state"]["branch"], f"xyn/task/{self.task.id}")

            post_publish_payload = json.loads(post_publish_detail.content)
            self.assertEqual(post_publish_payload["publish_state"]["status"], "pushed")
            self.assertEqual(post_publish_payload["publish_state"]["push_status"], "pushed")
            self.assertEqual(post_publish_payload["publish_state"]["branch"], f"xyn/task/{self.task.id}")
            self.assertTrue(post_publish_payload["publish_state"]["commit"])
            self.assertEqual(
                subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=repo_dir,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip(),
                f"xyn/task/{self.task.id}",
            )
