from unittest import mock

from django.test import SimpleTestCase

from xyn_orchestrator.deployment_provider_contract import (
    build_non_destructive_deployment_plan,
    build_deployment_release_target_preparation_metadata,
    derive_staged_execution_intent_from_deployment_plan,
    derive_deployment_dns_deploy_preparation_actions,
    derive_deployment_dns_deprovision_preparation_actions,
    evaluate_deployment_execution_preflight_readiness,
    evaluate_deployment_dns_deploy_preparation_readiness,
    evaluate_deployment_dns_deprovision_readiness,
    normalize_deployment_dns_provider_config,
    resolve_deployment_target_contract,
    resolve_deployment_dns_deprovision_orchestration,
    validate_deployment_dns_provider_config,
)
from xyn_orchestrator import xyn_api


class DeploymentProviderSeamRuntimeTests(SimpleTestCase):
    def test_seam_stub_normalizes_dns_provider_config_for_route53_kind(self):
        normalized = normalize_deployment_dns_provider_config(
            dns_provider="route53",
            selected_provider_key="aws_ssm_route53",
            config={"hosted_zone_id": "Z123"},
        )
        self.assertEqual(normalized.get("kind"), "route53")
        self.assertEqual(normalized.get("hosted_zone_id"), "Z123")

    def test_seam_stub_validates_dns_provider_config_for_legacy_provider(self):
        errors = validate_deployment_dns_provider_config(
            dns_provider="route53",
            selected_provider_key="aws_ssm_route53",
            config={"kind": "cloudflare"},
        )
        self.assertIn("dns_provider.kind: only route53 is supported by the aws_ssm_route53 provider seam", errors)

    def test_seam_stub_builds_release_target_preparation_metadata(self):
        preparation = build_deployment_release_target_preparation_metadata(
            dns_provider="route53",
            selected_provider_key="aws_ssm_route53",
            dns_config={"hosted_zone_id": "Z123"},
            runtime_config={"transport": "ssm"},
            tls_config={"mode": "none"},
        )
        self.assertEqual(preparation.get("provider_key"), "aws_ssm_route53")
        self.assertEqual(preparation.get("dns_provider"), "route53")
        self.assertIn("dns_provider.credentials_ref.context_pack_id", preparation.get("missing_inputs") or [])

    def test_seam_stub_evaluates_dns_deprovision_readiness(self):
        route53_readiness = evaluate_deployment_dns_deprovision_readiness(
            dns_provider="route53",
            selected_provider_key="aws_ssm_route53",
            dns_config={},
        )
        self.assertTrue(route53_readiness.get("can_delete_dns_record"))
        self.assertEqual(str(route53_readiness.get("blocked_reason") or ""), "")

        unsupported_readiness = evaluate_deployment_dns_deprovision_readiness(
            dns_provider="cloudflare",
            selected_provider_key="aws_ssm_route53",
            dns_config={},
        )
        self.assertFalse(unsupported_readiness.get("can_delete_dns_record"))
        self.assertIn("not supported for deprovision delete", str(unsupported_readiness.get("blocked_reason") or ""))

    def test_seam_stub_resolves_dns_deprovision_orchestration(self):
        route53_orchestration = resolve_deployment_dns_deprovision_orchestration(
            dns_provider="route53",
            selected_provider_key="aws_ssm_route53",
            fqdn="demo.xyence.local",
            release_target_id="target-1",
        )
        self.assertTrue(route53_orchestration.get("can_orchestrate"))
        self.assertEqual(route53_orchestration.get("step_capability"), "dns.route53.delete_record")
        self.assertEqual(route53_orchestration.get("step_id"), "dns.delete_record.route53.target-1")

        unsupported_orchestration = resolve_deployment_dns_deprovision_orchestration(
            dns_provider="cloudflare",
            selected_provider_key="aws_ssm_route53",
            fqdn="demo.xyence.local",
            release_target_id="target-1",
        )
        self.assertFalse(unsupported_orchestration.get("can_orchestrate"))
        self.assertIn("no deprovision orchestration mapping", str(unsupported_orchestration.get("blocked_reason") or ""))

    def test_seam_stub_derives_dns_deprovision_preparation_actions(self):
        actions = derive_deployment_dns_deprovision_preparation_actions(
            dns_provider="route53",
            selected_provider_key="aws_ssm_route53",
            fqdn="demo.xyence.local",
            release_target_id="target-1",
        )
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].get("action_key"), "dns_delete_record")
        self.assertEqual(actions[0].get("capability"), "dns.route53.delete_record")

        unsupported_actions = derive_deployment_dns_deprovision_preparation_actions(
            dns_provider="cloudflare",
            selected_provider_key="aws_ssm_route53",
            fqdn="demo.xyence.local",
            release_target_id="target-1",
        )
        self.assertEqual(unsupported_actions, [])

    def test_seam_stub_derives_dns_deploy_preparation_actions(self):
        actions = derive_deployment_dns_deploy_preparation_actions(
            dns_provider="route53",
            selected_provider_key="aws_ssm_route53",
            fqdn="demo.xyence.local",
            target_instance_id="instance-1",
        )
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].get("action_key"), "dns_ensure_record")
        self.assertEqual(actions[0].get("capability"), "dns.route53.records")
        self.assertEqual(actions[0].get("step_id"), "dns.ensure_record.route53")

        unsupported_actions = derive_deployment_dns_deploy_preparation_actions(
            dns_provider="cloudflare",
            selected_provider_key="aws_ssm_route53",
            fqdn="demo.xyence.local",
            target_instance_id="instance-1",
        )
        self.assertEqual(unsupported_actions, [])

    def test_seam_stub_evaluates_dns_deploy_preparation_readiness(self):
        readiness = evaluate_deployment_dns_deploy_preparation_readiness(
            dns_provider="route53",
            selected_provider_key="aws_ssm_route53",
            fqdn="demo.xyence.local",
            target_instance_id="instance-1",
            dns_config={
                "hosted_zone_id": "Z123",
                "credentials_ref": {"context_pack_id": "11111111-1111-1111-1111-111111111111"},
            },
        )
        self.assertTrue(readiness.get("can_prepare"))
        self.assertEqual(readiness.get("missing_inputs"), [])

        blocked = evaluate_deployment_dns_deploy_preparation_readiness(
            dns_provider="route53",
            selected_provider_key="aws_ssm_route53",
            fqdn="",
            target_instance_id="instance-1",
            dns_config={"hosted_zone_id": "Z123"},
        )
        self.assertFalse(blocked.get("can_prepare"))
        self.assertIn("release_target.fqdn", blocked.get("missing_inputs") or [])

    def test_seam_stub_evaluates_execution_preflight_readiness(self):
        ready = evaluate_deployment_execution_preflight_readiness(
            operation="check_drift",
            selected_provider_key="aws_ssm_route53",
            runtime_config={"transport": "ssm"},
            target_instance_id="i-123",
            aws_region="us-west-2",
            remote_root="/opt/xyn/apps/demo",
        )
        self.assertTrue(ready.get("can_probe_runtime_marker"))
        self.assertEqual(ready.get("blocked_reason"), "")
        self.assertFalse(bool(ready.get("can_prepare_runtime_root")))

        prepare_ready = evaluate_deployment_execution_preflight_readiness(
            operation="prepare_runtime_root",
            selected_provider_key="aws_ssm_route53",
            runtime_config={"transport": "ssm"},
            target_instance_id="i-123",
            aws_region="us-west-2",
            remote_root="/opt/xyn/apps/demo",
        )
        self.assertTrue(bool(prepare_ready.get("can_prepare_runtime_root")))
        self.assertFalse(bool(prepare_ready.get("can_probe_runtime_marker")))

        manifest_ready = evaluate_deployment_execution_preflight_readiness(
            operation="stage_execution_manifest",
            selected_provider_key="aws_ssm_route53",
            runtime_config={"transport": "ssm"},
            target_instance_id="i-123",
            aws_region="us-west-2",
            remote_root="/opt/xyn/apps/demo",
        )
        self.assertTrue(bool(manifest_ready.get("can_stage_execution_manifest")))
        self.assertFalse(bool(manifest_ready.get("can_probe_runtime_marker")))

        blocked = evaluate_deployment_execution_preflight_readiness(
            operation="check_drift",
            selected_provider_key="aws_ssm_route53",
            runtime_config={"transport": "ssh"},
            target_instance_id="",
            aws_region="",
            remote_root="",
        )
        self.assertFalse(blocked.get("can_probe_runtime_marker"))
        self.assertIn("not supported", str(blocked.get("blocked_reason") or ""))

    def test_seam_stub_exposes_provider_neutral_deployment_target_contract(self):
        contract = resolve_deployment_target_contract(selected_provider_key="aws_ssm_route53")
        self.assertEqual(contract.get("provider_key"), "aws_ssm_route53")
        self.assertEqual(contract.get("target_profile_kind"), "sibling_runtime")
        self.assertEqual(contract.get("runtime_target_kind"), "ec2_instance")
        self.assertIn("prepare_runtime_target", contract.get("capability_categories") or [])
        module_contract = contract.get("provider_module_contract") or {}
        self.assertEqual(module_contract.get("module_id"), "deploy-aws-ec2-sibling")
        self.assertEqual(
            module_contract.get("module_manifest_ref"),
            "backend/registry/modules/deploy-aws-ec2-sibling.json",
        )

    @mock.patch("xyn_orchestrator.deployment_provider_contract.subprocess.run")
    def test_non_destructive_deployment_plan_is_seam_backed_and_machine_readable(self, mock_run):
        mock_run.return_value = mock.Mock(
            returncode=0,
            stdout='{"Account":"123456789012"}',
            stderr="",
        )
        plan = build_non_destructive_deployment_plan(
            selected_provider_key="aws_ssm_route53",
            release_target_id="target-1",
            blueprint_ref="blueprint-1",
            solution_name="real-estate-deal-finder",
            target_instance_id="i-123",
            aws_region="us-west-2",
            runtime_config={"transport": "ssm", "remote_root": "/opt/xyn/apps/deal-finder"},
            dns_provider="route53",
            dns_config={
                "hosted_zone_id": "Z123",
                "credentials_ref": {"context_pack_id": "11111111-1111-1111-1111-111111111111"},
            },
            fqdn="deal.xyence.io",
            instance_type="t3.small",
            discover_environment=True,
        )

        self.assertEqual(plan.get("planning_mode"), "non_destructive")
        self.assertTrue(plan.get("execution_ready_in_principle"))
        self.assertEqual(plan.get("provider_key"), "aws_ssm_route53")
        provider_contract = plan.get("provider_contract") or {}
        deployment_contract = provider_contract.get("deployment_target_contract") or {}
        self.assertEqual(deployment_contract.get("runtime_target_kind"), "ec2_instance")
        module_contract = provider_contract.get("provider_module_contract") or {}
        self.assertEqual(module_contract.get("module_id"), "deploy-aws-ec2-sibling")
        self.assertEqual((plan.get("environment_discovery") or {}).get("account_id"), "123456789012")
        self.assertEqual((plan.get("requested_config") or {}).get("instance_type"), "t3.small")
        step_statuses = {str(step.get("id") or ""): str(step.get("status") or "") for step in (plan.get("steps") or [])}
        self.assertEqual(step_statuses.get("prepare.runtime_target"), "ready")
        self.assertEqual(step_statuses.get("prepare.dns_target"), "ready")
        self.assertEqual(step_statuses.get("prepare.execution_preflight"), "ready")

    def test_staged_execution_intent_derives_ready_and_blocked_steps(self):
        plan = {
            "planning_mode": "non_destructive",
            "operation": "sibling_runtime_deployment_plan",
            "provider_key": "aws_ssm_route53",
            "execution_ready_in_principle": False,
            "provider_contract": {"module_manifest_ref": "backend/registry/modules/deploy-aws-ec2-sibling.json"},
            "warnings": ["non-destructive only"],
            "steps": [
                {
                    "id": "prepare.runtime_target",
                    "title": "Prepare runtime",
                    "status": "blocked",
                    "capability_category": "prepare_runtime_target",
                    "blocked_reason": "missing runtime inputs",
                    "missing_inputs": ["target_instance.aws_region"],
                },
                {
                    "id": "prepare.dns_target",
                    "title": "Prepare dns",
                    "status": "ready",
                    "capability_category": "prepare_dns_target",
                    "blocked_reason": "",
                    "missing_inputs": [],
                },
            ],
        }
        intent = derive_staged_execution_intent_from_deployment_plan(plan)
        self.assertEqual(intent.get("schema_version"), "xyn.deployment_staged_intent.v1")
        self.assertFalse(intent.get("promotable_to_execution_in_principle"))
        self.assertIn("prepare.runtime_target", intent.get("blocked_steps") or [])
        self.assertIn("prepare.dns_target", intent.get("ready_steps") or [])
        self.assertIn("target_instance.aws_region", intent.get("required_future_inputs") or [])

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

    def test_release_target_normalization_uses_seam_dns_provider_config_normalization(self):
        profile = {
            "resolved": True,
            "selected_provider_key": "aws_ssm_route53",
            "requested_provider": "route53",
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
            "dns": {"provider": "route53"},
            "dns_provider": {"hosted_zone_id": "Z123"},
            "runtime": {"type": "docker-compose", "transport": "ssm", "mode": "compose_images"},
            "tls": {"mode": "none"},
        }
        normalized_dns_provider_payload = {
            "hosted_zone_id": "Z123",
            "kind": "route53",
        }

        with mock.patch(
            "xyn_orchestrator.xyn_api.resolve_deployment_dns_profile",
            return_value=profile,
        ) as resolver, mock.patch(
            "xyn_orchestrator.xyn_api.normalize_deployment_dns_provider_config",
            return_value=normalized_dns_provider_payload,
        ) as normalizer:
            normalized = xyn_api._normalize_release_target_payload(payload, "00000000-0000-0000-0000-000000000001")

        resolver.assert_called_once_with(requested_provider="route53")
        normalizer.assert_called_once_with(
            dns_provider="route53",
            config={"hosted_zone_id": "Z123"},
            selected_provider_key="aws_ssm_route53",
        )
        self.assertEqual(normalized.get("dns_provider"), normalized_dns_provider_payload)

    def test_release_target_validation_uses_seam_dns_provider_config_validation(self):
        payload = {
            "schema_version": "release_target.v1",
            "id": "00000000-0000-0000-0000-000000000001",
            "blueprint_id": "00000000-0000-0000-0000-000000000002",
            "name": "Target",
            "environment": "dev",
            "target_instance_id": "instance-1",
            "fqdn": "demo.xyence.local",
            "dns": {"provider": "route53", "zone_name": "xyence.local", "zone_id": "Z123", "record_type": "A", "ttl": 60},
            "runtime": {"type": "docker-compose", "transport": "ssm", "remote_root": "/opt/xyn", "compose_file_path": "docker-compose.yml"},
            "tls": {"mode": "none"},
            "ingress": {"network": "xyn-edge", "routes": []},
            "env": {},
            "secret_refs": [],
            "dns_provider": {"kind": "cloudflare"},
            "auto_generated": False,
            "editable": True,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        profile = {
            "resolved": True,
            "selected_provider_key": "aws_ssm_route53",
            "requested_provider": "route53",
            "default_dns_provider": "route53",
            "contract": {
                "provider_key": "aws_ssm_route53",
                "execution_path": "xyn_orchestrator.xyn_api._intent_apply_provision_xyn_remote",
                "implementation_kind": "legacy_core",
            },
        }
        seam_errors = ["dns_provider.kind: only route53 is supported by the aws_ssm_route53 provider seam"]

        with mock.patch(
            "xyn_orchestrator.xyn_api.resolve_deployment_dns_profile",
            return_value=profile,
        ) as resolver, mock.patch(
            "xyn_orchestrator.xyn_api.validate_deployment_dns_provider_config",
            return_value=seam_errors,
        ) as validator:
            errors = xyn_api._validate_release_target_payload(payload)

        resolver.assert_called_once_with(requested_provider="route53")
        validator.assert_called_once_with(
            dns_provider="route53",
            config={"kind": "cloudflare"},
            selected_provider_key="aws_ssm_route53",
        )
        self.assertIn(seam_errors[0], errors)

    def test_release_target_normalization_uses_seam_preparation_metadata_builder(self):
        profile = {
            "resolved": True,
            "selected_provider_key": "aws_ssm_route53",
            "requested_provider": "route53",
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
            "dns": {"provider": "route53"},
            "dns_provider": {"hosted_zone_id": "Z123", "credentials_ref": {"context_pack_id": "11111111-1111-1111-1111-111111111111"}},
            "runtime": {"type": "docker-compose", "transport": "ssm", "mode": "compose_images"},
            "tls": {"mode": "none"},
        }
        normalized_dns_provider_payload = {
            "hosted_zone_id": "Z123",
            "credentials_ref": {"context_pack_id": "11111111-1111-1111-1111-111111111111"},
            "kind": "route53",
        }
        preparation = {
            "provider_key": "aws_ssm_route53",
            "seam_source": "deployment_provider_contract",
            "dns_provider": "route53",
            "required_inputs": ["dns_provider.hosted_zone_id", "dns_provider.credentials_ref.context_pack_id"],
            "missing_inputs": [],
        }

        with mock.patch(
            "xyn_orchestrator.xyn_api.resolve_deployment_dns_profile",
            return_value=profile,
        ), mock.patch(
            "xyn_orchestrator.xyn_api.normalize_deployment_dns_provider_config",
            return_value=normalized_dns_provider_payload,
        ), mock.patch(
            "xyn_orchestrator.xyn_api.build_deployment_release_target_preparation_metadata",
            return_value=preparation,
        ) as preparation_builder:
            normalized = xyn_api._normalize_release_target_payload(payload, "00000000-0000-0000-0000-000000000001")

        preparation_builder.assert_called_once_with(
            dns_provider="route53",
            dns_config=normalized_dns_provider_payload,
            runtime_config={"type": "docker-compose", "transport": "ssm", "mode": "compose_images"},
            tls_config={"mode": "none"},
            selected_provider_key="aws_ssm_route53",
        )
        self.assertEqual(normalized.get("deployment_preparation"), preparation)
