import json
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from xyn_orchestrator.matching import DjangoMatchResultRepository, MatchableRecordRef, RecordMatchingService
from xyn_orchestrator.models import (
    PlatformAuditEvent,
    ProvenanceLink,
    SourceConnector,
    UserIdentity,
    WatchDefinition,
    Workspace,
    WorkspaceMembership,
)
from xyn_orchestrator.provenance import AuditEventInput, ObjectRef, ProvenanceLinkInput, ProvenanceService
from xyn_orchestrator.sources import SourceConnectorService, SourceInspectionInput, SourceMappingInput, SourceRegistration
from xyn_orchestrator.watching import WatchEvaluationInput, WatchRegistration, WatchService, WatchSubscriberInput
from xyn_orchestrator.xyn_api import audit_events_collection, provenance_links_collection


class AuditProvenancePrimitiveTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        suffix = uuid.uuid4().hex[:8]
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username=f"prov-admin-{suffix}",
            email=f"prov-admin-{suffix}@example.com",
            password="password",
        )
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example",
            subject=f"prov-admin-{suffix}",
            email=f"prov-admin-{suffix}@example.com",
        )
        self.workspace = Workspace.objects.create(slug=f"prov-{suffix}", name="Provenance Workspace")
        self.other_workspace = Workspace.objects.create(slug=f"prov-other-{suffix}", name="Other Provenance Workspace")
        WorkspaceMembership.objects.create(workspace=self.workspace, user_identity=self.identity, role="admin")

    def _request(self, path: str, *, method: str = "get", data=None):
        request = getattr(self.factory, method.lower())(path, data=data or {}, content_type="application/json")
        request.user = self.user
        return request

    def test_record_and_query_audit_and_provenance(self):
        service = ProvenanceService()
        event = service.record_audit_event(
            AuditEventInput(
                workspace_id=str(self.workspace.id),
                event_type="import.completed",
                subject_ref=ObjectRef(object_family="dataset", object_id="records-v1", workspace_id=str(self.workspace.id)),
                summary="Import completed",
                reason="Source refresh succeeded",
                metadata={"changed_rows": 11},
                correlation_id="corr-1",
                chain_id="chain-1",
            )
        )
        link = service.record_provenance_link(
            ProvenanceLinkInput(
                workspace_id=str(self.workspace.id),
                relationship_type="derived_from",
                source_ref=ObjectRef(object_family="source_file", object_id="file-1", workspace_id=str(self.workspace.id)),
                target_ref=ObjectRef(object_family="dataset", object_id="records-v1", workspace_id=str(self.workspace.id)),
                reason="normalized import",
                explanation={"stage": "normalize"},
                origin_event_id=str(event.id),
                correlation_id="corr-1",
                chain_id="chain-1",
            )
        )

        self.assertEqual(event.event_type, "import.completed")
        self.assertEqual(link.relationship_type, "derived_from")

        history = list(
            service.audit_history(
                workspace_id=str(self.workspace.id),
                object_type="dataset",
                object_id="records-v1",
            )
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].id, event.id)

        upstream = list(
            service.provenance_for_object(
                workspace_id=str(self.workspace.id),
                object_type="dataset",
                object_id="records-v1",
                direction="upstream",
            )
        )
        self.assertEqual(len(upstream), 1)
        self.assertEqual(upstream[0].id, link.id)

    def test_matching_and_watch_integrations_emit_audit_and_provenance(self):
        matching = RecordMatchingService(repository=DjangoMatchResultRepository())
        a = MatchableRecordRef(
            source_namespace="crm",
            source_record_type="contact",
            source_record_id="left-1",
            workspace_id=str(self.workspace.id),
            attributes={"name": "Jane Doe", "external_id": "jane-1"},
        )
        b = MatchableRecordRef(
            source_namespace="billing",
            source_record_type="account_contact",
            source_record_id="right-2",
            workspace_id=str(self.workspace.id),
            attributes={"name": "Jane Doe", "external_id": "JANE1"},
        )
        matching.evaluate_pair(
            workspace_id=str(self.workspace.id),
            candidate_a=a,
            candidate_b=b,
            strategy_key="weighted_composite",
            persist=True,
            metadata={"trigger": "test"},
        )

        self.assertTrue(
            PlatformAuditEvent.objects.filter(workspace=self.workspace, event_type="record_matching.evaluated").exists()
        )
        self.assertEqual(
            ProvenanceLink.objects.filter(
                workspace=self.workspace,
                relationship_type="match_evaluated_from",
            ).count(),
            2,
        )

        watch_service = WatchService()
        watch = watch_service.register_watch(
            WatchRegistration(
                workspace_id=str(self.workspace.id),
                key="north-watch",
                name="North Watch",
                target_kind="area",
                target_ref={"region": "north"},
                filter_criteria={"event_type": "change"},
                lifecycle_state="active",
                created_by_id=str(self.identity.id),
            )
        )
        watch_service.add_subscriber(
            WatchSubscriberInput(
                watch_id=str(watch.id),
                subscriber_type="user_identity",
                subscriber_ref=str(self.identity.id),
            )
        )
        rows = watch_service.evaluate(
            WatchEvaluationInput(
                workspace_id=str(self.workspace.id),
                event_key="event-1",
                event_ref={"target_kind": "area", "region": "north", "event_type": "change", "object_type": "parcel", "object_id": "p-1"},
                correlation_id="corr-watch",
                chain_id="chain-watch",
            ),
            persist=True,
        )
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].matched)
        self.assertTrue(PlatformAuditEvent.objects.filter(workspace=self.workspace, event_type="watch.evaluated").exists())
        self.assertTrue(
            ProvenanceLink.objects.filter(workspace=self.workspace, relationship_type="watch_match_emitted_from_watch").exists()
        )

    def test_source_connector_lifecycle_actions_emit_audit_events(self):
        service = SourceConnectorService()
        source = service.register_source(
            SourceRegistration(
                workspace_id=str(self.workspace.id),
                key="county-feed",
                name="County Feed",
                source_type="records_feed",
                source_mode="manual",
                created_by_id=str(self.identity.id),
            )
        )
        service.record_inspection(
            SourceInspectionInput(
                source_id=str(source.id),
                status="ok",
                detected_format="csv",
                discovered_fields=[{"name": "parcel_id", "type": "string"}],
                inspected_by_id=str(self.identity.id),
            )
        )
        service.update_mapping(
            SourceMappingInput(
                source_id=str(source.id),
                status="validated",
                field_mapping={"parcel_id": "source.parcel_id"},
                validation_state={"ok": True},
                validated_by_id=str(self.identity.id),
            )
        )
        service.activate_source(source_id=str(source.id))
        service.pause_source(source_id=str(source.id))
        service.update_health(
            payload=type(
                "H",
                (),
                {
                    "source_id": str(source.id),
                    "health_status": "failing",
                    "lifecycle_state": None,
                    "success": False,
                    "failure_reason": "timeout",
                    "run_id": "",
                },
            )()
        )
        event_types = set(
            PlatformAuditEvent.objects.filter(workspace=self.workspace, subject_type="source_connector").values_list(
                "event_type", flat=True
            )
        )
        self.assertIn("source_connector.activated", event_types)
        self.assertIn("source_connector.paused", event_types)
        self.assertIn("source_connector.health_updated", event_types)
        self.assertTrue(SourceConnector.objects.filter(workspace=self.workspace, key="county-feed").exists())

    def test_api_visibility_and_workspace_isolation(self):
        service = ProvenanceService()
        event = service.record_audit_event(
            AuditEventInput(
                workspace_id=str(self.workspace.id),
                event_type="rule.evaluated",
                subject_ref=ObjectRef(object_family="rule_result", object_id="r-1", workspace_id=str(self.workspace.id)),
                summary="Rule evaluated",
            )
        )
        service.record_provenance_link(
            ProvenanceLinkInput(
                workspace_id=str(self.workspace.id),
                relationship_type="caused_by",
                source_ref=ObjectRef(object_family="rule", object_id="rule-1", workspace_id=str(self.workspace.id)),
                target_ref=ObjectRef(object_family="rule_result", object_id="r-1", workspace_id=str(self.workspace.id)),
                origin_event_id=str(event.id),
            )
        )

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            events_response = audit_events_collection(
                self._request(
                    "/xyn/api/audit-events",
                    data={"workspace_id": str(self.workspace.id), "object_type": "rule_result", "object_id": "r-1"},
                )
            )
        self.assertEqual(events_response.status_code, 200)
        events_payload = json.loads(events_response.content)
        self.assertEqual(len(events_payload["events"]), 1)

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            links_response = provenance_links_collection(
                self._request(
                    "/xyn/api/provenance-links",
                    data={
                        "workspace_id": str(self.workspace.id),
                        "object_type": "rule_result",
                        "object_id": "r-1",
                        "direction": "upstream",
                    },
                )
            )
        self.assertEqual(links_response.status_code, 200)
        links_payload = json.loads(links_response.content)
        self.assertEqual(len(links_payload["links"]), 1)

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            forbidden = audit_events_collection(
                self._request(
                    "/xyn/api/audit-events",
                    data={"workspace_id": str(self.other_workspace.id)},
                )
            )
        self.assertEqual(forbidden.status_code, 403)

    def test_object_reference_normalization(self):
        ref = ObjectRef(object_family="  RULE_Result ", object_id="  42 ", namespace=" CRM ")
        normalized = ref.normalized_family(), ref.normalized_id()
        self.assertEqual(normalized[0], "rule_result")
        self.assertEqual(normalized[1], "42")

