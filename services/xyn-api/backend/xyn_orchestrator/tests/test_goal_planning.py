import json
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import RequestFactory, TestCase

from xyn_orchestrator.goal_progress import compute_goal_execution_metrics, compute_goal_health_indicators, compute_goal_progress
from xyn_orchestrator.development_intelligence import compute_goal_development_insights, compute_goal_diagnostic
from xyn_orchestrator.goal_planning import decompose_goal, persist_goal_plan, recommend_next_slice, valid_goal_transition
from xyn_orchestrator.application_factories import apply_application_plan, create_or_get_application_plan, infer_application_name
from xyn_orchestrator.portfolio_intelligence import (
    build_goal_portfolio_row,
    build_goal_portfolio_state,
    compute_portfolio_insights,
    recommend_portfolio_goal,
)
from xyn_orchestrator.models import (
    Application,
    ApplicationArtifactMembership,
    ApplicationPlan,
    SolutionChangeSession,
    SolutionPlanningTurn,
    SolutionPlanningCheckpoint,
    Artifact,
    ArtifactType,
    Campaign,
    CampaignType,
    CoordinationEvent,
    CoordinationThread,
    DevTask,
    Goal,
    ManagedRepository,
    UserIdentity,
    Workspace,
    WorkspaceAppInstance,
    WorkspaceMembership,
)
from xyn_orchestrator.xyn_api import (
    application_artifact_membership_detail,
    application_artifact_memberships_collection,
    application_solution_change_session_detail,
    application_solution_change_session_reply,
    application_solution_change_session_regenerate_options,
    application_solution_change_session_select_option,
    application_solution_change_session_checkpoint_decision,
    application_solution_change_session_plan,
    application_solution_change_session_prepare_preview,
    application_solution_change_session_stage_apply,
    application_solution_change_session_validate,
    application_solution_change_sessions_collection,
    application_detail,
    application_factories_collection,
    application_plan_apply,
    application_plan_detail,
    application_plans_collection,
    campaign_detail,
    campaign_types_collection,
    campaigns_collection,
    composer_state,
    goal_decompose,
    goal_detail,
    goal_review,
    goals_collection,
)


class GoalPlanningTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        suffix = uuid.uuid4().hex[:8]
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username=f"planner-{suffix}",
            email=f"planner-{suffix}@example.com",
            password="password",
        )
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example.com",
            subject=f"planner-user-{suffix}",
            email=f"planner-{suffix}@example.com",
        )
        self.workspace = Workspace.objects.create(name="Planning Workspace", slug=f"planning-workspace-{suffix}")
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user_identity=self.identity,
            role="admin",
            termination_authority=True,
        )

    def _request(self, path: str, *, method: str = "get", data=None):
        request = getattr(self.factory, method.lower())(path, data=data or {}, content_type="application/json")
        request.user = self.user
        return request

    def test_goal_can_be_created_listed_and_updated_independently(self):
        request = self._request(
            "/xyn/api/goals",
            method="post",
            data=json.dumps(
                {
                    "workspace_id": str(self.workspace.id),
                    "title": "AI Real Estate Deal Finder",
                    "description": "Build a deal finder using listings and comparables.",
                    "source_conversation_id": "thread-1",
                    "goal_type": "build_system",
                    "priority": "high",
                }
            ),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api._resolve_workspace_for_identity", return_value=self.workspace
        ):
            response = goals_collection(request)
        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.content)
        self.assertEqual(payload["title"], "AI Real Estate Deal Finder")
        self.assertEqual(payload["planning_status"], "proposed")
        self.assertEqual(payload["thread_count"], 0)

        list_request = self._request("/xyn/api/goals", data={"workspace_id": str(self.workspace.id)})
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api._resolve_workspace_for_identity", return_value=self.workspace
        ):
            list_response = goals_collection(list_request)
        listing = json.loads(list_response.content)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(listing["goals"]), 1)
        self.assertIn("portfolio_state", listing)
        self.assertEqual(len(listing["portfolio_state"]["goals"]), 1)

        goal = Goal.objects.get(id=payload["id"])
        patch_request = self._request(
            f"/xyn/api/goals/{goal.id}",
            method="patch",
            data=json.dumps({"planning_status": "decomposed", "planning_summary": "Reviewed plan"}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            patch_response = goal_detail(patch_request, str(goal.id))
        patched = json.loads(patch_response.content)
        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(patched["planning_status"], "decomposed")
        self.assertEqual(patched["planning_summary"], "Reviewed plan")
        self.assertEqual(goal.threads.count(), 0)
        self.assertEqual(goal.work_items.count(), 0)

    def test_goal_status_transitions_are_validated(self):
        self.assertTrue(valid_goal_transition("proposed", "decomposed"))
        self.assertTrue(valid_goal_transition("decomposed", "in_progress"))
        self.assertFalse(valid_goal_transition("completed", "in_progress"))

    def test_campaign_can_be_created_listed_and_updated(self):
        create_request = self._request(
            "/xyn/api/campaigns",
            method="post",
            data=json.dumps(
                {
                    "workspace_id": str(self.workspace.id),
                    "name": "Q2 Launch",
                    "campaign_type": "generic",
                    "description": "Baseline launch campaign",
                }
            ),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            create_response = campaigns_collection(create_request)
        self.assertEqual(create_response.status_code, 201)
        created = json.loads(create_response.content)
        self.assertEqual(created["name"], "Q2 Launch")
        self.assertEqual(created["campaign_type"], "generic")
        self.assertEqual(created["status"], "draft")
        self.assertEqual(created["slug"], "q2-launch")

        list_request = self._request("/xyn/api/campaigns", data={"workspace_id": str(self.workspace.id)})
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            list_response = campaigns_collection(list_request)
        listing = json.loads(list_response.content)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(listing["campaigns"]), 1)
        self.assertEqual(listing["campaigns"][0]["id"], created["id"])

        detail_request = self._request(
            f"/xyn/api/campaigns/{created['id']}",
            method="patch",
            data=json.dumps({"workspace_id": str(self.workspace.id), "status": "active", "description": "Updated description"}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            detail_response = campaign_detail(detail_request, str(created["id"]))
        updated = json.loads(detail_response.content)
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(updated["status"], "active")
        self.assertEqual(updated["description"], "Updated description")

    def test_campaign_listing_is_workspace_scoped(self):
        other_workspace = Workspace.objects.create(name="Other Workspace", slug=f"other-workspace-{uuid.uuid4().hex[:8]}")
        WorkspaceMembership.objects.create(
            workspace=other_workspace,
            user_identity=self.identity,
            role="admin",
            termination_authority=True,
        )
        Campaign.objects.create(
            workspace=self.workspace,
            slug="primary-campaign",
            name="Primary Campaign",
            campaign_type="generic",
            status="draft",
            created_by=self.identity,
        )
        Campaign.objects.create(
            workspace=other_workspace,
            slug="other-campaign",
            name="Other Campaign",
            campaign_type="generic",
            status="draft",
            created_by=self.identity,
        )
        request = self._request("/xyn/api/campaigns", data={"workspace_id": str(self.workspace.id)})
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = campaigns_collection(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["name"] for row in payload["campaigns"]], ["Primary Campaign"])

    def test_campaign_type_catalog_includes_generic_and_enabled_extensions(self):
        CampaignType.objects.create(
            key="global_marketing",
            label="Global Marketing",
            description="Global extension type",
            enabled=True,
        )
        CampaignType.objects.create(
            workspace=self.workspace,
            key="workspace_ops",
            label="Workspace Ops",
            description="Workspace extension type",
            enabled=True,
        )
        CampaignType.objects.create(
            workspace=self.workspace,
            key="disabled_type",
            label="Disabled Type",
            description="Should be filtered",
            enabled=False,
        )
        request = self._request("/xyn/api/campaign-types", data={"workspace_id": str(self.workspace.id)})
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = campaign_types_collection(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        keys = {row["key"] for row in payload["campaign_types"]}
        self.assertIn("generic", keys)
        self.assertIn("global_marketing", keys)
        self.assertIn("workspace_ops", keys)
        self.assertNotIn("disabled_type", keys)

    def test_campaign_model_enforces_workspace_slug_uniqueness(self):
        Campaign.objects.create(
            workspace=self.workspace,
            slug="shared-slug",
            name="One",
            campaign_type="generic",
            status="draft",
            created_by=self.identity,
        )
        with self.assertRaises(IntegrityError):
            Campaign.objects.create(
                workspace=self.workspace,
                slug="shared-slug",
                name="Two",
                campaign_type="generic",
                status="draft",
                created_by=self.identity,
            )

    def test_campaign_model_allows_same_slug_in_different_workspaces(self):
        other_workspace = Workspace.objects.create(name="Alt Workspace", slug=f"alt-workspace-{uuid.uuid4().hex[:8]}")
        Campaign.objects.create(
            workspace=self.workspace,
            slug="shared-slug",
            name="Primary Workspace Campaign",
            campaign_type="generic",
            status="draft",
            created_by=self.identity,
        )
        Campaign.objects.create(
            workspace=other_workspace,
            slug="shared-slug",
            name="Secondary Workspace Campaign",
            campaign_type="generic",
            status="draft",
            created_by=self.identity,
        )
        self.assertEqual(Campaign.objects.filter(slug="shared-slug").count(), 2)

    def test_campaign_list_supports_status_type_and_archived_filters(self):
        CampaignType.objects.create(workspace=self.workspace, key="workspace_ops", label="Workspace Ops", enabled=True)
        Campaign.objects.create(
            workspace=self.workspace,
            slug="draft-generic",
            name="Draft Generic",
            campaign_type="generic",
            status="draft",
            archived=False,
            created_by=self.identity,
        )
        Campaign.objects.create(
            workspace=self.workspace,
            slug="active-ops",
            name="Active Ops",
            campaign_type="workspace_ops",
            status="active",
            archived=False,
            created_by=self.identity,
        )
        Campaign.objects.create(
            workspace=self.workspace,
            slug="archived-generic",
            name="Archived Generic",
            campaign_type="generic",
            status="completed",
            archived=True,
            created_by=self.identity,
        )

        request_default = self._request("/xyn/api/campaigns", data={"workspace_id": str(self.workspace.id)})
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response_default = campaigns_collection(request_default)
        payload_default = json.loads(response_default.content)
        self.assertEqual(response_default.status_code, 200)
        self.assertEqual(len(payload_default["campaigns"]), 2)
        self.assertEqual({row["name"] for row in payload_default["campaigns"]}, {"Draft Generic", "Active Ops"})
        self.assertTrue(any(row["key"] == "generic" for row in payload_default["campaign_types"]))

        request_status = self._request("/xyn/api/campaigns", data={"workspace_id": str(self.workspace.id), "status": "active"})
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response_status = campaigns_collection(request_status)
        payload_status = json.loads(response_status.content)
        self.assertEqual(response_status.status_code, 200)
        self.assertEqual(len(payload_status["campaigns"]), 1)
        self.assertEqual(payload_status["campaigns"][0]["status"], "active")

        request_type = self._request("/xyn/api/campaigns", data={"workspace_id": str(self.workspace.id), "campaign_type": "workspace_ops"})
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response_type = campaigns_collection(request_type)
        payload_type = json.loads(response_type.content)
        self.assertEqual(response_type.status_code, 200)
        self.assertEqual(len(payload_type["campaigns"]), 1)
        self.assertEqual(payload_type["campaigns"][0]["campaign_type"], "workspace_ops")

        request_archived = self._request("/xyn/api/campaigns", data={"workspace_id": str(self.workspace.id), "include_archived": "true"})
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response_archived = campaigns_collection(request_archived)
        payload_archived = json.loads(response_archived.content)
        self.assertEqual(response_archived.status_code, 200)
        self.assertEqual(len(payload_archived["campaigns"]), 3)
        self.assertTrue(any(row["archived"] for row in payload_archived["campaigns"]))

    def test_campaign_create_defaults_to_generic_when_campaign_type_omitted(self):
        request = self._request(
            "/xyn/api/campaigns",
            method="post",
            data=json.dumps({"workspace_id": str(self.workspace.id), "name": "Generic Default"}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = campaigns_collection(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(payload["campaign_type"], "generic")

    def test_campaign_create_rejects_invalid_campaign_type(self):
        request = self._request(
            "/xyn/api/campaigns",
            method="post",
            data=json.dumps(
                {"workspace_id": str(self.workspace.id), "name": "Invalid Type", "campaign_type": "not_registered"}
            ),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = campaigns_collection(request)
        self.assertEqual(response.status_code, 400)
        self.assertIn("campaign_type", json.loads(response.content).get("error", ""))

    def test_campaign_collection_rejects_inaccessible_workspace(self):
        other_workspace = Workspace.objects.create(name="Restricted Workspace", slug=f"restricted-{uuid.uuid4().hex[:8]}")
        request = self._request("/xyn/api/campaigns", data={"workspace_id": str(other_workspace.id)})
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = campaigns_collection(request)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(json.loads(response.content)["error"], "forbidden")

    def test_campaign_detail_read_and_patch_enforce_workspace_membership(self):
        campaign = Campaign.objects.create(
            workspace=self.workspace,
            slug="workspace-campaign",
            name="Workspace Campaign",
            campaign_type="generic",
            status="draft",
            created_by=self.identity,
        )
        foreign_identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example.com",
            subject=f"foreign-{uuid.uuid4().hex[:8]}",
            email=f"foreign-{uuid.uuid4().hex[:8]}@example.com",
        )

        get_request = self._request(f"/xyn/api/campaigns/{campaign.id}", data={"workspace_id": str(self.workspace.id)})
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            get_response = campaign_detail(get_request, str(campaign.id))
        self.assertEqual(get_response.status_code, 200)

        forbidden_get_request = self._request(f"/xyn/api/campaigns/{campaign.id}", data={"workspace_id": str(self.workspace.id)})
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=foreign_identity):
            forbidden_get_response = campaign_detail(forbidden_get_request, str(campaign.id))
        self.assertEqual(forbidden_get_response.status_code, 403)

        forbidden_patch_request = self._request(
            f"/xyn/api/campaigns/{campaign.id}",
            method="patch",
            data=json.dumps({"workspace_id": str(self.workspace.id), "status": "active"}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=foreign_identity):
            forbidden_patch_response = campaign_detail(forbidden_patch_request, str(campaign.id))
        self.assertEqual(forbidden_patch_response.status_code, 403)

    def test_campaign_detail_rejects_workspace_context_mismatch(self):
        other_workspace = Workspace.objects.create(name="Context Workspace", slug=f"context-ws-{uuid.uuid4().hex[:8]}")
        WorkspaceMembership.objects.create(
            workspace=other_workspace,
            user_identity=self.identity,
            role="admin",
            termination_authority=True,
        )
        campaign = Campaign.objects.create(
            workspace=self.workspace,
            slug="context-campaign",
            name="Context Campaign",
            campaign_type="generic",
            status="draft",
            created_by=self.identity,
        )

        get_request = self._request(
            f"/xyn/api/campaigns/{campaign.id}",
            data={"workspace_id": str(other_workspace.id)},
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            get_response = campaign_detail(get_request, str(campaign.id))
        self.assertEqual(get_response.status_code, 404)

        patch_request = self._request(
            f"/xyn/api/campaigns/{campaign.id}",
            method="patch",
            data=json.dumps({"workspace_id": str(other_workspace.id), "status": "active"}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            patch_response = campaign_detail(patch_request, str(campaign.id))
        self.assertEqual(patch_response.status_code, 404)

    def test_campaign_patch_supports_mutations_and_slug_conflict_validation(self):
        CampaignType.objects.create(workspace=self.workspace, key="workspace_ops", label="Workspace Ops", enabled=True)
        primary = Campaign.objects.create(
            workspace=self.workspace,
            slug="alpha",
            name="Alpha",
            campaign_type="generic",
            status="draft",
            archived=False,
            created_by=self.identity,
        )
        Campaign.objects.create(
            workspace=self.workspace,
            slug="beta",
            name="Beta",
            campaign_type="generic",
            status="draft",
            archived=False,
            created_by=self.identity,
        )

        update_request = self._request(
            f"/xyn/api/campaigns/{primary.id}",
            method="patch",
            data=json.dumps(
                {
                    "workspace_id": str(self.workspace.id),
                    "description": "Updated description",
                    "campaign_type": "workspace_ops",
                    "status": "active",
                    "archived": True,
                    "slug": "alpha-updated",
                }
            ),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            update_response = campaign_detail(update_request, str(primary.id))
        updated = json.loads(update_response.content)
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(updated["description"], "Updated description")
        self.assertEqual(updated["campaign_type"], "workspace_ops")
        self.assertEqual(updated["status"], "active")
        self.assertTrue(updated["archived"])
        self.assertEqual(updated["slug"], "alpha-updated")

        conflict_request = self._request(
            f"/xyn/api/campaigns/{primary.id}",
            method="patch",
            data=json.dumps({"workspace_id": str(self.workspace.id), "slug": "beta"}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            conflict_response = campaign_detail(conflict_request, str(primary.id))
        self.assertEqual(conflict_response.status_code, 409)
        self.assertIn("slug", json.loads(conflict_response.content).get("error", ""))

        invalid_type_request = self._request(
            f"/xyn/api/campaigns/{primary.id}",
            method="patch",
            data=json.dumps({"workspace_id": str(self.workspace.id), "campaign_type": "does_not_exist"}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            invalid_type_response = campaign_detail(invalid_type_request, str(primary.id))
        self.assertEqual(invalid_type_response.status_code, 400)
        self.assertIn("campaign_type", json.loads(invalid_type_response.content).get("error", ""))

    def test_campaign_type_catalog_does_not_leak_workspace_specific_types(self):
        other_workspace = Workspace.objects.create(name="Scoped Workspace", slug=f"scoped-{uuid.uuid4().hex[:8]}")
        WorkspaceMembership.objects.create(
            workspace=other_workspace,
            user_identity=self.identity,
            role="admin",
            termination_authority=True,
        )
        CampaignType.objects.create(workspace=self.workspace, key="workspace_only", label="Workspace Only", enabled=True)
        CampaignType.objects.create(workspace=other_workspace, key="other_workspace_only", label="Other Workspace Only", enabled=True)

        request = self._request("/xyn/api/campaign-types", data={"workspace_id": str(self.workspace.id)})
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = campaign_types_collection(request)
        payload = json.loads(response.content)
        keys = {row["key"] for row in payload["campaign_types"]}
        self.assertIn("generic", keys)
        self.assertIn("workspace_only", keys)
        self.assertNotIn("other_workspace_only", keys)

    def test_goal_decomposition_is_deterministic_and_mvp_first(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="AI Real Estate Deal Finder",
            description="Build an AI-driven application that identifies promising real estate deals using listing data, comparables, and scoring.",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="high",
        )
        plan_a = decompose_goal(goal)
        plan_b = decompose_goal(goal)

        self.assertEqual(plan_a.model_dump(mode="json"), plan_b.model_dump(mode="json"))
        self.assertEqual([thread.title for thread in plan_a.threads[:3]], [
            "Core Domain Slice",
            "Operational Surface",
            "Stabilization",
        ])
        self.assertIn("vertical slice", plan_a.planning_summary.lower())
        self.assertEqual(plan_a.work_items[0].title, "Define the minimum durable model for the first working slice")

    def test_generic_goal_decomposition_starts_with_durable_xyn_records(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Generic MVP Goal",
            description="Build a useful application with one MVP slice.",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="high",
        )

        plan = decompose_goal(goal)

        self.assertEqual(plan.work_items[0].title, "Define the minimum durable model for the first working slice")
        self.assertEqual(plan.work_items[0].description, "Model the first end-to-end slice as durable Xyn records.")
        self.assertEqual(plan.work_items[0].priority, "high")
        self.assertEqual(plan.work_items[0].sequence, 1)

    def test_persist_goal_plan_creates_threads_and_work_items(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="AI Real Estate Deal Finder",
            description="Build an AI-driven application that identifies promising real estate deals using listing data, comparables, and scoring.",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="high",
        )
        plan = decompose_goal(goal)
        persisted = persist_goal_plan(goal, plan, user=self.user)
        goal.refresh_from_db()

        self.assertEqual(goal.planning_status, "decomposed")
        self.assertEqual(goal.threads.count(), 3)
        self.assertEqual(goal.work_items.count(), 4)
        self.assertEqual(len(persisted["threads"]), 3)
        self.assertEqual(len(persisted["work_items"]), 4)
        self.assertTrue(all(thread.goal_id == goal.id for thread in goal.threads.all()))
        self.assertTrue(all(task.goal_id == goal.id for task in goal.work_items.all()))
        self.assertTrue(goal.work_items.filter(coordination_thread__title="Core Domain Slice").exists())
        first_task = goal.work_items.order_by("priority", "created_at", "id").first()
        self.assertIsNotNone(first_task)
        self.assertEqual((first_task.execution_brief or {}).get("schema_version"), "v1")
        self.assertEqual((first_task.execution_brief or {}).get("summary"), first_task.title)
        self.assertEqual(first_task.execution_brief_review_state, "draft")
        self.assertEqual(first_task.execution_policy, {"require_brief_approval": True})
        self.assertEqual(
            ((first_task.execution_brief or {}).get("source_context") or {}).get("planning_source"),
            "goal_plan",
        )
        self.assertEqual(
            (((first_task.execution_brief or {}).get("target") or {}).get("goal_id")),
            str(goal.id),
        )

    def test_generic_application_plan_carries_request_entities_into_first_slice(self):
        objective = (
            "Build a simple internal web app called Team Lunch Poll. "
            "Core entities: 1. Poll - title - poll_date - status 2. Lunch Option - poll - name 3. Vote - poll - lunch option - voter_name. "
            "Views / usability: - List all polls - View a poll with its options and vote counts. "
            "Behavior: - Users can create a poll, add lunch options, and cast votes."
        )
        plan, _definition, generated, created = create_or_get_application_plan(
            workspace=self.workspace,
            objective=objective,
            requested_by=self.identity,
            application_name="Team Lunch Poll",
        )
        self.assertTrue(created)
        self.assertEqual(plan.status, "review")
        self.assertIn("Poll", generated.generated_goals[0].description)
        self.assertIn("Lunch Option", generated.generated_goals[0].description)
        self.assertEqual(generated.generated_goals[0].work_items[0].title, "Define the Poll, Lunch Option, and Vote entity model")
        self.assertIn("vote counts", generated.generated_goals[0].work_items[2].description.lower())

    def test_infer_application_name_prefers_named_clause_over_full_objective_text(self):
        objective = (
            "Build an application named \"Real Estate Deal Finder\". "
            "Purpose: identify distressed properties in St. Louis City and surface investor signals."
        )
        self.assertEqual(infer_application_name(objective), "Real Estate Deal Finder")

    def test_application_plan_uses_concise_name_and_preserves_full_request_objective(self):
        objective = (
            "Build an application named \"Real Estate Deal Finder\". "
            "Purpose: identify distressed properties in St. Louis City and surface investor signals. "
            "Requirements: include campaigns, map selection, source governance, and signal feed."
        )
        plan, _definition, generated, created = create_or_get_application_plan(
            workspace=self.workspace,
            objective=objective,
            requested_by=self.identity,
        )
        self.assertTrue(created)
        self.assertEqual(plan.name, "Real Estate Deal Finder")
        self.assertEqual(generated.application_name, "Real Estate Deal Finder")
        self.assertEqual(plan.request_objective, objective)

    def test_apply_application_plan_uses_work_item_description_as_execution_objective(self):
        objective = (
            "Build a simple internal web app called Team Lunch Poll. "
            "Core entities: 1. Poll - title - poll_date - status 2. Lunch Option - poll - name 3. Vote - poll - lunch option - voter_name. "
            "Views / usability: - List all polls - View a poll with its options and vote counts. "
            "Behavior: - Users can create a poll, add lunch options, and cast votes."
        )
        plan, _definition, _generated, _created = create_or_get_application_plan(
            workspace=self.workspace,
            objective=objective,
            requested_by=self.identity,
            application_name="Team Lunch Poll",
        )
        application, created = apply_application_plan(application_plan=plan, user=self.user)
        self.assertTrue(created)
        first_goal = application.goals.order_by("created_at").first()
        self.assertIsNotNone(first_goal)
        first_task = first_goal.work_items.order_by("priority", "created_at", "id").first()
        self.assertIsNotNone(first_task)
        self.assertEqual(
            (first_task.execution_brief or {}).get("objective"),
            "Model Poll, Lunch Option, and Vote as durable Xyn records with the relationships and statuses needed for the first slice.",
        )

    def test_goal_decompose_endpoint_persists_plan(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="AI Real Estate Deal Finder",
            description="Build a deal finder using listings and comparables.",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="high",
        )
        request = self._request(f"/xyn/api/goals/{goal.id}/decompose", method="post", data=json.dumps({}))
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = goal_decompose(request, str(goal.id))
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["goal"]["planning_status"], "decomposed")
        self.assertGreaterEqual(len(payload["threads"]), 1)
        self.assertGreaterEqual(len(payload["work_items"]), 1)
        self.assertEqual(payload["planning_output"]["goal_id"], str(goal.id))

    def test_goal_review_queue_first_slice_marks_goal_in_progress_and_activates_first_thread(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="AI Real Estate Deal Finder",
            description="Build a deal finder using listings and comparables.",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="high",
        )
        persist_goal_plan(goal, decompose_goal(goal), user=self.user)
        recommendation_id = recommend_next_slice(goal).recommendation_id

        request = self._request(
            f"/xyn/api/goals/{goal.id}/review",
            method="post",
            data=json.dumps({"review_action": "queue_first_slice", "recommendation_id": recommendation_id}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api._dispatch_next_queue_item"
        ) as mock_dispatch:
            response = goal_review(request, str(goal.id))
        payload = json.loads(response.content)
        goal.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "approved")
        self.assertEqual(goal.planning_status, "in_progress")
        seeded_task = DevTask.objects.get(id=payload["queue_seed"]["work_item_id"])
        self.assertEqual(seeded_task.status, "queued")
        self.assertEqual(seeded_task.coordination_thread.status, "active")
        self.assertTrue(
            CoordinationEvent.objects.filter(
                thread=seeded_task.coordination_thread,
                event_type="approval_queue_first_slice",
                work_item=seeded_task,
            ).exists()
        )
        mock_dispatch.assert_not_called()

    def test_goal_review_returns_no_recommendation_for_blocked_work_without_side_effects(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Blocked Goal",
            description="Blocked work.",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="high",
        )
        thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Blocked Thread",
            owner=self.identity,
            priority="high",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        task = DevTask.objects.create(
            title="Blocked item",
            description="",
            task_type="codegen",
            status="awaiting_review",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=thread,
            work_item_id="blocked-item",
        )

        request = self._request(
            f"/xyn/api/goals/{goal.id}/review",
            method="post",
            data=json.dumps({"review_action": "approve_and_queue"}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = goal_review(request, str(goal.id))
        payload = json.loads(response.content)
        thread.refresh_from_db()
        goal.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "no_recommendation")
        self.assertEqual(thread.status, "active")
        self.assertEqual(goal.planning_status, "proposed")
        self.assertFalse(CoordinationEvent.objects.filter(event_type="approval_recommendation", work_item=task).exists())

    def test_goal_review_repeat_approval_does_not_duplicate_queue_side_effects(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Repeat Approval Goal",
            description="Repeat approval idempotency.",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="high",
        )
        persist_goal_plan(goal, decompose_goal(goal), user=self.user)
        recommendation_id = recommend_next_slice(goal).recommendation_id

        request = self._request(
            f"/xyn/api/goals/{goal.id}/review",
            method="post",
            data=json.dumps({"review_action": "approve_and_queue", "recommendation_id": recommendation_id}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            first = goal_review(request, str(goal.id))
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            second = goal_review(request, str(goal.id))
        first_payload = json.loads(first.content)
        second_payload = json.loads(second.content)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first_payload["status"], "approved")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second_payload["status"], "already_queued")
        thread_id = first_payload["queue_seed"]["thread_id"]
        self.assertEqual(
            CoordinationEvent.objects.filter(thread_id=thread_id, event_type="approval_recommendation").count(),
            1,
        )

    def test_application_factory_catalog_lists_builtins(self):
        request = self._request("/xyn/api/application-factories")
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = application_factories_collection(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        factory_keys = [row["key"] for row in payload["factories"]]
        self.assertIn("generic_application_mvp", factory_keys)
        self.assertIn("telecom_support_operations_console", factory_keys)
        self.assertIn("reseller_portal", factory_keys)

    def test_application_plan_generation_is_reviewable_and_non_executing(self):
        applications_before = Application.objects.count()
        goals_before = Goal.objects.count()
        threads_before = CoordinationThread.objects.count()
        work_items_before = DevTask.objects.count()
        request = self._request(
            "/xyn/api/application-plans",
            method="post",
            data=json.dumps(
                {
                    "workspace_id": str(self.workspace.id),
                    "objective": "Build an AI real estate deal finder",
                    "source_conversation_id": "thread-1",
                }
            ),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api._dispatch_next_queue_item"
        ) as mock_dispatch:
            response = application_plans_collection(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(payload["status"], "review")
        self.assertEqual(payload["source_factory_key"], "generic_application_mvp")
        self.assertGreaterEqual(len(payload["generated_goals"]), 1)
        self.assertEqual(Application.objects.count(), applications_before)
        self.assertEqual(Goal.objects.count(), goals_before)
        self.assertEqual(CoordinationThread.objects.count(), threads_before)
        self.assertEqual(DevTask.objects.count(), work_items_before)
        mock_dispatch.assert_not_called()

    def test_application_plan_apply_creates_durable_objects_and_is_idempotent(self):
        generate_request = self._request(
            "/xyn/api/application-plans",
            method="post",
            data=json.dumps(
                {
                    "workspace_id": str(self.workspace.id),
                    "objective": "Build an AI real estate deal finder",
                    "source_conversation_id": "thread-1",
                }
            ),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            generate_response = application_plans_collection(generate_request)
        plan_payload = json.loads(generate_response.content)
        plan = ApplicationPlan.objects.get(id=plan_payload["id"])

        apply_request = self._request(f"/xyn/api/application-plans/{plan.id}/apply", method="post", data=json.dumps({}))
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api._dispatch_next_queue_item"
        ) as mock_dispatch:
            apply_response = application_plan_apply(apply_request, str(plan.id))
        applied = json.loads(apply_response.content)
        self.assertEqual(apply_response.status_code, 200)
        self.assertEqual(applied["status"], "applied")
        application = Application.objects.get(id=applied["application"]["id"])
        plan.refresh_from_db()
        self.assertEqual(plan.status, "applied")
        self.assertEqual(plan.application_id, application.id)
        self.assertGreater(application.goals.count(), 0)
        self.assertGreater(CoordinationThread.objects.filter(goal__application=application).count(), 0)
        self.assertGreater(DevTask.objects.filter(goal__application=application).count(), 0)
        mock_dispatch.assert_not_called()

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            second_response = application_plan_apply(apply_request, str(plan.id))
        second_payload = json.loads(second_response.content)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(second_payload["status"], "already_applied")
        self.assertEqual(Application.objects.filter(id=application.id).count(), 1)

    def test_application_plan_target_repository_propagates_to_application_and_generated_tasks(self):
        repository = ManagedRepository.objects.create(
            slug="shine-app",
            display_name="Shine App",
            remote_url="https://example.com/shine-app.git",
            default_branch="main",
            is_active=True,
            auth_mode="local",
        )
        generate_request = self._request(
            "/xyn/api/application-plans",
            method="post",
            data=json.dumps(
                {
                    "workspace_id": str(self.workspace.id),
                    "objective": "Build an AI real estate deal finder",
                    "source_conversation_id": "thread-1",
                    "target_repository_slug": "shine-app",
                }
            ),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            generate_response = application_plans_collection(generate_request)
        self.assertEqual(generate_response.status_code, 201)
        generated = json.loads(generate_response.content)
        self.assertEqual(generated["target_repository_slug"], "shine-app")

        plan = ApplicationPlan.objects.get(id=generated["id"])
        self.assertEqual(plan.target_repository_id, repository.id)
        apply_request = self._request(f"/xyn/api/application-plans/{plan.id}/apply", method="post", data=json.dumps({}))
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            apply_response = application_plan_apply(apply_request, str(plan.id))
        self.assertEqual(apply_response.status_code, 200)
        application = Application.objects.get(id=json.loads(apply_response.content)["application"]["id"])
        self.assertEqual(application.target_repository_id, repository.id)
        self.assertTrue(DevTask.objects.filter(goal__application=application, target_repo="shine-app", target_branch="main").exists())
        task = DevTask.objects.filter(goal__application=application, target_repo="shine-app", target_branch="main").order_by("created_at").first()
        self.assertIsNotNone(task)
        self.assertEqual(((task.execution_brief or {}).get("target") or {}).get("repository_slug"), "shine-app")
        self.assertEqual(((task.execution_brief or {}).get("target") or {}).get("branch"), "main")

    def test_apply_application_plan_without_target_repository_leaves_generated_tasks_unresolved(self):
        objective = (
            "Build a simple internal web app called Team Lunch Poll. "
            "Core entities: 1. Poll - title - poll_date - status 2. Lunch Option - poll - name 3. Vote - poll - lunch option - voter_name."
        )
        plan, _definition, _generated, _created = create_or_get_application_plan(
            workspace=self.workspace,
            objective=objective,
            requested_by=self.identity,
            application_name="Team Lunch Poll",
        )

        application, created = apply_application_plan(application_plan=plan, user=self.user)

        self.assertTrue(created)
        task = DevTask.objects.filter(goal__application=application).order_by("created_at").first()
        self.assertIsNotNone(task)
        self.assertEqual(task.target_repo, "")
        self.assertEqual(((task.execution_brief or {}).get("target") or {}).get("repository_slug"), None)
        self.assertEqual(((task.execution_brief or {}).get("target") or {}).get("source_kind"), "unresolved")

    def test_application_detail_groups_goals_and_reuses_portfolio_state(self):
        plan = ApplicationPlan.objects.create(
            workspace=self.workspace,
            name="Deal Finder",
            summary="Reviewable plan",
            source_factory_key="generic_application_mvp",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            status="review",
            request_objective="Build an AI real estate deal finder",
            plan_fingerprint=f"plan-{uuid.uuid4().hex}",
            plan_json={},
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Deal Finder",
            summary="Deal finder app",
            source_factory_key="generic_application_mvp",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=plan.plan_fingerprint,
            request_objective=plan.request_objective,
        )
        goal = Goal.objects.create(
            workspace=self.workspace,
            application=application,
            title="Listing and Property Foundation",
            description="Initial MVP slice",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="high",
            planning_status="decomposed",
        )
        CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Listing Data Ingestion",
            owner=self.identity,
            priority="high",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        request = self._request(f"/xyn/api/applications/{application.id}")
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = application_detail(request, str(application.id))
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["id"], str(application.id))
        self.assertEqual(len(payload["goals"]), 1)
        self.assertEqual(payload["goals"][0]["application_id"], str(application.id))
        self.assertIn("portfolio_state", payload)
        self.assertEqual(len(payload["portfolio_state"]["goals"]), 1)

    def test_application_detail_patch_updates_application_status(self):
        application = Application.objects.create(
            workspace=self.workspace,
            name="Deal Finder",
            summary="Deal finder app",
            source_factory_key="generic_application_mvp",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Build an AI real estate deal finder",
        )
        request = self._request(
            f"/xyn/api/applications/{application.id}",
            method="patch",
            data=json.dumps({"status": "archived"}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = application_detail(request, str(application.id))
        payload = json.loads(response.content)
        application.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(application.status, "archived")
        self.assertEqual(payload["status"], "archived")

    def test_application_detail_includes_artifact_memberships(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Deal Finder API",
            slug=f"deal-finder-api-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Deal Finder",
            summary="Deal finder app",
            source_factory_key="generic_application_mvp",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Build an AI real estate deal finder",
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=artifact,
            role="primary_api",
            responsibility_summary="Primary domain API",
        )
        request = self._request(f"/xyn/api/applications/{application.id}")
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = application_detail(request, str(application.id))
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["artifact_member_count"], 1)
        self.assertEqual(len(payload.get("artifact_memberships") or []), 1)
        self.assertEqual(payload["artifact_memberships"][0]["role"], "primary_api")
        self.assertEqual(payload["artifact_memberships"][0]["artifact"]["id"], str(artifact.id))

    def test_application_artifact_memberships_collection_create_and_update(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-ui-{uuid.uuid4().hex[:6]}", name="Generated UI")
        artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Deal Finder UI",
            slug=f"deal-finder-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Deal Finder",
            summary="Deal finder app",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Build an AI real estate deal finder",
        )

        create_request = self._request(
            f"/xyn/api/applications/{application.id}/artifacts",
            method="post",
            data=json.dumps(
                {
                    "artifact_id": str(artifact.id),
                    "role": "primary_ui",
                    "responsibility_summary": "Shell-hosted workflow UI",
                }
            ),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            create_response = application_artifact_memberships_collection(create_request, str(application.id))
        create_payload = json.loads(create_response.content)
        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(create_payload["membership"]["role"], "primary_ui")
        membership_id = create_payload["membership"]["id"]

        list_request = self._request(f"/xyn/api/applications/{application.id}/artifacts")
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            list_response = application_artifact_memberships_collection(list_request, str(application.id))
        list_payload = json.loads(list_response.content)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_payload["memberships"]), 1)

        patch_request = self._request(
            f"/xyn/api/applications/{application.id}/artifacts/{membership_id}",
            method="patch",
            data=json.dumps({"role": "supporting"}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            patch_response = application_artifact_membership_detail(patch_request, str(application.id), membership_id)
        patch_payload = json.loads(patch_response.content)
        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(patch_payload["role"], "supporting")

    def test_solution_change_session_create_and_impacted_artifacts(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Deal Finder UI",
            slug=f"df-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        api_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Deal Finder API",
            slug=f"df-api-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Deal Finder",
            summary="Deal finder app",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Build an AI real estate deal finder",
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=ui_artifact,
            role="primary_ui",
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=api_artifact,
            role="primary_api",
        )
        create_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions",
            method="post",
            data=json.dumps({"title": "Campaign UX update", "request_text": "Update UI and API for campaign flow"}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = application_solution_change_sessions_collection(create_request, str(application.id))
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(payload["created"])
        self.assertEqual(payload["session"]["title"], "Campaign UX update")
        self.assertTrue(payload["session"]["selected_artifact_ids"])
        impacted = ((payload["session"].get("analysis") or {}).get("impacted_artifacts") or [])
        self.assertGreaterEqual(len(impacted), 1)
        planning = payload["session"].get("planning") or {}
        turns = planning.get("turns") or []
        checkpoints = planning.get("checkpoints") or []
        self.assertGreaterEqual(len(turns), 2)
        self.assertTrue(any(str(turn.get("actor") or "") == "user" and str(turn.get("kind") or "") == "request" for turn in turns))
        self.assertTrue(any(str(turn.get("actor") or "") == "planner" for turn in turns))
        self.assertEqual(len(checkpoints), 0)
        self.assertIsNone(planning.get("latest_draft_plan"))

    def test_solution_change_session_create_without_memberships_seeds_initial_draft_plan(self):
        application = Application.objects.create(
            workspace=self.workspace,
            name="Personal Knowledgebase",
            summary="Knowledgebase app",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Create a personal knowledgebase application.",
        )
        create_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions",
            method="post",
            data=json.dumps(
                {
                    "title": "Initial plan",
                    "request_text": "Create a personal knowledgebase application that tracks notes and searchable information.",
                }
            ),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = application_solution_change_sessions_collection(create_request, str(application.id))
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 201)
        planning = ((payload.get("session") or {}).get("planning") or {})
        latest_draft = planning.get("latest_draft_plan") or {}
        self.assertEqual(str(latest_draft.get("kind") or ""), "draft_plan")
        self.assertTrue((latest_draft.get("payload") or {}).get("selected_artifact_ids"))
        self.assertIsNone(planning.get("pending_question"))
        self.assertIsNone(planning.get("pending_option_set"))
        pending_checkpoints = planning.get("pending_checkpoints") or []
        self.assertEqual(len(pending_checkpoints), 1)
        self.assertEqual(str((pending_checkpoints[0] or {}).get("status") or ""), "pending")

    def test_solution_change_session_create_without_memberships_asks_plain_language_clarification_when_ambiguous(self):
        application = Application.objects.create(
            workspace=self.workspace,
            name="New App",
            summary="New app",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Build app",
        )
        create_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions",
            method="post",
            data=json.dumps({"title": "Initial plan", "request_text": "knowledgebase app"}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = application_solution_change_sessions_collection(create_request, str(application.id))
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 201)
        planning = ((payload.get("session") or {}).get("planning") or {})
        self.assertIsNone(planning.get("latest_draft_plan"))
        self.assertIsNone(planning.get("pending_option_set"))
        pending_question = planning.get("pending_question") or {}
        question_text = str(((pending_question.get("payload") or {}).get("question")) or "")
        self.assertTrue(question_text)
        lowered = question_text.lower()
        self.assertNotIn("membership", lowered)
        self.assertNotIn("selectable artifacts", lowered)
        self.assertNotIn("regenerate options", lowered)

    def test_solution_change_session_reply_option_and_checkpoint_decision_are_persisted(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Deal Finder UI",
            slug=f"df-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Deal Finder",
            summary="Deal finder app",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Build an AI real estate deal finder",
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=ui_artifact,
            role="primary_ui",
        )
        create_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions",
            method="post",
            data=json.dumps(
                {
                    "title": "Campaign UX update",
                    "request_text": "Update campaign UX and signal review flow end to end.",
                }
            ),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            create_response = application_solution_change_sessions_collection(create_request, str(application.id))
            self.assertEqual(create_response.status_code, 201)
            create_payload = json.loads(create_response.content)
            session_id = str((create_payload.get("session") or {}).get("id") or "")
            session = SolutionChangeSession.objects.get(id=session_id)
            option_turn = (
                SolutionPlanningTurn.objects.filter(session=session, actor="planner", kind="option_set")
                .order_by("-sequence")
                .first()
            )
            self.assertIsNotNone(option_turn)
            option_payload = option_turn.payload_json if isinstance(option_turn.payload_json, dict) else {}
            option_rows = option_payload.get("options") if isinstance(option_payload.get("options"), list) else []
            self.assertTrue(option_rows)
            option_id = str((option_rows[0] if isinstance(option_rows[0], dict) else {}).get("id") or "")

            reply_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/reply",
                method="post",
                data=json.dumps({"reply_text": "Target the UI and API first."}),
            )
            reply_response = application_solution_change_session_reply(reply_request, str(application.id), str(session.id))
            self.assertEqual(reply_response.status_code, 200)

            select_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/select-option",
                method="post",
                data=json.dumps({"source_turn_id": str(option_turn.id), "option_id": option_id}),
            )
            select_response = application_solution_change_session_select_option(select_request, str(application.id), str(session.id))
            self.assertEqual(select_response.status_code, 200)
            select_payload = json.loads(select_response.content)
            planning_after_select = ((select_payload.get("session") or {}).get("planning") or {})
            self.assertIsNotNone(planning_after_select.get("latest_draft_plan"))
            self.assertFalse(planning_after_select.get("pending_option_set"))
            self.assertFalse(planning_after_select.get("pending_question"))

            checkpoint = SolutionPlanningCheckpoint.objects.filter(session=session).first()
            self.assertIsNotNone(checkpoint)
            checkpoint_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/checkpoints/{checkpoint.id}/decision",
                method="post",
                data=json.dumps({"decision": "approved", "notes": "Scope looks correct."}),
            )
            checkpoint_response = application_solution_change_session_checkpoint_decision(
                checkpoint_request,
                str(application.id),
                str(session.id),
                str(checkpoint.id),
            )
            self.assertEqual(checkpoint_response.status_code, 200)

        session.refresh_from_db()
        checkpoint = SolutionPlanningCheckpoint.objects.get(id=checkpoint.id)
        self.assertEqual(checkpoint.status, "approved")
        turns = list(SolutionPlanningTurn.objects.filter(session=session).order_by("sequence"))
        kinds = [turn.kind for turn in turns]
        self.assertIn("response", kinds)
        self.assertIn("approval", kinds)

    def test_solution_change_session_refinement_reply_generates_revised_draft_and_resets_checkpoint(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Deal Finder UI",
            slug=f"df-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Deal Finder",
            summary="Deal finder app",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Build an AI real estate deal finder",
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=ui_artifact,
            role="primary_ui",
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            create_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions",
                method="post",
                data=json.dumps(
                    {
                        "title": "Campaign UX update",
                        "request_text": "Update campaign UX and signal review flow end to end.",
                    }
                ),
            )
            create_response = application_solution_change_sessions_collection(create_request, str(application.id))
            self.assertEqual(create_response.status_code, 201)
            create_payload = json.loads(create_response.content)
            session_id = str((create_payload.get("session") or {}).get("id") or "")
            session = SolutionChangeSession.objects.get(id=session_id)

            option_turn = (
                SolutionPlanningTurn.objects.filter(session=session, actor="planner", kind="option_set")
                .order_by("-sequence")
                .first()
            )
            self.assertIsNotNone(option_turn)
            option_payload = option_turn.payload_json if isinstance(option_turn.payload_json, dict) else {}
            option_rows = option_payload.get("options") if isinstance(option_payload.get("options"), list) else []
            self.assertTrue(option_rows)
            option_id = str((option_rows[0] if isinstance(option_rows[0], dict) else {}).get("id") or "")

            select_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/select-option",
                method="post",
                data=json.dumps({"source_turn_id": str(option_turn.id), "option_id": option_id}),
            )
            select_response = application_solution_change_session_select_option(select_request, str(application.id), str(session.id))
            self.assertEqual(select_response.status_code, 200)

            checkpoint = SolutionPlanningCheckpoint.objects.filter(session=session).first()
            self.assertIsNotNone(checkpoint)
            checkpoint_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/checkpoints/{checkpoint.id}/decision",
                method="post",
                data=json.dumps({"decision": "approved", "notes": "Looks good."}),
            )
            checkpoint_response = application_solution_change_session_checkpoint_decision(
                checkpoint_request,
                str(application.id),
                str(session.id),
                str(checkpoint.id),
            )
            self.assertEqual(checkpoint_response.status_code, 200)

            reply_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/reply",
                method="post",
                data=json.dumps({"reply_text": "Focus first on campaign creation and map validation."}),
            )
            reply_response = application_solution_change_session_reply(reply_request, str(application.id), str(session.id))
        self.assertEqual(reply_response.status_code, 200)

        session.refresh_from_db()
        checkpoint.refresh_from_db()
        self.assertTrue(isinstance(session.plan_json, dict) and session.plan_json)
        self.assertEqual(checkpoint.status, "pending")

        turns = list(SolutionPlanningTurn.objects.filter(session=session).order_by("sequence"))
        self.assertGreaterEqual(len(turns), 5)
        self.assertEqual(turns[-3].kind, "response")
        self.assertEqual(turns[-2].kind, "draft_plan")
        self.assertIn("Revised draft plan", str((turns[-2].payload_json or {}).get("summary") or ""))
        self.assertEqual(turns[-1].kind, "checkpoint")

    def test_solution_change_session_update_and_plan_generation(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Deal Finder UI",
            slug=f"df-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Deal Finder",
            summary="Deal finder app",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Build an AI real estate deal finder",
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=ui_artifact,
            role="primary_ui",
        )
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Campaign UX update",
            request_text="Update campaign UX",
            created_by=self.identity,
            analysis_json={"impacted_artifacts": [], "suggested_artifact_ids": [str(ui_artifact.id)]},
            selected_artifact_ids_json=[str(ui_artifact.id)],
        )
        patch_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}",
            method="patch",
            data=json.dumps({"selected_artifact_ids": [str(ui_artifact.id)]}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            patch_response = application_solution_change_session_detail(patch_request, str(application.id), str(session.id))
        patch_payload = json.loads(patch_response.content)
        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(patch_payload["selected_artifact_ids"], [str(ui_artifact.id)])

        plan_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/plan",
            method="post",
            data=json.dumps({}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            plan_response = application_solution_change_session_plan(plan_request, str(application.id), str(session.id))
        plan_payload = json.loads(plan_response.content)
        self.assertEqual(plan_response.status_code, 200)
        self.assertTrue(plan_payload["planned"])
        self.assertIn("per_artifact_work", plan_payload["session"]["plan"])
        planning = plan_payload["session"].get("planning") or {}
        latest_draft = planning.get("latest_draft_plan") or {}
        self.assertEqual(str(latest_draft.get("kind") or ""), "draft_plan")

    def test_solution_change_session_regenerate_options_adds_option_set_turn(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Deal Finder UI",
            slug=f"df-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Deal Finder",
            summary="Deal finder app",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Build an AI real estate deal finder",
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=ui_artifact,
            role="primary_ui",
        )
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Campaign UX update",
            request_text="Update campaign UX",
            created_by=self.identity,
            selected_artifact_ids_json=[str(ui_artifact.id)],
        )
        regen_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/regenerate-options",
            method="post",
            data=json.dumps({}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            regen_response = application_solution_change_session_regenerate_options(
                regen_request,
                str(application.id),
                str(session.id),
            )
        payload = json.loads(regen_response.content)
        self.assertEqual(regen_response.status_code, 200)
        self.assertTrue(payload.get("regenerated"))
        turns = ((payload.get("session") or {}).get("planning") or {}).get("turns") or []
        self.assertTrue(any(str(item.get("kind") or "") == "option_set" for item in turns if isinstance(item, dict)))

    def test_solution_change_session_stage_preview_and_validate_flow(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Deal Finder UI",
            slug=f"app.deal-finder-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Deal Finder",
            summary="Deal finder app",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Build an AI real estate deal finder",
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=ui_artifact,
            role="primary_ui",
        )
        WorkspaceAppInstance.objects.create(
            workspace=self.workspace,
            artifact=ui_artifact,
            app_slug=ui_artifact.slug.replace("app.", "", 1),
            customer_name="Preview",
            fqdn=f"preview-{uuid.uuid4().hex[:6]}.internal",
            deployment_target="local",
            status="active",
            dns_config_json={
                "runtime_target": {
                    "runtime_owner": "sibling",
                    "runtime_base_url": "http://deal-finder-runtime:8080",
                    "public_app_url": "http://localhost:32822",
                    "compose_project": "xyn-preview",
                    "app_slug": ui_artifact.slug.replace("app.", "", 1),
                    "source_build_job_id": "job-123",
                }
            },
        )
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Campaign UX update",
            request_text="Update campaign UX",
            created_by=self.identity,
            analysis_json={"impacted_artifacts": [], "suggested_artifact_ids": [str(ui_artifact.id)]},
            selected_artifact_ids_json=[str(ui_artifact.id)],
            status="planned",
            plan_json={
                "per_artifact_work": [
                    {
                        "artifact_id": str(ui_artifact.id),
                        "planned_work": ["Update shell views and interaction flows"],
                    }
                ]
            },
        )
        SolutionPlanningTurn.objects.create(
            workspace=self.workspace,
            session=session,
            actor="planner",
            kind="draft_plan",
            sequence=1,
            payload_json={
                "summary": "Generated structured cross-artifact draft plan.",
                "selected_artifact_ids": [str(ui_artifact.id)],
            },
        )
        SolutionPlanningCheckpoint.objects.create(
            workspace=self.workspace,
            session=session,
            checkpoint_key="plan_scope_confirmed",
            label="Approve planning scope before stage apply",
            status="approved",
            required_before="stage",
            payload_json={},
            decided_by=self.identity,
        )

        stage_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/stage-apply",
            method="post",
            data=json.dumps({}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            stage_response = application_solution_change_session_stage_apply(stage_request, str(application.id), str(session.id))
        stage_payload = json.loads(stage_response.content)
        self.assertEqual(stage_response.status_code, 200)
        self.assertTrue(stage_payload["staged"])
        self.assertEqual(stage_payload["session"]["execution_status"], "staged")
        self.assertEqual(len((stage_payload["session"].get("staged_changes") or {}).get("artifact_states") or []), 1)

        preview_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/prepare-preview",
            method="post",
            data=json.dumps({}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api._runtime_target_request", return_value=mock.Mock(status_code=200)
        ):
            preview_response = application_solution_change_session_prepare_preview(
                preview_request, str(application.id), str(session.id)
            )
        preview_payload = json.loads(preview_response.content)
        self.assertEqual(preview_response.status_code, 200)
        self.assertTrue(preview_payload["prepared"])
        self.assertEqual(preview_payload["session"]["execution_status"], "preview_ready")
        self.assertEqual((preview_payload["session"].get("preview") or {}).get("status"), "ready")
        self.assertTrue((preview_payload["session"].get("preview") or {}).get("preview_urls"))
        preview = preview_payload["session"].get("preview") or {}
        self.assertFalse(bool(preview.get("newly_built_for_session")))
        self.assertTrue(bool(preview.get("reused_existing_runtime")))
        self.assertEqual(((preview.get("session_build") or {}).get("status")), "reused")

        validate_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/validate",
            method="post",
            data=json.dumps({}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            validate_response = application_solution_change_session_validate(
                validate_request, str(application.id), str(session.id)
            )
        validate_payload = json.loads(validate_response.content)
        self.assertEqual(validate_response.status_code, 200)
        self.assertTrue(validate_payload["validated"])
        self.assertEqual(validate_payload["session"]["execution_status"], "ready_for_promotion")
        checks = ((validate_payload["session"].get("validation") or {}).get("checks") or [])
        self.assertTrue(checks)
        self.assertTrue(all(item.get("status") == "passed" for item in checks if isinstance(item, dict)))

    def test_solution_change_session_stage_apply_requires_approved_checkpoint(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Deal Finder UI",
            slug=f"app.deal-finder-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Deal Finder",
            summary="Deal finder app",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Build an AI real estate deal finder",
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=ui_artifact,
            role="primary_ui",
        )
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Campaign UX update",
            request_text="Update campaign UX",
            created_by=self.identity,
            selected_artifact_ids_json=[str(ui_artifact.id)],
            status="planned",
            plan_json={"selected_artifact_ids": [str(ui_artifact.id)], "per_artifact_work": [{"artifact_id": str(ui_artifact.id)}]},
        )
        SolutionPlanningTurn.objects.create(
            workspace=self.workspace,
            session=session,
            actor="planner",
            kind="draft_plan",
            sequence=1,
            payload_json={"summary": "Draft plan"},
        )
        pending_checkpoint = SolutionPlanningCheckpoint.objects.create(
            workspace=self.workspace,
            session=session,
            checkpoint_key="plan_scope_confirmed",
            label="Approve planning scope before stage apply",
            status="pending",
            required_before="stage",
            payload_json={},
        )
        stage_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/stage-apply",
            method="post",
            data=json.dumps({}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            blocked_response = application_solution_change_session_stage_apply(stage_request, str(application.id), str(session.id))
        self.assertEqual(blocked_response.status_code, 409)
        self.assertIn("checkpoint", str(json.loads(blocked_response.content).get("error") or "").lower())

        pending_checkpoint.status = "approved"
        pending_checkpoint.decided_by = self.identity
        pending_checkpoint.save(update_fields=["status", "decided_by", "updated_at"])
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            approved_response = application_solution_change_session_stage_apply(stage_request, str(application.id), str(session.id))
        self.assertEqual(approved_response.status_code, 200)
        self.assertTrue(json.loads(approved_response.content).get("staged"))

    def test_solution_change_session_prepare_preview_fails_without_runtime_evidence(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Deal Finder UI",
            slug=f"app.deal-finder-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Deal Finder",
            summary="Deal finder app",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Build an AI real estate deal finder",
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=ui_artifact,
            role="primary_ui",
        )
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Campaign UX update",
            request_text="Update campaign UX",
            created_by=self.identity,
            selected_artifact_ids_json=[str(ui_artifact.id)],
            status="planned",
            plan_json={"per_artifact_work": [{"artifact_id": str(ui_artifact.id), "planned_work": ["Update shell UI"]}]},
            staged_changes_json={
                "artifact_states": [
                    {
                        "artifact_id": str(ui_artifact.id),
                        "artifact_title": ui_artifact.title,
                        "role": "primary_ui",
                        "apply_state": "proposed",
                    }
                ]
            },
            execution_status="staged",
        )
        preview_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/prepare-preview",
            method="post",
            data=json.dumps({}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            preview_response = application_solution_change_session_prepare_preview(
                preview_request, str(application.id), str(session.id)
            )
        preview_payload = json.loads(preview_response.content)
        self.assertEqual(preview_response.status_code, 409)
        self.assertFalse(preview_payload["prepared"])
        self.assertEqual(preview_payload["session"]["execution_status"], "failed")
        self.assertEqual((preview_payload["session"].get("preview") or {}).get("status"), "failed")

    def test_solution_change_session_prepare_preview_marks_session_built_when_sibling_launch_succeeds(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Deal Finder UI",
            slug=f"app.deal-finder-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Deal Finder",
            summary="Deal finder app",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Build an AI real estate deal finder",
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=ui_artifact,
            role="primary_ui",
        )
        WorkspaceAppInstance.objects.create(
            workspace=self.workspace,
            artifact=ui_artifact,
            app_slug=ui_artifact.slug.replace("app.", "", 1),
            customer_name="Preview",
            fqdn=f"preview-{uuid.uuid4().hex[:6]}.internal",
            deployment_target="local",
            status="active",
            dns_config_json={
                "runtime_target": {
                    "runtime_owner": "sibling",
                    "runtime_base_url": "http://deal-finder-runtime:8080",
                    "public_app_url": "http://localhost:32822",
                    "compose_project": "xyn-preview",
                    "app_slug": ui_artifact.slug.replace("app.", "", 1),
                    "source_build_job_id": "job-123",
                    "app_container_name": "xyn-preview-deal-finder-runtime",
                }
            },
        )
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Campaign UX update",
            request_text="Update campaign UX",
            created_by=self.identity,
            selected_artifact_ids_json=[str(ui_artifact.id)],
            status="planned",
            plan_json={"per_artifact_work": [{"artifact_id": str(ui_artifact.id), "planned_work": ["Update shell UI"]}]},
            staged_changes_json={
                "artifact_states": [
                    {
                        "artifact_id": str(ui_artifact.id),
                        "artifact_title": ui_artifact.title,
                        "role": "primary_ui",
                        "apply_state": "proposed",
                    }
                ]
            },
            execution_status="staged",
        )
        preview_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/prepare-preview",
            method="post",
            data=json.dumps({}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api._runtime_target_request", return_value=mock.Mock(status_code=200)
        ), mock.patch(
            "xyn_orchestrator.xyn_api.subprocess.run",
            side_effect=[
                mock.Mock(returncode=0, stdout="24.0.0", stderr=""),
                mock.Mock(returncode=0, stdout="restarted", stderr=""),
            ],
        ):
            preview_response = application_solution_change_session_prepare_preview(
                preview_request, str(application.id), str(session.id)
            )
        preview_payload = json.loads(preview_response.content)
        self.assertEqual(preview_response.status_code, 200)
        self.assertTrue(preview_payload["prepared"])
        preview = preview_payload["session"].get("preview") or {}
        self.assertEqual(preview.get("status"), "ready")
        self.assertTrue(preview.get("newly_built_for_session"))
        self.assertFalse(preview.get("reused_existing_runtime"))
        session_build = preview.get("session_build") if isinstance(preview.get("session_build"), dict) else {}
        self.assertEqual(session_build.get("status"), "succeeded")
        self.assertTrue(session_build.get("launched_containers"))

    def test_solution_change_session_prepare_preview_fails_when_session_launch_fails(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Deal Finder UI",
            slug=f"app.deal-finder-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Deal Finder",
            summary="Deal finder app",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Build an AI real estate deal finder",
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=ui_artifact,
            role="primary_ui",
        )
        WorkspaceAppInstance.objects.create(
            workspace=self.workspace,
            artifact=ui_artifact,
            app_slug=ui_artifact.slug.replace("app.", "", 1),
            customer_name="Preview",
            fqdn=f"preview-{uuid.uuid4().hex[:6]}.internal",
            deployment_target="local",
            status="active",
            dns_config_json={
                "runtime_target": {
                    "runtime_owner": "sibling",
                    "runtime_base_url": "http://deal-finder-runtime:8080",
                    "public_app_url": "http://localhost:32822",
                    "compose_project": "xyn-preview",
                    "app_slug": ui_artifact.slug.replace("app.", "", 1),
                    "source_build_job_id": "job-123",
                    "app_container_name": "xyn-preview-deal-finder-runtime",
                }
            },
        )
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Campaign UX update",
            request_text="Update campaign UX",
            created_by=self.identity,
            selected_artifact_ids_json=[str(ui_artifact.id)],
            status="planned",
            plan_json={"per_artifact_work": [{"artifact_id": str(ui_artifact.id), "planned_work": ["Update shell UI"]}]},
            staged_changes_json={
                "artifact_states": [
                    {
                        "artifact_id": str(ui_artifact.id),
                        "artifact_title": ui_artifact.title,
                        "role": "primary_ui",
                        "apply_state": "proposed",
                    }
                ]
            },
            execution_status="staged",
        )
        preview_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/prepare-preview",
            method="post",
            data=json.dumps({}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api._runtime_target_request", return_value=mock.Mock(status_code=200)
        ), mock.patch(
            "xyn_orchestrator.xyn_api.subprocess.run",
            side_effect=[
                mock.Mock(returncode=0, stdout="24.0.0", stderr=""),
                mock.Mock(returncode=1, stdout="", stderr="restart failed"),
            ],
        ):
            preview_response = application_solution_change_session_prepare_preview(
                preview_request, str(application.id), str(session.id)
            )
        preview_payload = json.loads(preview_response.content)
        self.assertEqual(preview_response.status_code, 409)
        self.assertFalse(preview_payload["prepared"])
        preview = preview_payload["session"].get("preview") or {}
        self.assertEqual(preview.get("status"), "failed")
        self.assertFalse(bool(preview.get("newly_built_for_session")))
        self.assertEqual((preview.get("error") or {}).get("reason"), "docker_restart_failed")

    def test_application_plan_detail_patch_updates_plan_status(self):
        plan = ApplicationPlan.objects.create(
            workspace=self.workspace,
            name="Deal Finder",
            summary="Reviewable plan",
            source_factory_key="generic_application_mvp",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            status="review",
            request_objective="Build an AI real estate deal finder",
            plan_fingerprint=f"plan-{uuid.uuid4().hex}",
            plan_json={"application_name": "Deal Finder"},
        )
        request = self._request(
            f"/xyn/api/application-plans/{plan.id}",
            method="patch",
            data=json.dumps({"status": "canceled"}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = application_plan_detail(request, str(plan.id))
        payload = json.loads(response.content)
        plan.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(plan.status, "canceled")
        self.assertEqual(payload["status"], "canceled")

    def test_create_or_get_application_plan_creates_fresh_plan_after_archived_application(self):
        objective = "Build Team Lunch Poll"
        plan, _definition, _generated, _created = create_or_get_application_plan(
            workspace=self.workspace,
            objective=objective,
            requested_by=self.identity,
            source_conversation_id="thread-1",
        )
        application, created = apply_application_plan(application_plan=plan, user=self.user)
        self.assertTrue(created)
        application.status = "archived"
        application.save(update_fields=["status", "updated_at"])

        next_plan, _definition2, _generated2, created_again = create_or_get_application_plan(
            workspace=self.workspace,
            objective=objective,
            requested_by=self.identity,
            source_conversation_id="thread-2",
        )

        plan.refresh_from_db()
        self.assertTrue(created_again)
        self.assertNotEqual(next_plan.id, plan.id)
        self.assertEqual(next_plan.status, "review")
        self.assertIsNone(next_plan.application_id)
        self.assertNotEqual(plan.plan_fingerprint, next_plan.plan_fingerprint)
        self.assertEqual(ApplicationPlan.objects.filter(workspace=self.workspace).count(), 2)

    def test_apply_application_plan_creates_fresh_application_when_archived_one_matches_fingerprint(self):
        objective = "Build Team Lunch Poll"
        plan, _definition, _generated, _created = create_or_get_application_plan(
            workspace=self.workspace,
            objective=objective,
            requested_by=self.identity,
            source_conversation_id="thread-1",
        )
        application, created = apply_application_plan(application_plan=plan, user=self.user)
        self.assertTrue(created)
        original_application_id = application.id
        original_plan_fingerprint = application.plan_fingerprint
        application.status = "archived"
        application.save(update_fields=["status", "updated_at"])
        plan.application = None
        plan.status = "review"
        plan.save(update_fields=["application", "status", "updated_at"])

        next_application, created_again = apply_application_plan(application_plan=plan, user=self.user)

        application.refresh_from_db()
        plan.refresh_from_db()
        self.assertTrue(created_again)
        self.assertNotEqual(next_application.id, original_application_id)
        self.assertEqual(next_application.status, "active")
        self.assertEqual(plan.application_id, next_application.id)
        self.assertNotEqual(application.plan_fingerprint, original_plan_fingerprint)

    def test_composer_state_defaults_to_factory_discovery(self):
        request = self._request("/xyn/api/composer/state", data={"workspace_id": str(self.workspace.id)})
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = composer_state(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["stage"], "factory_discovery")
        self.assertGreaterEqual(len(payload["factory_catalog"]), 1)
        self.assertIsNone(payload["context"]["application_plan_id"])

    def test_composer_state_returns_plan_review_for_application_plan_context(self):
        plan = ApplicationPlan.objects.create(
            workspace=self.workspace,
            name="Deal Finder",
            summary="Reviewable plan",
            source_factory_key="generic_application_mvp",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            status="review",
            request_objective="Build an AI real estate deal finder",
            plan_fingerprint=f"plan-{uuid.uuid4().hex}",
            plan_json={"application_name": "Deal Finder"},
        )
        request = self._request(
            "/xyn/api/composer/state",
            data={"workspace_id": str(self.workspace.id), "application_plan_id": str(plan.id)},
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = composer_state(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["stage"], "plan_review")
        self.assertEqual((payload["application_plan"] or {}).get("id"), str(plan.id))

    def test_composer_state_returns_application_goal_and_thread_focus(self):
        application = Application.objects.create(
            workspace=self.workspace,
            name="Deal Finder",
            summary="Deal finder app",
            source_factory_key="generic_application_mvp",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Build an AI real estate deal finder",
        )
        goal = Goal.objects.create(
            workspace=self.workspace,
            application=application,
            title="Listing and Property Foundation",
            description="Initial MVP slice",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="high",
            planning_status="decomposed",
        )
        thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Listing Data Ingestion",
            owner=self.identity,
            priority="high",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )

        application_request = self._request(
            "/xyn/api/composer/state",
            data={"workspace_id": str(self.workspace.id), "application_id": str(application.id)},
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            application_response = composer_state(application_request)
        application_payload = json.loads(application_response.content)
        self.assertEqual(application_response.status_code, 200)
        self.assertEqual(application_payload["stage"], "application_overview")
        self.assertEqual((application_payload["application"] or {}).get("id"), str(application.id))

        goal_request = self._request(
            "/xyn/api/composer/state",
            data={"workspace_id": str(self.workspace.id), "goal_id": str(goal.id)},
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            goal_response = composer_state(goal_request)
        goal_payload = json.loads(goal_response.content)
        self.assertEqual(goal_response.status_code, 200)
        self.assertEqual(goal_payload["stage"], "goal_focus")
        self.assertEqual((goal_payload["goal"] or {}).get("id"), str(goal.id))

        thread_request = self._request(
            "/xyn/api/composer/state",
            data={"workspace_id": str(self.workspace.id), "thread_id": str(thread.id)},
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            thread_response = composer_state(thread_request)
        thread_payload = json.loads(thread_response.content)
        self.assertEqual(thread_response.status_code, 200)
        self.assertEqual(thread_payload["stage"], "thread_focus")
        self.assertEqual((thread_payload["thread"] or {}).get("id"), str(thread.id))

    def test_composer_state_includes_solution_execution_actions(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Deal Finder UI",
            slug=f"df-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Deal Finder",
            summary="Deal finder app",
            source_factory_key="generic_application_mvp",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Build an AI real estate deal finder",
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=ui_artifact,
            role="primary_ui",
        )
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Execution Session",
            request_text="Coordinate UI/API updates",
            created_by=self.identity,
            status="planned",
            plan_json={"per_artifact_work": [{"artifact_id": str(ui_artifact.id), "planned_work": ["Update shell UI"]}]},
            execution_status="staged",
        )
        request = self._request(
            "/xyn/api/composer/state",
            data={
                "workspace_id": str(self.workspace.id),
                "application_id": str(application.id),
                "solution_change_session_id": str(session.id),
            },
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = composer_state(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        actions = payload.get("available_actions") or []
        action_types = {str(item.get("type") or "") for item in actions if isinstance(item, dict)}
        self.assertIn("stage_solution_change", action_types)
        self.assertIn("prepare_solution_preview", action_types)
        self.assertIn("validate_solution_change", action_types)
        session_payload = payload.get("solution_change_session") or {}
        planning_payload = session_payload.get("planning") if isinstance(session_payload, dict) else {}
        self.assertIsInstance(planning_payload, dict)
        self.assertIn("turns", planning_payload)
        self.assertIn("checkpoints", planning_payload)

    def test_composer_state_default_workspace_view_excludes_archived_application_work(self):
        archived_application = Application.objects.create(
            workspace=self.workspace,
            name="Archived effort",
            summary="Historical effort",
            source_factory_key="generic_application_mvp",
            source_conversation_id="thread-archived",
            requested_by=self.identity,
            status="archived",
            plan_fingerprint=f"archived-{uuid.uuid4().hex}",
            request_objective="Historical application effort",
        )
        archived_goal = Goal.objects.create(
            workspace=self.workspace,
            application=archived_application,
            title="Archived goal",
            description="Should not appear in the default composer queue view.",
            source_conversation_id="thread-archived",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
            planning_status="decomposed",
        )
        CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=archived_goal,
            title="Archived thread",
            owner=self.identity,
            priority="normal",
            status="queued",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-archived",
        )

        active_application = Application.objects.create(
            workspace=self.workspace,
            name="Active effort",
            summary="Current effort",
            source_factory_key="generic_application_mvp",
            source_conversation_id="thread-active",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"active-{uuid.uuid4().hex}",
            request_objective="Current application effort",
        )
        active_goal = Goal.objects.create(
            workspace=self.workspace,
            application=active_application,
            title="Active goal",
            description="Should appear in the default composer queue view.",
            source_conversation_id="thread-active",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
            planning_status="decomposed",
        )
        active_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=active_goal,
            title="Active thread",
            owner=self.identity,
            priority="normal",
            status="queued",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-active",
        )

        request = self._request("/xyn/api/composer/state", data={"workspace_id": str(self.workspace.id)})
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = composer_state(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([(goal or {}).get("id") for goal in payload["related_goals"]], [str(active_goal.id)])
        self.assertEqual([(thread or {}).get("id") for thread in payload["related_threads"]], [str(active_thread.id)])

    def test_recommend_next_slice_includes_stable_recommendation_id_for_unchanged_state(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Stable Recommendation",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        persist_goal_plan(goal, decompose_goal(goal), user=self.user)

        recommendation_a = recommend_next_slice(goal)
        recommendation_b = recommend_next_slice(goal)

        self.assertTrue(recommendation_a.recommendation_id)
        self.assertEqual(recommendation_a.recommendation_id, recommendation_b.recommendation_id)
        self.assertFalse(CoordinationEvent.objects.filter(event_type__startswith="approval_").exists())

    def test_recommend_next_slice_changes_recommendation_id_when_state_changes(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Changing Recommendation",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Paused Thread",
            owner=self.identity,
            priority="normal",
            status="paused",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="Queued work",
            description="",
            task_type="codegen",
            status="queued",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=thread,
            work_item_id="queued-work",
        )
        recommendation_a = recommend_next_slice(goal)
        thread.status = "active"
        thread.save(update_fields=["status", "updated_at"])
        recommendation_b = recommend_next_slice(goal)
        self.assertNotEqual(recommendation_a.recommendation_id, recommendation_b.recommendation_id)

    def test_goal_review_rejects_stale_recommendation_id_without_side_effects(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Stale Recommendation",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        persist_goal_plan(goal, decompose_goal(goal), user=self.user)
        recommendation_id = recommend_next_slice(goal).recommendation_id
        task = goal.work_items.order_by("priority", "created_at", "id").first()
        self.assertIsNotNone(task)
        task.status = "completed"
        task.save(update_fields=["status", "updated_at"])

        request = self._request(
            f"/xyn/api/goals/{goal.id}/review",
            method="post",
            data=json.dumps({"review_action": "approve_and_queue", "recommendation_id": recommendation_id}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = goal_review(request, str(goal.id))
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(payload["status"], "stale_recommendation")
        self.assertFalse(CoordinationEvent.objects.filter(event_type__startswith="approval_").exists())

    def test_recommend_next_slice_prefers_first_queue_ready_work_item(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="AI Real Estate Deal Finder",
            description="Build a deal finder using listings and comparables.",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="high",
        )
        persist_goal_plan(goal, decompose_goal(goal), user=self.user)
        recommendation = recommend_next_slice(goal)
        self.assertEqual(recommendation.thread_title, "Core Domain Slice")
        self.assertEqual(len(recommendation.recommended_work_items), 1)
        self.assertIn("Core Domain Slice", recommendation.reasoning_summary)
        self.assertIsNotNone(recommendation.queue_suggestion)
        self.assertEqual(recommendation.queue_suggestion.action_type, "queue_first_slice")
        action_types = [action.type for action in recommendation.actions]
        self.assertEqual(action_types[:2], ["approve_and_queue", "queue_first_slice"])
        self.assertTrue(recommendation.actions[0].queueable)
        self.assertEqual(recommendation.actions[0].target_work_item, str(recommendation.work_item_id))
        self.assertEqual(recommendation.actions[0].target_thread, str(recommendation.thread_id))

    def test_recommend_next_slice_for_paused_thread_is_not_queueable(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Paused Goal",
            description="Resume before queueing.",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="high",
        )
        thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Paused Thread",
            owner=self.identity,
            priority="high",
            status="paused",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="Queued item",
            description="",
            task_type="codegen",
            status="queued",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=thread,
            work_item_id="queued-item",
        )
        recommendation = recommend_next_slice(goal)
        self.assertEqual(recommendation.queue_suggestion.action_type, "resume_thread")
        self.assertEqual([action.type for action in recommendation.actions], ["resume_thread", "review_thread"])
        self.assertFalse(recommendation.actions[0].queueable)

    def test_goal_progress_reports_not_started_when_no_work_exists(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Empty Goal",
            description="No work yet.",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        progress = compute_goal_progress(goal)
        self.assertEqual(progress.goal_progress_status, "not_started")
        self.assertEqual(progress.completed_work_items, 0)
        self.assertEqual(progress.active_work_items, 0)
        self.assertEqual(progress.blocked_work_items, 0)

    def test_goal_progress_reports_in_progress_when_ready_or_running_work_exists(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Active Goal",
            description="Active work.",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="high",
        )
        thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Thread A",
            owner=self.identity,
            priority="high",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="Ready item",
            description="",
            task_type="codegen",
            status="queued",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=thread,
            work_item_id="ready-item",
        )
        progress = compute_goal_progress(goal)
        self.assertEqual(progress.goal_progress_status, "in_progress")
        self.assertEqual(progress.active_work_items, 1)

    def test_goal_progress_reports_completed_when_all_work_is_completed(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Done Goal",
            description="Completed work.",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Thread Done",
            owner=self.identity,
            priority="normal",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        for index in range(2):
            DevTask.objects.create(
                title=f"Completed {index}",
                description="",
                task_type="codegen",
                status="completed",
                priority=index,
                source_entity_type="goal",
                source_entity_id=goal.id,
                source_conversation_id="thread-1",
                intent_type="goal_planning",
                target_repo="xyn-platform",
                target_branch="develop",
                execution_policy={},
                goal=goal,
                coordination_thread=thread,
                work_item_id=f"completed-{index}",
            )
        progress = compute_goal_progress(goal)
        self.assertEqual(progress.goal_progress_status, "completed")
        self.assertEqual(progress.completed_work_items, 2)

    def test_goal_progress_reports_stalled_when_only_blocked_work_remains(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Blocked Goal",
            description="Blocked work.",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Thread Blocked",
            owner=self.identity,
            priority="normal",
            status="paused",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="Blocked item",
            description="",
            task_type="codegen",
            status="queued",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=thread,
            work_item_id="blocked-item",
        )
        progress = compute_goal_progress(goal)
        self.assertEqual(progress.goal_progress_status, "stalled")
        self.assertEqual(progress.blocked_work_items, 1)

    def test_goal_progress_reports_nearing_completion_when_small_remainder_exists(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Nearly Done Goal",
            description="Mostly complete.",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Thread Near",
            owner=self.identity,
            priority="normal",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        for index in range(4):
            DevTask.objects.create(
                title=f"Completed {index}",
                description="",
                task_type="codegen",
                status="completed",
                priority=index,
                source_entity_type="goal",
                source_entity_id=goal.id,
                source_conversation_id="thread-1",
                intent_type="goal_planning",
                target_repo="xyn-platform",
                target_branch="develop",
                execution_policy={},
                goal=goal,
                coordination_thread=thread,
                work_item_id=f"done-{index}",
            )
        DevTask.objects.create(
            title="Small remaining slice",
            description="",
            task_type="codegen",
            status="queued",
            priority=99,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=thread,
            work_item_id="remaining-slice",
        )
        progress = compute_goal_progress(goal)
        self.assertEqual(progress.goal_progress_status, "nearing_completion")
        self.assertEqual(progress.completed_work_items, 4)
        self.assertEqual(progress.active_work_items, 1)

    def test_goal_execution_metrics_calculate_thread_state_and_artifact_counts(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Observed Goal",
            description="Operational metrics",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="high",
        )
        active_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Active Thread",
            owner=self.identity,
            priority="high",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        blocked_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Blocked Thread",
            owner=self.identity,
            priority="normal",
            status="paused",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        finished = DevTask.objects.create(
            title="Finished slice",
            description="",
            task_type="codegen",
            status="completed",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=active_thread,
            work_item_id="finished-slice",
            runtime_run_id=uuid.uuid4(),
        )
        DevTask.objects.create(
            title="Ready slice",
            description="",
            task_type="codegen",
            status="queued",
            priority=0,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=active_thread,
            work_item_id="ready-slice",
        )
        DevTask.objects.create(
            title="Blocked slice",
            description="",
            task_type="codegen",
            status="queued",
            priority=2,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=blocked_thread,
            work_item_id="blocked-slice",
            dependency_work_item_ids=["missing-dependency"],
        )

        def runtime_detail_lookup(task):
            if task.id != finished.id:
                return None
            return {
                "artifacts": [
                    {"id": "artifact-1"},
                    {"id": "artifact-2"},
                ]
            }

        metrics = compute_goal_execution_metrics(goal, runtime_detail_lookup=runtime_detail_lookup)
        self.assertEqual(metrics.active_threads, 1)
        self.assertEqual(metrics.blocked_threads, 1)
        self.assertEqual(metrics.total_completed_work_items, 1)
        self.assertEqual(metrics.artifact_production_count, 2)

    def test_goal_health_indicators_reflect_progress_and_blocked_threads(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Health Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="high",
        )
        active_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Active Thread",
            owner=self.identity,
            priority="high",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        blocked_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Blocked Thread",
            owner=self.identity,
            priority="normal",
            status="paused",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        finished = DevTask.objects.create(
            title="Finished",
            description="",
            task_type="codegen",
            status="completed",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=active_thread,
            work_item_id="done-1",
            runtime_run_id=uuid.uuid4(),
        )
        DevTask.objects.create(
            title="Ready",
            description="",
            task_type="codegen",
            status="queued",
            priority=2,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=active_thread,
            work_item_id="ready-1",
        )
        DevTask.objects.create(
            title="Blocked",
            description="",
            task_type="codegen",
            status="queued",
            priority=3,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=blocked_thread,
            work_item_id="blocked-1",
            dependency_work_item_ids=["missing-dependency"],
        )

        def runtime_detail_lookup(task):
            if task.id != finished.id:
                return None
            return {"artifacts": [{"id": "artifact-1"}]}

        health = compute_goal_health_indicators(goal, runtime_detail_lookup=runtime_detail_lookup)
        self.assertEqual(health.progress_percent, 33)
        self.assertEqual(health.active_threads, 1)
        self.assertEqual(health.blocked_threads, 1)
        self.assertEqual(health.recent_artifacts, 1)

    def test_goal_execution_metrics_handle_goal_with_no_threads(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="No Threads Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        metrics = compute_goal_execution_metrics(goal, runtime_detail_lookup=lambda _task: None)
        self.assertEqual(metrics.active_threads, 0)
        self.assertEqual(metrics.blocked_threads, 0)
        self.assertEqual(metrics.total_completed_work_items, 0)
        self.assertEqual(metrics.artifact_production_count, 0)

    def test_goal_health_indicators_handle_goal_with_no_threads(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Empty Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        health = compute_goal_health_indicators(goal, runtime_detail_lookup=lambda _task: None)
        progress = compute_goal_progress(goal)
        self.assertEqual(progress.goal_progress_status, "not_started")
        self.assertEqual(health.progress_percent, 0)
        self.assertEqual(health.active_threads, 0)
        self.assertEqual(health.blocked_threads, 0)
        self.assertEqual(health.recent_artifacts, 0)

    def test_goal_health_indicators_handle_blocked_threads_only(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Blocked Only Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        blocked_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Blocked Thread",
            owner=self.identity,
            priority="high",
            status="paused",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="Blocked",
            description="",
            task_type="codegen",
            status="queued",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=blocked_thread,
            work_item_id="blocked-1",
            dependency_work_item_ids=["missing-dependency"],
        )
        health = compute_goal_health_indicators(goal, runtime_detail_lookup=lambda _task: None)
        progress = compute_goal_progress(goal)
        self.assertEqual(progress.goal_progress_status, "stalled")
        self.assertEqual(health.progress_percent, 0)
        self.assertEqual(health.active_threads, 0)
        self.assertEqual(health.blocked_threads, 1)
        self.assertEqual(health.recent_artifacts, 0)

    def test_goal_health_indicators_handle_artifact_activity_with_low_completion(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Artifact Heavy Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        active_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Active Thread",
            owner=self.identity,
            priority="high",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        finished = DevTask.objects.create(
            title="Finished",
            description="",
            task_type="codegen",
            status="completed",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=active_thread,
            work_item_id="done-1",
            runtime_run_id=uuid.uuid4(),
        )
        DevTask.objects.create(
            title="Queued",
            description="",
            task_type="codegen",
            status="queued",
            priority=2,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=active_thread,
            work_item_id="queued-1",
        )
        health = compute_goal_health_indicators(
            goal,
            runtime_detail_lookup=lambda task: {"artifacts": [{"id": "artifact-1"}, {"id": "artifact-2"}, {"id": "artifact-3"}]}
            if task.id == finished.id
            else None,
        )
        self.assertEqual(health.progress_percent, 50)
        self.assertEqual(health.active_threads, 1)
        self.assertEqual(health.blocked_threads, 0)
        self.assertEqual(health.recent_artifacts, 3)

    def test_goal_health_indicators_completed_goal_ignores_historical_runtime_activity_for_progress(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Completed Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Done Thread",
            owner=self.identity,
            priority="high",
            status="completed",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        finished = DevTask.objects.create(
            title="Finished",
            description="",
            task_type="codegen",
            status="completed",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=thread,
            work_item_id="done-1",
            runtime_run_id=uuid.uuid4(),
        )
        health = compute_goal_health_indicators(
            goal,
            runtime_detail_lookup=lambda task: {"artifacts": [{"id": "artifact-1"}]} if task.id == finished.id else None,
        )
        progress = compute_goal_progress(goal)
        self.assertEqual(progress.goal_progress_status, "completed")
        self.assertEqual(health.progress_percent, 100)
        self.assertEqual(health.active_threads, 0)
        self.assertEqual(health.blocked_threads, 0)
        self.assertEqual(health.recent_artifacts, 1)

    def test_recommend_next_slice_prefers_ready_unblocked_work_over_blocked_work(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Blocked vs Ready",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        blocked_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Blocked Thread",
            owner=self.identity,
            priority="high",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        ready_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Ready Thread",
            owner=self.identity,
            priority="normal",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="Blocked work",
            description="",
            task_type="codegen",
            status="queued",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=blocked_thread,
            work_item_id="blocked-work",
            dependency_work_item_ids=["missing-dependency"],
        )
        DevTask.objects.create(
            title="Ready work",
            description="",
            task_type="codegen",
            status="queued",
            priority=2,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=ready_thread,
            work_item_id="ready-work",
        )
        recommendation = recommend_next_slice(goal)
        self.assertEqual(recommendation.thread_title, "Ready Thread")
        self.assertEqual(recommendation.recommended_work_items[0].title, "Ready work")
        self.assertEqual(recommendation.queue_suggestion.action_type, "queue_first_slice")

    def test_goal_portfolio_priority_marks_blocked_goal_high(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Blocked Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        blocked_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Blocked Thread",
            owner=self.identity,
            priority="high",
            status="paused",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="Blocked task",
            description="",
            task_type="codegen",
            status="queued",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=blocked_thread,
            work_item_id="blocked-work",
            dependency_work_item_ids=["missing-dependency"],
        )
        row = build_goal_portfolio_row(goal, runtime_detail_lookup=lambda _task: None)
        self.assertEqual(row.health_status, "blocked")
        self.assertEqual(row.coordination_priority.value, "high")
        self.assertIn("Blocked threads", " ".join(row.coordination_priority.reasons))

    def test_goal_portfolio_priority_marks_active_goal_medium(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Active Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        active_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Active Thread",
            owner=self.identity,
            priority="high",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="Ready task",
            description="",
            task_type="codegen",
            status="queued",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=active_thread,
            work_item_id="ready-task",
        )
        row = build_goal_portfolio_row(goal, runtime_detail_lookup=lambda _task: None)
        self.assertEqual(row.health_status, "active")
        self.assertEqual(row.coordination_priority.value, "medium")

    def test_goal_portfolio_priority_marks_completed_goal_low(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Completed Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            planning_status="completed",
            priority="normal",
        )
        row = build_goal_portfolio_row(goal, runtime_detail_lookup=lambda _task: None)
        self.assertEqual(row.coordination_priority.value, "low")

    def test_build_goal_portfolio_state_is_deterministic(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Portfolio Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Thread",
            owner=self.identity,
            priority="normal",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="Task",
            description="",
            task_type="codegen",
            status="queued",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=thread,
            work_item_id="task-1",
        )
        first = build_goal_portfolio_state([goal], runtime_detail_lookup=lambda _task: None)
        second = build_goal_portfolio_state([goal], runtime_detail_lookup=lambda _task: None)
        self.assertEqual(first, second)

    def test_goal_listing_includes_portfolio_recommendation(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Portfolio Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="high",
        )
        thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Listing Data Ingestion",
            owner=self.identity,
            priority="high",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="Implement adapter",
            description="",
            task_type="codegen",
            status="queued",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=thread,
            work_item_id="task-1",
        )

        list_request = self._request("/xyn/api/goals", data={"workspace_id": str(self.workspace.id)})
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api._resolve_workspace_for_identity", return_value=self.workspace
        ):
            list_response = goals_collection(list_request)
        listing = json.loads(list_response.content)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(listing["portfolio_state"]["recommended_goal"]["goal_id"], str(goal.id))
        self.assertEqual(listing["portfolio_state"]["recommended_goal"]["queue_action_type"], "queue_first_slice")

    def test_recommend_portfolio_goal_prefers_high_priority_actionable_goal(self):
        dominant_goal = Goal.objects.create(
            workspace=self.workspace,
            title="Blocked Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="high",
        )
        dominant_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=dominant_goal,
            title="Blocked Thread",
            owner=self.identity,
            priority="high",
            status="paused",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="Resume-worthy task",
            description="",
            task_type="codegen",
            status="queued",
            priority=1,
            source_entity_type="goal",
            source_entity_id=dominant_goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=dominant_goal,
            coordination_thread=dominant_thread,
            work_item_id="resume-task",
        )
        secondary_goal = Goal.objects.create(
            workspace=self.workspace,
            title="Secondary Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        secondary_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=secondary_goal,
            title="Secondary Thread",
            owner=self.identity,
            priority="normal",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="Secondary queued task",
            description="",
            task_type="codegen",
            status="queued",
            priority=1,
            source_entity_type="goal",
            source_entity_id=secondary_goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=secondary_goal,
            coordination_thread=secondary_thread,
            work_item_id="secondary-task",
        )

        recommendation = recommend_portfolio_goal([secondary_goal, dominant_goal], runtime_detail_lookup=lambda _task: None)

        self.assertIsNotNone(recommendation)
        self.assertEqual(recommendation.goal_id, str(dominant_goal.id))
        self.assertEqual(recommendation.queue_action_type, "resume_thread")

    def test_recommend_portfolio_goal_preserves_input_order_when_priority_ties(self):
        first_goal = Goal.objects.create(
            workspace=self.workspace,
            title="First Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="high",
        )
        first_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=first_goal,
            title="First Thread",
            owner=self.identity,
            priority="high",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="First queued task",
            description="",
            task_type="codegen",
            status="queued",
            priority=1,
            source_entity_type="goal",
            source_entity_id=first_goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=first_goal,
            coordination_thread=first_thread,
            work_item_id="first-task",
        )
        second_goal = Goal.objects.create(
            workspace=self.workspace,
            title="Second Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="high",
        )
        second_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=second_goal,
            title="Second Thread",
            owner=self.identity,
            priority="high",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="Second queued task",
            description="",
            task_type="codegen",
            status="queued",
            priority=1,
            source_entity_type="goal",
            source_entity_id=second_goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=second_goal,
            coordination_thread=second_thread,
            work_item_id="second-task",
        )

        recommendation = recommend_portfolio_goal([first_goal, second_goal], runtime_detail_lookup=lambda _task: None)

        self.assertIsNotNone(recommendation)
        self.assertEqual(recommendation.goal_id, str(first_goal.id))

    def test_compute_portfolio_insights_detects_blocked_goal(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Blocked Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="high",
        )
        blocked_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Blocked Thread",
            owner=self.identity,
            priority="high",
            status="paused",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="Blocked task",
            description="",
            task_type="codegen",
            status="queued",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=blocked_thread,
            work_item_id="blocked-1",
            dependency_work_item_ids=["missing-dependency"],
        )
        insights = compute_portfolio_insights([goal], runtime_detail_lookup=lambda _task: None)
        self.assertEqual(insights[0].key, "blocked_goals")
        self.assertIn("blocked", insights[0].summary.lower())

    def test_compute_portfolio_insights_detects_dominant_goal(self):
        dominant_goal = Goal.objects.create(
            workspace=self.workspace,
            title="Dominant Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="high",
        )
        quiet_goal = Goal.objects.create(
            workspace=self.workspace,
            title="Quiet Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        dominant_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=dominant_goal,
            title="Dominant Thread",
            owner=self.identity,
            priority="high",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        quiet_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=quiet_goal,
            title="Quiet Thread",
            owner=self.identity,
            priority="normal",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        for index in range(3):
            DevTask.objects.create(
                title=f"Dominant task {index}",
                description="",
                task_type="codegen",
                status="completed",
                priority=index + 1,
                source_entity_type="goal",
                source_entity_id=dominant_goal.id,
                source_conversation_id="thread-1",
                intent_type="goal_planning",
                target_repo="xyn-platform",
                target_branch="develop",
                execution_policy={},
                goal=dominant_goal,
                coordination_thread=dominant_thread,
                work_item_id=f"dominant-{index}",
                runtime_run_id=uuid.uuid4(),
            )
        DevTask.objects.create(
            title="Quiet task",
            description="",
            task_type="codegen",
            status="queued",
            priority=1,
            source_entity_type="goal",
            source_entity_id=quiet_goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=quiet_goal,
            coordination_thread=quiet_thread,
            work_item_id="quiet-1",
        )
        insights = compute_portfolio_insights([dominant_goal, quiet_goal], runtime_detail_lookup=lambda _task: None)
        dominant = next((item for item in insights if item.key == "dominant_goal"), None)
        self.assertIsNotNone(dominant)
        self.assertIn("dominates", dominant.summary.lower())

    def test_compute_portfolio_insights_detects_starved_goal(self):
        active_goal = Goal.objects.create(
            workspace=self.workspace,
            title="Active Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="high",
        )
        starved_goal = Goal.objects.create(
            workspace=self.workspace,
            title="Starved Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        active_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=active_goal,
            title="Active Thread",
            owner=self.identity,
            priority="high",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        starved_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=starved_goal,
            title="Starved Thread",
            owner=self.identity,
            priority="normal",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="Done",
            description="",
            task_type="codegen",
            status="completed",
            priority=1,
            source_entity_type="goal",
            source_entity_id=active_goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=active_goal,
            coordination_thread=active_thread,
            work_item_id="done-1",
            runtime_run_id=uuid.uuid4(),
        )
        DevTask.objects.create(
            title="Ready but idle",
            description="",
            task_type="codegen",
            status="queued",
            priority=1,
            source_entity_type="goal",
            source_entity_id=starved_goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=starved_goal,
            coordination_thread=starved_thread,
            work_item_id="idle-1",
        )
        insights = compute_portfolio_insights([active_goal, starved_goal], runtime_detail_lookup=lambda _task: None)
        starved = next((item for item in insights if item.key == "starved_goals"), None)
        self.assertIsNotNone(starved)
        self.assertIn("idle", starved.summary.lower())

    def test_recommend_next_slice_prefers_earlier_thread_when_candidates_are_equally_valid(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Tie Break Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        earlier = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Earlier Thread",
            owner=self.identity,
            priority="normal",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        later = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Later Thread",
            owner=self.identity,
            priority="normal",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="Earlier slice",
            description="",
            task_type="codegen",
            status="queued",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=earlier,
            work_item_id="earlier-slice",
        )
        DevTask.objects.create(
            title="Later slice",
            description="",
            task_type="codegen",
            status="queued",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=later,
            work_item_id="later-slice",
        )
        recommendation_a = recommend_next_slice(goal)
        recommendation_b = recommend_next_slice(goal)
        self.assertEqual(recommendation_a.thread_title, "Earlier Thread")
        self.assertEqual(recommendation_a.thread_title, recommendation_b.thread_title)
        self.assertEqual(recommendation_a.queue_suggestion.action_type, "queue_first_slice")

    def test_recommend_next_slice_suggests_resume_for_paused_thread_with_queued_work(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="No Ready Work",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        blocked_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Blocked Thread",
            owner=self.identity,
            priority="normal",
            status="paused",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="Blocked work",
            description="",
            task_type="codegen",
            status="queued",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=blocked_thread,
            work_item_id="blocked-work",
        )
        recommendation = recommend_next_slice(goal)
        self.assertEqual(recommendation.recommended_work_items, [])
        self.assertIsNotNone(recommendation.queue_suggestion)
        self.assertEqual(recommendation.queue_suggestion.action_type, "resume_thread")
        self.assertIn("paused", recommendation.reasoning_summary.lower())

    def test_recommend_next_slice_returns_empty_recommendation_when_nothing_is_queueable(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Nothing Queueable",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        blocked_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Blocked Thread",
            owner=self.identity,
            priority="normal",
            status="active",
            work_in_progress_limit=1,
            execution_policy={"review_required": True},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="Blocked work",
            description="",
            task_type="codegen",
            status="awaiting_review",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={"require_human_review_on_failure": True},
            goal=goal,
            coordination_thread=blocked_thread,
            work_item_id="blocked-work",
        )
        recommendation = recommend_next_slice(goal)
        self.assertEqual(recommendation.recommended_work_items, [])
        self.assertIsNone(recommendation.queue_suggestion)
        self.assertIn("No executable slice is ready yet", recommendation.reasoning_summary)
        self.assertEqual([action.type for action in recommendation.actions], ["review_thread"])

    def test_recommend_next_slice_returns_empty_for_completed_goal(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Completed Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
            planning_status="completed",
        )
        thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Completed Thread",
            owner=self.identity,
            priority="normal",
            status="completed",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="Completed work",
            description="",
            task_type="codegen",
            status="completed",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=thread,
            work_item_id="completed-work",
        )
        recommendation = recommend_next_slice(goal)
        self.assertEqual(recommendation.recommended_work_items, [])
        self.assertIsNone(recommendation.queue_suggestion)
        self.assertEqual(recommendation.actions, [])
        self.assertIn("completed", recommendation.summary.lower())

    def test_goal_review_rejects_stale_approval_when_thread_state_changes(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Stale Approval",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
            planning_status="decomposed",
        )
        thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Primary Thread",
            owner=self.identity,
            priority="high",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="Queued work",
            description="",
            task_type="codegen",
            status="queued",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=thread,
            work_item_id="queued-work",
        )
        other_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Follow-on Thread",
            owner=self.identity,
            priority="low",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="Follow-on work",
            description="",
            task_type="codegen",
            status="queued",
            priority=2,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=other_thread,
            work_item_id="follow-on-work",
        )
        recommendation_id = recommend_next_slice(goal).recommendation_id
        task = thread.work_items.get(work_item_id="queued-work")
        task.status = "completed"
        task.save(update_fields=["status", "updated_at"])
        request = self._request(
            f"/xyn/api/goals/{goal.id}/review",
            method="POST",
            data=json.dumps({"review_action": "approve_and_queue", "recommendation_id": recommendation_id}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = goal_review(request, str(goal.id))
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(payload["status"], "stale_recommendation")

    def test_goal_detail_includes_development_loop_summary(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Goal Detail Summary",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Listing Data Ingestion",
            owner=self.identity,
            priority="high",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="Implement adapter",
            description="",
            task_type="codegen",
            status="completed",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=thread,
            work_item_id="adapter",
            runtime_run_id="77ad82b5-a303-4455-8994-853e4bb89df3",
        )
        request = self._request(f"/xyn/api/goals/{goal.id}")
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api._fetch_runtime_run_detail_payload",
            return_value={
                "run_id": "77ad82b5-a303-4455-8994-853e4bb89df3",
                "status": "completed",
                "summary": "Adapter implemented",
                "artifacts": [
                    {
                        "id": "artifact-1",
                        "artifact_type": "summary",
                        "label": "Final summary",
                    }
                ],
                "steps": [],
            },
        ):
            response = goal_detail(request, str(goal.id))
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["development_loop_summary"]["goal_status"], "completed")
        self.assertEqual(payload["development_loop_summary"]["threads"][0]["title"], "Listing Data Ingestion")
        self.assertEqual(payload["development_loop_summary"]["recent_work_results"][0]["title"], "Implement adapter")
        self.assertEqual(payload["development_loop_summary"]["recent_work_results"][0]["artifact_count"], 1)
        self.assertEqual(payload["development_loop_summary"]["recent_work_results"][0]["artifact_labels"], ["Final summary"])

    def test_goal_detail_includes_goal_health_and_execution_metrics(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Goal Health Detail",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="high",
        )
        active_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Active Thread",
            owner=self.identity,
            priority="high",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        blocked_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Blocked Thread",
            owner=self.identity,
            priority="normal",
            status="paused",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="Completed work",
            description="",
            task_type="codegen",
            status="completed",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=active_thread,
            work_item_id="goal-health-complete",
            runtime_run_id="8ca46c57-aa11-4495-a232-c43775a34c59",
        )
        DevTask.objects.create(
            title="Ready work",
            description="",
            task_type="codegen",
            status="queued",
            priority=2,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=active_thread,
            work_item_id="goal-health-ready",
        )
        DevTask.objects.create(
            title="Blocked work",
            description="",
            task_type="codegen",
            status="queued",
            priority=2,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=blocked_thread,
            work_item_id="goal-health-blocked",
            dependency_work_item_ids=["missing-dependency"],
        )
        request = self._request(f"/xyn/api/goals/{goal.id}")
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api._fetch_runtime_run_detail_payload",
            return_value={
                "run_id": "8ca46c57-aa11-4495-a232-c43775a34c59",
                "status": "completed",
                "summary": "Completed successfully",
                "artifacts": [{"id": "artifact-1", "artifact_type": "summary", "label": "Summary"}],
                "steps": [],
            },
        ):
            response = goal_detail(request, str(goal.id))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["metrics"]["active_threads"], 1)
        self.assertEqual(payload["metrics"]["blocked_threads"], 1)
        self.assertEqual(payload["metrics"]["total_completed_work_items"], 1)
        self.assertEqual(payload["metrics"]["artifact_production_count"], 1)
        self.assertEqual(payload["goal_health"]["active_threads"], 1)
        self.assertEqual(payload["goal_health"]["blocked_threads"], 1)
        self.assertEqual(payload["goal_health"]["recent_artifacts"], 1)
        self.assertEqual(payload["goal_diagnostic"]["status"], "blocked")
        self.assertTrue(payload["development_insights"])
        self.assertEqual(payload["development_insights"][0]["key"], "blocked_work_dominates")

    def test_goal_diagnostic_detects_blocked_goal_due_to_blocked_threads(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Blocked Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="high",
        )
        thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Blocked Thread",
            owner=self.identity,
            priority="high",
            status="paused",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="Blocked slice",
            description="",
            task_type="codegen",
            status="queued",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=thread,
            work_item_id="blocked-slice",
        )
        diagnostic = compute_goal_diagnostic(goal)
        self.assertEqual(diagnostic.status, "blocked")
        self.assertTrue(any("blocked" in line.lower() for line in diagnostic.evidence))

    def test_goal_diagnostic_detects_fragmented_goal(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Fragmented Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        for index in range(3):
            thread = CoordinationThread.objects.create(
                workspace=self.workspace,
                goal=goal,
                title=f"Active Thread {index + 1}",
                owner=self.identity,
                priority="normal",
                status="active",
                work_in_progress_limit=1,
                execution_policy={},
                source_conversation_id="thread-1",
            )
            DevTask.objects.create(
                title=f"Queued {index + 1}",
                description="",
                task_type="codegen",
                status="queued",
                priority=index,
                source_entity_type="goal",
                source_entity_id=goal.id,
                source_conversation_id="thread-1",
                intent_type="goal_planning",
                target_repo="xyn-platform",
                target_branch="develop",
                execution_policy={},
                goal=goal,
                coordination_thread=thread,
                work_item_id=f"queued-{index + 1}",
            )
        diagnostic = compute_goal_diagnostic(goal)
        self.assertEqual(diagnostic.status, "fragmented")
        self.assertTrue(any("active thread" in line.lower() for line in diagnostic.evidence))

    def test_goal_diagnostic_detects_high_activity_low_progress(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="High Activity Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Active Thread",
            owner=self.identity,
            priority="normal",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        task = DevTask.objects.create(
            title="Queued work",
            description="",
            task_type="codegen",
            status="queued",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=thread,
            work_item_id="queued-work",
            runtime_run_id=uuid.uuid4(),
        )

        def runtime_detail_lookup(candidate):
            if candidate.id != task.id:
                return None
            return {
                "id": "run-1",
                "run_id": "run-1",
                "status": "failed",
                "artifacts": [
                    {"id": "artifact-1", "artifact_type": "summary", "label": "Summary 1"},
                    {"id": "artifact-2", "artifact_type": "summary", "label": "Summary 2"},
                    {"id": "artifact-3", "artifact_type": "summary", "label": "Summary 3"},
                    {"id": "artifact-4", "artifact_type": "summary", "label": "Summary 4"},
                ],
            }

        diagnostic = compute_goal_diagnostic(goal, runtime_detail_lookup=runtime_detail_lookup)
        self.assertEqual(diagnostic.status, "high_activity_low_progress")
        self.assertTrue(any("artifact" in line.lower() for line in diagnostic.evidence))

    def test_goal_diagnostic_detects_completed_goal(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Completed Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
            planning_status="completed",
        )
        thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Done Thread",
            owner=self.identity,
            priority="normal",
            status="completed",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="Done work",
            description="",
            task_type="codegen",
            status="completed",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=thread,
            work_item_id="done-work",
        )
        diagnostic = compute_goal_diagnostic(goal)
        self.assertEqual(diagnostic.status, "completed")

    def test_goal_diagnostic_handles_low_signal_goal(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Low Signal Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        diagnostic = compute_goal_diagnostic(goal)
        self.assertEqual(diagnostic.status, "low_signal")

    def test_goal_development_insights_detect_failure_cluster_and_blocked_work(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Insight Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        blocked_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Blocked Thread",
            owner=self.identity,
            priority="normal",
            status="paused",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        unstable_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Unstable Thread",
            owner=self.identity,
            priority="normal",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
        )
        DevTask.objects.create(
            title="Blocked slice",
            description="",
            task_type="codegen",
            status="queued",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=blocked_thread,
            work_item_id="blocked-slice",
            dependency_work_item_ids=["missing"],
        )
        failing_task = DevTask.objects.create(
            title="Unstable slice",
            description="",
            task_type="codegen",
            status="awaiting_review",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=unstable_thread,
            work_item_id="unstable-slice",
            runtime_run_id=uuid.uuid4(),
        )
        second_failing_task = DevTask.objects.create(
            title="Unstable slice 2",
            description="",
            task_type="codegen",
            status="awaiting_review",
            priority=2,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=unstable_thread,
            work_item_id="unstable-slice-2",
            runtime_run_id=uuid.uuid4(),
        )

        def runtime_detail_lookup(candidate):
            if candidate.id == failing_task.id:
                return {
                    "id": "run-unstable",
                    "run_id": "run-unstable",
                    "status": "failed",
                    "started_at": "2026-03-12T10:00:00Z",
                    "completed_at": "2026-03-12T11:00:00Z",
                    "artifacts": [
                        {"id": "artifact-1", "artifact_type": "summary", "label": "Summary 1"},
                        {"id": "artifact-2", "artifact_type": "summary", "label": "Summary 2"},
                    ],
                }
            if candidate.id == second_failing_task.id:
                return {
                    "id": "run-unstable-2",
                    "run_id": "run-unstable-2",
                    "status": "blocked",
                    "started_at": "2026-03-12T11:00:00Z",
                    "completed_at": "2026-03-12T11:30:00Z",
                    "artifacts": [
                        {"id": "artifact-3", "artifact_type": "summary", "label": "Summary 3"},
                        {"id": "artifact-4", "artifact_type": "summary", "label": "Summary 4"},
                    ],
                }
            return None

        insights = compute_goal_development_insights(goal, runtime_detail_lookup=runtime_detail_lookup)
        keys = [item.key for item in insights]
        self.assertIn("blocked_work_dominates", keys)
        self.assertIn("failure_cluster", keys)

    def test_goal_development_insights_degrade_to_low_signal_when_evidence_is_sparse(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Sparse Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        insights = compute_goal_development_insights(goal)
        self.assertEqual(len(insights), 1)
        self.assertEqual(insights[0].key, "low_signal")

    def test_goal_diagnostic_reports_ambiguous_runtime_provenance_conservatively(self):
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Ambiguous Runtime Goal",
            description="",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            title="Runtime Refactor",
            description="",
            owner=self.identity,
            priority="high",
            status="active",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id="thread-1",
            goal=goal,
        )
        task = DevTask.objects.create(
            title="Runtime work",
            description="",
            task_type="codegen",
            status="running",
            priority=1,
            source_entity_type="goal",
            source_entity_id=goal.id,
            source_conversation_id="thread-1",
            intent_type="goal_planning",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={},
            goal=goal,
            coordination_thread=thread,
            work_item_id="runtime-work",
            runtime_run_id=uuid.uuid4(),
        )

        def runtime_detail_lookup(candidate):
            if candidate.id != task.id:
                return None
            return {
                "id": "run-ambiguous",
                "run_id": "run-ambiguous",
                "status": "running",
                "started_at": "2026-03-12T10:00:00Z",
                "completed_at": None,
                "artifacts": [],
            }

        diagnostic = compute_goal_diagnostic(goal, runtime_detail_lookup=runtime_detail_lookup)
        self.assertEqual(diagnostic.status, "low_signal")
        self.assertTrue(any("sparse" in item.lower() or "insufficient" in item.lower() for item in diagnostic.evidence))
        self.assertIn("not enough execution evidence", compute_goal_development_insights(goal, runtime_detail_lookup=runtime_detail_lookup)[0].summary.lower())
        self.assertFalse(any("queued through the supervised loop" in item.lower() for item in diagnostic.evidence))
