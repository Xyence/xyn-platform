import json
import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from xyn_orchestrator.intent_engine.contracts import DraftIntakeContractRegistry
from xyn_orchestrator.intent_engine.engine import IntentResolutionEngine, ResolutionContext
from xyn_orchestrator.intent_engine.proposal_provider import IntentContextPackMissingError
from xyn_orchestrator.artifact_links import ensure_context_pack_artifact
from xyn_orchestrator.models import (
    AuditLog,
    Artifact,
    ArtifactType,
    ArticleCategory,
    ContextPack,
    LedgerEvent,
    RoleBinding,
    UserIdentity,
    Workspace,
    WorkspaceAppInstance,
    WorkspaceArtifactBinding,
)


class _FakeProvider:
    def __init__(self, proposal):
        self.proposal = proposal

    def propose(self, **_kwargs):
        return dict(self.proposal)


class IntentEngineApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="intent-admin", password="pass", is_staff=True)
        self.client.force_login(self.user)
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer",
            subject="intent-admin",
            email="intent-admin@example.com",
        )
        RoleBinding.objects.create(user_identity=self.identity, scope_kind="platform", role="platform_admin")
        self.workspace, _ = Workspace.objects.get_or_create(slug="platform-builder", defaults={"name": "Platform Builder"})
        session = self.client.session
        session["user_identity_id"] = str(self.identity.id)
        session.save()
        os.environ["XYN_INTENT_ENGINE_V1"] = "1"

    def tearDown(self):
        os.environ.pop("XYN_INTENT_ENGINE_V1", None)

    def test_contract_no_longer_requires_intent_for_explainer_video(self):
        registry = DraftIntakeContractRegistry(category_options_provider=lambda: [{"slug": "web", "name": "Web"}])
        contract = registry.get("ArticleDraft")
        self.assertIsNotNone(contract)
        assert contract is not None
        merged = contract.merge_defaults({"title": "x", "category": "web", "format": "explainer_video"})
        self.assertNotIn("intent", contract.missing_fields(merged))

    def test_contract_infers_explicit_fields_from_message(self):
        registry = DraftIntakeContractRegistry(category_options_provider=lambda: [{"slug": "demo", "name": "Demo"}])
        contract = registry.get("ArticleDraft")
        self.assertIsNotNone(contract)
        assert contract is not None
        inferred = contract.infer_fields(
            message='Intent: Create an explainer video about Xyn governance ledger for telecom engineers. title: "What I Did On My Summer Vacation". category: demo',
            inferred_fields={},
        )
        self.assertEqual(inferred.get("format"), "explainer_video")
        self.assertEqual(inferred.get("title"), "What I Did On My Summer Vacation")
        self.assertEqual(inferred.get("category"), "demo")
        self.assertTrue(str(inferred.get("intent") or "").lower().startswith("create an explainer video"))

    def test_contract_infers_category_from_natural_phrase(self):
        registry = DraftIntakeContractRegistry(category_options_provider=lambda: [{"slug": "demo", "name": "Demo"}])
        contract = registry.get("ArticleDraft")
        self.assertIsNotNone(contract)
        assert contract is not None
        inferred = contract.infer_fields(
            message='Create an explainer video about Xyn governance ledger for telecom engineers. The title is "What I Did On My Summer Vacation". Create it in the demo category.',
            inferred_fields={},
        )
        self.assertEqual(inferred.get("category"), "demo")

    def test_contract_infers_title_from_title_it_phrase(self):
        registry = DraftIntakeContractRegistry(category_options_provider=lambda: [{"slug": "demo", "name": "Demo"}])
        contract = registry.get("ArticleDraft")
        self.assertIsNotNone(contract)
        assert contract is not None
        inferred = contract.infer_fields(
            message=(
                "Create an explainer video about turtles. Make it scientific. "
                "Title it 'Adult Non-mutant Tai-Chi Turtles' and put it in the demo category."
            ),
            inferred_fields={},
        )
        self.assertEqual(inferred.get("title"), "Adult Non-mutant Tai-Chi Turtles")

    def test_context_pack_contract_defaults(self):
        registry = DraftIntakeContractRegistry(category_options_provider=lambda: [{"slug": "demo", "name": "Demo"}])
        contract = registry.get("ContextPack")
        self.assertIsNotNone(contract)
        assert contract is not None
        merged = contract.merge_defaults({"title": "Pack", "content": "{}"})
        self.assertEqual(merged.get("format"), "json")
        self.assertEqual(contract.missing_fields(merged), [])

    def test_engine_rejects_unknown_action_type(self):
        registry = DraftIntakeContractRegistry(category_options_provider=lambda: [{"slug": "web", "name": "Web"}])
        engine = IntentResolutionEngine(
            proposal_provider=_FakeProvider(
                {
                    "action_type": "DoSomethingElse",
                    "artifact_type": "ArticleDraft",
                    "inferred_fields": {},
                    "confidence": 0.9,
                }
            ),
            contracts=registry,
        )
        result, _ = engine.resolve(message="hello", context=ResolutionContext(artifact=None))
        self.assertEqual(result["status"], "UnsupportedIntent")

    def test_resolve_create_returns_missing_fields_when_incomplete(self):
        with patch(
            "xyn_orchestrator.intent_engine.proposal_provider.LlmIntentProposalProvider.propose",
            return_value={
                "action_type": "CreateDraft",
                "artifact_type": "ArticleDraft",
                "inferred_fields": {"title": "Draft title"},
                "confidence": 0.93,
                "_model": "fake",
                "_context_pack_slug": "xyn-console-default",
                "_context_pack_version": "1.0.0",
                "_context_pack_hash": "abc123",
            },
        ):
            response = self.client.post(
                "/xyn/api/xyn/intent/resolve",
                data=json.dumps({"message": "create draft"}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertEqual(payload["status"], "MissingFields")
        self.assertTrue(any(item["field"] == "category" for item in payload.get("missing_fields", [])))
        self.assertEqual((payload.get("audit") or {}).get("context_pack_slug"), "xyn-console-default")

    def test_resolve_heuristic_create_fallback_for_low_confidence(self):
        with patch(
            "xyn_orchestrator.intent_engine.proposal_provider.LlmIntentProposalProvider.propose",
            return_value={
                "action_type": "ValidateDraft",
                "artifact_type": "ArticleDraft",
                "inferred_fields": {},
                "confidence": 0.01,
                "_model": "fake",
            },
        ):
            response = self.client.post(
                "/xyn/api/xyn/intent/resolve",
                data=json.dumps({"message": "Create an explainer video about governance ledger for telecom engineers."}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertEqual(payload["status"], "MissingFields")
        self.assertEqual(payload["action_type"], "CreateDraft")
        self.assertEqual(payload["artifact_type"], "ArticleDraft")
        self.assertNotEqual(payload["summary"], "Intent is ambiguous; provide clearer draft instructions.")

    def test_resolve_low_confidence_with_explicit_fields_returns_draft_ready(self):
        with patch(
            "xyn_orchestrator.intent_engine.proposal_provider.LlmIntentProposalProvider.propose",
            return_value={
                "action_type": "ValidateDraft",
                "artifact_type": "ArticleDraft",
                "inferred_fields": {},
                "confidence": 0.1,
                "_model": "fake",
            },
        ):
            response = self.client.post(
                "/xyn/api/xyn/intent/resolve",
                data=json.dumps(
                    {
                        "message": 'Intent: Create an explainer video about Xyn governance ledger for telecom engineers. title: "What I Did On My Summer Vacation". category: demo'
                    }
                ),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertEqual(payload["status"], "DraftReady")
        self.assertEqual((payload.get("draft_payload") or {}).get("category"), "demo")
        self.assertEqual((payload.get("draft_payload") or {}).get("title"), "What I Did On My Summer Vacation")

    def test_resolve_returns_explicit_error_when_console_context_pack_missing(self):
        with patch(
            "xyn_orchestrator.intent_engine.proposal_provider.LlmIntentProposalProvider.propose",
            side_effect=IntentContextPackMissingError("xyn-console-default"),
        ):
            response = self.client.post(
                "/xyn/api/xyn/intent/resolve",
                data=json.dumps({"message": "create an explainer video"}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("status"), "UnsupportedIntent")
        self.assertIn("context pack missing", str(payload.get("summary") or "").lower())

    def test_resolve_build_new_app_prompt_routes_to_app_intent_draft(self):
        prompt = (
            "Build a new app. It is a network inventory application for managing devices, interfaces, "
            "IP addresses, and locations per workspace. Start with devices and locations only. "
            "Add one chart that shows devices by status."
        )
        response = self.client.post(
            "/xyn/api/xyn/intent/resolve",
            data=json.dumps({"message": prompt, "context": {"workspace_id": str(self.workspace.id)}}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("status"), "DraftReady")
        self.assertEqual(payload.get("action_type"), "CreateDraft")
        self.assertEqual(payload.get("artifact_type"), "Workspace")
        draft_payload = payload.get("draft_payload") or {}
        self.assertEqual(draft_payload.get("__operation"), "create_app_intent_draft")
        initial_intent = draft_payload.get("initial_intent") or {}
        self.assertEqual(initial_intent.get("app_kind"), "network_inventory")
        self.assertIn("devices", initial_intent.get("requested_entities") or [])
        self.assertIn("locations", initial_intent.get("requested_entities") or [])
        self.assertEqual(initial_intent.get("phase_1_scope"), ["devices", "locations"])
        self.assertIn("devices_by_status_chart", initial_intent.get("requested_visuals") or [])
        self.assertTrue(initial_intent.get("workspace_scoped"))
        self.assertNotEqual(payload.get("summary"), "Intent is ambiguous; provide clearer draft instructions.")

    def test_resolve_follow_up_prompt_targets_installed_generated_app(self):
        application_type, _ = ArtifactType.objects.get_or_create(slug="application", defaults={"name": "Application"})
        generated_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=application_type,
            title="Network Inventory",
            slug="app.net-inventory",
            status="published",
            visibility="team",
            artifact_state="canonical",
            package_version="0.0.1-dev",
            scope_json={
                "imported_manifest": {
                    "artifact": {
                        "type": "application",
                        "slug": "app.net-inventory",
                        "version": "0.0.1-dev",
                        "generated": True,
                        "title": "Network Inventory",
                        "capability": {
                            "visibility": "capabilities",
                            "label": "Network Inventory",
                            "category": "application",
                        },
                    },
                    "content": {
                        "app_spec": {
                            "schema_version": "xyn.appspec.v0",
                            "app_slug": "net-inventory",
                            "title": "Network Inventory",
                            "workspace_id": str(self.workspace.id),
                            "entities": ["devices", "locations"],
                            "phase_1_scope": ["devices", "locations"],
                            "requested_visuals": ["devices_by_status_chart"],
                            "reports": ["devices_by_status"],
                            "services": [
                                {"name": "net-inventory-api", "image": "public.ecr.aws/i0h0h0n4/xyn/artifacts/net-inventory-api:dev"},
                                {"name": "net-inventory-db", "image": "postgres:16-alpine"},
                            ],
                            "source_prompt": "Build a network inventory app.",
                        }
                    },
                    "runtime": {
                        "runtime_config": {
                            "app_slug": "net-inventory",
                            "artifact_slug": "app.net-inventory",
                            "artifact_version": "0.0.1-dev",
                            "app_spec_artifact_id": "appspec-123",
                        }
                    },
                }
            },
        )
        WorkspaceArtifactBinding.objects.create(workspace=self.workspace, artifact=generated_artifact)
        WorkspaceAppInstance.objects.create(
            workspace=self.workspace,
            artifact=generated_artifact,
            app_slug="net-inventory",
            fqdn="net-inventory.localtest.me",
            status="active",
            dns_config_json={
                "runtime_target": {
                    "runtime_owner": "sibling",
                    "runtime_base_url": "http://xyn-sibling-net-inventory-api:8080",
                    "app_slug": "net-inventory",
                    "installed_artifact_slug": "app.net-inventory",
                }
            },
        )

        prompt = "Add interfaces to devices and include a chart showing interfaces by status."
        response = self.client.post(
            "/xyn/api/xyn/intent/resolve",
            data=json.dumps({"message": prompt, "context": {"workspace_id": str(self.workspace.id)}}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("status"), "DraftReady")
        draft_payload = payload.get("draft_payload") or {}
        self.assertEqual(draft_payload.get("__operation"), "evolve_app_intent_draft")
        revision_anchor = draft_payload.get("revision_anchor") or {}
        self.assertEqual(revision_anchor.get("artifact_slug"), "app.net-inventory")
        self.assertEqual(revision_anchor.get("app_slug"), "net-inventory")
        initial_intent = draft_payload.get("initial_intent") or {}
        self.assertIn("interfaces", initial_intent.get("requested_entities") or [])
        self.assertIn("interfaces_by_status_chart", initial_intent.get("requested_visuals") or [])
        self.assertEqual(initial_intent.get("evolution_mode"), "modify_installed_generated_app")
        current_app_spec = draft_payload.get("current_app_spec") or {}
        self.assertIn("devices", current_app_spec.get("entities") or [])
        self.assertIn("locations", current_app_spec.get("entities") or [])
        self.assertIn("installed generated app", str(payload.get("summary") or "").lower())

    @patch("xyn_orchestrator.xyn_api.requests.request")
    def test_apply_create_app_intent_draft_submits_to_seed_and_returns_ids(self, request_mock):
        class _FakeResponse:
            def __init__(self, status_code: int, payload: dict):
                self.status_code = status_code
                self._payload = payload
                self.content = json.dumps(payload).encode("utf-8")
                self.text = json.dumps(payload)

            def json(self):
                return self._payload

        draft_id = "49d67e63-28d1-4d7e-a4c4-ec18f0563767"
        job_id = "d2369c24-bd2d-43ee-a0a6-ec5cf8ecbdf1"
        request_mock.side_effect = [
            _FakeResponse(
                200,
                [
                    {
                        "id": "a50816b5-16d9-45f0-a4d4-31483bbdb307",
                        "slug": str(self.workspace.slug),
                        "title": str(self.workspace.name),
                    }
                ],
            ),
            _FakeResponse(
                201,
                {
                    "id": draft_id,
                    "workspace_id": str(self.workspace.id),
                    "type": "app_intent",
                    "title": "Network Inventory App",
                    "content_json": {},
                    "status": "ready",
                    "created_by": "intent-admin@example.com",
                },
            ),
            _FakeResponse(
                200,
                {
                    "draft": {"id": draft_id},
                    "job_id": job_id,
                    "job_status": "queued",
                },
            ),
        ]

        response = self.client.post(
            "/xyn/api/xyn/intent/apply",
            data=json.dumps(
                {
                    "action_type": "CreateDraft",
                    "artifact_type": "Workspace",
                    "payload": {
                        "__operation": "create_app_intent_draft",
                        "workspace_id": str(self.workspace.id),
                        "title": "Network Inventory App",
                        "raw_prompt": "Build a new app for devices and locations by workspace.",
                        "initial_intent": {
                            "app_kind": "network_inventory",
                            "requested_entities": ["devices", "locations"],
                            "phase_1_scope": ["devices", "locations"],
                            "requested_visuals": ["devices_by_status_chart"],
                            "workspace_scoped": True,
                        },
                    },
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("status"), "DraftReady")
        self.assertEqual((payload.get("result") or {}).get("draft_id"), draft_id)
        self.assertEqual((payload.get("result") or {}).get("job_id"), job_id)
        next_actions = payload.get("next_actions") or []
        self.assertEqual((next_actions[0] or {}).get("label"), "Track build")
        self.assertEqual((next_actions[0] or {}).get("panel_key"), "draft_detail")
        self.assertEqual(request_mock.call_count, 3)
        second_call = request_mock.call_args_list[1]
        self.assertEqual(second_call.kwargs.get("method"), "POST")
        self.assertIn("/api/v1/drafts", str(second_call.kwargs.get("url") or ""))

    @patch("xyn_orchestrator.xyn_api.requests.request")
    def test_apply_evolved_app_intent_draft_posts_revision_anchor_to_seed(self, request_mock):
        class _FakeResponse:
            def __init__(self, status_code: int, payload: dict):
                self.status_code = status_code
                self._payload = payload
                self.content = json.dumps(payload).encode("utf-8")
                self.text = json.dumps(payload)

            def json(self):
                return self._payload

        draft_id = "1b5bf3f6-5588-4cae-a79e-3f5d2fb1cf78"
        job_id = "f4fcbfb8-2d66-4675-8766-b61af7948ddb"
        request_mock.side_effect = [
            _FakeResponse(
                200,
                [
                    {
                        "id": "a50816b5-16d9-45f0-a4d4-31483bbdb307",
                        "slug": str(self.workspace.slug),
                        "title": str(self.workspace.name),
                    }
                ],
            ),
            _FakeResponse(
                201,
                {
                    "id": draft_id,
                    "workspace_id": str(self.workspace.id),
                    "type": "app_intent",
                    "title": "Network Inventory Revision",
                    "content_json": {},
                    "status": "ready",
                    "created_by": "intent-admin@example.com",
                },
            ),
            _FakeResponse(
                200,
                {
                    "draft": {"id": draft_id},
                    "job_id": job_id,
                    "job_status": "queued",
                },
            ),
        ]

        response = self.client.post(
            "/xyn/api/xyn/intent/apply",
            data=json.dumps(
                {
                    "action_type": "CreateDraft",
                    "artifact_type": "Workspace",
                    "payload": {
                        "__operation": "evolve_app_intent_draft",
                        "workspace_id": str(self.workspace.id),
                        "title": "Network Inventory Revision",
                        "raw_prompt": "Add interfaces to devices and include a chart showing interfaces by status.",
                        "initial_intent": {
                            "app_kind": "network_inventory",
                            "requested_entities": ["interfaces"],
                            "requested_visuals": ["interfaces_by_status_chart"],
                            "workspace_scoped": True,
                            "evolution_mode": "modify_installed_generated_app",
                        },
                        "revision_anchor": {
                            "artifact_slug": "app.net-inventory",
                            "app_slug": "net-inventory",
                            "runtime_instance_id": "runtime-123",
                        },
                        "current_app_summary": {
                            "app_slug": "net-inventory",
                            "entities": ["devices", "locations"],
                        },
                        "current_app_spec": {
                            "app_slug": "net-inventory",
                            "entities": ["devices", "locations"],
                            "reports": ["devices_by_status"],
                        },
                        "latest_appspec_ref": {"artifact_id": "appspec-123"},
                    },
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("status"), "DraftReady")
        self.assertEqual((payload.get("result") or {}).get("draft_id"), draft_id)
        self.assertEqual((payload.get("result") or {}).get("job_id"), job_id)
        draft_create_call = request_mock.call_args_list[1]
        body = draft_create_call.kwargs.get("json") or {}
        content_json = body.get("content_json") or {}
        self.assertEqual((content_json.get("revision_anchor") or {}).get("artifact_slug"), "app.net-inventory")
        self.assertEqual((content_json.get("initial_intent") or {}).get("evolution_mode"), "modify_installed_generated_app")
        self.assertEqual((content_json.get("latest_appspec_ref") or {}).get("artifact_id"), "appspec-123")

    def test_prompt_submission_activity_is_visible(self):
        prompt = "Build a new app for network inventory with devices and locations."
        response = self.client.post(
            "/xyn/api/xyn/intent/resolve",
            data=json.dumps({"message": prompt, "context": {"workspace_id": str(self.workspace.id)}}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content.decode())
        self.assertTrue(AuditLog.objects.filter(message="prompt_submission").exists())

        activity = self.client.get(f"/xyn/api/ai/activity?workspace_id={self.workspace.id}")
        self.assertEqual(activity.status_code, 200, activity.content.decode())
        items = activity.json().get("items") or []
        prompt_item = next((item for item in items if item.get("event_type") == "prompt_submission"), None)
        self.assertIsNotNone(prompt_item)

    @patch("xyn_orchestrator.xyn_api.requests.request")
    def test_app_builder_execution_notes_proxy_returns_explicitly_matched_note(self, request_mock):
        class _FakeResponse:
            def __init__(self, status_code: int, payload):
                self.status_code = status_code
                self._payload = payload
                self.content = json.dumps(payload).encode("utf-8")
                self.text = json.dumps(payload)
                self.headers = {"content-type": "application/json"}

            def json(self):
                return self._payload

        note_id = "c105190a-92f4-49fc-b81d-43723004e18b"
        artifact_id = "40b9dd27-2195-4d10-b9e1-6f633c8f7d8d"
        job_id = "b8cfcdcb-4c25-4688-b703-1f4a86d6d17a"
        request_mock.side_effect = [
            _FakeResponse(
                200,
                {
                    "items": [
                        {
                            "id": note_id,
                            "workspace_id": str(self.workspace.id),
                            "name": f"execution-note.{note_id}",
                            "kind": "execution-note",
                            "metadata": {
                                "prompt_or_request": "Build a network inventory app.",
                                "related_artifact_ids": [artifact_id],
                                "status": "completed",
                                "job_id": job_id,
                                "app_spec_artifact_id": artifact_id,
                            },
                            "created_at": "2026-03-07T10:00:00+00:00",
                        }
                    ]
                },
            ),
            _FakeResponse(
                200,
                {
                    "id": note_id,
                    "timestamp": "2026-03-07T10:00:00+00:00",
                    "workspace_id": str(self.workspace.id),
                    "related_artifact_ids": [artifact_id],
                    "prompt_or_request": "Build a network inventory app.",
                    "findings": ["Draft reached non-trivial generation path."],
                    "root_cause": "AppSpec generation must be auditable.",
                    "proposed_fix": "Persist AppSpec and carry execution note through the pipeline.",
                    "implementation_summary": "Generated AppSpec and linked execution note.",
                    "validation_summary": ["AppSpec validated.", "Deployment started."],
                    "debt_recorded": [],
                    "status": "completed",
                    "updated_at": "2026-03-07T10:05:00+00:00",
                },
            ),
        ]

        response = self.client.get(
            f"/xyn/api/app-builder/execution-notes?workspace_id={self.workspace.id}&related_artifact_id={artifact_id}&job_id={job_id}"
        )
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["id"], note_id)
        self.assertEqual(payload[0]["match_reason"], "related_artifact_ids")
        self.assertEqual(payload[0]["prompt_or_request"], "Build a network inventory app.")
        self.assertIn("AppSpec validated.", payload[0]["validation_summary"])
        self.assertIn("Build a new app", str((prompt_item or {}).get("prompt") or ""))

    def test_apply_patch_rejects_unauthorized_fields(self):
        create_response = self.client.post(
            "/xyn/api/xyn/intent/apply",
            data=json.dumps(
                {
                    "action_type": "CreateDraft",
                    "artifact_type": "ArticleDraft",
                    "payload": {
                        "title": "Patch Target",
                        "category": "web",
                        "format": "article",
                    },
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(create_response.status_code, 200, create_response.content.decode())
        artifact_id = create_response.json().get("artifact_id")

        patch_response = self.client.post(
            "/xyn/api/xyn/intent/apply",
            data=json.dumps(
                {
                    "action_type": "ApplyPatch",
                    "artifact_type": "ArticleDraft",
                    "artifact_id": artifact_id,
                    "payload": {"evil_field": "value"},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(patch_response.status_code, 400)
        self.assertEqual(patch_response.json().get("status"), "ValidationError")

    def test_context_pack_apply_patch_validates_and_writes_ledger(self):
        pack = ContextPack.objects.create(
            name="xyn-console-default",
            purpose="any",
            scope="global",
            version="1.0.0",
            is_active=True,
            content_markdown='{"hello":"world"}',
            applies_to_json={"content_format": "json"},
        )
        artifact = ensure_context_pack_artifact(pack, owner_user=self.user)
        bad = self.client.post(
            "/xyn/api/xyn/intent/apply",
            data=json.dumps(
                {
                    "action_type": "ApplyPatch",
                    "artifact_type": "ContextPack",
                    "artifact_id": str(artifact.id),
                    "payload": {"content": "{invalid json}", "format": "json"},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(bad.status_code, 400, bad.content.decode())
        self.assertEqual(bad.json().get("status"), "ValidationError")

        ok = self.client.post(
            "/xyn/api/xyn/intent/apply",
            data=json.dumps(
                {
                    "action_type": "ApplyPatch",
                    "artifact_type": "ContextPack",
                    "artifact_id": str(artifact.id),
                    "payload": {"title": "xyn-console-default", "content": '{"hello":"xyn"}', "format": "json"},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(ok.status_code, 200, ok.content.decode())
        artifact.refresh_from_db()
        pack.refresh_from_db()
        self.assertEqual(pack.content_markdown, '{"hello":"xyn"}')
        self.assertTrue(LedgerEvent.objects.filter(artifact=artifact, action="contextpack.patched").exists())

    def test_resolve_context_pack_with_context(self):
        pack = ContextPack.objects.create(
            name="xyn-console-default",
            purpose="any",
            scope="global",
            version="1.0.0",
            is_active=True,
            content_markdown='{"hello":"world"}',
            applies_to_json={"content_format": "json"},
        )
        artifact = ensure_context_pack_artifact(pack, owner_user=self.user)
        with patch(
            "xyn_orchestrator.intent_engine.proposal_provider.LlmIntentProposalProvider.propose",
            return_value={
                "action_type": "ProposePatch",
                "artifact_type": "ContextPack",
                "inferred_fields": {"content": '{"hello":"patched"}', "format": "json"},
                "confidence": 0.95,
                "_model": "fake",
            },
        ):
            response = self.client.post(
                "/xyn/api/xyn/intent/resolve",
                data=json.dumps(
                    {
                        "message": "Update context pack content",
                        "context": {"artifact_id": str(artifact.id), "artifact_type": "ContextPack"},
                    }
                ),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("status"), "ProposedPatch")
        self.assertEqual(payload.get("artifact_type"), "ContextPack")

    def test_show_options_returns_categories_and_formats(self):
        options = self.client.get("/xyn/api/xyn/intent/options?artifact_type=ArticleDraft&field=format")
        self.assertEqual(options.status_code, 200)
        self.assertIn("explainer_video", options.json().get("options", []))

        categories = self.client.get("/xyn/api/xyn/intent/options?artifact_type=ArticleDraft&field=category")
        self.assertEqual(categories.status_code, 200)
        self.assertTrue(categories.json().get("options"))

    def test_create_and_patch_write_ledger_events(self):
        create_response = self.client.post(
            "/xyn/api/xyn/intent/apply",
            data=json.dumps(
                {
                    "action_type": "CreateDraft",
                    "artifact_type": "ArticleDraft",
                    "payload": {
                        "title": "Ledger Draft",
                        "category": "web",
                        "format": "article",
                        "summary": "initial",
                    },
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(create_response.status_code, 200, create_response.content.decode())
        artifact_id = create_response.json().get("artifact_id")
        artifact = Artifact.objects.get(id=artifact_id)

        self.assertTrue(LedgerEvent.objects.filter(artifact=artifact, action="draft.created").exists())

        patch_response = self.client.post(
            "/xyn/api/xyn/intent/apply",
            data=json.dumps(
                {
                    "action_type": "ApplyPatch",
                    "artifact_type": "ArticleDraft",
                    "artifact_id": artifact_id,
                    "payload": {"summary": "updated summary"},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(patch_response.status_code, 200, patch_response.content.decode())
        self.assertTrue(LedgerEvent.objects.filter(artifact=artifact, action="draft.patched").exists())

    def test_resolve_and_apply_integration(self):
        with patch(
            "xyn_orchestrator.intent_engine.proposal_provider.LlmIntentProposalProvider.propose",
            return_value={
                "action_type": "CreateDraft",
                "artifact_type": "ArticleDraft",
                "inferred_fields": {
                    "title": "Intent Generated Draft",
                    "category": "web",
                    "format": "explainer_video",
                    "intent": "Explain Xyn governance quickly",
                    "duration": "5m",
                },
                "confidence": 0.95,
                "_model": "fake",
            },
        ):
            resolve_response = self.client.post(
                "/xyn/api/xyn/intent/resolve",
                data=json.dumps({"message": "Create an explainer video draft"}),
                content_type="application/json",
            )
        self.assertEqual(resolve_response.status_code, 200, resolve_response.content.decode())
        resolve_payload = resolve_response.json()
        self.assertEqual(resolve_payload.get("status"), "DraftReady")
        self.assertTrue(resolve_payload.get("draft_payload"))

        apply_response = self.client.post(
            "/xyn/api/xyn/intent/apply",
            data=json.dumps(
                {
                    "action_type": "CreateDraft",
                    "artifact_type": "ArticleDraft",
                    "payload": resolve_payload.get("draft_payload") or {},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(apply_response.status_code, 200, apply_response.content.decode())
        created = Artifact.objects.get(id=apply_response.json().get("artifact_id"))
        self.assertEqual(created.format, "video_explainer")
        self.assertEqual((created.video_spec_json or {}).get("intent"), "Explain Xyn governance quickly")
        scenes = (created.video_spec_json or {}).get("scenes") if isinstance(created.video_spec_json, dict) else []
        self.assertTrue(isinstance(scenes, list) and len(scenes) >= 3)
        latest = created.revisions.order_by("-revision_number").first()
        content = latest.content_json if latest and isinstance(latest.content_json, dict) else {}
        self.assertTrue(str(content.get("summary") or "").strip())
        self.assertTrue(str(content.get("body_markdown") or "").strip())
        serialized_scenes = json.dumps(scenes).lower()
        self.assertNotIn("/app/artifacts", serialized_scenes)
        self.assertNotIn("validation", serialized_scenes)
        self.assertNotIn("content_hash", serialized_scenes)

    def test_create_explainer_uses_structured_topic_and_auto_binds_default_pack(self):
        ArticleCategory.objects.get_or_create(slug="demo", defaults={"name": "Demo", "enabled": True})
        default_pack, _ = ContextPack.objects.get_or_create(
            name="explainer-video-default",
            purpose="video_explainer",
            scope="global",
            version="1.0.0",
            namespace="",
            project_key="",
            defaults={
                "is_active": True,
                "is_default": False,
                "content_markdown": "Ground scenes in factual biology.",
            },
        )
        if not default_pack.is_active:
            default_pack.is_active = True
            default_pack.save(update_fields=["is_active", "updated_at"])
        response = self.client.post(
            "/xyn/api/xyn/intent/apply",
            data=json.dumps(
                {
                    "action_type": "CreateDraft",
                    "artifact_type": "ArticleDraft",
                    "payload": {
                        "title": "The Intrigue of Salamanders",
                        "category": "demo",
                        "format": "explainer_video",
                        "intent": (
                            "Create an explainer video about salamanders. Ground it in actual biology. "
                            "The title is 'The Intrigue of Salamanders'. Create it in the demo category."
                        ),
                    },
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content.decode())
        artifact = Artifact.objects.get(id=response.json().get("artifact_id"))
        self.assertEqual(str(artifact.video_context_pack_id), str(default_pack.id))
        latest = artifact.revisions.order_by("-revision_number").first()
        content = latest.content_json if latest and isinstance(latest.content_json, dict) else {}
        summary = str(content.get("summary") or "").lower()
        body = str(content.get("body_markdown") or "").lower()
        self.assertIn("salamander", summary)
        self.assertIn("salamander", body)
        self.assertNotIn("create an explainer video", summary)
        self.assertNotIn("create an explainer video", body)
        scenes = (artifact.video_spec_json or {}).get("scenes") if isinstance(artifact.video_spec_json, dict) else []
        self.assertTrue(isinstance(scenes, list) and len(scenes) >= 3)
        scene_blob = json.dumps(scenes).lower()
        self.assertIn("regener", scene_blob)
        self.assertIn("amphib", scene_blob)
        self.assertNotIn("hook / premise", scene_blob)
        self.assertNotIn("setup / context", scene_blob)

    def test_deploy_ems_for_customer_creates_child_workspace_and_binding(self):
        module_type, _ = ArtifactType.objects.get_or_create(slug="module", defaults={"name": "Module"})
        ems_artifact, _ = Artifact.objects.get_or_create(
            workspace=self.workspace,
            slug="ems",
            defaults={
                "type": module_type,
                "title": "EMS",
                "status": "published",
                "visibility": "team",
            },
        )
        resolve_response = self.client.post(
            "/xyn/api/xyn/intent/resolve",
            data=json.dumps(
                {
                    "message": "deploy EMS for customer Acme Grid",
                    "context": {"workspace_id": str(self.workspace.id)},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(resolve_response.status_code, 200, resolve_response.content.decode())
        resolve_payload = resolve_response.json()
        self.assertEqual(resolve_payload.get("status"), "DraftReady")
        self.assertEqual(resolve_payload.get("artifact_type"), "Workspace")
        draft_payload = resolve_payload.get("draft_payload") or {}
        self.assertEqual(draft_payload.get("__operation"), "deploy_ems_customer")

        apply_response = self.client.post(
            "/xyn/api/xyn/intent/apply",
            data=json.dumps(
                {
                    "action_type": "CreateDraft",
                    "artifact_type": "Workspace",
                    "payload": draft_payload,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(apply_response.status_code, 200, apply_response.content.decode())
        apply_payload = apply_response.json()
        self.assertEqual(apply_payload.get("status"), "DraftReady")
        open_ems = next((item for item in apply_payload.get("next_actions", []) if item.get("action") == "OpenPath"), None)
        self.assertIsNotNone(open_ems)
        open_path = str((open_ems or {}).get("path") or "")
        self.assertIn("/apps/ems", open_path)
        child_workspace = Workspace.objects.exclude(id=self.workspace.id).order_by("-created_at").first()
        self.assertIsNotNone(child_workspace)
        assert child_workspace is not None
        self.assertEqual(child_workspace.parent_workspace_id, self.workspace.id)
        self.assertEqual(child_workspace.lifecycle_stage, "prospect")
        self.assertEqual(child_workspace.kind, "customer")
        self.assertTrue(WorkspaceArtifactBinding.objects.filter(workspace=child_workspace, artifact=ems_artifact).exists())

    def test_create_ems_instance_command_is_idempotent(self):
        module_type, _ = ArtifactType.objects.get_or_create(slug="module", defaults={"name": "Module"})
        ems_artifact, _ = Artifact.objects.get_or_create(
            workspace=self.workspace,
            slug="ems",
            defaults={
                "type": module_type,
                "title": "EMS",
                "status": "published",
                "visibility": "team",
            },
        )
        message = "Create a new instance of EMS for customer ACME Co. FQDN should be ems.xyence.io"

        resolve_response = self.client.post(
            "/xyn/api/xyn/intent/resolve",
            data=json.dumps({"message": message, "context": {"workspace_id": str(self.workspace.id)}}),
            content_type="application/json",
        )
        self.assertEqual(resolve_response.status_code, 200, resolve_response.content.decode())
        draft_payload = resolve_response.json().get("draft_payload") or {}
        self.assertEqual(draft_payload.get("__operation"), "create_ems_instance")
        self.assertEqual(draft_payload.get("fqdn"), "ems.xyence.io")

        first_apply = self.client.post(
            "/xyn/api/xyn/intent/apply",
            data=json.dumps(
                {
                    "action_type": "CreateDraft",
                    "artifact_type": "Workspace",
                    "payload": draft_payload,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(first_apply.status_code, 200, first_apply.content.decode())
        first_payload = first_apply.json()
        self.assertEqual(first_payload.get("status"), "DraftReady")
        result = first_payload.get("result") or {}
        workspace_id = str((result.get("workspace") or {}).get("id") or "")
        instance_id = str((result.get("instance") or {}).get("id") or "")
        self.assertTrue(workspace_id)
        self.assertTrue(instance_id)
        self.assertEqual((result.get("instance") or {}).get("deployment_target"), "local")
        self.assertEqual((result.get("instance") or {}).get("fqdn"), "ems.xyence.io")
        self.assertIn(f"/w/{workspace_id}/apps/ems", str(result.get("app_url") or ""))

        second_apply = self.client.post(
            "/xyn/api/xyn/intent/apply",
            data=json.dumps(
                {
                    "action_type": "CreateDraft",
                    "artifact_type": "Workspace",
                    "payload": draft_payload,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(second_apply.status_code, 200, second_apply.content.decode())
        second_payload = second_apply.json()
        second_result = second_payload.get("result") or {}
        self.assertEqual(str((second_result.get("workspace") or {}).get("id") or ""), workspace_id)
        self.assertEqual(str((second_result.get("instance") or {}).get("id") or ""), instance_id)
        self.assertEqual(
            WorkspaceAppInstance.objects.filter(workspace_id=workspace_id, app_slug="ems", fqdn="ems.xyence.io").count(),
            1,
        )
        self.assertEqual(WorkspaceArtifactBinding.objects.filter(workspace_id=workspace_id, artifact=ems_artifact).count(), 1)

    def test_install_xyn_instance_command_creates_runtime_run_and_is_idempotent(self):
        module_type, _ = ArtifactType.objects.get_or_create(slug="module", defaults={"name": "Module"})
        Artifact.objects.get_or_create(
            workspace=self.workspace,
            slug="xyn-api",
            defaults={
                "type": module_type,
                "title": "xyn-api",
                "status": "published",
                "visibility": "team",
            },
        )
        Artifact.objects.get_or_create(
            workspace=self.workspace,
            slug="xyn-ui",
            defaults={
                "type": module_type,
                "title": "xyn-ui",
                "status": "published",
                "visibility": "team",
            },
        )
        message = "install xyn instance for ACME Co fqdn ems.xyence.io"
        resolve_response = self.client.post(
            "/xyn/api/xyn/intent/resolve",
            data=json.dumps({"message": message, "context": {"workspace_id": str(self.workspace.id)}}),
            content_type="application/json",
        )
        self.assertEqual(resolve_response.status_code, 200, resolve_response.content.decode())
        draft_payload = resolve_response.json().get("draft_payload") or {}
        self.assertEqual(draft_payload.get("__operation"), "deploy_release_spec")
        self.assertEqual(draft_payload.get("fqdn"), "ems.xyence.io")
        draft_payload["dry_run"] = True

        first_apply = self.client.post(
            "/xyn/api/xyn/intent/apply",
            data=json.dumps(
                {
                    "action_type": "CreateDraft",
                    "artifact_type": "Workspace",
                    "payload": draft_payload,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(first_apply.status_code, 200, first_apply.content.decode())
        first_payload = first_apply.json()
        self.assertEqual(first_payload.get("status"), "DraftReady")
        first_result = first_payload.get("result") or {}
        workspace_id = str((first_result.get("workspace") or {}).get("id") or "")
        instance_id = str((first_result.get("instance") or {}).get("id") or "")
        run_id = str((first_result.get("run") or {}).get("id") or "")
        self.assertTrue(workspace_id)
        self.assertTrue(instance_id)
        self.assertTrue(run_id)
        self.assertIn("https://ems.xyence.io", str(first_result.get("ui_url") or ""))

        panel_actions = [item for item in first_payload.get("next_actions", []) if item.get("action") == "OpenPanel"]
        self.assertTrue(panel_actions)
        self.assertTrue(any(str(item.get("panel_key") or "") in {"run_detail", "artifact_detail"} for item in panel_actions))

        second_apply = self.client.post(
            "/xyn/api/xyn/intent/apply",
            data=json.dumps(
                {
                    "action_type": "CreateDraft",
                    "artifact_type": "Workspace",
                    "payload": draft_payload,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(second_apply.status_code, 200, second_apply.content.decode())
        second_result = second_apply.json().get("result") or {}
        self.assertEqual(str((second_result.get("workspace") or {}).get("id") or ""), workspace_id)
        self.assertEqual(str((second_result.get("instance") or {}).get("id") or ""), instance_id)
        self.assertEqual(
            WorkspaceAppInstance.objects.filter(workspace_id=workspace_id, app_slug="xyn-runtime", fqdn="ems.xyence.io").count(),
            1,
        )

    def test_open_ems_panel_command_returns_panel_action(self):
        resolve_response = self.client.post(
            "/xyn/api/xyn/intent/resolve",
            data=json.dumps(
                {
                    "message": "Show registrations in the past 24 hours",
                    "context": {"workspace_id": str(self.workspace.id)},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(resolve_response.status_code, 200, resolve_response.content.decode())
        draft_payload = resolve_response.json().get("draft_payload") or {}
        self.assertEqual(draft_payload.get("__operation"), "open_ems_panel")
        self.assertEqual(draft_payload.get("panel_key"), "ems_registrations_time")
        self.assertEqual((draft_payload.get("params") or {}).get("hours"), 24)

        apply_response = self.client.post(
            "/xyn/api/xyn/intent/apply",
            data=json.dumps(
                {
                    "action_type": "CreateDraft",
                    "artifact_type": "Workspace",
                    "payload": draft_payload,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(apply_response.status_code, 200, apply_response.content.decode())
        payload = apply_response.json()
        self.assertEqual(payload.get("status"), "DraftReady")
        panel_action = next((row for row in payload.get("next_actions", []) if row.get("action") == "OpenPanel"), None)
        self.assertIsNotNone(panel_action)
        self.assertEqual((panel_action or {}).get("panel_key"), "ems_registrations_time")

    def test_artifact_panel_commands_return_open_panel_actions(self):
        module_type, _ = ArtifactType.objects.get_or_create(slug="module", defaults={"name": "Module"})
        Artifact.objects.get_or_create(
            workspace=self.workspace,
            type=module_type,
            slug="core.authn-jwt",
            defaults={
                "title": "core.authn-jwt",
                "status": "published",
                "visibility": "team",
            },
        )

        resolve_response = self.client.post(
            "/xyn/api/xyn/intent/resolve",
            data=json.dumps({"message": "list core artifacts"}),
            content_type="application/json",
        )
        self.assertEqual(resolve_response.status_code, 200, resolve_response.content.decode())
        draft_payload = resolve_response.json().get("draft_payload") or {}
        self.assertEqual(draft_payload.get("__operation"), "open_artifact_panel")
        self.assertEqual(draft_payload.get("panel_key"), "artifact_list")
        self.assertEqual((draft_payload.get("params") or {}).get("namespace"), "core")

        apply_response = self.client.post(
            "/xyn/api/xyn/intent/apply",
            data=json.dumps(
                {
                    "action_type": "CreateDraft",
                    "artifact_type": "Workspace",
                    "payload": draft_payload,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(apply_response.status_code, 200, apply_response.content.decode())
        panel_action = next((row for row in apply_response.json().get("next_actions", []) if row.get("action") == "OpenPanel"), None)
        self.assertIsNotNone(panel_action)
        self.assertEqual((panel_action or {}).get("panel_key"), "artifact_list")

        raw_resolve = self.client.post(
            "/xyn/api/xyn/intent/resolve",
            data=json.dumps({"message": "edit artifact core.authn-jwt raw"}),
            content_type="application/json",
        )
        self.assertEqual(raw_resolve.status_code, 200, raw_resolve.content.decode())
        raw_payload = raw_resolve.json().get("draft_payload") or {}
        self.assertEqual(raw_payload.get("panel_key"), "artifact_raw_json")
        self.assertEqual((raw_payload.get("params") or {}).get("slug"), "core.authn-jwt")

    def test_artifact_slug_endpoints_return_full_raw_json_and_files(self):
        module_type, _ = ArtifactType.objects.get_or_create(slug="module", defaults={"name": "Module"})
        artifact, _ = Artifact.objects.get_or_create(
            workspace=self.workspace,
            type=module_type,
            slug="core.authn-jwt",
            defaults={
                "title": "core.authn-jwt",
                "status": "published",
                "visibility": "team",
                "scope_json": {"manifest_ref": "registry/modules/authn-jwt.artifact.manifest.json"},
            },
        )

        detail = self.client.get("/xyn/api/artifacts/slug/core.authn-jwt")
        self.assertEqual(detail.status_code, 200, detail.content.decode())
        body = detail.json()
        self.assertEqual((body.get("artifact") or {}).get("id"), str(artifact.id))
        self.assertIn("manifest_summary", body)
        self.assertIn("raw_artifact_json", body)
        self.assertIn("files", body)
        self.assertTrue(isinstance(body.get("files"), list))
        self.assertGreaterEqual(len(body.get("files") or []), 1)

        files = self.client.get("/xyn/api/artifacts/slug/core.authn-jwt/files")
        self.assertEqual(files.status_code, 200, files.content.decode())
        files_payload = files.json()
        self.assertEqual(((files_payload.get("artifact") or {}).get("slug")), "core.authn-jwt")
        first = (files_payload.get("files") or [{}])[0]
        self.assertIn("path", first)
        self.assertIn("size_bytes", first)
        self.assertIn("sha256", first)
