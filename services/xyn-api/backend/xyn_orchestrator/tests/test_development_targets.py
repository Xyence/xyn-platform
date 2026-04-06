import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase

from xyn_orchestrator.development_targets import resolve_development_target
from xyn_orchestrator.models import (
    Application,
    ApplicationArtifactMembership,
    Artifact,
    ArtifactType,
    DevTask,
    Goal,
    Workspace,
)


class DevelopmentTargetResolutionTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username=f"dev-target-{uuid.uuid4().hex[:8]}",
            email=f"dev-target-{uuid.uuid4().hex[:8]}@example.com",
            password="password",
        )
        self.workspace = Workspace.objects.create(slug=f"ws-{uuid.uuid4().hex[:8]}", name="Workspace")
        self.artifact_type, _ = ArtifactType.objects.get_or_create(
            slug="application",
            defaults={"name": "Application", "description": "Generated app artifact."},
        )

    def _task(self, **overrides) -> DevTask:
        defaults = {
            "title": "Implement task",
            "description": "Resolve target",
            "task_type": "codegen",
            "status": "queued",
            "priority": 0,
            "source_entity_type": "manual",
            "source_entity_id": uuid.uuid4(),
            "created_by": self.user,
            "updated_by": self.user,
        }
        defaults.update(overrides)
        return DevTask.objects.create(**defaults)

    def test_resolve_development_target_uses_artifact_ownership(self):
        artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=self.artifact_type,
            title="Runtime Core",
            slug=f"app-runtime-{uuid.uuid4().hex[:6]}",
            owner_repo_slug="xyn",
            owner_path_prefixes_json=["services/runtime/", "services/common/"],
            edit_mode="repo_backed",
        )
        task = self._task(source_entity_type="artifact", source_entity_id=artifact.id)

        resolution = resolve_development_target(task=task)

        self.assertEqual(resolution.source_kind, "artifact_ownership")
        self.assertEqual(resolution.repository_slug, "xyn")
        self.assertEqual(resolution.allowed_paths, ("services/runtime/", "services/common/"))
        self.assertIsNone(resolution.unresolved_reason)

    def test_resolve_development_target_errors_when_artifacts_span_multiple_repositories(self):
        first = Artifact.objects.create(
            workspace=self.workspace,
            type=self.artifact_type,
            title="UI",
            slug=f"app-ui-{uuid.uuid4().hex[:6]}",
            owner_repo_slug="xyn-platform",
            owner_path_prefixes_json=["apps/xyn-ui/"],
            edit_mode="repo_backed",
        )
        second = Artifact.objects.create(
            workspace=self.workspace,
            type=self.artifact_type,
            title="Runtime",
            slug=f"app-runtime-{uuid.uuid4().hex[:6]}",
            owner_repo_slug="xyn",
            owner_path_prefixes_json=["services/runtime/"],
            edit_mode="repo_backed",
        )
        application = Application.objects.create(
            workspace=self.workspace,
            name="Composite",
            summary="",
            source_factory_key="manual",
            source_conversation_id="",
            status="active",
            request_objective="",
            metadata_json={},
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=first,
            role="primary_ui",
        )
        ApplicationArtifactMembership.objects.create(
            workspace=self.workspace,
            application=application,
            artifact=second,
            role="supporting",
            sort_order=10,
        )
        goal = Goal.objects.create(
            workspace=self.workspace,
            application=application,
            title="Goal",
            description="",
            source_conversation_id="",
            goal_type="build_system",
            planning_status="proposed",
            priority="normal",
        )
        task = self._task(goal=goal)

        resolution = resolve_development_target(task=task)

        self.assertIsNone(resolution.repository_slug)
        self.assertEqual(resolution.unresolved_reason, "multiple_artifact_repositories")

    def test_resolve_development_target_fails_without_artifact_context(self):
        task = self._task()

        resolution = resolve_development_target(task=task)

        self.assertIsNone(resolution.repository_slug)
        self.assertEqual(resolution.source_kind, "unresolved")
        self.assertEqual(resolution.unresolved_reason, "artifact_context_missing")
