from django.test import TestCase

from xyn_orchestrator.lifecycle_primitive import (
    InvalidTransitionError,
    TransitionRequest,
    validate_transition,
)
from xyn_orchestrator.models import LifecycleTransition, Workspace


class LifecyclePrimitiveTests(TestCase):
    def test_validate_transition_accepts_legal_transitions(self):
        validate_transition(
            TransitionRequest(
                lifecycle="draft",
                object_type="draft",
                object_id="abc-1",
                from_state=None,
                to_state="draft",
                actor="tester",
            )
        )
        validate_transition(
            TransitionRequest(
                lifecycle="job",
                object_type="job",
                object_id="job-1",
                from_state="queued",
                to_state="running",
            )
        )

    def test_validate_transition_rejects_illegal_transition(self):
        with self.assertRaises(InvalidTransitionError):
            validate_transition(
                TransitionRequest(
                    lifecycle="job",
                    object_type="job",
                    object_id="job-2",
                    from_state="queued",
                    to_state="succeeded",
                )
            )

    def test_lifecycle_transition_model_persists_generic_history(self):
        workspace = Workspace.objects.create(slug="lifecycle-ws", name="Lifecycle Workspace")
        row = LifecycleTransition.objects.create(
            workspace=workspace,
            lifecycle_name="draft",
            object_type="draft",
            object_id="obj-1",
            from_state="draft",
            to_state="ready",
            actor="user-1",
            reason="Validated",
            metadata_json={"source": "api"},
            correlation_id="corr-1",
        )

        fetched = LifecycleTransition.objects.get(id=row.id)
        self.assertEqual(fetched.lifecycle_name, "draft")
        self.assertEqual(fetched.object_type, "draft")
        self.assertEqual(fetched.to_state, "ready")
        self.assertEqual(fetched.metadata_json.get("source"), "api")
