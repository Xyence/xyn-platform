import json
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from xyn_orchestrator.models import SourceConnector, UserIdentity, Workspace, WorkspaceMembership
from xyn_orchestrator.ingestion import IngestionExecutionResult
from xyn_orchestrator.xyn_api import (
    source_connector_activate,
    source_connector_detail,
    source_connector_health_update,
    source_connector_inspections_collection,
    source_connector_mappings_collection,
    source_connector_pause,
    source_connector_refresh,
    source_connectors_collection,
)


class SourceConnectorApiTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        suffix = uuid.uuid4().hex[:8]
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username=f"source-admin-{suffix}",
            email=f"source-admin-{suffix}@example.com",
            password="password",
        )
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example",
            subject=f"source-admin-{suffix}",
            email=f"source-admin-{suffix}@example.com",
        )
        self.operator_identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example",
            subject=f"source-operator-{suffix}",
            email=f"source-operator-{suffix}@example.com",
        )
        self.workspace = Workspace.objects.create(slug=f"sources-{suffix}", name="Sources Workspace")
        self.other_workspace = Workspace.objects.create(slug=f"sources-other-{suffix}", name="Other Sources Workspace")
        WorkspaceMembership.objects.create(workspace=self.workspace, user_identity=self.identity, role="admin")
        WorkspaceMembership.objects.create(workspace=self.workspace, user_identity=self.operator_identity, role="contributor")

    def _request(self, path: str, *, method: str = "get", data=None):
        request = getattr(self.factory, method.lower())(path, data=data or {}, content_type="application/json")
        request.user = self.user
        return request

    def _create_source(self, *, mode: str = "manual") -> dict:
        allowed_method = {
            "manual": "manual",
            "file_upload": "upload",
            "remote_url": "download",
            "api_polling": "api",
        }.get(mode, "manual")
        payload = {
            "workspace_id": str(self.workspace.id),
            "key": f"source-{uuid.uuid4().hex[:6]}",
            "name": "County Feed",
            "source_type": "records_feed",
            "source_mode": mode,
            "refresh_cadence_seconds": 3600 if mode in {"remote_url", "api_polling"} else 0,
            "configuration": {"url": "https://example.com/feed.csv"} if mode != "manual" else {},
            "governance": {"allowed_ingestion_methods": [allowed_method], "legal_status": "allowed"},
            "provenance": {"origin_url": "https://example.com/feed.csv"},
        }
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = source_connectors_collection(
                self._request("/xyn/api/source-connectors", method="post", data=json.dumps(payload))
            )
        self.assertEqual(response.status_code, 201)
        return json.loads(response.content)

    def test_register_and_list_sources(self):
        source = self._create_source(mode="file_upload")
        self.assertEqual(source["lifecycle_state"], "registered")
        self.assertEqual(source["source_mode"], "file_upload")
        self.assertIn("governance_status", source)
        self.assertEqual(source["governance"]["legal_status"], "allowed")

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = source_connectors_collection(
                self._request(
                    "/xyn/api/source-connectors",
                    data={"workspace_id": str(self.workspace.id), "source_mode": "file_upload"},
                )
            )
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(len(payload["sources"]), 1)
        self.assertEqual(payload["sources"][0]["id"], source["id"])

    def test_inspection_mapping_readiness_activate_and_pause(self):
        source = self._create_source(mode="remote_url")

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            not_ready = source_connector_activate(
                self._request(
                    f"/xyn/api/source-connectors/{source['id']}/activate",
                    method="post",
                    data=json.dumps({"workspace_id": str(self.workspace.id)}),
                ),
                source["id"],
            )
        self.assertEqual(not_ready.status_code, 409)

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            inspect_response = source_connector_inspections_collection(
                self._request(
                    f"/xyn/api/source-connectors/{source['id']}/inspections",
                    method="post",
                    data=json.dumps(
                        {
                            "workspace_id": str(self.workspace.id),
                            "status": "ok",
                            "detected_format": "csv",
                            "discovered_fields": [{"name": "parcel_id", "type": "string"}],
                        }
                    ),
                ),
                source["id"],
            )
        self.assertEqual(inspect_response.status_code, 201)

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            mapping_response = source_connector_mappings_collection(
                self._request(
                    f"/xyn/api/source-connectors/{source['id']}/mappings",
                    method="post",
                    data=json.dumps(
                        {
                            "workspace_id": str(self.workspace.id),
                            "status": "validated",
                            "field_mapping": {"parcel_id": "source.parcel_id"},
                            "transformation_hints": {"coerce_types": True},
                            "validation_state": {"ok": True},
                        }
                    ),
                ),
                source["id"],
            )
        self.assertEqual(mapping_response.status_code, 201)

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            activate_response = source_connector_activate(
                self._request(
                    f"/xyn/api/source-connectors/{source['id']}/activate",
                    method="post",
                    data=json.dumps({"workspace_id": str(self.workspace.id)}),
                ),
                source["id"],
            )
        self.assertEqual(activate_response.status_code, 200)
        activated = json.loads(activate_response.content)
        self.assertTrue(activated["is_active"])
        self.assertEqual(activated["lifecycle_state"], "active")

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            pause_response = source_connector_pause(
                self._request(
                    f"/xyn/api/source-connectors/{source['id']}/pause",
                    method="post",
                    data=json.dumps({"workspace_id": str(self.workspace.id)}),
                ),
                source["id"],
            )
        self.assertEqual(pause_response.status_code, 200)
        paused = json.loads(pause_response.content)
        self.assertFalse(paused["is_active"])
        self.assertEqual(paused["lifecycle_state"], "paused")

    def test_health_updates_and_detail_visibility(self):
        source = self._create_source(mode="api_polling")

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            health_response = source_connector_health_update(
                self._request(
                    f"/xyn/api/source-connectors/{source['id']}/health",
                    method="post",
                    data=json.dumps(
                        {
                            "workspace_id": str(self.workspace.id),
                            "health_status": "failing",
                            "failure_reason": "upstream timeout",
                        }
                    ),
                ),
                source["id"],
            )
        self.assertEqual(health_response.status_code, 200)
        health_payload = json.loads(health_response.content)
        self.assertEqual(health_payload["health_status"], "failing")
        self.assertEqual(health_payload["lifecycle_state"], "failing")

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            detail_response = source_connector_detail(
                self._request(
                    f"/xyn/api/source-connectors/{source['id']}",
                    data={"workspace_id": str(self.workspace.id)},
                ),
                source["id"],
            )
        self.assertEqual(detail_response.status_code, 200)
        detail_payload = json.loads(detail_response.content)
        self.assertEqual(detail_payload["last_failure_reason"], "upstream timeout")
        self.assertFalse(detail_payload["readiness"]["ready"])

    def test_workspace_isolation(self):
        source = self._create_source(mode="manual")
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = source_connector_detail(
                self._request(
                    f"/xyn/api/source-connectors/{source['id']}",
                    data={"workspace_id": str(self.other_workspace.id)},
                ),
                source["id"],
            )
        self.assertEqual(response.status_code, 404)

    def test_invalid_mode_is_rejected(self):
        payload = {
            "workspace_id": str(self.workspace.id),
            "key": "bad-source",
            "name": "Bad Source",
            "source_mode": "ftp_sync",
        }
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = source_connectors_collection(
                self._request("/xyn/api/source-connectors", method="post", data=json.dumps(payload))
            )
        self.assertEqual(response.status_code, 400)

    def test_invalid_governance_contract_is_rejected(self):
        payload = {
            "workspace_id": str(self.workspace.id),
            "key": "bad-governance-source",
            "name": "Bad Governance Source",
            "source_mode": "manual",
            "governance": {"allowed_ingestion_methods": ["ftp_sync"]},
        }
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = source_connectors_collection(
                self._request("/xyn/api/source-connectors", method="post", data=json.dumps(payload))
            )
        self.assertEqual(response.status_code, 400)

    def test_activation_is_deferred_when_governance_review_required(self):
        source = self._create_source(mode="manual")
        source_row = SourceConnector.objects.get(id=source["id"])
        source_row.governance_json = {"review_required": True, "allowed_ingestion_methods": ["manual"]}
        source_row.save(update_fields=["governance_json", "updated_at"])

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            inspect_response = source_connector_inspections_collection(
                self._request(
                    f"/xyn/api/source-connectors/{source['id']}/inspections",
                    method="post",
                    data=json.dumps(
                        {
                            "workspace_id": str(self.workspace.id),
                            "status": "ok",
                            "detected_format": "csv",
                            "discovered_fields": [{"name": "parcel_id", "type": "string"}],
                        }
                    ),
                ),
                source["id"],
            )
            mapping_response = source_connector_mappings_collection(
                self._request(
                    f"/xyn/api/source-connectors/{source['id']}/mappings",
                    method="post",
                    data=json.dumps(
                        {
                            "workspace_id": str(self.workspace.id),
                            "status": "validated",
                            "field_mapping": {"parcel_id": "source.parcel_id"},
                            "transformation_hints": {},
                            "validation_state": {"ok": True},
                        }
                    ),
                ),
                source["id"],
            )
            activate_response = source_connector_activate(
                self._request(
                    f"/xyn/api/source-connectors/{source['id']}/activate",
                    method="post",
                    data=json.dumps({"workspace_id": str(self.workspace.id)}),
                ),
                source["id"],
            )
        self.assertEqual(inspect_response.status_code, 201)
        self.assertEqual(mapping_response.status_code, 201)
        self.assertEqual(activate_response.status_code, 409)
        payload = json.loads(activate_response.content)
        self.assertEqual(payload["governance_decision"]["reason_code"], "governance.review_required")

    def test_activation_allowed_after_review_approval(self):
        source = self._create_source(mode="manual")
        source_row = SourceConnector.objects.get(id=source["id"])
        source_row.governance_json = {"review_required": True, "allowed_ingestion_methods": ["manual"]}
        source_row.review_approved = True
        source_row.review_approved_by = self.identity
        source_row.review_approved_at = source_row.created_at
        source_row.save(update_fields=["governance_json", "review_approved", "review_approved_by", "review_approved_at", "updated_at"])
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            source_connector_inspections_collection(
                self._request(
                    f"/xyn/api/source-connectors/{source['id']}/inspections",
                    method="post",
                    data=json.dumps(
                        {
                            "workspace_id": str(self.workspace.id),
                            "status": "ok",
                            "detected_format": "csv",
                            "discovered_fields": [{"name": "parcel_id", "type": "string"}],
                        }
                    ),
                ),
                source["id"],
            )
            source_connector_mappings_collection(
                self._request(
                    f"/xyn/api/source-connectors/{source['id']}/mappings",
                    method="post",
                    data=json.dumps(
                        {
                            "workspace_id": str(self.workspace.id),
                            "status": "validated",
                            "field_mapping": {"parcel_id": "source.parcel_id"},
                            "transformation_hints": {},
                            "validation_state": {"ok": True},
                        }
                    ),
                ),
                source["id"],
            )
            activate_response = source_connector_activate(
                self._request(
                    f"/xyn/api/source-connectors/{source['id']}/activate",
                    method="post",
                    data=json.dumps({"workspace_id": str(self.workspace.id)}),
                ),
                source["id"],
            )
        self.assertEqual(activate_response.status_code, 200)

    def test_campaign_operator_cannot_manage_sources(self):
        payload = {
            "workspace_id": str(self.workspace.id),
            "key": "operator-blocked-source",
            "name": "Blocked Source",
            "source_type": "records_feed",
            "source_mode": "manual",
        }
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.operator_identity):
            response = source_connectors_collection(
                self._request("/xyn/api/source-connectors", method="post", data=json.dumps(payload))
            )
        self.assertEqual(response.status_code, 403)

    def test_campaign_operator_cannot_read_source_detail(self):
        source = self._create_source(mode="manual")
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.operator_identity):
            response = source_connector_detail(
                self._request(
                    f"/xyn/api/source-connectors/{source['id']}",
                    data={"workspace_id": str(self.workspace.id)},
                ),
                source["id"],
            )
        self.assertEqual(response.status_code, 403)

    def test_models_exist(self):
        self._create_source(mode="manual")
        self.assertEqual(SourceConnector.objects.filter(workspace=self.workspace).count(), 1)

    def test_source_detail_patch_can_set_review_approval(self):
        source = self._create_source(mode="manual")
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = source_connector_detail(
                self._request(
                    f"/xyn/api/source-connectors/{source['id']}",
                    method="patch",
                    data=json.dumps(
                        {
                            "workspace_id": str(self.workspace.id),
                            "review_approved": True,
                        }
                    ),
                ),
                source["id"],
            )
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertTrue(payload["review_approved"])
        self.assertEqual(payload["review_approved_by_id"], str(self.identity.id))

    def test_inspection_and_mapping_replay_with_idempotency_key(self):
        source = self._create_source(mode="remote_url")
        inspection_payload = {
            "workspace_id": str(self.workspace.id),
            "status": "ok",
            "detected_format": "csv",
            "discovered_fields": [{"name": "parcel_id", "type": "string"}],
            "idempotency_key": "source-inspection-idem-1",
        }
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            first_inspect = source_connector_inspections_collection(
                self._request(
                    f"/xyn/api/source-connectors/{source['id']}/inspections",
                    method="post",
                    data=json.dumps(inspection_payload),
                ),
                source["id"],
            )
            second_inspect = source_connector_inspections_collection(
                self._request(
                    f"/xyn/api/source-connectors/{source['id']}/inspections",
                    method="post",
                    data=json.dumps(inspection_payload),
                ),
                source["id"],
            )
        self.assertEqual(first_inspect.status_code, 201)
        self.assertEqual(second_inspect.status_code, 201)

        mapping_payload = {
            "workspace_id": str(self.workspace.id),
            "status": "validated",
            "field_mapping": {"parcel_id": "source.parcel_id"},
            "transformation_hints": {"coerce_types": True},
            "validation_state": {"ok": True},
            "idempotency_key": "source-mapping-idem-1",
        }
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            first_mapping = source_connector_mappings_collection(
                self._request(
                    f"/xyn/api/source-connectors/{source['id']}/mappings",
                    method="post",
                    data=json.dumps(mapping_payload),
                ),
                source["id"],
            )
            second_mapping = source_connector_mappings_collection(
                self._request(
                    f"/xyn/api/source-connectors/{source['id']}/mappings",
                    method="post",
                    data=json.dumps(mapping_payload),
                ),
                source["id"],
            )
        self.assertEqual(first_mapping.status_code, 201)
        self.assertEqual(second_mapping.status_code, 201)
        source_row = SourceConnector.objects.get(id=source["id"])
        self.assertEqual(source_row.inspections.count(), 1)
        self.assertEqual(source_row.mappings.count(), 1)

    def test_refresh_requires_active_source(self):
        source = self._create_source(mode="remote_url")
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = source_connector_refresh(
                self._request(
                    f"/xyn/api/source-connectors/{source['id']}/refresh",
                    method="post",
                    data=json.dumps({"workspace_id": str(self.workspace.id)}),
                ),
                source["id"],
            )
        self.assertEqual(response.status_code, 409)

    @mock.patch("xyn_orchestrator.xyn_api.IngestionCoordinator")
    def test_refresh_executes_ingestion_and_returns_run_payload(self, coordinator_cls):
        source = self._create_source(mode="remote_url")
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            source_connector_inspections_collection(
                self._request(
                    f"/xyn/api/source-connectors/{source['id']}/inspections",
                    method="post",
                    data=json.dumps(
                        {
                            "workspace_id": str(self.workspace.id),
                            "status": "ok",
                            "detected_format": "csv",
                            "discovered_fields": [{"name": "parcel_id", "type": "string"}],
                        }
                    ),
                ),
                source["id"],
            )
            source_connector_mappings_collection(
                self._request(
                    f"/xyn/api/source-connectors/{source['id']}/mappings",
                    method="post",
                    data=json.dumps(
                        {
                            "workspace_id": str(self.workspace.id),
                            "status": "validated",
                            "field_mapping": {"parcel_id": "source.parcel_id"},
                            "transformation_hints": {},
                            "validation_state": {"ok": True},
                        }
                    ),
                ),
                source["id"],
            )
            source_connector_activate(
                self._request(
                    f"/xyn/api/source-connectors/{source['id']}/activate",
                    method="post",
                    data=json.dumps({"workspace_id": str(self.workspace.id)}),
                ),
                source["id"],
            )

        fake_run_id = str(uuid.uuid4())
        fake_artifact_id = str(uuid.uuid4())
        coordinator_cls.return_value.ingest_from_url.return_value = IngestionExecutionResult(
            run_id=fake_run_id,
            artifact_record_id=fake_artifact_id,
            parsed_record_count=12,
            warnings=("warning: sample",),
        )

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = source_connector_refresh(
                self._request(
                    f"/xyn/api/source-connectors/{source['id']}/refresh",
                    method="post",
                    data=json.dumps({"workspace_id": str(self.workspace.id)}),
                ),
                source["id"],
            )
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["run"]["id"], fake_run_id)
        self.assertEqual(payload["artifact_record_id"], fake_artifact_id)
        self.assertEqual(payload["parsed_record_count"], 12)
        coordinator_cls.return_value.ingest_from_url.assert_called_once()
