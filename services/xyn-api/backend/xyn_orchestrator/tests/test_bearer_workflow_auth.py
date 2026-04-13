import json
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from xyence.middleware import _reset_oidc_caches_for_tests
from xyn_orchestrator.models import (
    Application,
    RoleBinding,
    SolutionChangeSession,
    UserIdentity,
    Workspace,
    WorkspaceMembership,
)


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
        self.assertFalse(response.has_header("Location"))

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
