from __future__ import annotations

import json
import tempfile
from pathlib import Path

from django.test import TestCase

from xyn_orchestrator.models import Artifact, ArtifactType, Workspace, WorkspaceArtifactBinding


class PublicRootResolutionTests(TestCase):
    def setUp(self):
        self.workspace = Workspace.objects.create(name="Development", slug="development")
        self.module_type, _ = ArtifactType.objects.get_or_create(slug="module", defaults={"name": "Module"})
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)

    def _write_manifest(self, payload: dict) -> str:
        path = Path(self._tmpdir.name) / f"{len(list(Path(self._tmpdir.name).glob('*.json'))) + 1}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    def _create_bound_artifact(self, *, slug: str, manifest: dict) -> Artifact:
        artifact = Artifact.objects.create(
            workspace=self.workspace,
            type=self.module_type,
            title=slug,
            slug=slug,
            status="published",
            visibility="team",
            scope_json={"manifest_ref": self._write_manifest(manifest), "slug": slug},
        )
        WorkspaceArtifactBinding.objects.create(
            workspace=self.workspace,
            artifact=artifact,
            enabled=True,
            installed_state="installed",
        )
        return artifact

    def test_returns_private_when_no_active_global_root_owner(self):
        self._create_bound_artifact(
            slug="workspace-only-ui",
            manifest={
                "artifact": {"id": "workspace-only-ui"},
                "roles": [{"role": "ui_mount", "scope": "workspace", "mount_path": "/"}],
                "surfaces": {"nav": [{"label": "Home", "path": "/"}]},
            },
        )

        response = self.client.get("/xyn/api/public/root-resolution")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"mode": "private"})

    def test_returns_public_when_active_global_root_owner_exists(self):
        artifact = self._create_bound_artifact(
            slug="public-root",
            manifest={
                "artifact": {"id": "public-root"},
                "roles": [{"role": "ui_mount", "scope": "global", "mount_path": "/"}],
                "surfaces": {"nav": [{"label": "Home", "path": "/"}]},
            },
        )

        response = self.client.get("/xyn/api/public/root-resolution")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "mode": "public",
                "owner_artifact_slug": "public-root",
                "owner_artifact_id": str(artifact.id),
            },
        )
