from django.contrib.auth import get_user_model
from django.test import TestCase

from xyn_orchestrator.capabilities.capability_service import get_capabilities
from xyn_orchestrator.models import RoleBinding, UserIdentity


class ContextualCapabilitiesTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="caps-admin", password="pass", is_staff=True)
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer",
            subject="caps-admin",
            email="caps-admin@example.com",
        )
        RoleBinding.objects.create(user_identity=self.identity, scope_kind="platform", role="platform_admin")
        self.client.force_login(self.user)
        session = self.client.session
        session["user_identity_id"] = str(self.identity.id)
        session.save()

    def test_service_resolves_landing_by_default(self):
        payload = get_capabilities()
        self.assertEqual(payload["context"], "landing")
        self.assertEqual(payload["capabilities"][0]["id"], "build_application")

    def test_service_prefers_artifact_context(self):
        payload = get_capabilities(artifact_id="art-1")
        self.assertEqual(payload["context"], "artifact_draft")
        self.assertEqual(payload["capabilities"][0]["id"], "revise_draft")

    def test_service_accepts_explicit_plan_review_context(self):
        payload = get_capabilities(context="plan_review", application_id="app-1")
        self.assertEqual(payload["context"], "plan_review")
        self.assertEqual(payload["capabilities"][0]["id"], "review_plan")

    def test_endpoint_returns_contextual_capabilities(self):
        response = self.client.get("/xyn/api/contextual-capabilities", {"context": "landing"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["context"], "landing")
        self.assertGreaterEqual(len(payload["capabilities"]), 1)
        self.assertEqual(payload["capabilities"][0]["id"], "build_application")
