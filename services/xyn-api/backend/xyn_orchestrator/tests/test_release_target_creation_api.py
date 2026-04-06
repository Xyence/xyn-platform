import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from xyn_orchestrator.models import Blueprint, ProvisionedInstance


class ReleaseTargetCreationApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff = user_model.objects.create_user(username="release-target-staff", password="pass", is_staff=True)
        self.client.force_login(self.staff)
        self.blueprint = Blueprint.objects.create(name="Xyn Runtime", namespace="xyn")
        self.instance = ProvisionedInstance.objects.create(
            name="xyn-sibling-ec2",
            aws_region="us-east-1",
            instance_type="t3.small",
            ami_id="ami-1234567890abcdef0",
            runtime_substrate="aws",
            created_by=self.staff,
            updated_by=self.staff,
        )

    def _create_payload(self) -> dict:
        return {
            "blueprint_id": str(self.blueprint.id),
            "name": "xyn-aws-sibling-dev",
            "environment": "dev",
            "target_instance_id": str(self.instance.id),
            "fqdn": "xyn-sibling.example.internal",
            "runtime": {
                "type": "docker-compose",
                "transport": "ssm",
                "mode": "compose_build",
                "remote_root": "/opt/xyn/apps/xyn-runtime",
                "compose_file_path": "compose.release.yml",
            },
            "dns": {"provider": "route53", "zone_name": "xyence.io", "record_type": "A", "ttl": 60},
            "tls": {"mode": "none"},
            "topology": {"kind": "sibling"},
            "provider_binding": {"provider_key": "deploy-ssm-compose"},
            "artifact_binding": {"artifact_slug": "xyn-runtime"},
        }

    def test_create_release_target_preserves_topology_and_bindings(self):
        response = self.client.post(
            "/xyn/api/release-targets",
            data=json.dumps(self._create_payload()),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content.decode())
        target_id = response.json().get("id")
        self.assertTrue(target_id)

        detail = self.client.get(f"/xyn/api/release-targets/{target_id}")
        self.assertEqual(detail.status_code, 200, detail.content.decode())
        payload = detail.json()
        self.assertEqual((payload.get("topology") or {}).get("kind"), "sibling")
        self.assertEqual((payload.get("provider_binding") or {}).get("provider_key"), "deploy-ssm-compose")
        self.assertEqual((payload.get("artifact_binding") or {}).get("artifact_slug"), "xyn-runtime")
        self.assertEqual(payload.get("blueprint_id"), str(self.blueprint.id))

        listing = self.client.get("/xyn/api/release-targets")
        self.assertEqual(listing.status_code, 200, listing.content.decode())
        targets = listing.json().get("release_targets") or []
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].get("name"), "xyn-aws-sibling-dev")

    def test_create_release_target_rejects_unresolved_blueprint(self):
        payload = self._create_payload()
        payload.pop("blueprint_id", None)
        payload["artifact_slug"] = "missing-artifact"
        payload.pop("artifact_binding", None)
        response = self.client.post("/xyn/api/release-targets", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 400, response.content.decode())
        self.assertEqual(response.json().get("error"), "release_target_blueprint_unresolved")
