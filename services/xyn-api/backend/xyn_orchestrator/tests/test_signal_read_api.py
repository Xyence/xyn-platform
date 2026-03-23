import json
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from xyn_orchestrator import models
from xyn_orchestrator.signal_read_model import SignalReadProjectionService
from xyn_orchestrator.xyn_api import (
    monitoring_funnel_summary,
    parcel_crosswalks_reresolve_source,
    signal_detail,
    signals_collection,
    signals_project_domain_events,
    watch_matches_collection,
)


class SignalReadApiTests(TestCase):
    def setUp(self):
        suffix = uuid.uuid4().hex[:8]
        self.factory = RequestFactory()
        self.workspace = models.Workspace.objects.create(slug=f"signal-{suffix}", name="Signal Workspace")
        self.source = models.SourceConnector.objects.create(
            workspace=self.workspace,
            key=f"source-{suffix}",
            name="Event Source",
            source_type="distress_events",
            source_mode="remote_url",
        )
        self.pipeline = models.OrchestrationPipeline.objects.create(
            workspace=self.workspace,
            key=f"pipeline-{suffix}",
            name="Pipeline",
        )
        self.run = models.OrchestrationRun.objects.create(
            workspace=self.workspace,
            pipeline=self.pipeline,
            trigger_cause="manual",
            trigger_key="test",
            scope_jurisdiction="mo-stl-city",
            scope_source=self.source.key,
        )
        self.artifact = models.IngestArtifactRecord.objects.create(
            workspace=self.workspace,
            source_connector=self.source,
            orchestration_run=self.run,
            artifact_id=uuid.uuid4(),
            original_filename="events.csv",
            sha256="a" * 64,
        )
        self.campaign = models.Campaign.objects.create(
            workspace=self.workspace,
            slug=f"campaign-{suffix}",
            name="Campaign",
            campaign_type="generic",
            status="active",
        )
        self.watch = models.WatchDefinition.objects.create(
            workspace=self.workspace,
            key=f"watch-{suffix}",
            name="Watch",
            target_kind="property",
            target_ref_json={"handle": "10174000016", "parcel_id": "parcel-1"},
            filter_criteria_json={"jurisdiction": "mo-stl-city"},
            lifecycle_state="active",
            linked_campaign=self.campaign,
        )

        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username=f"user-{suffix}",
            email=f"user-{suffix}@example.com",
            password="password",
        )
        self.identity = models.UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example",
            subject=f"user-{suffix}",
            email=f"user-{suffix}@example.com",
        )
        models.WorkspaceMembership.objects.create(workspace=self.workspace, user_identity=self.identity, role="admin")

    def _request(self, path: str, *, method: str = "get", data=None):
        request = getattr(self.factory, method.lower())(path, data=data or {}, content_type="application/json")
        request.user = self.user
        return request

    def test_signal_projection_and_query_surfaces(self):
        match = models.WatchMatchEvent.objects.create(
            workspace=self.workspace,
            watch=self.watch,
            event_key="csb.event.resolved",
            matched=True,
            score=1.0,
            reason="matched",
            explanation_json={},
            event_ref_json={
                "target_kind": "property",
                "jurisdiction": "mo-stl-city",
                "source": self.source.key,
                "handle": "10174000016",
                "parcel_id": "parcel-1",
            },
            filter_snapshot_json={"jurisdiction": "mo-stl-city"},
            notification_intent_json={},
            event_fingerprint="fingerprint",
            idempotency_key=f"match-{uuid.uuid4().hex}",
            scope_jurisdiction="mo-stl-city",
            reconciled_state_version="recon-v1",
            run=self.run,
        )
        domain_event = models.PlatformDomainEvent.objects.create(
            workspace=self.workspace,
            pipeline=self.pipeline,
            run=self.run,
            event_type="signal.watch_match_detected",
            stage_key="signal_matching",
            scope_jurisdiction="mo-stl-city",
            scope_source=self.source.key,
            subject_ref_json={"kind": "watch_match_event", "id": str(match.id), "watch_id": str(self.watch.id)},
            payload_json={
                "watch_id": str(self.watch.id),
                "watch_match_event_id": str(match.id),
                "event_key": "csb.event.resolved",
                "reason": "matched",
                "event_ref": match.event_ref_json,
            },
            reconciled_state_version="recon-v1",
            signal_set_version="signal-v1",
            idempotency_key=f"event-{uuid.uuid4().hex}",
        )
        SignalReadProjectionService().project_domain_event(event=domain_event)
        signal_row = models.SignalReadModel.objects.get(workspace=self.workspace, domain_event=domain_event)

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            list_response = signals_collection(
                self._request(
                    "/xyn/api/signals",
                    data={
                        "workspace_id": str(self.workspace.id),
                        "watch_id": str(self.watch.id),
                        "campaign_id": str(self.campaign.id),
                        "handle": "10174000016",
                    },
                )
            )
        self.assertEqual(list_response.status_code, 200)
        body = json.loads(list_response.content)
        self.assertEqual(len(body["signals"]), 1)
        self.assertEqual(body["signals"][0]["id"], str(signal_row.id))

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            detail_response = signal_detail(
                self._request(
                    f"/xyn/api/signals/{signal_row.id}",
                    data={"workspace_id": str(self.workspace.id)},
                ),
                signal_id=str(signal_row.id),
            )
        self.assertEqual(detail_response.status_code, 200)
        detail_body = json.loads(detail_response.content)
        self.assertEqual(detail_body["watch_id"], str(self.watch.id))
        self.assertEqual(detail_body["campaign_id"], str(self.campaign.id))

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            matches_response = watch_matches_collection(
                self._request(
                    "/xyn/api/watches/matches",
                    data={"workspace_id": str(self.workspace.id), "campaign_id": str(self.campaign.id)},
                )
            )
        self.assertEqual(matches_response.status_code, 200)
        matches_body = json.loads(matches_response.content)
        self.assertEqual(len(matches_body["matches"]), 1)
        self.assertEqual(matches_body["matches"][0]["watch_id"], str(self.watch.id))

    def test_signals_project_domain_events_endpoint(self):
        match = models.WatchMatchEvent.objects.create(
            workspace=self.workspace,
            watch=self.watch,
            event_key="event",
            matched=True,
            score=1.0,
            reason="matched",
            explanation_json={},
            event_ref_json={"jurisdiction": "mo-stl-city", "source": self.source.key, "handle": "111"},
            filter_snapshot_json={},
            notification_intent_json={},
            event_fingerprint="fp",
            idempotency_key=f"match-{uuid.uuid4().hex}",
            scope_jurisdiction="mo-stl-city",
            reconciled_state_version="recon",
            run=self.run,
        )
        models.PlatformDomainEvent.objects.create(
            workspace=self.workspace,
            event_type="signal.watch_match_detected",
            stage_key="signal_matching",
            scope_jurisdiction="mo-stl-city",
            scope_source=self.source.key,
            subject_ref_json={"kind": "watch_match_event", "id": str(match.id)},
            payload_json={"watch_match_event_id": str(match.id), "event_ref": match.event_ref_json},
            idempotency_key=f"evt-{uuid.uuid4().hex}",
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = signals_project_domain_events(
                self._request(
                    "/xyn/api/signals/project",
                    method="post",
                    data=json.dumps({"workspace_id": str(self.workspace.id), "limit": 25}),
                )
            )
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body["count"], 1)
        self.assertEqual(models.SignalReadModel.objects.filter(workspace=self.workspace).count(), 1)

    def test_reresolve_source_endpoint_and_funnel_summary(self):
        adapted = models.IngestAdaptedRecord.objects.create(
            workspace=self.workspace,
            source_connector=self.source,
            orchestration_run=self.run,
            artifact=self.artifact,
            adapter_kind="json_http",
            source_format="json",
            adapted_payload_json={"attributes": {"HANDLE": "H-777"}},
            status="ok",
        )
        models.ParcelCrosswalkMapping.objects.create(
            workspace=self.workspace,
            source_connector=self.source,
            adapted_record=adapted,
            namespace="",
            identifier_value_raw="",
            identifier_value_normalized="",
            status="unresolved",
            resolution_method="unresolved",
            confidence=0.0,
            reason="missing identifiers",
            idempotency_key=f"cw-{uuid.uuid4().hex}",
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = parcel_crosswalks_reresolve_source(
                self._request(
                    "/xyn/api/parcel-crosswalks/reresolve-source",
                    method="post",
                    data=json.dumps(
                        {
                            "workspace_id": str(self.workspace.id),
                            "source_id": str(self.source.id),
                            "limit": 10,
                        }
                    ),
                )
            )
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertGreaterEqual(body["count"], 1)
        self.assertGreaterEqual(body["after"]["resolved"], 1)

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            funnel_response = monitoring_funnel_summary(
                self._request(
                    "/xyn/api/monitoring/funnel-summary",
                    data={"workspace_id": str(self.workspace.id), "source_id": str(self.source.id)},
                )
            )
        self.assertEqual(funnel_response.status_code, 200)
        funnel = json.loads(funnel_response.content)
        self.assertIn("counts", funnel)
        self.assertIn("crosswalk_method_counts", funnel)
        self.assertGreaterEqual(funnel["counts"]["adapted_rows"], 1)
