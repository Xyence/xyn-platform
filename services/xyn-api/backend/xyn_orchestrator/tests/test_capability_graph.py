from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from xyn_orchestrator.capabilities.graph.capability_graph import get_capability_ids_for_context
from xyn_orchestrator.capabilities.graph.graph_service import get_capabilities_for_context
from xyn_orchestrator.capabilities.graph.path_service import get_capability_paths_for_context
from xyn_orchestrator.models import RoleBinding, UserIdentity, Workspace


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
        self.workspace = Workspace.objects.create(name="Capability Graph", slug="capability-graph")
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

    def test_graph_service_returns_app_draft_capabilities_when_state_is_valid(self):
        payload = get_capabilities_for_context(
            context="app_intent_draft",
            entity_id="draft-1",
            workspace_id="ws-1",
            entity_state={"draft_state": "plan_ready", "execution_state": None, "application_exists": False},
        )
        self.assertEqual(payload["context"], "app_intent_draft")
        self.assertEqual(payload["entityId"], "draft-1")
        self.assertEqual(payload["workspaceId"], "ws-1")
        self.assertEqual([entry["id"] for entry in payload["capabilities"]], ["continue_application_draft"])
        self.assertTrue(payload["capabilities"][0]["available"])

    def test_graph_service_filters_invalid_capabilities_for_completed_draft(self):
        payload = get_capabilities_for_context(
            context="app_intent_draft",
            entity_id="draft-1",
            workspace_id="ws-1",
            entity_state={"draft_state": "completed", "execution_state": "completed", "application_exists": True},
        )
        self.assertEqual([entry["id"] for entry in payload["capabilities"]], ["open_application_workspace", "view_execution_status"])

    def test_graph_service_normalizes_legacy_artifact_draft_context(self):
        payload = get_capabilities_for_context(context="artifact_draft")
        self.assertEqual(payload["context"], "artifact_detail")
        self.assertEqual(payload["capabilities"][0]["id"], "view_artifact_details")
        self.assertEqual(payload["capabilities"][0]["action_type"], "open_descriptor")
        self.assertEqual(payload["capabilities"][0]["action_target"], "fromArtifactDetail")

    def test_graph_service_filters_console_workspace_open_without_application_state(self):
        payload = get_capabilities_for_context(context="console", workspace_id="ws-1", entity_state={})
        self.assertEqual([entry["id"] for entry in payload["capabilities"]], ["build_application", "explore_artifacts"])

    def test_endpoint_returns_context_capabilities(self):
        response = self.client.get("/xyn/api/capabilities/context", {"context": "artifact_registry", "workspaceId": "ws-1"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["context"], "artifact_registry")
        self.assertEqual(payload["workspaceId"], "ws-1")
        self.assertGreaterEqual(len(payload["capabilities"]), 1)
        self.assertEqual(payload["capabilities"][0]["id"], "explore_artifacts")
        self.assertEqual(payload["capabilities"][0]["action_type"], "prompt")
        self.assertTrue(payload["capabilities"][0]["available"])

    def test_endpoint_filters_app_draft_capabilities_from_runtime_state(self):
        draft_response = mock.Mock(
            status_code=200,
            content=b"{}",
            json=mock.Mock(
                return_value={
                    "id": "draft-1",
                    "status": "submitted",
                    "content_json": {"initial_intent": {"requested_entities": ["poll"]}},
                }
            ),
        )
        jobs_response = mock.Mock(
            status_code=200,
            content=b"[]",
            json=mock.Mock(
                return_value=[
                    {
                        "id": "job-1",
                        "status": "running",
                        "input_json": {"draft_id": "draft-1"},
                        "output_json": {
                            "app_spec": {"app_slug": "team-lunch-poll"},
                            "generated_artifact": {"artifact_slug": "app.team-lunch-poll"},
                        },
                    }
                ]
            ),
        )

        with (
            mock.patch("xyn_orchestrator.xyn_api._resolve_workspace_for_identity", return_value=self.workspace),
            mock.patch("xyn_orchestrator.xyn_api._seed_api_request", side_effect=[draft_response, jobs_response]),
        ):
            response = self.client.get(
                "/xyn/api/capabilities/context",
                {"context": "app_intent_draft", "entityId": "draft-1", "workspaceId": str(self.workspace.id)},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            [entry["id"] for entry in payload["capabilities"]],
            ["open_application_workspace", "view_execution_status"],
        )

    def test_path_service_returns_build_application_path(self):
        payload = get_capability_paths_for_context(context="landing", workspace_id="ws-1")
        self.assertEqual(payload["context"], "landing")
        self.assertEqual(payload["paths"][0]["id"], "build_application")
        self.assertEqual(
            [(step["capability_id"], step["status"]) for step in payload["paths"][0]["steps"]],
            [
                ("build_application", "current"),
                ("continue_application_draft", "pending"),
                ("view_execution_status", "pending"),
                ("open_application_workspace", "pending"),
            ],
        )

    def test_path_service_adapts_completed_app_draft_to_workspace_open(self):
        payload = get_capability_paths_for_context(
            context="app_intent_draft",
            entity_id="draft-1",
            workspace_id="ws-1",
            entity_state={"draft_state": "completed", "execution_state": "completed", "application_exists": True},
        )
        self.assertEqual(payload["paths"][0]["id"], "build_application")
        self.assertEqual(
            [(step["capability_id"], step["status"]) for step in payload["paths"][0]["steps"]],
            [("build_application", "completed"), ("open_application_workspace", "current")],
        )

    def test_path_service_keeps_execution_status_while_app_draft_is_running(self):
        payload = get_capability_paths_for_context(
            context="app_intent_draft",
            entity_id="draft-1",
            workspace_id="ws-1",
            entity_state={"draft_state": "submitted", "execution_state": "executing", "application_exists": True},
        )
        self.assertEqual(
            [(step["capability_id"], step["status"]) for step in payload["paths"][0]["steps"]],
            [
                ("build_application", "completed"),
                ("continue_application_draft", "completed"),
                ("view_execution_status", "current"),
                ("open_application_workspace", "pending"),
            ],
        )

    def test_path_endpoint_returns_artifact_review_path(self):
        response = self.client.get(
            "/xyn/api/capability-paths/context",
            {"context": "artifact_detail", "entityId": "artifact-1", "workspaceId": "ws-1"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["context"], "artifact_detail")
        self.assertEqual(payload["paths"][0]["id"], "artifact_review")
        self.assertEqual(payload["paths"][0]["steps"][0]["capability_id"], "view_artifact_details")

    def test_path_service_filters_invalid_app_draft_steps(self):
        payload = get_capability_paths_for_context(
            context="app_intent_draft",
            entity_id="draft-1",
            workspace_id="ws-1",
            entity_state={"draft_state": "draft", "execution_state": None, "application_exists": False},
        )
        self.assertEqual(
            [(step["capability_id"], step["status"]) for step in payload["paths"][0]["steps"]],
            [
                ("build_application", "completed"),
                ("continue_application_draft", "current"),
                ("view_execution_status", "pending"),
                ("open_application_workspace", "pending"),
            ],
        )

    def test_workspace_exploration_path_truncates_when_workspace_is_initialized(self):
        payload = get_capability_paths_for_context(
            context="application_workspace",
            entity_id="app-1",
            workspace_id="ws-1",
            entity_state={"application_exists": True, "workspace_available": True, "workspace_initialized": True},
        )
        self.assertEqual(payload["paths"][0]["id"], "workspace_exploration")
        self.assertEqual(
            [(step["capability_id"], step["status"]) for step in payload["paths"][0]["steps"]],
            [("open_application_workspace", "completed")],
        )
