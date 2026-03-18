import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase

from xyn_orchestrator.models import Artifact, ArtifactRevision, ArtifactType, RoleBinding, UserIdentity, Workspace


class RulesApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_user(username="rules-admin", password="pass", is_staff=True)
        self.admin_identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer",
            subject="rules-admin",
            email="rules-admin@example.com",
        )
        RoleBinding.objects.create(user_identity=self.admin_identity, scope_kind="platform", role="platform_admin")
        self.viewer_user = user_model.objects.create_user(username="rules-viewer", password="pass", is_staff=True)
        self.viewer_identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer",
            subject="rules-viewer",
            email="rules-viewer@example.com",
        )
        self.workspace, _ = Workspace.objects.get_or_create(slug="rules-ws", defaults={"name": "Rules Workspace"})
        self.policy_type, _ = ArtifactType.objects.get_or_create(slug="policy_bundle", defaults={"name": "Policy Bundle"})
        self.app_type, _ = ArtifactType.objects.get_or_create(slug="application", defaults={"name": "Application"})
        self._seed_policy_artifacts()
        self._login_identity(self.admin_user, self.admin_identity)

    def _login_identity(self, user, identity: UserIdentity):
        self.client.force_login(user)
        session = self.client.session
        session["user_identity_id"] = str(identity.id)
        session.save()

    def _seed_policy_artifacts(self):
        app_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=self.app_type,
            slug="app.team-lunch-poll",
            title="Team Lunch Poll",
            status="published",
            visibility="team",
        )
        ArtifactRevision.objects.create(
            artifact=app_artifact,
            revision_number=1,
            content_json={"schema_version": "xyn.app_spec.v1", "app_slug": "app.team-lunch-poll"},
            created_by=self.admin_identity,
        )
        policy_artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=self.policy_type,
            slug="policy.team-lunch-poll",
            title="Team Lunch Poll Policy Bundle",
            status="published",
            visibility="team",
        )
        ArtifactRevision.objects.create(
            artifact=policy_artifact,
            revision_number=1,
            content_json={
                "schema_version": "xyn.policy_bundle.v0",
                "bundle_id": "policy.team-lunch-poll",
                "app_slug": "app.team-lunch-poll",
                "workspace_id": str(self.workspace.id),
                "title": "Team Lunch Poll Policy Bundle",
                "description": "Policy bundle",
                "scope": {"artifact_slug": "app.team-lunch-poll", "applies_to": ["generated_runtime"]},
                "ownership": {"owner_kind": "generated_application", "editable": True, "source": "generated_from_prompt"},
                "policy_families": ["validation_policies", "invariant_policies"],
                "policies": {
                    "validation_policies": [
                        {
                            "id": "policy-1",
                            "name": "Vote gate",
                            "description": "Votes allowed when poll is open.",
                            "family": "validation_policies",
                            "status": "documented",
                            "enforcement_stage": "runtime_enforced",
                        }
                    ],
                    "relation_constraints": [],
                    "transition_policies": [],
                    "invariant_policies": [
                        {
                            "id": "policy-2",
                            "name": "One selected option",
                            "description": "At most one selected option per poll.",
                            "family": "invariant_policies",
                            "status": "documented",
                            "enforcement_stage": "runtime_enforced",
                        }
                    ],
                    "derived_policies": [],
                    "trigger_policies": [],
                },
                "configurable_parameters": [],
                "explanation": {
                    "summary": "Rules for generated app.",
                    "coverage": {"documented_policy_count": 2, "compiled_policy_count": 2},
                    "future_capabilities": ["render_policy_bundle"],
                },
            },
            created_by=self.admin_identity,
        )

        system_policy = Artifact.objects.create(
            workspace=self.workspace,
            type=self.policy_type,
            slug="policy.system-defaults",
            title="System Defaults Policy Bundle",
            status="published",
            visibility="team",
        )
        ArtifactRevision.objects.create(
            artifact=system_policy,
            revision_number=1,
            content_json={
                "schema_version": "xyn.policy_bundle.v0",
                "bundle_id": "policy.system-defaults",
                "app_slug": "app.system-defaults",
                "workspace_id": str(self.workspace.id),
                "title": "System Defaults Policy Bundle",
                "description": "Platform-level system policy",
                "scope": {"artifact_slug": "app.system-defaults", "applies_to": ["system"]},
                "ownership": {"owner_kind": "platform", "editable": False, "source": "platform_managed"},
                "policy_families": ["validation_policies"],
                "policies": {
                    "validation_policies": [
                        {
                            "id": str(uuid.uuid4()),
                            "name": "System guard",
                            "description": "Platform-only guardrail.",
                            "family": "validation_policies",
                            "status": "documented",
                            "enforcement_stage": "not_compiled",
                        }
                    ],
                    "relation_constraints": [],
                    "transition_policies": [],
                    "invariant_policies": [],
                    "derived_policies": [],
                    "trigger_policies": [],
                },
                "configurable_parameters": [],
                "explanation": {
                    "summary": "System defaults.",
                    "coverage": {"documented_policy_count": 1, "compiled_policy_count": 0},
                    "future_capabilities": [],
                },
            },
            created_by=self.admin_identity,
        )

    def test_rules_collection_returns_grouped_rules_for_target_app(self):
        response = self.client.get("/xyn/api/rules", {"artifact_slug": "app.team-lunch-poll"})
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        bundles = payload.get("bundles") or []
        self.assertTrue(any(row.get("bundle_id") == "policy.team-lunch-poll" for row in bundles))
        rules = payload.get("rules") or []
        self.assertGreaterEqual(len(rules), 2)
        self.assertTrue(any(row.get("family") == "validation_policies" for row in rules))
        self.assertTrue(any(row.get("family") == "invariant_policies" for row in rules))

    def test_rules_collection_supports_editable_filter(self):
        response = self.client.get("/xyn/api/rules", {"artifact_slug": "app.team-lunch-poll", "editable": "true"})
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        for row in payload.get("rules") or []:
            self.assertTrue(bool(row.get("editable")))

    def test_rules_collection_hides_platform_system_bundle_for_non_admin(self):
        self._login_identity(self.viewer_user, self.viewer_identity)
        response = self.client.get("/xyn/api/rules")
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        bundle_ids = {str(row.get("bundle_id") or "") for row in (payload.get("bundles") or [])}
        self.assertNotIn("policy.system-defaults", bundle_ids)
        self.assertGreaterEqual(int(((payload.get("access") or {}).get("filtered_out_bundles") or 0)), 1)
