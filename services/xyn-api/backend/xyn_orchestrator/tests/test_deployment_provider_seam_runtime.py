from unittest import mock

from django.test import SimpleTestCase

from xyn_orchestrator import xyn_api


class DeploymentProviderSeamRuntimeTests(SimpleTestCase):
    def test_release_target_normalization_uses_seam_dns_profile_resolution(self):
        profile = {
            "resolved": True,
            "selected_provider_key": "aws_ssm_route53",
            "requested_provider": "",
            "default_dns_provider": "route53",
            "contract": {
                "provider_key": "aws_ssm_route53",
                "execution_path": "xyn_orchestrator.xyn_api._intent_apply_provision_xyn_remote",
                "implementation_kind": "legacy_core",
            },
        }
        payload = {
            "name": "Target",
            "target_instance_id": "instance-1",
            "fqdn": "demo.xyence.local",
            "dns": {},
            "runtime": {"type": "docker-compose", "transport": "ssm", "mode": "compose_images"},
            "tls": {"mode": "none"},
        }

        with mock.patch(
            "xyn_orchestrator.xyn_api.resolve_deployment_dns_profile",
            return_value=profile,
        ) as resolver:
            normalized = xyn_api._normalize_release_target_payload(payload, "00000000-0000-0000-0000-000000000001")

        resolver.assert_called_once_with(requested_provider="")
        self.assertEqual((normalized.get("dns") or {}).get("provider"), "route53")
        self.assertEqual(normalized.get("deployment_provider_profile"), profile)
