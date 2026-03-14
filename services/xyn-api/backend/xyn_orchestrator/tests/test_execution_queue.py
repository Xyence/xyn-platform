import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase

from xyn_orchestrator.execution_queue import (
    evaluate_dev_task_queue_state,
    select_next_dispatchable_queue_entry,
)
from xyn_orchestrator.models import CoordinationThread, DevTask, UserIdentity, Workspace, WorkspaceMembership
from xyn_orchestrator.xco import derive_work_queue


class ExecutionQueueTests(TestCase):
    def setUp(self):
        suffix = uuid.uuid4().hex[:8]
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username=f"queue-user-{suffix}",
            email=f"queue-{suffix}@example.com",
            password="password",
        )
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example.com",
            subject=f"queue-user-{suffix}",
            email=f"queue-{suffix}@example.com",
        )
        self.workspace = Workspace.objects.create(name="Queue Workspace", slug=f"queue-workspace-{suffix}")
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user_identity=self.identity,
            role="admin",
            termination_authority=True,
        )
        self.thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            title="Queue Thread",
            owner=self.identity,
            priority="normal",
            status="active",
            domain="development",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id=f"queue-thread-{suffix}",
        )

    def _task(self, **overrides) -> DevTask:
        defaults = {
            "title": "Implement queue dispatch",
            "task_type": "codegen",
            "status": "queued",
            "priority": 0,
            "max_attempts": 3,
            "source_entity_type": "manual",
            "source_entity_id": uuid.uuid4(),
            "work_item_id": f"wi-{uuid.uuid4().hex[:6]}",
            "created_by": self.user,
            "updated_by": self.user,
            "coordination_thread": self.thread,
        }
        defaults.update(overrides)
        return DevTask.objects.create(**defaults)

    def test_queue_state_requires_brief_approval_when_gated(self):
        task = self._task(
            execution_brief={"schema_version": "v1", "summary": "Implement queue dispatch"},
            execution_brief_review_state="draft",
            execution_policy={"require_brief_approval": True},
        )
        state = evaluate_dev_task_queue_state(task, normalized_status="queued")
        self.assertFalse(state.dispatchable)
        self.assertTrue(state.blocked)
        self.assertEqual(state.reason, "brief_not_ready")

    def test_queue_state_allows_approved_structured_brief(self):
        task = self._task(
            execution_brief={"schema_version": "v1", "summary": "Implement queue dispatch"},
            execution_brief_review_state="approved",
            execution_policy={"require_brief_approval": True},
        )
        state = evaluate_dev_task_queue_state(task, normalized_status="queued")
        self.assertTrue(state.dispatchable)
        self.assertTrue(state.queue_ready)
        self.assertEqual(state.status, "queue_ready")

    def test_queue_state_marks_runtime_queued_task_as_dispatched(self):
        task = self._task(runtime_run_id=uuid.uuid4())
        state = evaluate_dev_task_queue_state(task, normalized_status="queued")
        self.assertFalse(state.dispatchable)
        self.assertTrue(state.dispatched)
        self.assertEqual(state.reason, "in_flight")

    def test_select_next_dispatchable_queue_entry_skips_blocked_first_candidate(self):
        blocked_thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            title="Blocked Thread",
            owner=self.identity,
            priority="high",
            status="active",
            domain="development",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id=f"blocked-{uuid.uuid4().hex[:6]}",
        )
        blocked = DevTask.objects.create(
            title="Blocked task",
            task_type="codegen",
            status="queued",
            priority=0,
            max_attempts=3,
            source_entity_type="manual",
            source_entity_id=uuid.uuid4(),
            work_item_id="wi-blocked",
            execution_brief={"schema_version": "v1", "summary": "Blocked brief"},
            execution_brief_review_state="draft",
            execution_policy={"require_brief_approval": True},
            created_by=self.user,
            updated_by=self.user,
            coordination_thread=blocked_thread,
        )
        approved = self._task(
            work_item_id="wi-approved",
            execution_brief={"schema_version": "v1", "summary": "Approved brief"},
            execution_brief_review_state="approved",
            execution_policy={"require_brief_approval": True},
        )
        queue = derive_work_queue(
            threads=CoordinationThread.objects.filter(id__in=[blocked_thread.id, self.thread.id]).prefetch_related("work_items"),
            status_lookup=lambda task: task.status,
            task_lookup=lambda reference: DevTask.objects.filter(work_item_id=reference).first() or DevTask.objects.filter(id=reference).first(),
        )
        selected = select_next_dispatchable_queue_entry(
            queue,
            task_lookup=lambda reference: DevTask.objects.filter(id=reference).first() or DevTask.objects.filter(work_item_id=reference).first(),
            status_lookup=lambda task: task.status,
        )
        self.assertIsNotNone(selected)
        entry, task, _state = selected
        self.assertEqual(entry.work_item_id, "wi-approved")
        self.assertEqual(task.id, approved.id)
        self.assertNotEqual(task.id, blocked.id)
