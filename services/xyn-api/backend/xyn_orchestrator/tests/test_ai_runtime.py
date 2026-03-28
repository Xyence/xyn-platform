import os
from unittest.mock import Mock, patch

from django.test import TestCase

from xyn_orchestrator.ai_runtime import (
    _extract_openai_response_text,
    assemble_system_prompt,
    ensure_default_ai_seeds,
    invoke_model,
    resolve_agent_routing,
    resolve_ai_config,
)
from xyn_orchestrator.models import AgentDefinition, AgentDefinitionPurpose, AgentPurpose, ContextPack, ModelConfig, ModelProvider, ProviderCredential


class AiRuntimeTests(TestCase):
    def setUp(self):
        os.environ["XYN_CREDENTIALS_ENCRYPTION_KEY"] = "V2S8x7lAB2BaN8A-14EvhA-gF1kq4KOlnS2vPc9vulE="
        for key in (
            "XYN_AI_PROVIDER",
            "XYN_AI_MODEL",
            "XYN_OPENAI_API_KEY",
            "XYN_GEMINI_API_KEY",
            "XYN_ANTHROPIC_API_KEY",
            "XYN_AI_PLANNING_PROVIDER",
            "XYN_AI_PLANNING_MODEL",
            "XYN_AI_PLANNING_API_KEY",
            "XYN_AI_CODING_PROVIDER",
            "XYN_AI_CODING_MODEL",
            "XYN_AI_CODING_API_KEY",
        ):
            os.environ.pop(key, None)

    def test_bootstrap_uses_canonical_seed_ai_env(self):
        with patch.dict(
            os.environ,
            {
                "XYN_AI_PROVIDER": "gemini",
                "XYN_AI_MODEL": "gemini-2.0-flash",
                "XYN_GEMINI_API_KEY": "gm-test-key",
            },
            clear=False,
        ):
            ensure_default_ai_seeds()
            default_assistant = AgentDefinition.objects.get(slug="default-assistant")
            self.assertEqual(default_assistant.model_config.provider.slug, "google")
            self.assertEqual(default_assistant.model_config.model_name, "gemini-2.0-flash")

    def test_bootstrap_default_only_creates_default_agent_and_planning_purpose(self):
        with patch.dict(
            os.environ,
            {
                "XYN_AI_PROVIDER": "openai",
                "XYN_AI_MODEL": "gpt-5-mini",
                "XYN_OPENAI_API_KEY": "sk-default-only",
            },
            clear=False,
        ):
            ensure_default_ai_seeds()
        self.assertTrue(AgentPurpose.objects.filter(slug="planning").exists())
        self.assertTrue(AgentDefinition.objects.filter(slug="default-assistant").exists())
        self.assertFalse(AgentDefinition.objects.filter(slug="planning-assistant").exists())
        self.assertFalse(AgentDefinition.objects.filter(slug="coding-assistant").exists())

    def test_bootstrap_default_and_planning_creates_planning_agent(self):
        with patch.dict(
            os.environ,
            {
                "XYN_AI_PROVIDER": "openai",
                "XYN_AI_MODEL": "gpt-5-mini",
                "XYN_OPENAI_API_KEY": "sk-default-openai",
                "XYN_AI_PLANNING_PROVIDER": "anthropic",
                "XYN_AI_PLANNING_MODEL": "claude-3-7-sonnet-latest",
                "XYN_AI_PLANNING_API_KEY": "sk-plan-anthropic",
            },
            clear=False,
        ):
            ensure_default_ai_seeds()
        planning_agent = AgentDefinition.objects.get(slug="planning-assistant")
        self.assertEqual(planning_agent.model_config.provider.slug, "anthropic")
        self.assertTrue(planning_agent.purposes.filter(slug="planning").exists())

    def test_bootstrap_default_and_coding_creates_coding_agent(self):
        with patch.dict(
            os.environ,
            {
                "XYN_AI_PROVIDER": "openai",
                "XYN_AI_MODEL": "gpt-5-mini",
                "XYN_OPENAI_API_KEY": "sk-default-openai",
                "XYN_AI_CODING_PROVIDER": "gemini",
                "XYN_AI_CODING_MODEL": "gemini-2.0-flash",
                "XYN_AI_CODING_API_KEY": "sk-code-gemini",
            },
            clear=False,
        ):
            ensure_default_ai_seeds()
        coding_agent = AgentDefinition.objects.get(slug="coding-assistant")
        self.assertEqual(coding_agent.model_config.provider.slug, "google")
        self.assertTrue(coding_agent.purposes.filter(slug="coding").exists())

    def test_bootstrap_reuses_same_credential_for_default_planning_and_coding_when_provider_and_key_match(self):
        with patch.dict(
            os.environ,
            {
                "XYN_AI_PROVIDER": "openai",
                "XYN_AI_MODEL": "gpt-5-mini",
                "XYN_OPENAI_API_KEY": "sk-shared-openai",
                "XYN_AI_PLANNING_PROVIDER": "openai",
                "XYN_AI_PLANNING_MODEL": "gpt-5-mini",
                "XYN_AI_PLANNING_API_KEY": "sk-shared-openai",
                "XYN_AI_CODING_PROVIDER": "openai",
                "XYN_AI_CODING_MODEL": "gpt-5.1-mini",
                "XYN_AI_CODING_API_KEY": "sk-shared-openai",
            },
            clear=False,
        ):
            ensure_default_ai_seeds()
        agents = {
            slug: AgentDefinition.objects.get(slug=slug)
            for slug in ("default-assistant", "planning-assistant", "coding-assistant")
        }
        credential_ids = {str(agent.model_config.credential_id) for agent in agents.values()}
        self.assertEqual(len(credential_ids), 1)
        self.assertEqual(ProviderCredential.objects.filter(provider__slug="openai").count(), 1)

    def test_bootstrap_attaches_planning_and_coding_context_packs_idempotently(self):
        with patch.dict(
            os.environ,
            {
                "XYN_AI_PROVIDER": "openai",
                "XYN_AI_MODEL": "gpt-5-mini",
                "XYN_OPENAI_API_KEY": "sk-default-openai",
                "XYN_AI_PLANNING_PROVIDER": "openai",
                "XYN_AI_PLANNING_MODEL": "gpt-5-mini",
                "XYN_AI_PLANNING_API_KEY": "sk-plan-openai",
                "XYN_AI_CODING_PROVIDER": "openai",
                "XYN_AI_CODING_MODEL": "gpt-5.1-mini",
                "XYN_AI_CODING_API_KEY": "sk-code-openai",
            },
            clear=False,
        ):
            ensure_default_ai_seeds()
            ensure_default_ai_seeds()
        planning_agent = AgentDefinition.objects.get(slug="planning-assistant")
        coding_agent = AgentDefinition.objects.get(slug="coding-assistant")
        planning_purpose = AgentPurpose.objects.get(slug="planning")
        coding_purpose = AgentPurpose.objects.get(slug="coding")
        self.assertTrue(planning_agent.context_pack_refs_json)
        self.assertTrue(coding_agent.context_pack_refs_json)
        self.assertTrue(planning_purpose.default_context_pack_refs_json)
        self.assertTrue(coding_purpose.default_context_pack_refs_json)
        self.assertEqual(ContextPack.objects.filter(name="xyn-planner-canon", purpose="planner").count(), 1)
        self.assertEqual(ContextPack.objects.filter(name="xyn-coder-canon", purpose="coder").count(), 1)

    def test_bootstrap_prunes_unused_duplicate_bootstrap_model_configs(self):
        with patch.dict(
            os.environ,
            {
                "XYN_AI_PROVIDER": "openai",
                "XYN_AI_MODEL": "gpt-5-mini",
                "XYN_OPENAI_API_KEY": "sk-dup-openai",
            },
            clear=False,
        ):
            ensure_default_ai_seeds()
            canonical = AgentDefinition.objects.get(slug="default-assistant").model_config
            provider = canonical.provider
            duplicate_credential = ProviderCredential.objects.create(
                provider=provider,
                name="openai-bootstrap-dup00000",
                auth_type="env_ref",
                env_var_name="XYN_OPENAI_API_KEY",
                enabled=True,
            )
            ModelConfig.objects.create(provider=provider, model_name="gpt-5-mini", credential=duplicate_credential, enabled=True)
            ModelConfig.objects.create(provider=provider, model_name="gpt-5-mini", credential=None, enabled=True)

            ensure_default_ai_seeds()

        self.assertEqual(
            ModelConfig.objects.filter(provider__slug="openai", model_name="gpt-5-mini", enabled=True).count(),
            1,
        )
        self.assertFalse(ModelConfig.objects.filter(credential_id=duplicate_credential.id).exists())

    def test_bootstrap_preserves_explicit_custom_purpose_default_assignments(self):
        with patch.dict(
            os.environ,
            {
                "XYN_AI_PROVIDER": "openai",
                "XYN_AI_MODEL": "gpt-5-mini",
                "XYN_OPENAI_API_KEY": "sk-default-openai",
                "XYN_AI_PLANNING_PROVIDER": "openai",
                "XYN_AI_PLANNING_MODEL": "gpt-5-mini",
                "XYN_AI_PLANNING_API_KEY": "sk-plan-openai",
            },
            clear=False,
        ):
            ensure_default_ai_seeds()
            planning_purpose = AgentPurpose.objects.get(slug="planning")
            custom_model = ModelConfig.objects.create(
                provider=ModelProvider.objects.get(slug="openai"),
                model_name="gpt-5-mini",
                enabled=True,
            )
            custom_agent = AgentDefinition.objects.create(
                slug="custom-planning-agent",
                name="Custom Planning Agent",
                model_config=custom_model,
                enabled=True,
            )
            custom_link = AgentDefinitionPurpose.objects.create(
                agent_definition=custom_agent,
                purpose=planning_purpose,
                is_default_for_purpose=True,
            )
            AgentDefinitionPurpose.objects.filter(
                purpose=planning_purpose, is_default_for_purpose=True
            ).exclude(id=custom_link.id).update(is_default_for_purpose=False)

            ensure_default_ai_seeds()

        refreshed = AgentDefinitionPurpose.objects.filter(
            purpose__slug="planning", is_default_for_purpose=True
        ).select_related("agent_definition")
        self.assertEqual(refreshed.count(), 1)
        self.assertEqual(refreshed.first().agent_definition.slug, "custom-planning-agent")

    def test_assemble_system_prompt_preamble_only(self):
        self.assertEqual(assemble_system_prompt("", "Purpose preamble"), "Purpose preamble")

    def test_assemble_system_prompt_agent_only(self):
        self.assertEqual(assemble_system_prompt("Agent prompt", ""), "Agent prompt")

    def test_assemble_system_prompt_both(self):
        self.assertEqual(
            assemble_system_prompt("Agent prompt", "Purpose preamble"),
            "Purpose preamble\n\nAgent prompt",
        )

    def test_assemble_system_prompt_neither(self):
        self.assertEqual(assemble_system_prompt("", ""), "")

    def test_bootstrap_removes_legacy_documentation_default_agent(self):
        provider, _ = ModelProvider.objects.get_or_create(slug="openai", defaults={"name": "OpenAI", "enabled": True})
        legacy, _ = AgentDefinition.objects.get_or_create(
            slug="documentation-default",
            defaults={
                "name": "Documentation Default",
                "model_config": provider.model_configs.create(model_name="gpt-4o-mini"),
                "enabled": True,
            },
        )
        legacy.name = "Documentation Default"
        legacy.enabled = True
        legacy.save(update_fields=["name", "enabled", "updated_at"])
        ensure_default_ai_seeds()
        self.assertFalse(AgentDefinition.objects.filter(slug="documentation-default").exists())
        default_assistant = AgentDefinition.objects.get(slug="default-assistant")
        self.assertEqual(default_assistant.name, "Xyn Default Assistant")
        self.assertTrue(default_assistant.purposes.filter(slug="coding").exists())
        self.assertTrue(default_assistant.purposes.filter(slug="documentation").exists())

    def test_resolve_ai_config_uses_provider_default_credential_when_model_credential_missing(self):
        provider, _ = ModelProvider.objects.get_or_create(slug="openai", defaults={"name": "OpenAI", "enabled": True})
        ProviderCredential.objects.filter(provider=provider).delete()
        os.environ["XYN_TEST_OPENAI_KEY"] = "sk-runtime-test-1234"
        ProviderCredential.objects.create(
            provider=provider,
            name="default-openai",
            auth_type="env_ref",
            env_var_name="XYN_TEST_OPENAI_KEY",
            is_default=True,
            enabled=True,
        )
        model = ModelConfig.objects.create(provider=provider, model_name="gpt-4o-mini", credential=None, enabled=True)
        purpose, _ = AgentPurpose.objects.get_or_create(slug="coding", defaults={"name": "Coding", "status": "active", "enabled": True})
        agent = AgentDefinition.objects.create(
            slug="test-default-credential-agent",
            name="Test Default Credential Agent",
            model_config=model,
            enabled=True,
        )
        AgentDefinitionPurpose.objects.create(agent_definition=agent, purpose=purpose)
        resolved = resolve_ai_config(agent_slug=agent.slug)
        self.assertEqual(resolved.get("provider"), "openai")
        self.assertEqual(resolved.get("api_key"), "sk-runtime-test-1234")

    def test_resolve_ai_config_falls_back_to_env_when_encrypted_credential_cannot_be_decrypted(self):
        provider, _ = ModelProvider.objects.get_or_create(slug="openai", defaults={"name": "OpenAI", "enabled": True})
        credential = ProviderCredential.objects.create(
            provider=provider,
            name="broken-openai",
            auth_type="api_key",
            api_key_encrypted="not-a-valid-fernet-payload",
            is_default=True,
            enabled=True,
        )
        model = ModelConfig.objects.create(provider=provider, model_name="gpt-5-mini", credential=credential, enabled=True)
        purpose, _ = AgentPurpose.objects.get_or_create(slug="coding", defaults={"name": "Coding", "status": "active", "enabled": True})
        agent = AgentDefinition.objects.create(
            slug="broken-credential-agent",
            name="Broken Credential Agent",
            model_config=model,
            enabled=True,
        )
        AgentDefinitionPurpose.objects.create(agent_definition=agent, purpose=purpose)
        with patch.dict(os.environ, {"XYN_OPENAI_API_KEY": "sk-env-fallback-openai"}, clear=False):
            resolved = resolve_ai_config(agent_slug=agent.slug)
        self.assertEqual(resolved.get("provider"), "openai")
        self.assertEqual(resolved.get("api_key"), "sk-env-fallback-openai")

    def test_resolve_ai_config_prefers_planning_agent_and_falls_back_to_default(self):
        with patch.dict(
            os.environ,
            {
                "XYN_AI_PROVIDER": "openai",
                "XYN_AI_MODEL": "gpt-5-mini",
                "XYN_OPENAI_API_KEY": "sk-default-openai",
            },
            clear=False,
        ):
            ensure_default_ai_seeds()
            resolved = resolve_ai_config(purpose_slug="planning")
            self.assertEqual(resolved.get("agent_slug"), "default-assistant")
            os.environ["XYN_AI_PLANNING_PROVIDER"] = "anthropic"
            os.environ["XYN_AI_PLANNING_MODEL"] = "claude-3-7-sonnet-latest"
            os.environ["XYN_AI_PLANNING_API_KEY"] = "sk-plan-anthropic"
            ensure_default_ai_seeds()
            resolved = resolve_ai_config(purpose_slug="planning")
        self.assertEqual(resolved.get("agent_slug"), "planning-assistant")
        self.assertEqual(resolved.get("purpose"), "planning")
        routing = resolved.get("agent_resolution") or {}
        self.assertEqual(routing.get("purpose"), "planning")
        self.assertEqual(routing.get("resolved_agent_name"), "Xyn Planning Assistant")
        self.assertEqual(routing.get("resolution_source"), "explicit")

    def test_resolve_ai_config_prefers_coding_agent_and_falls_back_to_default(self):
        with patch.dict(
            os.environ,
            {
                "XYN_AI_PROVIDER": "openai",
                "XYN_AI_MODEL": "gpt-5-mini",
                "XYN_OPENAI_API_KEY": "sk-default-openai",
            },
            clear=False,
        ):
            ensure_default_ai_seeds()
            resolved = resolve_ai_config(purpose_slug="coding")
            self.assertEqual(resolved.get("agent_slug"), "default-assistant")
            os.environ["XYN_AI_CODING_PROVIDER"] = "gemini"
            os.environ["XYN_AI_CODING_MODEL"] = "gemini-2.0-flash"
            os.environ["XYN_AI_CODING_API_KEY"] = "sk-code-gemini"
            ensure_default_ai_seeds()
            resolved = resolve_ai_config(purpose_slug="coding")
        self.assertEqual(resolved.get("agent_slug"), "coding-assistant")
        self.assertEqual(resolved.get("purpose"), "coding")
        routing = resolved.get("agent_resolution") or {}
        self.assertEqual(routing.get("purpose"), "coding")
        self.assertEqual(routing.get("resolved_agent_name"), "Xyn Coding Assistant")
        self.assertEqual(routing.get("resolution_source"), "explicit")

    def test_resolve_ai_config_uses_resolved_agent_model_not_purpose_model(self):
        provider, _ = ModelProvider.objects.get_or_create(slug="openai", defaults={"name": "OpenAI", "enabled": True})
        purpose_model = ModelConfig.objects.create(provider=provider, model_name="gpt-5-mini", enabled=True)
        purpose, _ = AgentPurpose.objects.get_or_create(
            slug="planning",
            defaults={"name": "Planning", "status": "active", "enabled": True},
        )
        purpose.model_config = purpose_model
        purpose.save(update_fields=["model_config", "updated_at"])

        os.environ["XYN_TEST_AGENT_MODEL_KEY"] = "sk-agent-model"
        credential = ProviderCredential.objects.create(
            provider=provider,
            name="agent-openai",
            auth_type="env_ref",
            env_var_name="XYN_TEST_AGENT_MODEL_KEY",
            enabled=True,
            is_default=True,
        )
        selected_model = ModelConfig.objects.create(
            provider=provider,
            model_name="gpt-5.4",
            credential=credential,
            enabled=True,
        )
        selected_agent = AgentDefinition.objects.create(
            slug="selected-planning-agent",
            name="Selected Planning Agent",
            model_config=selected_model,
            enabled=True,
        )
        AgentDefinitionPurpose.objects.create(
            agent_definition=selected_agent,
            purpose=purpose,
            is_default_for_purpose=True,
        )

        resolved = resolve_ai_config(purpose_slug="planning")
        self.assertEqual(resolved.get("agent_slug"), "selected-planning-agent")
        self.assertEqual(resolved.get("model_name"), "gpt-5.4")

    def test_resolve_agent_routing_uses_default_fallback_when_purpose_unassigned(self):
        with patch.dict(
            os.environ,
            {
                "XYN_AI_PROVIDER": "openai",
                "XYN_AI_MODEL": "gpt-5-mini",
                "XYN_OPENAI_API_KEY": "sk-default-openai",
            },
            clear=False,
        ):
            ensure_default_ai_seeds()
        routing = resolve_agent_routing(purpose_slug="documentation")
        self.assertEqual(routing.get("purpose"), "documentation")
        self.assertEqual(routing.get("resolution_source"), "default_fallback")
        self.assertEqual(routing.get("resolved_agent_name"), "Xyn Default Assistant")

    def test_resolve_agent_routing_returns_unresolved_when_no_enabled_agents_exist(self):
        AgentDefinition.objects.all().delete()
        routing = resolve_agent_routing(purpose_slug="planning")
        self.assertEqual(routing.get("resolution_source"), "default_fallback")
        self.assertIsNone(routing.get("resolved_agent_id"))
        self.assertIn("no enabled agent available", str(routing.get("reason") or ""))

    def test_extract_openai_response_text_from_output_content(self):
        payload = {
            "id": "resp_123",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Health check passed.",
                        }
                    ],
                }
            ],
        }
        self.assertEqual(_extract_openai_response_text(payload), "Health check passed.")

    @patch("xyn_orchestrator.ai_runtime.requests.post")
    def test_invoke_model_omits_unsupported_temperature_for_gpt5(self, post_mock):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"output_text": "ok"}
        post_mock.return_value = response
        invoke_model(
            resolved_config={
                "provider": "openai",
                "model_name": "gpt-5",
                "api_key": "sk-test",
                "temperature": 0.2,
                "top_p": 0.95,
                "max_tokens": 120,
            },
            messages=[{"role": "user", "content": "hello"}],
        )
        kwargs = post_mock.call_args.kwargs
        body = kwargs["json"]
        self.assertNotIn("temperature", body)
        self.assertNotIn("top_p", body)
        self.assertEqual(body.get("max_output_tokens"), 120)
