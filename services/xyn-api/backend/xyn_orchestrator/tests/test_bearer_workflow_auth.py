import json
import uuid
from typing import Any, Dict
from unittest import mock

from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.test import TestCase

from xyence.middleware import _reset_oidc_caches_for_tests
from xyn_orchestrator.models import (
    Artifact,
    ArtifactType,
    Application,
    ApplicationArtifactMembership,
    RoleBinding,
    SolutionChangeSession,
    UserIdentity,
    Workspace,
    WorkspaceMembership,
)
from xyn_orchestrator.xyn_api import _build_change_request_text_from_decomposition_campaign


class BearerWorkflowAuthTests(TestCase):
    def setUp(self):
        _reset_oidc_caches_for_tests()
        self.workspace = Workspace.objects.create(
            slug=f"bearer-ws-{uuid.uuid4().hex[:8]}",
            name="Bearer Workspace",
        )
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example.com",
            subject="user-subject",
            email="member@example.com",
            display_name="Member",
        )
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user_identity=self.identity,
            role="admin",
            termination_authority=True,
        )
        RoleBinding.objects.get_or_create(
            user_identity=self.identity,
            scope_kind="platform",
            scope_id=None,
            role="platform_admin",
        )
        self.application = Application.objects.create(
            workspace=self.workspace,
            name="Bearer App",
            source_factory_key="manual",
            requested_by=self.identity,
            status="active",
        )
        self.change_session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=self.application,
            title="Session 1",
            request_text="Initial change request",
            created_by=self.identity,
        )

    def _bearer_claims(self, *, email: str = "member@example.com", sub: str = "user-subject"):
        return {
            "iss": "https://issuer.example.com",
            "sub": sub,
            "email": email,
            "email_verified": True,
            "name": "Bearer User",
            "aud": "xyn-ui",
        }

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc"}, clear=False)
    @mock.patch("xyence.middleware._verify_oidc_token")
    def test_bearer_can_list_applications(self, mock_verify: mock.Mock):
        mock_verify.return_value = self._bearer_claims()
        response = self.client.get(
            "/xyn/api/applications",
            {"workspace_id": str(self.workspace.id)},
            HTTP_AUTHORIZATION="Bearer token-ok",
        )
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertEqual(len(payload.get("applications") or []), 1)
        self.assertEqual(payload["applications"][0]["id"], str(self.application.id))

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc"}, clear=False)
    @mock.patch("xyence.middleware._verify_oidc_token")
    def test_platform_admin_without_membership_can_list_and_read_application_sessions(self, mock_verify: mock.Mock):
        WorkspaceMembership.objects.filter(workspace=self.workspace, user_identity=self.identity).delete()
        mock_verify.return_value = self._bearer_claims()

        list_response = self.client.get(
            "/xyn/api/applications",
            {"workspace_id": str(self.workspace.id)},
            HTTP_AUTHORIZATION="Bearer token-platform-admin",
        )
        self.assertEqual(list_response.status_code, 200, list_response.content.decode())
        list_payload = list_response.json()
        self.assertEqual(len(list_payload.get("applications") or []), 1)
        self.assertEqual(list_payload["applications"][0]["id"], str(self.application.id))

        detail_response = self.client.get(
            f"/xyn/api/applications/{self.application.id}",
            HTTP_AUTHORIZATION="Bearer token-platform-admin",
        )
        self.assertEqual(detail_response.status_code, 200, detail_response.content.decode())
        self.assertEqual(detail_response.json().get("id"), str(self.application.id))

        sessions_response = self.client.get(
            f"/xyn/api/applications/{self.application.id}/change-sessions",
            HTTP_AUTHORIZATION="Bearer token-platform-admin",
        )
        self.assertEqual(sessions_response.status_code, 200, sessions_response.content.decode())
        self.assertEqual(sessions_response.json().get("application_id"), str(self.application.id))

        session_detail_response = self.client.get(
            f"/xyn/api/applications/{self.application.id}/change-sessions/{self.change_session.id}",
            HTTP_AUTHORIZATION="Bearer token-platform-admin",
        )
        self.assertEqual(session_detail_response.status_code, 200, session_detail_response.content.decode())
        self.assertEqual(session_detail_response.json().get("id"), str(self.change_session.id))

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc"}, clear=False)
    @mock.patch("xyence.middleware._verify_oidc_token")
    @mock.patch("xyn_orchestrator.xyn_api._maybe_emit_solution_checkpoint_turn")
    @mock.patch("xyn_orchestrator.xyn_api._reset_solution_stage_checkpoint")
    @mock.patch("xyn_orchestrator.xyn_api._record_solution_draft_plan")
    @mock.patch("xyn_orchestrator.xyn_api._solution_planning_state")
    @mock.patch("xyn_orchestrator.xyn_api._build_solution_impacted_analysis")
    @mock.patch("xyn_orchestrator.xyn_api._stage_solution_change_session")
    def test_platform_admin_without_membership_can_create_control_plan_and_stage_apply(
        self,
        mock_stage: mock.Mock,
        mock_analysis: mock.Mock,
        mock_planning_state: mock.Mock,
        mock_record_plan: mock.Mock,
        mock_reset_checkpoint: mock.Mock,
        mock_emit_checkpoint: mock.Mock,
        mock_verify: mock.Mock,
    ):
        WorkspaceMembership.objects.filter(workspace=self.workspace, user_identity=self.identity).delete()
        mock_verify.return_value = self._bearer_claims()
        mock_analysis.return_value = {"suggested_artifact_ids": []}
        mock_planning_state.return_value = {"pending_question": None, "pending_option_set": None, "latest_draft_plan": {"ok": True}}
        mock_reset_checkpoint.return_value = None
        mock_record_plan.return_value = None
        mock_emit_checkpoint.return_value = None
        mock_stage.return_value = None

        create_response = self.client.post(
            f"/xyn/api/applications/{self.application.id}/change-sessions",
            data=json.dumps({"request_text": "do a change"}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-platform-admin",
        )
        self.assertEqual(create_response.status_code, 201, create_response.content.decode())
        session_id = str(((create_response.json().get("session") or {}).get("id") or "")).strip()
        self.assertTrue(session_id)

        control_response = self.client.get(
            f"/xyn/api/applications/{self.application.id}/change-sessions/{session_id}/control",
            HTTP_AUTHORIZATION="Bearer token-platform-admin",
        )
        self.assertEqual(control_response.status_code, 200, control_response.content.decode())

        plan_response = self.client.post(
            f"/xyn/api/applications/{self.application.id}/change-sessions/{session_id}/plan",
            data=json.dumps({}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-platform-admin",
        )
        self.assertEqual(plan_response.status_code, 200, plan_response.content.decode())

        session = SolutionChangeSession.objects.get(id=session_id)
        session.plan_json = {"summary": "ready"}
        session.save(update_fields=["plan_json", "updated_at"])

        stage_response = self.client.post(
            f"/xyn/api/applications/{self.application.id}/change-sessions/{session_id}/control/actions",
            data=json.dumps({"operation": "stage_apply"}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-platform-admin",
        )
        self.assertIn(stage_response.status_code, {200, 202}, stage_response.content.decode())

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc", "OIDC_ISSUER": "https://issuer.example.com", "OIDC_CLIENT_ID": "xyn-ui"}, clear=False)
    @mock.patch("xyence.middleware.jwt.decode", side_effect=Exception("bad_jwt"))
    @mock.patch("xyence.middleware._get_jwks_client")
    @mock.patch("xyence.middleware.requests.get")
    def test_applications_uses_userinfo_fallback_when_jwt_decode_fails(
        self,
        mock_requests_get: mock.Mock,
        mock_jwks_client: mock.Mock,
        _mock_jwt_decode: mock.Mock,
    ):
        key = mock.Mock()
        key.key = "signing-key"
        mock_jwks_client.return_value = mock.Mock(get_signing_key_from_jwt=mock.Mock(return_value=key))
        discovery_response = mock.Mock()
        discovery_response.status_code = 200
        discovery_response.raise_for_status.return_value = None
        discovery_response.json.return_value = {"userinfo_endpoint": "https://issuer.example.com/userinfo"}
        userinfo_response = mock.Mock()
        userinfo_response.status_code = 200
        userinfo_response.json.return_value = {
            "sub": "userinfo-subject",
            "email": "member@example.com",
            "name": "Userinfo Member",
        }
        mock_requests_get.side_effect = [discovery_response, userinfo_response]

        response = self.client.get(
            "/xyn/api/applications",
            {"workspace_id": str(self.workspace.id)},
            HTTP_AUTHORIZATION="Bearer token-userinfo",
        )
        self.assertIn(response.status_code, {200, 400}, response.content.decode())
        self.assertNotEqual(response.status_code, 401, response.content.decode())
        self.assertFalse(response.has_header("Location"))

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc"}, clear=False)
    @mock.patch("xyence.middleware._verify_oidc_token")
    def test_bearer_can_access_change_session_collection(self, mock_verify: mock.Mock):
        mock_verify.return_value = self._bearer_claims()
        response = self.client.get(
            f"/xyn/api/applications/{self.application.id}/change-sessions",
            HTTP_AUTHORIZATION="Bearer token-ok",
        )
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("application_id"), str(self.application.id))
        self.assertIn("sessions", payload)

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc"}, clear=False)
    @mock.patch("xyence.middleware._verify_oidc_token")
    @mock.patch("xyn_orchestrator.xyn_api._seed_api_request")
    def test_bearer_can_access_runtime_runs(self, mock_seed_request: mock.Mock, mock_verify: mock.Mock):
        mock_verify.return_value = self._bearer_claims()
        fake_response = mock.Mock()
        fake_response.status_code = 200
        fake_response.content = b'{"items":[]}'
        fake_response.json.return_value = {"items": []}
        mock_seed_request.return_value = fake_response
        response = self.client.get(
            "/xyn/api/runtime/runs",
            {"workspace_id": str(self.workspace.id)},
            HTTP_AUTHORIZATION="Bearer token-ok",
        )
        self.assertEqual(response.status_code, 200, response.content.decode())
        self.assertEqual(response.json().get("runs"), [])
        self.assertFalse(response.has_header("Location"))

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc"}, clear=False)
    @mock.patch("xyence.middleware._verify_oidc_token")
    def test_bearer_can_access_runs_collection(self, mock_verify: mock.Mock):
        mock_verify.return_value = self._bearer_claims()
        response = self.client.get(
            "/xyn/api/runs",
            HTTP_AUTHORIZATION="Bearer token-ok",
        )
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertIn("runs", payload)
    def test_session_auth_still_works_for_applications(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="session-admin",
            password="pass",
            email=self.identity.email,
            is_staff=True,
        )
        self.client.force_login(user)
        session = self.client.session
        session["user_identity_id"] = str(self.identity.id)
        session.save()
        response = self.client.get("/xyn/api/applications", {"workspace_id": str(self.workspace.id)})
        self.assertEqual(response.status_code, 200, response.content.decode())
        self.assertEqual(len(response.json().get("applications") or []), 1)

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc"}, clear=False)
    @mock.patch("xyence.middleware._verify_oidc_token")
    def test_invalid_bearer_is_rejected(self, mock_verify: mock.Mock):
        mock_verify.return_value = None
        response = self.client.get(
            "/xyn/api/applications",
            {"workspace_id": str(self.workspace.id)},
            HTTP_AUTHORIZATION="Bearer invalid",
        )
        self.assertEqual(response.status_code, 401, response.content.decode())
        self.assertFalse(response.has_header("Location"))
        self.assertEqual(response.json().get("error"), "not authenticated")

    def test_missing_auth_returns_json_unauthorized_for_applications_and_runs(self):
        app_response = self.client.get("/xyn/api/applications", {"workspace_id": str(self.workspace.id)})
        self.assertEqual(app_response.status_code, 401, app_response.content.decode())
        self.assertFalse(app_response.has_header("Location"))
        self.assertEqual(app_response.json().get("error"), "not authenticated")

        runs_response = self.client.get("/xyn/api/runs")
        self.assertEqual(runs_response.status_code, 401, runs_response.content.decode())
        self.assertFalse(runs_response.has_header("Location"))
        self.assertEqual(runs_response.json().get("error"), "not authenticated")

        detail_response = self.client.get(f"/xyn/api/applications/{self.application.id}")
        self.assertEqual(detail_response.status_code, 401, detail_response.content.decode())
        self.assertFalse(detail_response.has_header("Location"))
        self.assertEqual(detail_response.json().get("error"), "not authenticated")

        sessions_response = self.client.get(f"/xyn/api/applications/{self.application.id}/change-sessions")
        self.assertEqual(sessions_response.status_code, 401, sessions_response.content.decode())
        self.assertFalse(sessions_response.has_header("Location"))
        self.assertEqual(sessions_response.json().get("error"), "not authenticated")

        control_response = self.client.get(
            f"/xyn/api/applications/{self.application.id}/change-sessions/{self.change_session.id}/control"
        )
        self.assertEqual(control_response.status_code, 401, control_response.content.decode())
        self.assertFalse(control_response.has_header("Location"))
        self.assertEqual(control_response.json().get("error"), "not authenticated")

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc"}, clear=False)
    @mock.patch("xyence.middleware._verify_oidc_token")
    def test_missing_workspace_membership_fails_under_bearer(self, mock_verify: mock.Mock):
        mock_verify.return_value = self._bearer_claims(email="other@example.com", sub="other-subject")
        response = self.client.get(
            "/xyn/api/applications",
            {"workspace_id": str(self.workspace.id)},
            HTTP_AUTHORIZATION="Bearer token-no-membership",
        )
        self.assertEqual(response.status_code, 403, response.content.decode())

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc"}, clear=False)
    @mock.patch("xyence.middleware._verify_oidc_token")
    def test_missing_workspace_capability_fails_under_bearer(self, mock_verify: mock.Mock):
        reader_identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example.com",
            subject="reader-subject",
            email="reader@example.com",
            display_name="Reader",
        )
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user_identity=reader_identity,
            role="reader",
            termination_authority=False,
        )
        mock_verify.return_value = self._bearer_claims(email="reader@example.com", sub="reader-subject")
        response = self.client.post(
            f"/xyn/api/applications/{self.application.id}/change-sessions",
            data=json.dumps({"request_text": "do a change"}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-reader",
        )
        self.assertEqual(response.status_code, 403, response.content.decode())
        self.assertEqual(response.json().get("error"), "forbidden")

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc"}, clear=False)
    @mock.patch("xyence.middleware._verify_oidc_token")
    def test_change_session_control_forbidden_without_workspace_access(self, mock_verify: mock.Mock):
        outsider = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example.com",
            subject="outsider-subject",
            email="outsider@example.com",
            display_name="Outsider",
        )
        mock_verify.return_value = self._bearer_claims(email=outsider.email, sub=outsider.subject)
        response = self.client.get(
            f"/xyn/api/applications/{self.application.id}/change-sessions/{self.change_session.id}/control",
            HTTP_AUTHORIZATION="Bearer token-outsider",
        )
        self.assertEqual(response.status_code, 403, response.content.decode())
        self.assertEqual(response.json().get("error"), "forbidden")

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc"}, clear=False)
    @mock.patch("xyence.middleware._verify_oidc_token")
    def test_artifacts_endpoint_still_works_with_bearer_auth(self, mock_verify: mock.Mock):
        mock_verify.return_value = self._bearer_claims()
        response = self.client.get("/xyn/api/artifacts", HTTP_AUTHORIZATION="Bearer token-ok")
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertIn("artifacts", payload)

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc"}, clear=False)
    @mock.patch("xyence.middleware._verify_oidc_token")
    @mock.patch("xyn_orchestrator.xyn_api._advance_solution_planning_after_user_response")
    @mock.patch("xyn_orchestrator.xyn_api._apply_scope_lock_to_selection")
    @mock.patch("xyn_orchestrator.xyn_api._solution_planning_state")
    def test_control_action_accepts_prompt_id_response_contract_for_option_set(
        self,
        mock_planning_state: mock.Mock,
        mock_apply_scope_lock: mock.Mock,
        _mock_advance: mock.Mock,
        mock_verify: mock.Mock,
    ):
        mock_verify.return_value = self._bearer_claims()
        mock_apply_scope_lock.return_value = (["art-1"], False, "")
        mock_planning_state.return_value = {
            "pending_question": None,
            "pending_option_set": {
                "id": "prompt-1",
                "kind": "option_set",
                "payload": {
                    "response_schema": {
                        "type": "object",
                        "required": ["selected_option_id"],
                        "properties": {"selected_option_id": {"type": "string"}},
                    },
                    "options": [{"id": "art-1", "label": "xyn-api"}],
                },
            },
        }
        response = self.client.post(
            f"/xyn/api/applications/{self.application.id}/change-sessions/{self.change_session.id}/control/actions",
            data=json.dumps(
                {
                    "operation": "respond_to_planner_prompt",
                    "prompt_id": "prompt-1",
                    "response": {"selected_option_id": "art-1"},
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-ok",
        )
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertIn("control", payload)
        operation = (payload.get("control") or {}).get("operation") or {}
        self.assertEqual(operation.get("type"), "respond_to_planner_prompt")


class ArtifactScopedChangeSessionTests(TestCase):
    def setUp(self):
        _reset_oidc_caches_for_tests()
        self.workspace = Workspace.objects.create(
            slug=f"artifact-scope-{uuid.uuid4().hex[:8]}",
            name="Artifact Scope Workspace",
        )
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example.com",
            subject=f"artifact-sub-{uuid.uuid4().hex[:8]}",
            email="artifact-admin@example.com",
            display_name="Artifact Admin",
        )
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user_identity=self.identity,
            role="admin",
            termination_authority=True,
        )
        RoleBinding.objects.get_or_create(
            user_identity=self.identity,
            scope_kind="platform",
            scope_id=None,
            role="platform_admin",
        )
        self.artifact_type = ArtifactType.objects.create(name="Runtime Module", slug=f"runtime-module-{uuid.uuid4().hex[:8]}")
        self.xyn_api_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=self.artifact_type,
            title="xyn-api",
            slug="xyn-api",
            artifact_state="canonical",
            status="active",
            author=self.identity,
            scope_json={"slug": "xyn-api"},
        )

    def _bearer_claims(self):
        return {
            "iss": "https://issuer.example.com",
            "sub": self.identity.subject,
            "email": self.identity.email,
            "email_verified": True,
            "name": "Artifact Admin",
            "aud": "xyn-ui",
        }

    def test_decomposition_request_text_derivation_is_deterministic(self):
        decomposition_campaign = {
            "target_source_files": ["backend/xyn_orchestrator/xyn_api.py"],
            "extraction_seams": ["solution_change_session_workflow", "stage_apply_dispatch"],
            "moved_handlers_modules": [
                "backend/xyn_orchestrator/api/solutions.py",
                "backend/xyn_orchestrator/solution_change_session/stage_apply_dispatch.py",
            ],
            "required_test_suites": ["test_solution_planner_engine", "test_goal_planning"],
        }
        first = _build_change_request_text_from_decomposition_campaign(decomposition_campaign)
        second = _build_change_request_text_from_decomposition_campaign(dict(decomposition_campaign))
        self.assertEqual(first, second)
        self.assertIn("backend/xyn_orchestrator/xyn_api.py", first)
        self.assertIn("Preserve route behavior, response contracts, and compatibility wrappers in xyn_api.py.", first)
        self.assertIn("solution_change_session_workflow", first)

    def _create_artifact_scoped_session_records(self) -> SolutionChangeSession:
        application = Application.objects.create(
            workspace=self.workspace,
            name="Artifact Scoped xyn-api",
            source_factory_key="artifact_scoped_decomposition",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"artifact-scope::{self.xyn_api_artifact.id}",
            metadata_json={
                "scope": {
                    "scope_type": "artifact",
                    "workspace_id": str(self.workspace.id),
                    "artifact_id": str(self.xyn_api_artifact.id),
                    "artifact_slug": "xyn-api",
                }
            },
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=self.xyn_api_artifact,
            role="primary_api",
            responsibility_summary="artifact-scoped test",
            metadata_json={"scope_type": "artifact"},
            sort_order=0,
        )
        return SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Artifact Session",
            request_text="Decompose xyn_api.py",
            created_by=self.identity,
            metadata_json={
                "scope": {
                    "scope_type": "artifact",
                    "workspace_id": str(self.workspace.id),
                    "application_id": str(application.id),
                    "artifact_id": str(self.xyn_api_artifact.id),
                    "artifact_slug": "xyn-api",
                }
            },
        )

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc"}, clear=False)
    @mock.patch("xyence.middleware._verify_oidc_token")
    @mock.patch("xyn_orchestrator.xyn_api._maybe_emit_solution_checkpoint_turn")
    @mock.patch("xyn_orchestrator.xyn_api._reset_solution_stage_checkpoint")
    @mock.patch("xyn_orchestrator.xyn_api._record_solution_draft_plan")
    @mock.patch("xyn_orchestrator.xyn_api._solution_planning_state")
    @mock.patch("xyn_orchestrator.xyn_api._build_solution_impacted_analysis")
    def test_artifact_scoped_decomposition_session_works_without_existing_application(
        self,
        mock_analysis: mock.Mock,
        mock_planning_state: mock.Mock,
        _mock_record_plan: mock.Mock,
        _mock_reset_checkpoint: mock.Mock,
        _mock_emit_checkpoint: mock.Mock,
        mock_verify: mock.Mock,
    ):
        mock_verify.return_value = self._bearer_claims()
        mock_analysis.return_value = {"suggested_artifact_ids": [str(self.xyn_api_artifact.id)]}
        mock_planning_state.return_value = {"pending_question": None, "pending_option_set": None, "latest_draft_plan": {"ok": True}}

        create_response = self.client.post(
            "/xyn/api/change-sessions",
            data=json.dumps(
                {
                    "workspace_id": str(self.workspace.id),
                    "artifact_slug": "xyn-api",
                    "request_text": "Decompose xyn_api.py",
                    "decomposition_campaign": {
                        "kind": "xyn_api_decomposition",
                        "target_source_files": ["backend/xyn_orchestrator/xyn_api.py"],
                    },
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-artifact-scope",
        )
        self.assertEqual(create_response.status_code, 201, create_response.content.decode())
        payload = create_response.json()
        self.assertEqual(payload.get("scope_type"), "artifact")
        self.assertEqual(payload.get("artifact_slug"), "xyn-api")
        session = payload.get("session") or {}
        self.assertEqual((session.get("scope") or {}).get("artifact_slug"), "xyn-api")
        session_id = str(session.get("id") or "").strip()
        self.assertTrue(session_id)

        generated_application_id = str(payload.get("application_id") or "").strip()
        self.assertTrue(generated_application_id)
        self.assertTrue(
            ApplicationArtifactMembership.objects.filter(
                application_id=generated_application_id,
                artifact_id=self.xyn_api_artifact.id,
            ).exists()
        )

        control_response = self.client.get(
            f"/xyn/api/change-sessions/{session_id}/control",
            HTTP_AUTHORIZATION="Bearer token-artifact-scope",
        )
        self.assertEqual(control_response.status_code, 200, control_response.content.decode())

        plan_response = self.client.post(
            f"/xyn/api/change-sessions/{session_id}/plan",
            data=json.dumps({}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-artifact-scope",
        )
        self.assertEqual(plan_response.status_code, 200, plan_response.content.decode())

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc"}, clear=False)
    @mock.patch("xyence.middleware._verify_oidc_token")
    @mock.patch("xyn_orchestrator.xyn_api._maybe_emit_solution_checkpoint_turn")
    @mock.patch("xyn_orchestrator.xyn_api._reset_solution_stage_checkpoint")
    @mock.patch("xyn_orchestrator.xyn_api._record_solution_draft_plan")
    @mock.patch("xyn_orchestrator.xyn_api._solution_planning_state")
    @mock.patch("xyn_orchestrator.xyn_api._build_solution_impacted_analysis")
    def test_artifact_scoped_decomposition_session_derives_request_text_when_omitted(
        self,
        mock_analysis: mock.Mock,
        mock_planning_state: mock.Mock,
        _mock_record_plan: mock.Mock,
        _mock_reset_checkpoint: mock.Mock,
        _mock_emit_checkpoint: mock.Mock,
        mock_verify: mock.Mock,
    ):
        mock_verify.return_value = self._bearer_claims()

        captured: Dict[str, Any] = {}

        def _analysis_side_effect(*, request_text: str, **kwargs):
            captured["request_text"] = request_text
            return {"suggested_artifact_ids": [str(self.xyn_api_artifact.id)]}

        mock_analysis.side_effect = _analysis_side_effect
        mock_planning_state.return_value = {"pending_question": None, "pending_option_set": None, "latest_draft_plan": {"ok": True}}

        response = self.client.post(
            "/xyn/api/change-sessions",
            data=json.dumps(
                {
                    "workspace_id": str(self.workspace.id),
                    "artifact_slug": "xyn-api",
                    "decomposition_campaign": {
                        "kind": "xyn_api_decomposition",
                        "target_source_files": ["backend/xyn_orchestrator/xyn_api.py"],
                        "extraction_seams": ["solution_change_plan_generation"],
                        "moved_handlers_modules": ["backend/xyn_orchestrator/api/solutions.py"],
                        "required_test_suites": ["test_solution_planner_engine"],
                    },
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-derived-request-text",
        )
        self.assertEqual(response.status_code, 201, response.content.decode())
        payload = response.json()
        session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
        derived_request_text = str(session.get("request_text") or "")
        self.assertTrue(derived_request_text)
        self.assertIn("backend/xyn_orchestrator/xyn_api.py", derived_request_text)
        self.assertIn("Preserve route behavior, response contracts, and compatibility wrappers in xyn_api.py.", derived_request_text)
        self.assertEqual(captured.get("request_text"), derived_request_text)

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc"}, clear=False)
    @mock.patch("xyence.middleware._verify_oidc_token")
    def test_artifact_scoped_decomposition_without_target_files_still_returns_structured_validation_error(
        self,
        mock_verify: mock.Mock,
    ):
        mock_verify.return_value = self._bearer_claims()
        response = self.client.post(
            "/xyn/api/change-sessions",
            data=json.dumps(
                {
                    "workspace_id": str(self.workspace.id),
                    "artifact_slug": "xyn-api",
                    "decomposition_campaign": {
                        "kind": "xyn_api_decomposition",
                        "extraction_seams": ["solution_change_plan_generation"],
                    },
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-validation-structured",
        )
        self.assertEqual(response.status_code, 400, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("error"), "request_text is required")
        self.assertEqual(payload.get("blocked_reason"), "backend_validation_error")
        self.assertEqual(payload.get("error_classification"), "backend_validation_error")
        self.assertIsInstance(payload.get("decomposition_campaign"), dict)

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc"}, clear=False)
    @mock.patch("xyence.middleware._verify_oidc_token")
    def test_artifact_scoped_decomposition_single_option_auto_locks_without_prompt(
        self,
        mock_verify: mock.Mock,
    ):
        mock_verify.return_value = self._bearer_claims()
        response = self.client.post(
            "/xyn/api/change-sessions",
            data=json.dumps(
                {
                    "workspace_id": str(self.workspace.id),
                    "artifact_slug": "xyn-api",
                    "decomposition_campaign": {
                        "kind": "xyn_api_decomposition",
                        "target_source_files": ["backend/xyn_orchestrator/xyn_api.py"],
                        "extraction_seams": [
                            "solution_change_plan_generation",
                            "solution_change_preview_validation",
                            "solution_change_session_workflow",
                            "stage_apply_dispatch",
                            "stage_apply_scoping",
                            "stage_apply_git",
                            "intent_resolution",
                        ],
                        "moved_handlers_modules": [
                            "backend/xyn_orchestrator/api/solutions.py",
                            "backend/xyn_orchestrator/api/runtime.py",
                            "backend/xyn_orchestrator/solution_change_session/stage_apply_workflow.py",
                            "backend/xyn_orchestrator/solution_change_session/stage_apply_dispatch.py",
                            "backend/xyn_orchestrator/solution_change_session/stage_apply_scoping.py",
                            "backend/xyn_orchestrator/solution_change_session/stage_apply_git.py",
                        ],
                        "required_test_suites": [
                            "test_solution_planner_engine",
                            "test_goal_planning",
                            "test_solution_change_session_repo_commits",
                            "test_api_route_domain_split",
                        ],
                    },
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-single-option-autolock",
        )
        self.assertEqual(response.status_code, 201, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("scope_type"), "artifact")
        self.assertEqual(payload.get("artifact_slug"), "xyn-api")
        session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
        planning = session.get("planning") if isinstance(session.get("planning"), dict) else {}
        self.assertFalse(bool(planning.get("pending_option_set")))
        self.assertTrue(bool(planning.get("decomposition_scope_locked")))
        expected_artifact_id = str(payload.get("artifact_id") or "")
        self.assertTrue(expected_artifact_id)
        self.assertEqual(
            [str(item) for item in (planning.get("locked_artifact_ids") or [])],
            [expected_artifact_id],
        )
        self.assertEqual(
            [str(item) for item in (session.get("selected_artifact_ids") or [])],
            [expected_artifact_id],
        )
        plan = session.get("plan") if isinstance(session.get("plan"), dict) else {}
        self.assertEqual(str(plan.get("planning_mode") or ""), "decompose_existing_system")
        self.assertTrue(bool(plan.get("proposed_moves")))
        self.assertTrue(bool(plan.get("file_operations")))
        self.assertTrue(bool(plan.get("test_operations")))
        self.assertTrue(bool(plan.get("destination_modules")))
        self.assertTrue(bool(plan.get("ordered_extraction_sequence")))

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc"}, clear=False)
    @mock.patch("xyence.middleware._verify_oidc_token")
    @mock.patch("xyn_orchestrator.xyn_api._maybe_emit_solution_checkpoint_turn")
    @mock.patch("xyn_orchestrator.xyn_api._reset_solution_stage_checkpoint")
    @mock.patch("xyn_orchestrator.xyn_api._record_solution_draft_plan")
    @mock.patch("xyn_orchestrator.xyn_api._solution_planning_state")
    @mock.patch("xyn_orchestrator.xyn_api._build_solution_impacted_analysis")
    def test_artifact_scoped_decomposition_session_resolves_single_workspace_when_omitted(
        self,
        mock_analysis: mock.Mock,
        mock_planning_state: mock.Mock,
        _mock_record_plan: mock.Mock,
        _mock_reset_checkpoint: mock.Mock,
        _mock_emit_checkpoint: mock.Mock,
        mock_verify: mock.Mock,
    ):
        mock_verify.return_value = self._bearer_claims()
        mock_analysis.return_value = {"suggested_artifact_ids": [str(self.xyn_api_artifact.id)]}
        mock_planning_state.return_value = {
            "pending_question": None,
            "pending_option_set": None,
            "latest_draft_plan": {
                "planning_mode": "decompose_existing_system",
                "proposed_moves": [{"source": "backend/xyn_orchestrator/xyn_api.py"}],
                "file_operations": [{"path": "backend/xyn_orchestrator/api/solutions.py", "operation": "create"}],
                "test_operations": [{"suite": "test_solution_planner_engine"}],
                "destination_modules": ["backend/xyn_orchestrator/api/solutions.py"],
                "ordered_extraction_sequence": ["solution_change_plan_generation"],
            },
        }

        response = self.client.post(
            "/xyn/api/change-sessions",
            data=json.dumps(
                {
                    "artifact_slug": "xyn-api",
                    "request_text": "Decompose xyn_api.py without explicit workspace",
                    "decomposition_campaign": {
                        "kind": "xyn_api_decomposition",
                        "target_source_files": ["backend/xyn_orchestrator/xyn_api.py"],
                        "extraction_seams": ["solution_change_plan_generation"],
                    },
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-no-workspace",
        )
        self.assertEqual(response.status_code, 201, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("scope_type"), "artifact")
        self.assertEqual(payload.get("artifact_slug"), "xyn-api")
        self.assertEqual((payload.get("scope") or {}).get("workspace_id"), str(self.workspace.id))
        session = payload.get("session") or {}
        self.assertEqual((session.get("scope") or {}).get("artifact_slug"), "xyn-api")
        self.assertEqual((session.get("scope") or {}).get("workspace_id"), str(self.workspace.id))
        self.assertEqual((session.get("scope") or {}).get("application_id"), str(payload.get("application_id") or ""))

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc"}, clear=False)
    @mock.patch("xyence.middleware._verify_oidc_token")
    @mock.patch("xyn_orchestrator.xyn_api._maybe_emit_solution_checkpoint_turn")
    @mock.patch("xyn_orchestrator.xyn_api._reset_solution_stage_checkpoint")
    @mock.patch("xyn_orchestrator.xyn_api._record_solution_draft_plan")
    @mock.patch("xyn_orchestrator.xyn_api._solution_planning_state")
    @mock.patch("xyn_orchestrator.xyn_api._build_solution_impacted_analysis")
    def test_artifact_scoped_decomposition_session_application_provisioning_is_idempotent(
        self,
        mock_analysis: mock.Mock,
        mock_planning_state: mock.Mock,
        _mock_record_plan: mock.Mock,
        _mock_reset_checkpoint: mock.Mock,
        _mock_emit_checkpoint: mock.Mock,
        mock_verify: mock.Mock,
    ):
        mock_verify.return_value = self._bearer_claims()
        mock_analysis.return_value = {"suggested_artifact_ids": [str(self.xyn_api_artifact.id)]}
        mock_planning_state.return_value = {"pending_question": None, "pending_option_set": None, "latest_draft_plan": {"ok": True}}

        def _create():
            return self.client.post(
                "/xyn/api/change-sessions",
                data=json.dumps(
                    {
                        "artifact_slug": "xyn-api",
                        "request_text": "Decompose xyn_api.py idempotent provisioning",
                        "decomposition_campaign": {
                            "kind": "xyn_api_decomposition",
                            "target_source_files": ["backend/xyn_orchestrator/xyn_api.py"],
                        },
                    }
                ),
                content_type="application/json",
                HTTP_AUTHORIZATION="Bearer token-idempotent",
            )

        first = _create()
        second = _create()
        self.assertEqual(first.status_code, 201, first.content.decode())
        self.assertEqual(second.status_code, 201, second.content.decode())
        first_payload = first.json()
        second_payload = second.json()
        self.assertEqual(first_payload.get("application_id"), second_payload.get("application_id"))
        fingerprint = f"artifact-scope::{self.xyn_api_artifact.id}"
        self.assertEqual(Application.objects.filter(workspace=self.workspace, plan_fingerprint=fingerprint).count(), 1)

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc"}, clear=False)
    @mock.patch("xyence.middleware._verify_oidc_token")
    @mock.patch("xyn_orchestrator.xyn_api._maybe_emit_solution_checkpoint_turn")
    @mock.patch("xyn_orchestrator.xyn_api._reset_solution_stage_checkpoint")
    @mock.patch("xyn_orchestrator.xyn_api._record_solution_draft_plan")
    @mock.patch("xyn_orchestrator.xyn_api._solution_planning_state")
    @mock.patch("xyn_orchestrator.xyn_api._build_solution_impacted_analysis")
    def test_artifact_scope_infers_xyn_api_from_target_source_path(
        self,
        mock_analysis: mock.Mock,
        mock_planning_state: mock.Mock,
        _mock_record_plan: mock.Mock,
        _mock_reset_checkpoint: mock.Mock,
        _mock_emit_checkpoint: mock.Mock,
        mock_verify: mock.Mock,
    ):
        mock_verify.return_value = self._bearer_claims()
        mock_analysis.return_value = {"suggested_artifact_ids": [str(self.xyn_api_artifact.id)]}
        mock_planning_state.return_value = {"pending_question": None, "pending_option_set": None, "latest_draft_plan": {"ok": True}}
        response = self.client.post(
            "/xyn/api/change-sessions",
            data=json.dumps(
                {
                    "workspace_id": str(self.workspace.id),
                    "request_text": "Decompose by path inference",
                    "decomposition_campaign": {
                        "kind": "xyn_api_decomposition",
                        "target_source_files": ["backend/xyn_orchestrator/xyn_api.py"],
                    },
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-path-infer",
        )
        self.assertEqual(response.status_code, 201, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("scope_type"), "artifact")
        self.assertEqual(payload.get("artifact_slug"), "xyn-api")

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc"}, clear=False)
    @mock.patch("xyence.middleware._verify_oidc_token")
    def test_artifact_scope_ambiguous_target_path_returns_structured_error(self, mock_verify: mock.Mock):
        mock_verify.return_value = self._bearer_claims()
        Artifact.objects.create(
            workspace=self.workspace,
            type=self.artifact_type,
            title="xyn-ui",
            slug="xyn-ui",
            artifact_state="canonical",
            status="active",
            author=self.identity,
            scope_json={"slug": "xyn-ui"},
        )
        response = self.client.post(
            "/xyn/api/change-sessions",
            data=json.dumps(
                {
                    "workspace_id": str(self.workspace.id),
                    "request_text": "Ambiguous target",
                    "decomposition_campaign": {
                        "kind": "xyn_api_decomposition",
                        "target_source_files": ["backend/src/shared/module.ts"],
                    },
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-ambiguous",
        )
        self.assertEqual(response.status_code, 409, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("blocked_reason"), "scope_resolution_failed")
        self.assertEqual(payload.get("error_classification"), "scope_resolution_failed")
        candidates = payload.get("candidate_artifact_slugs") or []
        self.assertIn("xyn-api", candidates)
        self.assertIn("xyn-ui", candidates)
        self.assertFalse(response.has_header("Location"))

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc"}, clear=False)
    @mock.patch("xyence.middleware._verify_oidc_token")
    def test_artifact_scope_requires_workspace_hint_when_multiple_workspaces_accessible(self, mock_verify: mock.Mock):
        mock_verify.return_value = self._bearer_claims()
        second_workspace = Workspace.objects.create(
            slug=f"artifact-scope-extra-{uuid.uuid4().hex[:8]}",
            name="Artifact Scope Extra",
        )
        WorkspaceMembership.objects.create(
            workspace=second_workspace,
            user_identity=self.identity,
            role="admin",
            termination_authority=True,
        )
        response = self.client.post(
            "/xyn/api/change-sessions",
            data=json.dumps(
                {
                    "artifact_slug": "xyn-api",
                    "request_text": "Should require workspace disambiguation",
                    "decomposition_campaign": {
                        "kind": "xyn_api_decomposition",
                        "target_source_files": ["backend/xyn_orchestrator/xyn_api.py"],
                    },
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-workspace-ambiguous",
        )
        self.assertEqual(response.status_code, 409, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("blocked_reason"), "scope_resolution_failed")
        self.assertEqual(payload.get("error_classification"), "scope_resolution_failed")
        candidates = payload.get("candidate_artifacts")
        self.assertIsInstance(candidates, list)
        self.assertGreaterEqual(len(candidates), 2)

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc"}, clear=False)
    @mock.patch("xyence.middleware._verify_oidc_token")
    @mock.patch("xyn_orchestrator.xyn_api._maybe_emit_solution_checkpoint_turn")
    @mock.patch("xyn_orchestrator.xyn_api._reset_solution_stage_checkpoint")
    @mock.patch("xyn_orchestrator.xyn_api._record_solution_draft_plan")
    @mock.patch("xyn_orchestrator.xyn_api._solution_planning_state")
    @mock.patch("xyn_orchestrator.xyn_api._build_solution_impacted_analysis")
    def test_artifact_id_resolution_realigns_workspace_for_change_session_create(
        self,
        mock_analysis: mock.Mock,
        mock_planning_state: mock.Mock,
        _mock_record_plan: mock.Mock,
        _mock_reset_checkpoint: mock.Mock,
        _mock_emit_checkpoint: mock.Mock,
        mock_verify: mock.Mock,
    ):
        mock_verify.return_value = self._bearer_claims()
        mock_analysis.return_value = {"suggested_artifact_ids": [str(self.xyn_api_artifact.id)]}
        mock_planning_state.return_value = {"pending_question": None, "pending_option_set": None, "latest_draft_plan": {"ok": True}}

        second_workspace = Workspace.objects.create(
            slug=f"artifact-scope-extra2-{uuid.uuid4().hex[:8]}",
            name="Artifact Scope Extra 2",
        )
        WorkspaceMembership.objects.create(
            workspace=second_workspace,
            user_identity=self.identity,
            role="admin",
            termination_authority=True,
        )

        response = self.client.post(
            "/xyn/api/change-sessions",
            data=json.dumps(
                {
                    "workspace_id": str(second_workspace.id),
                    "artifact_id": str(self.xyn_api_artifact.id),
                    "request_text": "Decompose xyn_api.py with artifact-id and mismatched workspace",
                    "decomposition_campaign": {
                        "kind": "xyn_api_decomposition",
                        "target_source_files": ["backend/xyn_orchestrator/xyn_api.py"],
                    },
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-realign",
        )
        self.assertEqual(response.status_code, 201, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("scope_type"), "artifact")
        self.assertEqual(payload.get("artifact_id"), str(self.xyn_api_artifact.id))
        scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
        self.assertEqual(scope.get("workspace_id"), str(self.workspace.id))
        self.assertEqual(scope.get("artifact_slug"), "xyn-api")

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc"}, clear=False)
    @mock.patch("xyence.middleware._verify_oidc_token")
    @mock.patch("xyn_orchestrator.xyn_api.application_solution_change_session_checkpoint_decision")
    def test_session_scoped_checkpoint_decision_route_delegates_for_artifact_scope(
        self,
        mock_decision: mock.Mock,
        mock_verify: mock.Mock,
    ):
        session = self._create_artifact_scoped_session_records()
        mock_verify.return_value = self._bearer_claims()
        mock_decision.return_value = JsonResponse({"recorded": True}, status=200)
        response = self.client.post(
            f"/xyn/api/change-sessions/{session.id}/checkpoints/{uuid.uuid4()}/decision",
            data=json.dumps({"decision": "approved"}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-checkpoint",
        )
        self.assertEqual(response.status_code, 200, response.content.decode())
        self.assertEqual(response.json().get("recorded"), True)
        self.assertTrue(mock_decision.called)

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc"}, clear=False)
    @mock.patch("xyence.middleware._verify_oidc_token")
    @mock.patch("xyn_orchestrator.xyn_api.application_solution_change_session_stage_apply")
    def test_session_scoped_stage_apply_control_action_works_without_application_in_route(
        self,
        mock_stage_apply: mock.Mock,
        mock_verify: mock.Mock,
    ):
        session = self._create_artifact_scoped_session_records()
        session.plan_json = {"summary": "ready"}
        session.save(update_fields=["plan_json", "updated_at"])
        mock_verify.return_value = self._bearer_claims()
        mock_stage_apply.return_value = JsonResponse({"started": True}, status=202)
        response = self.client.post(
            f"/xyn/api/change-sessions/{session.id}/control/actions",
            data=json.dumps({"operation": "stage_apply", "dispatch_runtime": True}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer token-stage-apply",
        )
        self.assertIn(response.status_code, {200, 202}, response.content.decode())
        payload = response.json()
        control = payload.get("control") if isinstance(payload.get("control"), dict) else {}
        session_block = control.get("session") if isinstance(control.get("session"), dict) else {}
        self.assertEqual(session_block.get("scope_type"), "artifact")
