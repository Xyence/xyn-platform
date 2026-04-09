from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from xyn_orchestrator.runtime_repo_map_validation import validate_runtime_repo_map_targets


class RuntimeRepoMapValidationTests(SimpleTestCase):
    def setUp(self) -> None:
        self._prev_map = os.environ.get("XYN_RUNTIME_REPO_MAP")
        self._tempdirs: list[str] = []

    def tearDown(self) -> None:
        if self._prev_map is None:
            os.environ.pop("XYN_RUNTIME_REPO_MAP", None)
        else:
            os.environ["XYN_RUNTIME_REPO_MAP"] = self._prev_map
        for row in self._tempdirs:
            shutil.rmtree(row, ignore_errors=True)

    def _temp_repo(self) -> Path:
        tmpdir = tempfile.mkdtemp(prefix="runtime-repo-map-")
        self._tempdirs.append(tmpdir)
        subprocess.run(["git", "init", "-b", "main"], cwd=tmpdir, check=True, capture_output=True, text=True)
        return Path(tmpdir)

    def test_reports_missing_targets(self) -> None:
        os.environ["XYN_RUNTIME_REPO_MAP"] = '{"xyn-platform":["/definitely/missing/path"]}'
        warnings = validate_runtime_repo_map_targets()
        self.assertEqual(len(warnings), 1)
        self.assertIn("repo 'xyn-platform'", warnings[0])

    def test_accepts_existing_git_target(self) -> None:
        repo = self._temp_repo()
        os.environ["XYN_RUNTIME_REPO_MAP"] = f'{{"xyn-platform":["{repo}"]}}'
        warnings = validate_runtime_repo_map_targets()
        self.assertEqual(warnings, [])

    def test_reports_unreadable_target(self) -> None:
        repo = self._temp_repo()
        os.environ["XYN_RUNTIME_REPO_MAP"] = f'{{"xyn-platform":["{repo}"]}}'
        with mock.patch("xyn_orchestrator.runtime_repo_map_validation.os.access", return_value=False):
            warnings = validate_runtime_repo_map_targets()
        self.assertEqual(len(warnings), 1)
        self.assertIn("not_readable", warnings[0])
