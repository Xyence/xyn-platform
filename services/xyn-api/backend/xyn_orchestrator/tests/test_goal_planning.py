import json
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from xyn_orchestrator.goal_progress import compute_goal_execution_metrics, compute_goal_health_indicators, compute_goal_progress
from xyn_orchestrator.development_intelligence import compute_goal_development_insights, compute_goal_diagnostic
from xyn_orchestrator.goal_planning import decompose_goal, persist_goal_plan, recommend_next_slice, valid_goal_transition
from xyn_orchestrator.portfolio_intelligence import (
    build_goal_portfolio_row,
    build_goal_portfolio_state,
    compute_portfolio_insights,
    recommend_portfolio_goal,
)
from xyn_orchestrator.models import (
    Application,
    ApplicationPlan,
    CoordinationEvent,
    CoordinationThread,
    DevTask,
    Goal,
    UserIdentity,
    Workspace,
    WorkspaceMembership,
)
from xyn_orchestrator.xyn_api import (
    application_detail,
    application_factories_collection,
    application_plan_apply,
    application_plans_collection,
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
        self.assertIn("ai_real_estate_deal_finder", factory_keys)
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
        self.assertEqual(payload["source_factory_key"], "ai_real_estate_deal_finder")
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

    def test_application_detail_groups_goals_and_reuses_portfolio_state(self):
        plan = ApplicationPlan.objects.create(
            workspace=self.workspace,
            name="Deal Finder",
            summary="Reviewable plan",
            source_factory_key="ai_real_estate_deal_finder",
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
            source_factory_key="ai_real_estate_deal_finder",
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
        self.assertEqual(recommendation.thread_title, "Listing Data Ingestion")
        self.assertEqual(len(recommendation.recommended_work_items), 1)
        self.assertIn("Listing Data Ingestion", recommendation.reasoning_summary)
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
