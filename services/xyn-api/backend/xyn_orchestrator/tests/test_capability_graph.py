from django.contrib.auth import get_user_model
from django.test import TestCase

from xyn_orchestrator.capabilities.graph.capability_graph import get_capability_ids_for_context
from xyn_orchestrator.capabilities.graph.graph_service import get_capabilities_for_context
from xyn_orchestrator.models import RoleBinding, UserIdentity


class CapabilityGraphTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="graph-admin", password="pass", is_staff=True)
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer",
            subject="graph-admin",
            email="graph-admin@example.com",
        )
        RoleBinding.objects.create(user_identity=self.identity, scope_kind="platform", role="platform_admin")
        self.client.force_login(self.user)
        session = self.client.session
        session["user_identity_id"] = str(self.identity.id)
        session.save()

    def test_graph_resolves_landing_capabilities(self):
        self.assertEqual(
            get_capability_ids_for_context("landing"),
            ["build_application", "write_article", "create_explainer_video", "explore_artifacts"],
        )

    def test_graph_service_returns_app_draft_capabilities(self):
        payload = get_capabilities_for_context(context="app_intent_draft", entity_id="draft-1", workspace_id="ws-1")
        self.assertEqual(payload["context"], "app_intent_draft")
        self.assertEqual(payload["entityId"], "draft-1")
        self.assertEqual(payload["workspaceId"], "ws-1")
        self.assertEqual(payload["capabilities"][0]["id"], "continue_application_draft")
        self.assertEqual(payload["capabilities"][0]["action_type"], "prompt")

    def test_graph_service_normalizes_legacy_artifact_draft_context(self):
        payload = get_capabilities_for_context(context="artifact_draft")
        self.assertEqual(payload["context"], "artifact_detail")
        self.assertEqual(payload["capabilities"][0]["id"], "view_artifact_details")
        self.assertEqual(payload["capabilities"][0]["action_type"], "open_descriptor")
        self.assertEqual(payload["capabilities"][0]["action_target"], "fromArtifactDetail")

    def test_endpoint_returns_context_capabilities(self):
        response = self.client.get(
            "/xyn/api/capabilities/context",
            {"context": "artifact_registry", "workspaceId": "ws-1"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["context"], "artifact_registry")
        self.assertEqual(payload["workspaceId"], "ws-1")
        self.assertGreaterEqual(len(payload["capabilities"]), 1)
        self.assertEqual(payload["capabilities"][0]["id"], "explore_artifacts")
        self.assertEqual(payload["capabilities"][0]["action_type"], "prompt")
