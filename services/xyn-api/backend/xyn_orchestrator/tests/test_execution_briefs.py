import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase

from xyn_orchestrator.execution_briefs import (
    execution_brief_readiness,
    serialize_execution_brief_review,
    normalize_execution_brief_review_state,
    regenerate_execution_brief,
    replace_execution_brief,
    resolve_execution_brief,
    valid_execution_brief_review_transition,
)
from xyn_orchestrator.models import DevTask


class ExecutionBriefTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username=f"brief-{uuid.uuid4().hex[:8]}",
            email=f"brief-{uuid.uuid4().hex[:8]}@example.com",
            password="password",
        )

    def _task(self, **overrides) -> DevTask:
        defaults = {
            "title": "Implement handoff",
            "description": "Use the brief",
            "task_type": "codegen",
            "status": "queued",
            "priority": 0,
            "source_entity_type": "manual",
            "source_entity_id": uuid.uuid4(),
            "created_by": self.user,
            "updated_by": self.user,
        }
        defaults.update(overrides)
        return DevTask.objects.create(**defaults)

    def test_review_state_defaults_to_draft(self):
        task = self._task()
        self.assertEqual(normalize_execution_brief_review_state(task.execution_brief_review_state), "draft")

    def test_review_state_transition_rules_are_deterministic(self):
        self.assertTrue(valid_execution_brief_review_transition("draft", "ready"))
        self.assertTrue(valid_execution_brief_review_transition("ready", "approved"))
        self.assertTrue(valid_execution_brief_review_transition("approved", "superseded"))
        self.assertFalse(valid_execution_brief_review_transition("superseded", "approved"))

    def test_readiness_blocks_gated_structured_brief_until_ready(self):
        task = self._task(
            execution_brief={"schema_version": "v1", "summary": "Implement handoff"},
            execution_brief_review_state="draft",
            execution_policy={"require_brief_approval": True},
        )
        readiness = execution_brief_readiness(task)
        self.assertFalse(readiness.executable)
        self.assertTrue(readiness.gated)
        self.assertEqual(readiness.reason, "brief_not_ready")

    def test_readiness_allows_gated_structured_brief_when_approved(self):
        task = self._task(
            execution_brief={"schema_version": "v1", "summary": "Implement handoff"},
            execution_brief_review_state="approved",
            execution_policy={"require_brief_approval": True},
        )
        readiness = execution_brief_readiness(task)
        self.assertTrue(readiness.executable)
        self.assertTrue(readiness.gated)
        self.assertEqual(readiness.review_state, "approved")

    def test_readiness_preserves_fallback_for_tasks_without_structured_brief(self):
        task = self._task(execution_policy={"require_brief_approval": True})
        readiness = execution_brief_readiness(task)
        self.assertTrue(readiness.executable)
        self.assertFalse(readiness.structured_brief)

    def test_rejected_brief_is_blocked_even_without_gate_flag(self):
        task = self._task(
            execution_brief={"schema_version": "v1", "summary": "Implement handoff"},
            execution_brief_review_state="rejected",
            execution_policy={},
        )
        readiness = execution_brief_readiness(task)
        self.assertFalse(readiness.executable)
        self.assertEqual(readiness.reason, "brief_rejected")

    def test_replace_execution_brief_supersedes_prior_brief_and_resets_review(self):
        task = self._task(
            execution_brief={"schema_version": "v1", "summary": "Initial brief", "revision": 1},
            execution_brief_review_state="approved",
            execution_brief_review_notes="Approved as-is",
            execution_policy={"require_brief_approval": True},
        )
        updated = replace_execution_brief(
            task,
            brief={"schema_version": "v1", "summary": "Revised brief"},
            replaced_by=self.user,
            replacement_reason="address review feedback",
            review_notes="Needs another review pass",
        )
        task.refresh_from_db()
        self.assertEqual(updated["revision"], 2)
        self.assertEqual(task.execution_brief_review_state, "draft")
        self.assertEqual(task.execution_brief_review_notes, "Needs another review pass")
        self.assertEqual(len(task.execution_brief_history), 1)
        snapshot = task.execution_brief_history[0]
        self.assertEqual(snapshot["brief"]["summary"], "Initial brief")
        self.assertEqual(snapshot["review_state"], "approved")
        self.assertEqual(snapshot["replacement_reason"], "address review feedback")

    def test_regenerate_execution_brief_uses_current_context_and_keeps_history(self):
        task = self._task(
            title="Implement runtime bridge",
            description="Update the runtime bridge",
            execution_brief={"schema_version": "v1", "summary": "Initial brief", "revision": 1, "scope": {"allowed_areas": ["bridge"]}},
            execution_brief_review_state="rejected",
            execution_brief_review_notes="Clarify the objective",
            execution_policy={"require_brief_approval": True},
        )
        regenerated = regenerate_execution_brief(
            task,
            work_item={
                "id": "wi-1",
                "title": "Implement runtime bridge",
                "description": "Update the runtime bridge to use execution briefs.",
                "acceptance_criteria": ["Use the current active brief"],
                "verify": [{"command": "python -m unittest"}],
            },
            regenerated_by=self.user,
            regeneration_reason="review_rejected",
            review_notes="Clarified after rejection",
        )
        task.refresh_from_db()
        self.assertEqual(regenerated["revision"], 2)
        self.assertEqual(task.execution_brief_review_state, "draft")
        self.assertEqual(task.execution_brief["objective"], "Update the runtime bridge to use execution briefs.")
        self.assertEqual(task.execution_brief["revision_reason"], "review_rejected")
        self.assertEqual(len(task.execution_brief_history), 1)
        self.assertEqual(task.execution_brief_history[0]["review_state"], "rejected")

    def test_resolve_execution_brief_uses_current_active_brief_not_history(self):
        task = self._task(
            execution_brief={"schema_version": "v1", "summary": "Current draft brief", "revision": 2},
            execution_brief_history=[
                {
                    "revision": 1,
                    "brief": {"schema_version": "v1", "summary": "Old approved brief", "revision": 1},
                    "review_state": "approved",
                }
            ],
            execution_brief_review_state="draft",
            execution_policy={"require_brief_approval": True},
        )
        resolved = resolve_execution_brief(task)
        readiness = execution_brief_readiness(task)
        self.assertEqual(resolved.brief["summary"], "Current draft brief")
        self.assertEqual(resolved.revision, 2)
        self.assertEqual(len(resolved.history), 1)
        self.assertFalse(readiness.executable)

    def test_serialize_execution_brief_review_exposes_blocked_state_and_actions(self):
        task = self._task(
            execution_brief={
                "schema_version": "v1",
                "summary": "Review the runtime bridge handoff",
                "objective": "Keep the change scoped to the runtime bridge.",
                "revision": 2,
                "target": {"repository_slug": "xyn-platform", "branch": "develop"},
            },
            execution_brief_history=[
                {
                    "revision": 1,
                    "brief": {"schema_version": "v1", "summary": "Old brief", "revision": 1},
                    "review_state": "rejected",
                }
            ],
            execution_brief_review_state="draft",
            execution_brief_review_notes="Needs an explicit boundary",
            execution_policy={"require_brief_approval": True},
        )
        review = serialize_execution_brief_review(task)
        self.assertTrue(review["has_brief"])
        self.assertTrue(review["blocked"])
        self.assertEqual(review["blocked_reason"], "brief_not_ready")
        self.assertEqual(review["revision"], 2)
        self.assertEqual(review["history_count"], 1)
        self.assertEqual(review["target_repository_slug"], "xyn-platform")
        self.assertIn("mark_ready", review["available_actions"])
        self.assertIn("approve", review["available_actions"])
