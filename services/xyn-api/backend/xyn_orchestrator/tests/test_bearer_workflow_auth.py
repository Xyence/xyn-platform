import json
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from xyn_orchestrator.models import (
    Application,
    RoleBinding,
    UserIdentity,
    Workspace,
    WorkspaceMembership,
)


class BearerWorkflowAuthTests(TestCase):
    def setUp(self):
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
