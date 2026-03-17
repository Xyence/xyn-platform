from django.contrib.auth import get_user_model
from django.test import TestCase

from xyn_orchestrator.models import RoleBinding, UserIdentity
from xyn_orchestrator.planning.plan_service import get_plan_for_capability


class PlanServiceTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="plan-admin", password="pass", is_staff=True)
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer",
            subject="plan-admin",
            email="plan-admin@example.com",
        )
        RoleBinding.objects.create(user_identity=self.identity, scope_kind="platform", role="platform_admin")
        self.client.force_login(self.user)
        session = self.client.session
        session["user_identity_id"] = str(self.identity.id)
        session.save()

    def test_service_returns_structured_plan(self):
        payload = get_plan_for_capability("build_application")
        self.assertEqual(payload["capability_id"], "build_application")
        self.assertEqual(payload["architecture"]["database"], "PostgreSQL")
        self.assertIn("FastAPI", payload["dependencies"])
        self.assertIn("application_service", payload["components"])
        self.assertEqual(payload["artifacts"], ["application"])

    def test_service_raises_for_unknown_capability(self):
        with self.assertRaisesMessage(ValueError, "Unknown capability"):
            get_plan_for_capability("missing")

    def test_plan_endpoint_returns_plan(self):
        response = self.client.get("/xyn/api/plan", {"capability_id": "build_application"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["capability_id"], "build_application")
        self.assertEqual(payload["architecture"]["interface"], "Xyn language interface")

    def test_plan_endpoint_returns_404_for_unknown_capability(self):
        response = self.client.get("/xyn/api/plan", {"capability_id": "missing"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "Unknown capability")
