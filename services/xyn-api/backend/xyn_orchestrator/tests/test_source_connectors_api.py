import json
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from xyn_orchestrator.models import SourceConnector, UserIdentity, Workspace, WorkspaceMembership
from xyn_orchestrator.xyn_api import (
    source_connector_activate,
    source_connector_detail,
    source_connector_health_update,
    source_connector_inspections_collection,
    source_connector_mappings_collection,
    source_connector_pause,
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
        self.workspace = Workspace.objects.create(slug=f"sources-{suffix}", name="Sources Workspace")
        self.other_workspace = Workspace.objects.create(slug=f"sources-other-{suffix}", name="Other Sources Workspace")
        WorkspaceMembership.objects.create(workspace=self.workspace, user_identity=self.identity, role="admin")

    def _request(self, path: str, *, method: str = "get", data=None):
        request = getattr(self.factory, method.lower())(path, data=data or {}, content_type="application/json")
        request.user = self.user
        return request

    def _create_source(self, *, mode: str = "manual") -> dict:
        payload = {
            "workspace_id": str(self.workspace.id),
            "key": f"source-{uuid.uuid4().hex[:6]}",
            "name": "County Feed",
            "source_type": "records_feed",
            "source_mode": mode,
            "refresh_cadence_seconds": 3600 if mode in {"remote_url", "api_polling"} else 0,
            "configuration": {"url": "https://example.com/feed.csv"} if mode != "manual" else {},
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

    def test_models_exist(self):
        self._create_source(mode="manual")
        self.assertEqual(SourceConnector.objects.filter(workspace=self.workspace).count(), 1)

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
