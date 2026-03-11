import json
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from xyn_orchestrator.models import DevTask, Run, UserIdentity, Workspace, WorkspaceMembership
from xyn_orchestrator.xyn_api import blueprint_dev_tasks, dev_task_detail, dev_task_retry, dev_task_run


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

    def _request(self, path: str, *, method: str = "post", query: dict | None = None):
        request = getattr(self.factory, method.lower())(path, data=query or {})
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
        self.assertEqual(runtime_payload["policy"]["max_retries"], 2)
        self.assertIn("report", runtime_payload["requested_outputs"])

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
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["runtime_run_id"], str(runtime_run_id))
        self.assertEqual(payload["result_run_detail"]["summary"], "Need review")
        self.assertEqual(payload["result_run_detail"]["failure_reason"], "contract_violation")
        self.assertEqual(payload["result_run_detail"]["escalation_reason"], "human_review_required")
        self.assertEqual(payload["result_run_artifacts"][0]["metadata"]["uri"], f"artifact://runs/{runtime_run_id}/final_summary.md")
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "blocked")
        self.assertEqual(self.task.last_error, "human_review_required")

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
            raise AssertionError(f"unexpected call {method} {path}")

        with self._auth_patches()[0], self._auth_patches()[1], self._auth_patches()[2], mock.patch(
            "xyn_orchestrator.xyn_api._download_artifact_json", return_value=self.plan_json
        ), mock.patch("xyn_orchestrator.xyn_api._seed_api_request", side_effect=_seed_api_request):
            response = dev_task_retry(request, str(self.task.id))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["run_id"], new_runtime_run_id)
        self.assertEqual(seen["post"], 1)
        self.task.refresh_from_db()
        self.assertEqual(str(self.task.runtime_run_id), new_runtime_run_id)

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
