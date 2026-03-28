from __future__ import annotations

import json
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from xyn_orchestrator.models import (
    Application,
    ApplicationArtifactMembership,
    Artifact,
    ArtifactType,
    UserIdentity,
    Workspace,
    WorkspaceAppInstance,
    WorkspaceMembership,
)
from xyn_orchestrator.xyn_api import application_activate, artifact_activate


def _mock_json_response(status_code: int, payload: dict) -> mock.Mock:
    body = json.dumps(payload)
    response = mock.Mock()
    response.status_code = status_code
    response.content = body.encode("utf-8")
    response.text = body
    response.json.return_value = payload
    return response


class ArtifactActivationApiTests(TestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()
        suffix = uuid.uuid4().hex[:8]
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username=f"activation-user-{suffix}",
            email=f"activation-user-{suffix}@example.com",
            password="password",
        )
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example",
            subject=f"activation-user-{suffix}",
            email=f"activation-user-{suffix}@example.com",
        )
        self.workspace = Workspace.objects.create(slug=f"activation-{suffix}", name="Activation Workspace")
        WorkspaceMembership.objects.create(workspace=self.workspace, user_identity=self.identity, role="admin")
        self.artifact_type = ArtifactType.objects.create(slug=f"application-{suffix}", name="Application")
        self.artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=self.artifact_type,
            title="Real Estate Deal Finder",
            slug="app.real-estate-deal-finder",
            package_version="0.0.1-dev",
            scope_json={
                "imported_manifest": {
                    "artifact": {"id": "app.real-estate-deal-finder"},
                    "content": {
                        "app_spec": {
                            "app_slug": "real-estate-deal-finder",
                            "title": "Real Estate Deal Finder",
                            "entities": ["deals", "properties"],
                            "requested_visuals": ["deals_board"],
                        },
                        "runtime_config": {
                            "source_job_id": "job-source",
                            "app_spec_artifact_id": "appspec-art-id",
                        },
                    },
                }
            },
        )
        self.policy_type, _ = ArtifactType.objects.get_or_create(slug="policy_bundle", defaults={"name": "Policy Bundle"})
        self.policy_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=self.policy_type,
            title="Real Estate Deal Finder Policy Bundle",
            slug="policy.real-estate-deal-finder",
            package_version="0.0.1-dev",
        )
        self.application = Application.objects.create(
            workspace=self.workspace,
            name="Real Estate Deal Finder",
            source_factory_key="manual",
            requested_by=self.identity,
            status="active",
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=self.application,
            artifact=self.artifact,
            role="primary_ui",
            sort_order=0,
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=self.application,
            artifact=self.policy_artifact,
            role="supporting",
            sort_order=10,
        )
        from xyn_orchestrator.models import ArtifactRevision  # local import to avoid test import churn

        ArtifactRevision.objects.create(
            artifact=self.policy_artifact,
            revision_number=1,
            content_json={
                "content": {
                    "policy_bundle": {
                        "schema_version": "xyn.policy_bundle.v0",
                        "bundle_id": "policy.real-estate-deal-finder",
                        "app_slug": "real-estate-deal-finder",
                        "workspace_id": str(self.workspace.id),
                        "title": "Deal Finder Policy Bundle",
                        "policies": {"validation_policies": [{"id": "deal-001", "family": "validation_policies"}]},
                    }
                }
            },
            created_by=None,
        )

    def _request(self, *, method: str = "post") -> object:
        request = getattr(self.factory, method.lower())(
            f"/xyn/api/artifacts/{self.artifact.id}/activate",
            data=json.dumps({}),
            content_type="application/json",
        )
        request.user = self.user
        return request

    def _application_request(self, *, method: str = "post") -> object:
        request = getattr(self.factory, method.lower())(
            f"/xyn/api/applications/{self.application.id}/activate",
            data=json.dumps({}),
            content_type="application/json",
        )
        request.user = self.user
        return request

    def _seed_side_effect(
        self,
        *,
        jobs: list[dict] | None = None,
        create_draft_id: str = "draft-123",
        submit_job_id: str = "job-123",
    ):
        def _impl(*, method: str, path: str, **kwargs):
            if method.upper() == "GET" and path == "/api/v1/jobs":
                return _mock_json_response(200, jobs or [])
            if method.upper() == "POST" and path == "/api/v1/drafts":
                return _mock_json_response(201, {"id": create_draft_id})
            if method.upper() == "POST" and path == f"/api/v1/drafts/{create_draft_id}/submit":
                return _mock_json_response(200, {"job_id": submit_job_id})
            raise AssertionError(f"Unexpected seed call method={method} path={path} kwargs={kwargs}")

        return _impl

    def test_activation_queues_pipeline_when_runtime_target_missing(self) -> None:
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            with mock.patch(
                "xyn_orchestrator.xyn_api._seed_api_request",
                side_effect=self._seed_side_effect(jobs=[]),
            ) as seed_mock:
                response = artifact_activate(self._request(method="post"), str(self.artifact.id))

        self.assertEqual(response.status_code, 202)
        payload = json.loads(response.content)
        self.assertEqual(payload.get("status"), "queued")
        self.assertEqual(payload.get("app_slug"), "real-estate-deal-finder")
        self.assertEqual((payload.get("activation") or {}).get("job_id"), "job-123")
        revision_anchor = payload.get("revision_anchor") or {}
        self.assertEqual(revision_anchor.get("artifact_slug"), "app.real-estate-deal-finder")
        self.assertEqual(revision_anchor.get("workspace_id"), str(self.workspace.id))
        self.assertGreaterEqual(seed_mock.call_count, 3)

    def test_activation_includes_source_policy_bundle_when_membership_exists(self) -> None:
        captured_draft_payload = {}

        def _seed_capture(*, method: str, path: str, **kwargs):
            nonlocal captured_draft_payload
            if method.upper() == "GET" and path == "/api/v1/jobs":
                return _mock_json_response(200, [])
            if method.upper() == "POST" and path == "/api/v1/drafts":
                captured_draft_payload = kwargs.get("payload") or {}
                return _mock_json_response(201, {"id": "draft-123"})
            if method.upper() == "POST" and path == "/api/v1/drafts/draft-123/submit":
                return _mock_json_response(200, {"job_id": "job-123"})
            raise AssertionError(f"Unexpected seed call method={method} path={path} kwargs={kwargs}")

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            with mock.patch("xyn_orchestrator.xyn_api._seed_api_request", side_effect=_seed_capture):
                response = artifact_activate(self._request(method="post"), str(self.artifact.id))

        self.assertEqual(response.status_code, 202)
        payload = json.loads(response.content)
        self.assertEqual(payload.get("status"), "queued")
        self.assertEqual(payload.get("policy_source"), "artifact")
        self.assertEqual(payload.get("policy_compatibility"), "unknown")
        self.assertEqual(payload.get("policy_compatibility_reason"), "missing_derivation_signature")
        self.assertEqual((payload.get("policy_artifact_ref") or {}).get("artifact_slug"), "policy.real-estate-deal-finder")
        content = (captured_draft_payload.get("content_json") if isinstance(captured_draft_payload, dict) else {}) or {}
        self.assertEqual(content.get("policy_source"), "artifact")
        self.assertEqual(content.get("policy_compatibility"), "unknown")
        self.assertEqual(content.get("policy_compatibility_reason"), "missing_derivation_signature")
        self.assertEqual((content.get("policy_artifact_ref") or {}).get("artifact_slug"), "policy.real-estate-deal-finder")
        self.assertEqual(
            str(((content.get("policy_bundle_override") or {}).get("schema_version") or "")),
            "xyn.policy_bundle.v0",
        )

    def test_activation_reuses_persisted_runtime_target_and_skips_seed_queue(self) -> None:
        WorkspaceAppInstance.objects.create(
            workspace=self.workspace,
            artifact=self.artifact,
            app_slug="real-estate-deal-finder",
            fqdn="real-estate-deal-finder.internal",
            status="active",
            dns_config_json={
                "runtime_target": {
                    "runtime_owner": "sibling",
                    "runtime_base_url": "http://real-estate-deal-finder-api:8080",
                    "public_app_url": "http://real-estate-deal-finder.localhost",
                    "compose_project": "xyn-real-estate-deal-finder",
                    "app_slug": "real-estate-deal-finder",
                    "installed_artifact_slug": "app.real-estate-deal-finder",
                }
            },
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            with mock.patch("xyn_orchestrator.xyn_api._seed_api_request") as seed_mock:
                response = artifact_activate(self._request(method="post"), str(self.artifact.id))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload.get("status"), "reused")
        runtime_target = payload.get("runtime_target") or {}
        self.assertEqual(runtime_target.get("compose_project"), "xyn-real-estate-deal-finder")
        seed_mock.assert_not_called()

    def test_second_activation_reuses_same_runtime_instance_without_duplicates(self) -> None:
        WorkspaceAppInstance.objects.create(
            workspace=self.workspace,
            artifact=self.artifact,
            app_slug="real-estate-deal-finder",
            fqdn="real-estate-deal-finder.internal",
            status="active",
            dns_config_json={
                "runtime_target": {
                    "runtime_owner": "sibling",
                    "runtime_base_url": "http://real-estate-deal-finder-api:8080",
                    "public_app_url": "http://real-estate-deal-finder.localhost",
                    "compose_project": "xyn-real-estate-deal-finder",
                    "app_slug": "real-estate-deal-finder",
                    "installed_artifact_slug": "app.real-estate-deal-finder",
                }
            },
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            first = artifact_activate(self._request(method="post"), str(self.artifact.id))
            second = artifact_activate(self._request(method="post"), str(self.artifact.id))

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        first_payload = json.loads(first.content)
        second_payload = json.loads(second.content)
        self.assertEqual(
            (first_payload.get("runtime_instance") or {}).get("id"),
            (second_payload.get("runtime_instance") or {}).get("id"),
        )
        self.assertEqual(
            WorkspaceAppInstance.objects.filter(
                workspace=self.workspace,
                app_slug="real-estate-deal-finder",
                status="active",
            ).count(),
            1,
        )

    def test_activation_does_not_reuse_runtime_target_for_different_artifact_slug(self) -> None:
        WorkspaceAppInstance.objects.create(
            workspace=self.workspace,
            artifact=self.artifact,
            app_slug="real-estate-deal-finder",
            fqdn="real-estate-deal-finder.internal",
            status="active",
            dns_config_json={
                "runtime_target": {
                    "runtime_owner": "sibling",
                    "runtime_base_url": "http://real-estate-deal-finder-api:8080",
                    "public_app_url": "http://real-estate-deal-finder.localhost",
                    "compose_project": "xyn-real-estate-deal-finder",
                    "app_slug": "real-estate-deal-finder",
                    "installed_artifact_slug": "app.some-other-artifact",
                }
            },
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            with mock.patch(
                "xyn_orchestrator.xyn_api._seed_api_request",
                side_effect=self._seed_side_effect(jobs=[]),
            ) as seed_mock:
                response = artifact_activate(self._request(method="post"), str(self.artifact.id))

        self.assertEqual(response.status_code, 202)
        payload = json.loads(response.content)
        self.assertEqual(payload.get("status"), "queued")
        self.assertEqual(payload.get("reuse_blocked_reason"), "runtime_artifact_slug_mismatch")
        self.assertGreaterEqual(seed_mock.call_count, 3)

    def test_activation_handles_malformed_runtime_target_record_by_queuing(self) -> None:
        WorkspaceAppInstance.objects.create(
            workspace=self.workspace,
            artifact=self.artifact,
            app_slug="real-estate-deal-finder",
            fqdn="real-estate-deal-finder.internal",
            status="active",
            dns_config_json={
                "runtime_target": {
                    "runtime_owner": "sibling",
                    "runtime_base_url": "http://real-estate-deal-finder-api:8080",
                    "compose_project": "xyn-real-estate-deal-finder",
                    "app_slug": "real-estate-deal-finder",
                }
            },
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            with mock.patch(
                "xyn_orchestrator.xyn_api._seed_api_request",
                side_effect=self._seed_side_effect(jobs=[]),
            ) as seed_mock:
                response = artifact_activate(self._request(method="post"), str(self.artifact.id))

        self.assertEqual(response.status_code, 202)
        payload = json.loads(response.content)
        self.assertEqual(payload.get("status"), "queued")
        self.assertEqual(payload.get("reuse_blocked_reason"), "runtime_artifact_slug_mismatch")
        self.assertGreaterEqual(seed_mock.call_count, 3)

    def test_second_identical_request_while_first_inflight_returns_queued_existing(self) -> None:
        inflight_jobs = [
            {
                "id": "job-queued-1",
                "type": "generate_app_spec",
                "status": "queued",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:01Z",
                "input_json": {
                    "draft_id": "draft-queued-1",
                    "content_json": {
                        "revision_anchor": {
                            "workspace_id": str(self.workspace.id),
                            "artifact_slug": "app.real-estate-deal-finder",
                            "app_slug": "real-estate-deal-finder",
                        }
                    },
                },
            }
        ]
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            with mock.patch(
                "xyn_orchestrator.xyn_api._seed_api_request",
                side_effect=self._seed_side_effect(jobs=inflight_jobs),
            ):
                response = artifact_activate(self._request(method="post"), str(self.artifact.id))

        self.assertEqual(response.status_code, 202)
        payload = json.loads(response.content)
        self.assertEqual(payload.get("status"), "queued_existing")
        self.assertEqual((payload.get("activation") or {}).get("job_id"), "job-queued-1")
        self.assertEqual((payload.get("activation") or {}).get("draft_id"), "draft-queued-1")

    def test_completed_activation_does_not_block_fresh_request(self) -> None:
        completed_jobs = [
            {
                "id": "job-completed-1",
                "type": "generate_app_spec",
                "status": "succeeded",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:10Z",
                "input_json": {
                    "draft_id": "draft-completed-1",
                    "content_json": {
                        "revision_anchor": {
                            "workspace_id": str(self.workspace.id),
                            "artifact_slug": "app.real-estate-deal-finder",
                            "app_slug": "real-estate-deal-finder",
                        }
                    },
                },
            }
        ]
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            with mock.patch(
                "xyn_orchestrator.xyn_api._seed_api_request",
                side_effect=self._seed_side_effect(jobs=completed_jobs, create_draft_id="draft-new", submit_job_id="job-new"),
            ):
                response = artifact_activate(self._request(method="post"), str(self.artifact.id))

        self.assertEqual(response.status_code, 202)
        payload = json.loads(response.content)
        self.assertEqual(payload.get("status"), "queued")
        self.assertEqual((payload.get("activation") or {}).get("job_id"), "job-new")

    def test_inflight_job_for_different_artifact_same_app_slug_does_not_dedupe(self) -> None:
        inflight_other_artifact = [
            {
                "id": "job-other-1",
                "type": "generate_app_spec",
                "status": "running",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:01Z",
                "input_json": {
                    "draft_id": "draft-other-1",
                    "content_json": {
                        "revision_anchor": {
                            "workspace_id": str(self.workspace.id),
                            "artifact_slug": "app.other-artifact",
                            "app_slug": "real-estate-deal-finder",
                        }
                    },
                },
            }
        ]
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            with mock.patch(
                "xyn_orchestrator.xyn_api._seed_api_request",
                side_effect=self._seed_side_effect(
                    jobs=inflight_other_artifact,
                    create_draft_id="draft-new",
                    submit_job_id="job-new",
                ),
            ):
                response = artifact_activate(self._request(method="post"), str(self.artifact.id))

        self.assertEqual(response.status_code, 202)
        payload = json.loads(response.content)
        self.assertEqual(payload.get("status"), "queued")
        self.assertEqual((payload.get("activation") or {}).get("job_id"), "job-new")

    def test_solution_activation_delegates_to_primary_app_artifact_activation(self) -> None:
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            with mock.patch(
                "xyn_orchestrator.xyn_api._seed_api_request",
                side_effect=self._seed_side_effect(jobs=[]),
            ):
                response = application_activate(self._application_request(method="post"), str(self.application.id))
        self.assertEqual(response.status_code, 202)
        payload = json.loads(response.content)
        self.assertEqual(payload.get("artifact_slug"), "app.real-estate-deal-finder")
