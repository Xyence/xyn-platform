from __future__ import annotations

import io
import json
import tempfile
import uuid
import zipfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from xyn_orchestrator.artifact_packages import import_package_blob_idempotent
from xyn_orchestrator.models import (
    Application,
    ApplicationArtifactMembership,
    Artifact,
    Workspace,
    WorkspaceArtifactBinding,
    WorkspaceMembership,
    UserIdentity,
)
from xyn_orchestrator.solution_bundles import SOLUTION_BUNDLE_SCHEMA, SolutionBundleError, load_solution_bundle_from_source
from xyn_orchestrator.solution_bundles import bootstrap_install_solution_bundles_from_env
from xyn_orchestrator.xyn_api import application_activate


def _mock_json_response(status_code: int, payload: dict) -> mock.Mock:
    body = json.dumps(payload)
    response = mock.Mock()
    response.status_code = status_code
    response.content = body.encode("utf-8")
    response.text = body
    response.json.return_value = payload
    return response


class SolutionBundleInstallApiTests(TestCase):
    def setUp(self) -> None:
        suffix = uuid.uuid4().hex[:8]
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username=f"solution-bundle-{suffix}",
            password="password",
            email=f"solution-bundle-{suffix}@example.com",
            is_staff=True,
        )
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example",
            subject=f"solution-bundle-{suffix}",
            email=f"solution-bundle-{suffix}@example.com",
        )
        self.workspace = Workspace.objects.create(
            slug=f"solution-bundle-{suffix}",
            name="Solution Bundle Workspace",
        )
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user_identity=self.identity,
            role="admin",
            termination_authority=True,
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["user_identity_id"] = str(self.identity.id)
        session.save()
        self.factory = RequestFactory()

    def _package_blob(self, *, include_policy: bool) -> bytes:
        files = {}
        app_content = {
            "app_spec": {
                "app_slug": "real-estate-deal-finder",
                "title": "Real Estate Deal Finder",
                "entities": ["campaign", "property"],
                "requested_visuals": ["campaign_map"],
            },
            "runtime_config": {"source_job_id": "job-source"},
        }
        artifacts = [
            {
                "type": "application",
                "slug": "app.real-estate-deal-finder",
                "version": "0.0.1-dev",
                "title": "Real Estate Deal Finder",
                "description": "Generated app artifact",
                "content": app_content,
            }
        ]
        if include_policy:
            artifacts.append(
                {
                    "type": "policy_bundle",
                    "slug": "policy.real-estate-deal-finder",
                    "version": "0.0.1-dev",
                    "title": "Real Estate Deal Finder Policy",
                    "description": "Generated policy artifact",
                    "content": {
                        "policy_bundle": {
                            "schema_version": "xyn.policy_bundle.v0",
                            "bundle_id": "policy.real-estate-deal-finder",
                            "app_slug": "real-estate-deal-finder",
                            "policies": {"validation_policies": []},
                        }
                    },
                }
            )

        manifest_artifacts = []
        for item in artifacts:
            base = f"artifacts/{item['type']}/{item['slug']}/{item['version']}"
            artifact_path = f"{base}/artifact.json"
            payload_path = f"{base}/payload/payload.json"
            surfaces_path = f"{base}/surfaces.json"
            runtime_roles_path = f"{base}/runtime_roles.json"
            artifact_payload = {
                "artifact": {
                    "type": item["type"],
                    "slug": item["slug"],
                    "version": item["version"],
                    "title": item["title"],
                    "description": item["description"],
                },
                "content": item["content"],
            }
            files[artifact_path] = json.dumps(artifact_payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
            files[payload_path] = json.dumps(item["content"], separators=(",", ":"), sort_keys=True).encode("utf-8")
            files[surfaces_path] = b"[]"
            files[runtime_roles_path] = b"[]"
            manifest_artifacts.append(
                {
                    "type": item["type"],
                    "slug": item["slug"],
                    "version": item["version"],
                    "artifact_hash": "",
                    "dependencies": [],
                    "bindings": [],
                }
            )

        checksums = {}
        import hashlib

        for path, blob in files.items():
            checksums[path] = hashlib.sha256(blob).hexdigest()
        manifest = {
            "format_version": 1,
            "package_name": "deal-finder-bundle",
            "package_version": "0.0.1-dev",
            "built_at": "2026-03-31T00:00:00Z",
            "platform_compatibility": {"min_version": "1.0.0", "required_features": ["artifact_packages_v1"]},
            "artifacts": manifest_artifacts,
            "checksums": checksums,
        }
        files["manifest.json"] = json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode("utf-8")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, blob in sorted(files.items()):
                archive.writestr(path, blob)
        return buffer.getvalue()

    def _install_from_package_source(self, package_id: str):
        return self.client.post(
            f"/xyn/api/solutions/install-bundle?workspace_id={self.workspace.id}",
            data=json.dumps({"source": f"package://{package_id}"}),
            content_type="application/json",
        )

    def test_fresh_install_creates_solution_and_memberships(self) -> None:
        package, _created = import_package_blob_idempotent(blob=self._package_blob(include_policy=True), created_by=self.user)
        response = self._install_from_package_source(str(package.id))
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("policy_source"), "artifact")
        self.assertEqual(payload.get("install_source"), f"package://{package.id}")
        application = Application.objects.get(workspace=self.workspace, metadata_json__solution_bundle_slug="real-estate-deal-finder")
        self.assertEqual(application.name, "Real Estate Deal Finder")
        self.assertEqual(
            (application.metadata_json or {}).get("solution_bundle_install_source"),
            f"package://{package.id}",
        )
        memberships = list(
            ApplicationArtifactMembership.objects.filter(application=application).select_related("artifact").order_by("sort_order", "created_at")
        )
        self.assertEqual(len(memberships), 2)
        self.assertEqual({row.artifact.slug for row in memberships}, {"app.real-estate-deal-finder", "policy.real-estate-deal-finder"})
        self.assertTrue(
            WorkspaceArtifactBinding.objects.filter(workspace=self.workspace, artifact__slug="app.real-estate-deal-finder", enabled=True).exists()
        )

    def test_reinstall_is_idempotent(self) -> None:
        package, _created = import_package_blob_idempotent(blob=self._package_blob(include_policy=True), created_by=self.user)
        first = self._install_from_package_source(str(package.id))
        self.assertEqual(first.status_code, 200, first.content.decode())
        second = self._install_from_package_source(str(package.id))
        self.assertEqual(second.status_code, 200, second.content.decode())
        self.assertEqual(
            Application.objects.filter(workspace=self.workspace, metadata_json__solution_bundle_slug="real-estate-deal-finder").count(),
            1,
        )
        application = Application.objects.get(workspace=self.workspace, metadata_json__solution_bundle_slug="real-estate-deal-finder")
        self.assertEqual(ApplicationArtifactMembership.objects.filter(application=application).count(), 2)

    def test_missing_policy_falls_back_to_reconstructed(self) -> None:
        package, _created = import_package_blob_idempotent(blob=self._package_blob(include_policy=False), created_by=self.user)
        first = self._install_from_package_source(str(package.id))
        self.assertEqual(first.status_code, 200, first.content.decode())
        app_artifact = Artifact.objects.get(workspace=self.workspace, slug="app.real-estate-deal-finder")
        bundle = {
            "schema_version": SOLUTION_BUNDLE_SCHEMA,
            "solution": {
                "slug": "real-estate-deal-finder",
                "name": "Real Estate Deal Finder",
                "description": "Generated app artifact package",
            },
            "artifacts": {
                "primary_app": {
                    "type": "application",
                    "slug": "app.real-estate-deal-finder",
                    "version": str(app_artifact.package_version or ""),
                    "role": "primary_ui",
                },
                "policy": {
                    "type": "policy_bundle",
                    "slug": "policy.real-estate-deal-finder",
                    "version": "0.0.1-dev",
                    "role": "supporting",
                    "optional": True,
                },
                "supporting": [],
            },
            "bootstrap": {},
        }
        response = self.client.post(
            f"/xyn/api/solutions/install-bundle?workspace_id={self.workspace.id}",
            data=json.dumps({"bundle": bundle}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("policy_source"), "reconstructed")
        self.assertEqual(payload.get("install_source"), "inline_bundle")
        warnings = payload.get("warnings") or []
        self.assertTrue(any("policy artifact not available" in str(item).lower() for item in warnings))

    def test_solution_activation_after_bundle_install(self) -> None:
        package, _created = import_package_blob_idempotent(blob=self._package_blob(include_policy=False), created_by=self.user)
        install_response = self._install_from_package_source(str(package.id))
        self.assertEqual(install_response.status_code, 200, install_response.content.decode())
        application = Application.objects.get(workspace=self.workspace, metadata_json__solution_bundle_slug="real-estate-deal-finder")

        request = self.factory.post(
            f"/xyn/api/applications/{application.id}/activate",
            data=json.dumps({}),
            content_type="application/json",
        )
        request.user = self.user

        def _seed_side_effect(*, method: str, path: str, **kwargs):
            if method.upper() == "GET" and path == "/api/v1/jobs":
                return _mock_json_response(200, [])
            if method.upper() == "POST" and path == "/api/v1/drafts":
                return _mock_json_response(201, {"id": "draft-activation"})
            if method.upper() == "POST" and path == "/api/v1/drafts/draft-activation/submit":
                return _mock_json_response(200, {"job_id": "job-activation"})
            raise AssertionError(f"Unexpected seed call method={method} path={path} kwargs={kwargs}")

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            with mock.patch("xyn_orchestrator.xyn_api._seed_api_request", side_effect=_seed_side_effect):
                response = application_activate(request, str(application.id))
        self.assertEqual(response.status_code, 202)
        payload = json.loads(response.content)
        self.assertEqual(payload.get("status"), "queued")
        self.assertEqual(payload.get("policy_source"), "reconstructed")

    def test_install_reports_referenced_artifact_missing_precisely(self) -> None:
        bundle = {
            "schema_version": SOLUTION_BUNDLE_SCHEMA,
            "solution": {"slug": "real-estate-deal-finder", "name": "Real Estate Deal Finder"},
            "artifacts": {
                "primary_app": {
                    "type": "application",
                    "slug": "app.real-estate-deal-finder",
                    "version": "0.0.1-dev",
                    "role": "primary_ui",
                },
                "supporting": [],
            },
            "bootstrap": {},
        }
        response = self.client.post(
            f"/xyn/api/solutions/install-bundle?workspace_id={self.workspace.id}",
            data=json.dumps({"bundle": bundle}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("primary_app artifact missing", str(response.json().get("error") or ""))

    def test_source_loader_supports_file_and_s3(self) -> None:
        bundle = {
            "schema_version": SOLUTION_BUNDLE_SCHEMA,
            "solution": {"slug": "real-estate-deal-finder", "name": "Real Estate Deal Finder"},
            "artifacts": {
                "primary_app": {"type": "application", "slug": "app.real-estate-deal-finder", "version": "0.0.1-dev"},
                "supporting": [],
            },
            "bootstrap": {},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", delete=False) as handle:
            json.dump(bundle, handle)
            temp_path = handle.name
        loaded_file = load_solution_bundle_from_source(temp_path)
        self.assertEqual(loaded_file["solution"]["slug"], "real-estate-deal-finder")

        s3_client = mock.Mock()
        s3_client.get_object.return_value = {"Body": io.BytesIO(json.dumps(bundle).encode("utf-8"))}
        with mock.patch("xyn_orchestrator.solution_bundles.boto3.client", return_value=s3_client):
            loaded_s3 = load_solution_bundle_from_source("s3://xyn-bundles/deal-finder.json")
        self.assertEqual(loaded_s3["solution"]["slug"], "real-estate-deal-finder")

    def test_source_loader_s3_manifest_resolves_relative_package_payloads(self) -> None:
        manifest = {
            "schema_version": SOLUTION_BUNDLE_SCHEMA,
            "solution": {"slug": "real-estate-deal-finder", "name": "Real Estate Deal Finder"},
            "package_payloads": {"app_pkg": "app-package.tgz"},
            "artifacts": {
                "primary_app": {
                    "type": "application",
                    "slug": "app.real-estate-deal-finder",
                    "version": "0.0.1-dev",
                    "package_ref": "app_pkg",
                },
                "supporting": [],
            },
            "bootstrap": {},
        }
        s3_client = mock.Mock()
        s3_client.get_object.return_value = {"Body": io.BytesIO(json.dumps(manifest).encode("utf-8"))}
        with mock.patch("xyn_orchestrator.solution_bundles.boto3.client", return_value=s3_client):
            loaded = load_solution_bundle_from_source("s3://xyn-bundles/deal-finder/v1")
        primary = ((loaded.get("artifacts") or {}).get("primary_app") or {})
        self.assertEqual(primary.get("package_source"), "s3://xyn-bundles/deal-finder/v1/app-package.tgz")

    def test_source_loader_s3_missing_manifest_has_precise_error(self) -> None:
        with mock.patch(
            "xyn_orchestrator.solution_bundles._s3_read_bytes",
            side_effect=SolutionBundleError("s3 key not found"),
        ):
            with self.assertRaisesRegex(Exception, r"s3 bundle manifest not found"):
                load_solution_bundle_from_source("s3://xyn-bundles/deal-finder/v1")

    def test_source_loader_s3_malformed_manifest_has_precise_error(self) -> None:
        s3_client = mock.Mock()
        s3_client.get_object.return_value = {"Body": io.BytesIO(b"{not-json")}
        with mock.patch("xyn_orchestrator.solution_bundles.boto3.client", return_value=s3_client):
            with self.assertRaisesRegex(Exception, r"malformed bundle manifest JSON"):
                load_solution_bundle_from_source("s3://xyn-bundles/deal-finder/v1/manifest.json")

    @mock.patch.dict("os.environ", {}, clear=True)
    def test_source_loader_s3_uses_safe_default_region_when_missing(self) -> None:
        bundle = {
            "schema_version": SOLUTION_BUNDLE_SCHEMA,
            "solution": {"slug": "real-estate-deal-finder", "name": "Real Estate Deal Finder"},
            "artifacts": {
                "primary_app": {"type": "application", "slug": "app.real-estate-deal-finder", "version": "0.0.1-dev"},
                "supporting": [],
            },
            "bootstrap": {},
        }
        s3_client = mock.Mock()
        s3_client.get_object.return_value = {"Body": io.BytesIO(json.dumps(bundle).encode("utf-8"))}
        with mock.patch("xyn_orchestrator.solution_bundles.boto3.client", return_value=s3_client) as mock_client:
            loaded = load_solution_bundle_from_source("s3://xyn-bundles/deal-finder.json")
        self.assertEqual(loaded["solution"]["slug"], "real-estate-deal-finder")
        _, kwargs = mock_client.call_args
        self.assertEqual(kwargs.get("region_name"), "us-east-1")

    @mock.patch.dict(
        "os.environ",
        {"AWS_REGION": "us-west-2", "AWS_ENDPOINT_URL_S3": "https://s3..amazonaws.com"},
        clear=True,
    )
    def test_source_loader_ignores_invalid_s3_endpoint_env(self) -> None:
        bundle = {
            "schema_version": SOLUTION_BUNDLE_SCHEMA,
            "solution": {"slug": "real-estate-deal-finder", "name": "Real Estate Deal Finder"},
            "artifacts": {
                "primary_app": {"type": "application", "slug": "app.real-estate-deal-finder", "version": "0.0.1-dev"},
                "supporting": [],
            },
            "bootstrap": {},
        }
        s3_client = mock.Mock()
        s3_client.get_object.return_value = {"Body": io.BytesIO(json.dumps(bundle).encode("utf-8"))}
        with mock.patch("xyn_orchestrator.solution_bundles.boto3.client", return_value=s3_client) as mock_client:
            loaded = load_solution_bundle_from_source("s3://xyn-bundles/deal-finder.json")
        self.assertEqual(loaded["solution"]["slug"], "real-estate-deal-finder")
        _, kwargs = mock_client.call_args
        self.assertEqual(kwargs.get("region_name"), "us-west-2")
        self.assertNotIn("endpoint_url", kwargs)


class SolutionBundleBootstrapEnvTests(TestCase):
    def setUp(self) -> None:
        suffix = uuid.uuid4().hex[:8]
        self.workspace = Workspace.objects.create(slug=f"bootstrap-{suffix}", name="Bootstrap Workspace")

    def _package_blob(self, *, include_policy: bool) -> bytes:
        files = {}
        app_content = {
            "app_spec": {
                "app_slug": "deal-finder",
                "title": "Deal Finder",
                "entities": ["campaign", "property"],
                "requested_visuals": ["campaign_map"],
            }
        }
        artifacts = [
            {
                "type": "application",
                "slug": "app.deal-finder",
                "version": "0.0.1-dev",
                "title": "Deal Finder",
                "description": "Generated app artifact",
                "content": app_content,
            }
        ]
        if include_policy:
            artifacts.append(
                {
                    "type": "policy_bundle",
                    "slug": "policy.deal-finder",
                    "version": "0.0.1-dev",
                    "title": "Deal Finder Policy",
                    "description": "Generated policy artifact",
                    "content": {
                        "policy_bundle": {
                            "schema_version": "xyn.policy_bundle.v0",
                            "bundle_id": "policy.deal-finder",
                            "app_slug": "deal-finder",
                            "policies": {"validation_policies": []},
                        }
                    },
                }
            )
        manifest_artifacts = []
        import hashlib

        for item in artifacts:
            base = f"artifacts/{item['type']}/{item['slug']}/{item['version']}"
            artifact_path = f"{base}/artifact.json"
            payload_path = f"{base}/payload/payload.json"
            surfaces_path = f"{base}/surfaces.json"
            runtime_roles_path = f"{base}/runtime_roles.json"
            files[artifact_path] = json.dumps(
                {
                    "artifact": {
                        "type": item["type"],
                        "slug": item["slug"],
                        "version": item["version"],
                        "title": item["title"],
                        "description": item["description"],
                    },
                    "content": item["content"],
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            files[payload_path] = json.dumps(item["content"], separators=(",", ":"), sort_keys=True).encode("utf-8")
            files[surfaces_path] = b"[]"
            files[runtime_roles_path] = b"[]"
            manifest_artifacts.append(
                {
                    "type": item["type"],
                    "slug": item["slug"],
                    "version": item["version"],
                    "artifact_hash": "",
                    "dependencies": [],
                    "bindings": [],
                }
            )
        checksums = {path: hashlib.sha256(blob).hexdigest() for path, blob in files.items()}
        manifest = {
            "format_version": 1,
            "package_name": "deal-finder-bundle",
            "package_version": "0.0.1-dev",
            "built_at": "2026-03-31T00:00:00Z",
            "platform_compatibility": {"min_version": "1.0.0", "required_features": ["artifact_packages_v1"]},
            "artifacts": manifest_artifacts,
            "checksums": checksums,
        }
        files["manifest.json"] = json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode("utf-8")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, blob in sorted(files.items()):
                archive.writestr(path, blob)
        return buffer.getvalue()

    def _write_bundle(self, *, package_id: str, path: str) -> None:
        bundle = {
            "schema_version": SOLUTION_BUNDLE_SCHEMA,
            "solution": {"slug": "deal-finder", "name": "Deal Finder"},
            "artifacts": {
                "primary_app": {
                    "type": "application",
                    "slug": "app.deal-finder",
                    "version": "0.0.1-dev",
                    "role": "primary_ui",
                    "package_source": f"package://{package_id}",
                },
                "policy": {
                    "type": "policy_bundle",
                    "slug": "policy.deal-finder",
                    "version": "0.0.1-dev",
                    "role": "supporting",
                    "optional": True,
                    "package_source": f"package://{package_id}",
                },
                "supporting": [],
            },
            "bootstrap": {},
        }
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(bundle, handle)

    def test_bootstrap_install_on_missing(self) -> None:
        package, _ = import_package_blob_idempotent(blob=self._package_blob(include_policy=True), created_by=None)
        with tempfile.TemporaryDirectory() as tempdir:
            self._write_bundle(package_id=str(package.id), path=f"{tempdir}/deal-finder.json")
            with mock.patch.dict(
                "os.environ",
                {
                    "XYN_BOOTSTRAP_INSTALL_SOLUTIONS": "deal-finder",
                    "XYN_BOOTSTRAP_SOLUTION_SOURCE": "local",
                    "XYN_BOOTSTRAP_SOLUTION_PREFIX": tempdir,
                    "XYN_BOOTSTRAP_IF_MISSING_ONLY": "true",
                    "XYN_BOOTSTRAP_SOLUTION_WORKSPACE_SLUG": self.workspace.slug,
                },
                clear=False,
            ):
                summary = bootstrap_install_solution_bundles_from_env(reason="test")
        self.assertTrue(summary.get("enabled"))
        self.assertEqual((summary.get("results") or [])[0].get("status"), "installed")
        self.assertTrue(
            Application.objects.filter(workspace=self.workspace, metadata_json__solution_bundle_slug="deal-finder").exists()
        )

    def test_bootstrap_skip_when_present(self) -> None:
        package, _ = import_package_blob_idempotent(blob=self._package_blob(include_policy=True), created_by=None)
        with tempfile.TemporaryDirectory() as tempdir:
            self._write_bundle(package_id=str(package.id), path=f"{tempdir}/deal-finder.json")
            env = {
                "XYN_BOOTSTRAP_INSTALL_SOLUTIONS": "deal-finder",
                "XYN_BOOTSTRAP_SOLUTION_SOURCE": "local",
                "XYN_BOOTSTRAP_SOLUTION_PREFIX": tempdir,
                "XYN_BOOTSTRAP_IF_MISSING_ONLY": "true",
                "XYN_BOOTSTRAP_SOLUTION_WORKSPACE_SLUG": self.workspace.slug,
            }
            with mock.patch.dict("os.environ", env, clear=False):
                first = bootstrap_install_solution_bundles_from_env(reason="test-first")
                second = bootstrap_install_solution_bundles_from_env(reason="test-second")
        self.assertEqual((first.get("results") or [])[0].get("status"), "installed")
        self.assertEqual((second.get("results") or [])[0].get("status"), "skipped")
        self.assertEqual(
            Application.objects.filter(workspace=self.workspace, metadata_json__solution_bundle_slug="deal-finder").count(),
            1,
        )

    def test_bootstrap_reinstall_mode(self) -> None:
        package, _ = import_package_blob_idempotent(blob=self._package_blob(include_policy=True), created_by=None)
        with tempfile.TemporaryDirectory() as tempdir:
            self._write_bundle(package_id=str(package.id), path=f"{tempdir}/deal-finder.json")
            env = {
                "XYN_BOOTSTRAP_INSTALL_SOLUTIONS": "deal-finder",
                "XYN_BOOTSTRAP_SOLUTION_SOURCE": "local",
                "XYN_BOOTSTRAP_SOLUTION_PREFIX": tempdir,
                "XYN_BOOTSTRAP_IF_MISSING_ONLY": "false",
                "XYN_BOOTSTRAP_SOLUTION_WORKSPACE_SLUG": self.workspace.slug,
            }
            with mock.patch.dict("os.environ", env, clear=False):
                first = bootstrap_install_solution_bundles_from_env(reason="test-first")
                second = bootstrap_install_solution_bundles_from_env(reason="test-second")
        self.assertEqual((first.get("results") or [])[0].get("status"), "installed")
        self.assertEqual((second.get("results") or [])[0].get("status"), "updated")

    def test_bootstrap_invalid_bundle_source(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {
                "XYN_BOOTSTRAP_INSTALL_SOLUTIONS": "deal-finder",
                "XYN_BOOTSTRAP_SOLUTION_SOURCE": "local",
                "XYN_BOOTSTRAP_SOLUTION_PREFIX": "/tmp/path/that/does/not/exist",
                "XYN_BOOTSTRAP_IF_MISSING_ONLY": "true",
                "XYN_BOOTSTRAP_SOLUTION_WORKSPACE_SLUG": self.workspace.slug,
            },
            clear=False,
        ):
            summary = bootstrap_install_solution_bundles_from_env(reason="test")
        self.assertEqual((summary.get("results") or [])[0].get("status"), "failed")

    def test_bootstrap_s3_source_wiring(self) -> None:
        package, _ = import_package_blob_idempotent(blob=self._package_blob(include_policy=False), created_by=None)
        bundle = {
            "schema_version": SOLUTION_BUNDLE_SCHEMA,
            "solution": {"slug": "deal-finder", "name": "Deal Finder"},
            "artifacts": {
                "primary_app": {
                    "type": "application",
                    "slug": "app.deal-finder",
                    "version": "0.0.1-dev",
                    "role": "primary_ui",
                    "package_source": f"package://{package.id}",
                },
                "supporting": [],
            },
            "bootstrap": {},
        }
        s3_client = mock.Mock()

        def _get_object(*, Bucket: str, Key: str):
            if Key == "solutions/deal-finder/manifest.json":
                return {"Body": io.BytesIO(json.dumps(bundle).encode("utf-8"))}
            raise AssertionError(f"Unexpected s3 key requested: {Bucket}/{Key}")

        s3_client.get_object.side_effect = _get_object
        with mock.patch.dict(
            "os.environ",
            {
                "XYN_BOOTSTRAP_INSTALL_SOLUTIONS": "deal-finder",
                "XYN_BOOTSTRAP_SOLUTION_SOURCE": "s3",
                "XYN_BOOTSTRAP_SOLUTION_BUCKET": "xyn-bundles",
                "XYN_BOOTSTRAP_SOLUTION_PREFIX": "solutions",
                "XYN_BOOTSTRAP_IF_MISSING_ONLY": "true",
                "XYN_BOOTSTRAP_SOLUTION_WORKSPACE_SLUG": self.workspace.slug,
            },
            clear=False,
        ):
            with mock.patch("xyn_orchestrator.solution_bundles.boto3.client", return_value=s3_client):
                summary = bootstrap_install_solution_bundles_from_env(reason="test")
        result = (summary.get("results") or [])[0]
        self.assertEqual(result.get("status"), "installed")
        self.assertEqual(result.get("source"), "s3://xyn-bundles/solutions/deal-finder")

    def test_bootstrap_s3_versioned_prefix_wiring(self) -> None:
        package, _ = import_package_blob_idempotent(blob=self._package_blob(include_policy=False), created_by=None)
        bundle = {
            "schema_version": SOLUTION_BUNDLE_SCHEMA,
            "solution": {"slug": "deal-finder", "name": "Deal Finder"},
            "artifacts": {
                "primary_app": {
                    "type": "application",
                    "slug": "app.deal-finder",
                    "version": "0.0.1-dev",
                    "role": "primary_ui",
                    "package_source": f"package://{package.id}",
                },
                "supporting": [],
            },
            "bootstrap": {},
        }
        s3_client = mock.Mock()

        def _get_object(*, Bucket: str, Key: str):
            if Key == "solutions/deal-finder/v2026-03-31/manifest.json":
                return {"Body": io.BytesIO(json.dumps(bundle).encode("utf-8"))}
            raise AssertionError(f"Unexpected s3 key requested: {Bucket}/{Key}")

        s3_client.get_object.side_effect = _get_object
        with mock.patch.dict(
            "os.environ",
            {
                "XYN_BOOTSTRAP_INSTALL_SOLUTIONS": "deal-finder",
                "XYN_BOOTSTRAP_SOLUTION_SOURCE": "s3",
                "XYN_BOOTSTRAP_SOLUTION_BUCKET": "xyn-bundles",
                "XYN_BOOTSTRAP_SOLUTION_PREFIX": "solutions",
                "XYN_BOOTSTRAP_SOLUTION_VERSION": "v2026-03-31",
                "XYN_BOOTSTRAP_IF_MISSING_ONLY": "true",
                "XYN_BOOTSTRAP_SOLUTION_WORKSPACE_SLUG": self.workspace.slug,
            },
            clear=False,
        ):
            with mock.patch("xyn_orchestrator.solution_bundles.boto3.client", return_value=s3_client):
                summary = bootstrap_install_solution_bundles_from_env(reason="test")
        result = (summary.get("results") or [])[0]
        self.assertEqual(result.get("status"), "installed")
        self.assertEqual(result.get("source"), "s3://xyn-bundles/solutions/deal-finder/v2026-03-31")
