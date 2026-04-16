import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError
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
        system_workspace = Workspace.objects.get(slug="platform-builder")
        system_meta = system_workspace.metadata_json if isinstance(system_workspace.metadata_json, dict) else {}
        self.assertEqual(system_meta.get("xyn_workspace_role"), "system_platform")
        self.assertTrue(system_meta.get("xyn_system_workspace"))
        self.assertTrue(system_meta.get("xyn_hidden_from_ui"))
        dev_meta = workspace.metadata_json if isinstance(workspace.metadata_json, dict) else {}
        self.assertEqual(dev_meta.get("xyn_workspace_role"), "default_user")
        self.assertNotIn("xyn_system_workspace", dev_meta)

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
        system_workspace = Workspace.objects.get(slug="platform-builder")
        system_meta = system_workspace.metadata_json if isinstance(system_workspace.metadata_json, dict) else {}
        self.assertEqual(system_meta.get("xyn_workspace_role"), "system_platform")
        company_meta = workspace.metadata_json if isinstance(workspace.metadata_json, dict) else {}
        self.assertEqual(company_meta.get("xyn_workspace_role"), "default_user")

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "oidc", "XYN_ORG_NAME": "Xyence"}, clear=False)
    def test_non_dev_me_auto_bootstraps_org_default_workspace(self):
        response = self.client.get("/xyn/api/me")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        workspaces = payload.get("workspaces") or []
        self.assertEqual(len(workspaces), 1)
        self.assertEqual(workspaces[0]["slug"], "xyence")
        self.assertEqual(workspaces[0]["workspace_role"], "default_user")
        workspace = Workspace.objects.get(slug="xyence")
        meta = workspace.metadata_json if isinstance(workspace.metadata_json, dict) else {}
        self.assertEqual(meta.get("xyn_workspace_role"), "default_user")
        self.assertEqual(payload.get("preferred_workspace_id"), str(workspace.id))

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "dev"}, clear=False)
    def test_system_workspace_hidden_by_default_and_visible_with_include_system(self):
        response = self.client.get("/xyn/api/me")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        workspaces = payload.get("workspaces") or []
        self.assertEqual([row.get("slug") for row in workspaces], ["development"])

        all_rows = self.client.get("/xyn/api/workspaces?include_system=true")
        self.assertEqual(all_rows.status_code, 200)
        full_payload = all_rows.json()
        listed = sorted([str(row.get("slug") or "") for row in (full_payload.get("workspaces") or [])])
        self.assertIn("development", listed)
        self.assertIn("platform-builder", listed)

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

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "dev"}, clear=False)
    def test_default_workspace_artifact_bindings_are_idempotent(self):
        workspace = Workspace.objects.create(slug="idempotent-bindings", name="Idempotent Bindings")

        xyn_api._ensure_default_workspace_artifact_bindings(workspace)
        first_binding_count = WorkspaceArtifactBinding.objects.filter(workspace=workspace).count()
        first_artifact_count = Artifact.objects.count()

        xyn_api._ensure_default_workspace_artifact_bindings(workspace)
        second_binding_count = WorkspaceArtifactBinding.objects.filter(workspace=workspace).count()
        second_artifact_count = Artifact.objects.count()

        self.assertEqual(first_binding_count, second_binding_count)
        self.assertEqual(first_artifact_count, second_artifact_count)

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "dev"}, clear=False)
    def test_ensure_runtime_artifact_reuses_existing_canonical_source_ref(self):
        host_workspace = Workspace.objects.create(slug="platform-builder", name="Platform Builder")
        caller_workspace = Workspace.objects.create(slug="customer-ws", name="Customer")
        module_type, _ = ArtifactType.objects.get_or_create(
            slug="module",
            defaults={"name": "Module", "description": "Kernel-loadable module artifact."},
        )

        canonical_git = xyn_api.build_runtime_artifact_git_provenance(
            slug="xyn-ui",
            manifest_ref="registry/modules/xyn-ui.artifact.manifest.json",
        )
        source_ref_type, source_ref_id = xyn_api.runtime_git_source_ref(canonical_git)
        canonical = Artifact.objects.create(
            workspace=host_workspace,
            type=module_type,
            title="xyn-ui",
            slug="xyn-ui",
            status="published",
            visibility="team",
            source_ref_type=source_ref_type,
            source_ref_id=source_ref_id,
        )

        ensured = xyn_api._ensure_runtime_artifact(
            workspace=caller_workspace,
            slug="xyn-ui",
            title="xyn-ui",
            manifest_ref="registry/modules/xyn-ui.artifact.manifest.json",
            summary="Deployable Xyn UI runtime artifact.",
        )

        self.assertEqual(str(ensured.id), str(canonical.id))
        self.assertEqual(
            Artifact.objects.filter(source_ref_type=source_ref_type, source_ref_id=source_ref_id).count(),
            1,
        )

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "dev"}, clear=False)
    def test_ensure_runtime_artifact_retries_canonical_fetch_after_integrity_error(self):
        workspace = Workspace.objects.create(slug="retry-ws", name="Retry WS")
        other_workspace = Workspace.objects.create(slug="retry-other", name="Retry Other")
        module_type, _ = ArtifactType.objects.get_or_create(
            slug="module",
            defaults={"name": "Module", "description": "Kernel-loadable module artifact."},
        )
        stale = Artifact.objects.create(
            workspace=workspace,
            type=module_type,
            title="xyn-api",
            slug="xyn-api",
            status="published",
            visibility="team",
            source_ref_type="",
            source_ref_id="",
        )

        canonical_git = xyn_api.build_runtime_artifact_git_provenance(
            slug="xyn-api",
            manifest_ref="registry/modules/xyn-api.artifact.manifest.json",
        )
        source_ref_type, source_ref_id = xyn_api.runtime_git_source_ref(canonical_git)
        canonical = Artifact.objects.create(
            workspace=other_workspace,
            type=module_type,
            title="xyn-api",
            slug="xyn-api",
            status="published",
            visibility="team",
            source_ref_type=source_ref_type,
            source_ref_id=source_ref_id,
        )

        original_save = Artifact.save
        raised = {"done": False}

        def _racey_save(instance, *args, **kwargs):
            update_fields = kwargs.get("update_fields") or []
            if (
                instance.id == stale.id
                and "source_ref_id" in update_fields
                and not raised["done"]
            ):
                raised["done"] = True
                raise IntegrityError("duplicate key value violates unique constraint \"uniq_artifact_source_ref\"")
            return original_save(instance, *args, **kwargs)

        with mock.patch.object(Artifact, "save", autospec=True, side_effect=_racey_save):
            ensured = xyn_api._ensure_runtime_artifact(
                workspace=workspace,
                slug="xyn-api",
                title="xyn-api",
                manifest_ref="registry/modules/xyn-api.artifact.manifest.json",
                summary="Deployable Xyn API runtime artifact.",
            )

        self.assertEqual(str(ensured.id), str(canonical.id))
        self.assertTrue(raised["done"])

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "dev"}, clear=False)
    def test_ensure_runtime_artifact_reuses_workspace_slug_owner_when_source_ref_missing(self):
        workspace = Workspace.objects.create(slug="slug-owner-ws", name="Slug Owner WS")
        module_type, _ = ArtifactType.objects.get_or_create(
            slug="module",
            defaults={"name": "Module", "description": "Kernel-loadable module artifact."},
        )
        existing = Artifact.objects.create(
            workspace=workspace,
            type=module_type,
            title="xyn-ui old",
            slug="xyn-ui",
            status="published",
            visibility="team",
            source_ref_type="",
            source_ref_id="",
        )
        ensured = xyn_api._ensure_runtime_artifact(
            workspace=workspace,
            slug="xyn-ui",
            title="xyn-ui",
            manifest_ref="registry/modules/xyn-ui.artifact.manifest.json",
            summary="Deployable Xyn UI runtime artifact.",
        )
        self.assertEqual(str(ensured.id), str(existing.id))
        self.assertEqual(str(ensured.slug), "xyn-ui")
        self.assertEqual(str(ensured.source_ref_type), "GitSource")
        self.assertTrue(str(ensured.source_ref_id))

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "dev"}, clear=False)
    def test_ensure_runtime_artifact_reconciles_split_unique_keys_with_source_ref_precedence(self):
        workspace = Workspace.objects.create(slug="split-keys-ws", name="Split Keys WS")
        module_type, _ = ArtifactType.objects.get_or_create(
            slug="module",
            defaults={"name": "Module", "description": "Kernel-loadable module artifact."},
        )
        slug_owner = Artifact.objects.create(
            workspace=workspace,
            type=module_type,
            title="xyn-ui slug owner",
            slug="xyn-ui",
            status="published",
            visibility="team",
            source_ref_type="",
            source_ref_id="",
        )
        canonical_git = xyn_api.build_runtime_artifact_git_provenance(
            slug="xyn-ui",
            manifest_ref="registry/modules/xyn-ui.artifact.manifest.json",
        )
        source_ref_type, source_ref_id = xyn_api.runtime_git_source_ref(canonical_git)
        source_owner = Artifact.objects.create(
            workspace=workspace,
            type=module_type,
            title="xyn-ui canonical owner",
            slug="xyn-ui-canonical",
            status="published",
            visibility="team",
            source_ref_type=source_ref_type,
            source_ref_id=source_ref_id,
        )

        ensured = xyn_api._ensure_runtime_artifact(
            workspace=workspace,
            slug="xyn-ui",
            title="xyn-ui",
            manifest_ref="registry/modules/xyn-ui.artifact.manifest.json",
            summary="Deployable Xyn UI runtime artifact.",
        )
        self.assertEqual(str(ensured.id), str(source_owner.id))
        slug_owner.refresh_from_db()
        source_owner.refresh_from_db()
        self.assertEqual(slug_owner.slug, "xyn-ui")
        self.assertEqual(source_owner.slug, "xyn-ui-canonical")
        self.assertEqual(
            Artifact.objects.filter(source_ref_type=source_ref_type, source_ref_id=source_ref_id).count(),
            1,
        )

    @mock.patch.dict("os.environ", {"XYN_AUTH_MODE": "dev"}, clear=False)
    def test_unique_source_ref_constraint_remains_enforced(self):
        workspace = Workspace.objects.create(slug="unique-ws", name="Unique WS")
        module_type, _ = ArtifactType.objects.get_or_create(
            slug="module",
            defaults={"name": "Module", "description": "Kernel-loadable module artifact."},
        )
        canonical_git = xyn_api.build_runtime_artifact_git_provenance(
            slug="core.workbench",
            manifest_ref="registry/modules/core.workbench.artifact.manifest.json",
        )
        source_ref_type, source_ref_id = xyn_api.runtime_git_source_ref(canonical_git)

        Artifact.objects.create(
            workspace=workspace,
            type=module_type,
            title="core.workbench",
            slug="core.workbench",
            status="published",
            visibility="team",
            source_ref_type=source_ref_type,
            source_ref_id=source_ref_id,
        )
        with self.assertRaises(IntegrityError):
            Artifact.objects.create(
                workspace=workspace,
                type=module_type,
                title="duplicate",
                slug="duplicate-workbench",
                status="published",
                visibility="team",
                source_ref_type=source_ref_type,
                source_ref_id=source_ref_id,
            )
