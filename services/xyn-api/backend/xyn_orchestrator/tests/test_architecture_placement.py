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
