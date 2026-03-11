import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory

from xyn_orchestrator import xyn_api as intent_api
from xyn_orchestrator.intent_engine.contracts import DraftIntakeContractRegistry
from xyn_orchestrator.intent_engine.engine import IntentResolutionEngine, ResolutionContext
from xyn_orchestrator.intent_engine.types import ClarificationReason, IntentEnvelope, IntentFamily, IntentType


class _FakeProvider:
    def propose(self, **_kwargs):
        return {
            "action_type": "ValidateDraft",
            "artifact_type": "ArticleDraft",
            "inferred_fields": {},
            "confidence": 0.0,
            "_model": "fake",
        }


def _registry():
    return DraftIntakeContractRegistry(category_options_provider=lambda: [{"slug": "demo", "name": "Demo"}])


class EpicDIntentEngineTests(unittest.TestCase):
    def assertEnvelopeStable(self, envelope):
        payload = envelope.model_dump(mode="json")
        self.assertEqual(
            set(payload.keys()),
            {
                "intent_family",
                "intent_type",
                "target_context",
                "resolved_subject",
                "action_payload",
                "policy",
                "confidence",
                "needs_clarification",
                "clarification_reason",
                "clarification_options",
                "resolution_notes",
            },
        )

    def test_continue_epic_d_resolves_to_continue_work_item(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            work_item_lookup=lambda query, workspace_id: [
                {"id": "task-1", "label": "Epic D", "kind": "dev_task", "work_item_id": "epic-d"}
            ],
        )
        envelope = engine.resolve_intent(
            user_message="continue Epic D",
            context=ResolutionContext(workspace_id="ws-1", user_identity_id="user-1"),
        )
        self.assertEqual(envelope.intent_family, IntentFamily.DEVELOPMENT_WORK.value)
        self.assertEqual(envelope.intent_type, IntentType.CONTINUE_WORK_ITEM.value)
        self.assertEqual(envelope.resolved_subject.get("work_item_id"), "epic-d")
        self.assertFalse(envelope.needs_clarification)
        self.assertEnvelopeStable(envelope)

    def test_continue_epic_d_implementation_uses_create_and_dispatch_run(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            work_item_lookup=lambda query, workspace_id: [
                {"id": "task-1", "label": "Epic D", "kind": "dev_task", "work_item_id": "epic-d"}
            ],
        )
        envelope = engine.resolve_intent(
            user_message="continue Epic D implementation",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertEqual(envelope.intent_type, IntentType.CREATE_AND_DISPATCH_RUN.value)
        self.assertEqual(envelope.policy.get("run_tests"), False)
        self.assertEnvelopeStable(envelope)

    def test_continue_epic_d_using_current_plan_strips_plan_phrase(self):
        captured = {}

        def lookup(query, workspace_id):
            captured["query"] = query
            return [{"id": "task-1", "label": "Epic D", "kind": "dev_task", "work_item_id": "epic-d"}]

        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            work_item_lookup=lookup,
        )
        envelope = engine.resolve_intent(
            user_message="continue Epic D implementation using the current plan",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertEqual(captured["query"], "Epic D")
        self.assertEqual(envelope.intent_type, IntentType.CREATE_AND_DISPATCH_RUN.value)
        self.assertEnvelopeStable(envelope)

    def test_run_tests_populates_policy(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            work_item_lookup=lambda query, workspace_id: [],
        )
        envelope = engine.resolve_intent(
            user_message="run tests",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertEqual(envelope.intent_type, IntentType.RUN_VALIDATION.value)
        self.assertTrue(envelope.policy.get("run_tests"))
        self.assertEnvelopeStable(envelope)

    def test_investigate_failure_resolves(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            run_lookup=lambda query, workspace_id: [{"id": "run-1", "label": "Epic D run", "kind": "runtime_run", "run_id": "run-1"}],
        )
        envelope = engine.resolve_intent(
            user_message="investigate the failure",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertEqual(envelope.intent_type, IntentType.INVESTIGATE_ISSUE.value)
        self.assertEqual(envelope.resolved_subject.get("run_id"), "run-1")
        self.assertEnvelopeStable(envelope)

    def test_pause_on_ambiguity_policy_populates(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
        )
        envelope = engine.resolve_intent(
            user_message="pause if ambiguity appears",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertEqual(envelope.intent_type, IntentType.PAUSE_OR_HOLD.value)
        self.assertTrue(envelope.policy.get("pause_on_ambiguity"))
        self.assertEnvelopeStable(envelope)

    def test_request_review_resolves(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            run_lookup=lambda query, workspace_id: [{"id": "run-1", "label": "Epic D run", "kind": "runtime_run", "run_id": "run-1"}],
        )
        envelope = engine.resolve_intent(
            user_message="request review",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertEqual(envelope.intent_family, IntentFamily.RUN_SUPERVISION.value)
        self.assertEqual(envelope.intent_type, IntentType.REQUEST_REVIEW.value)
        self.assertEnvelopeStable(envelope)

    def test_retry_run_resolves(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            run_lookup=lambda query, workspace_id: [{"id": "run-1", "label": "Epic D run", "kind": "runtime_run", "run_id": "run-1"}],
        )
        envelope = engine.resolve_intent(
            user_message="retry the run",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertEqual(envelope.intent_type, IntentType.RETRY_RUN.value)
        self.assertEnvelopeStable(envelope)

    def test_development_resolution_has_priority_over_app_operation(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            work_item_lookup=lambda query, workspace_id: [
                {"id": "task-1", "label": "Epic D", "kind": "dev_task", "work_item_id": "epic-d"}
            ],
            capability_manifest_lookup=lambda workspace_id: {"entities": [{"key": "devices"}]},
            app_operation_lookup=lambda message, manifest: {
                "intent_type": "create_record",
                "resolved_subject": {"entity_key": "devices"},
                "action_payload": {"operation": "create", "entity_key": "devices"},
                "confidence": 0.99,
                "resolution_notes": ["app operation matched"],
            },
        )
        envelope = engine.resolve_intent(
            user_message="continue Epic D implementation",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertEqual(envelope.intent_family, IntentFamily.DEVELOPMENT_WORK.value)
        self.assertEqual(envelope.intent_type, IntentType.CREATE_AND_DISPATCH_RUN.value)
        self.assertEnvelopeStable(envelope)

    def test_create_device_called_r1_in_st_louis_maps_to_create_record(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            capability_manifest_lookup=lambda workspace_id: {"entities": [{"key": "devices"}]},
            app_operation_lookup=lambda message, manifest: {
                "intent_type": "create_record",
                "resolved_subject": {"entity_key": "devices"},
                "action_payload": {
                    "operation": "create",
                    "entity_key": "devices",
                    "fields": {"name": "r1", "location_id": "St. Louis"},
                },
                "confidence": 0.93,
                "resolution_notes": ["resolved against installed capability manifest"],
            },
        )
        envelope = engine.resolve_intent(
            user_message="create a device called r1 in St. Louis",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertEqual(envelope.intent_family, IntentFamily.APP_OPERATION.value)
        self.assertEqual(envelope.intent_type, IntentType.CREATE_RECORD.value)
        self.assertEqual((envelope.action_payload.get("fields") or {}).get("name"), "r1")
        self.assertEnvelopeStable(envelope)

    def test_rename_location_maps_to_update_record(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            capability_manifest_lookup=lambda workspace_id: {"entities": [{"key": "locations"}]},
            app_operation_lookup=lambda message, manifest: {
                "intent_type": "update_record",
                "resolved_subject": {"entity_key": "locations"},
                "action_payload": {
                    "operation": "update",
                    "entity_key": "locations",
                    "target_reference": "office",
                    "field_mutations": {"name": "headquarters"},
                },
                "confidence": 0.91,
                "resolution_notes": ["resolved against installed capability manifest"],
            },
        )
        envelope = engine.resolve_intent(
            user_message="rename location office to headquarters",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertEqual(envelope.intent_type, IntentType.UPDATE_RECORD.value)
        self.assertEqual((envelope.action_payload.get("field_mutations") or {}).get("name"), "headquarters")
        self.assertEnvelopeStable(envelope)

    def test_delete_test_device_maps_to_delete_record(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            capability_manifest_lookup=lambda workspace_id: {"entities": [{"key": "devices"}]},
            app_operation_lookup=lambda message, manifest: {
                "intent_type": "delete_record",
                "resolved_subject": {"entity_key": "devices"},
                "action_payload": {"operation": "delete", "entity_key": "devices", "target_reference": "test device"},
                "confidence": 0.89,
                "resolution_notes": ["resolved against installed capability manifest"],
            },
        )
        envelope = engine.resolve_intent(
            user_message="delete the test device",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertEqual(envelope.intent_type, IntentType.DELETE_RECORD.value)
        self.assertEnvelopeStable(envelope)

    def test_show_devices_by_status_maps_to_list_records(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            capability_manifest_lookup=lambda workspace_id: {"entities": [{"key": "devices"}]},
            app_operation_lookup=lambda message, manifest: {
                "intent_type": "list_records",
                "resolved_subject": {"entity_key": "devices", "command_key": "show devices by status"},
                "action_payload": {"command_key": "show devices by status", "mode": "declared_command"},
                "confidence": 0.88,
                "resolution_notes": ["resolved against declared generated app command"],
            },
        )
        envelope = engine.resolve_intent(
            user_message="show devices by status",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertEqual(envelope.intent_type, IntentType.LIST_RECORDS.value)
        self.assertEqual(envelope.action_payload.get("command_key"), "show devices by status")
        self.assertEnvelopeStable(envelope)

    def test_undeclared_interface_returns_structured_unsupported(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            capability_manifest_lookup=lambda workspace_id: {"entities": [{"key": "devices"}, {"key": "locations"}]},
            app_operation_lookup=lambda message, manifest: {
                "intent_type": "unsupported_declared_entity",
                "resolved_subject": {"entity_key": "interface"},
                "action_payload": {"alternative": "propose_app_evolution"},
                "confidence": 0.72,
                "resolution_notes": ["interface is not declared in the installed capability manifest"],
            },
        )
        envelope = engine.resolve_intent(
            user_message="create interface gi0/1 on router-1",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertEqual(envelope.intent_type, IntentType.UNSUPPORTED_DECLARED_ENTITY.value)
        self.assertEqual(envelope.action_payload.get("alternative"), "propose_app_evolution")
        self.assertEnvelopeStable(envelope)

    def test_continue_the_work_returns_clarification(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            work_item_lookup=lambda query, workspace_id: [
                {"id": "task-1", "label": "Epic D 1", "kind": "dev_task", "work_item_id": "epic-d-1"},
                {"id": "task-2", "label": "Epic D 2", "kind": "dev_task", "work_item_id": "epic-d-2"},
            ],
        )
        envelope = engine.resolve_intent(
            user_message="continue the work",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertTrue(envelope.needs_clarification)
        self.assertEqual(envelope.clarification_reason, ClarificationReason.AMBIGUOUS_TARGET.value)
        self.assertEqual(len(envelope.clarification_options), 2)
        self.assertEnvelopeStable(envelope)

    def test_update_the_record_returns_clarification(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            capability_manifest_lookup=lambda workspace_id: {
                "entities": [{"key": "devices", "plural_label": "devices"}, {"key": "locations", "plural_label": "locations"}]
            },
            app_operation_lookup=lambda message, manifest: {
                "intent_type": "update_record",
                "needs_clarification": True,
                "clarification_reason": "ambiguous_target",
                "clarification_options": [
                    {"id": "devices", "label": "devices", "kind": "entity", "payload": {"entity_key": "devices"}},
                    {"id": "locations", "label": "locations", "kind": "entity", "payload": {"entity_key": "locations"}},
                ],
                "confidence": 0.4,
                "resolution_notes": ["record target is ambiguous"],
            },
        )
        envelope = engine.resolve_intent(
            user_message="update the record",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertTrue(envelope.needs_clarification)
        self.assertEqual(envelope.intent_family, IntentFamily.APP_OPERATION.value)
        self.assertEnvelopeStable(envelope)

    def test_rerun_it_returns_clarification(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            run_lookup=lambda query, workspace_id: [],
        )
        envelope = engine.resolve_intent(
            user_message="rerun it",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertTrue(envelope.needs_clarification)
        self.assertEqual(envelope.intent_type, IntentType.RETRY_RUN.value)
        self.assertEnvelopeStable(envelope)

    def test_summarize_current_run_resolves(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            run_lookup=lambda query, workspace_id: [{"id": "run-1", "label": "run-1", "kind": "runtime_run", "run_id": "run-1"}],
        )
        envelope = engine.resolve_intent(
            user_message="summarize the current run",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertEqual(envelope.intent_family, IntentFamily.RUN_SUPERVISION.value)
        self.assertEqual(envelope.intent_type, IntentType.SUMMARIZE_RUN.value)
        self.assertEnvelopeStable(envelope)

    def test_show_me_what_failed_resolves(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            run_lookup=lambda query, workspace_id: [{"id": "run-1", "label": "run-1", "kind": "runtime_run", "run_id": "run-1"}],
        )
        envelope = engine.resolve_intent(
            user_message="show me what failed",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertEqual(envelope.intent_type, IntentType.SHOW_STATUS.value)
        self.assertEqual(envelope.action_payload.get("status_filter"), "failed")
        self.assertEnvelopeStable(envelope)

    def test_pause_here_and_wait_for_review_sets_pause_and_review_policy(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            run_lookup=lambda query, workspace_id: [{"id": "run-1", "label": "run-1", "kind": "runtime_run", "run_id": "run-1"}],
        )
        envelope = engine.resolve_intent(
            user_message="pause here and wait for review",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertEqual(envelope.intent_type, IntentType.PAUSE_OR_HOLD.value)
        self.assertEqual(envelope.intent_family, IntentFamily.RUN_SUPERVISION.value)
        self.assertIn("pause requested", " ".join(envelope.resolution_notes).lower())
        self.assertEnvelopeStable(envelope)

    def test_unmatched_message_returns_stable_unsupported_envelope(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
        )
        envelope = engine.resolve_intent(
            user_message="hello there",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertEqual(envelope.intent_family, IntentFamily.DEVELOPMENT_WORK.value)
        self.assertEqual(envelope.intent_type, IntentType.UNSUPPORTED_INTENT.value)
        self.assertFalse(envelope.needs_clarification)
        self.assertEqual(envelope.target_context.get("workspace_id"), "ws-1")
        self.assertEnvelopeStable(envelope)


class EpicDIntentResolveRouteTests(unittest.TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_resolve_route_returns_structured_intent_and_trace_for_development_resolution(self):
        envelope = IntentEnvelope(
            intent_family=IntentFamily.DEVELOPMENT_WORK.value,
            intent_type=IntentType.CREATE_AND_DISPATCH_RUN.value,
            target_context={"workspace_id": "ws-1"},
            resolved_subject={"work_item_id": "epic-d"},
            action_payload={"reference": "Epic D", "work_item_action": "continue"},
            policy={"run_tests": False},
            confidence=0.9,
            needs_clarification=False,
            clarification_reason=None,
            clarification_options=[],
            resolution_notes=["reused existing work item"],
        )
        logger_calls = []
        request = self.factory.post(
            "/xyn/api/xyn/intent/resolve",
            data='{"message":"continue Epic D implementation","context":{"workspace_id":"ws-1"}}',
            content_type="application/json",
        )
        with patch.object(intent_api, "_intent_engine_enabled", return_value=True), \
            patch.object(intent_api, "_require_authenticated", return_value=SimpleNamespace(id="user-1")), \
            patch.object(intent_api, "_resolve_workspace_for_identity", return_value=SimpleNamespace(id="ws-1")), \
            patch.object(intent_api, "_intent_engine", return_value=SimpleNamespace(resolve_intent=lambda **kwargs: envelope)), \
            patch.object(intent_api, "_audit_intent_event"), \
            patch.object(intent_api, "_log_prompt_activity", side_effect=lambda **kwargs: logger_calls.append(kwargs)):
            response = intent_api.xyn_intent_resolve(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "IntentResolved")
        self.assertEqual((payload.get("intent") or {}).get("intent_type"), IntentType.CREATE_AND_DISPATCH_RUN.value)
        self.assertEqual(((payload.get("prompt_interpretation") or {}).get("execution_mode")), "queued_run")
        self.assertTrue(any(any(step.get("step") == "intent_resolved" for step in (call.get("trace") or [])) for call in logger_calls))

    def test_resolve_route_preserves_draft_ready_for_app_operation_and_attaches_intent(self):
        envelope = IntentEnvelope(
            intent_family=IntentFamily.APP_OPERATION.value,
            intent_type=IntentType.CREATE_RECORD.value,
            target_context={"workspace_id": "ws-1"},
            resolved_subject={"entity_key": "devices"},
            action_payload={"operation": "create", "entity_key": "devices"},
            policy={},
            confidence=0.92,
            needs_clarification=False,
            clarification_reason=None,
            clarification_options=[],
            resolution_notes=["resolved against installed capability manifest"],
        )
        request = self.factory.post(
            "/xyn/api/xyn/intent/resolve",
            data='{"message":"create a device called r1","context":{"workspace_id":"ws-1"}}',
            content_type="application/json",
        )
        with patch.object(intent_api, "_intent_engine_enabled", return_value=True), \
            patch.object(intent_api, "_require_authenticated", return_value=SimpleNamespace(id="user-1")), \
            patch.object(intent_api, "_resolve_workspace_for_identity", return_value=SimpleNamespace(id="ws-1")), \
            patch.object(intent_api, "_intent_engine", return_value=SimpleNamespace(resolve_intent=lambda **kwargs: envelope)), \
            patch.object(intent_api, "_audit_intent_event"), \
            patch.object(intent_api, "_log_prompt_activity"):
            response = intent_api.xyn_intent_resolve(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "DraftReady")
        self.assertEqual((payload.get("intent") or {}).get("intent_type"), IntentType.CREATE_RECORD.value)
        self.assertEqual(((payload.get("prompt_interpretation") or {}).get("target_entity") or {}).get("key"), "devices")
        self.assertEqual(((payload.get("draft_payload") or {}).get("structured_operation") or {}).get("operation"), "create")

    def test_resolve_route_returns_machine_readable_unsupported_for_undeclared_entity(self):
        envelope = IntentEnvelope(
            intent_family=IntentFamily.APP_OPERATION.value,
            intent_type=IntentType.UNSUPPORTED_DECLARED_ENTITY.value,
            target_context={"workspace_id": "ws-1"},
            resolved_subject={"entity_key": "interface"},
            action_payload={"alternative": "propose_app_evolution"},
            policy={},
            confidence=0.72,
            needs_clarification=False,
            clarification_reason=None,
            clarification_options=[],
            resolution_notes=["interface is not declared in the installed capability manifest"],
        )
        request = self.factory.post(
            "/xyn/api/xyn/intent/resolve",
            data='{"message":"create interface gi0/1 on router-1","context":{"workspace_id":"ws-1"}}',
            content_type="application/json",
        )
        with patch.object(intent_api, "_intent_engine_enabled", return_value=True), \
            patch.object(intent_api, "_require_authenticated", return_value=SimpleNamespace(id="user-1")), \
            patch.object(intent_api, "_resolve_workspace_for_identity", return_value=SimpleNamespace(id="ws-1")), \
            patch.object(intent_api, "_intent_engine", return_value=SimpleNamespace(resolve_intent=lambda **kwargs: envelope)), \
            patch.object(intent_api, "_audit_intent_event"), \
            patch.object(intent_api, "_log_prompt_activity"):
            response = intent_api.xyn_intent_resolve(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "UnsupportedIntent")
        self.assertEqual((payload.get("intent") or {}).get("intent_type"), IntentType.UNSUPPORTED_DECLARED_ENTITY.value)
        self.assertEqual(((payload.get("prompt_interpretation") or {}).get("capability_state") or {}).get("state"), "known_but_disabled")
        self.assertEqual(((payload.get("intent") or {}).get("action_payload") or {}).get("alternative"), "propose_app_evolution")

    def test_resolve_route_attaches_prompt_interpretation_for_run_supervision(self):
        envelope = IntentEnvelope(
            intent_family=IntentFamily.RUN_SUPERVISION.value,
            intent_type=IntentType.SHOW_STATUS.value,
            target_context={"workspace_id": "ws-1"},
            resolved_subject={"run_id": "run-1", "label": "run-1", "status": "failed"},
            action_payload={"reference": "run-1", "status_filter": "failed"},
            policy={},
            confidence=0.85,
            needs_clarification=False,
            clarification_reason=None,
            clarification_options=[],
            resolution_notes=["failure status requested"],
        )
        request = self.factory.post(
            "/xyn/api/xyn/intent/resolve",
            data='{"message":"show me what failed","context":{"workspace_id":"ws-1"}}',
            content_type="application/json",
        )
        with patch.object(intent_api, "_intent_engine_enabled", return_value=True), \
            patch.object(intent_api, "_require_authenticated", return_value=SimpleNamespace(id="user-1")), \
            patch.object(intent_api, "_resolve_workspace_for_identity", return_value=SimpleNamespace(id="ws-1")), \
            patch.object(intent_api, "_intent_engine", return_value=SimpleNamespace(resolve_intent=lambda **kwargs: envelope)), \
            patch.object(intent_api, "_audit_intent_event"), \
            patch.object(intent_api, "_log_prompt_activity"):
            response = intent_api.xyn_intent_resolve(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "IntentResolved")
        self.assertEqual(((payload.get("prompt_interpretation") or {}).get("target_run") or {}).get("id"), "run-1")
        self.assertEqual((payload.get("prompt_interpretation") or {}).get("execution_mode"), "immediate_execution")

    def test_prompt_interpretation_mapper_builds_machine_readable_fields(self):
        interpretation = intent_api._prompt_interpretation_from_intent(
            message="create a device called r1 in St. Louis",
            intent_payload=IntentEnvelope(
                intent_family=IntentFamily.APP_OPERATION.value,
                intent_type=IntentType.CREATE_RECORD.value,
                target_context={"workspace_id": "ws-1"},
                resolved_subject={"entity_key": "devices"},
                action_payload={"operation": "create", "entity_key": "devices", "fields": {"name": "r1", "location_id": "St. Louis"}},
                policy={},
                confidence=0.93,
                needs_clarification=False,
                clarification_reason=None,
                clarification_options=[],
                resolution_notes=["resolved against installed capability manifest"],
            ).model_dump(mode="json"),
            resolution_status="DraftReady",
            summary="Will execute generated app create_record intent.",
        )
        self.assertEqual(interpretation["intent_type"], IntentType.CREATE_RECORD.value)
        self.assertEqual((interpretation["target_entity"] or {}).get("key"), "devices")
        self.assertEqual(interpretation["execution_mode"], "immediate_execution")
        self.assertTrue(any(field.get("name") == "name" for field in interpretation["fields"]))
        self.assertTrue(any(span.get("kind") == "action" for span in interpretation["recognized_spans"]))

    def test_resolve_route_preserves_legacy_app_builder_flow_without_epic_d_intent(self):
        request = self.factory.post(
            "/xyn/api/xyn/intent/resolve",
            data='{"message":"build a new app","context":{"workspace_id":"ws-1"}}',
            content_type="application/json",
        )
        with patch.object(intent_api, "_intent_engine_enabled", return_value=True), \
            patch.object(intent_api, "_require_authenticated", return_value=SimpleNamespace(id="user-1")), \
            patch.object(intent_api, "_match_app_builder_command", return_value={"operation": "create_app_intent_draft", "title": "New App", "raw_prompt": "build a new app", "initial_intent": {"app_kind": "network_inventory"}}), \
            patch.object(intent_api, "_resolve_workspace_for_identity", return_value=SimpleNamespace(id="ws-1")), \
            patch.object(intent_api, "_audit_intent_event"), \
            patch.object(intent_api, "_log_prompt_activity"):
            response = intent_api.xyn_intent_resolve(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "DraftReady")
        self.assertEqual((payload.get("draft_payload") or {}).get("__operation"), "create_app_intent_draft")
        self.assertNotIn("intent", payload)

    def test_resolve_route_unmatched_request_falls_through_to_legacy_unsupported_result(self):
        epic_d_unsupported = IntentEnvelope(
            intent_family=IntentFamily.DEVELOPMENT_WORK.value,
            intent_type=IntentType.UNSUPPORTED_INTENT.value,
            target_context={"workspace_id": "ws-1"},
            resolved_subject={},
            action_payload={},
            policy={},
            confidence=0.0,
            needs_clarification=False,
            clarification_reason=None,
            clarification_options=[],
            resolution_notes=["no Epic D resolver matched the message"],
        )
        legacy_engine = SimpleNamespace(
            resolve=lambda **kwargs: (
                {
                    "status": "UnsupportedIntent",
                    "action_type": "ValidateDraft",
                    "artifact_type": "ArticleDraft",
                    "artifact_id": None,
                    "summary": "Intent is ambiguous; provide clearer draft instructions.",
                    "next_actions": [],
                    "audit": {"request_id": "req-1", "timestamp": "2026-03-11T00:00:00Z"},
                },
                {"action_type": "ValidateDraft", "artifact_type": "ArticleDraft"},
            )
        )
        request = self.factory.post(
            "/xyn/api/xyn/intent/resolve",
            data='{"message":"hello there","context":{"workspace_id":"ws-1"}}',
            content_type="application/json",
        )
        with patch.object(intent_api, "_intent_engine_enabled", return_value=True), \
            patch.object(intent_api, "_require_authenticated", return_value=SimpleNamespace(id="user-1")), \
            patch.object(intent_api, "_resolve_workspace_for_identity", return_value=SimpleNamespace(id="ws-1")), \
            patch.object(intent_api, "_workspace_runtime_target", return_value=None), \
            patch.object(intent_api, "_workspace_generated_artifact_issue", return_value=None), \
            patch.object(intent_api, "_workspace_installed_capability_manifest", return_value=None), \
            patch.object(intent_api, "_match_generated_app_evolution_command", return_value=None), \
            patch.object(intent_api, "_match_provision_xyn_remote_command", return_value=None), \
            patch.object(intent_api, "_match_install_xyn_instance_command", return_value=None), \
            patch.object(intent_api, "_match_create_ems_instance_command", return_value=None), \
            patch.object(intent_api, "_match_ems_panel_command", return_value=None), \
            patch.object(intent_api, "_match_artifact_panel_command", return_value=None), \
            patch.object(intent_api, "_match_deploy_ems_customer_command", return_value=None), \
            patch.object(intent_api, "_intent_engine", side_effect=[SimpleNamespace(resolve_intent=lambda **kwargs: epic_d_unsupported), legacy_engine]), \
            patch.object(intent_api, "_audit_intent_event"), \
            patch.object(intent_api, "_log_prompt_activity"):
            response = intent_api.xyn_intent_resolve(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "UnsupportedIntent")
        self.assertNotIn("intent", payload)
        self.assertNotEqual(payload["status"], "IntentResolved")
