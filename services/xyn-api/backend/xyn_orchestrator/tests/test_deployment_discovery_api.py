from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from xyn_orchestrator.models import ArtifactType, Blueprint, Module, ReleaseTarget, Workspace


class DeploymentDiscoveryApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff = user_model.objects.create_user(username="discovery-staff", password="pass", is_staff=True)
        self.client.force_login(self.staff)
        self.workspace, _ = Workspace.objects.get_or_create(slug="platform-builder", defaults={"name": "Platform Builder"})
        self.artifact_type, _ = ArtifactType.objects.get_or_create(slug="module", defaults={"name": "Module"})

    def test_release_target_discovery_empty_returns_list(self):
        response = self.client.get("/xyn/api/release-targets")
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("release_targets"), [])

    def test_artifact_discovery_empty_returns_list(self):
        response = self.client.get("/xyn/api/artifacts", {"limit": 10, "offset": 0, "query": "no-such-artifact-slug-xyz"})
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("artifacts"), [])
        self.assertEqual(payload.get("count"), 0)

    def test_release_target_and_artifact_discovery_non_empty(self):
        blueprint = Blueprint.objects.create(name="Deal Finder", namespace="real-estate")
        target = ReleaseTarget.objects.create(
            blueprint=blueprint,
            name="Deal Finder Dev",
            fqdn="deal.xyence.io",
            runtime_json={"transport": "ssm", "type": "docker-compose"},
            dns_json={"provider": "route53"},
        )
        rt_response = self.client.get("/xyn/api/release-targets")
        self.assertEqual(rt_response.status_code, 200, rt_response.content.decode())
        rt_payload = rt_response.json().get("release_targets") or []
        self.assertEqual(len(rt_payload), 1)
        self.assertEqual(rt_payload[0].get("name"), target.name)
        self.assertEqual((rt_payload[0].get("runtime") or {}).get("transport"), "ssm")
        self.assertEqual((rt_payload[0].get("dns") or {}).get("provider"), "route53")

        artifact_response = self.client.get("/xyn/api/artifacts")
        self.assertEqual(artifact_response.status_code, 200, artifact_response.content.decode())
        artifacts = artifact_response.json().get("artifacts") or []
        self.assertGreaterEqual(len(artifacts), 1)
        self.assertTrue(all(isinstance(row, dict) for row in artifacts))

    @mock.patch("xyn_orchestrator.xyn_api.maybe_sync_modules_from_registry")
    def test_deployment_provider_discovery_empty_and_non_empty(self, sync_mock: mock.Mock):
        sync_mock.return_value = 0
        Module.objects.all().delete()

        empty_response = self.client.get("/xyn/api/deployment-providers")
        self.assertEqual(empty_response.status_code, 200, empty_response.content.decode())
        self.assertEqual(empty_response.json().get("providers"), [])
        self.assertEqual(empty_response.json().get("count"), 0)

        module = Module.objects.create(
            namespace="core",
            name="deploy-ssm-compose",
            fqn="core.deploy-ssm-compose",
            type="lib",
            current_version="0.1.0",
            capabilities_provided_json=["deploy.ssm.run_shell", "runtime.compose.apply_remote"],
            interfaces_json={"operations": {"ensure_remote_runtime": "desc"}},
            latest_module_spec_json={
                "description": "Remote docker-compose deployment via AWS SSM RunCommand.",
                "metadata": {"labels": {"topology": "sibling"}},
                "module": {"capabilitiesProvided": ["deploy.ssm.run_shell", "runtime.compose.apply_remote"]},
            },
        )

        response = self.client.get("/xyn/api/deployment-providers")
        self.assertEqual(response.status_code, 200, response.content.decode())
        providers = response.json().get("providers") or []
        self.assertEqual(len(providers), 1)
        provider = providers[0]
        self.assertEqual(provider.get("provider_key"), module.name)
        self.assertIn("plan", provider.get("supported_operations") or [])
        self.assertIn("execute", provider.get("supported_operations") or [])
        self.assertIn("runtime.compose.apply_remote", provider.get("known_capabilities") or [])
        self.assertEqual(provider.get("supported_topologies"), ["sibling"])

        detail = self.client.get(f"/xyn/api/deployment-providers/{module.name}")
        self.assertEqual(detail.status_code, 200, detail.content.decode())
        detail_provider = (detail.json().get("provider") or {})
        self.assertEqual(detail_provider.get("provider_key"), module.name)
        self.assertEqual(detail_provider.get("module_fqn"), module.fqn)
