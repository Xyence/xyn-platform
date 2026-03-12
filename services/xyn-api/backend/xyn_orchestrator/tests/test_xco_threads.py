import json
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from xyn_orchestrator.models import CoordinationEvent, CoordinationThread, DevTask, UserIdentity, Workspace, WorkspaceMembership
from xyn_orchestrator.xco import derive_work_queue
from xyn_orchestrator.xyn_api import _dispatch_next_queue_item, _update_thread_status_from_tasks, thread_detail, threads_collection, xco_queue_collection


class XcoThreadTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="xco-admin", email="xco@example.com", password="password")
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example.com",
            subject="xco-admin",
            email="xco@example.com",
        )
        self.workspace = Workspace.objects.create(name="XCO Workspace", slug="xco-workspace")
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

    def _auth_patches(self):
        return (
            mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity),
            mock.patch("xyn_orchestrator.xyn_api._resolve_workspace_for_identity", return_value=self.workspace),
        )

    def _create_thread(self, **overrides) -> CoordinationThread:
        defaults = {
            "workspace": self.workspace,
            "title": "Runtime Refactor",
            "description": "",
            "owner": self.identity,
            "priority": "normal",
            "status": "active",
            "domain": "development",
            "work_in_progress_limit": 1,
            "execution_policy": {},
            "source_conversation_id": "thread-1",
        }
        defaults.update(overrides)
        return CoordinationThread.objects.create(**defaults)

    def _create_task(self, thread: CoordinationThread, **overrides) -> DevTask:
        defaults = {
            "title": f"Task {uuid.uuid4().hex[:6]}",
            "task_type": "codegen",
            "status": "queued",
            "priority": 0,
            "max_attempts": 3,
            "source_entity_type": "blueprint",
            "source_entity_id": uuid.uuid4(),
            "work_item_id": f"wi-{uuid.uuid4().hex[:6]}",
            "created_by": self.user,
            "updated_by": self.user,
            "coordination_thread": thread,
        }
        defaults.update(overrides)
        return DevTask.objects.create(**defaults)

    def test_thread_create_list_and_invalid_transition_are_supported(self):
        create_request = self._request(
            "/xyn/api/threads",
            method="post",
            data=json.dumps({"workspace_id": str(self.workspace.id), "title": "Queue Reliability", "priority": "high"}),
        )
        with self._auth_patches()[0], self._auth_patches()[1]:
            create_response = threads_collection(create_request)
        self.assertEqual(create_response.status_code, 201)
        created = json.loads(create_response.content)
        self.assertEqual(created["title"], "Queue Reliability")
        self.assertEqual(created["priority"], "high")

        list_request = self._request("/xyn/api/threads", data={"workspace_id": str(self.workspace.id)})
        with self._auth_patches()[0], self._auth_patches()[1]:
            list_response = threads_collection(list_request)
        self.assertEqual(list_response.status_code, 200)
        listing = json.loads(list_response.content)
        self.assertEqual(len(listing["threads"]), 1)

        thread = CoordinationThread.objects.get(id=created["id"])
        patch_request = self._request(
            f"/xyn/api/threads/{thread.id}",
            method="patch",
            data=json.dumps({"status": "queued"}),
        )
        with self._auth_patches()[0]:
            patch_response = thread_detail(patch_request, str(thread.id))
        self.assertEqual(patch_response.status_code, 409)

    def test_work_item_can_reference_thread_durably(self):
        thread = self._create_thread()
        task = self._create_task(thread)
        self.assertEqual(str(task.coordination_thread_id), str(thread.id))
        self.assertEqual(thread.work_items.count(), 1)

    def test_thread_can_exist_without_work_items(self):
        thread = self._create_thread(title="Empty Thread")
        self.assertEqual(thread.work_items.count(), 0)

    def test_derive_work_queue_orders_by_priority_then_created_at(self):
        high = self._create_thread(title="High", priority="high")
        normal_older = self._create_thread(title="Normal Older", priority="normal")
        normal_newer = self._create_thread(title="Normal Newer", priority="normal")
        CoordinationThread.objects.filter(id=normal_older.id).update(created_at=timezone.now() - timezone.timedelta(hours=1))
        normal_older.refresh_from_db()
        self._create_task(high, work_item_id="wi-high")
        self._create_task(normal_older, work_item_id="wi-normal-older")
        self._create_task(normal_newer, work_item_id="wi-normal-newer")

        queue = derive_work_queue(
            threads=CoordinationThread.objects.filter(id__in=[high.id, normal_older.id, normal_newer.id]).prefetch_related("work_items"),
            status_lookup=lambda task: task.status,
            task_lookup=lambda work_item_id: DevTask.objects.filter(work_item_id=work_item_id).first(),
        )

        self.assertEqual([entry.work_item_id for entry in queue], ["wi-high", "wi-normal-older", "wi-normal-newer"])

    def test_derive_work_queue_respects_wip_pause_and_dependency_blocks(self):
        running_thread = self._create_thread(title="Running", execution_policy={"max_concurrent_runs": 1})
        self._create_task(running_thread, status="running", work_item_id="wi-running")
        self._create_task(running_thread, status="queued", work_item_id="wi-blocked-by-wip")

        paused_thread = self._create_thread(title="Paused", status="paused")
        self._create_task(paused_thread, status="queued", work_item_id="wi-paused")

        dependency_thread = self._create_thread(title="Dependency")
        blocked = self._create_task(dependency_thread, status="queued", work_item_id="wi-dependent", dependency_work_item_ids=["wi-missing"])

        eligible_thread = self._create_thread(title="Eligible", priority="high")
        self._create_task(eligible_thread, status="queued", work_item_id="wi-eligible")

        queue = derive_work_queue(
            threads=CoordinationThread.objects.all().prefetch_related("work_items"),
            status_lookup=lambda task: task.status,
            task_lookup=lambda work_item_id: DevTask.objects.filter(work_item_id=work_item_id).first(),
        )

        self.assertEqual([entry.work_item_id for entry in queue], ["wi-eligible"])
        self.assertTrue(blocked.dependency_work_item_ids)

    def test_derive_work_queue_excludes_review_required_threads(self):
        review_thread = self._create_thread(
            title="Needs Review",
            execution_policy={"review_required": True},
        )
        self._create_task(review_thread, status="queued", work_item_id="wi-review")

        queue = derive_work_queue(
            threads=CoordinationThread.objects.filter(id=review_thread.id).prefetch_related("work_items"),
            status_lookup=lambda task: task.status,
            task_lookup=lambda work_item_id: DevTask.objects.filter(work_item_id=work_item_id).first(),
        )

        self.assertEqual(queue, [])

    def test_update_thread_status_from_tasks_applies_pause_and_completion_rules(self):
        failed_thread = self._create_thread(title="Pause On Failure", execution_policy={"pause_on_failure": True})
        self._create_task(failed_thread, status="failed", work_item_id="wi-failed")
        _update_thread_status_from_tasks(failed_thread)
        failed_thread.refresh_from_db()
        self.assertEqual(failed_thread.status, "paused")

        complete_thread = self._create_thread(title="Complete", status="active")
        self._create_task(complete_thread, status="completed", work_item_id="wi-complete")
        _update_thread_status_from_tasks(complete_thread)
        complete_thread.refresh_from_db()
        self.assertEqual(complete_thread.status, "completed")

    def test_update_thread_status_from_tasks_auto_resumes_queued_thread(self):
        queued_thread = self._create_thread(
            title="Auto Resume",
            status="queued",
            execution_policy={"auto_resume": True},
        )
        self._create_task(queued_thread, status="queued", work_item_id="wi-queued")
        _update_thread_status_from_tasks(queued_thread)
        queued_thread.refresh_from_db()
        self.assertEqual(queued_thread.status, "active")

    def test_xco_queue_endpoint_returns_derived_items(self):
        thread = self._create_thread(priority="critical")
        self._create_task(thread, work_item_id="wi-queue")
        request = self._request("/xyn/api/xco/queue", data={"workspace_id": str(self.workspace.id)})
        with self._auth_patches()[0], self._auth_patches()[1]:
            response = xco_queue_collection(request)
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["items"][0]["work_item_id"], "wi-queue")
        self.assertEqual(payload["items"][0]["thread_priority"], "critical")

    def test_dispatch_next_queue_item_creates_runtime_dispatch_and_events(self):
        thread = self._create_thread(status="queued", priority="high", execution_policy={"auto_resume": True})
        task = self._create_task(thread, work_item_id="wi-dispatch")

        with mock.patch(
            "xyn_orchestrator.xyn_api._submit_dev_task_runtime_run",
            return_value={"run_id": "run-123", "status": "queued", "work_item_id": "wi-dispatch"},
        ):
            result = _dispatch_next_queue_item(workspace=self.workspace, user=self.user, identity=self.identity)

        self.assertEqual(result["run_id"], "run-123")
        thread.refresh_from_db()
        self.assertEqual(thread.status, "active")
        event_types = list(CoordinationEvent.objects.filter(thread=thread).values_list("event_type", flat=True))
        self.assertIn("thread_active", event_types)
        self.assertIn("work_item_promoted", event_types)
        self.assertIn("run_dispatched_from_queue", event_types)
        task.refresh_from_db()
        self.assertEqual(str(task.coordination_thread_id), str(thread.id))
