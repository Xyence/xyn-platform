import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import RequestFactory, TestCase
from django.utils import timezone

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
    ContextPack,
    SolutionChangeSession,
    SolutionChangeSessionPromotionEvidence,
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
import xyn_orchestrator.xyn_api as xyn_api
from xyn_orchestrator.xyn_api import (
    application_artifact_membership_detail,
    application_artifact_memberships_collection,
    application_solution_change_session_detail,
    application_solution_change_session_control,
    application_solution_change_session_control_action,
    application_solution_change_session_reply,
    application_solution_change_session_continue,
    application_solution_change_session_regenerate_options,
    application_solution_change_session_select_option,
    application_solution_change_session_checkpoint_decision,
    application_solution_change_session_plan,
    application_solution_change_session_prepare_preview,
    application_solution_change_session_stage_apply,
    application_solution_change_session_validate,
    application_solution_change_session_promote,
    application_solution_change_session_rollback,
    application_solution_change_session_promotion_evidence,
    application_solution_change_session_finalize,
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
    workspace_linked_change_session,
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

    def _seed_default_xyn_solution_memberships(self) -> tuple[Application, Artifact, Artifact, Artifact]:
        module_type = ArtifactType.objects.create(slug=f"module-{uuid.uuid4().hex[:6]}", name="Module")
        workbench_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=module_type,
            title="Workbench",
            slug=f"core.workbench-{uuid.uuid4().hex[:6]}",
            status="published",
            visibility="team",
            summary="Default shell/workbench surface.",
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=[],
            edit_mode="repo_backed",
        )
        xyn_ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=module_type,
            title="xyn-ui",
            slug=f"xyn-ui-{uuid.uuid4().hex[:6]}",
            status="published",
            visibility="team",
            summary="Deployable Xyn UI runtime artifact.",
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["apps/xyn-ui/"],
            edit_mode="repo_backed",
        )
        xyn_api_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=module_type,
            title="xyn-api",
            slug=f"xyn-api-{uuid.uuid4().hex[:6]}",
            status="published",
            visibility="team",
            summary="Deployable Xyn API runtime artifact.",
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["services/xyn-api/backend/"],
            edit_mode="repo_backed",
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Xyn",
            summary="Default Xyn solution",
            source_factory_key="xyn_platform_default",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Improve platform workflows",
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=workbench_artifact,
            role="primary_ui",
            responsibility_summary="Default shell/workbench surface.",
            sort_order=10,
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=xyn_ui_artifact,
            role="runtime_service",
            responsibility_summary="Default UI runtime artifact.",
            sort_order=20,
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=xyn_api_artifact,
            role="runtime_service",
            responsibility_summary="Default API runtime artifact.",
            sort_order=30,
        )
        return application, workbench_artifact, xyn_ui_artifact, xyn_api_artifact

    def test_solution_change_session_ui_code_change_prefers_editable_xyn_ui_artifact(self):
        application, workbench_artifact, xyn_ui_artifact, _xyn_api_artifact = self._seed_default_xyn_solution_memberships()
        create_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions",
            method="post",
            data=json.dumps(
                {
                    "title": "Resize input field",
                    "request_text": "Resize the requested change input field so it uses the full panel width.",
                }
            ),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = application_solution_change_sessions_collection(create_request, str(application.id))
        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.content)
        analysis = ((payload.get("session") or {}).get("analysis") or {})
        suggested_ids = [str(item) for item in (analysis.get("suggested_artifact_ids") or [])]
        self.assertTrue(suggested_ids)
        self.assertEqual(suggested_ids[0], str(xyn_ui_artifact.id))
        self.assertNotEqual(suggested_ids[0], str(workbench_artifact.id))

    def test_solution_change_session_workbench_navigation_request_can_still_select_workbench(self):
        application, workbench_artifact, _xyn_ui_artifact, _xyn_api_artifact = self._seed_default_xyn_solution_memberships()
        create_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions",
            method="post",
            data=json.dumps(
                {
                    "title": "Workbench navigation",
                    "request_text": "Change workbench navigation structure for platform settings grouping.",
                }
            ),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = application_solution_change_sessions_collection(create_request, str(application.id))
        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.content)
        analysis = ((payload.get("session") or {}).get("analysis") or {})
        suggested_ids = [str(item) for item in (analysis.get("suggested_artifact_ids") or [])]
        self.assertTrue(suggested_ids)
        self.assertEqual(suggested_ids[0], str(workbench_artifact.id))

    def test_solution_change_session_api_request_still_prefers_xyn_api(self):
        application, _workbench_artifact, _xyn_ui_artifact, xyn_api_artifact = self._seed_default_xyn_solution_memberships()
        create_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions",
            method="post",
            data=json.dumps(
                {
                    "title": "API schema update",
                    "request_text": "Update API endpoint schema and response contract for change session payloads.",
                }
            ),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = application_solution_change_sessions_collection(create_request, str(application.id))
        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.content)
        analysis = ((payload.get("session") or {}).get("analysis") or {})
        suggested_ids = [str(item) for item in (analysis.get("suggested_artifact_ids") or [])]
        self.assertTrue(suggested_ids)
        self.assertEqual(suggested_ids[0], str(xyn_api_artifact.id))

    def test_solution_change_session_strict_backend_refactor_prefers_xyn_api_and_suppresses_ui_routing(self):
        application, _workbench_artifact, xyn_ui_artifact, xyn_api_artifact = self._seed_default_xyn_solution_memberships()
        request_text = (
            "STRICT REFACTOR: Decompose xyn_orchestrator/xyn_api.py into smaller modules by extracting "
            "solution-change-session workflow logic only. DO NOT modify UI, styling, layout, or behavior. "
            "DO NOT introduce new features. Only move existing logic into new modules and replace with delegation "
            "wrappers. Maintain identical request/response behavior."
        )
        create_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions",
            method="post",
            data=json.dumps(
                {
                    "title": "Strict backend refactor",
                    "request_text": request_text,
                }
            ),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = application_solution_change_sessions_collection(create_request, str(application.id))
        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.content)
        analysis = ((payload.get("session") or {}).get("analysis") or {})
        suggested_ids = [str(item) for item in (analysis.get("suggested_artifact_ids") or [])]
        self.assertTrue(suggested_ids)
        self.assertEqual(suggested_ids[0], str(xyn_api_artifact.id))
        self.assertNotEqual(suggested_ids[0], str(xyn_ui_artifact.id))
        planning = ((payload.get("session") or {}).get("planning") or {})
        option_turn = planning.get("pending_option_set") or {}
        option_payload = option_turn.get("payload") if isinstance(option_turn.get("payload"), dict) else {}
        options = option_payload.get("options") if isinstance(option_payload.get("options"), list) else []
        self.assertTrue(options)
        self.assertEqual(str((options[0] or {}).get("id") or ""), str(xyn_api_artifact.id))

        memberships = list(
            ApplicationArtifactMembership.objects.filter(application=application)
            .select_related("artifact", "artifact__type")
            .order_by("sort_order", "created_at")
        )
        direct_analysis = xyn_api._analyze_solution_impacted_artifacts(
            application=application,
            request_text=request_text,
            memberships=memberships,
        )
        impacted = direct_analysis.get("impacted_artifacts") if isinstance(direct_analysis.get("impacted_artifacts"), list) else []
        self.assertTrue(impacted)
        self.assertEqual(str((impacted[0] or {}).get("artifact_id") or ""), str(xyn_api_artifact.id))
        top_reasons = [str(item).lower() for item in ((impacted[0] or {}).get("reasons") or [])]
        self.assertFalse(any("ui code-change request" in item for item in top_reasons))
        self.assertTrue(any("structural backend refactor" in item or "backend python module" in item for item in top_reasons))

    def test_solution_change_session_explicit_backend_file_path_dominates_routing(self):
        application, _workbench_artifact, xyn_ui_artifact, xyn_api_artifact = self._seed_default_xyn_solution_memberships()
        request_text = (
            "Refactor services/xyn-api/backend/xyn_orchestrator/xyn_api.py by extracting solution change session handlers "
            "into dedicated backend modules and preserve external behavior."
        )
        create_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions",
            method="post",
            data=json.dumps({"title": "Backend module extraction", "request_text": request_text}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = application_solution_change_sessions_collection(create_request, str(application.id))
        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.content)
        analysis = ((payload.get("session") or {}).get("analysis") or {})
        suggested_ids = [str(item) for item in (analysis.get("suggested_artifact_ids") or [])]
        self.assertTrue(suggested_ids)
        self.assertEqual(suggested_ids[0], str(xyn_api_artifact.id))
        self.assertNotEqual(suggested_ids[0], str(xyn_ui_artifact.id))

    def test_solution_change_session_negative_ui_constraints_suppress_ui_ranking_without_ui_file_target(self):
        application, _workbench_artifact, xyn_ui_artifact, xyn_api_artifact = self._seed_default_xyn_solution_memberships()
        request_text = (
            "Backend-only cleanup for change session orchestration. No UI changes. "
            "No styling changes. No layout changes. Keep behavior identical."
        )
        create_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions",
            method="post",
            data=json.dumps({"title": "Backend only cleanup", "request_text": request_text}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = application_solution_change_sessions_collection(create_request, str(application.id))
        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.content)
        analysis = ((payload.get("session") or {}).get("analysis") or {})
        impacted = analysis.get("impacted_artifacts") if isinstance(analysis.get("impacted_artifacts"), list) else []
        self.assertTrue(impacted)
        suggested_ids = [str(item) for item in (analysis.get("suggested_artifact_ids") or [])]
        self.assertTrue(suggested_ids)
        self.assertEqual(suggested_ids[0], str(xyn_api_artifact.id))
        ui_row = next((row for row in impacted if str((row or {}).get("artifact_id") or "") == str(xyn_ui_artifact.id)), None)
        api_row = next((row for row in impacted if str((row or {}).get("artifact_id") or "") == str(xyn_api_artifact.id)), None)
        self.assertIsNotNone(ui_row)
        self.assertIsNotNone(api_row)
        self.assertLess(int((ui_row or {}).get("score") or 0), int((api_row or {}).get("score") or 0))

    def test_solution_change_session_negative_ui_constraints_with_explicit_ui_file_can_still_target_ui(self):
        application, _workbench_artifact, xyn_ui_artifact, _xyn_api_artifact = self._seed_default_xyn_solution_memberships()
        request_text = (
            "Patch apps/xyn-ui/src/app/components/common/HeaderUtilityMenu.tsx. "
            "No UI changes, no styling changes, no layout changes. "
            "Only extract duplicated menu utility code into a sibling module."
        )
        create_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions",
            method="post",
            data=json.dumps({"title": "UI path explicitly targeted", "request_text": request_text}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = application_solution_change_sessions_collection(create_request, str(application.id))
        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.content)
        analysis = ((payload.get("session") or {}).get("analysis") or {})
        suggested_ids = [str(item) for item in (analysis.get("suggested_artifact_ids") or [])]
        self.assertTrue(suggested_ids)
        self.assertEqual(suggested_ids[0], str(xyn_ui_artifact.id))

    def test_solution_change_session_option_set_orders_by_impacted_artifact_ranking(self):
        application, _workbench_artifact, xyn_ui_artifact, _xyn_api_artifact = self._seed_default_xyn_solution_memberships()
        create_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions",
            method="post",
            data=json.dumps(
                {
                    "title": "Resize input field",
                    "request_text": "Resize the requested change input field so it uses the full panel width.",
                }
            ),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = application_solution_change_sessions_collection(create_request, str(application.id))
        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.content)
        planning = ((payload.get("session") or {}).get("planning") or {})
        option_turn = planning.get("pending_option_set") or {}
        option_payload = option_turn.get("payload") if isinstance(option_turn.get("payload"), dict) else {}
        options = option_payload.get("options") if isinstance(option_payload.get("options"), list) else []
        self.assertTrue(options)
        self.assertEqual(str((options[0] or {}).get("id") or ""), str(xyn_ui_artifact.id))
        self.assertIn("initial artifact", str(option_payload.get("prompt") or "").lower())

    def test_solution_change_session_select_option_reorders_selected_artifacts_without_dropping_others(self):
        application, _workbench_artifact, xyn_ui_artifact, xyn_api_artifact = self._seed_default_xyn_solution_memberships()
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Multi-artifact reorder",
            request_text="Update UI and API behavior",
            created_by=self.identity,
            selected_artifact_ids_json=[str(xyn_api_artifact.id), str(xyn_ui_artifact.id)],
        )
        option_turn = SolutionPlanningTurn.objects.create(
            workspace=self.workspace,
            session=session,
            actor="planner",
            kind="option_set",
            payload_json={
                "prompt": "Select focus",
                "options": [
                    {"id": str(xyn_ui_artifact.id), "label": "xyn-ui"},
                    {"id": str(xyn_api_artifact.id), "label": "xyn-api"},
                ],
            },
            created_by=self.identity,
        )
        select_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/select-option",
            method="post",
            data=json.dumps({"source_turn_id": str(option_turn.id), "option_id": str(xyn_ui_artifact.id)}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = application_solution_change_session_select_option(select_request, str(application.id), str(session.id))
        self.assertEqual(response.status_code, 200)
        session.refresh_from_db()
        self.assertEqual(
            [str(item) for item in (session.selected_artifact_ids_json or [])],
            [str(xyn_ui_artifact.id), str(xyn_api_artifact.id)],
        )

    def test_solution_change_session_plan_auto_selects_default_pending_option(self):
        application, _workbench_artifact, xyn_ui_artifact, xyn_api_artifact = self._seed_default_xyn_solution_memberships()
        create_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions",
            method="post",
            data=json.dumps(
                {
                    "title": "Resize input field",
                    "request_text": "Resize the requested change input field so it uses the full panel width.",
                }
            ),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            create_response = application_solution_change_sessions_collection(create_request, str(application.id))
            self.assertEqual(create_response.status_code, 201)
            create_payload = json.loads(create_response.content)
            session_id = str((create_payload.get("session") or {}).get("id") or "")
            session = SolutionChangeSession.objects.get(id=session_id)
            self.assertIn(str(xyn_ui_artifact.id), [str(item) for item in (session.selected_artifact_ids_json or [])])
            self.assertIn(str(xyn_api_artifact.id), [str(item) for item in (session.selected_artifact_ids_json or [])])

            plan_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/plan",
                method="post",
                data=json.dumps({}),
            )
            plan_response = application_solution_change_session_plan(plan_request, str(application.id), str(session.id))

        self.assertEqual(plan_response.status_code, 200)
        session.refresh_from_db()
        selected_ids = [str(item) for item in (session.selected_artifact_ids_json or [])]
        self.assertTrue(selected_ids)
        self.assertEqual(selected_ids[0], str(xyn_ui_artifact.id))
        turns = list(SolutionPlanningTurn.objects.filter(session=session).order_by("sequence"))
        auto_option_responses = [
            turn for turn in turns
            if turn.actor == "user"
            and turn.kind == "response"
            and isinstance(turn.payload_json, dict)
            and str(turn.payload_json.get("response_kind") or "") == "option_selection"
            and bool(turn.payload_json.get("auto_selected"))
        ]
        self.assertTrue(auto_option_responses)

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
        self.assertEqual((latest_draft.get("payload") or {}).get("selected_artifact_ids"), [])
        self.assertIsNone(planning.get("pending_question"))
        self.assertIsNone(planning.get("pending_option_set"))
        pending_checkpoints = planning.get("pending_checkpoints") or []
        self.assertEqual(len(pending_checkpoints), 1)
        self.assertEqual(str((pending_checkpoints[0] or {}).get("status") or ""), "pending")

    def test_existing_solution_change_session_without_memberships_generates_targeted_plan_not_bootstrap_scaffold(self):
        application = Application.objects.create(
            workspace=self.workspace,
            name="Workbench UI",
            summary="Workbench ui polish",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Improve workbench usability",
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            initial_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions",
                method="post",
                data=json.dumps(
                    {
                        "title": "Initial plan",
                        "request_text": "Create a personal knowledgebase application that tracks notes and searchable information.",
                    }
                ),
            )
            initial_response = application_solution_change_sessions_collection(initial_request, str(application.id))
            self.assertEqual(initial_response.status_code, 201)

            targeted_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions",
                method="post",
                data=json.dumps(
                    {
                        "title": "Header selector width",
                        "request_text": "Narrow the workspace selector width and align it to the right of the logo in the header.",
                    }
                ),
            )
            targeted_response = application_solution_change_sessions_collection(targeted_request, str(application.id))
        self.assertEqual(targeted_response.status_code, 201)
        targeted_payload = json.loads(targeted_response.content)
        session = (targeted_payload.get("session") or {})
        planning = (session.get("planning") or {})
        latest_draft = planning.get("latest_draft_plan") or {}
        draft_payload = latest_draft.get("payload") if isinstance(latest_draft.get("payload"), dict) else {}
        self.assertEqual(draft_payload.get("selected_artifact_ids"), [])
        shared_contracts_text = " ".join(str(item) for item in (draft_payload.get("shared_contracts") or [])).lower()
        self.assertNotIn("single-user or multi-user", shared_contracts_text)
        self.assertNotIn("external integrations required in v1", shared_contracts_text)
        validation_plan_text = " ".join(str(item) for item in (draft_payload.get("validation_plan") or [])).lower()
        self.assertIn("ui behavior", validation_plan_text)
        self.assertIn("responsive behavior", validation_plan_text)
        self.assertIn("ui", [str(item) for item in (draft_payload.get("suggested_workstreams") or [])])

    def test_existing_solution_change_session_without_memberships_infers_api_workstream(self):
        application = Application.objects.create(
            workspace=self.workspace,
            name="Service Workspace",
            summary="Service updates",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Improve service behavior",
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            bootstrap_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions",
                method="post",
                data=json.dumps({"title": "Initial plan", "request_text": "Create service workspace baseline."}),
            )
            bootstrap_response = application_solution_change_sessions_collection(bootstrap_request, str(application.id))
            self.assertEqual(bootstrap_response.status_code, 201)

            targeted_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions",
                method="post",
                data=json.dumps(
                    {
                        "title": "API response tuning",
                        "request_text": "Update endpoint request and response validation for service contracts.",
                    }
                ),
            )
            targeted_response = application_solution_change_sessions_collection(targeted_request, str(application.id))
        self.assertEqual(targeted_response.status_code, 201)
        targeted_payload = json.loads(targeted_response.content)
        self.assertEqual(str(((targeted_payload.get("session") or {}).get("analysis") or {}).get("analysis_status") or ""), "suggested_only")
        session_plan = ((targeted_payload.get("session") or {}).get("plan") or {})
        self.assertIn("api", [str(item) for item in (session_plan.get("suggested_workstreams") or [])])
        self.assertEqual(session_plan.get("selected_artifact_ids"), [])

    def test_existing_solution_change_session_without_memberships_infers_data_workstream(self):
        application = Application.objects.create(
            workspace=self.workspace,
            name="Data Workspace",
            summary="Data updates",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Improve storage behavior",
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            bootstrap_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions",
                method="post",
                data=json.dumps({"title": "Initial plan", "request_text": "Create baseline app skeleton."}),
            )
            bootstrap_response = application_solution_change_sessions_collection(bootstrap_request, str(application.id))
            self.assertEqual(bootstrap_response.status_code, 201)

            targeted_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions",
                method="post",
                data=json.dumps(
                    {
                        "title": "Schema persistence update",
                        "request_text": "Adjust model schema and storage persistence rules for note records.",
                    }
                ),
            )
            targeted_response = application_solution_change_sessions_collection(targeted_request, str(application.id))
        self.assertEqual(targeted_response.status_code, 201)
        targeted_payload = json.loads(targeted_response.content)
        session_plan = ((targeted_payload.get("session") or {}).get("plan") or {})
        self.assertIn("data", [str(item) for item in (session_plan.get("suggested_workstreams") or [])])
        self.assertEqual(session_plan.get("selected_artifact_ids"), [])

    def test_existing_solution_change_session_uses_confident_membership_match_and_never_fake_ids(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Workbench UI",
            slug=f"wb-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        api_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Workbench API",
            slug=f"wb-api-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Workbench",
            summary="Workbench improvements",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Improve workspace interactions",
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
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            create_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions",
                method="post",
                data=json.dumps(
                    {
                        "title": "Selector width",
                        "request_text": "UI header selector width tweak",
                    }
                ),
            )
            create_response = application_solution_change_sessions_collection(create_request, str(application.id))
            self.assertEqual(create_response.status_code, 201)
            create_payload = json.loads(create_response.content)
            session_id = str((create_payload.get("session") or {}).get("id") or "")
            session = SolutionChangeSession.objects.get(id=session_id)
            self.assertIsNotNone(
                SolutionPlanningTurn.objects.filter(session=session, actor="planner", kind="question")
                .order_by("-sequence")
                .first()
            )
            reply_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/reply",
                method="post",
                data=json.dumps({"reply_text": "Set default theme to light."}),
            )
            reply_response = application_solution_change_session_reply(reply_request, str(application.id), str(session.id))
        self.assertEqual(reply_response.status_code, 200)
        reply_payload = json.loads(reply_response.content)
        plan = ((reply_payload.get("session") or {}).get("plan") or {})
        selected_ids = [str(item) for item in (plan.get("selected_artifact_ids") or [])]
        self.assertTrue(selected_ids)
        self.assertIn(str(ui_artifact.id), selected_ids)
        self.assertTrue(all(item in {str(ui_artifact.id), str(api_artifact.id)} for item in selected_ids))

    def test_existing_solution_change_session_weak_inference_falls_back_safely(self):
        application = Application.objects.create(
            workspace=self.workspace,
            name="Weak Signal App",
            summary="Weak signal handling",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Improve app",
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            bootstrap_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions",
                method="post",
                data=json.dumps({"title": "Initial plan", "request_text": "Create baseline app skeleton."}),
            )
            bootstrap_response = application_solution_change_sessions_collection(bootstrap_request, str(application.id))
            self.assertEqual(bootstrap_response.status_code, 201)

            targeted_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions",
                method="post",
                data=json.dumps(
                    {
                        "title": "Ambiguous tweak",
                        "request_text": "Please improve the overall experience and quality soon",
                    }
                ),
            )
            targeted_response = application_solution_change_sessions_collection(targeted_request, str(application.id))
        self.assertEqual(targeted_response.status_code, 201)
        targeted_payload = json.loads(targeted_response.content)
        session_plan = ((targeted_payload.get("session") or {}).get("plan") or {})
        self.assertEqual(session_plan.get("selected_artifact_ids"), [])
        self.assertEqual((session_plan.get("suggested_workstreams") or []), [])
        self.assertEqual(str(((targeted_payload.get("session") or {}).get("analysis") or {}).get("analysis_status") or ""), "no_confident_matches")

    def test_solution_change_session_plan_refreshes_analysis_for_ui_width_request(self):
        application = Application.objects.create(
            workspace=self.workspace,
            name="UI Workspace",
            summary="UI updates",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Improve change session ui",
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            bootstrap_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions",
                method="post",
                data=json.dumps({"title": "Initial plan", "request_text": "Create baseline app skeleton."}),
            )
            bootstrap_response = application_solution_change_sessions_collection(bootstrap_request, str(application.id))
            self.assertEqual(bootstrap_response.status_code, 201)

            targeted_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions",
                method="post",
                data=json.dumps(
                    {
                        "title": "Width tweak",
                        "request_text": "The requested change input should use full horizontal pane width.",
                    }
                ),
            )
            targeted_response = application_solution_change_sessions_collection(targeted_request, str(application.id))
            self.assertEqual(targeted_response.status_code, 201)
            session_id = str(((json.loads(targeted_response.content).get("session") or {}).get("id")) or "")
            plan_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session_id}/plan",
                method="post",
                data=json.dumps({}),
            )
            plan_response = application_solution_change_session_plan(plan_request, str(application.id), session_id)
        self.assertEqual(plan_response.status_code, 200)
        payload = json.loads(plan_response.content)
        analysis = ((payload.get("session") or {}).get("analysis") or {})
        self.assertTrue(str(analysis.get("analyzed_at") or "").strip())
        self.assertIn("ui", [str(item) for item in (analysis.get("suggested_workstreams") or [])])

    def test_solution_change_session_plan_does_not_reopen_approved_checkpoint_when_scope_unchanged(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        api_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Xyn API",
            slug=f"xyn-api-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["services/xyn-api/backend/"],
            edit_mode="repo_backed",
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Xyn",
            summary="Platform backend",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Decompose xyn_api.py",
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=api_artifact,
            role="primary_api",
        )
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Decompose API",
            request_text="Decompose services/xyn-api/backend/xyn_orchestrator/xyn_api.py into modules.",
            created_by=self.identity,
            selected_artifact_ids_json=[str(api_artifact.id)],
            plan_json={
                "planning_mode": "decompose_existing_system",
                "plan_kind": "decomposition",
                "selected_artifact_ids": [str(api_artifact.id)],
                "candidate_files": ["services/xyn-api/backend/xyn_orchestrator/xyn_api.py"],
                "extraction_seams": ["solution_change_session_handlers"],
                "implementation_steps": ["Extract handlers into modules."],
            },
        )
        checkpoint = xyn_api._ensure_solution_stage_checkpoint(session=session)
        checkpoint.status = "approved"
        checkpoint.decided_by = self.identity
        checkpoint.decided_at = timezone.now()
        checkpoint.save(update_fields=["status", "decided_by", "decided_at", "updated_at"])

        plan_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/plan",
            method="post",
            data=json.dumps({}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api._record_solution_draft_plan",
            return_value=session.plan_json,
        ):
            plan_response = application_solution_change_session_plan(plan_request, str(application.id), str(session.id))
        self.assertEqual(plan_response.status_code, 200)
        checkpoint.refresh_from_db()
        self.assertEqual(checkpoint.status, "approved")

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

    def test_solution_change_session_refinement_is_incorporated_into_revised_draft_plan(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Knowledgebase UI",
            slug=f"kb-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Knowledgebase",
            summary="Personal knowledgebase app",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Create a personal knowledgebase application",
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
                        "title": "Knowledgebase Initial Plan",
                        "request_text": "Create a personal knowledgebase application for notes, search, tagging, and quick capture workflows.",
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
            options = option_payload.get("options") if isinstance(option_payload.get("options"), list) else []
            self.assertTrue(options)
            option_id = str((options[0] if isinstance(options[0], dict) else {}).get("id") or "")

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

            refinement_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/reply",
                method="post",
                data=json.dumps({"reply_text": "Include rich text editor support in the first iteration."}),
            )
            refinement_response = application_solution_change_session_reply(
                refinement_request,
                str(application.id),
                str(session.id),
            )
            self.assertEqual(refinement_response.status_code, 200)
            refinement_payload = json.loads(refinement_response.content)
            planning = ((refinement_payload.get("session") or {}).get("planning") or {})
            latest_draft = planning.get("latest_draft_plan") or {}
            draft_payload = latest_draft.get("payload") if isinstance(latest_draft.get("payload"), dict) else {}
            merged_text = " ".join(
                [
                    str(draft_payload.get("objective") or ""),
                    " ".join(str(item) for item in (draft_payload.get("shared_contracts") or []) if isinstance(item, str)),
                    " ".join(str(item) for item in (draft_payload.get("validation_plan") or []) if isinstance(item, str)),
                ]
            ).lower()
            self.assertIn("rich text", merged_text)

    def test_solution_change_session_refinement_rewrites_plan_sections_instead_of_echoing_constraints(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Xyn UI",
            slug=f"xyn-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["apps/xyn-ui/"],
            edit_mode="repo_backed",
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Xyn",
            summary="Platform shell",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Fix workspace dropdown header styling",
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=ui_artifact,
            role="primary_ui",
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api.gather_solution_change_code_context",
            return_value={
                "available": True,
                "summary": "Used repo context from xyn-platform (apps/xyn-ui/).",
                "candidate_files": [
                    "apps/xyn-ui/src/app/components/common/WorkspaceContextBar.tsx",
                    "apps/xyn-ui/src/app/components/common/HeaderUtilityMenu.tsx",
                ],
                "candidate_components": ["WorkspaceContextBar", "HeaderUtilityMenu"],
                "confidence": 0.86,
                "needs_clarification": False,
            },
        ):
            create_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions",
                method="post",
                data=json.dumps(
                    {
                        "title": "Header dropdown CSS mismatch",
                        "request_text": "The workspace dropdown in the Xyn UI header does not appear to use the same CSS as the header profile dropdown.",
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
            options = option_payload.get("options") if isinstance(option_payload.get("options"), list) else []
            self.assertTrue(options)
            option_id = str((options[0] if isinstance(options[0], dict) else {}).get("id") or "")

            select_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/select-option",
                method="post",
                data=json.dumps({"source_turn_id": str(option_turn.id), "option_id": option_id}),
            )
            select_response = application_solution_change_session_select_option(select_request, str(application.id), str(session.id))
            self.assertEqual(select_response.status_code, 200)

            plan_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/plan",
                method="post",
                data=json.dumps({}),
            )
            plan_response = application_solution_change_session_plan(plan_request, str(application.id), str(session.id))
            self.assertEqual(plan_response.status_code, 200)
            initial_plan_payload = json.loads(plan_response.content)
            initial_plan = ((initial_plan_payload.get("session") or {}).get("plan") or {})
            initial_proposed_work = [str(item) for item in (initial_plan.get("proposed_work") or [])]
            self.assertTrue(initial_proposed_work)

            refinement_text = (
                "Tighten this draft: keep WorkspaceContextBar.tsx primary, include HeaderUtilityMenu.tsx only if evidence supports it, "
                "remove provider/framework noise, rewrite Proposed Work as concrete implementation steps, and replace Next Action with an actual implementation action."
            )
            with mock.patch(
                "xyn_orchestrator.xyn_api._interpret_solution_refinement",
                return_value={
                    "mode": "agent_fallback",
                    "result_type": "plan_revision",
                    "confidence": 0.91,
                    "normalized_updates": {
                        "constraints_add": [
                            "keep WorkspaceContextBar.tsx primary",
                            "include HeaderUtilityMenu.tsx only if evidence supports it",
                            "remove provider/framework noise",
                            "rewrite Proposed Work as concrete implementation steps",
                            "replace Next Action with an actual implementation action",
                        ]
                    },
                    "planner_message": "Applied requested refinement.",
                    "warnings": [],
                },
            ):
                refinement_request = self._request(
                    f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/reply",
                    method="post",
                    data=json.dumps({"reply_text": refinement_text}),
                )
                refinement_response = application_solution_change_session_reply(
                    refinement_request,
                    str(application.id),
                    str(session.id),
                )
            self.assertEqual(refinement_response.status_code, 200)
            refinement_payload = json.loads(refinement_response.content)
            revised_plan = ((refinement_payload.get("session") or {}).get("plan") or {})

        revised_proposed_work = [str(item) for item in (revised_plan.get("proposed_work") or [])]
        revised_contracts = [str(item) for item in (revised_plan.get("shared_contracts") or [])]
        revised_validation_plan = [str(item) for item in (revised_plan.get("validation_plan") or [])]
        combined_contract_text = " ".join(revised_contracts).lower()
        combined_work_text = " ".join(revised_proposed_work).lower()

        self.assertTrue(revised_proposed_work)
        self.assertNotEqual(revised_proposed_work, initial_proposed_work)
        self.assertTrue(any("workspacecontextbar.tsx" in item.lower() for item in revised_proposed_work))
        self.assertFalse(any("provider" in item.lower() or "framework" in item.lower() for item in revised_contracts))
        self.assertNotIn("rewrite proposed work", combined_contract_text)
        self.assertNotIn("replace next action", combined_contract_text)
        self.assertNotIn("keep workspacecontextbar", combined_contract_text)
        self.assertIn("only if evidence", combined_work_text)
        self.assertTrue(revised_validation_plan)
        self.assertIn("apply the first implementation change", revised_validation_plan[0].lower())
        self.assertIn("workspacecontextbar.tsx", revised_validation_plan[0].lower())
        self.assertIn("workspacecontextbar.tsx", str(revised_plan.get("next_action") or "").lower())

    def test_solution_change_session_initial_code_aware_draft_is_clean_and_actionable(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Xyn UI",
            slug=f"xyn-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["apps/xyn-ui/"],
            edit_mode="repo_backed",
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Xyn",
            summary="Platform shell",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Fix workspace dropdown header overflow",
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=ui_artifact,
            role="primary_ui",
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api.gather_solution_change_code_context",
            return_value={
                "available": True,
                "summary": "Used repo context from xyn-platform (apps/xyn-ui/).",
                "candidate_files": [
                    "apps/xyn-ui/src/app/components/common/WorkspaceContextBar.tsx",
                    "apps/xyn-ui/src/app/components/common/HeaderUtilityMenu.tsx",
                ],
                "candidate_components": ["WorkspaceContextBar", "HeaderUtilityMenu", "ThemeProvider"],
                "confidence": 0.58,
                "needs_clarification": False,
                "evidence": [
                    {
                        "path": "apps/xyn-ui/src/app/components/common/WorkspaceContextBar.tsx",
                        "rationale": "matched terms: header/navigation path, header/navigation export",
                        "score": 8,
                    },
                    {
                        "path": "apps/xyn-ui/src/app/components/common/HeaderUtilityMenu.tsx",
                        "rationale": "matched terms: page-level path penalty, matched terms: dropdown",
                        "score": 3,
                    },
                ],
            },
        ):
            create_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions",
                method="post",
                data=json.dumps(
                    {
                        "title": "Header dropdown width",
                        "request_text": "The Workspaces dropdown in the header is wider than the page.",
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
            options = option_payload.get("options") if isinstance(option_payload.get("options"), list) else []
            self.assertTrue(options)
            option_id = str((options[0] if isinstance(options[0], dict) else {}).get("id") or "")
            select_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/select-option",
                method="post",
                data=json.dumps({"source_turn_id": str(option_turn.id), "option_id": option_id}),
            )
            select_response = application_solution_change_session_select_option(select_request, str(application.id), str(session.id))
            self.assertEqual(select_response.status_code, 200)

            plan_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/plan",
                method="post",
                data=json.dumps({}),
            )
            plan_response = application_solution_change_session_plan(plan_request, str(application.id), str(session.id))
            self.assertEqual(plan_response.status_code, 200)
            plan_payload = json.loads(plan_response.content)
            plan = ((plan_payload.get("session") or {}).get("plan") or {})

        proposed_work = [str(item) for item in (plan.get("proposed_work") or [])]
        self.assertGreaterEqual(len(proposed_work), 3)
        self.assertLessEqual(len(proposed_work), 5)
        self.assertTrue(any("workspacecontextbar.tsx" in item.lower() for item in proposed_work))
        combined_work = " ".join(proposed_work).lower()
        self.assertNotIn("themeprovider", combined_work)
        self.assertNotIn("operationsprovider", combined_work)
        self.assertNotIn("the workspaces dropdown in the header is wider than the page", combined_work)
        self.assertTrue(any("only if implementation evidence" in item.lower() for item in proposed_work))
        next_action = str(plan.get("next_action") or "").strip()
        self.assertTrue(next_action)
        self.assertIn("workspacecontextbar.tsx", next_action.lower())
        validation_plan = [str(item).strip() for item in (plan.get("validation_plan") or []) if str(item).strip()]
        self.assertTrue(validation_plan)
        self.assertEqual(validation_plan[0], next_action)

    def test_solution_change_session_page_specific_initial_draft_has_actionable_next_action(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Xyn UI",
            slug=f"xyn-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["apps/xyn-ui/"],
            edit_mode="repo_backed",
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Xyn",
            summary="Platform shell",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Adjust page-specific workspace form field width",
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
            title="Workspace page input width",
            request_text="Increase field width on the Workspaces page form.",
            created_by=self.identity,
            analysis_json={"impacted_artifacts": [], "suggested_artifact_ids": [str(ui_artifact.id)]},
            selected_artifact_ids_json=[str(ui_artifact.id)],
        )
        plan_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/plan",
            method="post",
            data=json.dumps({}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api.gather_solution_change_code_context",
            return_value={
                "available": True,
                "summary": "Used repo context from xyn-platform (apps/xyn-ui/).",
                "candidate_files": ["apps/xyn-ui/src/app/pages/WorkspacesPage.tsx"],
                "candidate_components": ["WorkspacesPage"],
                "confidence": 0.83,
                "needs_clarification": False,
                "evidence": [
                    {
                        "path": "apps/xyn-ui/src/app/pages/WorkspacesPage.tsx",
                        "rationale": "matched terms: page, workspace, field, width",
                        "score": 8,
                    }
                ],
            },
        ):
            plan_response = application_solution_change_session_plan(plan_request, str(application.id), str(session.id))
        self.assertEqual(plan_response.status_code, 200)
        payload = json.loads(plan_response.content)
        plan = ((payload.get("session") or {}).get("plan") or {})
        proposed_work = [str(item) for item in (plan.get("proposed_work") or [])]
        self.assertTrue(proposed_work)
        self.assertTrue(any("workspacespage.tsx" in item.lower() for item in proposed_work))
        next_action = str(plan.get("next_action") or "").strip()
        self.assertTrue(next_action)
        self.assertIn("workspacespage.tsx", next_action.lower())

    def test_solution_change_session_refinement_resolves_open_questions_without_pasting_raw_notes(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Knowledgebase UI",
            slug=f"kb-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Knowledgebase",
            summary="Personal knowledgebase app",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Create a personal knowledgebase application",
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
                        "title": "Knowledgebase Initial Plan",
                        "request_text": "Create a personal knowledgebase application for notes, search, tagging, and quick capture workflows.",
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
            options = option_payload.get("options") if isinstance(option_payload.get("options"), list) else []
            self.assertTrue(options)
            option_id = str((options[0] if isinstance(options[0], dict) else {}).get("id") or "")
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

            refinement_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/reply",
                method="post",
                data=json.dumps({"reply_text": "No external integrations are required in v1."}),
            )
            refinement_response = application_solution_change_session_reply(
                refinement_request,
                str(application.id),
                str(session.id),
            )
            self.assertEqual(refinement_response.status_code, 200)
            refinement_payload = json.loads(refinement_response.content)
            planning = ((refinement_payload.get("session") or {}).get("planning") or {})
            latest_draft = planning.get("latest_draft_plan") or {}
            draft_payload = latest_draft.get("payload") if isinstance(latest_draft.get("payload"), dict) else {}

            objective_text = str(draft_payload.get("objective") or "").lower()
            self.assertNotIn("no external integrations", objective_text)

            shared_contracts = [
                str(item)
                for item in (draft_payload.get("shared_contracts") or [])
                if isinstance(item, str)
            ]
            unresolved_questions = [entry for entry in shared_contracts if entry.lower().startswith("open question:")]
            unresolved_text = " ".join(unresolved_questions).lower()
            self.assertNotIn("external integrations", unresolved_text)
            self.assertTrue(any("resolved: v1 excludes external integrations" in entry.lower() for entry in shared_contracts))

    def test_solution_change_session_refinement_parses_name_theme_and_features(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Knowledgebase UI",
            slug=f"kb-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Knowledgebase",
            summary="Personal knowledgebase app",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Create a personal knowledgebase application",
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
                        "title": "Knowledgebase Initial Plan",
                        "request_text": "Create a personal knowledgebase application for notes, search, tagging, and quick capture workflows.",
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
            options = option_payload.get("options") if isinstance(option_payload.get("options"), list) else []
            self.assertTrue(options)
            option_id = str((options[0] if isinstance(options[0], dict) else {}).get("id") or "")
            select_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/select-option",
                method="post",
                data=json.dumps({"source_turn_id": str(option_turn.id), "option_id": option_id}),
            )
            select_response = application_solution_change_session_select_option(select_request, str(application.id), str(session.id))
            self.assertEqual(select_response.status_code, 200)

            for reply_text in [
                "Name the application My Knowledge",
                "Set default theme to light",
                "Add offline sync",
            ]:
                refinement_request = self._request(
                    f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/reply",
                    method="post",
                    data=json.dumps({"reply_text": reply_text}),
                )
                refinement_response = application_solution_change_session_reply(
                    refinement_request,
                    str(application.id),
                    str(session.id),
                )
                self.assertEqual(refinement_response.status_code, 200)
                refinement_payload = json.loads(refinement_response.content)

            plan = ((refinement_payload.get("session") or {}).get("plan") or {})
            self.assertEqual(plan.get("title"), "My Knowledge")
            per_artifact = plan.get("per_artifact_work") if isinstance(plan.get("per_artifact_work"), list) else []
            flattened_work = " ".join(
                str(item)
                for row in per_artifact
                if isinstance(row, dict)
                for item in (row.get("planned_work") if isinstance(row.get("planned_work"), list) else [])
            ).lower()
            self.assertIn("set default ui theme to light", flattened_work)
            self.assertIn("add support for offline sync", flattened_work)
            shared_contracts = " ".join(str(item) for item in (plan.get("shared_contracts") or [])).lower()
            self.assertIn("resolved ui default: use light theme", shared_contracts)

    def test_solution_change_session_refinement_unknown_input_is_kept_as_additional_consideration(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Knowledgebase UI",
            slug=f"kb-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Knowledgebase",
            summary="Personal knowledgebase app",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Create a personal knowledgebase application",
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
                        "title": "Knowledgebase Initial Plan",
                        "request_text": "Create a personal knowledgebase application for notes, search, tagging, and quick capture workflows.",
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
            options = option_payload.get("options") if isinstance(option_payload.get("options"), list) else []
            self.assertTrue(options)
            option_id = str((options[0] if isinstance(options[0], dict) else {}).get("id") or "")
            select_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/select-option",
                method="post",
                data=json.dumps({"source_turn_id": str(option_turn.id), "option_id": option_id}),
            )
            select_response = application_solution_change_session_select_option(select_request, str(application.id), str(session.id))
            self.assertEqual(select_response.status_code, 200)

            with mock.patch("xyn_orchestrator.xyn_api.resolve_ai_config", return_value={"provider": "openai", "model_name": "gpt-5-mini", "api_key": "test-key"}):
                with mock.patch(
                    "xyn_orchestrator.xyn_api.invoke_model",
                    return_value={
                        "content": json.dumps(
                            {
                                "mode": "agent_fallback",
                                "result_type": "plan_revision",
                                "confidence": 0.7,
                                "normalized_updates": {
                                    "additional_considerations_add": ["Prioritize delightful onboarding copy tone."],
                                },
                            }
                        )
                    },
                ):
                    refinement_request = self._request(
                        f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/reply",
                        method="post",
                        data=json.dumps({"reply_text": "Prioritize delightful onboarding copy tone."}),
                    )
                    refinement_response = application_solution_change_session_reply(
                        refinement_request,
                        str(application.id),
                        str(session.id),
                    )
                    self.assertEqual(refinement_response.status_code, 200)
            refinement_payload = json.loads(refinement_response.content)
            plan = ((refinement_payload.get("session") or {}).get("plan") or {})
            shared_contracts = [
                str(item)
                for item in (plan.get("shared_contracts") or [])
                if isinstance(item, str)
            ]
            self.assertTrue(
                any("additional consideration: prioritize delightful onboarding copy tone" in entry.lower() for entry in shared_contracts)
            )

    def test_solution_change_session_refinement_no_match_uses_agent_fallback_when_available(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Knowledgebase UI",
            slug=f"kb-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Knowledgebase",
            summary="Personal knowledgebase app",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Create a personal knowledgebase application",
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
                        "title": "Knowledgebase Initial Plan",
                        "request_text": "Create a personal knowledgebase application for notes, search, tagging, and quick capture workflows.",
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
            options = option_payload.get("options") if isinstance(option_payload.get("options"), list) else []
            self.assertTrue(options)
            option_id = str((options[0] if isinstance(options[0], dict) else {}).get("id") or "")
            select_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/select-option",
                method="post",
                data=json.dumps({"source_turn_id": str(option_turn.id), "option_id": option_id}),
            )
            select_response = application_solution_change_session_select_option(select_request, str(application.id), str(session.id))
            self.assertEqual(select_response.status_code, 200)

            with mock.patch("xyn_orchestrator.xyn_api.resolve_ai_config", return_value={"provider": "openai", "model_name": "gpt-5-mini", "api_key": "test-key"}):
                with mock.patch(
                    "xyn_orchestrator.xyn_api.invoke_model",
                    return_value={
                        "content": json.dumps(
                            {
                                "mode": "agent_fallback",
                                "result_type": "plan_revision",
                                "confidence": 0.82,
                                "normalized_updates": {
                                    "name": "My Knowledge",
                                    "ui_preferences": {"theme": "light"},
                                    "features_add": ["offline sync"],
                                    "resolved_answers": [{"question_key": "integration_v1", "value": False}],
                                },
                                "planner_message": "Applied requested planning refinements.",
                                "warnings": [],
                            }
                        )
                    },
                ) as invoke_mock:
                    refinement_request = self._request(
                        f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/reply",
                        method="post",
                        data=json.dumps({"reply_text": "Please make this delightful and practical."}),
                    )
                    refinement_response = application_solution_change_session_reply(
                        refinement_request,
                        str(application.id),
                        str(session.id),
                    )
                    self.assertEqual(refinement_response.status_code, 200)
                    self.assertTrue(invoke_mock.called)

            refinement_payload = json.loads(refinement_response.content)
            plan = ((refinement_payload.get("session") or {}).get("plan") or {})
            self.assertEqual(plan.get("title"), "My Knowledge")
            shared_contracts = " ".join(str(item) for item in (plan.get("shared_contracts") or [])).lower()
            self.assertIn("resolved ui default: use light theme", shared_contracts)
            self.assertNotIn("open question: are external integrations required in v1", shared_contracts)
            per_artifact = plan.get("per_artifact_work") if isinstance(plan.get("per_artifact_work"), list) else []
            flattened_work = " ".join(
                str(item)
                for row in per_artifact
                if isinstance(row, dict)
                for item in (row.get("planned_work") if isinstance(row.get("planned_work"), list) else [])
            ).lower()
            self.assertIn("set default ui theme to light", flattened_work)
            self.assertIn("add support for offline sync", flattened_work)

    def test_solution_change_session_refinement_fallback_accepts_markdown_fenced_json(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Knowledgebase UI",
            slug=f"kb-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Knowledgebase",
            summary="Personal knowledgebase app",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Create a personal knowledgebase application",
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
                        "title": "Knowledgebase Initial Plan",
                        "request_text": "Create a personal knowledgebase application for notes, search, tagging, and quick capture workflows.",
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
            options = option_payload.get("options") if isinstance(option_payload.get("options"), list) else []
            self.assertTrue(options)
            option_id = str((options[0] if isinstance(options[0], dict) else {}).get("id") or "")
            select_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/select-option",
                method="post",
                data=json.dumps({"source_turn_id": str(option_turn.id), "option_id": option_id}),
            )
            select_response = application_solution_change_session_select_option(select_request, str(application.id), str(session.id))
            self.assertEqual(select_response.status_code, 200)

            fenced_payload = "```json\n" + json.dumps(
                {
                    "mode": "agent_fallback",
                    "result_type": "plan_revision",
                    "confidence": 0.9,
                    "normalized_updates": {
                        "ui_preferences": {"theme": "light"},
                        "resolved_answers": [{"question_key": "ui_theme", "value": "light"}],
                    },
                    "warnings": [],
                }
            ) + "\n```"
            with mock.patch("xyn_orchestrator.xyn_api.resolve_ai_config", return_value={"provider": "openai", "model_name": "gpt-5-mini", "api_key": "test-key"}):
                with mock.patch("xyn_orchestrator.xyn_api.invoke_model", return_value={"content": fenced_payload}):
                    refinement_request = self._request(
                        f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/reply",
                        method="post",
                        data=json.dumps({"reply_text": "use light theme as the default"}),
                    )
                    refinement_response = application_solution_change_session_reply(
                        refinement_request,
                        str(application.id),
                        str(session.id),
                    )
                    self.assertEqual(refinement_response.status_code, 200)

            refinement_payload = json.loads(refinement_response.content)
            plan = ((refinement_payload.get("session") or {}).get("plan") or {})
            shared_contracts = " ".join(str(item) for item in (plan.get("shared_contracts") or [])).lower()
            self.assertIn("resolved ui default: use light theme", shared_contracts)

    def test_solution_change_session_refinement_fallback_extracts_json_with_surrounding_prose(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Knowledgebase UI",
            slug=f"kb-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Knowledgebase",
            summary="Personal knowledgebase app",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Create a personal knowledgebase application",
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
                        "title": "Knowledgebase Initial Plan",
                        "request_text": "Create a personal knowledgebase application for notes, search, tagging, and quick capture workflows.",
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
            options = option_payload.get("options") if isinstance(option_payload.get("options"), list) else []
            self.assertTrue(options)
            option_id = str((options[0] if isinstance(options[0], dict) else {}).get("id") or "")
            select_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/select-option",
                method="post",
                data=json.dumps({"source_turn_id": str(option_turn.id), "option_id": option_id}),
            )
            select_response = application_solution_change_session_select_option(select_request, str(application.id), str(session.id))
            self.assertEqual(select_response.status_code, 200)

            noisy_payload = (
                "Here is the interpretation result:\n"
                + json.dumps(
                    {
                        "mode": "agent_fallback",
                        "result_type": "plan_revision",
                        "confidence": 0.88,
                        "normalized_updates": {"features_add": ["rich text editor"]},
                        "warnings": [],
                    }
                )
                + "\nApplied."
            )
            with mock.patch("xyn_orchestrator.xyn_api.resolve_ai_config", return_value={"provider": "openai", "model_name": "gpt-5-mini", "api_key": "test-key"}):
                with mock.patch("xyn_orchestrator.xyn_api.invoke_model", return_value={"content": noisy_payload}):
                    refinement_request = self._request(
                        f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/reply",
                        method="post",
                        data=json.dumps({"reply_text": "add rich text editor support"}),
                    )
                    refinement_response = application_solution_change_session_reply(
                        refinement_request,
                        str(application.id),
                        str(session.id),
                    )
                    self.assertEqual(refinement_response.status_code, 200)

            refinement_payload = json.loads(refinement_response.content)
            plan = ((refinement_payload.get("session") or {}).get("plan") or {})
            per_artifact = plan.get("per_artifact_work") if isinstance(plan.get("per_artifact_work"), list) else []
            flattened_work = " ".join(
                str(item)
                for row in per_artifact
                if isinstance(row, dict)
                for item in (row.get("planned_work") if isinstance(row.get("planned_work"), list) else [])
            ).lower()
            self.assertIn("rich text", flattened_work)

    def test_solution_change_session_refinement_invalid_fallback_payload_becomes_cannot_interpret(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Knowledgebase UI",
            slug=f"kb-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Knowledgebase",
            summary="Personal knowledgebase app",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Create a personal knowledgebase application",
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
                        "title": "Knowledgebase Initial Plan",
                        "request_text": "Create a personal knowledgebase application for notes, search, tagging, and quick capture workflows.",
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
            options = option_payload.get("options") if isinstance(option_payload.get("options"), list) else []
            self.assertTrue(options)
            option_id = str((options[0] if isinstance(options[0], dict) else {}).get("id") or "")
            select_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/select-option",
                method="post",
                data=json.dumps({"source_turn_id": str(option_turn.id), "option_id": option_id}),
            )
            select_response = application_solution_change_session_select_option(select_request, str(application.id), str(session.id))
            self.assertEqual(select_response.status_code, 200)

            with mock.patch("xyn_orchestrator.xyn_api.resolve_ai_config", return_value={"provider": "openai", "model_name": "gpt-5-mini", "api_key": "test-key"}):
                with mock.patch(
                    "xyn_orchestrator.xyn_api.invoke_model",
                    return_value={
                        "content": json.dumps(
                            {
                                "mode": "agent_fallback",
                                "result_type": "plan_revision",
                                "confidence": 0.9,
                                "workspace_id": "evil-mutation",
                                "normalized_updates": {"name": "Should Be Rejected"},
                            }
                        )
                    },
                ):
                    refinement_request = self._request(
                        f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/reply",
                        method="post",
                        data=json.dumps({"reply_text": "Please improve onboarding delight."}),
                    )
                    refinement_response = application_solution_change_session_reply(
                        refinement_request,
                        str(application.id),
                        str(session.id),
                    )
                    self.assertEqual(refinement_response.status_code, 200)

            refinement_payload = json.loads(refinement_response.content)
            planning = ((refinement_payload.get("session") or {}).get("planning") or {})
            pending_question = planning.get("pending_question") or {}
            self.assertTrue(pending_question)
            pending_question_payload = pending_question.get("payload") if isinstance(pending_question.get("payload"), dict) else {}
            interpretation = pending_question_payload.get("interpretation") if isinstance(pending_question_payload.get("interpretation"), dict) else {}
            self.assertEqual(interpretation.get("result_type"), "cannot_interpret")
            warnings_text = " ".join(str(item) for item in (interpretation.get("warnings") or [])).lower()
            self.assertIn("unknown top-level keys", warnings_text)
            self.assertNotIn("invalid json", str(interpretation.get("planner_message") or "").lower())
            planner_question_text = str((pending_question_payload.get("question") or "")).lower()
            self.assertIn("could not safely interpret", planner_question_text)

    def test_solution_change_session_refinement_malformed_fallback_output_becomes_cannot_interpret(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Knowledgebase UI",
            slug=f"kb-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Knowledgebase",
            summary="Personal knowledgebase app",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Create a personal knowledgebase application",
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
                        "title": "Knowledgebase Initial Plan",
                        "request_text": "Create a personal knowledgebase application for notes, search, tagging, and quick capture workflows.",
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
            options = option_payload.get("options") if isinstance(option_payload.get("options"), list) else []
            self.assertTrue(options)
            option_id = str((options[0] if isinstance(options[0], dict) else {}).get("id") or "")
            select_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/select-option",
                method="post",
                data=json.dumps({"source_turn_id": str(option_turn.id), "option_id": option_id}),
            )
            select_response = application_solution_change_session_select_option(select_request, str(application.id), str(session.id))
            self.assertEqual(select_response.status_code, 200)

            with mock.patch("xyn_orchestrator.xyn_api.resolve_ai_config", return_value={"provider": "openai", "model_name": "gpt-5-mini", "api_key": "test-key"}):
                with mock.patch("xyn_orchestrator.xyn_api.invoke_model", return_value={"content": "not-json-response"}):
                    refinement_request = self._request(
                        f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/reply",
                        method="post",
                        data=json.dumps({"reply_text": "use light theme as the default", "use_planner_interpretation": True}),
                    )
                    refinement_response = application_solution_change_session_reply(
                        refinement_request,
                        str(application.id),
                        str(session.id),
                    )
                    self.assertEqual(refinement_response.status_code, 200)

            refinement_payload = json.loads(refinement_response.content)
            planning = ((refinement_payload.get("session") or {}).get("planning") or {})
            pending_question = planning.get("pending_question") or {}
            self.assertTrue(pending_question)
            pending_question_payload = pending_question.get("payload") if isinstance(pending_question.get("payload"), dict) else {}
            interpretation = pending_question_payload.get("interpretation") if isinstance(pending_question_payload.get("interpretation"), dict) else {}
            self.assertEqual(interpretation.get("result_type"), "cannot_interpret")
            self.assertNotIn("invalid json", str(interpretation.get("planner_message") or "").lower())

    def test_solution_change_session_refinement_explicit_override_forces_fallback(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Knowledgebase UI",
            slug=f"kb-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Knowledgebase",
            summary="Personal knowledgebase app",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Create a personal knowledgebase application",
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
                        "title": "Knowledgebase Initial Plan",
                        "request_text": "Create a personal knowledgebase application for notes, search, tagging, and quick capture workflows.",
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
            options = option_payload.get("options") if isinstance(option_payload.get("options"), list) else []
            self.assertTrue(options)
            option_id = str((options[0] if isinstance(options[0], dict) else {}).get("id") or "")
            select_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/select-option",
                method="post",
                data=json.dumps({"source_turn_id": str(option_turn.id), "option_id": option_id}),
            )
            select_response = application_solution_change_session_select_option(select_request, str(application.id), str(session.id))
            self.assertEqual(select_response.status_code, 200)

            with mock.patch("xyn_orchestrator.xyn_api.resolve_ai_config", return_value={"provider": "openai", "model_name": "gpt-5-mini", "api_key": "test-key"}):
                with mock.patch(
                    "xyn_orchestrator.xyn_api.invoke_model",
                    return_value={
                        "content": json.dumps(
                            {
                                "mode": "agent_fallback",
                                "result_type": "plan_revision",
                                "confidence": 0.88,
                                "normalized_updates": {"ui_preferences": {"theme": "dark"}},
                                "planner_message": "Using planner fallback override.",
                                "warnings": [],
                            }
                        )
                    },
                ) as invoke_mock:
                    refinement_request = self._request(
                        f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/reply",
                        method="post",
                        data=json.dumps(
                            {
                                "reply_text": "Use light theme",
                                "use_planner_interpretation": True,
                            }
                        ),
                    )
                    refinement_response = application_solution_change_session_reply(
                        refinement_request,
                        str(application.id),
                        str(session.id),
                    )
                    self.assertEqual(refinement_response.status_code, 200)
                    self.assertTrue(invoke_mock.called)

            refinement_payload = json.loads(refinement_response.content)
            plan = ((refinement_payload.get("session") or {}).get("plan") or {})
            shared_contracts = " ".join(str(item) for item in (plan.get("shared_contracts") or [])).lower()
            self.assertIn("resolved ui default: use dark theme", shared_contracts)
            self.assertNotIn("resolved ui default: use light theme", shared_contracts)

    def test_deterministic_theme_phrase_does_not_invoke_fallback_unless_forced(self):
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=Application.objects.create(
                workspace=self.workspace,
                name="KB",
                summary="KB",
                source_factory_key="generic_application_mvp",
                requested_by=self.identity,
                status="active",
                plan_fingerprint=f"app-{uuid.uuid4().hex}",
                request_objective="Build KB",
            ),
            title="Theme update",
            request_text="Adjust theme",
            created_by=self.identity,
        )
        with mock.patch("xyn_orchestrator.xyn_api._invoke_planner_refinement_fallback") as fallback_mock:
            result = xyn_api._interpret_solution_refinement(
                session=session,
                reply_text="Use light theme as the default",
                force_planner_fallback=False,
            )
        fallback_mock.assert_not_called()
        self.assertEqual(result.get("mode"), "deterministic")
        self.assertEqual(result.get("result_type"), "answer_resolution")
        self.assertEqual(((result.get("normalized_updates") or {}).get("ui_preferences") or {}).get("theme"), "light")

    def test_fallback_applies_context_pack_content_to_model_request(self):
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=Application.objects.create(
                workspace=self.workspace,
                name="KB",
                summary="KB",
                source_factory_key="generic_application_mvp",
                requested_by=self.identity,
                status="active",
                plan_fingerprint=f"app-{uuid.uuid4().hex}",
                request_objective="Build KB",
            ),
            title="Theme update",
            request_text="Adjust theme",
            created_by=self.identity,
        )
        pack = ContextPack.objects.create(
            name=f"planner-pack-{uuid.uuid4().hex[:6]}",
            purpose="planner",
            scope="global",
            namespace="",
            project_key="",
            version="1.0.0",
            is_active=True,
            is_default=True,
            content_markdown="CONTEXT PACK STRICT JSON CONTRACT",
            applies_to_json={},
        )
        captured = {}

        def _fake_invoke(*, resolved_config, messages):
            captured["system_prompt"] = resolved_config.get("system_prompt")
            captured["messages"] = messages
            return {
                "content": json.dumps(
                    {
                        "mode": "agent_fallback",
                        "result_type": "plan_revision",
                        "confidence": 0.91,
                        "normalized_updates": {"ui_preferences": {"theme": "light"}},
                        "planner_message": "",
                        "warnings": [],
                    }
                )
            }

        with mock.patch(
            "xyn_orchestrator.xyn_api.resolve_ai_config",
            return_value={
                "provider": "openai",
                "model_name": "gpt-5-mini",
                "api_key": "test-key",
                "system_prompt": "BASE SYSTEM",
                "purpose_default_context_pack_refs_json": [{"id": str(pack.id)}],
                "agent_context_pack_refs_json": [],
            },
        ):
            with mock.patch("xyn_orchestrator.xyn_api.invoke_model", side_effect=_fake_invoke):
                result = xyn_api._invoke_planner_refinement_fallback(
                    session=session,
                    reply_text="Use light theme as the default",
                    deterministic={"normalized_updates": {}},
                    force_planner_fallback=True,
                )
        self.assertEqual(result.get("result_type"), "plan_revision")
        self.assertIn("CONTEXT PACK STRICT JSON CONTRACT", str(captured.get("system_prompt") or ""))

    def test_fallback_noncompliant_output_rejected_with_precise_reason(self):
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=Application.objects.create(
                workspace=self.workspace,
                name="KB",
                summary="KB",
                source_factory_key="generic_application_mvp",
                requested_by=self.identity,
                status="active",
                plan_fingerprint=f"app-{uuid.uuid4().hex}",
                request_objective="Build KB",
            ),
            title="Theme update",
            request_text="Adjust theme",
            created_by=self.identity,
        )
        with mock.patch(
            "xyn_orchestrator.xyn_api.resolve_ai_config",
            return_value={"provider": "openai", "model_name": "gpt-5-mini", "api_key": "test-key"},
        ):
            with mock.patch(
                "xyn_orchestrator.xyn_api.invoke_model",
                return_value={"content": '{"mode":"agent_fallback","result_type":"plan_revision","confidence":0.8,"normalized_updates":{},"planner_message":"","warnings":[],"extra":"x"}'},
            ):
                result = xyn_api._invoke_planner_refinement_fallback(
                    session=session,
                    reply_text="Use light theme as the default",
                    deterministic={"normalized_updates": {}},
                    force_planner_fallback=True,
                )
        self.assertEqual(result.get("result_type"), "cannot_interpret")
        self.assertTrue(
            any("unknown top-level keys" in str(item) for item in (result.get("warnings") or [])),
            msg=str(result.get("warnings")),
        )

    def test_forced_fallback_theme_phrase_yields_valid_light_theme_update(self):
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=Application.objects.create(
                workspace=self.workspace,
                name="KB",
                summary="KB",
                source_factory_key="generic_application_mvp",
                requested_by=self.identity,
                status="active",
                plan_fingerprint=f"app-{uuid.uuid4().hex}",
                request_objective="Build KB",
            ),
            title="Theme update",
            request_text="Adjust theme",
            created_by=self.identity,
        )
        with mock.patch(
            "xyn_orchestrator.xyn_api.resolve_ai_config",
            return_value={"provider": "openai", "model_name": "gpt-5-mini", "api_key": "test-key"},
        ):
            with mock.patch(
                "xyn_orchestrator.xyn_api.invoke_model",
                return_value={
                    "content": json.dumps(
                        {
                            "mode": "agent_fallback",
                            "result_type": "plan_revision",
                            "confidence": 0.88,
                            "normalized_updates": {"ui_preferences": {"theme": "light"}},
                            "planner_message": "Applied.",
                            "warnings": [],
                        }
                    )
                },
            ):
                result = xyn_api._interpret_solution_refinement(
                    session=session,
                    reply_text="Use light theme as the default",
                    force_planner_fallback=True,
                )
        self.assertEqual(result.get("mode"), "agent_fallback")
        self.assertEqual(result.get("result_type"), "plan_revision")
        self.assertEqual(((result.get("normalized_updates") or {}).get("ui_preferences") or {}).get("theme"), "light")

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

    def test_solution_change_session_simple_ui_change_has_no_default_shared_contracts_or_open_questions(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Xyn UI",
            slug=f"xyn-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Xyn",
            summary="Platform shell",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Refine solution detail layout",
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
            title="Resize field",
            request_text="Resize the requested change input field to use the full panel width.",
            created_by=self.identity,
            analysis_json={"impacted_artifacts": [], "suggested_artifact_ids": [str(ui_artifact.id)]},
            selected_artifact_ids_json=[str(ui_artifact.id)],
        )
        plan_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/plan",
            method="post",
            data=json.dumps({}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            plan_response = application_solution_change_session_plan(plan_request, str(application.id), str(session.id))
        self.assertEqual(plan_response.status_code, 200)
        payload = json.loads(plan_response.content)
        plan = ((payload.get("session") or {}).get("plan") or {})
        self.assertEqual(plan.get("shared_contracts"), [])
        self.assertEqual(plan.get("open_questions"), [])

    def test_solution_change_session_multi_artifact_api_ui_change_adds_only_relevant_shared_contracts(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Xyn UI",
            slug=f"xyn-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        api_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Xyn API",
            slug=f"xyn-api-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Xyn",
            summary="Platform shell",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Coordinate UI + API update",
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
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Campaign contract update",
            request_text="Update campaign UI and API payload schema; keep request/response contracts backward compatible.",
            created_by=self.identity,
            analysis_json={
                "impacted_artifacts": [],
                "suggested_artifact_ids": [str(ui_artifact.id), str(api_artifact.id)],
                "suggested_workstreams": ["ui", "api"],
            },
            selected_artifact_ids_json=[str(ui_artifact.id), str(api_artifact.id)],
        )
        plan_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/plan",
            method="post",
            data=json.dumps({}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            plan_response = application_solution_change_session_plan(plan_request, str(application.id), str(session.id))
        self.assertEqual(plan_response.status_code, 200)
        payload = json.loads(plan_response.content)
        plan = ((payload.get("session") or {}).get("plan") or {})
        shared_contracts = [str(item) for item in (plan.get("shared_contracts") or []) if str(item).strip()]
        self.assertIn("Maintain backward-compatible API contracts across selected artifacts.", shared_contracts)
        self.assertIn(
            "Validate payload/data-shape compatibility where selected artifacts exchange runtime data.",
            shared_contracts,
        )
        self.assertFalse(any("generated surface/action metadata" in item.lower() for item in shared_contracts))
        self.assertEqual(plan.get("open_questions"), [])

    def test_solution_change_session_ui_implementation_request_triggers_code_aware_planning(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Xyn UI",
            slug=f"xyn-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["apps/xyn-ui/"],
            edit_mode="repo_backed",
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Xyn",
            summary="Platform shell",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Refine solution detail layout",
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
            title="Resize field",
            request_text="The input box for the Solution detail requested change field is too small and should use full panel width.",
            created_by=self.identity,
            analysis_json={"impacted_artifacts": [], "suggested_artifact_ids": [str(ui_artifact.id)]},
            selected_artifact_ids_json=[str(ui_artifact.id)],
        )
        plan_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/plan",
            method="post",
            data=json.dumps({}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api.gather_solution_change_code_context",
            return_value={
                "available": True,
                "summary": "Used repo context from xyn-ui.",
                "candidate_files": [
                    "apps/xyn-ui/src/app/components/console/SolutionPanels.tsx",
                    "apps/xyn-ui/src/app/components/console/SolutionPanels.css",
                ],
                "candidate_components": ["SolutionPanels"],
            },
        ):
            plan_response = application_solution_change_session_plan(plan_request, str(application.id), str(session.id))
        self.assertEqual(plan_response.status_code, 200)
        payload = json.loads(plan_response.content)
        plan = ((payload.get("session") or {}).get("plan") or {})
        self.assertEqual(plan.get("planning_mode"), "code_aware")
        self.assertTrue((plan.get("candidate_files") or [])[0].startswith("apps/xyn-ui/"))
        self.assertTrue(any("SolutionPanels" in str(item) for item in (plan.get("candidate_components") or [])))
        proposed_work = [str(item) for item in (plan.get("proposed_work") or [])]
        self.assertTrue(any("Inspect `apps/xyn-ui/src/app/components/console/SolutionPanels.tsx`" in item for item in proposed_work))
        self.assertFalse(any(re.search(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", item, re.I) for item in proposed_work))
        self.assertEqual(plan.get("shared_contracts"), [])
        latest_draft = (((payload.get("session") or {}).get("planning") or {}).get("latest_draft_plan") or {}).get("payload") or {}
        self.assertEqual(latest_draft.get("planning_mode"), "code_aware")
        self.assertEqual(latest_draft.get("proposed_work"), proposed_work)

    def test_solution_change_session_non_implementation_request_remains_deterministic(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Xyn UI",
            slug=f"xyn-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["apps/xyn-ui/"],
            edit_mode="repo_backed",
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Xyn",
            summary="Platform shell",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Improve planning workflow",
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
            title="Planning process clarity",
            request_text="Improve the planning process clarity and keep workflow guidance concise.",
            created_by=self.identity,
            analysis_json={"impacted_artifacts": [], "suggested_artifact_ids": [str(ui_artifact.id)]},
            selected_artifact_ids_json=[str(ui_artifact.id)],
        )
        plan_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/plan",
            method="post",
            data=json.dumps({}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api.gather_solution_change_code_context"
        ) as gather_mock:
            plan_response = application_solution_change_session_plan(plan_request, str(application.id), str(session.id))
        self.assertEqual(plan_response.status_code, 200)
        payload = json.loads(plan_response.content)
        plan = ((payload.get("session") or {}).get("plan") or {})
        self.assertEqual(plan.get("planning_mode"), "deterministic")
        self.assertEqual(plan.get("candidate_files"), [])
        gather_mock.assert_not_called()

    def test_solution_change_session_dropdown_css_request_triggers_code_aware_planning(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Xyn UI",
            slug=f"xyn-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["apps/xyn-ui/"],
            edit_mode="repo_backed",
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Xyn",
            summary="Platform shell",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Align header dropdown CSS",
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=ui_artifact,
            role="primary_ui",
        )
        request_text = "The workspace dropdown in the Xyn UI header does not appear to use the same CSS as the header profile dropdown."
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Header dropdown CSS mismatch",
            request_text=request_text,
            created_by=self.identity,
            analysis_json={"impacted_artifacts": [], "suggested_artifact_ids": [str(ui_artifact.id)]},
            selected_artifact_ids_json=[str(ui_artifact.id)],
        )
        plan_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/plan",
            method="post",
            data=json.dumps({}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api.gather_solution_change_code_context",
            return_value={
                "available": True,
                "summary": "Used repo context from xyn-ui.",
                "candidate_files": [
                    "apps/xyn-ui/src/app/components/common/HeaderUtilityMenu.tsx",
                    "apps/xyn-ui/src/styles/base.css",
                ],
                "candidate_components": ["HeaderUtilityMenu"],
            },
        ):
            plan_response = application_solution_change_session_plan(plan_request, str(application.id), str(session.id))
        self.assertEqual(plan_response.status_code, 200)
        payload = json.loads(plan_response.content)
        plan = ((payload.get("session") or {}).get("plan") or {})
        self.assertEqual(plan.get("planning_mode"), "code_aware")
        proposed_work = [str(item) for item in (plan.get("proposed_work") or [])]
        self.assertTrue(proposed_work)
        self.assertFalse(any(re.search(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", item, re.I) for item in proposed_work))
        self.assertTrue(any("HeaderUtilityMenu" in item or "header" in item.lower() for item in proposed_work))

    def test_solution_change_session_explicit_ui_request_still_generates_ui_oriented_steps(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Xyn UI",
            slug=f"xyn-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["apps/xyn-ui/"],
            edit_mode="repo_backed",
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Xyn",
            summary="Platform shell",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Fix header utility menu layout",
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
            title="Header layout fix",
            request_text=(
                "Fix apps/xyn-ui/src/app/components/common/HeaderUtilityMenu.tsx layout and width behavior "
                "for the workspace dropdown in the header."
            ),
            created_by=self.identity,
            analysis_json={"impacted_artifacts": [], "suggested_artifact_ids": [str(ui_artifact.id)]},
            selected_artifact_ids_json=[str(ui_artifact.id)],
        )
        plan_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/plan",
            method="post",
            data=json.dumps({}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api.gather_solution_change_code_context",
            return_value={
                "available": True,
                "summary": "Used repo context from xyn-ui.",
                "candidate_files": ["apps/xyn-ui/src/app/components/common/HeaderUtilityMenu.tsx"],
                "candidate_components": ["HeaderUtilityMenu"],
            },
        ):
            plan_response = application_solution_change_session_plan(plan_request, str(application.id), str(session.id))
        self.assertEqual(plan_response.status_code, 200)
        payload = json.loads(plan_response.content)
        plan = ((payload.get("session") or {}).get("plan") or {})
        proposed_work = " ".join(str(item) for item in (plan.get("proposed_work") or [])).lower()
        self.assertIn("width", proposed_work)
        self.assertTrue(any(token in proposed_work for token in ("header", "layout", "styling")))

    def test_solution_change_plan_guardrail_rewrites_conflicting_ui_steps_when_ui_forbidden(self):
        request_text = (
            "STRICT REFACTOR: extract into modules only. "
            "DO NOT modify UI, styling, or layout. "
            "Preserve behavior and do not introduce new features."
        )
        base_plan = {
            "implementation_steps": [
                "Update header layout width and anchoring in the navigation shell.",
                "Extract solution-change-session workflow into backend modules and keep delegation wrappers.",
            ],
            "proposed_work": [
                "Apply styling and max-width updates to header navigation controls.",
                "Extract backend workflow handlers into focused modules.",
            ],
            "validation_plan": [
                "Validate header layout and styling behavior in navigation.",
                "Run regression checks for solution-change-session request/response behavior.",
            ],
            "next_action": "Adjust header layout and styling constraints first.",
        }
        rewritten = xyn_api._apply_plan_prohibition_guardrails(plan=base_plan, request_text=request_text)
        self.assertTrue(isinstance(rewritten, dict))
        rendered = " ".join(
            [
                *[str(item) for item in (rewritten.get("implementation_steps") or [])],
                *[str(item) for item in (rewritten.get("proposed_work") or [])],
                *[str(item) for item in (rewritten.get("validation_plan") or [])],
                str(rewritten.get("next_action") or ""),
            ]
        ).lower()
        for forbidden in ("width", "min-width", "max-width", "anchoring", "header", "navigation", "layout", "styling"):
            self.assertNotIn(forbidden, rendered)
        self.assertIn("extract", rendered)
        annotations = [str(item) for item in (rewritten.get("guardrail_annotations") or []) if str(item).strip()]
        self.assertTrue(annotations)
        self.assertTrue(any("guardrail enforcement" in item.lower() for item in annotations))

    def test_solution_change_session_structural_fallback_triggers_when_classifier_misses_ui_request(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Xyn UI",
            slug=f"xyn-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["apps/xyn-ui/"],
            edit_mode="repo_backed",
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Xyn",
            summary="Platform shell",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="UI visual consistency",
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
            title="Visual consistency",
            request_text="Make this control look consistent with the profile control in the top chrome.",
            created_by=self.identity,
            analysis_json={"impacted_artifacts": [], "suggested_artifact_ids": [str(ui_artifact.id)]},
            selected_artifact_ids_json=[str(ui_artifact.id)],
        )
        plan_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/plan",
            method="post",
            data=json.dumps({}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), \
            mock.patch("xyn_orchestrator.xyn_api._request_appears_implementation_specific", return_value=False), \
            mock.patch("xyn_orchestrator.xyn_api._request_appears_ui_implementation_specific", return_value=True), \
            mock.patch(
                "xyn_orchestrator.xyn_api.gather_solution_change_code_context",
                return_value={
                    "available": True,
                    "summary": "Used repo context from xyn-ui.",
                    "candidate_files": ["apps/xyn-ui/src/app/components/common/HeaderUtilityMenu.tsx"],
                    "candidate_components": ["HeaderUtilityMenu"],
                },
            ) as gather_mock:
            plan_response = application_solution_change_session_plan(plan_request, str(application.id), str(session.id))
        self.assertEqual(plan_response.status_code, 200)
        payload = json.loads(plan_response.content)
        plan = ((payload.get("session") or {}).get("plan") or {})
        self.assertEqual(plan.get("planning_mode"), "code_aware")
        self.assertTrue(plan.get("proposed_work"))
        gather_mock.assert_called_once()

    def test_solution_change_session_strict_backend_refactor_plan_avoids_ui_layout_language(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        api_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="xyn-api",
            slug=f"xyn-api-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["services/xyn-api/backend/"],
            edit_mode="repo_backed",
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Xyn",
            summary="Platform backend",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Decompose change-session workflow handlers",
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=api_artifact,
            role="primary_api",
        )
        request_text = (
            "STRICT REFACTOR: Decompose xyn_orchestrator/xyn_api.py into smaller modules by extracting "
            "solution-change-session workflow logic only. DO NOT modify UI, styling, layout, or behavior. "
            "DO NOT introduce new features. Only move existing logic into new modules and replace with delegation "
            "wrappers. Maintain identical request/response behavior."
        )
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Strict backend refactor plan",
            request_text=request_text,
            created_by=self.identity,
            analysis_json={"impacted_artifacts": [], "suggested_artifact_ids": [str(api_artifact.id)]},
            selected_artifact_ids_json=[str(api_artifact.id)],
        )
        plan_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/plan",
            method="post",
            data=json.dumps({}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api.gather_solution_change_code_context",
            return_value={
                "available": True,
                "summary": "Used repo context from xyn-platform backend.",
                "candidate_files": [
                    "services/xyn-api/backend/xyn_orchestrator/xyn_api.py",
                    "services/xyn-api/backend/xyn_orchestrator/change_sessions.py",
                ],
                "candidate_components": ["SolutionChangeSession"],
            },
        ):
            plan_response = application_solution_change_session_plan(plan_request, str(application.id), str(session.id))
        self.assertEqual(plan_response.status_code, 200)
        payload = json.loads(plan_response.content)
        plan = ((payload.get("session") or {}).get("plan") or {})
        self.assertEqual(plan.get("planning_mode"), "code_aware")
        proposed_work = [str(item) for item in (plan.get("proposed_work") or [])]
        self.assertTrue(proposed_work)
        rendered = " ".join(proposed_work).lower()
        self.assertIn("extract", rendered)
        self.assertIn("delegation wrappers", rendered)
        for forbidden in ("width", "min-width", "max-width", "anchoring", "header", "navigation", "layout", "styling"):
            self.assertNotIn(forbidden, rendered)
        next_action = str(plan.get("next_action") or "").lower()
        for forbidden in ("width", "min-width", "max-width", "anchoring", "header", "navigation", "layout", "styling"):
            self.assertNotIn(forbidden, next_action)
        annotations = [str(item) for item in (plan.get("guardrail_annotations") or []) if str(item).strip()]
        self.assertTrue(annotations)
        self.assertTrue(any("guardrail enforcement" in item.lower() for item in annotations))

    def test_solution_change_session_validation_plan_is_lifecycle_aligned(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Xyn UI",
            slug=f"xyn-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["apps/xyn-ui/"],
            edit_mode="repo_backed",
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Xyn",
            summary="Platform shell",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Improve solution UI",
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
                        "title": "Header layout refinement",
                        "request_text": "Adjust the header control layout to align with profile menu spacing.",
                    }
                ),
            )
            create_response = application_solution_change_sessions_collection(create_request, str(application.id))
            self.assertEqual(create_response.status_code, 201)
            create_payload = json.loads(create_response.content)
            session_id = str((create_payload.get("session") or {}).get("id") or "")
            plan_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session_id}/plan",
                method="post",
                data=json.dumps({}),
            )
            plan_response = application_solution_change_session_plan(plan_request, str(application.id), session_id)
        self.assertEqual(plan_response.status_code, 200)
        payload = json.loads(plan_response.content)
        draft_payload = ((((payload.get("session") or {}).get("planning") or {}).get("latest_draft_plan") or {}).get("payload") or {})
        validation_plan = [str(item) for item in (draft_payload.get("validation_plan") or [])]
        validation_text = " ".join(validation_plan).lower()
        self.assertNotIn("unit tests", validation_text)
        self.assertIn("stage", validation_text)
        self.assertIn("preview", validation_text)
        self.assertIn("validate", validation_text)

    def test_solution_change_session_ui_request_never_returns_uuid_based_proposed_work(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Xyn UI",
            slug=f"xyn-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["apps/xyn-ui/"],
            edit_mode="repo_backed",
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Xyn",
            summary="Platform shell",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Normalize header dropdown CSS",
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=ui_artifact,
            role="primary_ui",
        )
        request_text = "Please make the workspace dropdown CSS match the header profile dropdown styling."
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Dropdown CSS consistency",
            request_text=request_text,
            created_by=self.identity,
            analysis_json={"impacted_artifacts": [], "suggested_artifact_ids": [str(ui_artifact.id)]},
            selected_artifact_ids_json=[str(ui_artifact.id)],
        )
        plan_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/plan",
            method="post",
            data=json.dumps({}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api.gather_solution_change_code_context",
            return_value={
                "available": True,
                "summary": "Used repo context from xyn-ui.",
                "candidate_files": ["apps/xyn-ui/src/app/components/common/HeaderUtilityMenu.tsx"],
                "candidate_components": ["HeaderUtilityMenu"],
            },
        ):
            plan_response = application_solution_change_session_plan(plan_request, str(application.id), str(session.id))
        self.assertEqual(plan_response.status_code, 200)
        payload = json.loads(plan_response.content)
        plan = ((payload.get("session") or {}).get("plan") or {})
        self.assertEqual(plan.get("planning_mode"), "code_aware")
        proposed_work = [str(item) for item in (plan.get("proposed_work") or [])]
        self.assertTrue(proposed_work)
        self.assertFalse(any(re.search(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", item, re.I) for item in proposed_work))

    def test_code_context_prefers_header_component_paths_for_dropdown_css_requests(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Xyn UI",
            slug=f"xyn-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["apps/xyn-ui/"],
            edit_mode="repo_backed",
        )
        with tempfile.TemporaryDirectory() as temp_repo:
            page_path = os.path.join(temp_repo, "apps/xyn-ui/src/app/pages/WorkspacesPage.tsx")
            header_path = os.path.join(temp_repo, "apps/xyn-ui/src/app/components/common/HeaderUtilityMenu.tsx")
            os.makedirs(os.path.dirname(page_path), exist_ok=True)
            os.makedirs(os.path.dirname(header_path), exist_ok=True)
            with open(page_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "export function WorkspacesPage(){ return <div>workspace dropdown settings page header css</div>; }\n"
                )
            with open(header_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "export const HeaderUtilityMenu = () => <div className='header-dropdown'>workspace dropdown header css</div>;\n"
                )
            with mock.patch("xyn_orchestrator.xyn_api._resolve_local_repo_root", return_value=xyn_api.Path(temp_repo)):
                context = xyn_api.gather_solution_change_code_context(
                    request_text="workspace dropdown in header too wide",
                    artifact=ui_artifact,
                    owner_repo_slug="xyn-platform",
                    allowed_paths=["apps/xyn-ui/"],
                )
        self.assertTrue(context.get("available"))
        candidate_files = [str(item) for item in (context.get("candidate_files") or [])]
        self.assertTrue(candidate_files)
        self.assertIn("components/common", candidate_files[0])
        self.assertFalse(candidate_files[0].endswith("WorkspacesPage.tsx"))

    def test_code_context_marks_low_confidence_when_header_request_only_matches_pages(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Xyn UI",
            slug=f"xyn-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["apps/xyn-ui/"],
            edit_mode="repo_backed",
        )
        with tempfile.TemporaryDirectory() as temp_repo:
            page_path = os.path.join(temp_repo, "apps/xyn-ui/src/app/pages/WorkspacesPage.tsx")
            os.makedirs(os.path.dirname(page_path), exist_ok=True)
            with open(page_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "export function WorkspacesPage(){ return <div>workspace dropdown header css</div>; }\n"
                )
            with mock.patch("xyn_orchestrator.xyn_api._resolve_local_repo_root", return_value=xyn_api.Path(temp_repo)):
                context = xyn_api.gather_solution_change_code_context(
                    request_text="workspace dropdown in header too wide",
                    artifact=ui_artifact,
                    owner_repo_slug="xyn-platform",
                    allowed_paths=["apps/xyn-ui/"],
                )
        self.assertTrue(context.get("available"))
        self.assertTrue(context.get("needs_clarification"))
        self.assertEqual(context.get("candidate_files"), [])
        self.assertIn("header dropdown", str(context.get("clarification_prompt") or "").lower())
        self.assertEqual(len(context.get("clarification_options") or []), 3)

    def test_code_context_component_graph_boosts_shared_owner_for_header_dropdown_requests(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Xyn UI",
            slug=f"xyn-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["apps/xyn-ui/"],
            edit_mode="repo_backed",
        )
        with tempfile.TemporaryDirectory() as temp_repo:
            page_path = os.path.join(temp_repo, "apps/xyn-ui/src/app/pages/WorkspacesPage.tsx")
            shared_owner_path = os.path.join(temp_repo, "apps/xyn-ui/src/app/components/shared/GlobalControls.tsx")
            os.makedirs(os.path.dirname(page_path), exist_ok=True)
            os.makedirs(os.path.dirname(shared_owner_path), exist_ok=True)
            with open(page_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "import { WorkspaceDropdown } from '../components/shared/GlobalControls';\n"
                    "export function WorkspacesPage(){ return <WorkspaceDropdown />; }\n"
                )
            with open(shared_owner_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "export const WorkspaceDropdown = () => <div className='dropdown'>workspace control</div>;\n"
                )
            with mock.patch("xyn_orchestrator.xyn_api._resolve_local_repo_root", return_value=xyn_api.Path(temp_repo)):
                context = xyn_api.gather_solution_change_code_context(
                    request_text="profile dropdown styling in header should match workspace dropdown",
                    artifact=ui_artifact,
                    owner_repo_slug="xyn-platform",
                    allowed_paths=["apps/xyn-ui/"],
                )
        self.assertTrue(context.get("available"))
        candidate_files = [str(item) for item in (context.get("candidate_files") or [])]
        self.assertTrue(candidate_files)
        self.assertTrue(candidate_files[0].endswith("components/shared/GlobalControls.tsx"))
        evidence = context.get("evidence") or []
        self.assertTrue(any("ownership bonus" in str((row or {}).get("rationale") or "").lower() for row in evidence if isinstance(row, dict)))

    def test_code_context_page_specific_request_can_still_target_page_file(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Xyn UI",
            slug=f"xyn-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["apps/xyn-ui/"],
            edit_mode="repo_backed",
        )
        with tempfile.TemporaryDirectory() as temp_repo:
            page_path = os.path.join(temp_repo, "apps/xyn-ui/src/app/pages/WorkspacesPage.tsx")
            header_path = os.path.join(temp_repo, "apps/xyn-ui/src/app/components/common/HeaderUtilityMenu.tsx")
            os.makedirs(os.path.dirname(page_path), exist_ok=True)
            os.makedirs(os.path.dirname(header_path), exist_ok=True)
            with open(page_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "export function WorkspacesPage(){ return <label>Workspace name</label><input className='workspace-field' />; }\n"
                )
            with open(header_path, "w", encoding="utf-8") as handle:
                handle.write("export const HeaderUtilityMenu = () => <div>profile</div>;\n")
            with mock.patch("xyn_orchestrator.xyn_api._resolve_local_repo_root", return_value=xyn_api.Path(temp_repo)):
                context = xyn_api.gather_solution_change_code_context(
                    request_text="Increase field width on the Workspaces page form.",
                    artifact=ui_artifact,
                    owner_repo_slug="xyn-platform",
                    allowed_paths=["apps/xyn-ui/"],
                )
        self.assertTrue(context.get("available"))
        candidate_files = [str(item) for item in (context.get("candidate_files") or [])]
        self.assertTrue(candidate_files)
        self.assertTrue(candidate_files[0].endswith("pages/WorkspacesPage.tsx"))
        self.assertFalse(context.get("needs_clarification"))

    def test_solution_change_plan_includes_meaningful_clarification_when_code_context_low_confidence(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Xyn UI",
            slug=f"xyn-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["apps/xyn-ui/"],
            edit_mode="repo_backed",
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Xyn",
            summary="Platform shell",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Header dropdown CSS consistency",
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
            title="Header dropdown CSS mismatch",
            request_text="workspace dropdown in header too wide",
            created_by=self.identity,
            analysis_json={"impacted_artifacts": [], "suggested_artifact_ids": [str(ui_artifact.id)]},
            selected_artifact_ids_json=[str(ui_artifact.id)],
        )
        plan_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/plan",
            method="post",
            data=json.dumps({}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api.gather_solution_change_code_context",
            return_value={
                "available": True,
                "summary": "Used repo context from xyn-platform (apps/xyn-ui/).",
                "candidate_files": [],
                "candidate_components": [],
                "confidence": 0.32,
                "needs_clarification": True,
                "clarification_prompt": (
                    "I may not have identified the correct component. "
                    "This request refers to a header dropdown, but current matches are page-level files."
                ),
                "clarification_options": [
                    "Search specifically for header/navigation components",
                    "Expand search scope",
                    "Proceed with current candidates",
                ],
                "search_strategy": "focused_header_navigation",
            },
        ):
            plan_response = application_solution_change_session_plan(plan_request, str(application.id), str(session.id))
        self.assertEqual(plan_response.status_code, 200)
        payload = json.loads(plan_response.content)
        plan = ((payload.get("session") or {}).get("plan") or {})
        self.assertEqual(plan.get("planning_mode"), "code_aware")
        self.assertIn("clarify", str(plan.get("next_action") or "").lower())
        self.assertTrue(any("identified the correct component" in str(item).lower() for item in (plan.get("open_questions") or [])))
        self.assertEqual(len(plan.get("clarification_options") or []), 3)

    def test_solution_change_session_code_aware_reports_unavailable_for_non_repo_backed_artifact(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Workbench",
            slug=f"core-workbench-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="",
            owner_path_prefixes_json=[],
            edit_mode="generated",
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Xyn",
            summary="Platform shell",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Refine solution detail layout",
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
            title="Resize field",
            request_text="Resize the requested change input field to use full panel width.",
            created_by=self.identity,
            analysis_json={"impacted_artifacts": [], "suggested_artifact_ids": [str(ui_artifact.id)]},
            selected_artifact_ids_json=[str(ui_artifact.id)],
        )
        plan_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/plan",
            method="post",
            data=json.dumps({}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            plan_response = application_solution_change_session_plan(plan_request, str(application.id), str(session.id))
        self.assertEqual(plan_response.status_code, 200)
        payload = json.loads(plan_response.content)
        plan = ((payload.get("session") or {}).get("plan") or {})
        self.assertEqual(plan.get("planning_mode"), "deterministic")
        self.assertIn("no repository ownership metadata", str(plan.get("code_context_summary") or "").lower())

    def test_solution_change_session_code_context_respects_allowed_paths_for_selected_artifact(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Xyn UI",
            slug=f"xyn-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["apps/xyn-ui/"],
            edit_mode="repo_backed",
        )
        api_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Xyn API",
            slug=f"xyn-api-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["services/xyn-api/backend/"],
            edit_mode="repo_backed",
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Xyn",
            summary="Platform shell",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Refine solution detail layout",
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
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Resize field",
            request_text="Resize the requested change input field to use full panel width.",
            created_by=self.identity,
            analysis_json={"impacted_artifacts": [], "suggested_artifact_ids": [str(ui_artifact.id), str(api_artifact.id)]},
            selected_artifact_ids_json=[str(ui_artifact.id), str(api_artifact.id)],
        )
        plan_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/plan",
            method="post",
            data=json.dumps({"force_code_aware_planning": True}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api.gather_solution_change_code_context",
            return_value={
                "available": True,
                "summary": "Used repo context from xyn-ui.",
                "candidate_files": ["apps/xyn-ui/src/app/components/console/SolutionPanels.tsx"],
                "candidate_components": ["SolutionPanels"],
            },
        ) as gather_mock:
            plan_response = application_solution_change_session_plan(plan_request, str(application.id), str(session.id))
        self.assertEqual(plan_response.status_code, 200)
        self.assertTrue(gather_mock.called)
        kwargs = gather_mock.call_args.kwargs
        self.assertEqual(kwargs.get("owner_repo_slug"), "xyn-platform")
        self.assertEqual(kwargs.get("allowed_paths"), ["apps/xyn-ui/"])

    def test_resolve_local_repo_root_prefers_runtime_repo_map(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mapped_root = os.path.join(tmpdir, "xyn-platform")
            os.makedirs(mapped_root, exist_ok=True)
            runtime_map = json.dumps({"xyn-platform": [mapped_root]})
            with mock.patch.dict("os.environ", {"XYN_RUNTIME_REPO_MAP": runtime_map}, clear=False):
                resolved = xyn_api._resolve_local_repo_root("xyn-platform")
            self.assertIsNotNone(resolved)
            self.assertEqual(str(resolved), str(xyn_api.Path(mapped_root).resolve()))

    def test_solution_change_session_can_persist_confirmed_workstreams(self):
        application = Application.objects.create(
            workspace=self.workspace,
            name="Deal Finder",
            summary="Deal finder app",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Improve session workflow",
        )
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Session 1",
            request_text="Widen solution panel input",
            created_by=self.identity,
            analysis_json={
                "analysis_status": "suggested_only",
                "suggested_workstreams": ["ui", "api"],
                "impacted_artifacts": [],
            },
        )
        patch_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}",
            method="patch",
            data=json.dumps({"confirmed_workstreams": ["ui"]}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            patch_response = application_solution_change_session_detail(
                patch_request,
                str(application.id),
                str(session.id),
            )
        self.assertEqual(patch_response.status_code, 200)
        patch_payload = json.loads(patch_response.content)
        self.assertEqual(patch_payload.get("confirmed_workstreams"), ["ui"])

    def test_confirmed_workstreams_force_targeted_plan_for_first_session_without_memberships(self):
        application = Application.objects.create(
            workspace=self.workspace,
            name="Workbench",
            summary="Workbench updates",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Improve workbench interactions",
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            create_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions",
                method="post",
                data=json.dumps(
                    {
                        "title": "Narrow selector width",
                        "request_text": "Make the workspace selector input use full pane width on this view.",
                    }
                ),
            )
            create_response = application_solution_change_sessions_collection(create_request, str(application.id))
            self.assertEqual(create_response.status_code, 201)
            session = (json.loads(create_response.content).get("session") or {})

            patch_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session.get('id')}",
                method="patch",
                data=json.dumps({"confirmed_workstreams": ["ui"]}),
            )
            patch_response = application_solution_change_session_detail(
                patch_request,
                str(application.id),
                str(session.get("id")),
            )
            self.assertEqual(patch_response.status_code, 200)

            plan_request = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session.get('id')}/plan",
                method="post",
                data=json.dumps({}),
            )
            plan_response = application_solution_change_session_plan(
                plan_request,
                str(application.id),
                str(session.get("id")),
            )
        self.assertEqual(plan_response.status_code, 200)
        plan_payload = json.loads(plan_response.content)
        planning = ((plan_payload.get("session") or {}).get("planning") or {})
        latest_draft = planning.get("latest_draft_plan") or {}
        draft_payload = latest_draft.get("payload") if isinstance(latest_draft.get("payload"), dict) else {}
        self.assertEqual(draft_payload.get("confirmed_workstreams"), ["ui"])
        self.assertIn("ui", [str(item) for item in (draft_payload.get("suggested_workstreams") or [])])
        shared_contracts_text = " ".join(str(item) for item in (draft_payload.get("shared_contracts") or [])).lower()
        self.assertNotIn("single-user or multi-user", shared_contracts_text)
        self.assertNotIn("external integrations", shared_contracts_text)
        validation_text = " ".join(str(item) for item in (draft_payload.get("validation_plan") or [])).lower()
        self.assertIn("ui behavior", validation_text)

    def test_solution_change_session_stage_uses_confirmed_workstreams_when_no_selected_ids(self):
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
            request_objective="Improve session workflow",
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
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Session 1",
            request_text="Make requested change input wider",
            created_by=self.identity,
            analysis_json={"suggested_workstreams": ["ui"], "impacted_artifacts": []},
            metadata_json={"confirmed_workstreams": ["ui"]},
            selected_artifact_ids_json=[],
            plan_json={"per_artifact_work": []},
        )
        SolutionPlanningTurn.objects.create(
            workspace=self.workspace,
            session=session,
            actor="planner",
            kind="draft_plan",
            sequence=1,
            payload_json={"summary": "Draft plan ready"},
            created_by=self.identity,
        )
        SolutionPlanningCheckpoint.objects.create(
            workspace=self.workspace,
            session=session,
            checkpoint_key="plan_scope_confirmed",
            label="Confirm plan scope before stage",
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
            stage_response = application_solution_change_session_stage_apply(
                stage_request,
                str(application.id),
                str(session.id),
            )
        self.assertEqual(stage_response.status_code, 200)
        payload = json.loads(stage_response.content)
        staged = ((payload.get("session") or {}).get("staged_changes") or {})
        staged_ids = [str(item) for item in (staged.get("selected_artifact_ids") or [])]
        self.assertEqual(staged_ids, [str(ui_artifact.id)])

    def test_solution_change_session_delete_allowed_before_execution_starts(self):
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
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Discard me",
            request_text="No longer needed",
            created_by=self.identity,
        )
        delete_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}",
            method="delete",
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            delete_response = application_solution_change_session_detail(delete_request, str(application.id), str(session.id))
        payload = json.loads(delete_response.content)
        self.assertEqual(delete_response.status_code, 200)
        self.assertTrue(payload.get("deleted"))
        self.assertFalse(SolutionChangeSession.objects.filter(id=session.id).exists())

    def test_solution_change_session_delete_blocked_after_execution_progress(self):
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
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Executed session",
            request_text="Already staged",
            created_by=self.identity,
            execution_status="staged",
            staged_changes_json={"artifacts": [{"id": "a1"}]},
        )
        delete_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}",
            method="delete",
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            delete_response = application_solution_change_session_detail(delete_request, str(application.id), str(session.id))
        payload = json.loads(delete_response.content)
        self.assertEqual(delete_response.status_code, 409)
        self.assertEqual(str(payload.get("code") or ""), "DELETE_BLOCKED")
        self.assertTrue(SolutionChangeSession.objects.filter(id=session.id).exists())

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

    def test_solution_change_session_stage_apply_dispatches_dev_task_runtime_for_repo_backed_artifact(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Deal Finder UI",
            slug=f"app.deal-finder-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["apps/xyn-ui/"],
            edit_mode="repo_backed",
        )
        ManagedRepository.objects.create(
            slug="xyn-platform",
            display_name="Xyn Platform",
            remote_url="https://example.com/xyn-platform.git",
            default_branch="develop",
            auth_mode="local",
            is_active=True,
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
            plan_json={
                "proposed_work": ["Update the solution requested-change field to use full panel width."],
                "per_artifact_work": [
                    {
                        "artifact_id": str(ui_artifact.id),
                        "planned_work": ["Update requested-change input layout classes and styles."],
                    }
                ],
            },
        )
        SolutionPlanningTurn.objects.create(
            workspace=self.workspace,
            session=session,
            actor="planner",
            kind="draft_plan",
            sequence=1,
            payload_json={"summary": "Draft plan"},
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
        run_id = str(uuid.uuid4())
        runtime_response = mock.Mock()
        runtime_response.status_code = 200
        runtime_response.headers = {"content-type": "application/json"}
        runtime_response.content = b'{"id": "queued"}'
        runtime_response.json.return_value = {"id": run_id, "status": "queued"}
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api._resolve_stage_apply_target_branch",
            return_value=("main", "runtime_repo_checkout", ""),
        ), mock.patch(
            "xyn_orchestrator.xyn_api._resolve_local_repo_root",
            return_value=tempfile.gettempdir(),
        ), mock.patch(
            "xyn_orchestrator.xyn_api._git_repo_dirty_files",
            return_value=([], ""),
        ), mock.patch(
            "xyn_orchestrator.xyn_api._seed_api_request",
            return_value=runtime_response,
        ) as runtime_request:
            stage_response = application_solution_change_session_stage_apply(stage_request, str(application.id), str(session.id))
        self.assertEqual(stage_response.status_code, 200)
        payload = json.loads(stage_response.content)
        staged_changes = ((payload.get("session") or {}).get("staged_changes") or {})
        execution_summary = staged_changes.get("execution_summary") if isinstance(staged_changes.get("execution_summary"), dict) else {}
        self.assertEqual(int(execution_summary.get("queued_count") or 0), 1)
        execution_runs = staged_changes.get("execution_runs") if isinstance(staged_changes.get("execution_runs"), list) else []
        self.assertEqual(len(execution_runs), 1)
        self.assertEqual(str(execution_runs[0].get("status") or ""), "queued")
        self.assertEqual(str(execution_runs[0].get("target_branch") or ""), "main")
        self.assertEqual(str(execution_runs[0].get("branch_source") or ""), "runtime_repo_checkout")
        self.assertTrue(str(execution_runs[0].get("dev_task_id") or "").strip())
        artifact_states = staged_changes.get("artifact_states") if isinstance(staged_changes.get("artifact_states"), list) else []
        self.assertEqual(str((artifact_states[0] if artifact_states else {}).get("apply_state") or ""), "queued")

        task = DevTask.objects.filter(source_entity_type="solution_change_session", source_entity_id=session.id).first()
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(str(task.target_repo or ""), "xyn-platform")
        self.assertEqual(str(task.target_branch or ""), "main")
        self.assertEqual(str(task.runtime_run_id or ""), run_id)
        self.assertEqual(str(task.runtime_workspace_id or ""), str(self.workspace.id))
        self.assertEqual(str(task.status or ""), "queued")
        self.assertEqual(runtime_request.call_count, 1)

    def test_solution_change_session_stage_apply_does_not_dispatch_when_branch_unresolved(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Deal Finder UI",
            slug=f"app.deal-finder-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["apps/xyn-ui/"],
            edit_mode="repo_backed",
        )
        ManagedRepository.objects.create(
            slug="xyn-platform",
            display_name="Xyn Platform",
            remote_url="https://example.com/xyn-platform.git",
            default_branch="develop",
            auth_mode="local",
            is_active=True,
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
            plan_json={
                "proposed_work": ["Update requested-change field styles."],
                "per_artifact_work": [
                    {
                        "artifact_id": str(ui_artifact.id),
                        "planned_work": ["Update requested-change input layout classes and styles."],
                    }
                ],
            },
        )
        SolutionPlanningTurn.objects.create(
            workspace=self.workspace,
            session=session,
            actor="planner",
            kind="draft_plan",
            sequence=1,
            payload_json={"summary": "Draft plan"},
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
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api._resolve_stage_apply_target_branch",
            return_value=("", "runtime_repo_checkout", "unable to determine checked out branch"),
        ), mock.patch(
            "xyn_orchestrator.xyn_api._seed_api_request",
        ) as runtime_request:
            stage_response = application_solution_change_session_stage_apply(stage_request, str(application.id), str(session.id))
        self.assertEqual(stage_response.status_code, 200)
        payload = json.loads(stage_response.content)
        staged_changes = ((payload.get("session") or {}).get("staged_changes") or {})
        execution_summary = staged_changes.get("execution_summary") if isinstance(staged_changes.get("execution_summary"), dict) else {}
        self.assertEqual(int(execution_summary.get("queued_count") or 0), 0)
        self.assertEqual(int(execution_summary.get("failed_count") or 0), 1)
        execution_runs = staged_changes.get("execution_runs") if isinstance(staged_changes.get("execution_runs"), list) else []
        self.assertEqual(len(execution_runs), 1)
        self.assertEqual(str(execution_runs[0].get("reason") or ""), "target_branch_unresolved")
        self.assertEqual(str(execution_runs[0].get("branch_source") or ""), "runtime_repo_checkout")
        artifact_states = staged_changes.get("artifact_states") if isinstance(staged_changes.get("artifact_states"), list) else []
        self.assertEqual(str((artifact_states[0] if artifact_states else {}).get("apply_state") or ""), "failed")
        self.assertFalse(DevTask.objects.filter(source_entity_type="solution_change_session", source_entity_id=session.id).exists())
        self.assertEqual(runtime_request.call_count, 0)

    def test_solution_change_session_stage_apply_coordinates_multiple_artifacts_per_repo(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Deal Finder UI",
            slug=f"app.deal-finder-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["apps/xyn-ui/"],
            edit_mode="repo_backed",
        )
        api_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Deal Finder API",
            slug=f"app.deal-finder-api-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["services/xyn-api/backend/"],
            edit_mode="repo_backed",
        )
        ManagedRepository.objects.create(
            slug="xyn-platform",
            display_name="Xyn Platform",
            remote_url="https://example.com/xyn-platform.git",
            default_branch="develop",
            auth_mode="local",
            is_active=True,
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
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Cross-artifact session",
            request_text="Adjust shared UI and API behavior",
            created_by=self.identity,
            selected_artifact_ids_json=[str(ui_artifact.id), str(api_artifact.id)],
            status="planned",
            plan_json={
                "proposed_work": ["Apply repo-coordinated changes."],
                "per_artifact_work": [
                    {"artifact_id": str(ui_artifact.id), "planned_work": ["Update UI component behavior."]},
                    {"artifact_id": str(api_artifact.id), "planned_work": ["Update API handler behavior."]},
                ],
            },
        )
        SolutionPlanningTurn.objects.create(
            workspace=self.workspace,
            session=session,
            actor="planner",
            kind="draft_plan",
            sequence=1,
            payload_json={"summary": "Draft plan"},
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
        run_id = str(uuid.uuid4())
        runtime_response = mock.Mock()
        runtime_response.status_code = 200
        runtime_response.headers = {"content-type": "application/json"}
        runtime_response.content = b'{"id": "queued"}'
        runtime_response.json.return_value = {"id": run_id, "status": "queued"}
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api._resolve_stage_apply_target_branch",
            return_value=("main", "runtime_repo_checkout", ""),
        ), mock.patch(
            "xyn_orchestrator.xyn_api._git_repo_dirty_files",
            return_value=([], ""),
        ), mock.patch(
            "xyn_orchestrator.xyn_api._seed_api_request",
            return_value=runtime_response,
        ) as runtime_request:
            stage_response = application_solution_change_session_stage_apply(stage_request, str(application.id), str(session.id))

        self.assertEqual(stage_response.status_code, 200)
        payload = json.loads(stage_response.content)
        staged_changes = ((payload.get("session") or {}).get("staged_changes") or {})
        execution_runs = staged_changes.get("execution_runs") if isinstance(staged_changes.get("execution_runs"), list) else []
        self.assertEqual(len(execution_runs), 2)
        dev_task_ids = {str(item.get("dev_task_id") or "") for item in execution_runs if isinstance(item, dict)}
        self.assertEqual(len(dev_task_ids), 1)
        self.assertEqual(runtime_request.call_count, 1)
        self.assertEqual(DevTask.objects.filter(source_entity_type="solution_change_session", source_entity_id=session.id).count(), 1)
        per_repo_results = staged_changes.get("per_repo_results") if isinstance(staged_changes.get("per_repo_results"), list) else []
        self.assertEqual(len(per_repo_results), 1)
        self.assertEqual(str(per_repo_results[0].get("status") or ""), "queued")
        self.assertEqual(len(per_repo_results[0].get("targeted_artifacts") or []), 2)
        stage_apply_result = payload.get("stage_apply_result") if isinstance(payload.get("stage_apply_result"), dict) else {}
        self.assertEqual(str(stage_apply_result.get("overall_status") or ""), "materialization_queued")
        self.assertTrue(bool(stage_apply_result.get("preview_can_proceed")))

    def test_solution_change_session_stage_apply_blocks_dirty_repo_before_dispatch(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Deal Finder UI",
            slug=f"app.deal-finder-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["apps/xyn-ui/"],
            edit_mode="repo_backed",
        )
        ManagedRepository.objects.create(
            slug="xyn-platform",
            display_name="Xyn Platform",
            remote_url="https://example.com/xyn-platform.git",
            default_branch="develop",
            auth_mode="local",
            is_active=True,
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
            title="Dirty repo guarded session",
            request_text="Update requested change field",
            created_by=self.identity,
            selected_artifact_ids_json=[str(ui_artifact.id)],
            status="planned",
            plan_json={
                "proposed_work": ["Update requested-change field styles."],
                "per_artifact_work": [
                    {
                        "artifact_id": str(ui_artifact.id),
                        "planned_work": ["Update requested-change input layout classes and styles."],
                    }
                ],
            },
        )
        SolutionPlanningTurn.objects.create(
            workspace=self.workspace,
            session=session,
            actor="planner",
            kind="draft_plan",
            sequence=1,
            payload_json={"summary": "Draft plan"},
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
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api._resolve_stage_apply_target_branch",
            return_value=("main", "runtime_repo_checkout", ""),
        ), mock.patch(
            "xyn_orchestrator.xyn_api._resolve_local_repo_root",
            return_value=Path(tempfile.gettempdir()),
        ), mock.patch(
            "xyn_orchestrator.xyn_api._git_repo_dirty_files",
            return_value=(["apps/xyn-ui/src/app/components/solutions/SolutionPanels.tsx"], ""),
        ), mock.patch(
            "xyn_orchestrator.xyn_api._seed_api_request",
        ) as runtime_request:
            stage_response = application_solution_change_session_stage_apply(stage_request, str(application.id), str(session.id))
        self.assertEqual(stage_response.status_code, 200)
        payload = json.loads(stage_response.content)
        staged_changes = ((payload.get("session") or {}).get("staged_changes") or {})
        execution_runs = staged_changes.get("execution_runs") if isinstance(staged_changes.get("execution_runs"), list) else []
        self.assertEqual(len(execution_runs), 1)
        self.assertEqual(str(execution_runs[0].get("reason") or ""), "unsafe_repository_state")
        self.assertFalse(DevTask.objects.filter(source_entity_type="solution_change_session", source_entity_id=session.id).exists())
        self.assertEqual(runtime_request.call_count, 0)
        per_repo_results = staged_changes.get("per_repo_results") if isinstance(staged_changes.get("per_repo_results"), list) else []
        self.assertEqual(len(per_repo_results), 1)
        self.assertEqual(str(per_repo_results[0].get("blocked_reason") or ""), "unsafe_repository_state")
        stage_apply_result = payload.get("stage_apply_result") if isinstance(payload.get("stage_apply_result"), dict) else {}
        self.assertEqual(str(stage_apply_result.get("overall_status") or ""), "failed")
        self.assertFalse(bool(stage_apply_result.get("preview_can_proceed")))

    def test_resolve_stage_apply_target_branch_allows_safe_directory_git_resolution(self):
        completed = mock.Mock(returncode=0, stdout="main\n")
        with mock.patch("xyn_orchestrator.xyn_api._resolve_local_repo_root", return_value=tempfile.gettempdir()), mock.patch(
            "xyn_orchestrator.xyn_api.subprocess.run",
            return_value=completed,
        ) as run_mock:
            branch, branch_source, branch_error = xyn_api._resolve_stage_apply_target_branch(
                repo_slug="xyn-platform",
                fallback_branch="develop",
            )

        self.assertEqual(branch, "main")
        self.assertEqual(branch_source, "runtime_repo_checkout")
        self.assertEqual(branch_error, "")
        self.assertEqual(run_mock.call_count, 1)
        args = run_mock.call_args[0][0]
        self.assertEqual(args[0], "git")
        self.assertEqual(args[1], "-c")
        self.assertTrue(str(args[2]).startswith("safe.directory="))
        self.assertIn("branch", args)

    def test_git_changed_files_for_paths_preserves_filename_case(self):
        repo_root = Path(tempfile.gettempdir())

        def _mock_git_repo_command(*, repo_root: Path, args: List[str], timeout_seconds: int = 20):
            joined = " ".join(args)
            if "diff --name-only" in joined:
                return 0, "apps/xyn-ui/src/app/components/solutions/SolutionPanels.tsx\n", ""
            if "diff --cached --name-only" in joined:
                return 0, "", ""
            if "ls-files --others" in joined:
                return 0, "", ""
            return 1, "", "unsupported"

        with mock.patch("xyn_orchestrator.xyn_api._git_repo_command", side_effect=_mock_git_repo_command):
            changed = xyn_api._git_changed_files_for_paths(
                repo_root=repo_root,
                pathspecs=["apps/xyn-ui/"],
            )

        self.assertEqual(changed, ["apps/xyn-ui/src/app/components/solutions/SolutionPanels.tsx"])

    def test_stage_apply_dispatch_wrapper_delegates_to_solution_workflow_module(self):
        session = mock.sentinel.session
        selected_members = [mock.sentinel.member]
        staged_artifacts = [{"artifact_id": "artifact-1"}]
        planned_work_by_artifact = {"artifact-1": ["step 1"]}
        plan = {"proposed_work": ["step 1"]}
        dispatch_user = mock.sentinel.user
        expected_payload = {"execution_runs": [], "per_repo_results": []}

        with mock.patch(
            "xyn_orchestrator.solution_change_session.stage_apply_workflow.stage_solution_change_dispatch_dev_tasks",
            return_value=expected_payload,
        ) as workflow_mock:
            payload = xyn_api._stage_solution_change_dispatch_dev_tasks(
                session=session,
                selected_members=selected_members,
                staged_artifacts=staged_artifacts,
                planned_work_by_artifact=planned_work_by_artifact,
                plan=plan,
                dispatch_user=dispatch_user,
            )

        self.assertIs(payload, expected_payload)
        self.assertEqual(workflow_mock.call_count, 1)
        kwargs = workflow_mock.call_args.kwargs
        self.assertIs(kwargs.get("session"), session)
        self.assertIs(kwargs.get("resolve_stage_apply_target_branch"), xyn_api._resolve_stage_apply_target_branch)
        self.assertIs(kwargs.get("git_repo_dirty_files"), xyn_api._git_repo_dirty_files)
        self.assertIs(kwargs.get("submit_dev_task_runtime_run"), xyn_api._submit_dev_task_runtime_run)

    def test_stage_apply_session_wrapper_delegates_to_solution_workflow_module(self):
        session = mock.sentinel.session
        memberships = [mock.sentinel.member]
        expected_payload = {"overall_state": "staged"}

        with mock.patch(
            "xyn_orchestrator.solution_change_session.stage_apply_workflow.stage_solution_change_session",
            return_value=expected_payload,
        ) as workflow_mock:
            payload = xyn_api._stage_solution_change_session(
                session=session,
                memberships=memberships,
                dispatch_runtime=True,
                dispatch_user=mock.sentinel.user,
            )

        self.assertIs(payload, expected_payload)
        self.assertEqual(workflow_mock.call_count, 1)
        kwargs = workflow_mock.call_args.kwargs
        self.assertIs(kwargs.get("session"), session)
        self.assertEqual(kwargs.get("memberships"), memberships)
        self.assertIs(kwargs.get("stage_solution_change_dispatch_dev_tasks"), xyn_api._stage_solution_change_dispatch_dev_tasks)

    def test_solution_change_session_continue_requires_iteration_linkage(self):
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
            status="planned",
        )
        continue_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/continue",
            method="post",
            data=json.dumps({"reply_text": "Use light theme as the default"}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = application_solution_change_session_continue(continue_request, str(application.id), str(session.id))
        self.assertEqual(response.status_code, 409)
        self.assertIn("anchored dev sibling context", str(json.loads(response.content).get("error") or ""))

    def test_solution_change_session_continue_records_refinement_against_iteration_linkage(self):
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
            status="planned",
            metadata_json={
                "iteration_linkage": {
                    "runtime_binding_id": str(uuid.uuid4()),
                    "runtime_instance": {"id": str(uuid.uuid4()), "app_slug": ui_artifact.slug.replace("app.", "", 1)},
                    "runtime_target": {"public_app_url": "http://localhost:32900"},
                    "revision_anchor": {"artifact_slug": ui_artifact.slug},
                }
            },
        )
        continue_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/continue",
            method="post",
            data=json.dumps({"reply_text": "Use light theme as the default"}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = application_solution_change_session_continue(continue_request, str(application.id), str(session.id))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertTrue(payload.get("recorded"))
        self.assertTrue(isinstance(payload.get("iteration_context"), dict))
        session.refresh_from_db()
        linkage = (session.metadata_json or {}).get("iteration_linkage") if isinstance(session.metadata_json, dict) else {}
        self.assertTrue(bool(str(linkage.get("continued_at") or "").strip()))
        latest_turn = SolutionPlanningTurn.objects.filter(session=session, actor="user", kind="response").order_by("-sequence").first()
        self.assertIsNotNone(latest_turn)
        latest_payload = latest_turn.payload_json if latest_turn and isinstance(latest_turn.payload_json, dict) else {}
        self.assertEqual(str(latest_payload.get("response_kind") or ""), "continue_refinement")
        self.assertTrue(isinstance(latest_payload.get("iteration_linkage"), dict))

    def test_solution_change_session_finalize_requires_ready_for_promotion_and_archives(self):
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
            status="planned",
            execution_status="preview_ready",
        )
        finalize_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/finalize",
            method="post",
            data=json.dumps({}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            blocked = application_solution_change_session_finalize(finalize_request, str(application.id), str(session.id))
        self.assertEqual(blocked.status_code, 409)
        self.assertIn("execution_status=promoted", str(json.loads(blocked.content).get("error") or ""))

        session.execution_status = "promoted"
        session.save(update_fields=["execution_status", "updated_at"])
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            finalized = application_solution_change_session_finalize(finalize_request, str(application.id), str(session.id))
        self.assertEqual(finalized.status_code, 200)
        payload = json.loads(finalized.content)
        self.assertTrue(payload.get("finalized"))
        session.refresh_from_db()
        self.assertEqual(session.status, "archived")
        finalized_meta = (session.metadata_json or {}).get("finalized") if isinstance(session.metadata_json, dict) else {}
        self.assertEqual(str(finalized_meta.get("by_user_identity_id") or ""), str(self.identity.id))

    def test_solution_change_session_promote_updates_local_runtime_and_records_metadata(self):
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
            app_slug=ui_artifact.slug[4:],
            fqdn=f"{ui_artifact.slug[4:]}.local.test",
            deployment_target="local",
            status="active",
            dns_config_json={
                "runtime_target": {
                    "runtime_owner": "primary",
                    "runtime_base_url": "http://localhost",
                    "public_app_url": "http://localhost",
                    "compose_project": "xyn-local",
                }
            },
        )
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Promote campaign UX update",
            request_text="Promote validated campaign UX",
            created_by=self.identity,
            status="planned",
            execution_status="committed",
        )
        promote_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/promote",
            method="post",
            data=json.dumps({}),
        )
        core_response = mock.Mock()
        core_response.status_code = 200
        core_response.headers = {"content-type": "application/json"}
        core_response.content = b'{"status":"succeeded","deployment_id":"dep-1","compose_project":"xyn-local","ui_url":"http://localhost","api_url":"http://localhost/xyn/api"}'
        core_response.json.return_value = {
            "status": "succeeded",
            "deployment_id": "dep-1",
            "compose_project": "xyn-local",
            "ui_url": "http://localhost",
            "api_url": "http://localhost/xyn/api",
        }
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            with mock.patch("xyn_orchestrator.xyn_api._seed_api_request", return_value=core_response) as mocked_seed:
                promoted = application_solution_change_session_promote(promote_request, str(application.id), str(session.id))
        self.assertEqual(promoted.status_code, 200)
        payload = json.loads(promoted.content)
        self.assertTrue(payload.get("promoted"))
        self.assertFalse(payload.get("already_up_to_date"))
        session_payload = payload.get("session") if isinstance(payload.get("session"), dict) else {}
        eligibility_payload = (
            session_payload.get("promote_eligibility")
            if isinstance(session_payload.get("promote_eligibility"), dict)
            else {}
        )
        self.assertTrue(bool(eligibility_payload.get("can_promote")))
        self.assertTrue(bool(eligibility_payload.get("root_target_present")))
        mocked_seed.assert_called_once()
        session.refresh_from_db()
        promotion_meta = (session.metadata_json or {}).get("promotion") if isinstance(session.metadata_json, dict) else {}
        self.assertEqual(str(promotion_meta.get("result") or ""), "success")
        self.assertEqual(str(promotion_meta.get("promote_mode") or ""), "local_runtime_update")
        self.assertEqual(str(promotion_meta.get("target_runtime") or ""), "xyn-local")

    def test_solution_change_session_promote_is_idempotent_when_already_promoted(self):
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
            app_slug=ui_artifact.slug[4:],
            fqdn=f"{ui_artifact.slug[4:]}.local.test",
            deployment_target="local",
            status="active",
            dns_config_json={
                "runtime_target": {
                    "runtime_owner": "primary",
                    "runtime_base_url": "http://localhost",
                    "public_app_url": "http://localhost",
                    "compose_project": "xyn-local",
                }
            },
        )
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Promote campaign UX update",
            request_text="Promote validated campaign UX",
            created_by=self.identity,
            status="planned",
            execution_status="committed",
            metadata_json={
                "promotion": {
                    "result": "success",
                    "promoted_at": "2026-04-03T10:00:00Z",
                    "promote_mode": "local_runtime_update",
                    "target_runtime": "xyn-local",
                }
            },
        )
        promote_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/promote",
            method="post",
            data=json.dumps({}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            with mock.patch("xyn_orchestrator.xyn_api._seed_api_request") as mocked_seed:
                promoted = application_solution_change_session_promote(promote_request, str(application.id), str(session.id))
        self.assertEqual(promoted.status_code, 200)
        payload = json.loads(promoted.content)
        self.assertTrue(payload.get("promoted"))
        self.assertTrue(payload.get("already_up_to_date"))
        mocked_seed.assert_not_called()

    def test_solution_change_session_promote_blocks_when_root_target_missing(self):
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
            title="Promote campaign UX update",
            request_text="Promote validated campaign UX",
            created_by=self.identity,
            status="planned",
            execution_status="committed",
        )
        promote_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/promote",
            method="post",
            data=json.dumps({}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            with mock.patch("xyn_orchestrator.xyn_api._seed_api_request") as mocked_seed:
                blocked = application_solution_change_session_promote(promote_request, str(application.id), str(session.id))
        self.assertEqual(blocked.status_code, 409)
        payload = json.loads(blocked.content)
        self.assertEqual(str(payload.get("blocked_reason") or ""), "solution_not_installed_in_root")
        eligibility = payload.get("promotion_eligibility") if isinstance(payload.get("promotion_eligibility"), dict) else {}
        self.assertFalse(bool(eligibility.get("can_promote")))
        self.assertFalse(bool(eligibility.get("root_target_present")))
        self.assertIn("install_in_root", list(eligibility.get("next_allowed_actions") or []))
        self.assertEqual(
            SolutionChangeSessionPromotionEvidence.objects.filter(solution_change_session=session).count(),
            0,
        )
        mocked_seed.assert_not_called()

    def test_solution_change_session_promote_creates_durable_evidence_and_returns_reference(self):
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
            app_slug=ui_artifact.slug[4:],
            fqdn=f"{ui_artifact.slug[4:]}.local.test",
            deployment_target="local",
            status="active",
            dns_config_json={
                "runtime_target": {
                    "runtime_owner": "primary",
                    "runtime_base_url": "http://localhost",
                    "public_app_url": "http://localhost",
                    "compose_project": "xyn-local",
                }
            },
        )
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Promote campaign UX update",
            request_text="Promote validated campaign UX",
            created_by=self.identity,
            status="planned",
            execution_status="committed",
            preview_json={"status": "ready", "primary_url": "http://xyn-preview.localhost", "mode": "coordinated_multi_artifact_preview"},
        )
        promote_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/promote",
            method="post",
            data=json.dumps({}),
        )
        core_response = mock.Mock()
        core_response.status_code = 200
        core_response.headers = {"content-type": "application/json"}
        core_response.content = b'{"status":"succeeded","deployment_id":"dep-1","compose_project":"xyn-local","ui_url":"http://localhost","api_url":"http://localhost/xyn/api"}'
        core_response.json.return_value = {
            "status": "succeeded",
            "deployment_id": "dep-1",
            "compose_project": "xyn-local",
            "ui_url": "http://localhost",
            "api_url": "http://localhost/xyn/api",
        }
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            with mock.patch("xyn_orchestrator.xyn_api._seed_api_request", return_value=core_response):
                promoted = application_solution_change_session_promote(promote_request, str(application.id), str(session.id))
        self.assertEqual(promoted.status_code, 200)
        payload = json.loads(promoted.content)
        evidence_ref = payload.get("evidence_ref") if isinstance(payload.get("evidence_ref"), dict) else {}
        evidence_id = str(evidence_ref.get("promotion_evidence_id") or "")
        self.assertTrue(bool(evidence_id))
        evidence = SolutionChangeSessionPromotionEvidence.objects.get(id=evidence_id)
        self.assertEqual(str(evidence.solution_change_session_id), str(session.id))
        self.assertEqual(str(evidence.promotion_status), "success")
        self.assertEqual(str(evidence.actor_source), "human")
        self.assertEqual(str(evidence.actor_identity_id), str(self.identity.id))

    def test_solution_change_session_promotion_evidence_query_returns_session_records(self):
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
            title="Promote campaign UX update",
            request_text="Promote validated campaign UX",
            created_by=self.identity,
            status="planned",
            execution_status="promoted",
        )
        evidence = SolutionChangeSessionPromotionEvidence.objects.create(
            workspace=self.workspace,
            application=application,
            solution_change_session=session,
            operation="promotion",
            promotion_status="success",
            actor_source="human",
            actor_identity=self.identity,
            targeted_artifacts_json=[{"artifact_id": str(ui_artifact.id), "artifact_slug": ui_artifact.slug}],
            preview_target_json={"status": "ready", "primary_url": "http://xyn-preview.localhost"},
            root_target_json={"runtime_owner": "primary", "runtime_base_url": "http://localhost"},
            resulting_active_target_json={"target_runtime": "xyn-local", "ui_url": "http://localhost"},
            control_result_json={"result": "success", "reason": "primary_local_runtime_reprovisioned"},
        )
        request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/promotion-evidence",
            method="get",
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = application_solution_change_session_promotion_evidence(request, str(application.id), str(session.id))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        records = payload.get("evidence") if isinstance(payload.get("evidence"), list) else []
        self.assertEqual(len(records), 1)
        self.assertEqual(str(records[0].get("id") or ""), str(evidence.id))

    def test_solution_change_session_control_includes_latest_promotion_evidence_reference(self):
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
            title="Promoted control",
            request_text="Control status",
            created_by=self.identity,
            status="planned",
            execution_status="promoted",
        )
        evidence = SolutionChangeSessionPromotionEvidence.objects.create(
            workspace=self.workspace,
            application=application,
            solution_change_session=session,
            operation="promotion",
            promotion_status="success",
            actor_source="human",
            actor_identity=self.identity,
            resulting_active_target_json={"target_runtime": "xyn-local"},
            superseded_active_state_json={"runtime_base_url": "http://prior.localhost"},
        )
        request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/control",
            method="get",
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = application_solution_change_session_control(request, str(application.id), str(session.id))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        control = payload.get("control") if isinstance(payload.get("control"), dict) else {}
        evidence_ref = control.get("evidence_ref") if isinstance(control.get("evidence_ref"), dict) else {}
        self.assertEqual(str(evidence_ref.get("promotion_evidence_id") or ""), str(evidence.id))
        self.assertTrue(bool(control.get("can_rollback")))
        self.assertIn("rollback", list(control.get("next_allowed_actions") or []))

    def test_solution_change_session_rollback_restores_superseded_target_and_emits_evidence(self):
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
        current_instance = WorkspaceAppInstance.objects.create(
            workspace=self.workspace,
            artifact=ui_artifact,
            app_slug=ui_artifact.slug[4:],
            fqdn=f"{ui_artifact.slug[4:]}.current.local.test",
            deployment_target="local",
            status="active",
            dns_config_json={
                "runtime_target": {
                    "runtime_owner": "primary",
                    "runtime_base_url": "http://localhost",
                    "public_app_url": "http://localhost",
                    "compose_project": "xyn-local",
                }
            },
        )
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Rollback test",
            request_text="Rollback promoted change",
            created_by=self.identity,
            status="planned",
            execution_status="promoted",
        )
        source_evidence = SolutionChangeSessionPromotionEvidence.objects.create(
            workspace=self.workspace,
            application=application,
            solution_change_session=session,
            operation="promotion",
            promotion_status="success",
            actor_source="human",
            actor_identity=self.identity,
            superseded_active_state_json={
                "runtime_target_id": "prior-target-id",
                "runtime_base_url": "http://prior.localhost",
                "public_app_url": "http://prior.localhost",
                "compose_project": "xyn-local-prior",
            },
            resulting_active_target_json={
                "runtime_target_id": str(current_instance.id),
                "runtime_base_url": "http://localhost",
                "public_app_url": "http://localhost",
                "compose_project": "xyn-local",
            },
        )
        rollback_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/rollback",
            method="post",
            data=json.dumps({"evidence_id": str(source_evidence.id)}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            rolled_back = application_solution_change_session_rollback(rollback_request, str(application.id), str(session.id))
        self.assertEqual(rolled_back.status_code, 200)
        payload = json.loads(rolled_back.content)
        self.assertTrue(bool(payload.get("rollback_performed")))
        self.assertEqual(str(payload.get("status") or ""), "succeeded")
        rollback_evidence_ref = payload.get("rollback_evidence_ref") if isinstance(payload.get("rollback_evidence_ref"), dict) else {}
        rollback_evidence_id = str(rollback_evidence_ref.get("promotion_evidence_id") or "")
        self.assertTrue(bool(rollback_evidence_id))
        rollback_evidence = SolutionChangeSessionPromotionEvidence.objects.get(id=rollback_evidence_id)
        self.assertEqual(str(rollback_evidence.operation), "rollback")
        self.assertEqual(str(rollback_evidence.source_promotion_evidence_id), str(source_evidence.id))
        session.refresh_from_db()
        self.assertEqual(str(session.execution_status or ""), "committed")

    def test_solution_change_session_rollback_blocks_when_superseded_state_missing(self):
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
            title="Rollback blocked test",
            request_text="Rollback promoted change",
            created_by=self.identity,
            status="planned",
            execution_status="promoted",
        )
        source_evidence = SolutionChangeSessionPromotionEvidence.objects.create(
            workspace=self.workspace,
            application=application,
            solution_change_session=session,
            operation="promotion",
            promotion_status="success",
            actor_source="human",
            actor_identity=self.identity,
            superseded_active_state_json={},
        )
        rollback_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/rollback",
            method="post",
            data=json.dumps({"evidence_id": str(source_evidence.id)}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            blocked = application_solution_change_session_rollback(rollback_request, str(application.id), str(session.id))
        self.assertEqual(blocked.status_code, 409)
        payload = json.loads(blocked.content)
        self.assertEqual(str(payload.get("blocked_reason") or ""), "superseded_state_missing")
        self.assertFalse(bool(payload.get("rollback_performed")))
        self.assertEqual(
            SolutionChangeSessionPromotionEvidence.objects.filter(solution_change_session=session, operation="rollback").count(),
            0,
        )

    def test_solution_change_session_control_inspect_returns_machine_envelope(self):
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
            title="Inspect control",
            request_text="Inspect status",
            created_by=self.identity,
            status="planned",
            execution_status="committed",
        )
        request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/control",
            method="get",
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = application_solution_change_session_control(request, str(application.id), str(session.id))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(str(payload.get("operation") or ""), "inspect")
        self.assertEqual(str(payload.get("status") or ""), "ready")
        control = payload.get("control") if isinstance(payload.get("control"), dict) else {}
        self.assertEqual(str(control.get("change_session_id") or ""), str(session.id))
        self.assertIn("can_stage_apply", control)
        self.assertIn("can_prepare_preview", control)
        self.assertIn("can_activate", control)
        self.assertIn("can_promote", control)
        self.assertEqual(str(control.get("blocked_reason") or ""), "solution_not_installed_in_root")
        self.assertIn("install_in_root", list(control.get("next_allowed_actions") or []))

    def test_solution_change_session_control_action_promote_blocked_returns_envelope(self):
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
            title="Promote control",
            request_text="Promote",
            created_by=self.identity,
            status="planned",
            execution_status="committed",
        )
        request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/control/actions",
            method="post",
            data=json.dumps({"operation": "promote"}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = application_solution_change_session_control_action(request, str(application.id), str(session.id))
        self.assertEqual(response.status_code, 409)
        payload = json.loads(response.content)
        self.assertEqual(str(payload.get("operation") or ""), "promote")
        self.assertEqual(str(payload.get("status") or ""), "blocked")
        control = payload.get("control") if isinstance(payload.get("control"), dict) else {}
        self.assertEqual(str(control.get("blocked_reason") or ""), "solution_not_installed_in_root")
        operation_result = payload.get("operation_result") if isinstance(payload.get("operation_result"), dict) else {}
        self.assertEqual(str(operation_result.get("blocked_reason") or ""), "solution_not_installed_in_root")

    def test_solution_change_session_control_action_respond_to_planner_prompt_succeeds(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        api_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="xyn-api",
            slug=f"xyn-api-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Xyn",
            summary="Planner prompt response",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Planner flow validation",
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=api_artifact,
            role="primary_api",
        )
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Respond to planner prompt",
            request_text="Refine planner scope",
            created_by=self.identity,
            status="planned",
        )
        xyn_api._append_solution_planning_turn(
            session=session,
            actor="planner",
            kind="question",
            payload={"question": "Please clarify scope"},
        )
        request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/control/actions",
            method="post",
            data=json.dumps(
                {
                    "operation": "respond_to_planner_prompt",
                    "response": "Keep this backend-only and preserve behavior.",
                    "metadata": {"source": "mcp-test"},
                }
            ),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api._interpret_solution_refinement",
            return_value={"result_type": "interpreted", "planner_message": ""},
        ):
            response = application_solution_change_session_control_action(request, str(application.id), str(session.id))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(str(payload.get("operation") or ""), "respond_to_planner_prompt")
        self.assertEqual(str(payload.get("status") or ""), "succeeded")
        result = payload.get("operation_result") if isinstance(payload.get("operation_result"), dict) else {}
        planner_response = result.get("planner_prompt_response") if isinstance(result.get("planner_prompt_response"), dict) else {}
        self.assertEqual(str((planner_response.get("metadata") or {}).get("source") or ""), "mcp-test")
        self.assertFalse(bool(planner_response.get("pending_prompt_remaining")))

    def test_solution_change_session_control_action_respond_to_planner_prompt_advances_blocked_reason(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        api_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="xyn-api",
            slug=f"xyn-api-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Xyn",
            summary="Planner prompt progression",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Planner flow validation",
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=api_artifact,
            role="primary_api",
        )
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Planner prompt progression",
            request_text="Need prompt resolution",
            created_by=self.identity,
            status="planned",
        )
        xyn_api._append_solution_planning_turn(
            session=session,
            actor="planner",
            kind="question",
            payload={"question": "Please clarify scope"},
        )
        request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/control/actions",
            method="post",
            data=json.dumps(
                {
                    "operation": "respond_to_planner_prompt",
                    "prompt_response": "Preserve behavior and do not add features.",
                }
            ),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api._interpret_solution_refinement",
            return_value={"result_type": "interpreted", "planner_message": ""},
        ):
            response = application_solution_change_session_control_action(request, str(application.id), str(session.id))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        control = payload.get("control") if isinstance(payload.get("control"), dict) else {}
        self.assertNotEqual(str(control.get("blocked_reason") or ""), "planning_prompt_pending")
        self.assertNotIn("respond_to_planner_prompt", list(control.get("next_allowed_actions") or []))

    def test_solution_change_session_control_action_respond_to_planner_prompt_returns_409_when_not_pending(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        api_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="xyn-api",
            slug=f"xyn-api-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Xyn",
            summary="Planner prompt missing",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Planner flow validation",
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=api_artifact,
            role="primary_api",
        )
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="No pending prompt",
            request_text="Already planned",
            created_by=self.identity,
            status="planned",
        )
        request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/control/actions",
            method="post",
            data=json.dumps(
                {
                    "operation": "respond_to_planner_prompt",
                    "response": "Any reply",
                }
            ),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = application_solution_change_session_control_action(request, str(application.id), str(session.id))
        self.assertEqual(response.status_code, 409)
        payload = json.loads(response.content)
        self.assertEqual(str(payload.get("operation") or ""), "respond_to_planner_prompt")
        self.assertEqual(str(payload.get("status") or ""), "blocked")
        operation_result = payload.get("operation_result") if isinstance(payload.get("operation_result"), dict) else {}
        self.assertEqual(str(operation_result.get("blocked_reason") or ""), "planning_prompt_not_pending")

    def test_solution_change_session_control_inspect_reports_stage_preview_progress(self):
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
            title="Stage preview control",
            request_text="Run stage and preview",
            created_by=self.identity,
            status="planned",
            execution_status="staged",
            plan_json={"per_artifact_work": []},
            staged_changes_json={
                "artifact_states": [{"artifact_id": str(ui_artifact.id), "state": "staged"}],
                "per_repo_results": [{"repo_slug": "xyn-platform", "status": "ready"}],
            },
        )
        request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/control",
            method="get",
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = application_solution_change_session_control(request, str(application.id), str(session.id))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        control = payload.get("control") if isinstance(payload.get("control"), dict) else {}
        self.assertTrue(bool(control.get("can_prepare_preview")))
        self.assertIn("prepare_preview", list(control.get("next_allowed_actions") or []))
        self.assertEqual(len(list(control.get("per_repo_results") or [])), 1)

    def test_solution_change_session_control_inspect_promotable_when_root_target_present(self):
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
            app_slug=ui_artifact.slug[4:],
            fqdn=f"{ui_artifact.slug[4:]}.local.test",
            deployment_target="local",
            status="active",
            dns_config_json={
                "runtime_target": {
                    "runtime_owner": "primary",
                    "runtime_base_url": "http://localhost",
                    "public_app_url": "http://localhost",
                    "compose_project": "xyn-local",
                }
            },
        )
        session = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Promotable control",
            request_text="Promote validated change",
            created_by=self.identity,
            status="planned",
            execution_status="committed",
        )
        request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/control",
            method="get",
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = application_solution_change_session_control(request, str(application.id), str(session.id))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        control = payload.get("control") if isinstance(payload.get("control"), dict) else {}
        self.assertTrue(bool(control.get("root_target_present")))
        self.assertTrue(bool(control.get("can_promote")))
        self.assertIn("promote", list(control.get("next_allowed_actions") or []))

    def test_workspace_linked_change_session_returns_active_matching_session(self):
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
            status="planned",
            execution_status="preview_ready",
            metadata_json={
                "iteration_linkage": {
                    "runtime_target": {
                        "public_app_url": "http://localhost:32932",
                        "runtime_base_url": "http://xyn-sibling-api:8080",
                    }
                }
            },
        )
        request = self._request(
            f"/xyn/api/workspaces/{self.workspace.id}/linked-change-session?current_origin=http://localhost:32932",
            method="get",
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = workspace_linked_change_session(request, str(self.workspace.id))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        linked = payload.get("linked_session") if isinstance(payload, dict) else None
        self.assertIsInstance(linked, dict)
        self.assertEqual(str(linked.get("solution_change_session_id") or ""), str(session.id))
        self.assertEqual(str(linked.get("application_id") or ""), str(application.id))

    def test_workspace_linked_change_session_hides_archived_or_finalized_sessions(self):
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
        SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Archived session",
            request_text="No longer active",
            created_by=self.identity,
            status="archived",
            execution_status="ready_for_promotion",
            metadata_json={
                "finalized": {"at": "2026-03-30T00:00:00Z"},
                "iteration_linkage": {"runtime_target": {"public_app_url": "http://localhost:32932"}},
            },
        )
        request = self._request(
            f"/xyn/api/workspaces/{self.workspace.id}/linked-change-session?current_origin=http://localhost:32932",
            method="get",
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = workspace_linked_change_session(request, str(self.workspace.id))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertIsNone(payload.get("linked_session"))

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

    def test_solution_change_session_prepare_preview_non_app_artifact_no_metadata_json_attr(self):
        artifact_type = ArtifactType.objects.create(slug=f"runtime-ui-{uuid.uuid4().hex[:6]}", name="Runtime UI")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Xyn UI",
            slug=f"xyn-ui-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            scope_json={"slug": "xyn-ui", "manifest_ref": "registry/modules/xyn-ui.artifact.manifest.json"},
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Xyn",
            summary="Platform shell",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Platform shell updates",
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
            title="Preview should fail cleanly",
            request_text="Adjust header spacing",
            created_by=self.identity,
            selected_artifact_ids_json=[str(ui_artifact.id)],
            status="planned",
            plan_json={"per_artifact_work": [{"artifact_id": str(ui_artifact.id), "planned_work": ["Update header spacing"]}]},
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
        artifacts = ((preview_payload.get("session") or {}).get("preview") or {}).get("artifacts") or []
        self.assertTrue(artifacts)
        self.assertEqual(str(artifacts[0].get("reason") or ""), "preview_app_slug_unresolved")

    def test_solution_change_session_prepare_preview_uses_local_platform_runtime_fallback(self):
        artifact_type = ArtifactType.objects.create(slug=f"runtime-ui-{uuid.uuid4().hex[:6]}", name="Runtime UI")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="xyn-ui",
            slug="xyn-ui",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            scope_json={"slug": "xyn-ui", "manifest_ref": "registry/modules/xyn-ui.artifact.manifest.json"},
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Xyn",
            summary="Platform shell",
            source_factory_key="generic_application_mvp",
            requested_by=self.identity,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Platform shell updates",
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
            title="Preview via local fallback",
            request_text="Adjust header spacing",
            created_by=self.identity,
            selected_artifact_ids_json=[str(ui_artifact.id)],
            status="planned",
            plan_json={"per_artifact_work": [{"artifact_id": str(ui_artifact.id), "planned_work": ["Update header spacing"]}]},
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
        healthy_response = mock.Mock(status_code=200)
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api._runtime_target_request",
            return_value=healthy_response,
        ), mock.patch.dict(
            os.environ,
            {"XYN_ENV": "local", "XYN_PUBLIC_BASE_URL": "http://localhost"},
            clear=False,
        ):
            preview_response = application_solution_change_session_prepare_preview(
                preview_request, str(application.id), str(session.id)
            )
        preview_payload = json.loads(preview_response.content)
        self.assertEqual(preview_response.status_code, 200)
        self.assertTrue(preview_payload["prepared"])
        preview = (preview_payload["session"].get("preview") or {})
        self.assertEqual(str(preview.get("status") or ""), "ready")
        self.assertEqual(str(preview.get("primary_url") or ""), "http://localhost")
        artifacts = preview.get("artifacts") if isinstance(preview.get("artifacts"), list) else []
        self.assertTrue(artifacts)
        self.assertEqual(str((artifacts[0] or {}).get("runtime_owner") or ""), "primary")

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

    def test_solution_change_session_prepare_preview_provisions_session_scoped_runtime_for_repo_backed_stage(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Deal Finder UI",
            slug=f"app.deal-finder-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["apps/xyn-ui/"],
            edit_mode="repo_backed",
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
                        "apply_state": "queued",
                    }
                ],
                "selected_artifact_ids": [str(ui_artifact.id)],
                "execution_runs": [
                    {
                        "artifact_id": str(ui_artifact.id),
                        "status": "queued",
                        "dev_task_id": str(uuid.uuid4()),
                        "runtime_run_id": str(uuid.uuid4()),
                    }
                ],
                "dev_task_ids": [str(uuid.uuid4())],
            },
            execution_status="staged",
        )
        preview_request = self._request(
            f"/xyn/api/applications/{application.id}/change-sessions/{session.id}/prepare-preview",
            method="post",
            data=json.dumps({}),
        )
        provision_response = mock.Mock()
        provision_response.status_code = 200
        provision_response.headers = {"content-type": "application/json"}
        provision_response.content = b'{"status":"succeeded"}'
        provision_response.json.return_value = {
            "status": "succeeded",
            "compose_project": "xyn-preview-123",
            "ui_url": "http://xyn-preview-session.localhost",
            "api_url": "http://api.xyn-preview-session.localhost",
        }
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api._seed_api_request",
            return_value=provision_response,
        ) as provision_request:
            preview_response = application_solution_change_session_prepare_preview(
                preview_request, str(application.id), str(session.id)
            )
        preview_payload = json.loads(preview_response.content)
        self.assertEqual(preview_response.status_code, 200)
        self.assertTrue(preview_payload["prepared"])
        preview = preview_payload["session"].get("preview") or {}
        self.assertTrue(bool(preview.get("isolated_session_preview_requested")))
        self.assertTrue(bool(preview.get("newly_built_for_session")))
        self.assertFalse(bool(preview.get("reused_existing_runtime")))
        self.assertEqual(str(preview.get("primary_url") or ""), "http://xyn-preview-session.localhost")
        self.assertNotEqual(str(preview.get("primary_url") or ""), "http://localhost")
        session_build = preview.get("session_build") if isinstance(preview.get("session_build"), dict) else {}
        self.assertEqual(str(session_build.get("status") or ""), "newly_built_for_session")
        self.assertEqual(str(session_build.get("reason") or ""), "session_preview_environment_created")
        self.assertEqual(provision_request.call_count, 1)
        kwargs = provision_request.call_args.kwargs
        payload = kwargs.get("payload") if isinstance(kwargs, dict) else {}
        self.assertTrue(str((payload or {}).get("name") or "").startswith("preview-"))
        self.assertTrue(str((payload or {}).get("ui_host") or "").startswith("xyn-preview-"))
        self.assertTrue(str((payload or {}).get("api_host") or "").startswith("api.xyn-preview-"))
        self.assertTrue(bool((payload or {}).get("prefer_local_images")))
        self.assertTrue(bool((payload or {}).get("prefer_local_sources")))

    def test_solution_change_session_prepare_preview_uses_unique_session_preview_project_per_session(self):
        artifact_type = ArtifactType.objects.create(slug=f"generated-app-{uuid.uuid4().hex[:6]}", name="Generated App")
        ui_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Deal Finder UI",
            slug=f"app.deal-finder-{uuid.uuid4().hex[:6]}",
            status="active",
            artifact_state="canonical",
            author=self.identity,
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["apps/xyn-ui/"],
            edit_mode="repo_backed",
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

        def _session_payload(session_id: str) -> Dict[str, Any]:
            return {
                "artifact_states": [
                    {
                        "artifact_id": str(ui_artifact.id),
                        "artifact_title": ui_artifact.title,
                        "role": "primary_ui",
                        "apply_state": "queued",
                    }
                ],
                "selected_artifact_ids": [str(ui_artifact.id)],
                "execution_runs": [
                    {
                        "artifact_id": str(ui_artifact.id),
                        "status": "queued",
                        "dev_task_id": str(uuid.uuid4()),
                        "runtime_run_id": str(uuid.uuid4()),
                    }
                ],
                "dev_task_ids": [str(uuid.uuid4())],
                "session_id": session_id,
            }

        session_one = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Preview one",
            request_text="Update campaign UX",
            created_by=self.identity,
            selected_artifact_ids_json=[str(ui_artifact.id)],
            status="planned",
            plan_json={"per_artifact_work": [{"artifact_id": str(ui_artifact.id), "planned_work": ["Update shell UI"]}]},
            staged_changes_json=_session_payload("one"),
            execution_status="staged",
        )
        session_two = SolutionChangeSession.objects.create(
            workspace=self.workspace,
            application=application,
            title="Preview two",
            request_text="Update campaign UX",
            created_by=self.identity,
            selected_artifact_ids_json=[str(ui_artifact.id)],
            status="planned",
            plan_json={"per_artifact_work": [{"artifact_id": str(ui_artifact.id), "planned_work": ["Update shell UI"]}]},
            staged_changes_json=_session_payload("two"),
            execution_status="staged",
        )

        def _make_response(url: str, compose_project: str) -> mock.Mock:
            response = mock.Mock()
            response.status_code = 200
            response.headers = {"content-type": "application/json"}
            response.content = b'{"status":"succeeded"}'
            response.json.return_value = {
                "status": "succeeded",
                "compose_project": compose_project,
                "ui_url": url,
                "api_url": f"{url}/api",
            }
            return response

        provision_calls: List[Dict[str, Any]] = []

        def _seed_side_effect(**kwargs: Any) -> mock.Mock:
            payload = kwargs.get("payload") if isinstance(kwargs, dict) else {}
            payload = payload if isinstance(payload, dict) else {}
            provision_calls.append(dict(payload))
            name = str(payload.get("name") or "")
            return _make_response(
                url=f"http://{name}.localhost",
                compose_project=f"xyn-{name}",
            )

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api._seed_api_request",
            side_effect=_seed_side_effect,
        ):
            request_one = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session_one.id}/prepare-preview",
                method="post",
                data=json.dumps({}),
            )
            response_one = application_solution_change_session_prepare_preview(
                request_one, str(application.id), str(session_one.id)
            )
            request_two = self._request(
                f"/xyn/api/applications/{application.id}/change-sessions/{session_two.id}/prepare-preview",
                method="post",
                data=json.dumps({}),
            )
            response_two = application_solution_change_session_prepare_preview(
                request_two, str(application.id), str(session_two.id)
            )

        payload_one = json.loads(response_one.content)
        payload_two = json.loads(response_two.content)
        preview_one = payload_one.get("session", {}).get("preview") or {}
        preview_two = payload_two.get("session", {}).get("preview") or {}
        self.assertEqual(response_one.status_code, 200)
        self.assertEqual(response_two.status_code, 200)
        self.assertEqual(len(provision_calls), 2)
        self.assertNotEqual(str(provision_calls[0].get("name") or ""), str(provision_calls[1].get("name") or ""))
        self.assertNotEqual(str(preview_one.get("primary_url") or ""), str(preview_two.get("primary_url") or ""))

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
