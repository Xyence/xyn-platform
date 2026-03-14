import json
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from xyn_orchestrator.development_intelligence import compute_thread_diagnostic
from xyn_orchestrator.execution_observability import build_thread_timeline, serialize_thread_timeline
from xyn_orchestrator.goal_progress import compute_thread_execution_metrics, compute_thread_progress
from xyn_orchestrator.models import CoordinationEvent, CoordinationThread, DevTask, UserIdentity, Workspace, WorkspaceMembership
from xyn_orchestrator.xco import derive_work_queue
from xyn_orchestrator.xyn_api import _dispatch_next_queue_item, _update_thread_status_from_tasks, thread_detail, thread_review, threads_collection, xco_queue_collection


class XcoThreadTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        suffix = uuid.uuid4().hex[:8]
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username=f"xco-admin-{suffix}",
            email=f"xco-{suffix}@example.com",
            password="password",
        )
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example.com",
            subject=f"xco-admin-{suffix}",
            email=f"xco-{suffix}@example.com",
        )
        self.workspace = Workspace.objects.create(name="XCO Workspace", slug=f"xco-workspace-{suffix}")
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
        self.assertEqual(payload["items"][0]["queue_state"]["status"], "queue_ready")

    def test_xco_queue_endpoint_excludes_gated_unapproved_work(self):
        thread = self._create_thread(priority="critical")
        self._create_task(
            thread,
            work_item_id="wi-needs-review",
            execution_brief={"schema_version": "v1", "summary": "Blocked handoff"},
            execution_brief_review_state="draft",
            execution_policy={"require_brief_approval": True},
        )
        request = self._request("/xyn/api/xco/queue", data={"workspace_id": str(self.workspace.id)})
        with self._auth_patches()[0], self._auth_patches()[1]:
            response = xco_queue_collection(request)
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["items"], [])

    def test_dispatch_next_queue_item_creates_runtime_dispatch_and_events(self):
        thread = self._create_thread(status="queued", priority="high", execution_policy={"auto_resume": True})
        task = self._create_task(
            thread,
            work_item_id="wi-dispatch",
            execution_brief={"schema_version": "v1", "summary": "Approved handoff"},
            execution_brief_review_state="approved",
            execution_policy={"require_brief_approval": True},
        )

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

    def test_dispatch_next_queue_item_skips_unapproved_work(self):
        blocked_thread = self._create_thread(status="queued", priority="critical", execution_policy={"auto_resume": True}, title="Blocked")
        self._create_task(
            blocked_thread,
            work_item_id="wi-blocked",
            execution_brief={"schema_version": "v1", "summary": "Needs review"},
            execution_brief_review_state="draft",
            execution_policy={"require_brief_approval": True},
        )
        ready_thread = self._create_thread(status="queued", priority="high", execution_policy={"auto_resume": True}, title="Ready")
        ready_task = self._create_task(
            ready_thread,
            work_item_id="wi-ready",
            execution_brief={"schema_version": "v1", "summary": "Approved handoff"},
            execution_brief_review_state="approved",
            execution_policy={"require_brief_approval": True},
        )
        with mock.patch(
            "xyn_orchestrator.xyn_api._submit_dev_task_runtime_run",
            return_value={"run_id": "run-ready", "status": "queued", "work_item_id": "wi-ready"},
        ):
            result = _dispatch_next_queue_item(workspace=self.workspace, user=self.user, identity=self.identity)
        self.assertEqual(result["work_item_id"], "wi-ready")
        ready_task.refresh_from_db()
        self.assertEqual(str(ready_task.coordination_thread_id), str(ready_thread.id))

    def test_thread_progress_reports_not_started_when_no_work_exists(self):
        thread = self._create_thread(title="Empty")
        progress = compute_thread_progress(thread)
        self.assertEqual(progress.thread_status, "not_started")
        self.assertEqual(progress.work_items_completed, 0)
        self.assertEqual(progress.work_items_ready, 0)
        self.assertEqual(progress.work_items_blocked, 0)

    def test_thread_progress_reports_active_when_ready_or_running_work_exists(self):
        thread = self._create_thread(title="Active Thread", status="active")
        self._create_task(thread, status="queued", work_item_id="wi-ready")
        progress = compute_thread_progress(thread)
        self.assertEqual(progress.thread_status, "active")
        self.assertEqual(progress.work_items_ready, 1)

    def test_thread_progress_reports_blocked_when_unfinished_work_cannot_proceed(self):
        thread = self._create_thread(title="Blocked Thread", status="paused")
        self._create_task(thread, status="queued", work_item_id="wi-blocked")
        progress = compute_thread_progress(thread)
        self.assertEqual(progress.thread_status, "blocked")
        self.assertEqual(progress.work_items_blocked, 1)

    def test_thread_progress_reports_completed_when_all_work_is_completed(self):
        thread = self._create_thread(title="Done Thread", status="active")
        self._create_task(thread, status="completed", work_item_id="wi-done-1")
        self._create_task(thread, status="succeeded", work_item_id="wi-done-2")
        progress = compute_thread_progress(thread)
        self.assertEqual(progress.thread_status, "completed")
        self.assertEqual(progress.work_items_completed, 2)

    def test_thread_execution_metrics_calculate_duration_and_counts(self):
        thread = self._create_thread(title="Metrics Thread", status="active")
        finished = self._create_task(thread, title="Finished task", status="completed", work_item_id="wi-finished", runtime_run_id=uuid.uuid4())
        self._create_task(thread, title="Failed task", status="failed", work_item_id="wi-failed")
        self._create_task(thread, title="Blocked task", status="queued", work_item_id="wi-blocked", dependency_work_item_ids=["missing-dependency"])

        def runtime_detail_lookup(task):
            if task.id != finished.id:
                return None
            return {
                "started_at": "2026-03-12T10:00:00Z",
                "completed_at": "2026-03-12T10:02:00Z",
                "artifacts": [],
            }

        metrics = compute_thread_execution_metrics(thread, runtime_detail_lookup=runtime_detail_lookup)
        self.assertEqual(metrics.average_run_duration_seconds, 120)
        self.assertEqual(metrics.total_completed_work_items, 1)
        self.assertEqual(metrics.failed_work_items, 1)
        self.assertEqual(metrics.blocked_work_items, 1)

    def test_thread_execution_metrics_handle_zero_runs(self):
        thread = self._create_thread(title="No Runs Metrics", status="active")
        self._create_task(thread, title="Queued task", status="queued", work_item_id="wi-queued")
        metrics = compute_thread_execution_metrics(thread, runtime_detail_lookup=lambda _task: None)
        self.assertEqual(metrics.average_run_duration_seconds, 0)
        self.assertEqual(metrics.total_completed_work_items, 0)
        self.assertEqual(metrics.failed_work_items, 0)
        self.assertEqual(metrics.blocked_work_items, 0)

    def test_thread_execution_metrics_handle_failed_only_runtime_history(self):
        thread = self._create_thread(title="Failed Runs Metrics", status="active")
        task_a = self._create_task(thread, title="Fail A", status="failed", work_item_id="wi-fail-a")
        task_b = self._create_task(thread, title="Fail B", status="failed", work_item_id="wi-fail-b")

        def runtime_detail_lookup(task):
            started = "2026-03-12T10:00:00Z" if task.id == task_a.id else "2026-03-12T11:00:00Z"
            completed = "2026-03-12T10:02:00Z" if task.id == task_a.id else "2026-03-12T11:03:00Z"
            return {"started_at": started, "completed_at": completed, "status": "failed"}

        metrics = compute_thread_execution_metrics(thread, runtime_detail_lookup=runtime_detail_lookup)
        self.assertEqual(metrics.average_run_duration_seconds, 150)
        self.assertEqual(metrics.total_completed_work_items, 0)
        self.assertEqual(metrics.failed_work_items, 2)
        self.assertEqual(metrics.blocked_work_items, 0)

    def test_thread_execution_metrics_handle_blocked_work_without_execution(self):
        thread = self._create_thread(title="Blocked Without Execution", status="paused")
        self._create_task(
            thread,
            title="Blocked task",
            status="queued",
            work_item_id="wi-blocked",
            dependency_work_item_ids=["missing-dependency"],
        )
        metrics = compute_thread_execution_metrics(thread, runtime_detail_lookup=lambda _task: None)
        self.assertEqual(metrics.average_run_duration_seconds, 0)
        self.assertEqual(metrics.total_completed_work_items, 0)
        self.assertEqual(metrics.failed_work_items, 0)
        self.assertEqual(metrics.blocked_work_items, 1)

    def test_thread_execution_metrics_handle_extreme_duration_variance(self):
        thread = self._create_thread(title="Variance Thread", status="active")
        fast = self._create_task(thread, title="Fast", status="completed", work_item_id="wi-fast")
        slow = self._create_task(thread, title="Slow", status="completed", work_item_id="wi-slow")

        def runtime_detail_lookup(task):
            if task.id == fast.id:
                return {"started_at": "2026-03-12T10:00:00Z", "completed_at": "2026-03-12T10:01:00Z", "status": "completed"}
            if task.id == slow.id:
                return {"started_at": "2026-03-12T11:00:00Z", "completed_at": "2026-03-12T12:00:00Z", "status": "completed"}
            return None

        metrics = compute_thread_execution_metrics(thread, runtime_detail_lookup=runtime_detail_lookup)
        self.assertEqual(metrics.average_run_duration_seconds, 1830)
        self.assertEqual(metrics.total_completed_work_items, 2)

    def test_build_thread_timeline_reconstructs_ordered_lifecycle_from_durable_state(self):
        thread = self._create_thread(title="Timeline Thread")
        task = self._create_task(thread, title="Implement scheduler", status="completed", work_item_id="wi-timeline")
        CoordinationEvent.objects.create(
            thread=thread,
            event_type="work_item_promoted",
            work_item=task,
            run_id=uuid.uuid4(),
            payload_json={"summary": "Promoted for queue dispatch"},
        )
        started = timezone.now() - timezone.timedelta(minutes=5)
        completed = timezone.now() - timezone.timedelta(minutes=1)

        timeline = build_thread_timeline(
            thread,
            runtime_detail_lookup=lambda candidate: {
                "id": "run-1",
                "run_id": "run-1",
                "status": "completed",
                "started_at": started,
                "completed_at": completed,
                "summary": "Scheduler completed successfully.",
            }
            if candidate.id == task.id
            else None,
        )
        serialized = serialize_thread_timeline(timeline)
        event_types = [entry["event_type"] for entry in serialized]
        self.assertIn("work_item_queued", event_types)
        self.assertIn("work_item_running", event_types)
        self.assertIn("work_item_completed", event_types)
        timestamps = [entry["created_at"] for entry in serialized]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_build_thread_timeline_marks_blocked_work_items(self):
        thread = self._create_thread(title="Blocked Timeline", status="paused")
        self._create_task(thread, title="Blocked item", status="queued", work_item_id="wi-blocked")
        timeline = serialize_thread_timeline(build_thread_timeline(thread))
        blocked = [entry for entry in timeline if entry["event_type"] == "work_item_blocked"]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0]["work_item_id"], "wi-blocked")

    def test_build_thread_timeline_uses_stable_order_for_identical_timestamps(self):
        thread = self._create_thread(title="Equal Timestamp Timeline")
        task_a = self._create_task(thread, title="Task A", status="completed", work_item_id="wi-a")
        task_b = self._create_task(thread, title="Task B", status="completed", work_item_id="wi-b")
        shared = timezone.now() - timezone.timedelta(minutes=5)
        DevTask.objects.filter(id__in=[task_a.id, task_b.id]).update(created_at=shared, updated_at=shared)

        def runtime_detail_lookup(task):
            return {
                "id": f"run-{task.work_item_id}",
                "run_id": f"run-{task.work_item_id}",
                "status": "completed",
                "started_at": shared,
                "completed_at": shared,
                "summary": f"{task.title} completed",
            }

        first = serialize_thread_timeline(build_thread_timeline(thread, runtime_detail_lookup=runtime_detail_lookup))
        second = serialize_thread_timeline(build_thread_timeline(thread, runtime_detail_lookup=runtime_detail_lookup))
        self.assertEqual(
            [(entry["event_type"], entry["work_item_id"], entry["run_id"], entry["id"]) for entry in first],
            [(entry["event_type"], entry["work_item_id"], entry["run_id"], entry["id"]) for entry in second],
        )
        self.assertEqual(
            [(entry["event_type"], entry["work_item_id"]) for entry in first],
            [
                ("work_item_completed", "wi-a"),
                ("work_item_completed", "wi-b"),
                ("work_item_queued", "wi-a"),
                ("work_item_queued", "wi-b"),
                ("work_item_running", "wi-a"),
                ("work_item_running", "wi-b"),
            ],
        )

    def test_build_thread_timeline_orders_blocked_before_completed_when_timestamp_matches(self):
        thread = self._create_thread(title="Blocked and Completed")
        blocked_task = self._create_task(
            thread,
            title="Blocked",
            status="queued",
            work_item_id="wi-blocked",
            dependency_work_item_ids=["missing-dependency"],
        )
        completed_task = self._create_task(thread, title="Completed", status="completed", work_item_id="wi-completed")
        shared = timezone.now() - timezone.timedelta(minutes=2)
        DevTask.objects.filter(id__in=[blocked_task.id, completed_task.id]).update(created_at=shared, updated_at=shared)

        timeline = serialize_thread_timeline(
            build_thread_timeline(
                thread,
                runtime_detail_lookup=lambda task: {
                    "id": "run-completed",
                    "run_id": "run-completed",
                    "status": "completed",
                    "started_at": shared,
                    "completed_at": shared,
                }
                if task.id == completed_task.id
                else None,
            )
        )
        same_timestamp_entries = [
            entry for entry in timeline if entry["created_at"] == shared and entry["event_type"] in {"work_item_blocked", "work_item_completed"}
        ]
        self.assertEqual(
            [(entry["event_type"], entry["work_item_id"]) for entry in same_timestamp_entries],
            [("work_item_blocked", "wi-blocked"), ("work_item_completed", "wi-completed")],
        )

    def test_thread_detail_returns_computed_execution_timeline(self):
        thread = self._create_thread(title="Detail Timeline")
        task = self._create_task(thread, title="Implement timeline", status="completed", work_item_id="wi-detail")
        request = self._request(f"/xyn/api/threads/{thread.id}")
        started = timezone.now() - timezone.timedelta(minutes=3)
        completed = timezone.now() - timezone.timedelta(minutes=1)
        with self._auth_patches()[0], mock.patch(
            "xyn_orchestrator.xyn_api._project_runtime_status_to_task",
            side_effect=lambda candidate: {
                "id": "run-detail",
                "run_id": "run-detail",
                "status": "completed",
                "started_at": started,
                "completed_at": completed,
                "summary": "Timeline finished",
            }
            if candidate.id == task.id
            else None,
        ):
            response = thread_detail(request, str(thread.id))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertTrue(any(entry["event_type"] == "work_item_running" for entry in payload["timeline"]))
        self.assertTrue(any(entry["event_type"] == "work_item_completed" for entry in payload["timeline"]))

    def test_thread_detail_includes_execution_metrics(self):
        thread = self._create_thread(title="Detail Metrics", status="active")
        finished = self._create_task(
            thread,
            title="Finished task",
            status="completed",
            work_item_id="wi-finished",
            runtime_run_id=uuid.uuid4(),
        )
        self._create_task(thread, title="Failed task", status="failed", work_item_id="wi-failed")
        self._create_task(
            thread,
            title="Blocked task",
            status="queued",
            work_item_id="wi-blocked",
            dependency_work_item_ids=["missing-dependency"],
        )
        request = self._request(f"/xyn/api/threads/{thread.id}")
        with self._auth_patches()[0], mock.patch(
            "xyn_orchestrator.xyn_api._project_runtime_status_to_task",
            side_effect=lambda candidate: {
                "id": "run-detail-metrics",
                "run_id": "run-detail-metrics",
                "status": "completed",
                "started_at": "2026-03-12T10:00:00Z",
                "completed_at": "2026-03-12T10:02:00Z",
                "summary": "Done",
            }
            if candidate.id == finished.id
            else None,
        ):
            response = thread_detail(request, str(thread.id))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["metrics"]["average_run_duration_seconds"], 120)
        self.assertEqual(payload["metrics"]["total_completed_work_items"], 1)
        self.assertEqual(payload["metrics"]["failed_work_items"], 1)
        self.assertEqual(payload["metrics"]["blocked_work_items"], 1)

    def test_thread_diagnostic_detects_slow_execution_from_duration_metrics(self):
        thread = self._create_thread(title="Slow Thread", status="active")
        finished = self._create_task(
            thread,
            title="Slow task",
            status="completed",
            work_item_id="wi-slow",
            runtime_run_id=uuid.uuid4(),
        )
        metrics = compute_thread_execution_metrics(
            thread,
            runtime_detail_lookup=lambda candidate: {
                "id": "run-slow",
                "run_id": "run-slow",
                "status": "completed",
                "started_at": "2026-03-12T10:00:00Z",
                "completed_at": "2026-03-12T10:45:00Z",
            }
            if candidate.id == finished.id
            else None,
        )
        timeline = build_thread_timeline(
            thread,
            runtime_detail_lookup=lambda candidate: {
                "id": "run-slow",
                "run_id": "run-slow",
                "status": "completed",
                "started_at": timezone.now() - timezone.timedelta(minutes=45),
                "completed_at": timezone.now(),
            }
            if candidate.id == finished.id
            else None,
        )
        diagnostic = compute_thread_diagnostic(
            thread,
            progress=compute_thread_progress(thread),
            metrics=metrics,
            timeline=timeline,
            recent_runs=[{"id": "run-slow", "status": "completed"}],
            recent_artifacts=[],
        )
        self.assertEqual(diagnostic.status, "slow")
        self.assertIn("Average run duration is 2700 seconds.", diagnostic.evidence)

    def test_thread_diagnostic_detects_repeated_failures(self):
        thread = self._create_thread(title="Failing Thread", status="active")
        self._create_task(thread, title="Fail 1", status="failed", work_item_id="wi-fail-1")
        self._create_task(thread, title="Fail 2", status="failed", work_item_id="wi-fail-2")
        diagnostic = compute_thread_diagnostic(
            thread,
            progress=compute_thread_progress(thread),
            metrics=compute_thread_execution_metrics(thread),
            timeline=build_thread_timeline(thread),
            recent_runs=[{"id": "run-1", "status": "failed"}, {"id": "run-2", "status": "failed"}],
            recent_artifacts=[],
        )
        self.assertEqual(diagnostic.status, "unstable")
        self.assertTrue(any("failed" in entry.lower() for entry in diagnostic.evidence))

    def test_thread_diagnostic_detects_blocked_state(self):
        thread = self._create_thread(title="Blocked Thread", status="paused")
        self._create_task(thread, title="Blocked", status="queued", work_item_id="wi-blocked")
        diagnostic = compute_thread_diagnostic(
            thread,
            progress=compute_thread_progress(thread),
            metrics=compute_thread_execution_metrics(thread),
            timeline=build_thread_timeline(thread),
            recent_runs=[],
            recent_artifacts=[],
        )
        self.assertEqual(diagnostic.status, "blocked")
        self.assertIn("blocked work item", " ".join(diagnostic.evidence).lower())

    def test_thread_diagnostic_detects_high_artifact_churn(self):
        thread = self._create_thread(title="Churn Thread", status="active")
        self._create_task(thread, title="Artifact work", status="completed", work_item_id="wi-artifact")
        diagnostic = compute_thread_diagnostic(
            thread,
            progress=compute_thread_progress(thread),
            metrics=compute_thread_execution_metrics(thread),
            timeline=build_thread_timeline(thread),
            recent_runs=[{"id": "run-1", "status": "completed"}],
            recent_artifacts=[
                {"artifact_type": "patch", "label": "Patch Output"},
                {"artifact_type": "patch", "label": "Patch Output"},
                {"artifact_type": "patch", "label": "Patch Output"},
            ],
        )
        self.assertEqual(diagnostic.status, "unstable")
        self.assertTrue(any("artifact family" in entry.lower() for entry in diagnostic.evidence))

    def test_thread_diagnostic_marks_runtime_history_as_provenance_ambiguous_without_queue_evidence(self):
        thread = self._create_thread(title="Ambiguous Provenance", status="active")
        self._create_task(thread, title="Runtime work", status="running", work_item_id="wi-runtime", runtime_run_id=uuid.uuid4())
        timeline = build_thread_timeline(
            thread,
            runtime_detail_lookup=lambda _candidate: {
                "id": "run-ambiguous",
                "run_id": "run-ambiguous",
                "status": "running",
                "started_at": timezone.now() - timezone.timedelta(minutes=2),
            },
        )
        diagnostic = compute_thread_diagnostic(
            thread,
            progress=compute_thread_progress(thread),
            metrics=compute_thread_execution_metrics(thread),
            timeline=timeline,
            recent_runs=[{"id": "run-ambiguous", "status": "running"}],
            recent_artifacts=[],
        )
        self.assertEqual(diagnostic.provenance.provenance_status, "runtime_provenance_ambiguous")
        self.assertTrue(diagnostic.provenance.ambiguous_runtime_evidence)
        self.assertIn("not fully attributable", diagnostic.provenance.summary)
        self.assertNotIn("queued through the supervised loop", diagnostic.provenance.summary.lower())

    def test_thread_detail_includes_thread_diagnostic(self):
        thread = self._create_thread(title="Diagnostic Detail", status="active")
        finished = self._create_task(
            thread,
            title="Finished task",
            status="completed",
            work_item_id="wi-finished",
            runtime_run_id=uuid.uuid4(),
        )
        request = self._request(f"/xyn/api/threads/{thread.id}")
        with self._auth_patches()[0], mock.patch(
            "xyn_orchestrator.xyn_api._project_runtime_status_to_task",
            side_effect=lambda candidate: {
                "id": "run-diagnostic",
                "run_id": "run-diagnostic",
                "status": "completed",
                "started_at": "2026-03-12T10:00:00Z",
                "completed_at": "2026-03-12T10:45:00Z",
                "summary": "Long-running change",
            }
            if candidate.id == finished.id
            else None,
        ):
            response = thread_detail(request, str(thread.id))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["thread_diagnostic"]["status"], "slow")
        self.assertIn("provenance", payload["thread_diagnostic"])

    def test_thread_summary_exposes_computed_progress_counts(self):
        thread = self._create_thread(title="Summary Thread", status="active")
        self._create_task(thread, status="completed", work_item_id="wi-complete")
        self._create_task(thread, status="queued", work_item_id="wi-ready")

        request = self._request("/xyn/api/threads", data={"workspace_id": str(self.workspace.id)})
        with self._auth_patches()[0], self._auth_patches()[1]:
            response = threads_collection(request)
        payload = json.loads(response.content)
        row = next(item for item in payload["threads"] if item["id"] == str(thread.id))
        self.assertEqual(row["thread_progress_status"], "active")
        self.assertEqual(row["work_items_completed"], 1)
        self.assertEqual(row["work_items_ready"], 1)

    def test_thread_detail_includes_recent_runs(self):
        thread = self._create_thread(status="active")
        self._create_task(thread, work_item_id="wi-run", runtime_run_id=uuid.uuid4(), status="running")
        request = self._request(f"/xyn/api/threads/{thread.id}")
        with self._auth_patches()[0]:
            with mock.patch(
                "xyn_orchestrator.xyn_api._fetch_runtime_run_detail_payload",
                return_value={
                    "run_id": "8dfc1f0c-5897-427e-b8ee-0debde6d1b0e",
                    "status": "running",
                    "summary": "Refactor is running",
                    "artifacts": [],
                    "steps": [],
                },
            ):
                response = thread_detail(request, str(thread.id))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["recent_runs"][0]["summary"], "Refactor is running")

    def test_thread_review_queue_next_slice_records_approval_without_dispatch(self):
        thread = self._create_thread(status="active", priority="high")
        task = self._create_task(thread, work_item_id="wi-next", status="queued")
        request = self._request(
            f"/xyn/api/threads/{thread.id}/review",
            method="post",
            data=json.dumps({"review_action": "queue_next_slice"}),
        )
        with self._auth_patches()[0]:
            response = thread_review(request, str(thread.id))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["status"], "approved")
        self.assertEqual(payload["queue_seed"]["work_item_id"], "wi-next")
        self.assertTrue(
            CoordinationEvent.objects.filter(
                thread=thread,
                work_item=task,
                event_type="approval_queue_next_slice",
            ).exists()
        )

    def test_thread_review_resume_and_complete_follow_coordination_state_rules(self):
        thread = self._create_thread(status="paused")
        resume_request = self._request(
            f"/xyn/api/threads/{thread.id}/review",
            method="post",
            data=json.dumps({"review_action": "resume_thread"}),
        )
        with self._auth_patches()[0]:
            resume_response = thread_review(resume_request, str(thread.id))
        self.assertEqual(resume_response.status_code, 200)
        thread.refresh_from_db()
        self.assertEqual(thread.status, "active")
        self.assertTrue(
            CoordinationEvent.objects.filter(
                thread=thread,
                event_type="approval_thread_resume",
            ).exists()
        )

        self._create_task(thread, status="completed", work_item_id="wi-done")
        complete_request = self._request(
            f"/xyn/api/threads/{thread.id}/review",
            method="post",
            data=json.dumps({"review_action": "mark_thread_completed"}),
        )
        with self._auth_patches()[0]:
            complete_response = thread_review(complete_request, str(thread.id))
        self.assertEqual(complete_response.status_code, 200)
        thread.refresh_from_db()
        self.assertEqual(thread.status, "completed")
