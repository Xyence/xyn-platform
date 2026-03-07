from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from django.test import SimpleTestCase


class ContextPackBridgeExportTests(SimpleTestCase):
    def test_export_manifest_contains_stable_runtime_slugs(self):
        backend_root = Path(__file__).resolve().parents[2]
        script = backend_root / "scripts" / "export_core_context_packs.py"
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "context-packs.manifest.json"
            result = subprocess.run(
                [sys.executable, str(script), "--output", str(output_path)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["manifest_version"], "xyn.context-pack-runtime-manifest.v1")
        pack_map = {row["slug"]: row for row in manifest["context_packs"]}
        self.assertIn("xyn-console-default", pack_map)
        self.assertIn("xyn-planner-canon", pack_map)
        self.assertTrue(pack_map["xyn-console-default"]["bind_by_default"])
        self.assertTrue(pack_map["xyn-planner-canon"]["bind_by_default"])
