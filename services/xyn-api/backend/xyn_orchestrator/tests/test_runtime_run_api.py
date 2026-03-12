import json
import uuid
from unittest import mock

from django.test import RequestFactory, SimpleTestCase

from xyn_orchestrator.models import Workspace
from xyn_orchestrator.xyn_api import (
    ai_activity_stream,
    _runtime_activity_item_from_event,
    _runtime_stream_envelope_from_event,
    runtime_run_detail,
    runtime_runs_collection,
)


class _FakeResponse:
    def __init__(self, *, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.headers = {"content-type": "application/json"}
        self.content = json.dumps(self._body).encode("utf-8")

    def json(self):
        return self._body


class RuntimeRunApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.identity = object()
        self.workspace = Workspace(id=uuid.uuid4(), slug="runtime-ws", name="Runtime WS")

    def test_active_runs_query_returns_expected_fields(self):
        run_id = str(uuid.uuid4())
        request = self.factory.get("/api/runtime/runs", {"workspace_id": str(self.workspace.id)})
        request.user = mock.Mock(is_authenticated=True)
        core_body = {
            "items": [
                {
                    "id": run_id,
                    "run_id": run_id,
                    "status": "running",
                    "created_at": "2026-03-11T10:00:00Z",
                    "started_at": "2026-03-11T10:00:05Z",
                    "heartbeat_at": "2026-03-11T10:00:10Z",
                    "work_item_id": "wi-123",
                    "thread_id": "thread-1",
                    "worker_type": "codex_local",
                    "worker_id": "codex-local-1",
                    "summary": "Running Codex task",
                    "prompt_payload": {
                        "target": {"repo": "xyn-platform", "branch": "develop", "workspace_id": str(self.workspace.id), "artifact_id": None},
                        "context": {"metadata": {"thread_id": "thread-1"}},
                    },
                }
            ]
        }
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api._resolve_workspace_for_identity", return_value=self.workspace
        ), mock.patch("xyn_orchestrator.xyn_api._seed_api_request", return_value=_FakeResponse(body=core_body)):
            response = runtime_runs_collection(request)

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(len(payload["runs"]), 1)
        item = payload["runs"][0]
        self.assertEqual(item["run_id"], run_id)
        self.assertEqual(item["work_item_id"], "wi-123")
        self.assertEqual(item["thread_id"], "thread-1")
        self.assertEqual(item["worker_type"], "codex_local")
        self.assertEqual(item["target"]["repo"], "xyn-platform")
        self.assertIn(item["heartbeat_freshness"], {"fresh", "stale"})

    def test_run_detail_returns_run_steps_and_artifacts(self):
        run_id = uuid.uuid4()
        request = self.factory.get(f"/api/runtime/runs/{run_id}", {"workspace_id": str(self.workspace.id)})
        request.user = mock.Mock(is_authenticated=True)
        run_body = {
            "id": str(run_id),
            "run_id": str(run_id),
            "status": "blocked",
            "summary": "Need human review",
            "failure_reason": "contract_violation",
            "escalation_reason": "human_review_required",
            "created_at": "2026-03-11T10:00:00Z",
            "started_at": "2026-03-11T10:00:05Z",
            "heartbeat_at": "2026-03-11T10:00:10Z",
            "worker_type": "codex_local",
            "worker_id": "codex-local-1",
            "execution_policy": {
                "auto_continue": True,
                "max_retries": 1,
                "require_human_review_on_failure": True,
                "timeout_seconds": 1800,
            },
            "prompt_payload": {
                "prompt": {"title": "Implement worker registration", "body": "Make it work."},
                "target": {"repo": "xyn", "branch": "develop", "workspace_id": str(self.workspace.id), "artifact_id": None},
            },
        }
        steps_body = [
            {
                "id": str(uuid.uuid4()),
                "step_id": str(uuid.uuid4()),
                "step_key": "inspect_repository",
                "label": "Inspect repository",
                "status": "completed",
                "summary": "Repo inspected",
                "sequence_no": 1,
                "started_at": "2026-03-11T10:00:06Z",
                "completed_at": "2026-03-11T10:00:07Z",
            }
        ]
        artifacts_body = [
            {
                "id": str(uuid.uuid4()),
                "artifact_id": str(uuid.uuid4()),
                "artifact_type": "summary",
                "label": "Final summary",
                "uri": f"artifact://runs/{run_id}/final_summary.md",
                "created_at": "2026-03-11T10:00:20Z",
                "metadata": {},
            }
        ]
        responses = [_FakeResponse(body=run_body), _FakeResponse(body=steps_body), _FakeResponse(body=artifacts_body)]
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api._resolve_workspace_for_identity", return_value=self.workspace
        ), mock.patch("xyn_orchestrator.xyn_api._seed_api_request", side_effect=responses):
            response = runtime_run_detail(request, run_id)

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["escalation_reason"], "human_review_required")
        self.assertEqual(payload["steps"][0]["step_key"], "inspect_repository")
        self.assertEqual(payload["artifacts"][0]["artifact_type"], "summary")

    def test_runtime_activity_items_map_terminal_states(self):
        completed = _runtime_activity_item_from_event(
            {
                "id": str(uuid.uuid4()),
                "event_name": "run.completed",
                "occurred_at": "2026-03-11T10:00:00Z",
                "run_id": "run-1",
                "data": {"workspace_id": "ws-1", "worker_type": "codex_local"},
            }
        )
        failed = _runtime_activity_item_from_event(
            {
                "id": str(uuid.uuid4()),
                "event_name": "run.failed",
                "occurred_at": "2026-03-11T10:00:00Z",
                "run_id": "run-2",
                "data": {"workspace_id": "ws-1", "failure_reason": "worker_unresponsive", "worker_type": "codex_local"},
            }
        )
        blocked = _runtime_activity_item_from_event(
            {
                "id": str(uuid.uuid4()),
                "event_name": "run.blocked",
                "occurred_at": "2026-03-11T10:00:00Z",
                "run_id": "run-3",
                "data": {"workspace_id": "ws-1", "escalation_reason": "contract ambiguity", "worker_type": "codex_local"},
            }
        )

        self.assertEqual(completed["status"], "succeeded")
        self.assertIn("Run completed", completed["summary"])
        self.assertEqual((completed.get("conversation_message") or {}).get("message_type"), "execution_summary")
        self.assertEqual((((completed.get("conversation_message") or {}).get("refs") or {}).get("run_id")), "run-1")
        self.assertEqual(failed["status"], "failed")
        self.assertIn("worker_unresponsive", failed["summary"])
        self.assertEqual(blocked["status"], "failed")
        self.assertIn("contract ambiguity", blocked["summary"])

    def test_runtime_stream_envelope_preserves_core_fields(self):
        envelope = _runtime_stream_envelope_from_event(
            {
                "id": str(uuid.uuid4()),
                "event_name": "run.step.completed",
                "occurred_at": "2026-03-11T10:00:00Z",
                "run_id": "run-1",
                "data": {
                    "workspace_id": str(self.workspace.id),
                    "thread_id": "thread-1",
                    "work_item_id": "wi-1",
                    "worker_type": "codex_local",
                    "status": "running",
                    "step_key": "inspect_repository",
                    "label": "Inspect repository",
                },
            }
        )
        self.assertEqual(envelope["workspace_id"], str(self.workspace.id))
        self.assertEqual(envelope["thread_id"], "thread-1")
        self.assertEqual(envelope["run_id"], "run-1")
        self.assertEqual(envelope["worker_type"], "codex_local")
        self.assertEqual(envelope["event_type"], "run.step.completed")

    def test_runtime_activity_stream_enforces_workspace_scope_and_streams_envelopes(self):
        request = self.factory.get("/xyn/api/ai/activity/stream", {"workspace_id": str(self.workspace.id), "thread_id": "thread-1"})
        request.user = mock.Mock(is_authenticated=True)

        class _FakeStreamResponse:
            def __init__(self, lines):
                self._lines = lines

            def raise_for_status(self):
                return None

            def iter_lines(self, decode_unicode=True):
                for line in self._lines:
                    yield line

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        upstream_lines = [
            "id: evt-1",
            "event: run.started",
            "data: "
            + json.dumps(
                {
                    "id": "evt-1",
                    "event_name": "run.started",
                    "occurred_at": "2026-03-11T10:00:00Z",
                    "run_id": "run-1",
                    "data": {"workspace_id": str(self.workspace.id), "thread_id": "thread-1", "worker_type": "codex_local", "work_item_id": "wi-1", "status": "running"},
                }
            ),
            "",
            "id: evt-2",
            "event: run.started",
            "data: "
            + json.dumps(
                {
                    "id": "evt-2",
                    "event_name": "run.started",
                    "occurred_at": "2026-03-11T10:00:01Z",
                    "run_id": "run-2",
                    "data": {"workspace_id": str(self.workspace.id), "thread_id": "thread-2", "worker_type": "codex_local", "work_item_id": "wi-2", "status": "running"},
                }
            ),
            "",
        ]
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api._resolve_workspace_for_identity", return_value=self.workspace
        ), mock.patch("xyn_orchestrator.xyn_api._seed_runtime_stream_request", return_value=_FakeStreamResponse(upstream_lines)):
            response = ai_activity_stream(request)
            self.assertEqual(response.status_code, 200)
            body = "".join(chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk) for chunk in response.streaming_content)
        self.assertIn("event: run.started", body)
        self.assertIn("\"workspace_id\":", body)
        self.assertIn("\"thread_id\": \"thread-1\"", body)
        self.assertIn("evt-1", body)
        self.assertNotIn("evt-2", body)
