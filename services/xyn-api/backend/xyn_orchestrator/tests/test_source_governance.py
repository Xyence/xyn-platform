import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from xyn_orchestrator.models import PlatformAuditEvent, SourceConnector, UserIdentity, Workspace
from xyn_orchestrator.source_governance import SourceGovernanceService, normalize_governance_policy


class SourceGovernanceTests(TestCase):
    def setUp(self):
        suffix = uuid.uuid4().hex[:8]
        self.workspace = Workspace.objects.create(slug=f"governance-{suffix}", name="Governance Workspace")
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example",
            subject=f"governance-{suffix}",
            email=f"governance-{suffix}@example.com",
        )
        self.service = SourceGovernanceService()

    def _source(self, governance: dict) -> SourceConnector:
        return SourceConnector.objects.create(
            workspace=self.workspace,
            key=f"source-{uuid.uuid4().hex[:6]}",
            name="Governed Source",
            source_mode="remote_url",
            governance_json=governance,
        )

    def test_governance_contract_validation_rejects_unknown_method(self):
        with self.assertRaises(ValueError):
            normalize_governance_policy(
                {
                    "allowed_ingestion_methods": ["ftp_sync"],
                    "legal_status": "allowed",
                },
                strict=True,
            )

    def test_prohibited_source_denies_execution(self):
        source = self._source({"legal_status": "prohibited"})
        decision = self.service.evaluate(source=source, action="run_source")
        self.assertEqual(decision.decision, "deny")
        self.assertEqual(decision.reason_code, "governance.legal_prohibited")

    def test_review_required_defers_until_approved(self):
        source = self._source({"review_required": True})
        before = self.service.evaluate(source=source, action="run_source")
        self.assertEqual(before.decision, "defer")
        source.review_approved = True
        source.review_approved_by = self.identity
        source.review_approved_at = timezone.now()
        source.save(update_fields=["review_approved", "review_approved_at", "review_approved_by", "updated_at"])
        after = self.service.evaluate(source=source, action="run_source")
        self.assertEqual(after.decision, "allow")

    def test_browser_automation_denied_by_default(self):
        source = self._source({"allowed_ingestion_methods": ["browser_automation"]})
        decision = self.service.evaluate(source=source, action="browser_automation")
        self.assertEqual(decision.decision, "deny")
        self.assertEqual(decision.reason_code, "governance.browser_automation_not_allowed")

    def test_freshness_status_is_stale_when_interval_exceeded(self):
        source = self._source({"expected_refresh_interval_seconds": 60})
        source.last_success_at = timezone.now() - timedelta(minutes=5)
        source.save(update_fields=["last_success_at", "updated_at"])
        decision = self.service.evaluate(source=source, action="run_source")
        self.assertEqual(decision.freshness.status, "stale")
        self.assertGreaterEqual(int(decision.freshness.stale_by_seconds or 0), 1)

    def test_audit_event_emitted_for_denied_decision(self):
        source = self._source({"legal_status": "prohibited"})
        decision = self.service.evaluate(source=source, action="fetch_source")
        event = self.service.emit_audit_event(
            source=source,
            decision=decision,
            actor_id=str(self.identity.id),
            metadata={"test_case": "denied_fetch"},
        )
        self.assertEqual(event.event_type, "source_governance.denied_fetch")
        self.assertTrue(
            PlatformAuditEvent.objects.filter(id=event.id, event_type="source_governance.denied_fetch").exists()
        )
