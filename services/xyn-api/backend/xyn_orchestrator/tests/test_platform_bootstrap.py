import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from xyn_orchestrator.models import RoleBinding, UserIdentity, Workspace, WorkspaceMembership


class PlatformBootstrapTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="bootstrap-admin",
            email="bootstrap-admin@example.com",
            password="pass",
            is_staff=True,
        )
        self.client.force_login(self.user)
        self.identity = UserIdentity.objects.create(
            provider="local",
            provider_id="local",
            issuer="local",
            subject="bootstrap-admin",
            email="bootstrap-admin@example.com",
            display_name="Bootstrap Admin",
        )
        RoleBinding.objects.create(
            user_identity=self.identity,
            scope_kind="platform",
            role="platform_admin",
        )
        session = self.client.session
        session["user_identity_id"] = str(self.identity.id)
        session.save()

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "dev"}, clear=False)
    def test_dev_me_auto_bootstraps_development_workspace(self):
        self.assertEqual(Workspace.objects.count(), 0)
        response = self.client.get("/xyn/api/me")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        workspaces = payload.get("workspaces") or []
        self.assertEqual(len(workspaces), 1)
        self.assertEqual(workspaces[0]["slug"], "development")
        workspace = Workspace.objects.get(slug="development")
        membership = WorkspaceMembership.objects.filter(workspace=workspace, user_identity=self.identity).first()
        self.assertIsNotNone(membership)
        self.assertEqual(membership.role, "admin")
        self.assertTrue(membership.termination_authority)

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc"}, clear=False)
    def test_non_dev_requires_setup_then_initializes(self):
        status_response = self.client.get("/xyn/api/platform/initialization/status")
        self.assertEqual(status_response.status_code, 200)
        status_payload = status_response.json()["platform_initialization"]
        self.assertFalse(status_payload["initialized"])
        self.assertTrue(status_payload["requires_setup"])

        complete_response = self.client.post(
            "/xyn/api/platform/initialization/complete",
            data=json.dumps({"workspace_name": "Company", "workspace_slug": "company"}),
            content_type="application/json",
        )
        self.assertEqual(complete_response.status_code, 200)
        complete_payload = complete_response.json()
        self.assertEqual(complete_payload["workspace"]["slug"], "company")

        workspace = Workspace.objects.get(slug="company")
        membership = WorkspaceMembership.objects.filter(workspace=workspace, user_identity=self.identity).first()
        self.assertIsNotNone(membership)
        self.assertEqual(membership.role, "admin")
        self.assertTrue(membership.termination_authority)

