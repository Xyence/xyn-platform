from django.test import SimpleTestCase

from xyn_orchestrator.architecture_placement import (
    deployment_provider_contract_summary,
    evaluate_architectural_placement,
)


class ArchitecturePlacementContractTests(SimpleTestCase):
    def test_deployment_provider_request_prefers_provider_artifact_module(self):
        decision = evaluate_architectural_placement(
            request_text="Add AWS deployment provider support for EKS runtime provisioning.",
            capability_domain="auto",
        )
        self.assertEqual(decision.get("policy_version"), "xyn.architecture_placement.v1")
        self.assertEqual(decision.get("capability_domain"), "deployment")
        self.assertTrue(bool(decision.get("provider_specific")))
        self.assertEqual(decision.get("recommendation"), "provider_artifact_module")
        self.assertEqual(decision.get("core_allowed"), "provider_neutral_only")
        self.assertEqual(decision.get("provider_strategy"), "provider_module_required")
        self.assertEqual(
            decision.get("provider_specific_implementation_target"),
            "xyn_orchestrator.deployment_provider_contract",
        )
        self.assertTrue(bool(decision.get("forbidden_core_targets")))

    def test_provider_neutral_deployment_abstraction_request_allows_minimal_core_abstraction(self):
        decision = evaluate_architectural_placement(
            request_text="Add a provider-neutral deployment lifecycle abstraction for runtime activation.",
            capability_domain="auto",
        )
        self.assertEqual(decision.get("capability_domain"), "deployment")
        self.assertEqual(decision.get("recommendation"), "core_abstraction_orchestration")
        self.assertTrue(bool(decision.get("required_core_abstraction_change")))
        self.assertEqual(decision.get("provider_strategy"), "neutral_core_abstraction")

    def test_provider_specific_core_coupling_request_is_explicitly_flagged(self):
        decision = evaluate_architectural_placement(
            request_text="Add Route53 logic directly into core deployment orchestration.",
            capability_domain="auto",
        )
        self.assertEqual(decision.get("capability_domain"), "deployment")
        self.assertEqual(decision.get("recommendation"), "forbidden_core_coupling")
        self.assertIn("provider_specific_core_coupling_detected", decision.get("warnings") or [])
        self.assertTrue(bool(decision.get("forbidden_core_targets")))

    def test_deployment_provider_contract_summary_exposes_extension_seam(self):
        summary = deployment_provider_contract_summary()
        self.assertEqual(summary.get("policy_version"), "xyn.architecture_placement.v1")
        contracts = summary.get("contracts") if isinstance(summary.get("contracts"), list) else []
        aws_contract = next(
            (row for row in contracts if isinstance(row, dict) and row.get("provider_key") == "aws_ssm_route53"),
            None,
        )
        self.assertIsNotNone(aws_contract)
        self.assertTrue(bool((aws_contract or {}).get("artifact_extension_expected")))
