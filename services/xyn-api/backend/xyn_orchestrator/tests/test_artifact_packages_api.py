import io
import json
import zipfile
import uuid
import datetime as dt
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from xyn_orchestrator import artifact_packages, xyn_api
from xyn_orchestrator.models import (
    Application,
    ApplicationArtifactMembership,
    Artifact,
    ArtifactType,
    ArtifactBindingValue,
    ArtifactInstallReceipt,
    ArtifactPackage,
    ArtifactRevision,
    PlatformConfigDocument,
    ArtifactRuntimeRole,
    ArtifactSurface,
    RoleBinding,
    UserIdentity,
    Workspace,
    WorkspaceArtifactBinding,
    WorkspaceMembership,
)


class ArtifactPackagesApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="pkg-admin",
            password="pass",
            is_staff=True,
            email="pkg-admin@example.com",
        )
        self.client.force_login(self.user)
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer",
            subject="pkg-admin",
            email="pkg-admin@example.com",
            display_name="Pkg Admin",
        )
        session = self.client.session
        session["user_identity_id"] = str(self.identity.id)
        session.save()
        self.workspace = Workspace.objects.create(
            slug=f"pkg-workspace-{uuid.uuid4().hex[:8]}",
            name="Package Workspace",
        )
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user_identity=self.identity,
            role="admin",
            termination_authority=True,
        )

    def _package_blob(self, *, artifacts, package_name="ems-hello", package_version="0.1.0", mutate_checksums=False):
        files = {}
        manifest_artifacts = []
        for item in artifacts:
            artifact_payload = {
                "artifact": {
                    "type": item["type"],
                    "slug": item["slug"],
                    "version": item["version"],
                    "title": item.get("title") or item["slug"],
                    "description": item.get("description") or "",
                },
                "content": item.get("content") or {},
            }
            if isinstance(item.get("metadata"), dict):
                artifact_payload["metadata"] = item.get("metadata")
            base = f"artifacts/{item['type']}/{item['slug']}/{item['version']}"
            artifact_path = f"{base}/artifact.json"
            payload_path = f"{base}/payload/payload.json"
            surfaces_path = f"{base}/surfaces.json"
            runtime_roles_path = f"{base}/runtime_roles.json"
            files[artifact_path] = json.dumps(artifact_payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
            files[payload_path] = json.dumps(item.get("content") or {}, separators=(",", ":"), sort_keys=True).encode("utf-8")
            files[surfaces_path] = json.dumps(item.get("surfaces") or [], separators=(",", ":"), sort_keys=True).encode("utf-8")
            files[runtime_roles_path] = json.dumps(item.get("runtime_roles") or [], separators=(",", ":"), sort_keys=True).encode("utf-8")
            manifest_artifacts.append(
                {
                    "type": item["type"],
                    "slug": item["slug"],
                    "version": item["version"],
                    "artifact_id": item.get("artifact_id") or f"{item['type']}-{item['slug']}-{item['version']}",
                    "artifact_hash": "",
                    "dependencies": item.get("dependencies") or [],
                    "bindings": item.get("bindings") or [],
                }
            )

        checksums = {}
        import hashlib

        for path, blob in files.items():
            checksums[path] = hashlib.sha256(blob).hexdigest()

        manifest = {
            "format_version": 1,
            "package_name": package_name,
            "package_version": package_version,
            "built_at": "2026-02-28T00:00:00Z",
            "platform_compatibility": {"min_version": "1.0.0", "required_features": ["artifact_packages_v1"]},
            "artifacts": manifest_artifacts,
            "checksums": checksums,
        }
        manifest_blob = json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode("utf-8")
        files["manifest.json"] = manifest_blob
        if mutate_checksums:
            manifest["checksums"][next(iter(checksums.keys()))] = "deadbeef"
            files["manifest.json"] = json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode("utf-8")

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, blob in sorted(files.items()):
                archive.writestr(path, blob)
        return buffer.getvalue()

    def _import_package(self, blob: bytes):
        upload = SimpleUploadedFile("bundle.zip", blob, content_type="application/zip")
        return self.client.post("/xyn/api/artifacts/packages/import", data={"file": upload})

    def _import_generated_artifacts(self, blob: bytes):
        upload = SimpleUploadedFile("bundle.zip", blob, content_type="application/zip")
        return self.client.post(
            f"/xyn/api/artifacts/import?workspace_id={self.workspace.id}",
            data={"file": upload},
        )

    def _grant_debug_view(self):
        RoleBinding.objects.get_or_create(
            user_identity=self.identity,
            scope_kind="platform",
            role="platform_admin",
        )

    def test_manifest_validation_rejects_invalid_package_version(self):
        blob = self._package_blob(
            artifacts=[{"type": "app_shell", "slug": "ems-app", "version": "1.0.0", "content": {}}],
            package_version="invalid",
        )
        response = self._import_package(blob)
        self.assertEqual(response.status_code, 400)
        self.assertIn("package_version", json.dumps(response.json()))

    def test_checksum_verification_rejects_mismatch(self):
        blob = self._package_blob(
            artifacts=[{"type": "app_shell", "slug": "ems-app", "version": "1.0.0", "content": {}}],
            mutate_checksums=True,
        )
        response = self._import_package(blob)
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertIn("checksum mismatch", " ".join(payload.get("details") or []))

    def test_generated_artifact_import_alias_is_idempotent(self):
        blob = self._package_blob(
            artifacts=[
                {
                    "type": "application",
                    "slug": "app.net-inventory",
                    "version": "0.0.1-dev",
                    "title": "Generated Network Inventory",
                    "content": {
                        "artifact": {
                            "id": "app.net-inventory",
                            "type": "application",
                            "slug": "app.net-inventory",
                            "version": "0.0.1-dev",
                            "generated": True,
                        },
                        "capability": {"visibility": "capabilities", "label": "Generated Network Inventory"},
                        "suggestions": [{"id": "show-devices", "prompt": "Show devices"}],
                        "surfaces": {"manage": [{"label": "Workbench", "path": "/app/workbench"}]},
                    },
                }
            ],
            package_name="app.net-inventory",
            package_version="0.0.1-dev",
        )
        first = self._import_generated_artifacts(blob)
        self.assertEqual(first.status_code, 200, first.content.decode())
        self.assertTrue(
            Artifact.objects.filter(slug="app.net-inventory", package_version="0.0.1-dev").exists()
        )
        artifact = Artifact.objects.get(slug="app.net-inventory", package_version="0.0.1-dev")
        self.assertEqual(str(artifact.workspace_id), str(self.workspace.id))

        second = self._import_generated_artifacts(blob)
        self.assertEqual(second.status_code, 200, second.content.decode())
        payload = second.json()
        self.assertFalse(payload["created"])
        self.assertEqual(
            Artifact.objects.filter(slug="app.net-inventory", package_version="0.0.1-dev").count(),
            1,
        )
        application_rows = Application.objects.filter(
            workspace=self.workspace,
            metadata_json__generated_artifact_key="net-inventory",
        )
        self.assertEqual(application_rows.count(), 1)
        app = application_rows.first()
        self.assertIsNotNone(app)
        self.assertEqual(ApplicationArtifactMembership.objects.filter(application=app).count(), 1)

    def test_install_maps_canonical_git_provenance_and_source_refs_for_xyn_api(self):
        blob = self._package_blob(
            artifacts=[
                {
                    "type": "app_shell",
                    "slug": "xyn-api",
                    "version": "1.2.3",
                    "title": "xyn-api",
                    "content": {"entrypoint": "xyn_orchestrator.xyn_api"},
                    "metadata": {
                        "manifest_ref": "xyn-api/artifact.manifest.json",
                        "provenance": {
                            "source": {
                                "kind": "git",
                                "repo_key": "xyn-platform",
                                "repo_url": "https://github.com/xyence/xyn-platform",
                                "commit_sha": "ABCDEF0123456789ABCDEF0123456789ABCDEF01",
                                "branch_hint": "develop",
                                "monorepo_subpath": "services/xyn-api/backend",
                                "manifest_ref": "xyn-api/artifact.manifest.json",
                            }
                        },
                    },
                }
            ],
            package_name="xyn-api",
            package_version="1.2.3",
        )
        imported = self._import_package(blob)
        self.assertEqual(imported.status_code, 200, imported.content.decode())
        package_id = imported.json()["package"]["id"]
        package = ArtifactPackage.objects.get(id=package_id)
        receipt = artifact_packages.install_package(
            package,
            installed_by=self.user,
            target_workspace=self.workspace,
        )
        self.assertEqual(receipt.status, "success")

        artifact = Artifact.objects.get(workspace=self.workspace, type__slug="app_shell", slug="xyn-api")
        provenance = artifact.provenance_json if isinstance(artifact.provenance_json, dict) else {}
        self.assertEqual(provenance.get("kind"), "git")
        self.assertEqual(provenance.get("repo_key"), "xyn-platform")
        self.assertEqual(provenance.get("repo_url"), "https://github.com/xyence/xyn-platform")
        self.assertEqual(provenance.get("commit_sha"), "abcdef0123456789abcdef0123456789abcdef01")
        self.assertEqual(provenance.get("branch_hint"), "develop")
        self.assertEqual(provenance.get("monorepo_subpath"), "services/xyn-api/backend")
        self.assertEqual(provenance.get("manifest_ref"), "xyn-api/artifact.manifest.json")
        self.assertEqual(artifact.source_ref_type, "GitSource")
        self.assertIn("xyn-platform", str(artifact.source_ref_id or ""))

    def test_workspace_artifact_detail_returns_canonical_git_provenance(self):
        blob = self._package_blob(
            artifacts=[
                {
                    "type": "app_shell",
                    "slug": "xyn-api",
                    "version": "2.0.0",
                    "title": "xyn-api",
                    "content": {"entrypoint": "xyn_orchestrator.xyn_api"},
                    "metadata": {
                        "provenance": {
                            "source": {
                                "kind": "git",
                                "repo_key": "xyn-platform",
                                "repo_url": "https://github.com/xyence/xyn-platform",
                                "commit_sha": "0123456789abcdef0123456789abcdef01234567",
                                "branch_hint": "main",
                                "monorepo_subpath": "services/xyn-api/backend",
                                "manifest_ref": "xyn-api/artifact.manifest.json",
                            }
                        }
                    },
                }
            ],
            package_name="xyn-api",
            package_version="2.0.0",
        )
        imported = self._import_package(blob)
        self.assertEqual(imported.status_code, 200, imported.content.decode())
        package_id = imported.json()["package"]["id"]

        package = ArtifactPackage.objects.get(id=package_id)
        receipt = artifact_packages.install_package(
            package,
            installed_by=self.user,
            target_workspace=self.workspace,
        )
        self.assertEqual(receipt.status, "success")

        artifact = Artifact.objects.get(workspace=self.workspace, type__slug="app_shell", slug="xyn-api")
        WorkspaceMembership.objects.get_or_create(
            workspace=artifact.workspace,
            user_identity=self.identity,
            defaults={"role": "admin", "termination_authority": True},
        )
        detail = self.client.get(f"/xyn/api/workspaces/{artifact.workspace_id}/artifacts/{artifact.id}")
        self.assertEqual(detail.status_code, 200, detail.content.decode())
        payload = detail.json()
        provenance = payload.get("provenance_json") if isinstance(payload.get("provenance_json"), dict) else {}
        self.assertEqual(provenance.get("kind"), "git")
        self.assertEqual(provenance.get("repo_key"), "xyn-platform")
        self.assertEqual(provenance.get("commit_sha"), "0123456789abcdef0123456789abcdef01234567")

    def test_export_runtime_artifact_package_emits_canonical_git_provenance(self):
        module_type, _ = ArtifactType.objects.get_or_create(slug="module", defaults={"name": "Module"})
        artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=module_type,
            title="xyn-api",
            slug="xyn-api",
            status="published",
            package_version="1.0.0",
            scope_json={"manifest_ref": "registry/modules/xyn-api.artifact.manifest.json"},
            provenance_json={"source_system": "seed-kernel", "source_id": "xyn-api"},
            source_ref_type="",
            source_ref_id="",
        )
        ArtifactRevision.objects.create(
            artifact=artifact,
            revision_number=1,
            created_by=self.identity,
            content_json={"entrypoint": "xyn_orchestrator.xyn_api"},
        )

        with mock.patch.dict("os.environ", {"XYN_RUNTIME_SOURCE_COMMIT_SHA": "931dd41"}, clear=False):
            package_blob = artifact_packages.export_artifact_package(
                root_artifact=artifact,
                package_name="xyn-api",
                package_version="1.0.0",
            )

        artifact.refresh_from_db()
        self.assertEqual(artifact.source_ref_type, "GitSource")
        self.assertEqual(artifact.source_ref_id, "xyn-platform|services/xyn-api/backend|931dd41")
        with zipfile.ZipFile(io.BytesIO(package_blob), "r") as archive:
            artifact_payload = json.loads(archive.read("artifacts/module/xyn-api/1.0.0/artifact.json").decode("utf-8"))
        provenance = ((artifact_payload.get("metadata") or {}).get("provenance") or {})
        source = provenance.get("source") if isinstance(provenance.get("source"), dict) else {}
        self.assertEqual(source.get("kind"), "git")
        self.assertEqual(source.get("repo_key"), "xyn-platform")
        self.assertEqual(source.get("repo_url"), "https://github.com/Xyence/xyn-platform")
        self.assertEqual(source.get("monorepo_subpath"), "services/xyn-api/backend")
        self.assertEqual(source.get("commit_sha"), "931dd41")

    def test_export_runtime_artifact_package_rejects_missing_git_commit(self):
        module_type, _ = ArtifactType.objects.get_or_create(slug="module", defaults={"name": "Module"})
        artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=module_type,
            title="xyn-api",
            slug="xyn-api",
            status="published",
            package_version="1.0.1",
            scope_json={"manifest_ref": "registry/modules/xyn-api.artifact.manifest.json"},
            provenance_json={
                "source_system": "seed-kernel",
                "source_id": "xyn-api",
                "source": {
                    "kind": "git",
                    "repo_key": "xyn-platform",
                    "repo_url": "https://github.com/Xyence/xyn-platform",
                    "monorepo_subpath": "services/xyn-api/backend",
                },
            },
        )
        ArtifactRevision.objects.create(
            artifact=artifact,
            revision_number=1,
            created_by=self.identity,
            content_json={"entrypoint": "xyn_orchestrator.xyn_api"},
        )

        with mock.patch.dict(
            "os.environ",
            {"XYN_RUNTIME_SOURCE_COMMIT_SHA": "", "XYN_RUNTIME_REPO_MAP": "{}", "XYN_API_IMAGE": "xyn-api:latest"},
            clear=False,
        ):
            with mock.patch("xyn_orchestrator.runtime_artifact_provenance._repo_root_candidates", return_value=[]):
                with self.assertRaises(artifact_packages.ArtifactPackageValidationError) as exc:
                    artifact_packages.export_artifact_package(
                        root_artifact=artifact,
                        package_name="xyn-api",
                        package_version="1.0.1",
                    )

        self.assertIn("source.commit_sha", " ".join(exc.exception.errors))

    def test_generated_artifact_import_preserves_manifest_summary_in_workspace_registry(self):
        blob = self._package_blob(
            artifacts=[
                {
                    "type": "application",
                    "slug": "app.net-inventory",
                    "version": "0.0.1-dev",
                    "title": "Generated Network Inventory",
                    "content": {
                        "artifact": {
                            "id": "app.net-inventory",
                            "type": "application",
                            "slug": "app.net-inventory",
                            "version": "0.0.1-dev",
                            "generated": True,
                        },
                        "capability": {
                            "visibility": "capabilities",
                            "label": "Generated Network Inventory",
                            "description": "Generated application capability installed through the artifact registry.",
                        },
                        "suggestions": [
                            {
                                "id": "show-devices",
                                "name": "Show Devices",
                                "prompt": "Show devices",
                                "visibility": ["capability", "palette"],
                            }
                        ],
                        "surfaces": {
                            "manage": [{"label": "Workbench", "path": "/app/workbench", "order": 100}],
                            "docs": [{"label": "Docs", "path": "/app/workbench", "order": 1000}],
                        },
                    },
                }
            ],
            package_name="app.net-inventory",
            package_version="0.0.1-dev",
        )
        imported = self._import_generated_artifacts(blob)
        self.assertEqual(imported.status_code, 200, imported.content.decode())

        artifact = Artifact.objects.get(slug="app.net-inventory", package_version="0.0.1-dev")
        workspace = Workspace.objects.create(slug="generated-netinv", name="Generated NetInv")
        WorkspaceMembership.objects.create(workspace=workspace, user_identity=self.identity, role="admin", termination_authority=True)
        WorkspaceArtifactBinding.objects.create(
            workspace=workspace,
            artifact=artifact,
            installed_state="installed",
            enabled=True,
        )

        response = self.client.get(f"/xyn/api/workspaces/{workspace.id}/artifacts")
        self.assertEqual(response.status_code, 200, response.content.decode())
        rows = response.json().get("artifacts", [])
        match = next(row for row in rows if row.get("slug") == "app.net-inventory")
        self.assertEqual((match.get("capability") or {}).get("visibility"), "capabilities")
        self.assertEqual(str((match.get("capability") or {}).get("label") or ""), "Generated Network Inventory")
        self.assertEqual(len(match.get("suggestions") or []), 1)
        self.assertEqual(str((match.get("suggestions") or [])[0].get("prompt") or ""), "Show devices")

    def test_generated_artifact_import_accepts_application_and_policy_bundle_slugs(self):
        blob = self._package_blob(
            artifacts=[
                {
                    "type": "application",
                    "slug": "app.team-lunch-poll",
                    "version": "0.0.1-dev",
                    "title": "Team Lunch Poll",
                    "content": {"artifact": {"id": "app.team-lunch-poll", "type": "application", "slug": "app.team-lunch-poll", "version": "0.0.1-dev"}},
                },
                {
                    "type": "policy_bundle",
                    "slug": "policy.team-lunch-poll",
                    "version": "0.0.1-dev",
                    "title": "Team Lunch Poll Policy Bundle",
                    "content": {
                        "schema_version": "xyn.policy_bundle.v0",
                        "bundle_id": "policy.team-lunch-poll",
                        "app_slug": "team-lunch-poll",
                        "workspace_id": "workspace-1",
                        "title": "Team Lunch Poll Policy Bundle",
                        "scope": {"artifact_slug": "app.team-lunch-poll", "applies_to": ["generated_runtime"]},
                        "ownership": {"owner_kind": "generated_application", "editable": True, "source": "generated_from_prompt"},
                        "policy_families": ["validation_policies"],
                        "policies": {
                            "validation_policies": [],
                            "relation_constraints": [],
                            "transition_policies": [],
                            "derived_policies": [],
                            "trigger_policies": [],
                        },
                        "configurable_parameters": [],
                        "explanation": {"summary": "Generated policy scaffold.", "coverage": {"documented_policy_count": 0}, "future_capabilities": ["render_policy_bundle"]},
                    },
                },
            ],
            package_name="app.team-lunch-poll",
            package_version="0.0.1-dev",
        )
        imported = self._import_generated_artifacts(blob)

        self.assertEqual(imported.status_code, 200, imported.content.decode())
        self.assertTrue(Artifact.objects.filter(slug="app.team-lunch-poll").exists())
        self.assertTrue(Artifact.objects.filter(slug="policy.team-lunch-poll").exists())
        app_artifact = Artifact.objects.get(slug="app.team-lunch-poll")
        policy_artifact = Artifact.objects.get(slug="policy.team-lunch-poll")
        self.assertEqual(str(app_artifact.workspace_id), str(self.workspace.id))
        self.assertEqual(str(policy_artifact.workspace_id), str(self.workspace.id))
        self.assertEqual(str(app_artifact.type).lower(), "application")
        self.assertEqual(str(app_artifact.slug), "app.team-lunch-poll")
        application = Application.objects.get(
            workspace=self.workspace,
            metadata_json__generated_artifact_key="team-lunch-poll",
        )
        self.assertEqual(application.name, "Team Lunch Poll")
        memberships = list(
            ApplicationArtifactMembership.objects.filter(application=application).select_related("artifact").order_by("sort_order", "created_at")
        )
        self.assertEqual(len(memberships), 2)
        self.assertEqual({member.artifact.slug for member in memberships}, {"app.team-lunch-poll", "policy.team-lunch-poll"})
        app_membership = next(member for member in memberships if member.artifact.slug == "app.team-lunch-poll")
        policy_membership = next(member for member in memberships if member.artifact.slug == "policy.team-lunch-poll")
        self.assertEqual(app_membership.role, "primary_ui")
        self.assertEqual(policy_membership.role, "supporting")
        self.assertEqual(str(policy_artifact.workspace_id), str(application.workspace_id))

    def test_generated_artifact_import_handles_long_application_slug_without_source_ref_overflow(self):
        app_slug = "app.real-estate-deal-finder-fidelity-validation-4"
        blob = self._package_blob(
            artifacts=[
                {
                    "type": "application",
                    "slug": app_slug,
                    "version": "0.0.1-dev",
                    "title": "Real Estate Deal Finder",
                    "content": {
                        "artifact": {
                            "id": app_slug,
                            "type": "application",
                            "slug": app_slug,
                            "version": "0.0.1-dev",
                        }
                    },
                },
                {
                    "type": "policy_bundle",
                    "slug": "policy.real-estate-deal-finder-fidelity-validation-4",
                    "version": "0.0.1-dev",
                    "title": "Real Estate Deal Finder Policy Bundle",
                    "content": {
                        "schema_version": "xyn.policy_bundle.v0",
                        "bundle_id": "policy.real-estate-deal-finder-fidelity-validation-4",
                        "app_slug": "real-estate-deal-finder-fidelity-validation-4",
                        "workspace_id": "workspace-1",
                        "title": "Real Estate Deal Finder Policy Bundle",
                        "scope": {"artifact_slug": app_slug, "applies_to": ["generated_runtime"]},
                        "ownership": {"owner_kind": "generated_application", "editable": True, "source": "generated_from_prompt"},
                        "policy_families": ["validation_policies"],
                        "policies": {
                            "validation_policies": [],
                            "relation_constraints": [],
                            "transition_policies": [],
                            "derived_policies": [],
                            "trigger_policies": [],
                        },
                        "configurable_parameters": [],
                        "explanation": {"summary": "Generated policy scaffold.", "coverage": {"documented_policy_count": 0}, "future_capabilities": ["render_policy_bundle"]},
                    },
                },
            ],
            package_name=app_slug,
            package_version="0.0.1-dev",
        )
        imported = self._import_generated_artifacts(blob)
        self.assertEqual(imported.status_code, 200, imported.content.decode())
        payload = imported.json()
        package_id = payload["package"]["id"]
        imported_rows = payload.get("artifacts") or []
        app_row = next(
            (row for row in imported_rows if str(row.get("slug") or "").strip() == app_slug),
            None,
        )
        self.assertIsNotNone(app_row, imported.content.decode())
        artifact_qs = Artifact.objects.filter(
            workspace=self.workspace,
            slug=app_slug,
            package_version="0.0.1-dev",
        )
        self.assertEqual(artifact_qs.count(), 1, imported.content.decode())
        artifact = artifact_qs.first()
        self.assertIsNotNone(artifact)
        self.assertEqual(str(artifact.id), str(app_row["id"]))
        self.assertEqual(str(artifact.workspace_id), str(self.workspace.id))
        self.assertTrue(str(artifact.source_ref_id or "").startswith(f"{package_id}:"))
        self.assertLessEqual(len(artifact.source_ref_id or ""), 120)

    def test_legacy_generated_solution_backfill_links_deterministic_groups_and_is_idempotent(self):
        workspace = Workspace.objects.create(slug=f"legacy-{uuid.uuid4().hex[:8]}", name="Legacy Solution Workspace")
        app_type, _ = ArtifactType.objects.get_or_create(slug="application", defaults={"name": "Application"})
        policy_type, _ = ArtifactType.objects.get_or_create(slug="policy_bundle", defaults={"name": "Policy Bundle"})

        app_artifact = Artifact.objects.create(
            workspace=workspace,
            type=app_type,
            title="Real Estate Deal Finder",
            slug="app.real-estate-deal-finder",
            summary="Generated app artifact",
            status="active",
            artifact_state="canonical",
        )
        policy_artifact = Artifact.objects.create(
            workspace=workspace,
            type=policy_type,
            title="Real Estate Deal Finder Policy Bundle",
            slug="policy.real-estate-deal-finder",
            summary="Generated policy bundle",
            status="active",
            artifact_state="canonical",
        )

        first = xyn_api._backfill_legacy_generated_solution_memberships()
        self.assertEqual(first["groups_backfilled"], 1)
        self.assertEqual(first["applications_created"], 1)
        self.assertEqual(first["memberships_created"], 2)

        application = Application.objects.get(
            workspace=workspace,
            metadata_json__generated_artifact_key="real-estate-deal-finder",
        )
        self.assertEqual(application.source_factory_key, "legacy_solution_backfill")
        self.assertEqual(application.metadata_json.get("origin"), "legacy_deterministic_backfill")
        memberships = list(
            ApplicationArtifactMembership.objects.filter(application=application).select_related("artifact").order_by("sort_order", "created_at")
        )
        self.assertEqual([member.artifact_id for member in memberships], [app_artifact.id, policy_artifact.id])
        self.assertEqual([member.role for member in memberships], ["primary_ui", "supporting"])

        second = xyn_api._backfill_legacy_generated_solution_memberships()
        self.assertEqual(second["groups_backfilled"], 0)
        self.assertEqual(Application.objects.filter(workspace=workspace, metadata_json__generated_artifact_key="real-estate-deal-finder").count(), 1)
        self.assertEqual(ApplicationArtifactMembership.objects.filter(application=application).count(), 2)

    def test_legacy_generated_solution_backfill_skips_conflicts_and_non_solution_scopes(self):
        workspace = Workspace.objects.create(slug=f"legacy-skip-{uuid.uuid4().hex[:8]}", name="Legacy Skip Workspace")
        app_type, _ = ArtifactType.objects.get_or_create(slug="application", defaults={"name": "Application"})

        ignored_artifact = Artifact.objects.create(
            workspace=workspace,
            type=app_type,
            title="Platform Scoped App Artifact",
            slug="app.platform-seeded",
            scope_json={"scope_classification": "platform"},
            status="active",
            artifact_state="canonical",
        )

        conflict_artifact = Artifact.objects.create(
            workspace=workspace,
            type=app_type,
            title="Team Lunch Poll",
            slug="app.team-lunch-poll",
            status="active",
            artifact_state="canonical",
        )
        conflicting_application = Application.objects.create(
            workspace=workspace,
            name="Existing Team Lunch Poll",
            summary="existing",
            source_factory_key="manual",
            source_conversation_id="",
            status="active",
            request_objective="",
            metadata_json={"generated_artifact_key": "team-lunch-poll", "origin": "manual"},
        )
        prelinked = Artifact.objects.create(
            workspace=workspace,
            type=app_type,
            title="Prelinked",
            slug=f"app.prelinked-{uuid.uuid4().hex[:8]}",
            status="active",
            artifact_state="canonical",
        )
        ApplicationArtifactMembership.objects.create(
            workspace=workspace,
            application=conflicting_application,
            artifact=prelinked,
            role="supporting",
            responsibility_summary="existing membership makes this key ambiguous",
        )

        summary = xyn_api._backfill_legacy_generated_solution_memberships(workspace_id=str(workspace.id))
        self.assertEqual(summary["groups_backfilled"], 0)
        skipped = summary.get("skipped") or []
        reasons = {str(item.get("reason") or "") for item in skipped}
        self.assertIn("conflicting_existing_application_association", reasons)
        self.assertFalse(
            Application.objects.filter(
                workspace=workspace,
                metadata_json__generated_artifact_key="platform-seeded",
            ).exists()
        )
        self.assertFalse(
            ApplicationArtifactMembership.objects.filter(artifact=ignored_artifact).exists()
        )
        self.assertFalse(
            ApplicationArtifactMembership.objects.filter(artifact=conflict_artifact).exists()
        )

    def test_policy_bundle_artifact_type_is_importable_and_registered(self):
        blob = self._package_blob(
            artifacts=[
                {
                    "type": "policy_bundle",
                    "slug": "policy.team-lunch-poll",
                    "version": "0.0.1-dev",
                    "title": "Team Lunch Poll Policy Bundle",
                    "content": {
                        "schema_version": "xyn.policy_bundle.v0",
                        "bundle_id": "policy.team-lunch-poll",
                        "app_slug": "team-lunch-poll",
                        "workspace_id": "workspace-1",
                        "title": "Team Lunch Poll Policy Bundle",
                        "scope": {"artifact_slug": "app.team-lunch-poll", "applies_to": ["generated_runtime"]},
                        "ownership": {"owner_kind": "generated_application", "editable": True, "source": "generated_from_prompt"},
                        "policy_families": ["validation_policies"],
                        "policies": {
                            "validation_policies": [{"id": "p-1", "description": "Prevent voting on polls that are not open."}],
                            "relation_constraints": [],
                            "transition_policies": [],
                            "derived_policies": [],
                            "trigger_policies": [],
                        },
                        "configurable_parameters": [],
                        "explanation": {"summary": "Generated policy scaffold.", "coverage": {"documented_policy_count": 1}, "future_capabilities": ["render_policy_bundle"]},
                    },
                }
            ],
            package_name="policy.team-lunch-poll",
            package_version="0.0.1-dev",
        )

        imported = self._import_package(blob)
        self.assertEqual(imported.status_code, 200, imported.content.decode())
        package_id = imported.json()["package"]["id"]
        install = self.client.post(
            f"/xyn/api/artifacts/packages/{package_id}/install",
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(install.status_code, 200, install.content.decode())

        artifact = Artifact.objects.get(slug="policy.team-lunch-poll")
        self.assertEqual(artifact.type.slug, "policy_bundle")
        latest_receipt = ArtifactInstallReceipt.objects.order_by("-created_at").first()
        self.assertEqual(latest_receipt.status, "success")
        latest_config = PlatformConfigDocument.objects.order_by("-created_at", "-version").first()
        self.assertEqual(
            ((latest_config.config_json.get("policy_bundle_registry") or {}).get("policy.team-lunch-poll") or {}).get("bundle_id"),
            "policy.team-lunch-poll",
        )

    def test_validate_returns_dependency_order_and_unresolved_bindings(self):
        blob = self._package_blob(
            artifacts=[
                {
                    "type": "ui_view",
                    "slug": "ems-devices-view",
                    "version": "1.0.0",
                    "content": {"view": "list"},
                },
                {
                    "type": "app_shell",
                    "slug": "ems-shell",
                    "version": "1.0.0",
                    "content": {"routes": ["/ems/devices"]},
                    "dependencies": [{"type": "ui_view", "slug": "ems-devices-view", "version_range": "^1.0.0"}],
                    "bindings": [
                        {
                            "name": "BASE_URL",
                            "required": True,
                            "type": "url",
                            "resolution_strategy": "instance_setting",
                        }
                    ],
                },
            ]
        )
        imported = self._import_package(blob)
        self.assertEqual(imported.status_code, 200, imported.content.decode())
        package_id = imported.json()["package"]["id"]

        validate = self.client.post(
            f"/xyn/api/artifacts/packages/{package_id}/validate",
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(validate.status_code, 200)
        payload = validate.json()
        self.assertFalse(payload["valid"])
        self.assertIn("binding unresolved: BASE_URL", payload["errors"])
        plan = payload["dependency_plan"]
        self.assertEqual(plan[0]["type"], "ui_view")
        self.assertEqual(plan[1]["type"], "app_shell")

    def test_install_is_idempotent_and_upgrade_records_receipt(self):
        ArtifactBindingValue.objects.create(name="BASE_URL", binding_type="url", value="https://ems.local")

        v1_blob = self._package_blob(
            artifacts=[
                {
                    "type": "data_model",
                    "slug": "ems_device",
                    "version": "1.0.0",
                    "content": {
                        "schema": {
                            "table_name": "ems_device",
                            "columns": [
                                {"name": "id", "type": "text", "nullable": False},
                                {"name": "name", "type": "text", "nullable": False},
                            ],
                        }
                    },
                },
                {
                    "type": "app_shell",
                    "slug": "ems-shell",
                    "version": "1.0.0",
                    "content": {"routes": ["/ems/devices"]},
                    "dependencies": [{"type": "data_model", "slug": "ems_device", "version_range": "^1.0.0"}],
                    "bindings": [{"name": "BASE_URL", "required": True, "type": "url", "resolution_strategy": "instance_setting"}],
                },
            ],
            package_version="1.0.0",
        )
        imported = self._import_package(v1_blob)
        self.assertEqual(imported.status_code, 200, imported.content.decode())
        pkg_v1 = imported.json()["package"]["id"]

        install1 = self.client.post(f"/xyn/api/artifacts/packages/{pkg_v1}/install", data=json.dumps({}), content_type="application/json")
        self.assertEqual(install1.status_code, 200, install1.content.decode())
        receipt1 = install1.json()["receipt"]
        self.assertEqual(receipt1["status"], "success")

        install2 = self.client.post(f"/xyn/api/artifacts/packages/{pkg_v1}/install", data=json.dumps({}), content_type="application/json")
        self.assertEqual(install2.status_code, 200, install2.content.decode())
        receipt2 = install2.json()["receipt"]
        actions = [row.get("action") for row in receipt2.get("artifact_changes") or []]
        self.assertIn("skip", actions)
        self.assertEqual(Artifact.objects.filter(type__slug="app_shell", slug="ems-shell").count(), 1)

        v2_blob = self._package_blob(
            artifacts=[
                {
                    "type": "data_model",
                    "slug": "ems_device",
                    "version": "1.1.0",
                    "content": {
                        "schema": {
                            "table_name": "ems_device",
                            "columns": [
                                {"name": "id", "type": "text", "nullable": False},
                                {"name": "name", "type": "text", "nullable": False},
                                {"name": "status", "type": "text", "nullable": True},
                            ],
                        }
                    },
                },
                {
                    "type": "app_shell",
                    "slug": "ems-shell",
                    "version": "1.1.0",
                    "content": {"routes": ["/ems/devices", "/ems/devices/:id"]},
                    "dependencies": [{"type": "data_model", "slug": "ems_device", "version_range": "^1.1.0"}],
                    "bindings": [{"name": "BASE_URL", "required": True, "type": "url", "resolution_strategy": "instance_setting"}],
                },
            ],
            package_version="1.1.0",
        )
        imported2 = self._import_package(v2_blob)
        self.assertEqual(imported2.status_code, 200, imported2.content.decode())
        pkg_v2 = imported2.json()["package"]["id"]
        install3 = self.client.post(f"/xyn/api/artifacts/packages/{pkg_v2}/install", data=json.dumps({}), content_type="application/json")
        self.assertEqual(install3.status_code, 200, install3.content.decode())
        receipt3 = install3.json()["receipt"]
        self.assertEqual(receipt3["install_mode"], "upgrade")

        shell = Artifact.objects.get(type__slug="app_shell", slug="ems-shell")
        self.assertEqual(shell.package_version, "1.1.0")
        self.assertEqual(ArtifactPackage.objects.count(), 2)
        self.assertEqual(ArtifactInstallReceipt.objects.count(), 3)

    def test_raw_endpoints_require_artifact_debug_permission(self):
        blob = self._package_blob(
            artifacts=[{"type": "app_shell", "slug": "ems-app", "version": "1.0.0", "content": {"view": "hello"}}]
        )
        imported = self._import_package(blob)
        self.assertEqual(imported.status_code, 200, imported.content.decode())
        package_id = imported.json()["package"]["id"]

        response = self.client.get(f"/xyn/api/artifacts/packages/{package_id}/raw/manifest")
        self.assertEqual(response.status_code, 403)

    def test_package_raw_tree_and_file_preview(self):
        self._grant_debug_view()
        blob = self._package_blob(
            artifacts=[{"type": "app_shell", "slug": "ems-app", "version": "1.0.0", "content": {"view": "hello"}}]
        )
        imported = self._import_package(blob)
        self.assertEqual(imported.status_code, 200, imported.content.decode())
        package_id = imported.json()["package"]["id"]

        tree = self.client.get(f"/xyn/api/artifacts/packages/{package_id}/raw/tree", {"path": "/"})
        self.assertEqual(tree.status_code, 200, tree.content.decode())
        entries = tree.json().get("entries") or []
        self.assertTrue(any(entry.get("name") == "manifest.json" for entry in entries))

        preview = self.client.get(
            f"/xyn/api/artifacts/packages/{package_id}/raw/file",
            {"path": "/manifest.json"},
        )
        self.assertEqual(preview.status_code, 200, preview.content.decode())

    def test_install_registers_surfaces_and_runtime_roles(self):
        self._grant_debug_view()
        blob = self._package_blob(
            artifacts=[
                {
                    "type": "app_shell",
                    "slug": "ems-surfaces",
                    "version": "1.0.0",
                    "content": {"view": "hello"},
                    "surfaces": [
                        {
                            "key": "dashboard",
                            "title": "EMS Dashboard",
                            "description": "Ops dashboard",
                            "surface_kind": "dashboard",
                            "route": "/app/a/ems/dashboard",
                            "nav_visibility": "always",
                            "nav_label": "EMS Dashboard",
                            "nav_icon": "Layers",
                            "nav_group": "Build",
                            "renderer": {"type": "ui_component_ref", "payload": {"component_key": "articles.index"}},
                            "context": {"required": [], "bindings": {}},
                            "permissions": {"required_roles": ["platform_admin"]},
                            "sort_order": 5,
                        }
                    ],
                    "runtime_roles": [
                        {"role_kind": "route_provider", "enabled": True, "spec": {"routes": ["/app/a/ems/dashboard"]}}
                    ],
                }
            ]
        )
        imported = self._import_package(blob)
        self.assertEqual(imported.status_code, 200, imported.content.decode())
        package_id = imported.json()["package"]["id"]

        install = self.client.post(f"/xyn/api/artifacts/packages/{package_id}/install", data=json.dumps({}), content_type="application/json")
        self.assertEqual(install.status_code, 200, install.content.decode())

        artifact = Artifact.objects.get(type__slug="app_shell", slug="ems-surfaces")
        surface = ArtifactSurface.objects.get(artifact=artifact, key="dashboard")
        runtime_role = ArtifactRuntimeRole.objects.get(artifact=artifact, role_kind="route_provider")
        self.assertEqual(surface.route, "/app/a/ems/dashboard")
        self.assertTrue(runtime_role.enabled)

    def test_install_registers_generated_dashboard_and_editor_surfaces(self):
        self._grant_debug_view()
        workspace = Workspace.objects.create(slug="deal-finder-shell", name="Deal Finder Shell")
        WorkspaceMembership.objects.create(workspace=workspace, user_identity=self.identity, role="admin", termination_authority=True)
        blob = self._package_blob(
            artifacts=[
                {
                    "type": "application",
                    "slug": "app.generated-deal-finder",
                    "version": "0.0.1-dev",
                    "content": {"artifact": {"id": "app.generated-deal-finder"}, "surfaces": {"manage": [], "docs": [], "nav": []}},
                    "surfaces": [
                        {
                            "key": "campaigns-list",
                            "title": "Campaigns",
                            "surface_kind": "dashboard",
                            "route": "/app/campaigns",
                            "nav_visibility": "always",
                            "nav_label": "Campaigns",
                            "nav_group": "apps",
                            "renderer": {"type": "generic_dashboard"},
                            "sort_order": 100,
                        },
                        {
                            "key": "campaigns-create",
                            "title": "Create Campaign",
                            "surface_kind": "editor",
                            "route": "/app/campaigns/new",
                            "nav_visibility": "always",
                            "nav_label": "Create Campaign",
                            "nav_group": "apps",
                            "renderer": {"type": "generic_editor", "payload": {"shell_renderer_key": "campaign_map_workflow", "mode": "create"}},
                            "sort_order": 101,
                        },
                    ],
                }
            ]
        )
        imported = self._import_package(blob)
        self.assertEqual(imported.status_code, 200, imported.content.decode())
        package_id = imported.json()["package"]["id"]
        install = self.client.post(f"/xyn/api/artifacts/packages/{package_id}/install", data=json.dumps({}), content_type="application/json")
        self.assertEqual(install.status_code, 200, install.content.decode())

        artifact = Artifact.objects.get(type__slug="application", slug="app.generated-deal-finder")
        WorkspaceArtifactBinding.objects.create(
            workspace=workspace,
            artifact=artifact,
            installed_state="installed",
            enabled=True,
        )
        rows = list(ArtifactSurface.objects.filter(artifact=artifact).order_by("sort_order"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].surface_kind, "dashboard")
        self.assertEqual(rows[0].route, "/app/campaigns")
        self.assertEqual((rows[0].renderer or {}).get("type"), "generic_dashboard")
        self.assertEqual(rows[1].surface_kind, "editor")
        self.assertEqual((rows[1].renderer or {}).get("type"), "generic_editor")
        self.assertEqual(((rows[1].renderer or {}).get("payload") or {}).get("shell_renderer_key"), "campaign_map_workflow")

        nav = self.client.get(f"/xyn/api/artifact-surfaces/nav?workspace_id={workspace.id}")
        self.assertEqual(nav.status_code, 200, nav.content.decode())
        nav_rows = nav.json().get("surfaces") or []
        nav_labels = [str(item.get("nav_label") or "") for item in nav_rows if isinstance(item, dict)]
        self.assertIn("Campaigns", nav_labels)
        self.assertIn("Create Campaign", nav_labels)

    def test_install_prunes_obsolete_generated_app_compat_surfaces(self):
        self._grant_debug_view()
        blob = self._package_blob(
            artifacts=[
                {
                    "type": "application",
                    "slug": "app.generated-legacy-surfaces",
                    "version": "0.0.1-dev",
                    "content": {"artifact": {"id": "app.generated-legacy-surfaces"}},
                    "surfaces": [
                        {
                            "key": "app-home",
                            "title": "App Home",
                            "surface_kind": "dashboard",
                            "route": "/app",
                            "nav_visibility": "always",
                            "renderer": {"type": "generic_dashboard"},
                        },
                        {
                            "key": "signals-list",
                            "title": "Signals",
                            "surface_kind": "dashboard",
                            "route": "/app/signals",
                            "nav_visibility": "always",
                            "renderer": {"type": "generic_dashboard"},
                        },
                        {
                            "key": "campaigns-list",
                            "title": "Campaigns",
                            "surface_kind": "dashboard",
                            "route": "/app/campaigns",
                            "nav_visibility": "always",
                            "renderer": {"type": "generic_dashboard"},
                        },
                        {
                            "key": "campaigns-create",
                            "title": "Create Campaign",
                            "surface_kind": "editor",
                            "route": "/app/campaigns/new",
                            "nav_visibility": "always",
                            "renderer": {
                                "type": "generic_editor",
                                "payload": {"shell_renderer_key": "campaign_map_workflow", "mode": "create"},
                            },
                        },
                    ],
                }
            ]
        )
        imported = self._import_package(blob)
        self.assertEqual(imported.status_code, 200, imported.content.decode())
        package_id = imported.json()["package"]["id"]
        install = self.client.post(f"/xyn/api/artifacts/packages/{package_id}/install", data=json.dumps({}), content_type="application/json")
        self.assertEqual(install.status_code, 200, install.content.decode())

        artifact = Artifact.objects.get(type__slug="application", slug="app.generated-legacy-surfaces")
        routes = set(ArtifactSurface.objects.filter(artifact=artifact).values_list("route", flat=True))
        self.assertEqual(routes, {"/app/campaigns", "/app/campaigns/new"})

    def test_export_package_omits_obsolete_generated_app_compat_surfaces(self):
        self._grant_debug_view()
        artifact_type, _ = ArtifactType.objects.get_or_create(slug="application", defaults={"name": "Application"})
        artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Legacy Surface Artifact",
            slug=f"app.legacy-export-{uuid.uuid4().hex[:8]}",
            status="active",
            visibility="private",
            package_version="0.0.1-dev",
        )
        ArtifactRevision.objects.create(
            artifact=artifact,
            revision_number=1,
            content_json={"content": {"artifact": {"id": artifact.slug}}},
            created_by=None,
        )
        ArtifactSurface.objects.create(
            artifact=artifact,
            key="app-root",
            title="App Root",
            surface_kind="dashboard",
            route="/app",
            nav_visibility="always",
            renderer={"type": "generic_dashboard"},
        )
        ArtifactSurface.objects.create(
            artifact=artifact,
            key="campaigns-list",
            title="Campaigns",
            surface_kind="dashboard",
            route="/app/campaigns",
            nav_visibility="always",
            renderer={"type": "generic_dashboard"},
        )
        ArtifactSurface.objects.create(
            artifact=artifact,
            key="campaigns-create",
            title="Create Campaign",
            surface_kind="editor",
            route="/app/campaigns/new",
            nav_visibility="always",
            renderer={"type": "generic_editor", "payload": {"shell_renderer_key": "campaign_map_workflow", "mode": "create"}},
        )

        export_response = self.client.post(
            f"/xyn/api/artifacts/{artifact.id}/export-package",
            data=json.dumps({"package_name": f"{artifact.slug}-bundle", "package_version": "0.0.1-dev"}),
            content_type="application/json",
        )
        self.assertEqual(export_response.status_code, 200)

        with zipfile.ZipFile(io.BytesIO(export_response.content), "r") as archive:
            surfaces_path = f"artifacts/application/{artifact.slug}/0.0.1-dev/surfaces.json"
            surfaces_payload = json.loads(archive.read(surfaces_path).decode("utf-8"))
        routes = {str(row.get("route") or "") for row in surfaces_payload if isinstance(row, dict)}
        self.assertNotIn("/app", routes)
        self.assertIn("/app/campaigns", routes)
        self.assertIn("/app/campaigns/new", routes)

    def test_export_import_preserves_source_created_at_when_known(self):
        self._grant_debug_view()
        artifact_type, _ = ArtifactType.objects.get_or_create(slug="application", defaults={"name": "Application"})
        source_created_at = timezone.now() - timezone.timedelta(days=14)
        artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=artifact_type,
            title="Portable Source Created App",
            slug=f"app.source-created-{uuid.uuid4().hex[:8]}",
            status="active",
            visibility="private",
            package_version="0.2.0",
            source_created_at=source_created_at,
        )

        ArtifactRevision.objects.create(
            artifact=artifact,
            revision_number=1,
            content_json={"content": {"artifact": {"id": artifact.slug}}},
            created_by=None,
        )

        export_response = self.client.post(
            f"/xyn/api/artifacts/{artifact.id}/export-package",
            data=json.dumps({"package_name": f"{artifact.slug}-bundle", "package_version": "0.2.0"}),
            content_type="application/json",
        )
        self.assertEqual(export_response.status_code, 200)

        imported = self._import_package(export_response.content)
        self.assertEqual(imported.status_code, 200, imported.content.decode())
        package_id = imported.json()["package"]["id"]

        install = self.client.post(
            f"/xyn/api/artifacts/packages/{package_id}/install",
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(install.status_code, 200, install.content.decode())

        installed = Artifact.objects.get(type=artifact_type, slug=artifact.slug)
        self.assertIsNotNone(installed.source_created_at)
        self.assertEqual(
            installed.source_created_at.astimezone(dt.timezone.utc).isoformat(),
            source_created_at.astimezone(dt.timezone.utc).isoformat(),
        )

    def test_surface_resolve_endpoint_matches_declared_route(self):
        self._grant_debug_view()
        blob = self._package_blob(
            artifacts=[
                {
                    "type": "app_shell",
                    "slug": "ems-router",
                    "version": "1.0.0",
                    "content": {"view": "hello"},
                    "surfaces": [
                        {
                            "key": "detail",
                            "title": "EMS Detail",
                            "surface_kind": "editor",
                            "route": "/app/a/ems/:artifactId",
                            "nav_visibility": "hidden",
                            "renderer": {"type": "ui_component_ref", "payload": {"component_key": "articles.draft_editor"}},
                        }
                    ],
                }
            ]
        )
        imported = self._import_package(blob)
        package_id = imported.json()["package"]["id"]
        install = self.client.post(f"/xyn/api/artifacts/packages/{package_id}/install", data=json.dumps({}), content_type="application/json")
        self.assertEqual(install.status_code, 200, install.content.decode())
        artifact = Artifact.objects.get(type__slug="app_shell", slug="ems-router")

        resolved = self.client.get("/xyn/api/artifact-surfaces/resolve", {"path": f"/app/a/ems/{artifact.id}"})
        self.assertEqual(resolved.status_code, 200, resolved.content.decode())
        payload = resolved.json()
        self.assertEqual(payload.get("surface", {}).get("key"), "detail")
        self.assertEqual(payload.get("params", {}).get("artifactId"), str(artifact.id))
        preview = self.client.get(f"/xyn/api/artifacts/packages/{package_id}/raw/file", {"path": "/manifest.json"})
        self.assertEqual(preview.status_code, 200, preview.content.decode())
        payload = preview.json()
        self.assertTrue(payload.get("inline"))
        self.assertIn("format_version", str(payload.get("content") or ""))

    def test_installed_artifact_raw_endpoints(self):
        self._grant_debug_view()
        ArtifactBindingValue.objects.create(name="BASE_URL", binding_type="url", value="https://ems.local")
        blob = self._package_blob(
            artifacts=[
                {
                    "type": "app_shell",
                    "slug": "ems-shell",
                    "version": "1.0.0",
                    "content": {"routes": ["/ems/devices"]},
                    "bindings": [{"name": "BASE_URL", "required": True, "type": "url", "resolution_strategy": "instance_setting"}],
                }
            ],
            package_version="1.0.0",
        )
        imported = self._import_package(blob)
        self.assertEqual(imported.status_code, 200, imported.content.decode())
        package_id = imported.json()["package"]["id"]
        installed = self.client.post(f"/xyn/api/artifacts/packages/{package_id}/install", data=json.dumps({}), content_type="application/json")
        self.assertEqual(installed.status_code, 200, installed.content.decode())

        artifact = Artifact.objects.get(type__slug="app_shell", slug="ems-shell")
        metadata = self.client.get(f"/xyn/api/artifacts/{artifact.id}/raw/metadata")
        self.assertEqual(metadata.status_code, 200, metadata.content.decode())
        self.assertEqual(metadata.json().get("artifact", {}).get("slug"), "ems-shell")

        listing = self.client.get(f"/xyn/api/artifacts/{artifact.id}/raw/files", {"path": "/"})
        self.assertEqual(listing.status_code, 200, listing.content.decode())
        entries = listing.json().get("entries") or []
        self.assertTrue(any(entry.get("name") == "artifact.json" for entry in entries))

        invalid = self.client.get(f"/xyn/api/artifacts/{artifact.id}/raw/files", {"path": "../"})
        self.assertEqual(invalid.status_code, 400)
