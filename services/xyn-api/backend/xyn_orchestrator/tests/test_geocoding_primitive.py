import json
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from xyn_orchestrator import models
from xyn_orchestrator.geocoding.interfaces import (
    GeocodeProviderCandidate,
    GeocodeProviderRequest,
    GeocodeProviderResponse,
)
from xyn_orchestrator.geocoding.providers import ArcGisGeocoderProvider
from xyn_orchestrator.geocoding.service import GeocodingService
from xyn_orchestrator.xyn_api import (
    geocode_result_detail,
    geocode_results_collection,
    geocode_results_resolve_adapted,
    geocode_results_resolve_source,
)


class _StaticProvider:
    kind = "arcgis_rest_geocoder"
    name = "arcgis_rest_geocoder"
    version = "test"

    def __init__(self, response: GeocodeProviderResponse):
        self.response = response
        self.calls: list[GeocodeProviderRequest] = []

    def geocode(self, *, request: GeocodeProviderRequest) -> GeocodeProviderResponse:
        self.calls.append(request)
        return self.response


class _FakeHttpResponse:
    def __init__(self, payload: dict, *, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


class GeocodingPrimitiveTests(TestCase):
    def setUp(self):
        suffix = uuid.uuid4().hex[:8]
        self.factory = RequestFactory()
        self.workspace = models.Workspace.objects.create(slug=f"geocode-{suffix}", name="Geocode Workspace")
        self.source = models.SourceConnector.objects.create(
            workspace=self.workspace,
            key=f"source-{suffix}",
            name="Geocode Source",
            source_type="records_feed",
            source_mode="remote_url",
            configuration_json={
                "geocoding": {
                    "provider_kind": "arcgis_rest_geocoder",
                    "url": "https://example.local/arcgis/findAddressCandidates",
                    "address_fields": ["record.address"],
                    "params": {"outFields": "*"},
                }
            },
        )
        self.pipeline = models.OrchestrationPipeline.objects.create(
            workspace=self.workspace,
            key=f"geocode-pipeline-{suffix}",
            name="Geocode Pipeline",
        )
        self.run = models.OrchestrationRun.objects.create(
            workspace=self.workspace,
            pipeline=self.pipeline,
            trigger_cause="manual",
            trigger_key="geocode-tests",
            scope_jurisdiction="mo-stl-city",
            scope_source="source-feed",
        )
        self.artifact = models.IngestArtifactRecord.objects.create(
            workspace=self.workspace,
            source_connector=self.source,
            orchestration_run=self.run,
            artifact_id=uuid.uuid4(),
            original_filename="input.json",
            sha256="b" * 64,
        )
        self.adapted = models.IngestAdaptedRecord.objects.create(
            workspace=self.workspace,
            source_connector=self.source,
            orchestration_run=self.run,
            artifact=self.artifact,
            adapter_kind="json_http",
            source_format="json",
            adapted_payload_json={"record": {"address": "123 North Main Street"}},
            status="ok",
        )

        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username=f"geocode-{suffix}",
            email=f"geocode-{suffix}@example.com",
            password="password",
        )
        self.identity = models.UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example",
            subject=f"geocode-{suffix}",
            email=f"geocode-{suffix}@example.com",
        )
        models.WorkspaceMembership.objects.create(workspace=self.workspace, user_identity=self.identity, role="admin")

    def _request(self, path: str, *, method: str = "get", data=None):
        request = getattr(self.factory, method.lower())(path, data=data or {}, content_type="application/json")
        request.user = self.user
        return request

    def test_arcgis_provider_parses_candidates(self):
        provider = ArcGisGeocoderProvider()
        with mock.patch(
            "xyn_orchestrator.geocoding.providers.requests.get",
            return_value=_FakeHttpResponse(
                {
                    "spatialReference": {"wkid": 4326},
                    "candidates": [
                        {"address": "123 N MAIN ST", "score": 98.4, "location": {"x": -90.2, "y": 38.6}},
                        {"address": "123 MAIN ST", "score": 91.0, "location": {"x": -90.19, "y": 38.61}},
                    ],
                }
            ),
        ):
            response = provider.geocode(
                request=GeocodeProviderRequest(
                    raw_address="123 North Main Street",
                    normalized_address="123 n main st",
                    address_fields={"record.address": "123 North Main Street"},
                    provider_config={"url": "https://example.local/geocode"},
                    context={},
                )
            )
        self.assertEqual(response.status, "success")
        self.assertEqual(len(response.candidates), 2)
        self.assertEqual(response.candidates[0].matched_address, "123 N MAIN ST")
        self.assertEqual(response.candidates[0].spatial_reference.get("wkid"), 4326)

    def test_service_extracts_normalized_address_and_persists_candidates(self):
        provider = _StaticProvider(
            GeocodeProviderResponse(
                status="success",
                candidates=(
                    GeocodeProviderCandidate(
                        rank=1,
                        score=88.0,
                        matched_address="123 N MAIN ST",
                        location={"x": -90.2, "y": 38.6},
                        spatial_reference={"wkid": 4326},
                    ),
                    GeocodeProviderCandidate(
                        rank=2,
                        score=92.5,
                        matched_address="123 MAIN STREET",
                        location={"x": -90.21, "y": 38.61},
                        spatial_reference={"wkid": 4326},
                    ),
                ),
                request_context={"request_id": "a1"},
                response_context={"provider": "arcgis"},
            )
        )
        service = GeocodingService(providers={"arcgis_rest_geocoder": provider})
        row = service.geocode_adapted_record(adapted_record_id=str(self.adapted.id))
        self.assertEqual(row.status, "selected")
        self.assertTrue(row.input_address_normalized)
        self.assertEqual(row.candidates.count(), 2)
        self.assertIsNotNone(row.selected_candidate_id)
        self.assertEqual(row.selection_reason, "highest_score_then_rank")
        self.assertEqual(row.selected_candidate.candidate_rank, 2)
        self.assertEqual(provider.calls[0].normalized_address, row.input_address_normalized)

    def test_no_candidates_and_invalid_input_outcomes_are_inspectable(self):
        service = GeocodingService(
            providers={"arcgis_rest_geocoder": _StaticProvider(GeocodeProviderResponse(status="no_candidates", candidates=tuple()))}
        )
        no_candidates = service.geocode_adapted_record(adapted_record_id=str(self.adapted.id))
        self.assertEqual(no_candidates.status, "no_candidates")
        self.assertEqual(no_candidates.candidates.count(), 0)

        empty = models.IngestAdaptedRecord.objects.create(
            workspace=self.workspace,
            source_connector=self.source,
            orchestration_run=self.run,
            artifact=self.artifact,
            adapter_kind="json_http",
            source_format="json",
            adapted_payload_json={"record": {"owner": "Acme LLC"}},
            status="ok",
        )
        invalid = service.geocode_adapted_record(adapted_record_id=str(empty.id))
        self.assertEqual(invalid.status, "invalid_input")
        self.assertEqual(invalid.failure_category, "invalid_input")

    def test_provider_error_and_idempotent_rerun(self):
        provider = _StaticProvider(
            GeocodeProviderResponse(status="provider_error", error_category="provider_error", error_message="timeout")
        )
        service = GeocodingService(providers={"arcgis_rest_geocoder": provider})
        first = service.geocode_adapted_record(adapted_record_id=str(self.adapted.id))
        second = service.geocode_adapted_record(adapted_record_id=str(self.adapted.id))
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.status, "provider_error")
        self.assertEqual(first.failure_category, "provider_error")
        self.assertEqual(models.GeocodeEnrichmentResult.objects.filter(workspace=self.workspace).count(), 1)

    def test_provenance_links_result_and_selected_candidate(self):
        provider = _StaticProvider(
            GeocodeProviderResponse(
                status="success",
                candidates=(GeocodeProviderCandidate(rank=1, score=99.0, matched_address="123 N MAIN ST", location={"x": -90.2, "y": 38.6}),),
            )
        )
        row = GeocodingService(providers={"arcgis_rest_geocoder": provider}).geocode_adapted_record(adapted_record_id=str(self.adapted.id))
        self.assertTrue(
            models.ProvenanceLink.objects.filter(
                workspace=self.workspace,
                relationship_type="geocode_enrichment_from_adapted",
                target_ref_json__object_id=str(row.id),
            ).exists()
        )
        self.assertTrue(
            models.ProvenanceLink.objects.filter(
                workspace=self.workspace,
                relationship_type="geocode_selected_candidate",
                source_ref_json__object_id=str(row.id),
            ).exists()
        )

    def test_api_resolve_and_query(self):
        provider = _StaticProvider(
            GeocodeProviderResponse(
                status="success",
                candidates=(GeocodeProviderCandidate(rank=1, score=90.0, matched_address="123 N MAIN ST", location={"x": -90.2, "y": 38.6}),),
            )
        )
        payload = {"workspace_id": str(self.workspace.id), "adapted_record_id": str(self.adapted.id)}
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api.GeocodingService", return_value=GeocodingService(providers={"arcgis_rest_geocoder": provider})
        ):
            resolve_response = geocode_results_resolve_adapted(
                self._request("/xyn/api/geocoding/resolve-adapted", method="post", data=json.dumps(payload))
            )
        self.assertEqual(resolve_response.status_code, 201)
        resolve_body = json.loads(resolve_response.content)
        result_id = resolve_body["results"][0]["id"]
        self.assertEqual(resolve_body["results"][0]["status"], "selected")

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            collection_response = geocode_results_collection(
                self._request(
                    "/xyn/api/geocoding/results",
                    data={"workspace_id": str(self.workspace.id), "adapted_record_id": str(self.adapted.id), "include_candidates": "true"},
                )
            )
        self.assertEqual(collection_response.status_code, 200)
        collection_body = json.loads(collection_response.content)
        self.assertEqual(len(collection_body["results"]), 1)
        self.assertEqual(collection_body["results"][0]["id"], result_id)
        self.assertEqual(len(collection_body["results"][0]["candidates"]), 1)

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            detail_response = geocode_result_detail(
                self._request("/xyn/api/geocoding/results/detail", data={"workspace_id": str(self.workspace.id)}),
                result_id=result_id,
            )
        self.assertEqual(detail_response.status_code, 200)
        detail_body = json.loads(detail_response.content)
        self.assertEqual(detail_body["id"], result_id)
        self.assertEqual(len(detail_body["candidates"]), 1)

    def test_api_resolve_source_supports_bulk(self):
        second = models.IngestAdaptedRecord.objects.create(
            workspace=self.workspace,
            source_connector=self.source,
            orchestration_run=self.run,
            artifact=self.artifact,
            adapter_kind="json_http",
            source_format="json",
            adapted_payload_json={"record": {"address": "500 South Grand Avenue"}},
            status="ok",
        )
        provider = _StaticProvider(
            GeocodeProviderResponse(
                status="success",
                candidates=(GeocodeProviderCandidate(rank=1, score=84.0, matched_address="500 S GRAND AVE", location={"x": -90.25, "y": 38.61}),),
            )
        )
        payload = {"workspace_id": str(self.workspace.id), "source_id": str(self.source.id), "run_id": str(self.run.id), "limit": 10}
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api.GeocodingService", return_value=GeocodingService(providers={"arcgis_rest_geocoder": provider})
        ):
            response = geocode_results_resolve_source(
                self._request("/xyn/api/geocoding/resolve-source", method="post", data=json.dumps(payload))
            )
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body["count"], 2)
        self.assertEqual(
            set(item["adapted_record_id"] for item in body["results"]),
            {str(self.adapted.id), str(second.id)},
        )
