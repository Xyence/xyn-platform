import json
import unittest
import uuid
import datetime as dt
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory

from xyn_orchestrator import xyn_api as intent_api
from xyn_orchestrator.intent_engine.contracts import DraftIntakeContractRegistry
from xyn_orchestrator.intent_engine.engine import IntentResolutionEngine, ResolutionContext
from xyn_orchestrator.intent_engine.types import ClarificationReason, ConversationExecutionContext, IntentEnvelope, IntentFamily, IntentType


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

    def test_start_new_development_thread_resolves_to_create_thread(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
        )
        envelope = engine.resolve_intent(
            user_message="start a new development thread for runtime refactor",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertEqual(envelope.intent_family, IntentFamily.THREAD_COORDINATION.value)
        self.assertEqual(envelope.intent_type, IntentType.CREATE_THREAD.value)
        self.assertEqual(envelope.action_payload.get("title"), "runtime refactor")
        self.assertEnvelopeStable(envelope)

    def test_pause_this_thread_uses_active_thread_context(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
        )
        envelope = engine.resolve_intent(
            user_message="pause this thread",
            context=ResolutionContext(
                workspace_id="ws-1",
                conversation_context=ConversationExecutionContext(
                    active_coordination_thread_id="thread-1",
                ),
            ),
        )
        self.assertEqual(envelope.intent_family, IntentFamily.THREAD_COORDINATION.value)
        self.assertEqual(envelope.intent_type, IntentType.PAUSE_THREAD.value)
        self.assertEqual(envelope.resolved_subject.get("id"), "thread-1")
        self.assertEnvelopeStable(envelope)

    def test_prioritize_thread_reference_resolves_through_thread_lookup(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            thread_lookup=lambda query, workspace_id: [
                {"id": "thread-2", "label": "Runtime Refactor", "kind": "coordination_thread"}
            ],
        )
        envelope = engine.resolve_intent(
            user_message="prioritize the runtime refactor thread to critical",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertEqual(envelope.intent_family, IntentFamily.THREAD_COORDINATION.value)
        self.assertEqual(envelope.intent_type, IntentType.PRIORITIZE_THREAD.value)
        self.assertEqual(envelope.resolved_subject.get("id"), "thread-2")
        self.assertEqual(envelope.action_payload.get("priority"), "critical")
        self.assertEnvelopeStable(envelope)

    def test_create_goal_resolves_for_real_estate_build_request(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
        )
        envelope = engine.resolve_intent(
            user_message="Build the AI real estate deal finder application",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertEqual(envelope.intent_family, IntentFamily.GOAL_PLANNING.value)
        self.assertEqual(envelope.intent_type, IntentType.CREATE_GOAL.value)
        self.assertEqual(envelope.action_payload.get("goal_type"), "build_system")
        self.assertIn("real estate deal finder", str(envelope.action_payload.get("title") or "").lower())
        self.assertEnvelopeStable(envelope)

    def test_decompose_goal_uses_active_goal_context(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
        )
        envelope = engine.resolve_intent(
            user_message="break this goal into implementation threads",
            context=ResolutionContext(
                workspace_id="ws-1",
                conversation_context=ConversationExecutionContext(active_goal_id="goal-1"),
            ),
        )
        self.assertEqual(envelope.intent_family, IntentFamily.GOAL_PLANNING.value)
        self.assertEqual(envelope.intent_type, IntentType.DECOMPOSE_GOAL.value)
        self.assertEqual(envelope.resolved_subject.get("id"), "goal-1")
        self.assertEnvelopeStable(envelope)

    def test_artifact_panel_matcher_accepts_natural_list_phrase(self):
        self.assertEqual(
            intent_api._match_artifact_panel_command("show me a list of artifacts"),
            ("artifact_list", {}),
        )

    def test_artifact_panel_matcher_accepts_stable_direct_view_variants(self):
        self.assertEqual(
            intent_api._match_artifact_panel_command("open artifacts"),
            ("artifact_list", {}),
        )
        self.assertEqual(
            intent_api._match_artifact_panel_command("please, show me a list of artifacts."),
            ("artifact_list", {}),
        )

    def test_artifact_panel_matcher_extracts_supported_created_day_filters(self):
        self.assertEqual(
            intent_api._match_artifact_panel_command("show me artifacts created yesterday"),
            (
                "artifact_list",
                {
                    "query": {
                        "entity": "artifacts",
                        "filters": [
                            {"field": "created_at", "op": "gte", "value": "day-start:-1"},
                            {"field": "created_at", "op": "lt", "value": "day-start:0"},
                        ],
                        "sort": [{"field": "created_at", "dir": "desc"}],
                        "limit": 50,
                        "offset": 0,
                    }
                },
            ),
        )
        self.assertEqual(
            intent_api._match_artifact_panel_command("show me the artifacts created two days ago"),
            (
                "artifact_list",
                {
                    "query": {
                        "entity": "artifacts",
                        "filters": [
                            {"field": "created_at", "op": "gte", "value": "day-start:-2"},
                            {"field": "created_at", "op": "lt", "value": "day-start:-1"},
                        ],
                        "sort": [{"field": "created_at", "dir": "desc"}],
                        "limit": 50,
                        "offset": 0,
                    }
                },
            ),
        )

    def test_artifact_panel_matcher_does_not_trap_broader_semantic_requests(self):
        self.assertIsNone(intent_api._match_artifact_panel_command("summarize artifact changes from the last run"))

    def test_artifact_panel_matcher_marks_unsupported_filter_semantics(self):
        self.assertEqual(
            intent_api._unsupported_artifact_filter_reason("show me artifacts with status draft"),
            "Artifact list filters currently support only created today, created yesterday, or created two days ago.",
        )
        self.assertEqual(
            intent_api._unsupported_artifact_filter_reason("show me artifacts created three weeks ago"),
            "Artifact list filters currently support only created today, created yesterday, or created two days ago.",
        )

    def test_core_surface_matcher_accepts_natural_platform_settings_phrase(self):
        self.assertEqual(
            intent_api._match_core_surface_command("please open the platform settings page"),
            ("platform_settings", {}),
        )

    def test_core_surface_matcher_accepts_stable_platform_settings_variants(self):
        self.assertEqual(
            intent_api._match_core_surface_command("take me to platform settings"),
            ("platform_settings", {}),
        )
        self.assertEqual(
            intent_api._match_core_surface_command("please, open the platform settings page."),
            ("platform_settings", {}),
        )

    def test_core_surface_matcher_does_not_trap_broader_platform_help_requests(self):
        self.assertIsNone(intent_api._match_core_surface_command("help me understand how platform settings work"))

    def test_legacy_article_intake_extracts_title_from_with_the_title_phrase(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
        )
        result, _proposal = engine.resolve(
            message='create an article about whales with the title "whales" in the demo category',
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertEqual(result["status"], "DraftReady")
        self.assertEqual((result.get("draft_payload") or {}).get("title"), "whales")
        self.assertEqual((result.get("draft_payload") or {}).get("category"), "demo")

    def test_legacy_article_intake_extracts_title_from_titled_phrase(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
        )
        result, _proposal = engine.resolve(
            message='create an article about whales titled "whales" in the demo category',
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertEqual(result["status"], "DraftReady")
        self.assertEqual((result.get("draft_payload") or {}).get("title"), "whales")
        self.assertEqual((result.get("draft_payload") or {}).get("category"), "demo")

    def test_legacy_article_intake_without_title_still_reports_missing_title(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
        )
        result, _proposal = engine.resolve(
            message="create an article about whales in the demo category",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertEqual(result["status"], "MissingFields")
        self.assertEqual([row.get("field") for row in (result.get("missing_fields") or [])], ["title"])

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

    def test_continue_run_resolves(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            run_lookup=lambda query, workspace_id: [{"id": "run-1", "label": "Epic D run", "kind": "runtime_run", "run_id": "run-1"}],
        )
        envelope = engine.resolve_intent(
            user_message="continue the run",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertEqual(envelope.intent_type, IntentType.CONTINUE_RUN.value)
        self.assertEqual(envelope.resolved_subject.get("run_id"), "run-1")
        self.assertEnvelopeStable(envelope)

    def test_show_logs_resolves_to_run_supervision_status_view(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            run_lookup=lambda query, workspace_id: [{"id": "run-1", "label": "Epic D run", "kind": "runtime_run", "run_id": "run-1"}],
        )
        envelope = engine.resolve_intent(
            user_message="show logs",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertEqual(envelope.intent_type, IntentType.SHOW_STATUS.value)
        self.assertEqual(envelope.action_payload.get("detail_view"), "logs")
        self.assertEnvelopeStable(envelope)

    def test_show_artifacts_resolves_to_run_supervision_status_view(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            run_lookup=lambda query, workspace_id: [{"id": "run-1", "label": "Epic D run", "kind": "runtime_run", "run_id": "run-1"}],
        )
        envelope = engine.resolve_intent(
            user_message="show artifacts",
            context=ResolutionContext(workspace_id="ws-1"),
        )
        self.assertEqual(envelope.intent_type, IntentType.SHOW_STATUS.value)
        self.assertEqual(envelope.action_payload.get("detail_view"), "artifacts")
        self.assertEnvelopeStable(envelope)

    def test_worker_mention_is_attached_to_dispatch_run_intent(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            work_item_lookup=lambda query, workspace_id: [
                {"id": "task-1", "label": "Epic D", "kind": "dev_task", "work_item_id": "epic-d"}
            ],
        )
        envelope = engine.resolve_intent(
            user_message="continue Epic D implementation",
            context=ResolutionContext(
                workspace_id="ws-1",
                worker_mention_token="@codex",
                requested_worker_type="codex_local",
                requested_worker_id="worker-1",
                requested_worker_status="idle",
                requested_worker_capabilities=["repo_modification", "test_execution"],
            ),
        )
        self.assertEqual(envelope.intent_type, IntentType.CREATE_AND_DISPATCH_RUN.value)
        self.assertEqual(envelope.action_payload.get("worker_type"), "codex_local")
        self.assertEqual(envelope.target_context.get("requested_worker_id"), "worker-1")
        self.assertIn("worker mention resolved to codex_local", envelope.resolution_notes)

    def test_worker_mention_error_blocks_resolution_safely(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
        )
        envelope = engine.resolve_intent(
            user_message="run the relevant tests",
            context=ResolutionContext(
                workspace_id="ws-1",
                worker_mention_token="@unknown",
                worker_mention_error="Unknown worker mention @unknown.",
            ),
        )
        self.assertEqual(envelope.intent_type, IntentType.UNSUPPORTED_INTENT.value)
        self.assertEqual(envelope.action_payload.get("worker_mention_token"), "@unknown")
        self.assertIn("Unknown worker mention", " ".join(envelope.resolution_notes))

    def test_non_executable_email_like_string_does_not_parse_as_worker_mention(self):
        parsed = intent_api._parse_worker_mention("email me at foo@codex.com")
        self.assertEqual(parsed, {"clean_message": "email me at foo@codex.com"})

    def test_worker_mention_with_parentheses_parses_safely(self):
        with patch.object(
            intent_api,
            "_runtime_worker_directory",
            return_value=[{"worker_id": "worker-1", "worker_type": "codex_local", "status": "idle", "capabilities": []}],
        ):
            parsed = intent_api._parse_worker_mention("(@codex) run tests")
        self.assertEqual(parsed.get("worker_type"), "codex_local")
        self.assertEqual(parsed.get("clean_message"), "run tests")

    def test_unknown_worker_mention_degrades_safely(self):
        parsed = intent_api._parse_worker_mention("@codexx run tests")
        self.assertEqual(parsed.get("mention_token"), "@codexx")
        self.assertIn("Unknown worker mention", str(parsed.get("error") or ""))

    def test_multiple_mentions_use_only_the_leading_worker_token(self):
        with patch.object(
            intent_api,
            "_runtime_worker_directory",
            return_value=[{"worker_id": "worker-1", "worker_type": "codex_local", "status": "idle", "capabilities": []}],
        ):
            parsed = intent_api._parse_worker_mention("@codex run tests with @repo_inspector later")
        self.assertEqual(parsed.get("worker_type"), "codex_local")
        self.assertIn("@repo_inspector", str(parsed.get("clean_message") or ""))

    def test_generic_continue_uses_conversation_context_work_item(self):
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            work_item_lookup=lambda query, workspace_id: [
                {"id": "task-1", "label": "Epic D", "kind": "dev_task", "work_item_id": "epic-d"}
            ] if query in {"epic-d", ""} else [],
        )
        envelope = engine.resolve_intent(
            user_message="continue the work",
            context=ResolutionContext(
                workspace_id="ws-1",
                conversation_context=ConversationExecutionContext(current_work_item_id="epic-d"),
            ),
        )
        self.assertEqual(envelope.intent_type, IntentType.CONTINUE_WORK_ITEM.value)
        self.assertEqual(envelope.resolved_subject.get("work_item_id"), "epic-d")

    def test_explicit_work_item_reference_beats_conversation_context(self):
        captured = {}

        def lookup(query, workspace_id):
            captured["query"] = query
            if query == "epic-x":
                return [{"id": "task-2", "label": "Epic X", "kind": "dev_task", "work_item_id": "epic-x"}]
            if query == "epic-d":
                return [{"id": "task-1", "label": "Epic D", "kind": "dev_task", "work_item_id": "epic-d"}]
            return []

        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            work_item_lookup=lookup,
        )
        envelope = engine.resolve_intent(
            user_message="continue work item epic-x",
            context=ResolutionContext(
                workspace_id="ws-1",
                conversation_context=ConversationExecutionContext(current_work_item_id="epic-d"),
            ),
        )
        self.assertEqual(captured["query"], "epic-x")
        self.assertEqual(envelope.resolved_subject.get("work_item_id"), "epic-x")
        self.assertNotIn("context_work_item", " ".join(envelope.resolution_notes))

    def test_explicit_run_reference_beats_conversation_context(self):
        captured = {}

        def run_lookup(query, workspace_id):
            captured["query"] = query
            if query == "123":
                return [{"id": "run-123", "label": "run-123", "kind": "runtime_run", "run_id": "run-123"}]
            if query == "run-456":
                return [{"id": "run-456", "label": "run-456", "kind": "runtime_run", "run_id": "run-456"}]
            return []

        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
            run_lookup=run_lookup,
        )
        envelope = engine.resolve_intent(
            user_message="pause run 123",
            context=ResolutionContext(
                workspace_id="ws-1",
                conversation_context=ConversationExecutionContext(current_run_id="run-456"),
            ),
        )
        self.assertEqual(captured["query"], "123")
        self.assertEqual(envelope.intent_type, IntentType.PAUSE_OR_HOLD.value)
        self.assertEqual(envelope.resolved_subject.get("run_id"), "run-123")
        self.assertNotIn("context_run", " ".join(envelope.resolution_notes))

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
            data='{"message":"continue Epic D implementation","context":{"workspace_id":"ws-1","thread_id":"thread-1"}}',
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
        self.assertEqual(payload["status"], "DraftReady")
        self.assertEqual((payload.get("intent") or {}).get("intent_type"), IntentType.CREATE_AND_DISPATCH_RUN.value)
        self.assertEqual(((payload.get("prompt_interpretation") or {}).get("execution_mode")), "queued_run")
        self.assertEqual(((payload.get("conversation_action") or {}).get("action_type")), "dispatch_run")
        self.assertEqual(((payload.get("conversation_action") or {}).get("thread_id")), "thread-1")
        self.assertEqual(((payload.get("draft_payload") or {}).get("thread_id")), "thread-1")
        self.assertEqual(((payload.get("draft_payload") or {}).get("__operation")), "execute_conversation_action")
        self.assertTrue(any(call.get("thread_id") == "thread-1" for call in logger_calls))
        self.assertTrue(any(any(step.get("step") == "intent_resolved" for step in (call.get("trace") or [])) for call in logger_calls))

    def test_resolve_route_returns_thread_intent_and_prompt_interpretation(self):
        envelope = IntentEnvelope(
            intent_family=IntentFamily.THREAD_COORDINATION.value,
            intent_type=IntentType.LIST_THREADS.value,
            target_context={"workspace_id": "ws-1"},
            resolved_subject={},
            action_payload={},
            policy={},
            confidence=0.92,
            needs_clarification=False,
            clarification_reason=None,
            clarification_options=[],
            resolution_notes=["listing active threads"],
        )
        request = self.factory.post(
            "/xyn/api/xyn/intent/resolve",
            data='{"message":"list active threads","context":{"workspace_id":"ws-1","thread_id":"thread-1"}}',
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
        self.assertEqual((payload.get("intent") or {}).get("intent_type"), IntentType.LIST_THREADS.value)
        self.assertEqual(((payload.get("conversation_action") or {}).get("action_type")), "list_threads")
        self.assertEqual(((payload.get("conversation_action") or {}).get("thread_id")), "thread-1")

    def test_resolve_route_returns_goal_intent_and_prompt_interpretation(self):
        envelope = IntentEnvelope(
            intent_family=IntentFamily.GOAL_PLANNING.value,
            intent_type=IntentType.CREATE_GOAL.value,
            target_context={"workspace_id": "ws-1"},
            resolved_subject={},
            action_payload={"title": "AI Real Estate Deal Finder", "goal_type": "build_system"},
            policy={},
            confidence=0.93,
            needs_clarification=False,
            clarification_reason=None,
            clarification_options=[],
            resolution_notes=["creating a new goal and decomposition plan"],
        )
        request = self.factory.post(
            "/xyn/api/xyn/intent/resolve",
            data='{"message":"Build the AI real estate deal finder application","context":{"workspace_id":"ws-1","thread_id":"thread-1"}}',
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
        self.assertEqual((payload.get("intent") or {}).get("intent_type"), IntentType.CREATE_GOAL.value)
        self.assertEqual(((payload.get("conversation_action") or {}).get("action_type")), "create_goal")
        self.assertEqual(((payload.get("conversation_action") or {}).get("thread_id")), "thread-1")
        self.assertEqual(((payload.get("prompt_interpretation") or {}).get("target_goal") or {}).get("label"), "AI Real Estate Deal Finder")

    def test_resolve_route_parses_worker_mentions_through_epic_d(self):
        captured = {}
        envelope = IntentEnvelope(
            intent_family=IntentFamily.DEVELOPMENT_WORK.value,
            intent_type=IntentType.CREATE_AND_DISPATCH_RUN.value,
            target_context={"workspace_id": "ws-1", "requested_worker_type": "codex_local"},
            resolved_subject={"work_item_id": "epic-d"},
            action_payload={"reference": "Epic D", "worker_type": "codex_local"},
            policy={},
            confidence=0.9,
            needs_clarification=False,
            clarification_reason=None,
            clarification_options=[],
            resolution_notes=["reused existing work item", "worker mention resolved to codex_local"],
        )
        request = self.factory.post(
            "/xyn/api/xyn/intent/resolve",
            data='{"message":"@codex continue Epic D implementation","context":{"workspace_id":"ws-1"}}',
            content_type="application/json",
        )
        def _resolve_with_capture(**kwargs):
            captured["context"] = kwargs.get("context")
            return envelope

        with patch.object(intent_api, "_intent_engine_enabled", return_value=True), \
            patch.object(intent_api, "_require_authenticated", return_value=SimpleNamespace(id="user-1")), \
            patch.object(intent_api, "_resolve_workspace_for_identity", return_value=SimpleNamespace(id="ws-1")), \
            patch.object(intent_api, "_runtime_worker_directory", return_value=[{"worker_id": "worker-1", "worker_type": "codex_local", "status": "idle", "capabilities": ["repo_modification", "test_execution"]}]), \
            patch.object(intent_api, "_intent_engine", return_value=SimpleNamespace(resolve_intent=_resolve_with_capture)), \
            patch.object(intent_api, "_audit_intent_event"), \
            patch.object(intent_api, "_log_prompt_activity"):
            response = intent_api.xyn_intent_resolve(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(getattr(captured.get("context"), "requested_worker_type", ""), "codex_local")
        self.assertEqual(getattr(captured.get("context"), "worker_mention_token", ""), "@codex")
        self.assertEqual((payload.get("intent") or {}).get("action_payload", {}).get("worker_type"), "codex_local")
        self.assertEqual(((payload.get("conversation_action") or {}).get("target_object") or {}).get("workspace_id"), "ws-1")

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
        self.assertEqual(((payload.get("conversation_action") or {}).get("action_type")), "execute_entity_operation")
        self.assertEqual(((payload.get("draft_payload") or {}).get("structured_operation") or {}).get("operation"), "create")

    def test_resolve_route_returns_direct_panel_intent_for_natural_artifact_list_phrase(self):
        request = self.factory.post(
            "/xyn/api/xyn/intent/resolve",
            data='{"message":"show me a list of artifacts","context":{"workspace_id":"ws-1"}}',
            content_type="application/json",
        )
        with patch.object(intent_api, "_intent_engine_enabled", return_value=True), \
            patch.object(intent_api, "_require_authenticated", return_value=SimpleNamespace(id="user-1")), \
            patch.object(intent_api, "_resolve_workspace_for_identity", return_value=SimpleNamespace(id="ws-1")), \
            patch.object(intent_api, "_audit_intent_event"), \
            patch.object(intent_api, "_log_prompt_activity"):
            response = intent_api.xyn_intent_resolve(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "IntentResolved")
        self.assertNotEqual(payload["status"], "DraftReady")
        self.assertEqual(((payload.get("next_actions") or [])[0] or {}).get("action"), "OpenPanel")
        self.assertEqual(((payload.get("next_actions") or [])[0] or {}).get("panel_key"), "artifact_list")
        self.assertEqual((payload.get("prompt_interpretation") or {}).get("execution_mode"), "immediate_execution")

    def test_resolve_route_returns_direct_panel_intent_for_open_artifacts_variant(self):
        request = self.factory.post(
            "/xyn/api/xyn/intent/resolve",
            data='{"message":"open artifacts","context":{"workspace_id":"ws-1"}}',
            content_type="application/json",
        )
        with patch.object(intent_api, "_intent_engine_enabled", return_value=True), \
            patch.object(intent_api, "_require_authenticated", return_value=SimpleNamespace(id="user-1")), \
            patch.object(intent_api, "_resolve_workspace_for_identity", return_value=SimpleNamespace(id="ws-1")), \
            patch.object(intent_api, "_audit_intent_event"), \
            patch.object(intent_api, "_log_prompt_activity"):
            response = intent_api.xyn_intent_resolve(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "IntentResolved")
        self.assertEqual(((payload.get("next_actions") or [])[0] or {}).get("panel_key"), "artifact_list")
        self.assertNotEqual(payload["status"], "DraftReady")

    def test_resolve_route_returns_direct_panel_intent_for_supported_artifact_created_filter(self):
        request = self.factory.post(
            "/xyn/api/xyn/intent/resolve",
            data='{"message":"show me artifacts created yesterday","context":{"workspace_id":"ws-1"}}',
            content_type="application/json",
        )
        with patch.object(intent_api, "_intent_engine_enabled", return_value=True), \
            patch.object(intent_api, "_require_authenticated", return_value=SimpleNamespace(id="user-1")), \
            patch.object(intent_api, "_resolve_workspace_for_identity", return_value=SimpleNamespace(id="ws-1")), \
            patch.object(intent_api, "_audit_intent_event"), \
            patch.object(intent_api, "_log_prompt_activity"):
            response = intent_api.xyn_intent_resolve(request)
        payload = json.loads(response.content)
        action = ((payload.get("next_actions") or [])[0] or {})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "IntentResolved")
        self.assertEqual(action.get("action"), "OpenPanel")
        self.assertEqual(action.get("panel_key"), "artifact_list")
        self.assertEqual(((action.get("params") or {}).get("query") or {}).get("filters"), [
            {"field": "created_at", "op": "gte", "value": "day-start:-1"},
            {"field": "created_at", "op": "lt", "value": "day-start:0"},
        ])
        self.assertNotEqual(payload["status"], "DraftReady")

    def test_resolve_route_rejects_unsupported_artifact_filter_semantics(self):
        request = self.factory.post(
            "/xyn/api/xyn/intent/resolve",
            data='{"message":"show me artifacts with status draft","context":{"workspace_id":"ws-1"}}',
            content_type="application/json",
        )
        with patch.object(intent_api, "_intent_engine_enabled", return_value=True), \
            patch.object(intent_api, "_require_authenticated", return_value=SimpleNamespace(id="user-1")), \
            patch.object(intent_api, "_resolve_workspace_for_identity", return_value=SimpleNamespace(id="ws-1")), \
            patch.object(intent_api, "_audit_intent_event"), \
            patch.object(intent_api, "_log_prompt_activity"):
            response = intent_api.xyn_intent_resolve(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "UnsupportedIntent")
        self.assertEqual(payload["summary"], "Artifact list filters currently support only created today, created yesterday, or created two days ago.")
        self.assertEqual(payload.get("next_actions"), [])

    def test_resolve_route_returns_direct_panel_intent_for_natural_platform_settings_phrase(self):
        request = self.factory.post(
            "/xyn/api/xyn/intent/resolve",
            data='{"message":"please open the platform settings page","context":{"workspace_id":"ws-1"}}',
            content_type="application/json",
        )
        with patch.object(intent_api, "_intent_engine_enabled", return_value=True), \
            patch.object(intent_api, "_require_authenticated", return_value=SimpleNamespace(id="user-1")), \
            patch.object(intent_api, "_resolve_workspace_for_identity", return_value=SimpleNamespace(id="ws-1")), \
            patch.object(intent_api, "_audit_intent_event"), \
            patch.object(intent_api, "_log_prompt_activity"):
            response = intent_api.xyn_intent_resolve(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "IntentResolved")
        self.assertEqual(((payload.get("next_actions") or [])[0] or {}).get("action"), "OpenPanel")
        self.assertEqual(((payload.get("next_actions") or [])[0] or {}).get("panel_key"), "platform_settings")
        self.assertEqual((payload.get("prompt_interpretation") or {}).get("execution_mode"), "immediate_execution")

    def test_resolve_route_returns_direct_panel_intent_for_take_me_to_platform_settings(self):
        request = self.factory.post(
            "/xyn/api/xyn/intent/resolve",
            data='{"message":"take me to platform settings","context":{"workspace_id":"ws-1"}}',
            content_type="application/json",
        )
        with patch.object(intent_api, "_intent_engine_enabled", return_value=True), \
            patch.object(intent_api, "_require_authenticated", return_value=SimpleNamespace(id="user-1")), \
            patch.object(intent_api, "_resolve_workspace_for_identity", return_value=SimpleNamespace(id="ws-1")), \
            patch.object(intent_api, "_audit_intent_event"), \
            patch.object(intent_api, "_log_prompt_activity"):
            response = intent_api.xyn_intent_resolve(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "IntentResolved")
        self.assertEqual(((payload.get("next_actions") or [])[0] or {}).get("panel_key"), "platform_settings")
        self.assertNotEqual(payload["status"], "DraftReady")


class ArtifactCollectionFilterTests(unittest.TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_artifacts_collection_applies_created_day_window_filters(self):
        fixed_now = dt.datetime(2026, 3, 12, 15, 0, tzinfo=dt.timezone.utc)
        fake_rows = {
            "art-1": {"slug": "art-1", "created_at": "2026-03-11T12:00:00Z"},
            "art-2": {"slug": "art-2", "created_at": "2026-03-10T12:00:00Z"},
            "art-3": {"slug": "art-3", "created_at": "2026-03-12T12:00:00Z"},
        }
        artifacts = [SimpleNamespace(id=slug) for slug in fake_rows]
        manager = SimpleNamespace(select_related=lambda *args, **kwargs: SimpleNamespace(all=lambda: artifacts))
        request = self.factory.get(
            "/xyn/api/artifacts",
            data={
                "entity": "artifacts",
                "filters": json.dumps(
                    [
                        {"field": "created_at", "op": "gte", "value": "day-start:-1"},
                        {"field": "created_at", "op": "lt", "value": "day-start:0"},
                    ]
                ),
                "sort": json.dumps([{"field": "created_at", "dir": "desc"}]),
            },
        )
        request.user = SimpleNamespace(is_staff=True, is_authenticated=True)
        with patch.object(intent_api, "_require_staff", return_value=None), \
            patch.object(intent_api.Artifact, "objects", manager), \
            patch.object(intent_api, "_dedupe_artifacts_for_dataset", side_effect=lambda rows, **kwargs: rows), \
            patch.object(intent_api, "_artifact_table_row", side_effect=lambda artifact, **kwargs: dict(fake_rows[str(artifact.id)])), \
            patch.object(intent_api.timezone, "now", return_value=fixed_now):
            response = intent_api.artifacts_collection(request)
        payload = json.loads(response.content)
        rows = (((payload.get("dataset") or {}).get("rows")) or [])
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row.get("slug") for row in rows], ["art-1"])

    def test_resolve_route_still_uses_epic_d_for_supported_non_deterministic_prompt(self):
        envelope = IntentEnvelope(
            intent_family=IntentFamily.DEVELOPMENT_WORK.value,
            intent_type=IntentType.CREATE_AND_DISPATCH_RUN.value,
            target_context={"workspace_id": "ws-1"},
            resolved_subject={"id": "task-1", "label": "Epic D", "work_item_id": "epic-d"},
            action_payload={"reference": "Epic D", "work_item_action": "continue"},
            policy={},
            confidence=0.91,
            needs_clarification=False,
            clarification_reason=None,
            clarification_options=[],
            resolution_notes=["reused existing work item"],
        )
        engine_calls = []
        request = self.factory.post(
            "/xyn/api/xyn/intent/resolve",
            data='{"message":"continue Epic D implementation","context":{"workspace_id":"ws-1"}}',
            content_type="application/json",
        )
        with patch.object(intent_api, "_intent_engine_enabled", return_value=True), \
            patch.object(intent_api, "_require_authenticated", return_value=SimpleNamespace(id="user-1")), \
            patch.object(intent_api, "_resolve_workspace_for_identity", return_value=SimpleNamespace(id="ws-1")), \
            patch.object(
                intent_api,
                "_intent_engine",
                return_value=SimpleNamespace(resolve_intent=lambda **kwargs: engine_calls.append(kwargs) or envelope),
            ), \
            patch.object(intent_api, "_audit_intent_event"), \
            patch.object(intent_api, "_log_prompt_activity"):
            response = intent_api.xyn_intent_resolve(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "DraftReady")
        self.assertTrue(engine_calls)
        self.assertEqual((payload.get("intent") or {}).get("intent_type"), IntentType.CREATE_AND_DISPATCH_RUN.value)

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
        self.assertEqual(payload["status"], "DraftReady")
        self.assertEqual(((payload.get("prompt_interpretation") or {}).get("target_run") or {}).get("id"), "run-1")
        self.assertEqual((payload.get("prompt_interpretation") or {}).get("execution_mode"), "immediate_execution")
        self.assertEqual(((payload.get("conversation_action") or {}).get("action_type")), "show_status")
        self.assertEqual(((payload.get("draft_payload") or {}).get("__operation")), "execute_conversation_action")

    def test_resolve_route_returns_draft_ready_for_development_dispatch(self):
        envelope = IntentEnvelope(
            intent_family=IntentFamily.DEVELOPMENT_WORK.value,
            intent_type=IntentType.CREATE_AND_DISPATCH_RUN.value,
            target_context={"workspace_id": "ws-1"},
            resolved_subject={"id": "task-1", "label": "Epic D", "work_item_id": "epic-d"},
            action_payload={"reference": "Epic D", "work_item_action": "continue"},
            policy={"run_tests": True},
            confidence=0.91,
            needs_clarification=False,
            clarification_reason=None,
            clarification_options=[],
            resolution_notes=["reused existing work item"],
        )
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
            patch.object(intent_api, "_log_prompt_activity"):
            response = intent_api.xyn_intent_resolve(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "DraftReady")
        self.assertEqual(((payload.get("conversation_action") or {}).get("action_type")), "dispatch_run")
        self.assertEqual(((payload.get("draft_payload") or {}).get("__operation")), "execute_conversation_action")

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

    def test_conversation_action_mapper_builds_dispatch_run_for_development_intent(self):
        action = intent_api._conversation_action_from_intent(
            source_message_id="msg-1",
            thread_id="thread-1",
            intent_payload=IntentEnvelope(
                intent_family=IntentFamily.DEVELOPMENT_WORK.value,
                intent_type=IntentType.CREATE_AND_DISPATCH_RUN.value,
                target_context={"workspace_id": "ws-1"},
                resolved_subject={"id": "task-1", "label": "Epic D", "work_item_id": "epic-d"},
                action_payload={"reference": "Epic D", "work_item_action": "continue"},
                policy={"run_tests": True},
                confidence=0.93,
                needs_clarification=False,
                clarification_reason=None,
                clarification_options=[],
                resolution_notes=["reused existing work item"],
            ).model_dump(mode="json"),
            prompt_interpretation={
                "intent_family": IntentFamily.DEVELOPMENT_WORK.value,
                "intent_type": IntentType.CREATE_AND_DISPATCH_RUN.value,
                "action": {"verb": "dispatch", "label": "Create and dispatch run"},
                "fields": [],
                "execution_mode": "queued_run",
                "confidence": 0.93,
                "needs_clarification": False,
                "capability_state": {"state": "unknown"},
                "clarification_options": [],
                "resolution_notes": ["reused existing work item"],
                "missing_fields": [],
                "recognized_spans": [],
                "target_work_item": {"id": "task-1", "label": "Epic D", "reference": "epic-d"},
            },
        )
        self.assertEqual(action["action_type"], "dispatch_run")
        self.assertEqual(action["thread_id"], "thread-1")
        self.assertEqual((action.get("target_object") or {}).get("kind"), "work_item")
        self.assertEqual(action["execution_mode"], "queued_run")

    def test_conversation_action_mapper_returns_none_for_clarification(self):
        action = intent_api._conversation_action_from_intent(
            source_message_id="msg-1",
            intent_payload=IntentEnvelope(
                intent_family=IntentFamily.RUN_SUPERVISION.value,
                intent_type=IntentType.RETRY_RUN.value,
                target_context={"workspace_id": "ws-1"},
                resolved_subject={},
                action_payload={"reference": "it"},
                policy={},
                confidence=0.4,
                needs_clarification=True,
                clarification_reason=ClarificationReason.AMBIGUOUS_TARGET.value,
                clarification_options=[],
                resolution_notes=["retry target is ambiguous"],
            ).model_dump(mode="json"),
            prompt_interpretation=None,
        )
        self.assertIsNone(action)

    def test_prompt_activity_mapper_builds_execution_summary_message(self):
        message = intent_api._conversation_message_from_prompt_activity(
            {
                "structured_operation": {"run_id": "run-1", "work_item_id": "epic-d"},
                "prompt_interpretation": {"target_work_item": {"reference": "epic-d"}},
                "conversation_action": {"action_type": "dispatch_run"},
                "thread_id": "thread-1",
            },
            status="succeeded",
            summary="Queued runtime run run-1 for work item epic-d.",
        )
        self.assertEqual(message["message_type"], "execution_summary")
        self.assertEqual((message.get("refs") or {}).get("run_id"), "run-1")
        self.assertEqual((message.get("refs") or {}).get("thread_id"), "thread-1")

    def test_prompt_activity_mapper_builds_escalation_message(self):
        message = intent_api._conversation_message_from_prompt_activity(
            {
                "error": "clarification required",
                "prompt_interpretation": {
                    "needs_clarification": True,
                    "clarification_options": [{"label": "Epic D", "action": "select"}],
                },
            },
            status="failed",
            summary="Clarification required.",
        )
        self.assertEqual(message["message_type"], "escalation")

    def test_prompt_activity_mapper_handles_legacy_records_without_thread_id(self):
        message = intent_api._conversation_message_from_prompt_activity(
            {
                "structured_operation": {"run_id": "run-1"},
                "prompt_interpretation": {"target_run": {"id": "run-1"}},
            },
            status="succeeded",
            summary="Run complete.",
        )
        self.assertIsNotNone(message)
        self.assertIsNone((message.get("refs") or {}).get("thread_id"))

    def test_conversation_runtime_payload_carries_thread_id_in_metadata(self):
        payload = intent_api._conversation_runtime_payload(
            task=SimpleNamespace(id="task-1", title="Epic G", task_type="codegen", work_item_id="epic-g"),
            workspace=SimpleNamespace(id="ws-1"),
            action={"thread_id": "thread-1", "payload": {}},
            prompt="continue Epic G implementation",
        )
        self.assertEqual(((payload.get("context") or {}).get("metadata") or {}).get("thread_id"), "thread-1")

    def test_execute_conversation_action_without_run_returns_clarification(self):
        response = intent_api._execute_conversation_action(
            identity=SimpleNamespace(id="user-1"),
            user=SimpleNamespace(id="user-1"),
            workspace=SimpleNamespace(id="ws-1"),
            action={
                "action_type": "pause_run",
                "target_object": {"kind": "run"},
                "payload": {},
            },
            prompt="pause the run",
            request_id="req-1",
            intent_payload={"intent_type": "pause_or_hold"},
            prompt_interpretation={"intent_type": "pause_or_hold"},
        )
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(payload["status"], "IntentClarificationRequired")

    def test_execute_conversation_action_show_logs_filters_log_artifacts(self):
        run_id = str(uuid.uuid4())
        with patch.object(
            intent_api,
            "_fetch_runtime_run_detail_payload",
            return_value={
                "id": run_id,
                "summary": "done",
                "status": "completed",
                "artifacts": [
                    {"artifact_type": "log", "label": "build log"},
                    {"artifact_type": "summary", "label": "summary"},
                ],
            },
        ):
            response = intent_api._execute_conversation_action(
                identity=SimpleNamespace(id="user-1"),
                user=SimpleNamespace(id="user-1"),
                workspace=SimpleNamespace(id="ws-1"),
                action={
                    "action_type": "show_status",
                    "target_object": {"kind": "run", "id": run_id},
                    "payload": {"action_payload": {"detail_view": "logs"}},
                },
                prompt="show logs",
                request_id="req-1",
                intent_payload={"intent_type": "show_status"},
                prompt_interpretation={"intent_type": "show_status"},
            )
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len((payload.get("result") or {}).get("logs") or []), 1)

    def test_execute_conversation_action_create_work_item_returns_work_item_panel_action(self):
        fake_task = SimpleNamespace(
            id="task-1",
            work_item_id="epic-h",
            title="Epic H",
            description="Implement durable coordination",
            source_conversation_id="thread-1",
            target_repo="xyn-platform",
            target_branch="develop",
            execution_policy={"auto_continue": True},
        )
        with patch.object(intent_api, "_ensure_conversation_dev_task", return_value=fake_task), patch.object(
            intent_api,
            "_serialize_dev_task_summary",
            return_value={"id": "task-1", "work_item_id": "epic-h", "title": "Epic H", "status": "queued"},
        ):
            response = intent_api._execute_conversation_action(
                identity=SimpleNamespace(id="user-1"),
                user=SimpleNamespace(id="user-1"),
                workspace=SimpleNamespace(id="ws-1"),
                action={
                    "action_type": "create_work_item",
                    "thread_id": "thread-1",
                    "payload": {},
                    "target_object": {"reference": "Epic H"},
                },
                prompt="create work item for Epic H",
                request_id="req-1",
                intent_payload={"intent_type": "create_work_item"},
                prompt_interpretation={"intent_type": "create_work_item"},
            )
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "DraftReady")
        self.assertEqual((payload.get("next_actions") or [])[0]["panel_key"], "work_item_detail")

    def test_execute_conversation_action_dispatch_run_returns_run_and_work_item_panel_actions(self):
        fake_task = SimpleNamespace(id="task-1", work_item_id="epic-h")
        with patch.object(intent_api, "_ensure_conversation_dev_task", return_value=fake_task), patch.object(
            intent_api, "_submit_conversation_runtime_run", return_value={"run_id": "run-1", "work_item_id": "epic-h", "status": "queued"}
        ), patch.object(
            intent_api,
            "_serialize_dev_task_summary",
            return_value={"id": "task-1", "work_item_id": "epic-h", "title": "Epic H", "status": "queued"},
        ), patch.object(intent_api, "_project_runtime_status_to_task", return_value={"status": "queued"}):
            response = intent_api._execute_conversation_action(
                identity=SimpleNamespace(id="user-1"),
                user=SimpleNamespace(id="user-1"),
                workspace=SimpleNamespace(id="ws-1"),
                action={
                    "action_type": "dispatch_run",
                    "thread_id": "thread-1",
                    "payload": {},
                    "target_object": {"reference": "Epic H"},
                },
                prompt="continue Epic H implementation",
                request_id="req-1",
                intent_payload={"intent_type": "create_and_dispatch_run"},
                prompt_interpretation={"intent_type": "create_and_dispatch_run"},
            )
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        panel_keys = [entry.get("panel_key") for entry in (payload.get("next_actions") or [])]
        self.assertIn("work_item_detail", panel_keys)
        self.assertIn("run_detail", panel_keys)

    def test_execute_conversation_action_create_goal_returns_goal_panel_action(self):
        goal = SimpleNamespace(id="goal-1", title="AI Real Estate Deal Finder", refresh_from_db=lambda: None)
        detail = {
            "id": "goal-1",
            "title": "AI Real Estate Deal Finder",
            "planning_status": "decomposed",
            "threads": [],
            "work_items": [],
            "planning_summary": "Start with listing ingestion and property CRUD.",
        }
        with patch.object(intent_api.Goal.objects, "create", return_value=goal), patch.object(
            intent_api,
            "decompose_goal",
            return_value=SimpleNamespace(model_dump=lambda mode="json": {"goal_id": "goal-1"}),
        ), patch.object(intent_api, "persist_goal_plan"), patch.object(
            intent_api, "_serialize_goal_detail", return_value=detail
        ):
            response = intent_api._execute_conversation_action(
                identity=SimpleNamespace(id="user-1"),
                user=SimpleNamespace(id="user-1"),
                workspace=SimpleNamespace(id="ws-1"),
                action={
                    "action_type": "create_goal",
                    "thread_id": "thread-1",
                    "payload": {"action_payload": {"title": "AI Real Estate Deal Finder", "goal_type": "build_system"}},
                    "target_object": {"workspace_id": "ws-1"},
                },
                prompt="Build the AI real estate deal finder application",
                request_id="req-1",
                intent_payload={"intent_type": "create_goal"},
                prompt_interpretation={"intent_type": "create_goal"},
            )
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "DraftReady")
        self.assertEqual((payload.get("result") or {}).get("goal", {}).get("id"), "goal-1")
        self.assertEqual((payload.get("next_actions") or [])[0]["panel_key"], "goal_detail")

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

    def test_resolve_route_unmatched_request_stays_on_epic_d_unsupported_boundary(self):
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
            patch.object(intent_api, "_intent_engine", return_value=SimpleNamespace(resolve_intent=lambda **kwargs: epic_d_unsupported)) as mock_engine, \
            patch.object(intent_api, "_audit_intent_event"), \
            patch.object(intent_api, "_log_prompt_activity"):
            response = intent_api.xyn_intent_resolve(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "UnsupportedIntent")
        self.assertEqual((payload.get("intent") or {}).get("intent_type"), IntentType.UNSUPPORTED_INTENT.value)
        self.assertEqual(payload.get("summary"), "no Epic D resolver matched the message")
        self.assertEqual(mock_engine.call_count, 1)

    def test_resolve_route_preserves_residual_legacy_intake_fallback(self):
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
                    "status": "DraftReady",
                    "action_type": "CreateDraft",
                    "artifact_type": "ArticleDraft",
                    "artifact_id": None,
                    "summary": "Ready to draft article content.",
                    "draft_payload": {"title": "Explainer", "format": "article"},
                    "next_actions": [{"label": "Create draft", "action": "CreateDraft"}],
                    "audit": {"request_id": "req-1", "timestamp": "2026-03-11T00:00:00Z"},
                },
                {"action_type": "CreateDraft", "artifact_type": "ArticleDraft"},
            )
        )
        request = self.factory.post(
            "/xyn/api/xyn/intent/resolve",
            data='{"message":"draft an explainer article about governance","context":{"workspace_id":"ws-1"}}',
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
            patch.object(intent_api, "_intent_engine", side_effect=[SimpleNamespace(resolve_intent=lambda **kwargs: epic_d_unsupported), legacy_engine]) as mock_engine, \
            patch.object(intent_api, "_audit_intent_event"), \
            patch.object(intent_api, "_log_prompt_activity"):
            response = intent_api.xyn_intent_resolve(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "DraftReady")
        self.assertEqual(payload["action_type"], "CreateDraft")
        self.assertEqual(payload["artifact_type"], "ArticleDraft")
        self.assertEqual(mock_engine.call_count, 2)

    def test_resolve_route_preserved_legacy_article_intake_extracts_title_fields(self):
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
        legacy_engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(),
            contracts=_registry(),
        )
        request = self.factory.post(
            "/xyn/api/xyn/intent/resolve",
            data='{"message":"create an article about whales with the title \\"whales\\" in the demo category","context":{"workspace_id":"ws-1"}}',
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
        self.assertEqual(payload["status"], "DraftReady")
        self.assertEqual((payload.get("draft_payload") or {}).get("title"), "whales")
        self.assertEqual((payload.get("draft_payload") or {}).get("category"), "demo")

    def test_apply_route_executes_conversation_action(self):
        workspace = SimpleNamespace(id="ws-1")
        request = self.factory.post(
            "/xyn/api/xyn/intent/apply",
            data=json.dumps(
                {
                    "action_type": "CreateDraft",
                    "artifact_type": "Workspace",
                    "payload": {
                        "__operation": "execute_conversation_action",
                        "workspace_id": "ws-1",
                        "raw_prompt": "continue Epic D implementation",
                    },
                }
            ),
            content_type="application/json",
        )
        request.user = SimpleNamespace(id="user-1")
        envelope = IntentEnvelope(
            intent_family=IntentFamily.DEVELOPMENT_WORK.value,
            intent_type=IntentType.CREATE_AND_DISPATCH_RUN.value,
            target_context={"workspace_id": "ws-1"},
            resolved_subject={"id": "task-1", "label": "Epic D", "work_item_id": "epic-d"},
            action_payload={"reference": "Epic D"},
            policy={},
            confidence=0.9,
            needs_clarification=False,
            clarification_reason=None,
            clarification_options=[],
            resolution_notes=["reused existing work item"],
        )
        with patch.object(intent_api, "_intent_engine_enabled", return_value=True), \
            patch.object(intent_api, "_require_authenticated", return_value=SimpleNamespace(id="user-1")), \
            patch.object(intent_api, "_resolve_workspace_for_identity", return_value=workspace), \
            patch.object(intent_api, "_parse_worker_mention", return_value={"clean_message": "continue Epic D implementation"}), \
            patch.object(intent_api, "_conversation_execution_context", return_value=ConversationExecutionContext()), \
            patch.object(intent_api, "_intent_engine", return_value=SimpleNamespace(resolve_intent=lambda **kwargs: envelope)), \
            patch.object(intent_api, "_execute_conversation_action", return_value=intent_api.JsonResponse({"status": "DraftReady", "summary": "Queued runtime run run-1.", "operation_result": True}, status=200)), \
            patch.object(intent_api, "_log_prompt_activity"):
            response = intent_api.xyn_intent_apply(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["summary"], "Queued runtime run run-1.")
        self.assertNotEqual(payload["status"], "IntentResolved")

    def test_apply_route_returns_validation_error_when_run_control_fails(self):
        workspace = SimpleNamespace(id="ws-1")
        request = self.factory.post(
            "/xyn/api/xyn/intent/apply",
            data=json.dumps(
                {
                    "action_type": "CreateDraft",
                    "artifact_type": "Workspace",
                    "payload": {
                        "__operation": "execute_conversation_action",
                        "workspace_id": "ws-1",
                        "raw_prompt": "continue the run",
                    },
                }
            ),
            content_type="application/json",
        )
        request.user = SimpleNamespace(id="user-1")
        envelope = IntentEnvelope(
            intent_family=IntentFamily.RUN_SUPERVISION.value,
            intent_type=IntentType.CONTINUE_RUN.value,
            target_context={"workspace_id": "ws-1"},
            resolved_subject={"run_id": "run-1", "label": "run-1"},
            action_payload={"reference": "run-1"},
            policy={},
            confidence=0.9,
            needs_clarification=False,
            clarification_reason=None,
            clarification_options=[],
            resolution_notes=["continue requested"],
        )
        with patch.object(intent_api, "_intent_engine_enabled", return_value=True), \
            patch.object(intent_api, "_require_authenticated", return_value=SimpleNamespace(id="user-1")), \
            patch.object(intent_api, "_resolve_workspace_for_identity", return_value=workspace), \
            patch.object(intent_api, "_parse_worker_mention", return_value={"clean_message": "continue the run"}), \
            patch.object(intent_api, "_conversation_execution_context", return_value=ConversationExecutionContext(current_run_id="run-1")), \
            patch.object(intent_api, "_intent_engine", return_value=SimpleNamespace(resolve_intent=lambda **kwargs: envelope)), \
            patch.object(intent_api, "_execute_conversation_action", side_effect=RuntimeError("Run is not blocked")), \
            patch.object(intent_api, "_log_prompt_activity"):
            response = intent_api.xyn_intent_apply(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(payload["status"], "ValidationError")
        self.assertIn("Run is not blocked", " ".join(payload.get("validation_errors") or []))
