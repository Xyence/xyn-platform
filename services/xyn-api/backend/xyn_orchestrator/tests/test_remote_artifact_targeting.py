import json
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.test import RequestFactory, TestCase

from xyn_orchestrator.models import (
    Application,
    ApplicationArtifactMembership,
    Artifact,
    ArtifactType,
    UserIdentity,
    Workspace,
    WorkspaceArtifactBinding,
    WorkspaceMembership,
)
from xyn_orchestrator.remote_artifact_targeting import (
    REMOTE_SOURCE_REF_TYPE,
    list_remote_artifact_candidates,
    upsert_remote_catalog_artifact,
)
from xyn_orchestrator.xyn_api import artifacts_remote_candidates_collection, solution_change_sessions_collection


class RemoteArtifactTargetingTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = get_user_model().objects.create_user(username=f"remote-user-{uuid.uuid4().hex[:8]}", password="pw")
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example.com",
            subject=f"remote-{uuid.uuid4().hex[:8]}",
            email="remote@example.com",
            display_name="Remote User",
        )
        self.workspace = Workspace.objects.create(slug=f"remote-ws-{uuid.uuid4().hex[:8]}", name="Remote WS")
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user_identity=self.identity,
            role="admin",
            termination_authority=True,
        )
        self.artifact_type = ArtifactType.objects.create(slug=f"application-{uuid.uuid4().hex[:6]}", name="Application")

    def _request(self, path: str, *, method: str = "post", payload: dict | None = None):
        body = json.dumps(payload or {})
        request = self.factory.post(path, data=body, content_type="application/json") if method == "post" else self.factory.get(path)
        request.user = self.user
        return request

    def test_list_remote_artifact_candidates_from_manifest_source(self):
        bundle = {
            "solution": {"slug": "deal-finder", "name": "Deal Finder"},
            "artifacts": {
                "primary_app": {
                    "type": "application",
                    "slug": "deal-finder-api",
                    "version": "1.2.0",
                    "package_source": "s3://bucket/key.tar.gz",
                    "owner_repo_slug": "deal-finder",
                    "owner_path_prefixes": ["services/api/"],
                }
            },
        }
        with mock.patch("xyn_orchestrator.remote_artifact_targeting.load_solution_bundle_from_source", return_value=bundle):
            candidates = list_remote_artifact_candidates(artifact_source={"manifest_source": "s3://bucket/manifest.json"})
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["artifact_slug"], "deal-finder-api")
        self.assertEqual(candidate["artifact_origin"], "remote_catalog")
        self.assertFalse(candidate["installed"])
        self.assertEqual(candidate["source_ref_type"], REMOTE_SOURCE_REF_TYPE)

    def test_upsert_remote_catalog_artifact_creates_catalog_only_row_without_bindings(self):
        candidate = {
            "artifact_slug": "deal-finder-api",
            "artifact_type": self.artifact_type.slug,
            "title": "Deal Finder API",
            "summary": "Remote candidate",
            "artifact_origin": "remote_catalog",
            "source_ref_type": REMOTE_SOURCE_REF_TYPE,
            "source_ref_id": "bundle:abc123:deal-finder-api:application",
            "remote_source": {
                "manifest_source": "s3://bucket/manifest.json",
                "package_source": "s3://bucket/deal-finder.tar.gz",
                "owner_repo_slug": "deal-finder",
                "owner_path_prefixes": ["services/api/"],
            },
        }
        artifact = upsert_remote_catalog_artifact(workspace=self.workspace, candidate=candidate, created_by=self.identity)
        self.assertEqual(str(artifact.workspace_id), str(self.workspace.id))
        self.assertEqual(artifact.scope_json.get("catalog_mode"), "remote_catalog")
        self.assertEqual(artifact.provenance_json.get("artifact_origin"), "remote_catalog")
        self.assertEqual(artifact.source_ref_type, REMOTE_SOURCE_REF_TYPE)
        self.assertFalse(WorkspaceArtifactBinding.objects.filter(artifact=artifact).exists())

    @mock.patch("xyn_orchestrator.xyn_api.application_solution_change_sessions_collection")
    @mock.patch("xyn_orchestrator.xyn_api.resolve_remote_artifact_candidate")
    @mock.patch("xyn_orchestrator.xyn_api._require_authenticated")
    def test_create_change_session_from_remote_source_upserts_catalog_artifact(
        self,
        mock_auth: mock.Mock,
        mock_resolve_remote: mock.Mock,
        mock_create_session: mock.Mock,
    ):
        mock_auth.return_value = self.identity
        mock_resolve_remote.return_value = {
            "artifact_slug": "deal-finder-api",
            "artifact_type": self.artifact_type.slug,
            "title": "Deal Finder API",
            "summary": "Remote candidate",
            "artifact_origin": "remote_catalog",
            "source_ref_type": REMOTE_SOURCE_REF_TYPE,
            "source_ref_id": "bundle:abc123:deal-finder-api:application",
            "remote_source": {
                "manifest_source": "s3://bucket/manifest.json",
                "package_source": "s3://bucket/deal-finder.tar.gz",
                "owner_repo_slug": "deal-finder",
                "owner_path_prefixes": ["services/api/"],
            },
        }
        mock_create_session.return_value = JsonResponse(
            {
                "session": {
                    "id": str(uuid.uuid4()),
                    "planning": {},
                    "plan": {},
                }
            },
            status=201,
        )

        request = self._request(
            "/xyn/api/change-sessions",
            payload={
                "workspace_id": str(self.workspace.id),
                "artifact_slug": "deal-finder-api",
                "artifact_source": {
                    "manifest_source": "s3://bucket/manifest.json",
                    "artifact_slug": "deal-finder-api",
                    "artifact_type": self.artifact_type.slug,
                },
                "request_text": "Refactor entrypoint",
            },
        )

        response = solution_change_sessions_collection(request)
        self.assertEqual(response.status_code, 201, response.content.decode())
        payload = json.loads(response.content)
        self.assertEqual(payload.get("artifact_origin"), "remote_catalog")
        self.assertTrue(str(payload.get("artifact_id") or "").strip())
        artifact = Artifact.objects.get(id=payload["artifact_id"])
        self.assertEqual(artifact.scope_json.get("catalog_mode"), "remote_catalog")
        self.assertFalse(WorkspaceArtifactBinding.objects.filter(artifact=artifact).exists())
        app = Application.objects.get(id=payload["application_id"])
        self.assertTrue(ApplicationArtifactMembership.objects.filter(application=app, artifact=artifact).exists())

    @mock.patch("xyn_orchestrator.xyn_api.application_solution_change_sessions_collection")
    @mock.patch("xyn_orchestrator.xyn_api.resolve_remote_artifact_candidate")
    @mock.patch("xyn_orchestrator.xyn_api._require_authenticated")
    def test_existing_local_artifact_flow_is_unchanged(
        self,
        mock_auth: mock.Mock,
        mock_resolve_remote: mock.Mock,
        mock_create_session: mock.Mock,
    ):
        mock_auth.return_value = self.identity
        local = Artifact.objects.create(
            workspace=self.workspace,
            type=self.artifact_type,
            slug="local-api",
            title="Local API",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        mock_create_session.return_value = JsonResponse({"session": {"id": str(uuid.uuid4())}}, status=201)

        request = self._request(
            "/xyn/api/change-sessions",
            payload={
                "workspace_id": str(self.workspace.id),
                "artifact_id": str(local.id),
                "request_text": "Do change",
            },
        )
        response = solution_change_sessions_collection(request)
        self.assertEqual(response.status_code, 201, response.content.decode())
        self.assertFalse(mock_resolve_remote.called)

    @mock.patch("xyn_orchestrator.xyn_api.list_remote_artifact_candidates")
    @mock.patch("xyn_orchestrator.xyn_api._require_staff")
    def test_remote_candidates_endpoint_returns_candidates(self, mock_require_staff: mock.Mock, mock_list: mock.Mock):
        mock_require_staff.return_value = None
        mock_list.return_value = [
            {
                "artifact_slug": "deal-finder-api",
                "artifact_type": "application",
                "installed": False,
            }
        ]
        request = self.factory.get(
            "/xyn/api/artifacts/remote-candidates",
            {"manifest_source": "s3://bucket/manifest.json"},
        )
        request.user = self.user
        response = artifacts_remote_candidates_collection(request)
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = json.loads(response.content)
        self.assertEqual(payload.get("count"), 1)
        self.assertEqual((payload.get("candidates") or [])[0].get("artifact_slug"), "deal-finder-api")
