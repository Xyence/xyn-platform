import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from xyn_orchestrator.models import Blueprint, ProvisionedInstance


class BlueprintDiscoveryApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff = user_model.objects.create_user(username="blueprint-discovery-staff", password="pass", is_staff=True)
        self.client.force_login(self.staff)
        self.instance = ProvisionedInstance.objects.create(
            name="xyn-sibling-ec2",
            aws_region="us-east-1",
            instance_type="t3.small",
            ami_id="ami-1234567890abcdef0",
            runtime_substrate="aws",
            created_by=self.staff,
            updated_by=self.staff,
        )

    def _self_hosting_blueprint_payload(self) -> dict:
        return {
            "name": "Xyn Self Hosted Sibling",
            "namespace": "xyn",
            "description": "Self-hosted Xyn sibling deployment baseline for AWS EC2 via SSM compose.",
            "spec_text": "Deploy Xyn Runtime to sibling topology via deploy-ssm-compose provider.",
            "metadata_json": {
                "deployment_profile": "xyn_self_hosting_aws_ec2_sibling",
                "topology": {"kind": "sibling"},
                "artifact_binding": {"artifact_slug": "xyn-runtime"},
                "provider_binding": {"provider_key": "deploy-ssm-compose"},
                "required_config_inputs": [
                    "target_instance_id",
                    "fqdn",
                    "runtime.remote_root",
                    "runtime.compose_file_path",
                    "dns.zone_name",
                ],
            },
        }

    def test_blueprint_discovery_and_release_target_creation_with_blueprint_id(self):
        create_bp = self.client.post(
            "/xyn/api/blueprints",
            data=json.dumps(self._self_hosting_blueprint_payload()),
            content_type="application/json",
        )
        self.assertEqual(create_bp.status_code, 200, create_bp.content.decode())
        blueprint_id = create_bp.json().get("id")
        self.assertTrue(blueprint_id)

        listing = self.client.get("/xyn/api/blueprints")
        self.assertEqual(listing.status_code, 200, listing.content.decode())
        rows = listing.json().get("blueprints") or []
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("namespace"), "xyn")
        self.assertEqual((rows[0].get("metadata_json") or {}).get("deployment_profile"), "xyn_self_hosting_aws_ec2_sibling")

        detail = self.client.get(f"/xyn/api/blueprints/{blueprint_id}")
        self.assertEqual(detail.status_code, 200, detail.content.decode())
        detail_payload = detail.json()
        self.assertEqual(detail_payload.get("id"), blueprint_id)
        self.assertEqual((detail_payload.get("metadata_json") or {}).get("provider_binding", {}).get("provider_key"), "deploy-ssm-compose")
        self.assertEqual((detail_payload.get("metadata_json") or {}).get("artifact_binding", {}).get("artifact_slug"), "xyn-runtime")
        self.assertEqual((detail_payload.get("metadata_json") or {}).get("topology", {}).get("kind"), "sibling")

        create_target = self.client.post(
            "/xyn/api/release-targets",
            data=json.dumps(
                {
                    "blueprint_id": blueprint_id,
                    "name": "xyn-aws-sibling-dev",
                    "environment": "dev",
                    "target_instance_id": str(self.instance.id),
                    "fqdn": "deal.xyence.io",
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
            ),
            content_type="application/json",
        )
        self.assertEqual(create_target.status_code, 200, create_target.content.decode())
        self.assertTrue(create_target.json().get("id"))

    def test_blueprint_discovery_empty_returns_list(self):
        Blueprint.objects.all().delete()
        response = self.client.get("/xyn/api/blueprints", {"q": "no-such-blueprint-xyz"})
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("blueprints"), [])

