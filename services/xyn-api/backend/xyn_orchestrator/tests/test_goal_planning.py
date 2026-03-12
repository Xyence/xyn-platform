import json
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from xyn_orchestrator.goal_planning import decompose_goal, persist_goal_plan, recommend_next_slice, valid_goal_transition
from xyn_orchestrator.models import CoordinationThread, DevTask, Goal, UserIdentity, Workspace, WorkspaceMembership
from xyn_orchestrator.xyn_api import goal_decompose, goal_detail, goal_review, goals_collection


class GoalPlanningTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="planner", email="planner@example.com", password="password")
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example.com",
            subject="planner-user",
            email="planner@example.com",
        )
        self.workspace = Workspace.objects.create(name="Planning Workspace", slug="planning-workspace")
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

    def test_real_estate_goal_decomposition_is_deterministic_and_mvp_first(self):
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
            "Listing Data Ingestion",
            "Property Model and CRUD",
            "Comparable Analysis",
        ])
        self.assertIn("smallest vertical slice", plan_a.planning_summary.lower())
        self.assertEqual(plan_a.work_items[0].title, "Identify the first listing source and capture the ingestion contract")

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
        self.assertEqual(goal.threads.count(), 6)
        self.assertEqual(goal.work_items.count(), 8)
        self.assertEqual(len(persisted["threads"]), 6)
        self.assertEqual(len(persisted["work_items"]), 8)
        self.assertTrue(all(thread.goal_id == goal.id for thread in goal.threads.all()))
        self.assertTrue(all(task.goal_id == goal.id for task in goal.work_items.all()))
        self.assertTrue(goal.work_items.filter(coordination_thread__title="Property Model and CRUD").exists())

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

        request = self._request(
            f"/xyn/api/goals/{goal.id}/review",
            method="post",
            data=json.dumps({"review_action": "queue_first_slice"}),
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = goal_review(request, str(goal.id))
        payload = json.loads(response.content)
        goal.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "queued_first_slice")
        self.assertEqual(goal.planning_status, "in_progress")
        seeded_task = DevTask.objects.get(id=payload["queue_seed"]["work_item_id"])
        self.assertEqual(seeded_task.status, "queued")
        self.assertEqual(seeded_task.coordination_thread.status, "active")

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
        self.assertEqual(recommendation.thread_title, "Listing Data Ingestion")
        self.assertIn("Start with the smallest queued slice", recommendation.summary)
