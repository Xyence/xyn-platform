import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from xyn_orchestrator.managed_storage import managed_workspace_path
from xyn_orchestrator.models import (
    Application,
    ApplicationArtifactMembership,
    Artifact,
    ArtifactType,
    DevTask,
    ManagedRepository,
    SolutionChangeSession,
    SolutionChangeSessionRepoCommit,
    UserIdentity,
    Workspace,
    WorkspaceMembership,
)
from xyn_orchestrator.xyn_api import (
    application_solution_change_session_commits,
    application_solution_change_session_finalize,
    dev_task_publish,
)


class SolutionChangeSessionRepoCommitTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)

        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="session-admin", email="session@example.com", password="password")
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])

        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example.com",
            subject="session-admin",
            email="session@example.com",
        )

        self.workspace = Workspace.objects.create(name="Session Workspace", slug=f"session-{uuid.uuid4().hex[:8]}")
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user_identity=self.identity,
            role="admin",
            termination_authority=True,
        )

        self.application = Application.objects.create(
            workspace=self.workspace,
            name="Deal Finder",
            summary="",
            source_factory_key="manual",
            source_conversation_id="",
            status="active",
            request_objective="",
            metadata_json={},
        )
        self.session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=self.application,
            title="Refine campaign flow",
            request_text="",
            status="planned",
            created_by=self.identity,
            execution_status="ready_for_promotion",
            selected_artifact_ids_json=[],
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
            title="Publish changes",
            task_type="codegen",
            status="completed",
            priority=0,
            max_attempts=3,
            source_entity_type="manual",
            source_entity_id=uuid.uuid4(),
            work_item_id="wi-commit",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_brief={"schema_version": "v1", "summary": "Publish seam"},
            created_by=self.user,
            updated_by=self.user,
        )

    def _auth_patches(self):
        return (
            mock.patch("xyn_orchestrator.xyn_api._require_staff", return_value=None),
            mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity),
            mock.patch("xyn_orchestrator.xyn_api._require_workspace_capabilities", return_value=True),
        )

    def _request(self, path: str, *, method: str = "post", data: dict | None = None):
        body = json.dumps(data or {})
        request = getattr(self.factory, method.lower())(path, data=body, content_type="application/json")
        request.user = self.user
        return request

    def _workspace_repo(self, *, with_change: bool) -> Path:
        repo_dir = managed_workspace_path("codegen", "tasks", self.task.id, "repos", "xyn-platform")
        repo_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "remote", "add", "origin", str(self.remote)], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "checkout", "-B", "develop"], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "session@example.com"], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.name", "Session Test"], cwd=repo_dir, check=True, capture_output=True, text=True)
        (repo_dir / "feature.py").write_text("value = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "feature.py"], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_dir, check=True, capture_output=True, text=True)
        if with_change:
            (repo_dir / "feature.py").write_text("value = 2\n", encoding="utf-8")
        return repo_dir

    def test_publish_records_session_commit_provenance(self):
        with mock.patch.dict(os.environ, {"XYN_WORKSPACE_ROOT": self.tempdir.name}, clear=False):
            self._workspace_repo(with_change=True)
            request = self._request(
                f"/xyn/api/dev-tasks/{self.task.id}/publish",
                data={"solution_change_session_id": str(self.session.id)},
            )
            with self._auth_patches()[0], self._auth_patches()[1], self._auth_patches()[2]:
                response = dev_task_publish(request, str(self.task.id))

        self.assertEqual(response.status_code, 200)
        commits = list(SolutionChangeSessionRepoCommit.objects.filter(solution_change_session=self.session))
        self.assertEqual(len(commits), 1)
        self.assertEqual(commits[0].repository_slug, "xyn-platform")
        self.assertTrue(commits[0].commit_sha)
        self.assertIn("feature.py", commits[0].changed_files_json)

    def test_session_commits_api_returns_persisted_history(self):
        SolutionChangeSessionRepoCommit.objects.create(
            workspace=self.workspace,
            solution_change_session=self.session,
            repository_slug="xyn-platform",
            branch="develop",
            commit_sha="abc123",
            changed_files_json=["services/xyn-api/backend/xyn_orchestrator/xyn_api.py"],
            validation_status="unknown",
        )
        request = self._request(
            f"/xyn/api/applications/{self.application.id}/change-sessions/{self.session.id}/commits",
            method="get",
        )
        with self._auth_patches()[1]:
            response = application_solution_change_session_commits(request, str(self.application.id), str(self.session.id))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(len(payload["commits"]), 1)
        self.assertEqual(payload["commits"][0]["commit_sha"], "abc123")

    def test_finalize_blocks_code_changing_session_without_commit(self):
        artifact_type, _ = ArtifactType.objects.get_or_create(slug="application", defaults={"name": "Application"})
        artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="xyn-api",
            slug=f"app-{uuid.uuid4().hex[:8]}",
            edit_mode="repo_backed",
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["services/xyn-api/backend/"],
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=self.application,
            artifact=artifact,
            role="primary_api",
        )
        self.session.selected_artifact_ids_json = [str(artifact.id)]
        self.session.save(update_fields=["selected_artifact_ids_json", "updated_at"])

        request = self._request(
            f"/xyn/api/applications/{self.application.id}/change-sessions/{self.session.id}/finalize",
        )
        with self._auth_patches()[1], self._auth_patches()[2]:
            response = application_solution_change_session_finalize(request, str(self.application.id), str(self.session.id))

        self.assertEqual(response.status_code, 409)
        payload = json.loads(response.content)
        self.assertIn("require at least one recorded repository commit", payload.get("error", ""))
