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
    configured_remote_catalog_sources,
    list_remote_artifact_candidates,
    search_remote_artifact_catalog,
    upsert_remote_catalog_artifact,
)
from xyn_orchestrator.solution_bundles import _resolve_s3_region
from xyn_orchestrator.xyn_api import (
    artifacts_remote_candidates_collection,
    artifacts_remote_catalog_collection,
    artifacts_remote_sources_collection,
    solution_change_sessions_collection,
)


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

    @mock.patch.dict("os.environ", {"XYN_SOLUTION_BUNDLE_SOURCES": "s3://bucket/a,s3://bucket/b"}, clear=False)
    def test_remote_sources_collection_exposes_configured_roots(self):
        with mock.patch("xyn_orchestrator.xyn_api._require_staff", return_value=None):
            request = self.factory.get("/xyn/api/artifacts/remote-sources")
            request.user = self.user
            response = artifacts_remote_sources_collection(request)
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = json.loads(response.content)
        sources = [str(row.get("source") or "") for row in (payload.get("sources") or [])]
        self.assertGreaterEqual(payload.get("count") or 0, 2)
        self.assertIn("s3://bucket/a", sources)
        self.assertIn("s3://bucket/b", sources)

    @mock.patch("xyn_orchestrator.remote_artifact_targeting.list_remote_artifact_candidates")
    @mock.patch("xyn_orchestrator.remote_artifact_targeting._iter_manifest_sources_for_root")
    @mock.patch.dict("os.environ", {"XYN_SOLUTION_BUNDLE_SOURCES": "s3://bucket/root"}, clear=False)
    def test_search_remote_artifact_catalog_by_query(
        self,
        mock_manifest_sources: mock.Mock,
        mock_list_candidates: mock.Mock,
    ):
        mock_manifest_sources.return_value = [
            "s3://bucket/root/deal-finder/manifest.json",
            "s3://bucket/root/crm/manifest.json",
        ]
        mock_list_candidates.side_effect = [
            [
                {
                    "artifact_slug": "deal-finder-api",
                    "artifact_type": "application",
                    "title": "Deal Finder API",
                    "summary": "AI real estate deal finder",
                    "remote_source": {"manifest_source": "s3://bucket/root/deal-finder/manifest.json"},
                }
            ],
            [
                {
                    "artifact_slug": "crm-api",
                    "artifact_type": "application",
                    "title": "CRM API",
                    "summary": "Customer tracking",
                    "remote_source": {"manifest_source": "s3://bucket/root/crm/manifest.json"},
                }
            ],
        ]
        result = search_remote_artifact_catalog(query="deal finder", artifact_type="application")
        self.assertEqual(result.get("total"), 1)
        self.assertEqual((result.get("candidates") or [])[0].get("artifact_slug"), "deal-finder-api")

    @mock.patch("xyn_orchestrator.remote_artifact_targeting.list_remote_artifact_candidates")
    @mock.patch("xyn_orchestrator.remote_artifact_targeting._fallback_manifest_sources_for_root")
    @mock.patch("xyn_orchestrator.remote_artifact_targeting._iter_manifest_sources_for_root")
    @mock.patch.dict("os.environ", {"XYN_SOLUTION_BUNDLE_SOURCES": "s3://bucket/root"}, clear=False)
    def test_search_remote_artifact_catalog_fallbacks_to_slug_json_when_no_manifest_scan_hits(
        self,
        mock_manifest_sources: mock.Mock,
        mock_fallback_sources: mock.Mock,
        mock_list_candidates: mock.Mock,
    ):
        mock_manifest_sources.return_value = []
        mock_fallback_sources.return_value = ["s3://bucket/root/deal-finder.json"]
        mock_list_candidates.return_value = [
            {
                "artifact_slug": "deal-finder-api",
                "artifact_type": "application",
                "title": "Deal Finder API",
                "summary": "Remote bundle",
                "remote_source": {"manifest_source": "s3://bucket/root/deal-finder.json"},
            }
        ]
        result = search_remote_artifact_catalog(query="deal finder", artifact_type="application")
        self.assertEqual(result.get("total"), 1)
        self.assertEqual((result.get("candidates") or [])[0].get("artifact_slug"), "deal-finder-api")
        mock_fallback_sources.assert_called()

    @mock.patch.dict("os.environ", {"XYN_SOLUTION_BUNDLE_SOURCES": "s3://bucket/solutions"}, clear=False)
    @mock.patch("xyn_orchestrator.remote_artifact_targeting._s3_client")
    @mock.patch("xyn_orchestrator.remote_artifact_targeting.list_remote_artifact_candidates")
    def test_search_remote_artifact_catalog_filters_manifest_scan_by_query_tokens(
        self,
        mock_list_candidates: mock.Mock,
        mock_s3_client: mock.Mock,
    ):
        client = mock.Mock()
        paginator = mock.Mock()
        paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "solutions/crm/v1/manifest.json"},
                    {"Key": "solutions/analytics/v2/manifest.json"},
                    {"Key": "solutions/real-estate-deal-finder/v2026-03-31/manifest.json"},
                ]
            }
        ]
        client.get_paginator.return_value = paginator
        mock_s3_client.return_value = client
        mock_list_candidates.return_value = [
            {
                "artifact_slug": "app.real-estate-deal-finder",
                "artifact_type": "application",
                "title": "Deal Finder",
                "summary": "Real estate deal finder",
                "remote_source": {
                    "manifest_source": "s3://bucket/solutions/real-estate-deal-finder/v2026-03-31/manifest.json"
                },
            }
        ]

        result = search_remote_artifact_catalog(query="deal finder", artifact_type="application")
        self.assertEqual(result.get("total"), 1)
        self.assertEqual((result.get("candidates") or [])[0].get("artifact_slug"), "app.real-estate-deal-finder")
        called_sources = [kwargs["artifact_source"]["manifest_source"] for _, kwargs in mock_list_candidates.call_args_list]
        self.assertIn("s3://bucket/solutions/real-estate-deal-finder/v2026-03-31/manifest.json", called_sources)
        self.assertFalse(any("crm/" in source for source in called_sources))
        self.assertFalse(any("analytics/" in source for source in called_sources))

    @mock.patch("xyn_orchestrator.xyn_api.search_remote_artifact_catalog")
    @mock.patch("xyn_orchestrator.xyn_api._require_staff")
    def test_remote_catalog_endpoint_returns_candidates(
        self,
        mock_require_staff: mock.Mock,
        mock_search: mock.Mock,
    ):
        mock_require_staff.return_value = None
        mock_search.return_value = {
            "candidates": [{"artifact_slug": "deal-finder-api", "artifact_type": "application"}],
            "count": 1,
            "total": 1,
            "next_cursor": "",
            "source_roots": ["s3://bucket/root"],
            "errors": [],
        }
        request = self.factory.get("/xyn/api/artifacts/remote-catalog", {"q": "deal finder"})
        request.user = self.user
        response = artifacts_remote_catalog_collection(request)
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = json.loads(response.content)
        self.assertEqual(payload.get("total"), 1)
        self.assertEqual((payload.get("candidates") or [])[0].get("artifact_slug"), "deal-finder-api")

    @mock.patch.dict("os.environ", {}, clear=True)
    def test_missing_region_defaults_safely_for_s3_clients(self):
        self.assertEqual(_resolve_s3_region(), "us-east-1")

    @mock.patch.dict(
        "os.environ",
        {
            "AWS_REGION": "us-west-2",
            "XYN_SOLUTION_BUNDLE_SOURCES": "s3://bucket/root",
            "AWS_ENDPOINT_URL_S3": "https://s3..amazonaws.com",
        },
        clear=True,
    )
    def test_invalid_s3_endpoint_env_is_ignored(self):
        with mock.patch("xyn_orchestrator.remote_artifact_targeting.boto3.client") as mock_client:
            mock_client.return_value = mock.Mock()
            from xyn_orchestrator.remote_artifact_targeting import _s3_client

            _s3_client()
        _, kwargs = mock_client.call_args
        self.assertEqual(kwargs.get("region_name"), "us-west-2")
        self.assertNotIn("endpoint_url", kwargs)
