import datetime as dt
import json
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase

from xyn_orchestrator.models import Application, CoordinationThread, DevTask, Goal, ManagedRepository, Run, RunArtifact, UserIdentity, Workspace, WorkspaceMembership
from xyn_orchestrator.xyn_api import (
    _build_dev_task_runtime_payload,
    _conversation_execution_context,
    _load_dev_task_runtime_source,
    blueprint_dev_tasks,
    dev_task_detail,
    dev_task_dispatch,
    dev_task_requeue,
    dev_task_retry,
    dev_task_run,
)


class _FakeResponse:
    def __init__(self, *, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.headers = {"content-type": "application/json"}
        self.content = json.dumps(self._body).encode("utf-8")

    def json(self):
        return self._body


class DevTaskRuntimeBridgeTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="devtask-admin", email="devtask@example.com", password="password")
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example.com",
            subject="devtask-admin",
            email="devtask@example.com",
        )
        self.workspace = Workspace.objects.create(name="Runtime Bridge", slug="runtime-bridge")
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user_identity=self.identity,
            role="admin",
            termination_authority=True,
        )
        self.csrf_client = Client(enforce_csrf_checks=True)
        self.csrf_client.force_login(self.user)
        session = self.csrf_client.session
        session["user_identity_id"] = str(self.identity.id)
        session.save()
        self.source_run = Run.objects.create(
            entity_type="blueprint",
            entity_id=uuid.uuid4(),
            status="succeeded",
            summary="Implementation plan source",
            created_by=self.user,
        )
        self.task = DevTask.objects.create(
            title="Implement Epic C bridge",
            task_type="codegen",
            status="queued",
            priority=0,
            max_attempts=3,
            source_entity_type="blueprint",
            source_entity_id=uuid.uuid4(),
            source_run=self.source_run,
            input_artifact_key="implementation_plan.json",
            work_item_id="epic-c-bridge",
            context_purpose="operator",
            created_by=self.user,
            updated_by=self.user,
        )
        self.plan_json = {
            "work_items": [
                {
                    "id": "epic-c-bridge",
                    "title": "Implement Epic C bridge",
                    "description": "Route development execution through Epic C runtime runs.",
                    "acceptance_criteria": ["Submit to runtime API", "Preserve work item identity"],
                    "repo_targets": [{"name": "xyn-platform", "ref": "develop"}],
                    "verify": [{"command": "python -m unittest"}],
                }
            ]
        }

    def _request(self, path: str, *, method: str = "post", query: dict | None = None, data=None):
        payload = data if data is not None else (query or {})
        kwargs = {"data": payload}
        if isinstance(payload, str):
            kwargs["content_type"] = "application/json"
        request = getattr(self.factory, method.lower())(path, **kwargs)
        request.user = self.user
        return request

    def _auth_patches(self):
        return (
            mock.patch("xyn_orchestrator.xyn_api._require_staff", return_value=None),
            mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity),
            mock.patch("xyn_orchestrator.xyn_api._resolve_workspace_for_identity", return_value=self.workspace),
        )

    def test_dev_task_run_submits_epic_c_runtime_run_with_expected_payload(self):
        runtime_run_id = str(uuid.uuid4())
        captured = {}

        def _seed_api_request(*, method, path, workspace_id="", workspace_slug="", payload=None, timeout=20):
            captured["method"] = method
            captured["path"] = path
            captured["payload"] = payload
            return _FakeResponse(body={"id": runtime_run_id, "status": "queued"})

        request = self._request(f"/xyn/api/dev-tasks/{self.task.id}/run")
        with self._auth_patches()[0], self._auth_patches()[1], self._auth_patches()[2], mock.patch(
            "xyn_orchestrator.xyn_api._download_artifact_json", return_value=self.plan_json
        ), mock.patch("xyn_orchestrator.xyn_api._seed_api_request", side_effect=_seed_api_request), mock.patch(
            "xyn_orchestrator.xyn_api._enqueue_job"
        ) as enqueue_job:
            response = dev_task_run(request, str(self.task.id))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["run_id"], runtime_run_id)
        self.task.refresh_from_db()
        self.assertEqual(str(self.task.runtime_run_id), runtime_run_id)
        self.assertEqual(str(self.task.runtime_workspace_id), str(self.workspace.id))
        self.assertIsNone(self.task.result_run_id)
        enqueue_job.assert_not_called()
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["path"], "/api/v1/runtime/runs")
        runtime_payload = captured["payload"]
        self.assertEqual(runtime_payload["work_item_id"], "epic-c-bridge")
        self.assertEqual(runtime_payload["worker_type"], "codex_local")
        self.assertEqual(runtime_payload["target"]["repo"], "xyn-platform")
        self.assertEqual(runtime_payload["target"]["branch"], "develop")
        self.assertEqual(runtime_payload["target"]["workspace_id"], str(self.workspace.id))
        self.assertEqual(runtime_payload["prompt"]["title"], "Implement Epic C bridge")
        self.assertIn("Route development execution through Epic C runtime runs.", runtime_payload["prompt"]["body"])
        self.assertEqual(runtime_payload["context"]["metadata"]["execution_brief_source"], "fallback")
        self.assertEqual(runtime_payload["policy"]["max_retries"], 2)
        self.assertIn("report", runtime_payload["requested_outputs"])

    def test_dev_task_run_blocks_gated_brief_until_approved(self):
        self.task.execution_brief = {
            "schema_version": "v1",
            "summary": "Implement Epic C bridge",
            "objective": "Route development execution through the runtime bridge.",
        }
        self.task.execution_brief_review_state = "draft"
        self.task.execution_policy = {"require_brief_approval": True}
        self.task.save(update_fields=["execution_brief", "execution_brief_review_state", "execution_policy", "updated_at"])

        request = self._request(f"/xyn/api/dev-tasks/{self.task.id}/run")
        with self._auth_patches()[0], self._auth_patches()[1], self._auth_patches()[2], mock.patch(
            "xyn_orchestrator.xyn_api._download_artifact_json", return_value=self.plan_json
        ), mock.patch("xyn_orchestrator.xyn_api._seed_api_request") as seed_api_request:
            response = dev_task_run(request, str(self.task.id))

        self.assertEqual(response.status_code, 409)
        payload = json.loads(response.content)
        self.assertIn("review is required", payload["error"])
        seed_api_request.assert_not_called()
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "awaiting_review")

    def test_dev_task_run_allows_gated_brief_when_approved(self):
        runtime_run_id = str(uuid.uuid4())
        self.task.execution_brief = {
            "schema_version": "v1",
            "summary": "Implement Epic C bridge",
            "objective": "Route development execution through the runtime bridge.",
        }
        self.task.execution_brief_review_state = "approved"
        self.task.execution_policy = {"require_brief_approval": True}
        self.task.save(update_fields=["execution_brief", "execution_brief_review_state", "execution_policy", "updated_at"])

        def _seed_api_request(*, method, path, workspace_id="", workspace_slug="", payload=None, timeout=20):
            self.assertEqual(method, "POST")
            self.assertEqual(path, "/api/v1/runtime/runs")
            return _FakeResponse(body={"id": runtime_run_id, "status": "queued"})

        request = self._request(f"/xyn/api/dev-tasks/{self.task.id}/run")
        with self._auth_patches()[0], self._auth_patches()[1], self._auth_patches()[2], mock.patch(
            "xyn_orchestrator.xyn_api._download_artifact_json", return_value=self.plan_json
        ), mock.patch("xyn_orchestrator.xyn_api._seed_api_request", side_effect=_seed_api_request):
            response = dev_task_run(request, str(self.task.id))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["run_id"], runtime_run_id)

    def test_dev_task_dispatch_returns_structured_runtime_submission_error(self):
        self.task.execution_brief = {
            "schema_version": "v1",
            "summary": "Implement Epic C bridge",
            "objective": "Route development execution through the runtime bridge.",
        }
        self.task.execution_brief_review_state = "approved"
        self.task.execution_policy = {"require_brief_approval": True}
        goal = Goal.objects.create(
            workspace=self.workspace,
            title="Runtime Dispatch Goal",
            description="",
            requested_by=self.identity,
            goal_type="build_system",
            priority="normal",
        )
        thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            goal=goal,
            title="Runtime Dispatch Thread",
            status="active",
            owner=self.identity,
        )
        self.task.goal = goal
        self.task.coordination_thread = thread
        self.task.status = "queued"
        self.task.save(
            update_fields=[
                "execution_brief",
                "execution_brief_review_state",
                "execution_policy",
                "goal",
                "coordination_thread",
                "status",
                "updated_at",
            ]
        )

        request = self._request(
            f"/xyn/api/dev-tasks/{self.task.id}/dispatch",
            data=json.dumps({"workspace_id": str(self.workspace.id)}),
            method="post",
        )
        with self._auth_patches()[0], self._auth_patches()[1], self._auth_patches()[2], mock.patch(
            "xyn_orchestrator.xyn_api._submit_dev_task_runtime_run",
            side_effect=RuntimeError("runtime submission failed"),
        ):
            response = dev_task_dispatch(request, str(self.task.id))

        self.assertEqual(response.status_code, 502)
        payload = json.loads(response.content)
        self.assertEqual(payload["error"], "runtime submission failed")
        self.assertEqual(payload["work_item"]["status"], "awaiting_review")
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "awaiting_review")
        self.assertEqual(self.task.last_error, "runtime submission failed")

    def test_dev_task_run_uses_current_active_brief_after_revision(self):
        runtime_run_id = str(uuid.uuid4())
        self.task.execution_brief = {
            "schema_version": "v1",
            "summary": "Current revised brief",
            "revision": 2,
            "objective": "Use the revised brief only.",
        }
        self.task.execution_brief_history = [
            {
                "revision": 1,
                "brief": {"schema_version": "v1", "summary": "Old approved brief", "revision": 1},
                "review_state": "approved",
            }
        ]
        self.task.execution_brief_review_state = "draft"
        self.task.execution_policy = {"require_brief_approval": True}
        self.task.save(
            update_fields=[
                "execution_brief",
                "execution_brief_history",
                "execution_brief_review_state",
                "execution_policy",
                "updated_at",
            ]
        )

        request = self._request(f"/xyn/api/dev-tasks/{self.task.id}/run")
        with self._auth_patches()[0], self._auth_patches()[1], self._auth_patches()[2], mock.patch(
            "xyn_orchestrator.xyn_api._download_artifact_json", return_value=self.plan_json
        ), mock.patch("xyn_orchestrator.xyn_api._seed_api_request") as seed_api_request:
            response = dev_task_run(request, str(self.task.id))

        self.assertEqual(response.status_code, 409)
        payload = json.loads(response.content)
        self.assertIn("review is required", payload["error"])
        seed_api_request.assert_not_called()

    def test_dev_task_runtime_payload_prefers_structured_execution_brief(self):
        self.task.execution_brief = {
            "schema_version": "v1",
            "summary": "Implement Epic C runtime bridge",
            "objective": "Route coding execution through the runtime bridge.",
            "implementation_intent": "Update the bridge layer and keep the change scoped to runtime submission.",
            "target": {"repository_slug": "xyn-platform", "branch": "develop"},
            "scope": {"allowed_areas": ["runtime bridge"], "allowed_files": []},
            "validation": {
                "acceptance_criteria": ["Submit to runtime API", "Preserve work item identity"],
                "commands": ["python -m unittest xyn_orchestrator.tests.test_dev_task_runtime_bridge"],
            },
            "boundaries": ["Do not broaden the change beyond the bridge seam."],
            "source_context": {"planning_source": "goal_plan"},
        }
        self.task.save(update_fields=["execution_brief", "updated_at"])
        with mock.patch("xyn_orchestrator.xyn_api._download_artifact_json", return_value=self.plan_json):
            payload = _build_dev_task_runtime_payload(self.task, self.workspace)
        self.assertEqual(payload["prompt"]["title"], "Implement Epic C runtime bridge")
        self.assertIn("Requested change: Update the bridge layer and keep the change scoped to runtime submission.", payload["prompt"]["body"])
        self.assertIn("Target repository: xyn-platform @ develop", payload["prompt"]["body"])
        self.assertIn("Allowed areas:", payload["prompt"]["body"])
        self.assertIn("Validation commands:", payload["prompt"]["body"])
        self.assertEqual(payload["context"]["metadata"]["execution_brief_source"], "task_execution_brief")
        self.assertEqual(payload["context"]["metadata"]["execution_brief"]["summary"], "Implement Epic C runtime bridge")

    def test_load_dev_task_runtime_source_falls_back_to_execution_brief_context(self):
        self.task.source_run = None
        self.task.input_artifact_key = ""
        self.task.target_repo = "xyn-platform"
        self.task.target_branch = "develop"
        self.task.execution_brief = {
            "schema_version": "v1",
            "summary": "Implement first durable slice",
            "objective": "Ship the smallest viable coding slice.",
            "implementation_intent": "Use the stored brief as the runtime handoff when no plan artifact exists.",
            "target": {"repository_slug": "xyn-platform", "branch": "develop"},
            "validation": {
                "acceptance_criteria": ["Wire the slice through the runtime bridge"],
                "commands": ["pytest services/xyn-api/backend/xyn_orchestrator/tests/test_dev_task_runtime_bridge.py"],
            },
        }
        self.task.save(
            update_fields=[
                "source_run",
                "input_artifact_key",
                "target_repo",
                "target_branch",
                "execution_brief",
                "updated_at",
            ]
        )

        source = _load_dev_task_runtime_source(self.task)

        self.assertEqual(source["target_repo"], "xyn-platform")
        self.assertEqual(source["target_branch"], "develop")
        self.assertEqual(source["work_item"]["id"], self.task.work_item_id)
        self.assertEqual(source["work_item"]["execution_brief"]["summary"], "Implement first durable slice")
        self.assertEqual(source["work_item"]["verify"][0]["command"], "pytest services/xyn-api/backend/xyn_orchestrator/tests/test_dev_task_runtime_bridge.py")

    def test_load_dev_task_runtime_source_prefers_application_target_repository(self):
        repository = ManagedRepository.objects.create(
            slug="shine-app",
            display_name="Shine App",
            remote_url="https://example.com/shine-app.git",
            default_branch="main",
            is_active=True,
            auth_mode="local",
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Shine App",
            summary="Targeted app",
            source_factory_key="generic_application_mvp",
            source_conversation_id="thread-1",
            requested_by=self.identity,
            target_repository=repository,
            status="active",
            plan_fingerprint=f"app-{uuid.uuid4().hex}",
            request_objective="Build Shine App",
        )
        goal = Goal.objects.create(
            workspace=self.workspace,
            application=application,
            title="Implement shine app",
            description="Use repository target",
            source_conversation_id="thread-1",
            requested_by=self.identity,
        )
        self.task.goal = goal
        self.task.target_repo = ""
        self.task.target_branch = ""
        self.task.save(update_fields=["goal", "target_repo", "target_branch", "updated_at"])
        with mock.patch("xyn_orchestrator.xyn_api._download_artifact_json", return_value=self.plan_json):
            source = _load_dev_task_runtime_source(self.task)
        self.assertEqual(source["target_repo"], "shine-app")
        self.assertEqual(source["target_branch"], "main")

    def test_load_dev_task_runtime_source_rejects_ambiguous_repo_targets_without_explicit_target(self):
        ambiguous_plan = {
            "work_items": [
                {
                    "id": "epic-c-bridge",
                    "title": "Implement Epic C bridge",
                    "repo_targets": [
                        {"name": "xyn-platform", "ref": "develop"},
                        {"name": "xyn", "ref": "main"},
                    ],
                }
            ]
        }
        with mock.patch("xyn_orchestrator.xyn_api._download_artifact_json", return_value=ambiguous_plan):
            with self.assertRaisesMessage(ValueError, "multiple runtime target repos found"):
                _load_dev_task_runtime_source(self.task)

    def test_work_item_detail_includes_durable_coordination_fields(self):
        self.task.description = "Track durable coordination"
        self.task.source_conversation_id = "thread-1"
        self.task.intent_type = "create_and_dispatch_run"
        self.task.target_repo = "xyn-platform"
        self.task.target_branch = "develop"
        self.task.execution_policy = {"auto_continue": True}
        self.task.save(
            update_fields=[
                "description",
                "source_conversation_id",
                "intent_type",
                "target_repo",
                "target_branch",
                "execution_policy",
                "updated_at",
            ]
        )
        request = self._request(f"/xyn/api/dev-tasks/{self.task.id}", method="get")
        with self._auth_patches()[0], self._auth_patches()[1], self._auth_patches()[2]:
            response = dev_task_detail(request, str(self.task.id))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["work_item_id"], "epic-c-bridge")
        self.assertEqual(payload["description"], "Track durable coordination")
        self.assertEqual(payload["source_conversation_id"], "thread-1")
        self.assertEqual(payload["intent_type"], "create_and_dispatch_run")
        self.assertEqual(payload["target_repo"], "xyn-platform")
        self.assertEqual(payload["target_branch"], "develop")
        self.assertEqual(payload["execution_policy"], {"auto_continue": True})
        self.assertEqual(payload["execution_brief_review_state"], "draft")
        self.assertEqual(payload["execution_queue"]["status"], "queue_ready")

    def test_work_item_detail_exposes_execution_brief(self):
        self.task.execution_brief = {
            "schema_version": "v1",
            "summary": "Bounded handoff",
            "objective": "Implement the explicit handoff",
            "implementation_intent": "Use the stored brief instead of inferring intent from description text alone.",
            "target": {"repository_slug": "xyn-platform", "branch": "develop"},
        }
        self.task.execution_brief_review_state = "ready"
        self.task.execution_brief_review_notes = "Ready for coding"
        self.task.save(update_fields=["execution_brief", "execution_brief_review_state", "execution_brief_review_notes", "updated_at"])
        request = self._request(f"/xyn/api/dev-tasks/{self.task.id}", method="get")
        with self._auth_patches()[0], self._auth_patches()[1], self._auth_patches()[2]:
            response = dev_task_detail(request, str(self.task.id))
        payload = json.loads(response.content)
        self.assertEqual(payload["execution_brief"]["summary"], "Bounded handoff")
        self.assertTrue(payload["has_execution_brief"])
        self.assertEqual(payload["execution_brief_review_state"], "ready")
        self.assertEqual(payload["execution_brief_review_notes"], "Ready for coding")
        self.assertEqual(payload["execution_brief_review"]["summary"], "Bounded handoff")
        self.assertFalse(payload["execution_brief_review"]["blocked"])
        self.assertIn("approve", payload["execution_brief_review"]["available_actions"])
        self.assertTrue(payload["execution_queue"]["queue_ready"])

    def test_dev_task_detail_patch_updates_execution_brief_review_state(self):
        self.task.execution_brief = {
            "schema_version": "v1",
            "summary": "Bounded handoff",
            "objective": "Implement the explicit handoff",
        }
        self.task.save(update_fields=["execution_brief", "updated_at"])
        request = self._request(
            f"/xyn/api/dev-tasks/{self.task.id}",
            method="patch",
            data=json.dumps(
                {
                "execution_brief_review_state": "approved",
                "execution_brief_review_notes": "Reviewed and approved",
                }
            ),
        )
        with self._auth_patches()[0], self._auth_patches()[1], self._auth_patches()[2]:
            response = dev_task_detail(request, str(self.task.id))
        self.assertEqual(response.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.execution_brief_review_state, "approved")
        self.assertEqual(self.task.execution_brief_review_notes, "Reviewed and approved")
        self.assertEqual(self.task.execution_brief_reviewed_by_id, self.user.id)

    def test_dev_task_detail_patch_supports_review_action_aliases(self):
        self.task.execution_brief = {
            "schema_version": "v1",
            "summary": "Bounded handoff",
            "objective": "Implement the explicit handoff",
        }
        self.task.execution_brief_review_state = "draft"
        self.task.execution_policy = {"require_brief_approval": True}
        self.task.save(update_fields=["execution_brief", "execution_brief_review_state", "execution_policy", "updated_at"])
        request = self._request(
            f"/xyn/api/dev-tasks/{self.task.id}",
            method="patch",
            data=json.dumps({"execution_brief_action": "approve"}),
        )
        with self._auth_patches()[0], self._auth_patches()[1], self._auth_patches()[2]:
            response = dev_task_detail(request, str(self.task.id))
        self.assertEqual(response.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.execution_brief_review_state, "approved")
        payload = json.loads(response.content)
        self.assertEqual(payload["execution_brief_review"]["review_state"], "approved")
        self.assertTrue(payload["execution_brief_review"]["ready"])

    def test_work_item_detail_patch_is_not_blocked_by_csrf_for_authenticated_ui_session(self):
        self.task.execution_brief = {
            "schema_version": "v1",
            "summary": "Bounded handoff",
            "objective": "Implement the explicit handoff",
        }
        self.task.execution_brief_review_state = "draft"
        self.task.execution_policy = {"require_brief_approval": True}
        self.task.save(update_fields=["execution_brief", "execution_brief_review_state", "execution_policy", "updated_at"])

        response = self.csrf_client.patch(
            f"/xyn/api/work-items/{self.task.id}",
            data=json.dumps({"execution_brief_action": "approve"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.execution_brief_review_state, "approved")

    def test_dev_task_detail_patch_regenerates_execution_brief_and_supersedes_prior_version(self):
        self.task.execution_brief = {
            "schema_version": "v1",
            "summary": "Initial brief",
            "revision": 1,
            "objective": "Initial objective",
        }
        self.task.execution_brief_review_state = "rejected"
        self.task.execution_brief_review_notes = "Needs clarification"
        self.task.execution_policy = {"require_brief_approval": True}
        self.task.save(
            update_fields=[
                "execution_brief",
                "execution_brief_review_state",
                "execution_brief_review_notes",
                "execution_policy",
                "updated_at",
            ]
        )
        request = self._request(
            f"/xyn/api/dev-tasks/{self.task.id}",
            method="patch",
            data=json.dumps(
                {
                    "execution_brief_action": "regenerate",
                    "execution_brief_revision_reason": "review_rejected",
                    "execution_brief_review_notes": "Clarified for another pass",
                }
            ),
        )
        with self._auth_patches()[0], self._auth_patches()[1], self._auth_patches()[2], mock.patch(
            "xyn_orchestrator.xyn_api._download_artifact_json", return_value=self.plan_json
        ):
            response = dev_task_detail(request, str(self.task.id))

        self.assertEqual(response.status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.execution_brief["revision"], 2)
        self.assertEqual(self.task.execution_brief["revision_reason"], "review_rejected")
        self.assertEqual(self.task.execution_brief_review_state, "draft")
        self.assertEqual(len(self.task.execution_brief_history), 1)
        self.assertEqual(self.task.execution_brief_history[0]["brief"]["summary"], "Initial brief")
        payload = json.loads(response.content)
        self.assertEqual(payload["execution_brief_revision"], 2)
        self.assertEqual(payload["execution_brief_history_count"], 1)

    def test_duplicate_run_request_reuses_active_runtime_run(self):
        runtime_run_id = uuid.uuid4()
        self.task.runtime_run_id = runtime_run_id
        self.task.runtime_workspace_id = self.workspace.id
        self.task.status = "running"
        self.task.save(update_fields=["runtime_run_id", "runtime_workspace_id", "status", "updated_at"])
        request = self._request(f"/xyn/api/dev-tasks/{self.task.id}/run")

        def _seed_api_request(*, method, path, workspace_id="", workspace_slug="", payload=None, timeout=20):
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}":
                return _FakeResponse(
                    body={
                        "id": str(runtime_run_id),
                        "run_id": str(runtime_run_id),
                        "status": "running",
                        "summary": "In progress",
                        "failure_reason": None,
                        "escalation_reason": None,
                        "prompt_payload": {"target": {"workspace_id": str(self.workspace.id), "repo": "xyn-platform", "branch": "develop"}},
                    }
                )
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}/steps":
                return _FakeResponse(body=[])
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}/artifacts":
                return _FakeResponse(body=[])
            raise AssertionError(f"unexpected call {method} {path}")

        with self._auth_patches()[0], self._auth_patches()[1], self._auth_patches()[2], mock.patch(
            "xyn_orchestrator.xyn_api._seed_api_request", side_effect=_seed_api_request
        ):
            response = dev_task_run(request, str(self.task.id))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["run_id"], str(runtime_run_id))
        self.assertEqual(payload["status"], "running")

    def test_dev_task_detail_reads_status_and_artifacts_from_runtime_run(self):
        runtime_run_id = uuid.uuid4()
        self.task.runtime_run_id = runtime_run_id
        self.task.runtime_workspace_id = self.workspace.id
        self.task.save(update_fields=["runtime_run_id", "runtime_workspace_id", "updated_at"])
        request = self._request(f"/xyn/api/dev-tasks/{self.task.id}", method="get")

        def _seed_api_request(*, method, path, workspace_id="", workspace_slug="", payload=None, timeout=20):
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}":
                return _FakeResponse(
                    body={
                        "id": str(runtime_run_id),
                        "run_id": str(runtime_run_id),
                        "status": "blocked",
                        "summary": "Need review",
                        "failure_reason": "contract_violation",
                        "escalation_reason": "human_review_required",
                        "started_at": "2026-03-11T12:00:00Z",
                        "completed_at": "2026-03-11T12:05:00Z",
                        "prompt_payload": {"target": {"workspace_id": str(self.workspace.id), "repo": "xyn-platform", "branch": "develop"}},
                        "execution_policy": {"auto_continue": True, "max_retries": 2, "require_human_review_on_failure": True, "timeout_seconds": 1800},
                    }
                )
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}/steps":
                return _FakeResponse(
                    body=[
                        {
                            "id": str(uuid.uuid4()),
                            "step_id": str(uuid.uuid4()),
                            "step_key": "execute_codex",
                            "label": "Execute Codex task",
                            "status": "completed",
                            "summary": "Done",
                            "sequence_no": 3,
                        }
                    ]
                )
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}/artifacts":
                return _FakeResponse(
                    body=[
                        {
                            "id": str(uuid.uuid4()),
                            "artifact_id": str(uuid.uuid4()),
                            "artifact_type": "summary",
                            "label": "final_summary.md",
                            "uri": f"artifact://runs/{runtime_run_id}/final_summary.md",
                            "created_at": "2026-03-11T12:05:00Z",
                            "metadata": {},
                        }
                    ]
                )
            raise AssertionError(f"unexpected call {method} {path}")

        with self._auth_patches()[0], self._auth_patches()[1], self._auth_patches()[2], mock.patch(
            "xyn_orchestrator.xyn_api._seed_api_request", side_effect=_seed_api_request
        ):
            response = dev_task_detail(request, str(self.task.id))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["status"], "awaiting_review")
        self.assertEqual(payload["runtime_run_id"], str(runtime_run_id))
        self.assertEqual(payload["execution_run"]["run_id"], str(runtime_run_id))
        self.assertEqual(payload["execution_run"]["state"], "awaiting_review")
        self.assertEqual(payload["execution_run"]["validation_status"], "needs_review")
        self.assertEqual(payload["execution_run"]["artifact_count"], 1)
        self.assertEqual(payload["execution_run"]["artifact_labels"], ["final_summary.md"])
        self.assertEqual(payload["result_run_detail"]["summary"], "Need review")
        self.assertEqual(payload["result_run_detail"]["failure_reason"], "contract_violation")
        self.assertEqual(payload["result_run_detail"]["escalation_reason"], "human_review_required")
        self.assertEqual(payload["result_run_artifacts"][0]["metadata"]["uri"], f"artifact://runs/{runtime_run_id}/final_summary.md")
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "awaiting_review")
        self.assertEqual(self.task.last_error, "human_review_required")

    def test_dev_task_detail_tolerates_non_numeric_runtime_step_sequence(self):
        runtime_run_id = uuid.uuid4()
        self.task.runtime_run_id = runtime_run_id
        self.task.runtime_workspace_id = self.workspace.id
        self.task.save(update_fields=["runtime_run_id", "runtime_workspace_id", "updated_at"])
        request = self._request(f"/xyn/api/dev-tasks/{self.task.id}", method="get")

        def _seed_api_request(*, method, path, workspace_id="", workspace_slug="", payload=None, timeout=20):
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}":
                return _FakeResponse(
                    body={
                        "id": str(runtime_run_id),
                        "run_id": str(runtime_run_id),
                        "status": "queued",
                        "summary": "Queued for execution",
                        "failure_reason": None,
                        "escalation_reason": None,
                        "prompt_payload": {"target": {"workspace_id": str(self.workspace.id), "repo": "xyn-platform", "branch": "develop"}},
                    }
                )
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}/steps":
                return _FakeResponse(
                    body=[
                        {
                            "id": str(uuid.uuid4()),
                            "step_id": str(uuid.uuid4()),
                            "step_key": "inspect_repository",
                            "label": "Inspect repository",
                            "status": "completed",
                            "summary": "Repo inspected",
                            "sequence_no": "phase-inspect",
                            "started_at": "2026-03-11T12:00:00Z",
                        },
                        {
                            "id": str(uuid.uuid4()),
                            "step_id": str(uuid.uuid4()),
                            "step_key": "execute_codex",
                            "label": "Execute Codex task",
                            "status": "queued",
                            "summary": "Waiting for worker",
                            "sequence_no": 2,
                            "started_at": "2026-03-11T12:01:00Z",
                        },
                    ]
                )
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}/artifacts":
                return _FakeResponse(body=[])
            raise AssertionError(f"unexpected call {method} {path}")

        with self._auth_patches()[0], self._auth_patches()[1], self._auth_patches()[2], mock.patch(
            "xyn_orchestrator.xyn_api._seed_api_request", side_effect=_seed_api_request
        ):
            response = dev_task_detail(request, str(self.task.id))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["execution_run"]["run_id"], str(runtime_run_id))
        self.assertEqual(payload["execution_run"]["state"], "queued")
        self.assertEqual(payload["result_run_detail"]["summary"], "Queued for execution")

    def test_dev_task_detail_exposes_ai_agent_override_metadata_from_runtime_payload(self):
        runtime_run_id = uuid.uuid4()
        self.task.runtime_run_id = runtime_run_id
        self.task.runtime_workspace_id = self.workspace.id
        self.task.save(update_fields=["runtime_run_id", "runtime_workspace_id", "updated_at"])
        request = self._request(f"/xyn/api/dev-tasks/{self.task.id}", method="get")

        def _seed_api_request(*, method, path, workspace_id="", workspace_slug="", payload=None, timeout=20):
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}":
                return _FakeResponse(
                    body={
                        "id": str(runtime_run_id),
                        "run_id": str(runtime_run_id),
                        "status": "queued",
                        "summary": None,
                        "failure_reason": None,
                        "escalation_reason": None,
                        "prompt_payload": {
                            "target": {"workspace_id": str(self.workspace.id), "repo": "xyn-platform", "branch": "develop"},
                            "context": {
                                "metadata": {
                                    "ai_agent_selection": {
                                        "purpose": "coding",
                                        "routed_agent_id": "agent-default",
                                        "routed_agent_name": "Bootstrap Default Agent",
                                        "routed_resolution_source": "default_fallback",
                                        "routed_resolution_label": "Default fallback",
                                        "effective_agent_id": "agent-alt",
                                        "effective_agent_name": "Claude Coding Agent",
                                        "effective_resolution_source": "action_override",
                                        "effective_resolution_label": "Action override",
                                        "override_agent_id": "agent-alt",
                                        "override_applied": True,
                                    }
                                }
                            },
                        },
                    }
                )
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}/steps":
                return _FakeResponse(body=[])
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}/artifacts":
                return _FakeResponse(body=[])
            raise AssertionError(f"unexpected call {method} {path}")

        with self._auth_patches()[0], self._auth_patches()[1], self._auth_patches()[2], mock.patch(
            "xyn_orchestrator.xyn_api._seed_api_request", side_effect=_seed_api_request
        ):
            response = dev_task_detail(request, str(self.task.id))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        selection = payload["execution_run"]["agent_selection"]
        self.assertEqual(selection["purpose"], "coding")
        self.assertEqual(selection["routed_agent_name"], "Bootstrap Default Agent")
        self.assertEqual(selection["effective_agent_name"], "Claude Coding Agent")
        self.assertTrue(selection["override_applied"])
        self.assertEqual(selection["effective_resolution_label"], "Action override")

    def test_dev_task_detail_reports_not_started_execution_when_no_run_exists(self):
        request = self._request(f"/xyn/api/dev-tasks/{self.task.id}", method="get")
        with self._auth_patches()[0], self._auth_patches()[1], self._auth_patches()[2]:
            response = dev_task_detail(request, str(self.task.id))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["execution_run"]["has_run"], False)
        self.assertEqual(payload["execution_run"]["state"], "not_started")
        self.assertEqual(payload["execution_run"]["validation_status"], "not_run")
        self.assertEqual(payload["execution_run"]["artifact_count"], 0)
        self.assertEqual(payload["execution_run"]["message"], "No execution run has been dispatched yet.")

    def test_dev_task_detail_uses_result_run_summary_when_runtime_run_missing(self):
        result_run = Run.objects.create(
            entity_type="dev_task",
            entity_id=self.task.id,
            status="succeeded",
            summary="Implemented scheduler seam",
            created_by=self.user,
            started_at=dt.datetime(2026, 3, 12, 15, 0, tzinfo=dt.timezone.utc),
            finished_at=dt.datetime(2026, 3, 12, 15, 5, tzinfo=dt.timezone.utc),
        )
        RunArtifact.objects.create(
            run=result_run,
            name="final_summary.md",
            kind="summary",
            url="https://example.com/final_summary.md",
            metadata_json={},
        )
        self.task.result_run = result_run
        self.task.status = "completed"
        self.task.save(update_fields=["result_run", "status", "updated_at"])
        request = self._request(f"/xyn/api/dev-tasks/{self.task.id}", method="get")

        with self._auth_patches()[0], self._auth_patches()[1], self._auth_patches()[2]:
            response = dev_task_detail(request, str(self.task.id))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["execution_run"]["has_run"], True)
        self.assertEqual(payload["execution_run"]["source"], "result")
        self.assertEqual(payload["execution_run"]["state"], "completed")
        self.assertEqual(payload["execution_run"]["validation_status"], "passed")
        self.assertEqual(payload["execution_run"]["artifact_count"], 1)
        self.assertEqual(payload["execution_run"]["summary"], "Implemented scheduler seam")
        self.assertEqual(payload["result_run_detail"]["summary"], "Implemented scheduler seam")

    def test_retry_submits_new_runtime_run_after_terminal_status(self):
        runtime_run_id = uuid.uuid4()
        new_runtime_run_id = str(uuid.uuid4())
        self.task.runtime_run_id = runtime_run_id
        self.task.runtime_workspace_id = self.workspace.id
        self.task.status = "failed"
        self.task.save(update_fields=["runtime_run_id", "runtime_workspace_id", "status", "updated_at"])
        request = self._request(f"/xyn/api/dev-tasks/{self.task.id}/retry")
        seen = {"post": 0}

        def _seed_api_request(*, method, path, workspace_id="", workspace_slug="", payload=None, timeout=20):
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}":
                return _FakeResponse(
                    body={
                        "id": str(runtime_run_id),
                        "run_id": str(runtime_run_id),
                        "status": "failed",
                        "summary": "Old run failed",
                        "failure_reason": "tests_failed",
                        "escalation_reason": None,
                        "prompt_payload": {"target": {"workspace_id": str(self.workspace.id), "repo": "xyn-platform", "branch": "develop"}},
                    }
                )
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}/steps":
                return _FakeResponse(body=[])
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}/artifacts":
                return _FakeResponse(body=[])
            if method == "POST" and path == "/api/v1/runtime/runs":
                seen["post"] += 1
                return _FakeResponse(body={"id": new_runtime_run_id, "status": "queued"})
            if method == "GET" and path == f"/api/v1/runs/{new_runtime_run_id}":
                return _FakeResponse(
                    body={
                        "id": new_runtime_run_id,
                        "run_id": new_runtime_run_id,
                        "status": "queued",
                        "summary": None,
                        "failure_reason": None,
                        "escalation_reason": None,
                        "prompt_payload": {"target": {"workspace_id": str(self.workspace.id), "repo": "xyn-platform", "branch": "develop"}},
                    }
                )
            if method == "GET" and path == f"/api/v1/runs/{new_runtime_run_id}/steps":
                return _FakeResponse(body=[])
            if method == "GET" and path == f"/api/v1/runs/{new_runtime_run_id}/artifacts":
                return _FakeResponse(body=[])
            raise AssertionError(f"unexpected call {method} {path}")

        with self._auth_patches()[0], self._auth_patches()[1], self._auth_patches()[2], mock.patch(
            "xyn_orchestrator.xyn_api._download_artifact_json", return_value=self.plan_json
        ), mock.patch("xyn_orchestrator.xyn_api._seed_api_request", side_effect=_seed_api_request):
            response = dev_task_retry(request, str(self.task.id))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["run_id"], new_runtime_run_id)
        self.assertEqual(seen["post"], 1)
        self.assertEqual(payload["work_item"]["execution_recovery"]["retryable"], False)
        self.task.refresh_from_db()
        self.assertEqual(str(self.task.runtime_run_id), new_runtime_run_id)
        self.assertEqual(
            (self.task.execution_policy or {}).get("recovery", {}).get("last_failure", {}).get("run_id"),
            str(runtime_run_id),
        )

    def test_retry_rejects_in_flight_runtime_task(self):
        runtime_run_id = uuid.uuid4()
        self.task.runtime_run_id = runtime_run_id
        self.task.runtime_workspace_id = self.workspace.id
        self.task.status = "running"
        self.task.save(update_fields=["runtime_run_id", "runtime_workspace_id", "status", "updated_at"])
        request = self._request(f"/xyn/api/dev-tasks/{self.task.id}/retry")

        def _seed_api_request(*, method, path, workspace_id="", workspace_slug="", payload=None, timeout=20):
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}":
                return _FakeResponse(
                    body={
                        "id": str(runtime_run_id),
                        "run_id": str(runtime_run_id),
                        "status": "running",
                        "summary": "Still running",
                        "prompt_payload": {"target": {"workspace_id": str(self.workspace.id), "repo": "xyn-platform", "branch": "develop"}},
                    }
                )
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}/steps":
                return _FakeResponse(body=[])
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}/artifacts":
                return _FakeResponse(body=[])
            raise AssertionError(f"unexpected call {method} {path}")

        with self._auth_patches()[0], self._auth_patches()[1], self._auth_patches()[2], mock.patch(
            "xyn_orchestrator.xyn_api._seed_api_request", side_effect=_seed_api_request
        ):
            response = dev_task_retry(request, str(self.task.id))

        self.assertEqual(response.status_code, 409)
        payload = json.loads(response.content)
        self.assertIn("already in progress", payload["error"])

    def test_retry_allows_awaiting_review_task_after_unsafe_repository_state(self):
        runtime_run_id = uuid.uuid4()
        new_runtime_run_id = str(uuid.uuid4())
        self.task.runtime_run_id = runtime_run_id
        self.task.runtime_workspace_id = self.workspace.id
        self.task.status = "awaiting_review"
        self.task.execution_brief_review_state = "approved"
        self.task.execution_policy = {
            "require_brief_approval": True,
            "recovery": {
                "last_failure": {
                    "run_id": str(runtime_run_id),
                    "source": "runtime",
                    "state": "awaiting_review",
                    "summary": "Repository is dirty",
                    "error": "unsafe_repository_state",
                }
            },
        }
        self.task.save(
            update_fields=[
                "runtime_run_id",
                "runtime_workspace_id",
                "status",
                "execution_brief_review_state",
                "execution_policy",
                "updated_at",
            ]
        )
        request = self._request(f"/xyn/api/dev-tasks/{self.task.id}/retry")

        def _seed_api_request(*, method, path, workspace_id="", workspace_slug="", payload=None, timeout=20):
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}":
                return _FakeResponse(
                    body={
                        "id": str(runtime_run_id),
                        "run_id": str(runtime_run_id),
                        "status": "blocked",
                        "summary": "Repository is dirty",
                        "failure_reason": "unsafe_repository_state",
                        "escalation_reason": "unsafe_repository_state",
                        "prompt_payload": {"target": {"workspace_id": str(self.workspace.id), "repo": "xyn-platform", "branch": "develop"}},
                    }
                )
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}/steps":
                return _FakeResponse(body=[])
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}/artifacts":
                return _FakeResponse(body=[])
            if method == "POST" and path == "/api/v1/runtime/runs":
                return _FakeResponse(body={"id": new_runtime_run_id, "status": "queued"})
            if method == "GET" and path == f"/api/v1/runs/{new_runtime_run_id}":
                return _FakeResponse(
                    body={
                        "id": new_runtime_run_id,
                        "run_id": new_runtime_run_id,
                        "status": "queued",
                        "summary": None,
                        "failure_reason": None,
                        "escalation_reason": None,
                        "prompt_payload": {"target": {"workspace_id": str(self.workspace.id), "repo": "xyn-platform", "branch": "develop"}},
                    }
                )
            if method == "GET" and path == f"/api/v1/runs/{new_runtime_run_id}/steps":
                return _FakeResponse(body=[])
            if method == "GET" and path == f"/api/v1/runs/{new_runtime_run_id}/artifacts":
                return _FakeResponse(body=[])
            raise AssertionError(f"unexpected call {method} {path}")

        with self._auth_patches()[0], self._auth_patches()[1], self._auth_patches()[2], mock.patch(
            "xyn_orchestrator.xyn_api._seed_api_request", side_effect=_seed_api_request
        ), mock.patch("xyn_orchestrator.xyn_api._download_artifact_json", return_value=self.plan_json):
            response = dev_task_retry(request, str(self.task.id))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["status"], "queued")
        self.assertEqual(payload["run_id"], new_runtime_run_id)

    def test_requeue_clears_failed_runtime_run_and_returns_task_to_queue(self):
        runtime_run_id = uuid.uuid4()
        self.task.runtime_run_id = runtime_run_id
        self.task.runtime_workspace_id = self.workspace.id
        self.task.status = "failed"
        self.task.last_error = "tests_failed"
        self.task.execution_brief = {
            "schema_version": "v1",
            "summary": "Recover the scheduler",
            "objective": "Retry the bounded code change.",
        }
        self.task.execution_brief_review_state = "approved"
        self.task.execution_policy = {"require_brief_approval": True}
        self.task.save(
            update_fields=[
                "runtime_run_id",
                "runtime_workspace_id",
                "status",
                "last_error",
                "execution_brief",
                "execution_brief_review_state",
                "execution_policy",
                "updated_at",
            ]
        )
        request = self._request(f"/xyn/api/dev-tasks/{self.task.id}/requeue")

        def _seed_api_request(*, method, path, workspace_id="", workspace_slug="", payload=None, timeout=20):
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}":
                return _FakeResponse(
                    body={
                        "id": str(runtime_run_id),
                        "run_id": str(runtime_run_id),
                        "status": "failed",
                        "summary": "Unit tests failed",
                        "failure_reason": "tests_failed",
                        "prompt_payload": {"target": {"workspace_id": str(self.workspace.id), "repo": "xyn-platform", "branch": "develop"}},
                    }
                )
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}/steps":
                return _FakeResponse(body=[])
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}/artifacts":
                return _FakeResponse(body=[])
            raise AssertionError(f"unexpected call {method} {path}")

        with self._auth_patches()[0], self._auth_patches()[1], self._auth_patches()[2], mock.patch(
            "xyn_orchestrator.xyn_api._seed_api_request", side_effect=_seed_api_request
        ):
            response = dev_task_requeue(request, str(self.task.id))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["status"], "queued")
        self.assertEqual(payload["work_item"]["status"], "queued")
        self.assertTrue(payload["work_item"]["execution_queue"]["queue_ready"])
        self.assertEqual(payload["work_item"]["execution_recovery"]["status"], "requeued")
        self.task.refresh_from_db()
        self.assertIsNone(self.task.runtime_run_id)
        self.assertEqual(self.task.status, "queued")
        self.assertEqual(
            (self.task.execution_policy or {}).get("recovery", {}).get("last_failure", {}).get("run_id"),
            str(runtime_run_id),
        )

    def test_conversation_execution_context_uses_durable_task_and_artifact_state(self):
        runtime_run_id = uuid.uuid4()
        self.task.runtime_run_id = runtime_run_id
        self.task.runtime_workspace_id = self.workspace.id
        self.task.source_conversation_id = "thread-1"
        self.task.status = "running"
        self.task.save(
            update_fields=["runtime_run_id", "runtime_workspace_id", "source_conversation_id", "status", "updated_at"]
        )

        def _seed_api_request(*, method, path, workspace_id="", workspace_slug="", payload=None, timeout=20):
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}":
                return _FakeResponse(
                    body={
                        "id": str(runtime_run_id),
                        "run_id": str(runtime_run_id),
                        "status": "running",
                        "summary": "In progress",
                        "prompt_payload": {"target": {"workspace_id": str(self.workspace.id), "repo": "xyn-platform", "branch": "develop"}},
                    }
                )
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}/steps":
                return _FakeResponse(body=[])
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}/artifacts":
                return _FakeResponse(
                    body=[
                        {
                            "id": str(uuid.uuid4()),
                            "artifact_id": str(uuid.uuid4()),
                            "artifact_type": "summary",
                            "label": "final_summary.md",
                            "uri": f"artifact://runs/{runtime_run_id}/final_summary.md",
                            "created_at": "2026-03-11T12:05:00Z",
                            "metadata": {},
                        }
                    ]
                )
            raise AssertionError(f"unexpected call {method} {path}")

        with mock.patch("xyn_orchestrator.xyn_api._seed_api_request", side_effect=_seed_api_request):
            context = _conversation_execution_context(self.identity, str(self.workspace.id), "thread-1")

        self.assertEqual(context.current_work_item_id, "epic-c-bridge")
        self.assertEqual(context.current_run_id, str(runtime_run_id))
        self.assertEqual(context.recent_artifacts[0].artifact_type, "summary")

    def test_blueprint_dev_tasks_projects_runtime_status(self):
        runtime_run_id = uuid.uuid4()
        self.task.runtime_run_id = runtime_run_id
        self.task.runtime_workspace_id = self.workspace.id
        self.task.save(update_fields=["runtime_run_id", "runtime_workspace_id", "updated_at"])
        request = self._request(f"/xyn/api/blueprints/{self.task.source_entity_id}/dev-tasks", method="get")

        def _seed_api_request(*, method, path, workspace_id="", workspace_slug="", payload=None, timeout=20):
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}":
                return _FakeResponse(
                    body={
                        "id": str(runtime_run_id),
                        "run_id": str(runtime_run_id),
                        "status": "running",
                        "summary": "Bridged runtime run",
                        "prompt_payload": {"target": {"workspace_id": str(self.workspace.id), "repo": "xyn-platform", "branch": "develop"}},
                    }
                )
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}/steps":
                return _FakeResponse(body=[])
            if method == "GET" and path == f"/api/v1/runs/{runtime_run_id}/artifacts":
                return _FakeResponse(body=[])
            raise AssertionError(f"unexpected call {method} {path}")

        with mock.patch("xyn_orchestrator.xyn_api._require_staff", return_value=None), mock.patch(
            "xyn_orchestrator.xyn_api._seed_api_request", side_effect=_seed_api_request
        ):
            response = blueprint_dev_tasks(request, str(self.task.source_entity_id))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["dev_tasks"][0]["status"], "running")
        self.assertEqual(payload["dev_tasks"][0]["runtime_run_id"], str(runtime_run_id))
