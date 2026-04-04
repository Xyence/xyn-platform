from types import SimpleNamespace

from xyn_orchestrator import xyn_api
from django.test import SimpleTestCase


class SolutionPlacementGuidanceTests(SimpleTestCase):
    def test_impacted_analysis_includes_machine_readable_placement_guidance(self):
        membership = SimpleNamespace(
            id="member-1",
            role="runtime_service",
            responsibility_summary="Runtime deployment orchestration",
            artifact_id="artifact-1",
            artifact=SimpleNamespace(
                id="artifact-1",
                title="xyn-runtime",
                slug="core.xyn-runtime",
                summary="Runtime deploy coordination",
                owner_path_prefixes_json=[],
                edit_mode="generated",
                type=SimpleNamespace(slug="module"),
                type_id="type-1",
            ),
        )

        analysis = xyn_api._build_solution_impacted_analysis(
            application=SimpleNamespace(id="app-1"),
            request_text="Add AWS deployment provider support for runtime provisioning.",
            memberships=[membership],
        )

        guidance = analysis.get("placement_guidance") if isinstance(analysis, dict) else {}
        self.assertIsInstance(guidance, dict)
        self.assertEqual(guidance.get("policy_version"), "xyn.architecture_placement.v1")
        self.assertEqual(guidance.get("capability_domain"), "deployment")
        self.assertEqual(guidance.get("recommendation"), "provider_artifact_module")
        self.assertEqual(guidance.get("provider_strategy"), "provider_module_required")
        self.assertEqual(
            guidance.get("provider_specific_implementation_target"),
            "xyn_orchestrator.deployment_provider_contract",
        )
        placement = analysis.get("architectural_placement") if isinstance(analysis, dict) else {}
        self.assertIsInstance(placement, dict)
        self.assertEqual(placement.get("classification"), "provider_artifact_module")
