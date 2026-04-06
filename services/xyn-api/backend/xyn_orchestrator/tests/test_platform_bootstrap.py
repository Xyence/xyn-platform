import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from xyn_orchestrator import xyn_api
from xyn_orchestrator.models import (
    Application,
    ApplicationArtifactMembership,
    Artifact,
    ArtifactType,
    RoleBinding,
    UserIdentity,
    Workspace,
    WorkspaceArtifactBinding,
    WorkspaceMembership,
)


class PlatformBootstrapTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="bootstrap-admin",
            email="bootstrap-admin@example.com",
            password="pass",
            is_staff=True,
        )
        self.client.force_login(self.user)
        self.identity = UserIdentity.objects.create(
            provider="local",
            provider_id="local",
            issuer="local",
            subject="bootstrap-admin",
            email="bootstrap-admin@example.com",
            display_name="Bootstrap Admin",
        )
        RoleBinding.objects.create(
            user_identity=self.identity,
            scope_kind="platform",
            role="platform_admin",
        )
        session = self.client.session
        session["user_identity_id"] = str(self.identity.id)
        session.save()

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "dev"}, clear=False)
    def test_dev_me_auto_bootstraps_development_workspace(self):
        self.assertFalse(Workspace.objects.filter(slug="development").exists())
        response = self.client.get("/xyn/api/me")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        workspaces = payload.get("workspaces") or []
        self.assertEqual(len(workspaces), 1)
        self.assertEqual(workspaces[0]["slug"], "development")
        workspace = Workspace.objects.get(slug="development")
        membership = WorkspaceMembership.objects.filter(workspace=workspace, user_identity=self.identity).first()
        self.assertIsNotNone(membership)
        self.assertEqual(membership.role, "admin")
        self.assertTrue(membership.termination_authority)
        xyn_solution = Application.objects.filter(
            workspace=workspace,
            metadata_json__system_solution_key="xyn-platform-default",
        ).first()
        self.assertIsNotNone(xyn_solution)
        self.assertEqual(xyn_solution.source_factory_key, "xyn_platform_default")

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "dev"}, clear=False)
    def test_dev_me_prefers_development_when_system_workspaces_exist(self):
        Workspace.objects.get_or_create(
            slug="platform-builder",
            defaults={"name": "Platform Builder", "metadata_json": {"xyn_system_workspace": True}},
        )
        Workspace.objects.get_or_create(
            slug="civic-lab",
            defaults={"name": "Civic Lab", "metadata_json": {"xyn_system_workspace": True}},
        )
        response = self.client.get("/xyn/api/me")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        workspaces = payload.get("workspaces") or []
        self.assertEqual(len(workspaces), 1)
        self.assertEqual(workspaces[0]["slug"], "development")
        self.assertEqual(payload.get("preferred_workspace_id"), workspaces[0]["id"])

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "dev"}, clear=False)
    def test_dev_bootstrap_xyn_solution_memberships_are_idempotent(self):
        response = self.client.get("/xyn/api/me")
        self.assertEqual(response.status_code, 200)
        workspace = Workspace.objects.get(slug="development")
        xyn_solution = Application.objects.get(
            workspace=workspace,
            metadata_json__system_solution_key="xyn-platform-default",
        )
        initial_memberships = ApplicationArtifactMembership.objects.filter(application=xyn_solution).count()

        response = self.client.get("/xyn/api/me")
        self.assertEqual(response.status_code, 200)
        restored_count = ApplicationArtifactMembership.objects.filter(application=xyn_solution).count()
        self.assertEqual(restored_count, initial_memberships)

        response = self.client.get("/xyn/api/me")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ApplicationArtifactMembership.objects.filter(application=xyn_solution).count(), restored_count)
        self.assertEqual(Workspace.objects.filter(slug="development").count(), 1)
        self.assertEqual(
            Application.objects.filter(
                workspace=workspace,
                metadata_json__system_solution_key="xyn-platform-default",
            ).count(),
            1,
        )

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "dev"}, clear=False)
    def test_dev_bootstrap_materializes_default_xyn_solution_memberships_from_platform_builder_artifacts(self):
        platform_builder = Workspace.objects.create(
            slug="platform-builder",
            name="Platform Builder",
            metadata_json={"xyn_system_workspace": True},
        )
        module_type, _ = ArtifactType.objects.get_or_create(
            slug="module",
            defaults={"name": "Module", "description": "Kernel-loadable module artifact."},
        )
        for slug in ("core.workbench", "xyn-ui", "xyn-api"):
            Artifact.objects.create(
                workspace=platform_builder,
                type=module_type,
                title=slug,
                slug=slug,
                status="published",
                visibility="team",
            )

        response = self.client.get("/xyn/api/me")
        self.assertEqual(response.status_code, 200)
        development = Workspace.objects.get(slug="development")
        xyn_solution = Application.objects.get(
            workspace=development,
            metadata_json__system_solution_key="xyn-platform-default",
        )
        memberships = list(
            ApplicationArtifactMembership.objects.filter(application=xyn_solution)
            .select_related("artifact")
            .order_by("sort_order", "created_at")
        )
        self.assertEqual(len(memberships), 3)
        self.assertEqual([row.artifact.slug for row in memberships], ["core.workbench", "xyn-ui", "xyn-api"])
        self.assertTrue(all(row.artifact.workspace_id == development.id for row in memberships))
        ownership_by_slug = {row.artifact.slug: xyn_api.resolve_artifact_ownership(row.artifact) for row in memberships}
        self.assertEqual(ownership_by_slug["core.workbench"]["repo_slug"], "xyn-platform")
        self.assertEqual(ownership_by_slug["core.workbench"]["allowed_paths"], [])
        self.assertEqual(ownership_by_slug["core.workbench"]["edit_mode"], "repo_backed")
        self.assertEqual(ownership_by_slug["xyn-ui"]["repo_slug"], "xyn-platform")
        self.assertEqual(ownership_by_slug["xyn-ui"]["allowed_paths"], ["apps/xyn-ui/"])
        self.assertEqual(ownership_by_slug["xyn-ui"]["edit_mode"], "repo_backed")
        self.assertEqual(ownership_by_slug["xyn-api"]["repo_slug"], "xyn-platform")
        self.assertEqual(ownership_by_slug["xyn-api"]["allowed_paths"], ["services/xyn-api/backend/"])
        self.assertEqual(ownership_by_slug["xyn-api"]["edit_mode"], "repo_backed")

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "dev"}, clear=False)
    def test_resolve_artifact_ownership_returns_repo_and_path_prefixes(self):
        response = self.client.get("/xyn/api/me")
        self.assertEqual(response.status_code, 200)
        workspace = Workspace.objects.get(slug="development")
        artifact = Artifact.objects.get(workspace=workspace, slug="xyn-ui")
        ownership = xyn_api.resolve_artifact_ownership(artifact)
        self.assertEqual(
            ownership,
            {
                "repo_slug": "xyn-platform",
                "allowed_paths": ["apps/xyn-ui/"],
                "edit_mode": "repo_backed",
            },
        )

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "dev"}, clear=False)
    def test_dev_bootstrap_recovers_cleanly_after_partial_failure(self):
        with mock.patch(
            "xyn_orchestrator.xyn_api._ensure_default_workspace_artifact_bindings",
            side_effect=[RuntimeError("transient bootstrap failure"), None],
        ):
            failed = self.client.get("/xyn/api/me")
            self.assertEqual(failed.status_code, 500)

            recovered = self.client.get("/xyn/api/me")
            self.assertEqual(recovered.status_code, 200)

        workspace = Workspace.objects.get(slug="development")
        self.assertEqual(Workspace.objects.filter(slug="development").count(), 1)
        self.assertEqual(
            WorkspaceMembership.objects.filter(workspace=workspace, user_identity=self.identity).count(),
            1,
        )

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "dev", "XYN_WORKSPACE_SLUG": "local-dev"}, clear=False)
    def test_dev_me_uses_configured_workspace_slug(self):
        self.assertFalse(Workspace.objects.filter(slug="local-dev").exists())
        response = self.client.get("/xyn/api/me")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        workspaces = payload.get("workspaces") or []
        self.assertEqual(len(workspaces), 1)
        self.assertEqual(workspaces[0]["slug"], "local-dev")
        self.assertEqual(payload.get("preferred_workspace_id"), workspaces[0]["id"])

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc"}, clear=False)
    def test_non_dev_requires_setup_then_initializes(self):
        status_response = self.client.get("/xyn/api/platform/initialization/status")
        self.assertEqual(status_response.status_code, 200)
        status_payload = status_response.json()["platform_initialization"]
        self.assertFalse(status_payload["initialized"])
        self.assertTrue(status_payload["requires_setup"])

        complete_response = self.client.post(
            "/xyn/api/platform/initialization/complete",
            data=json.dumps({"workspace_name": "Company", "workspace_slug": "company"}),
            content_type="application/json",
        )
        self.assertEqual(complete_response.status_code, 200)
        complete_payload = complete_response.json()
        self.assertEqual(complete_payload["workspace"]["slug"], "company")

        workspace = Workspace.objects.get(slug="company")
        membership = WorkspaceMembership.objects.filter(workspace=workspace, user_identity=self.identity).first()
        self.assertIsNotNone(membership)
        self.assertEqual(membership.role, "admin")
        self.assertTrue(membership.termination_authority)
        self.assertFalse(Workspace.objects.filter(slug="development").exists())

    @mock.patch.dict(
        "os.environ",
        {
            "XYN_AUTH_MODE": "oidc",
            "XYN_DEFAULT_XYN_SOLUTION_WORKSPACE_SLUG": "company",
        },
        clear=False,
    )
    def test_non_dev_can_seed_default_xyn_solution_for_configured_workspace(self):
        workspace = Workspace.objects.create(slug="company", name="Company", metadata_json={})
        module_type, _ = ArtifactType.objects.get_or_create(
            slug="module",
            defaults={"name": "Module", "description": "Kernel-loadable module artifact."},
        )
        for slug in ("core.workbench", "xyn-ui", "xyn-api"):
            artifact = Artifact.objects.create(
                workspace=workspace,
                type=module_type,
                title=slug,
                slug=slug,
                status="published",
            )
            WorkspaceArtifactBinding.objects.create(
                workspace=workspace,
                artifact=artifact,
                enabled=True,
                installed_state="installed",
            )

        response = self.client.get("/xyn/api/me")
        self.assertEqual(response.status_code, 200)
        xyn_solution = Application.objects.filter(
            workspace=workspace,
            metadata_json__system_solution_key="xyn-platform-default",
        ).first()
        self.assertIsNotNone(xyn_solution)
        self.assertEqual(ApplicationArtifactMembership.objects.filter(application=xyn_solution).count(), 3)
        self.assertFalse(Workspace.objects.filter(slug="development").exists())
