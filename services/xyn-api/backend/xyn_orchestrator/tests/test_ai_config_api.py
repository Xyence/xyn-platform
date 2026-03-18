import json
import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from xyn_orchestrator.models import AgentPurpose, AuditLog, ModelConfig, ModelProvider, RoleBinding, UserIdentity


class AiConfigApiTests(TestCase):
    def setUp(self):
        os.environ["XYN_CREDENTIALS_ENCRYPTION_KEY"] = "V2S8x7lAB2BaN8A-14EvhA-gF1kq4KOlnS2vPc9vulE="
        os.environ["XYN_OPENAI_API_KEY"] = "sk-test-openai-1234"
        user_model = get_user_model()
        self.staff = user_model.objects.create_user(username="staff-ai", password="pass", is_staff=True)
        self.client.force_login(self.staff)

        self.admin_identity = UserIdentity.objects.create(
            provider="oidc", issuer="https://issuer", subject="ai-admin", email="ai-admin@example.com"
        )
        self.user_identity = UserIdentity.objects.create(
            provider="oidc", issuer="https://issuer", subject="ai-user", email="ai-user@example.com"
        )
        RoleBinding.objects.create(user_identity=self.admin_identity, scope_kind="platform", role="platform_admin")
        RoleBinding.objects.create(user_identity=self.user_identity, scope_kind="platform", role="app_user")

    def _set_identity(self, identity: UserIdentity):
        session = self.client.session
        session["user_identity_id"] = str(identity.id)
        session.save()

    def _ensure_provider(self) -> ModelProvider:
        provider, _ = ModelProvider.objects.get_or_create(slug="openai", defaults={"name": "OpenAI", "enabled": True})
        return provider

    def test_non_admin_cannot_mutate_ai_credentials(self):
        self._set_identity(self.user_identity)
        response = self.client.post(
            "/xyn/api/ai/credentials",
            data=json.dumps({
                "provider": "openai",
                "name": "blocked",
                "auth_type": "env_ref",
                "env_var_name": "XYN_OPENAI_API_KEY",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_credential_model_agent_flow_and_purpose_filter(self):
        self._set_identity(self.admin_identity)
        self._ensure_provider()

        created_credential = self.client.post(
            "/xyn/api/ai/credentials",
            data=json.dumps(
                {
                    "provider": "openai",
                    "name": "openai-primary",
                    "auth_type": "api_key",
                    "api_key": "sk-live-abcdefghijklmn1234",
                    "is_default": True,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(created_credential.status_code, 200)
        payload = created_credential.json()["credential"]
        self.assertNotIn("api_key", payload)
        self.assertTrue(payload["secret"]["configured"])
        self.assertEqual(payload["secret"]["last4"], "1234")

        config_response = self.client.post(
            "/xyn/api/ai/model-configs",
            data=json.dumps(
                {
                    "provider": "openai",
                    "credential_id": payload["id"],
                    "model_name": "gpt-4o-mini",
                    "temperature": 0.2,
                    "max_tokens": 800,
                    "enabled": True,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(config_response.status_code, 200)
        model_config = config_response.json()["model_config"]

        agent_response = self.client.post(
            "/xyn/api/ai/agents",
            data=json.dumps(
                {
                    "slug": "docs-default",
                    "name": "Docs Default",
                    "model_config_id": model_config["id"],
                    "system_prompt_text": "You are docs.",
                    "purposes": ["documentation"],
                    "enabled": True,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(agent_response.status_code, 200)

        docs_agents = self.client.get("/xyn/api/ai/agents?purpose=documentation")
        self.assertEqual(docs_agents.status_code, 200)
        doc_slugs = [item["slug"] for item in docs_agents.json()["agents"]]
        self.assertIn("docs-default", doc_slugs)

        coding_agents = self.client.get("/xyn/api/ai/agents?purpose=coding")
        self.assertEqual(coding_agents.status_code, 200)
        coding_slugs = [item["slug"] for item in coding_agents.json()["agents"]]
        self.assertIn("default-assistant", coding_slugs)

        planning_purposes = self.client.get("/xyn/api/ai/purposes")
        self.assertEqual(planning_purposes.status_code, 200)
        planning_slugs = [item["slug"] for item in planning_purposes.json()["purposes"]]
        self.assertIn("planning", planning_slugs)

    def test_bootstrap_status_reports_default_planning_and_coding_agents(self):
        self._set_identity(self.admin_identity)
        with patch.dict(
            os.environ,
            {
                "XYN_AI_PROVIDER": "openai",
                "XYN_AI_MODEL": "gpt-5-mini",
                "XYN_OPENAI_API_KEY": "sk-default-openai",
                "XYN_AI_PLANNING_PROVIDER": "anthropic",
                "XYN_AI_PLANNING_MODEL": "claude-3-7-sonnet-latest",
                "XYN_AI_PLANNING_API_KEY": "sk-plan-anthropic",
                "XYN_AI_CODING_PROVIDER": "gemini",
                "XYN_AI_CODING_MODEL": "gemini-2.0-flash",
                "XYN_AI_CODING_API_KEY": "sk-code-gemini",
            },
            clear=False,
        ):
            response = self.client.get("/xyn/api/ai/bootstrap-status")
        self.assertEqual(response.status_code, 200)
        payload = response.json()["default_agent"]
        self.assertEqual(payload["default_agent_slug"], "default-assistant")
        self.assertEqual(payload["planning_agent_slug"], "planning-assistant")
        self.assertEqual(payload["coding_agent_slug"], "coding-assistant")

    def test_ai_routing_status_reports_current_purpose_resolution(self):
        self._set_identity(self.admin_identity)
        with patch.dict(
            os.environ,
            {
                "XYN_AI_PROVIDER": "openai",
                "XYN_AI_MODEL": "gpt-5-mini",
                "XYN_OPENAI_API_KEY": "sk-default-openai",
                "XYN_AI_PLANNING_PROVIDER": "anthropic",
                "XYN_AI_PLANNING_MODEL": "claude-3-7-sonnet-latest",
                "XYN_AI_PLANNING_API_KEY": "sk-plan-anthropic",
                "XYN_AI_CODING_PROVIDER": "gemini",
                "XYN_AI_CODING_MODEL": "gemini-2.0-flash",
                "XYN_AI_CODING_API_KEY": "sk-code-gemini",
            },
            clear=False,
        ):
            response = self.client.get("/xyn/api/ai/routing")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        routing = payload.get("routing") or []
        self.assertEqual(len(routing), 3)
        planning = next(item for item in routing if item.get("purpose") == "planning")
        coding = next(item for item in routing if item.get("purpose") == "coding")
        self.assertEqual(planning.get("resolved_agent_name"), "Xyn Planning Assistant")
        self.assertEqual(planning.get("resolution_source"), "explicit")
        self.assertEqual(coding.get("resolved_agent_name"), "Xyn Coding Assistant")
        self.assertEqual(coding.get("resolution_source"), "explicit")

    @patch("xyn_orchestrator.xyn_api.invoke_model")
    def test_ai_invoke_uses_agent_and_returns_content(self, invoke_mock):
        self._set_identity(self.admin_identity)
        provider = self._ensure_provider()
        model_config = ModelConfig.objects.create(provider=provider, model_name="gpt-4o-mini", enabled=True)

        create_agent = self.client.post(
            "/xyn/api/ai/agents",
            data=json.dumps(
                {
                    "slug": "docs-invoke",
                    "name": "Docs Invoke",
                    "model_config_id": str(model_config.id),
                    "system_prompt_text": "assist docs",
                    "purposes": ["documentation"],
                    "enabled": True,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(create_agent.status_code, 200)

        invoke_mock.return_value = {
            "content": "Generated markdown",
            "provider": "openai",
            "model": "gpt-4o-mini",
            "usage": {"input_tokens": 1},
            "effective_params": {"temperature": 0.2, "max_tokens": 800},
            "warnings": [],
        }

        response = self.client.post(
            "/xyn/api/ai/invoke",
            data=json.dumps(
                {
                    "agent_slug": "docs-invoke",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "metadata": {"feature": "articles_ai_assist"},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["content"], "Generated markdown")
        self.assertEqual(body["provider"], "openai")
        self.assertEqual(body["agent_slug"], "docs-invoke")
        self.assertEqual(body["agent_name"], "Docs Invoke")
        self.assertEqual(body["effective_params"]["temperature"], 0.2)
        self.assertEqual(body["warnings"], [])
        self.assertEqual((body.get("agent_resolution") or {}).get("resolved_agent_name"), "Docs Invoke")
        self.assertEqual((body.get("agent_resolution") or {}).get("resolution_source"), "explicit")
        audit = AuditLog.objects.filter(message="ai_invocation").order_by("-created_at").first()
        self.assertIsNotNone(audit)
        assert audit is not None
        audit_meta = audit.metadata_json if isinstance(audit.metadata_json, dict) else {}
        self.assertEqual((audit_meta.get("agent_resolution") or {}).get("resolved_agent_name"), "Docs Invoke")
        self.assertEqual((audit_meta.get("agent_resolution") or {}).get("resolution_source"), "explicit")
        invoke_kwargs = invoke_mock.call_args.kwargs
        resolved = invoke_kwargs["resolved_config"]
        self.assertIn("assist docs", str(resolved.get("system_prompt") or ""))
        self.assertIn("documentation", str(resolved.get("purpose") or ""))
        for message in invoke_kwargs["messages"]:
            self.assertNotEqual(message.get("role"), "system")

    @patch("xyn_orchestrator.xyn_api.invoke_model")
    def test_ai_invoke_ignores_client_system_message(self, invoke_mock):
        self._set_identity(self.admin_identity)
        provider = self._ensure_provider()
        model_config = ModelConfig.objects.create(provider=provider, model_name="gpt-4o-mini", enabled=True)
        create_agent = self.client.post(
            "/xyn/api/ai/agents",
            data=json.dumps(
                {
                    "slug": "docs-invoke-strip-system",
                    "name": "Docs Invoke Strip System",
                    "model_config_id": str(model_config.id),
                    "system_prompt_text": "assist docs",
                    "purposes": ["documentation"],
                    "enabled": True,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(create_agent.status_code, 200)
        AgentPurpose.objects.filter(slug="documentation").update(preamble="Doc preamble")
        invoke_mock.return_value = {"content": "ok", "provider": "openai", "model": "gpt-4o-mini", "usage": None}
        response = self.client.post(
            "/xyn/api/ai/invoke",
            data=json.dumps(
                {
                    "agent_slug": "docs-invoke-strip-system",
                    "messages": [
                        {"role": "system", "content": "attempted override"},
                        {"role": "user", "content": "Hello"},
                    ],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        invoke_kwargs = invoke_mock.call_args.kwargs
        self.assertEqual(len(invoke_kwargs["messages"]), 1)
        self.assertEqual(invoke_kwargs["messages"][0]["role"], "user")

    def test_model_config_compat_endpoint_warns_for_gpt5_temperature(self):
        self._set_identity(self.admin_identity)
        provider = self._ensure_provider()
        config = ModelConfig.objects.create(
            provider=provider,
            model_name="gpt-5",
            temperature=0.2,
            max_tokens=500,
            enabled=True,
        )
        response = self.client.get(f"/xyn/api/ai/model-configs/{config.id}/compat")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        warned_params = {item["param"] for item in payload.get("warnings") or []}
        self.assertIn("temperature", warned_params)
        self.assertNotIn("temperature", payload.get("effective_params") or {})

    def test_delete_model_config_deprecates_instead_of_hard_delete(self):
        self._set_identity(self.admin_identity)
        provider = self._ensure_provider()
        config = ModelConfig.objects.create(
            provider=provider,
            model_name="gpt-5",
            temperature=0.2,
            max_tokens=500,
            enabled=True,
        )
        response = self.client.delete(f"/xyn/api/ai/model-configs/{config.id}")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload.get("status"), "deprecated")
        config.refresh_from_db()
        self.assertFalse(config.enabled)

    @patch("xyn_orchestrator.xyn_api.invoke_model")
    def test_ai_activity_lists_ai_invocations(self, invoke_mock):
        self._set_identity(self.admin_identity)
        provider = self._ensure_provider()
        model_config = ModelConfig.objects.create(provider=provider, model_name="gpt-4o-mini", enabled=True)
        create_agent = self.client.post(
            "/xyn/api/ai/agents",
            data=json.dumps(
                {
                    "slug": "docs-activity",
                    "name": "Docs Activity",
                    "model_config_id": str(model_config.id),
                    "system_prompt_text": "assist docs",
                    "purposes": ["documentation"],
                    "enabled": True,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(create_agent.status_code, 200)
        invoke_mock.return_value = {"content": "ok", "provider": "openai", "model": "gpt-4o-mini", "usage": None}
        self.client.post(
            "/xyn/api/ai/invoke",
            data=json.dumps(
                {
                    "agent_slug": "docs-activity",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "metadata": {"feature": "articles_ai_assist", "workspace_id": "ws-1", "artifact_id": "art-1"},
                }
            ),
            content_type="application/json",
        )
        response = self.client.get("/xyn/api/ai/activity")
        self.assertEqual(response.status_code, 200)
        items = response.json().get("items") or []
        self.assertGreaterEqual(len(items), 1)
        self.assertEqual(items[0].get("event_type"), "ai_invocation")
