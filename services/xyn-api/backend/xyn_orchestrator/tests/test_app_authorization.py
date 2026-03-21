from django.test import TestCase

from xyn_orchestrator.app_authorization import (
    CAP_CAMPAIGNS_MANAGE,
    CAP_SOURCES_MANAGE,
    ROLE_APPLICATION_ADMIN,
    ROLE_CAMPAIGN_OPERATOR,
    ROLE_READ_ONLY_ANALYST,
    canonical_model_payload,
    effective_app_roles,
    effective_capabilities_for_roles,
    has_required_capabilities,
)


class AppAuthorizationTests(TestCase):
    def test_effective_roles_include_workspace_platform_and_explicit(self):
        roles = effective_app_roles(
            workspace_role="contributor",
            platform_roles=["platform_admin"],
            explicit_roles=[ROLE_READ_ONLY_ANALYST],
        )
        self.assertEqual(
            roles,
            sorted([ROLE_APPLICATION_ADMIN, ROLE_CAMPAIGN_OPERATOR, ROLE_READ_ONLY_ANALYST]),
        )

    def test_has_required_capabilities(self):
        caps = effective_capabilities_for_roles([ROLE_CAMPAIGN_OPERATOR])
        self.assertTrue(
            has_required_capabilities(
                effective_capabilities=caps,
                required_capabilities=[CAP_CAMPAIGNS_MANAGE],
            )
        )
        self.assertFalse(
            has_required_capabilities(
                effective_capabilities=caps,
                required_capabilities=[CAP_SOURCES_MANAGE],
            )
        )

    def test_canonical_payload_includes_roles_and_mappings(self):
        payload = canonical_model_payload()
        self.assertEqual(payload["schema_version"], "xyn.application_access_model.v1")
        self.assertIn("roles", payload)
        self.assertIn(ROLE_APPLICATION_ADMIN, payload["roles"])
        self.assertIn("workspace_role_mapping", payload)
        self.assertIn("platform_role_mapping", payload)
