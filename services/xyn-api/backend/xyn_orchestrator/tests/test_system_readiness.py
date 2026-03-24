import os
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from xyn_orchestrator.ai_runtime import ensure_default_ai_seeds
from xyn_orchestrator.models import (
    AgentDefinition,
    AgentDefinitionPurpose,
    AgentPurpose,
    ModelConfig,
    ModelProvider,
    ProviderCredential,
    RoleBinding,
    UserIdentity,
)
from xyn_orchestrator.system_readiness import system_readiness_report


class SystemReadinessTests(TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        os.environ["XYN_CREDENTIALS_ENCRYPTION_KEY"] = "V2S8x7lAB2BaN8A-14EvhA-gF1kq4KOlnS2vPc9vulE="
        for key in (
            "XYN_AI_PROVIDER",
            "XYN_AI_MODEL",
            "XYN_OPENAI_API_KEY",
            "XYN_AI_PLANNING_PROVIDER",
            "XYN_AI_PLANNING_MODEL",
            "XYN_AI_PLANNING_API_KEY",
            "XYN_AI_CODING_PROVIDER",
            "XYN_AI_CODING_MODEL",
            "XYN_AI_CODING_API_KEY",
        ):
            os.environ.pop(key, None)
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="ready-admin", password="pass", is_staff=True)
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer",
            subject="ready-admin",
            email="ready-admin@example.com",
        )
        RoleBinding.objects.create(user_identity=self.identity, scope_kind="platform", role="platform_admin")
        self.client.force_login(self.user)
        session = self.client.session
        session["user_identity_id"] = str(self.identity.id)
        session.save()

    def _seed_local_remote(self, branch: str = "main") -> Path:
        root = Path(self.tempdir.name)
        source = root / "source"
        remote = root / "remote.git"
        source.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-b", branch], cwd=source, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "ready@example.com"], cwd=source, check=True)
        subprocess.run(["git", "config", "user.name", "Ready User"], cwd=source, check=True)
        (source / "README.md").write_text("ready\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=source, check=True, capture_output=True, text=True)
        subprocess.run(["git", "init", "--bare", remote], check=True, capture_output=True, text=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=source, check=True)
        subprocess.run(["git", "push", "-u", "origin", branch], cwd=source, check=True, capture_output=True, text=True)
        return remote

    def test_readiness_reports_missing_ai_agents_and_repositories(self):
        AgentDefinition.objects.all().delete()
        ProviderCredential.objects.all().delete()
        with mock.patch.dict(
            os.environ,
            {
                "XYN_WORKSPACE_ROOT": str(Path(self.tempdir.name) / "workspaces"),
                "XYN_ARTIFACT_ROOT": str(Path(self.tempdir.name) / "artifacts"),
            },
            clear=False,
        ):
            report = system_readiness_report()
        self.assertFalse(report["ready"])
        statuses = {check["component"]: check for check in report["checks"]}
        self.assertEqual(statuses["ai_providers"]["status"], "missing")
        self.assertEqual(statuses["planning_agents"]["status"], "missing")
        self.assertEqual(statuses["coding_agents"]["status"], "missing")
        self.assertEqual(statuses["repositories"]["status"], "missing")

    def test_readiness_reports_workspace_write_failure(self):
        with mock.patch.dict(
            os.environ,
            {
                "XYN_WORKSPACE_ROOT": str(Path(self.tempdir.name) / "workspaces"),
                "XYN_ARTIFACT_ROOT": str(Path(self.tempdir.name) / "artifacts"),
                "XYN_AI_PROVIDER": "openai",
                "XYN_AI_MODEL": "gpt-5-mini",
                "XYN_OPENAI_API_KEY": "sk-ready-openai",
                "XYN_AI_PLANNING_PROVIDER": "openai",
                "XYN_AI_PLANNING_MODEL": "gpt-5-mini",
                "XYN_AI_PLANNING_API_KEY": "sk-ready-openai",
                "XYN_AI_CODING_PROVIDER": "openai",
                "XYN_AI_CODING_MODEL": "gpt-5-mini",
                "XYN_AI_CODING_API_KEY": "sk-ready-openai",
            },
            clear=False,
        ):
            ensure_default_ai_seeds()
            with mock.patch("xyn_orchestrator.system_readiness._check_writable_directory") as writable:
                writable.side_effect = [
                    {"ok": False, "message": "workspace root is not writable"},
                    {"ok": True, "message": "artifact root is writable"},
                ]
                report = system_readiness_report()
        workspace_check = next(check for check in report["checks"] if check["component"] == "workspace_storage")
        self.assertEqual(workspace_check["status"], "error")
        self.assertIn("not writable", workspace_check["message"])

    def test_readiness_reports_agent_resolution_errors(self):
        with mock.patch.dict(
            os.environ,
            {
                "XYN_WORKSPACE_ROOT": str(Path(self.tempdir.name) / "workspaces"),
                "XYN_ARTIFACT_ROOT": str(Path(self.tempdir.name) / "artifacts"),
                "XYN_AI_PROVIDER": "openai",
                "XYN_AI_MODEL": "gpt-5-mini",
                "XYN_OPENAI_API_KEY": "sk-ready-openai",
            },
            clear=False,
        ):
            ensure_default_ai_seeds()
        ProviderCredential.objects.update(api_key_encrypted="not-a-valid-fernet-payload")
        with mock.patch.dict(
            os.environ,
            {
                "XYN_OPENAI_API_KEY": "",
                "OPENAI_API_KEY": "",
            },
            clear=False,
        ):
            report = system_readiness_report()
        planning = next(check for check in report["checks"] if check["component"] == "planning_agents")
        coding = next(check for check in report["checks"] if check["component"] == "coding_agents")
        self.assertEqual(planning["status"], "error")
        self.assertEqual(coding["status"], "error")
        self.assertIn("usable runtime credential", planning["message"])

    @override_settings(MEDIA_ROOT="/tmp/xyn-ready-media")
    def test_readiness_reports_ready_when_prerequisites_exist(self):
        remote = self._seed_local_remote(branch="main")
        with mock.patch.dict(
            os.environ,
            {
                "XYN_WORKSPACE_ROOT": str(Path(self.tempdir.name) / "workspaces"),
                "XYN_ARTIFACT_ROOT": str(Path(self.tempdir.name) / "artifacts"),
                "XYN_AI_PROVIDER": "openai",
                "XYN_AI_MODEL": "gpt-5-mini",
                "XYN_OPENAI_API_KEY": "sk-ready-openai",
                "XYN_AI_PLANNING_PROVIDER": "openai",
                "XYN_AI_PLANNING_MODEL": "gpt-5-mini",
                "XYN_AI_PLANNING_API_KEY": "sk-ready-openai",
                "XYN_AI_CODING_PROVIDER": "openai",
                "XYN_AI_CODING_MODEL": "gpt-5-mini",
                "XYN_AI_CODING_API_KEY": "sk-ready-openai",
            },
            clear=False,
        ):
            ensure_default_ai_seeds()
            from xyn_orchestrator.managed_repositories import register_managed_repository

            register_managed_repository(
                slug="xyn-platform",
                remote_url=str(remote),
                default_branch="main",
                auth_mode="local",
                display_name="Xyn Platform",
            )
            report = system_readiness_report()
        self.assertTrue(report["ready"])
        self.assertEqual(report["summary"], "System ready")
        repo_access = next(check for check in report["checks"] if check["component"] == "repository_access")
        self.assertEqual(repo_access["status"], "ok")

    def test_readiness_endpoint_returns_report(self):
        with mock.patch.dict(
            os.environ,
            {
                "XYN_WORKSPACE_ROOT": str(Path(self.tempdir.name) / "workspaces"),
                "XYN_ARTIFACT_ROOT": str(Path(self.tempdir.name) / "artifacts"),
            },
            clear=False,
        ):
            response = self.client.get("/xyn/api/system/readiness")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("ready", payload)
        self.assertIn("checks", payload)

    def test_readiness_reports_model_from_resolved_purpose_agent(self):
        provider, _ = ModelProvider.objects.get_or_create(slug="openai", defaults={"name": "OpenAI", "enabled": True})
        os.environ["XYN_TEST_READINESS_AGENT_KEY"] = "sk-readiness-agent"
        credential = ProviderCredential.objects.create(
            provider=provider,
            name="readiness-openai",
            auth_type="env_ref",
            env_var_name="XYN_TEST_READINESS_AGENT_KEY",
            enabled=True,
            is_default=True,
        )
        default_model = ModelConfig.objects.create(provider=provider, model_name="gpt-5-mini", credential=credential, enabled=True)
        selected_model = ModelConfig.objects.create(provider=provider, model_name="gpt-5.4", credential=credential, enabled=True)
        planning_purpose, _ = AgentPurpose.objects.get_or_create(
            slug="planning",
            defaults={"name": "Planning", "status": "active", "enabled": True},
        )
        coding_purpose, _ = AgentPurpose.objects.get_or_create(
            slug="coding",
            defaults={"name": "Coding", "status": "active", "enabled": True},
        )
        planning_purpose.model_config = default_model
        planning_purpose.save(update_fields=["model_config", "updated_at"])
        selected_planning_agent = AgentDefinition.objects.create(
            slug="readiness-planning-agent",
            name="Readiness Planning Agent",
            model_config=selected_model,
            enabled=True,
        )
        AgentDefinitionPurpose.objects.create(
            agent_definition=selected_planning_agent,
            purpose=planning_purpose,
            is_default_for_purpose=True,
        )
        selected_coding_agent = AgentDefinition.objects.create(
            slug="readiness-coding-agent",
            name="Readiness Coding Agent",
            model_config=selected_model,
            enabled=True,
        )
        AgentDefinitionPurpose.objects.create(
            agent_definition=selected_coding_agent,
            purpose=coding_purpose,
            is_default_for_purpose=True,
        )

        report = system_readiness_report()
        planning = next(check for check in report["checks"] if check["component"] == "planning_agents")
        coding = next(check for check in report["checks"] if check["component"] == "coding_agents")
        self.assertIn("openai:gpt-5.4", planning["message"])
        self.assertIn("openai:gpt-5.4", coding["message"])
