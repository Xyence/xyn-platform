import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase

from xyn_orchestrator.execution_recovery import evaluate_dev_task_recovery_state
from xyn_orchestrator.models import CoordinationThread, DevTask, UserIdentity, Workspace, WorkspaceMembership


class ExecutionRecoveryTests(TestCase):
    def setUp(self):
        suffix = uuid.uuid4().hex[:8]
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username=f"recovery-user-{suffix}",
            email=f"recovery-{suffix}@example.com",
            password="password",
        )
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example.com",
            subject=f"recovery-user-{suffix}",
            email=f"recovery-{suffix}@example.com",
        )
        self.workspace = Workspace.objects.create(name="Recovery Workspace", slug=f"recovery-workspace-{suffix}")
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user_identity=self.identity,
            role="admin",
            termination_authority=True,
        )
        self.thread = CoordinationThread.objects.create(
            workspace=self.workspace,
            title="Recovery Thread",
            owner=self.identity,
            priority="normal",
            status="active",
            domain="development",
            work_in_progress_limit=1,
            execution_policy={},
            source_conversation_id=f"recovery-thread-{suffix}",
        )

    def _task(self, **overrides) -> DevTask:
        defaults = {
            "title": "Recover failed execution",
            "task_type": "codegen",
            "status": "failed",
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

    def test_failed_task_is_retryable_when_brief_ready(self):
        task = self._task(
            execution_brief={"schema_version": "v1", "summary": "Recover scheduler"},
            execution_brief_review_state="approved",
            execution_policy={"require_brief_approval": True},
        )
        state = evaluate_dev_task_recovery_state(
            task,
            execution_summary={
                "state": "failed",
                "run_id": "run-1",
                "summary": "Tests failed",
                "error": "tests_failed",
            },
        )
        self.assertTrue(state.retryable)
        self.assertTrue(state.requeueable)
        self.assertEqual(state.status, "retryable")

    def test_failed_task_is_not_retryable_when_brief_is_not_approved(self):
        task = self._task(
            execution_brief={"schema_version": "v1", "summary": "Recover scheduler"},
            execution_brief_review_state="draft",
            execution_policy={"require_brief_approval": True},
        )
        state = evaluate_dev_task_recovery_state(
            task,
            execution_summary={
                "state": "failed",
                "run_id": "run-1",
                "summary": "Tests failed",
                "error": "tests_failed",
            },
        )
        self.assertFalse(state.retryable)
        self.assertFalse(state.requeueable)
        self.assertTrue(state.blocked)
        self.assertEqual(state.reason, "brief_not_ready")

    def test_running_task_is_not_retryable_or_requeueable(self):
        task = self._task(status="running", runtime_run_id=uuid.uuid4())
        state = evaluate_dev_task_recovery_state(
            task,
            execution_summary={
                "state": "running",
                "run_id": "run-1",
                "summary": "In progress",
            },
        )
        self.assertFalse(state.retryable)
        self.assertFalse(state.requeueable)
        self.assertTrue(state.in_flight)
        self.assertEqual(state.reason, "in_flight")

    def test_awaiting_review_is_distinct_from_failure(self):
        task = self._task(status="awaiting_review")
        state = evaluate_dev_task_recovery_state(
            task,
            execution_summary={
                "state": "awaiting_review",
                "run_id": "run-1",
                "summary": "Needs review",
                "error": "human_review_required",
            },
        )
        self.assertFalse(state.retryable)
        self.assertFalse(state.requeueable)
        self.assertFalse(state.failed)
        self.assertTrue(state.blocked)
        self.assertEqual(state.status, "review_blocked")

    def test_awaiting_review_unsafe_repository_state_is_retryable_once_brief_is_ready(self):
        task = self._task(
            status="awaiting_review",
            execution_brief={"schema_version": "v1", "summary": "Recover scheduler"},
            execution_brief_review_state="approved",
            execution_policy={"require_brief_approval": True},
        )
        state = evaluate_dev_task_recovery_state(
            task,
            execution_summary={
                "state": "awaiting_review",
                "run_id": "run-1",
                "summary": "Repository is dirty",
                "error": "unsafe_repository_state",
            },
        )
        self.assertTrue(state.retryable)
        self.assertTrue(state.requeueable)
        self.assertTrue(state.failed)
        self.assertFalse(state.blocked)
        self.assertEqual(state.status, "retryable_after_review")
