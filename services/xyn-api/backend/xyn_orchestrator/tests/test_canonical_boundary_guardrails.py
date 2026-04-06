from pathlib import Path
import tempfile

from django.test import SimpleTestCase

from xyn_orchestrator.guardrails import scan_backend_canonical_drift
from xyn_orchestrator.models import WatchDefinition, WatchMatchEvent
from xyn_orchestrator.provenance import normalize_object_ref, object_ref, serialize_object_ref


class CanonicalBoundaryGuardrailTests(SimpleTestCase):
    def test_backend_guardrail_scan_has_no_findings(self):
        backend_root = Path(__file__).resolve().parents[2]
        findings = scan_backend_canonical_drift(backend_root)
        self.assertEqual([], findings, "\n".join(findings))

    def test_boundary_docs_state_canonical_run_and_lifecycle_seams(self):
        repo_root = Path(__file__).resolve().parents[5]
        run_history_doc = (repo_root / "docs" / "platform-run-history-boundaries.md").read_text(encoding="utf-8").lower()
        lifecycle_doc = (repo_root / "docs" / "platform-lifecycle-primitive.md").read_text(encoding="utf-8").lower()
        watch_doc = (repo_root / "docs" / "platform-watchlist-subscription-primitive.md").read_text(encoding="utf-8").lower()

        self.assertIn("canonical durable history substrate", run_history_doc)
        self.assertIn("orchestration run", run_history_doc)
        self.assertIn("xyn/core", lifecycle_doc)
        self.assertIn("compatibility", lifecycle_doc)
        self.assertIn("not a full campaign engine", watch_doc)

    def test_provenance_object_ref_shape_is_canonical(self):
        ref = object_ref(
            object_family=" Rule_Result ",
            object_id=" 42 ",
            workspace_id=" ws-1 ",
            namespace=" CRM ",
            attributes={"score": 0.9},
        )
        normalized = normalize_object_ref(ref)
        serialized = serialize_object_ref(
            {
                "object_family": normalized.object_family,
                "object_id": normalized.object_id,
                "workspace_id": normalized.workspace_id,
                "namespace": normalized.namespace,
                "attributes": normalized.attributes,
            }
        )
        self.assertEqual(
            {"object_family", "object_id", "workspace_id", "namespace", "attributes"},
            set(serialized.keys()),
        )
        self.assertEqual("rule_result", serialized["object_family"])
        self.assertEqual("42", serialized["object_id"])

    def test_watch_campaign_boundary_stays_adapter_like(self):
        watch_fields = {field.name for field in WatchDefinition._meta.fields}
        match_fields = {field.name for field in WatchMatchEvent._meta.fields}

        self.assertIn("linked_campaign", watch_fields)
        self.assertNotIn("campaign", match_fields)
        self.assertIn("watch", match_fields)

    def test_guardrail_flags_provider_specific_deployment_logic_outside_allowed_core_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            backend_root = Path(tmpdir)
            runtime_root = backend_root / "xyn_orchestrator"
            runtime_root.mkdir(parents=True, exist_ok=True)
            bad_file = runtime_root / "deployment_helpers.py"
            bad_file.write_text(
                "\n".join(
                    [
                        "import boto3",
                        "def deploy_runtime():",
                        "    return boto3.client('ssm').send_command(DocumentName='AWS-RunShellScript')",
                    ]
                ),
                encoding="utf-8",
            )
            findings = scan_backend_canonical_drift(backend_root)
            self.assertTrue(any("provider-specific deployment markers" in item for item in findings), findings)
