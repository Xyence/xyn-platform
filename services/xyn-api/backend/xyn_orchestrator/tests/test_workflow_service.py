import json
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from xyn_orchestrator.models import CoordinationThread, DevTask, Run, UserIdentity, Workspace
from xyn_orchestrator.workflows.workflow_service import get_draft_workflow
from xyn_orchestrator.xyn_api import draft_workflow


class WorkflowServiceTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="draft-flow-admin", password="pass", is_staff=True)
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer",
            subject="draft-flow-admin",
            email="draft-flow-admin@example.com",
        )
        self.workspace = Workspace.objects.create(name="Draft Flow", slug="draft-flow")
        self.factory = RequestFactory()

    def _draft(self, status: str) -> dict:
        return {
            "id": "draft-123",
            "workspace_id": str(self.workspace.id),
            "type": "app_intent",
            "title": "Team Lunch Poll",
            "status": status,
            "content_json": {"initial_intent": {"requested_entities": ["polls"]}} if status != "draft" else {},
        }

    def _job(self, job_id: str, status: str, *, source_job_id: str = "", work_item_id: str = "") -> dict:
        input_json = {"draft_id": "draft-123"}
        if source_job_id:
            input_json["source_job_id"] = source_job_id
        if work_item_id:
            input_json["work_item_id"] = work_item_id
        return {
            "id": job_id,
            "status": status,
            "input_json": input_json,
            "output_json": {},
            "created_at": f"2026-03-16T10:00:0{job_id[-1]}Z",
            "updated_at": f"2026-03-16T10:00:0{job_id[-1]}Z",
        }

    def test_service_returns_draft_state_before_plan(self):
        payload = get_draft_workflow(workspace=self.workspace, draft=self._draft("draft"), jobs=[])
        self.assertEqual(payload["state"], "draft")
        self.assertFalse(payload["plan_available"])
        self.assertIsNone(payload["thread_id"])
        self.assertIsNone(payload["active_run_id"])

    def test_service_returns_plan_ready_when_draft_is_ready(self):
        payload = get_draft_workflow(workspace=self.workspace, draft=self._draft("ready"), jobs=[])
        self.assertEqual(payload["state"], "plan_ready")
        self.assertTrue(payload["plan_available"])

    def test_service_returns_submitted_when_no_jobs_exist_yet(self):
        payload = get_draft_workflow(workspace=self.workspace, draft=self._draft("submitted"), jobs=[])
        self.assertEqual(payload["state"], "submitted")

    def test_service_returns_queued_from_related_job_state(self):
        payload = get_draft_workflow(
            workspace=self.workspace,
            draft=self._draft("submitted"),
            jobs=[self._job("job-1", "queued")],
        )
        self.assertEqual(payload["state"], "queued")
        self.assertEqual(payload["last_run_status"], "queued")

    def test_service_resolves_thread_and_run_from_work_item(self):
        thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            title="Build Team Lunch Poll",
            owner=self.identity,
            status="active",
            domain="development",
        )
        task = DevTask.objects.create(
            title="Implement poll workflow",
            task_type="codegen",
            status="running",
            source_entity_type="application",
            source_entity_id=uuid.uuid4(),
            work_item_id="wi-team-lunch",
            coordination_thread=thread,
        )
        run = Run.objects.create(
            entity_type="dev_task",
            entity_id=task.id,
            status="running",
            created_by=self.user,
        )
        task.result_run = run
        task.save(update_fields=["result_run", "updated_at"])

        payload = get_draft_workflow(
            workspace=self.workspace,
            draft=self._draft("submitted"),
            jobs=[self._job("job-2", "running", work_item_id="wi-team-lunch")],
        )

        self.assertEqual(payload["state"], "executing")
        self.assertEqual(payload["thread_id"], str(thread.id))
        self.assertEqual(payload["active_run_id"], str(run.id))
        self.assertEqual(payload["last_run_status"], "running")

    def test_service_returns_completed_when_local_run_succeeded(self):
        thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            title="Build Team Lunch Poll",
            owner=self.identity,
            status="completed",
            domain="development",
        )
        task = DevTask.objects.create(
            title="Implement poll workflow",
            task_type="codegen",
            status="completed",
            source_entity_type="application",
            source_entity_id=uuid.uuid4(),
            work_item_id="wi-team-lunch-complete",
            coordination_thread=thread,
        )
        run = Run.objects.create(
            entity_type="dev_task",
            entity_id=task.id,
            status="succeeded",
            created_by=self.user,
        )
        task.result_run = run
        task.save(update_fields=["result_run", "updated_at"])

        payload = get_draft_workflow(
            workspace=self.workspace,
            draft=self._draft("submitted"),
            jobs=[self._job("job-3", "succeeded", work_item_id="wi-team-lunch-complete")],
        )

        self.assertEqual(payload["state"], "completed")
        self.assertEqual(payload["last_run_status"], "succeeded")

    def test_service_returns_failed_when_related_job_failed(self):
        payload = get_draft_workflow(
            workspace=self.workspace,
            draft=self._draft("submitted"),
            jobs=[self._job("job-4", "failed")],
        )
        self.assertEqual(payload["state"], "failed")
        self.assertEqual(payload["last_run_status"], "failed")

    def test_endpoint_returns_workflow_summary(self):
        request = self.factory.get(
            f"/xyn/api/draft_workflow?draft_id=draft-123&workspace_id={self.workspace.id}"
        )
        request.user = self.user

        draft_response = mock.Mock(status_code=200, content=b"{}", json=mock.Mock(return_value=self._draft("submitted")))
        jobs_response = mock.Mock(
            status_code=200,
            content=b"[]",
            json=mock.Mock(return_value=[self._job("job-5", "queued")]),
        )

        with (
            mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity),
            mock.patch("xyn_orchestrator.xyn_api._resolve_workspace_for_identity", return_value=self.workspace),
            mock.patch("xyn_orchestrator.xyn_api._seed_api_request", side_effect=[draft_response, jobs_response]),
        ):
            response = draft_workflow(request)

        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = json.loads(response.content)
        self.assertEqual(payload["draft_id"], "draft-123")
        self.assertEqual(payload["state"], "queued")
