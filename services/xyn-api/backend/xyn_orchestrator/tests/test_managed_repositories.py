import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase

from xyn_orchestrator.managed_repositories import (
    ManagedRepositoryError,
    ensure_repository_materialized,
    materialize_repository_workspace,
    register_managed_repository,
    repository_cache_path,
)
from xyn_orchestrator.managed_storage import codegen_task_workspace
from xyn_orchestrator.models import ManagedRepository
from xyn_orchestrator.worker_tasks import _ensure_repo_workspace


class ManagedRepositoryTests(TestCase):
    def setUp(self):
        self._tempdirs: list[tempfile.TemporaryDirectory[str]] = []

    def tearDown(self):
        for tempdir in reversed(self._tempdirs):
            tempdir.cleanup()

    def _tmpdir(self) -> str:
        tempdir = tempfile.TemporaryDirectory()
        self._tempdirs.append(tempdir)
        return tempdir.name

    def _seed_remote_repo(self, *, branch: str = "main") -> tuple[Path, Path]:
        root = Path(self._tmpdir())
        source = root / "source"
        remote = root / "remote.git"
        source.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-b", branch], cwd=source, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=source, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=source, check=True)
        (source / "README.md").write_text("initial\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=source, check=True, capture_output=True, text=True)
        subprocess.run(["git", "init", "--bare", remote], check=True, capture_output=True, text=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=source, check=True)
        subprocess.run(["git", "push", "-u", "origin", branch], cwd=source, check=True, capture_output=True, text=True)
        return source, remote

    def _commit_remote_change(self, source: Path, *, filename: str = "README.md", content: str = "updated\n", branch: str = "main") -> None:
        (source / filename).write_text(content, encoding="utf-8")
        subprocess.run(["git", "add", filename], cwd=source, check=True)
        subprocess.run(["git", "commit", "-m", "update"], cwd=source, check=True, capture_output=True, text=True)
        subprocess.run(["git", "push", "origin", branch], cwd=source, check=True, capture_output=True, text=True)

    def test_register_managed_repository_is_idempotent(self):
        repository = register_managed_repository(
            slug="xyn-platform",
            remote_url="https://example.com/xyn-platform.git",
            default_branch="develop",
            auth_mode="https_token",
            display_name="Xyn Platform",
        )
        second = register_managed_repository(
            slug="xyn-platform",
            remote_url="https://example.com/xyn-platform.git",
            default_branch="develop",
            auth_mode="https_token",
            display_name="Xyn Platform",
        )
        self.assertEqual(repository.id, second.id)
        self.assertEqual(ManagedRepository.objects.count(), 1)
        self.assertEqual(second.default_branch, "develop")

    def test_repository_materialization_clones_and_refreshes_cache(self):
        source, remote = self._seed_remote_repo()
        workspace_root = self._tmpdir()
        with mock.patch.dict("os.environ", {"XYN_WORKSPACE_ROOT": workspace_root}, clear=False):
            materialized = ensure_repository_materialized(
                {
                    "name": "xyn-platform",
                    "url": str(remote),
                    "ref": "main",
                    "auth": "local",
                }
            )
            cache_path = materialized.cache_path
            self.assertTrue((cache_path / ".git").exists())
            self.assertEqual((cache_path / "README.md").read_text(encoding="utf-8"), "initial\n")
            self.assertEqual(cache_path, repository_cache_path(materialized.repository))

            self._commit_remote_change(source, content="updated from remote\n")
            refreshed = ensure_repository_materialized(materialized.repository, refresh=True)
            self.assertEqual(refreshed.cache_path, cache_path)
            self.assertEqual((cache_path / "README.md").read_text(encoding="utf-8"), "updated from remote\n")
            materialized.repository.refresh_from_db()
            self.assertTrue(materialized.repository.local_cache_relpath.startswith("repositories/cache/"))
            self.assertIsNotNone(materialized.repository.last_synced_at)

    def test_repository_workspace_materializes_under_managed_workspace_root(self):
        _source, remote = self._seed_remote_repo()
        workspace_root = self._tmpdir()
        with mock.patch.dict("os.environ", {"XYN_WORKSPACE_ROOT": workspace_root}, clear=False):
            task_workspace = codegen_task_workspace("task-77", reset=True)
            repo_workspace = materialize_repository_workspace(
                {
                    "name": "xyn-platform",
                    "url": str(remote),
                    "ref": "main",
                    "auth": "local",
                },
                workspace_root=task_workspace,
                reset=False,
            )
            self.assertTrue(str(repo_workspace).startswith(str(task_workspace)))
            self.assertTrue((repo_workspace / ".git").exists())
            self.assertTrue((repo_workspace / ".xyn-repository.json").exists())
            self.assertEqual((repo_workspace / "README.md").read_text(encoding="utf-8"), "initial\n")
            second = materialize_repository_workspace("xyn-platform", workspace_root=task_workspace, reset=False)
            self.assertEqual(repo_workspace, second)

    def test_worker_repo_workspace_uses_managed_repository_materialization_when_available(self):
        _source, remote = self._seed_remote_repo()
        workspace_root = self._tmpdir()
        with mock.patch.dict("os.environ", {"XYN_WORKSPACE_ROOT": workspace_root}, clear=False):
            task_workspace = codegen_task_workspace("task-worker", reset=True)
            repo_dir = Path(
                _ensure_repo_workspace(
                    {
                        "name": "xyn-platform",
                        "url": str(remote),
                        "ref": "main",
                        "auth": "local",
                    },
                    str(task_workspace),
                )
            )
            self.assertTrue(str(repo_dir).startswith(str(task_workspace / "repos")))
            self.assertTrue((repo_dir / ".git").exists())
            self.assertEqual(ManagedRepository.objects.filter(slug="xyn-platform").count(), 1)
            self.assertTrue((Path(workspace_root) / "repositories" / "cache" / "xyn-platform" / ".git").exists())

    def test_worker_repo_workspace_falls_back_to_direct_clone_when_registry_materialization_fails(self):
        _source, remote = self._seed_remote_repo()
        workspace_root = Path(self._tmpdir())
        workspace_root.mkdir(parents=True, exist_ok=True)
        with mock.patch("xyn_orchestrator.worker_tasks.materialize_repository_workspace", side_effect=ManagedRepositoryError("boom")):
            repo_dir = Path(
                _ensure_repo_workspace(
                    {
                        "name": "fallback-repo",
                        "url": str(remote),
                        "ref": "main",
                        "auth": "local",
                    },
                    str(workspace_root),
                )
            )
        self.assertEqual(repo_dir, workspace_root / "fallback-repo")
        self.assertTrue((repo_dir / ".git").exists())
