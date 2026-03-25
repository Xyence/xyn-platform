import json
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from xyn_orchestrator import models
from xyn_orchestrator.parcel_identity import ParcelIdentityResolverService
from xyn_orchestrator.xyn_api import (
    parcel_crosswalks_collection,
    parcel_crosswalks_resolve_adapted,
    parcel_identity_lookup,
)


class ParcelIdentityPrimitiveTests(TestCase):
    def setUp(self):
        suffix = uuid.uuid4().hex[:8]
        self.factory = RequestFactory()
        self.workspace = models.Workspace.objects.create(slug=f"parcel-{suffix}", name="Parcel Workspace")
        self.source = models.SourceConnector.objects.create(
            workspace=self.workspace,
            key=f"parcel-source-{suffix}",
            name="Parcel Source",
            source_type="records_feed",
            source_mode="remote_url",
            configuration_json={},
        )
        self.pipeline = models.OrchestrationPipeline.objects.create(
            workspace=self.workspace,
            key=f"parcel-pipeline-{suffix}",
            name="Parcel Pipeline",
        )
        self.run = models.OrchestrationRun.objects.create(
            workspace=self.workspace,
            pipeline=self.pipeline,
            trigger_cause="manual",
            trigger_key="parcel-tests",
            scope_jurisdiction="mo-stl-city",
            scope_source="parcel-feed",
        )
        self.artifact = models.IngestArtifactRecord.objects.create(
            workspace=self.workspace,
            source_connector=self.source,
            orchestration_run=self.run,
            artifact_id=uuid.uuid4(),
            original_filename="parcel.json",
            sha256="a" * 64,
        )
        self.service = ParcelIdentityResolverService()

        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username=f"parcel-{suffix}",
            email=f"parcel-{suffix}@example.com",
            password="password",
        )
        self.identity = models.UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example",
            subject=f"parcel-{suffix}",
            email=f"parcel-{suffix}@example.com",
        )
        models.WorkspaceMembership.objects.create(workspace=self.workspace, user_identity=self.identity, role="admin")

    def _request(self, path: str, *, method: str = "get", data=None):
        request = getattr(self.factory, method.lower())(path, data=data or {}, content_type="application/json")
        request.user = self.user
        return request

    def _adapted_row(self, payload: dict, *, geometry: dict | None = None) -> models.IngestAdaptedRecord:
        return models.IngestAdaptedRecord.objects.create(
            workspace=self.workspace,
            source_connector=self.source,
            orchestration_run=self.run,
            artifact=self.artifact,
            adapter_kind="json_http",
            source_format="json",
            adapted_payload_json=payload,
            geometry_payload_json=geometry or {},
            status="ok",
        )

    def test_deterministic_identifier_creates_canonical_and_aliases(self):
        adapted = self._adapted_row({"attributes": {"HANDLE": "H-100", "Ref_ID": "ref-100"}})
        mapping = self.service.resolve_adapted_record(adapted_record_id=str(adapted.id))
        self.assertEqual(mapping.status, "resolved")
        self.assertEqual(mapping.resolution_method, "deterministic_identifier")
        self.assertIsNotNone(mapping.parcel_id)
        self.assertEqual(mapping.namespace, "handle")
        self.assertEqual(mapping.identifier_value_normalized, "h100")

        parcel = mapping.parcel
        self.assertIsNotNone(parcel)
        aliases = models.ParcelIdentifierAlias.objects.filter(parcel=parcel).order_by("namespace")
        self.assertTrue(aliases.filter(namespace="handle", value_normalized="h100").exists())
        self.assertTrue(aliases.filter(namespace="ref_id", value_normalized="ref100").exists())

    def test_alternate_identifier_lookup_resolves_existing_canonical(self):
        first = self._adapted_row({"attributes": {"HANDLE": "H-200", "REF_ID": "REF-200"}})
        first_mapping = self.service.resolve_adapted_record(adapted_record_id=str(first.id))
        second = self._adapted_row({"attributes": {"REF_ID": "ref 200"}})
        second_mapping = self.service.resolve_adapted_record(adapted_record_id=str(second.id))
        self.assertEqual(second_mapping.status, "resolved")
        self.assertEqual(second_mapping.parcel_id, first_mapping.parcel_id)
        self.assertEqual(second_mapping.resolution_method, "deterministic_identifier")

    def test_composite_identifier_resolution(self):
        self.source.configuration_json = {
            "parcel_identity": {
                "identifier_fields": [{"namespace": "unused", "path": "attributes.DOES_NOT_EXIST"}],
                "composite_identifiers": [
                    {
                        "namespace": "cityblock_parcel",
                        "delimiter": "|",
                        "parts": [
                            {"namespace": "cityblock", "path": "attributes.CITYBLOCK"},
                            {"namespace": "parcel", "path": "attributes.PARCEL"},
                        ],
                    }
                ],
            }
        }
        self.source.save(update_fields=["configuration_json"])
        adapted = self._adapted_row({"attributes": {"CITYBLOCK": "A-10", "PARCEL": "001"}})
        mapping = self.service.resolve_adapted_record(adapted_record_id=str(adapted.id))
        self.assertEqual(mapping.status, "resolved")
        self.assertEqual(mapping.resolution_method, "deterministic_composite")
        self.assertEqual(mapping.namespace, "cityblock_parcel")
        self.assertEqual(mapping.composite_key_normalized, "a10|001")

    def test_unresolved_outcome_is_persisted(self):
        adapted = self._adapted_row({"record": {"owner": "Alpha LLC"}})
        mapping = self.service.resolve_adapted_record(adapted_record_id=str(adapted.id))
        self.assertEqual(mapping.status, "unresolved")
        self.assertEqual(mapping.resolution_method, "unresolved")
        self.assertIsNone(mapping.parcel_id)
        self.assertIn("identifier_candidates", mapping.explanation_json)

    def test_address_fallback_uses_existing_alias(self):
        parcel = models.ParcelCanonicalIdentity.objects.create(
            workspace=self.workspace,
            canonical_namespace="handle",
            canonical_value_raw="H-300",
            canonical_value_normalized="h300",
        )
        models.ParcelIdentifierAlias.objects.create(
            workspace=self.workspace,
            parcel=parcel,
            namespace="address",
            value_raw="123 N Main Street",
            value_normalized="123 n main st",
            is_canonical=False,
            confidence=0.55,
        )
        adapted = self._adapted_row({"attributes": {"ADDRESS": "123 North Main St."}})
        mapping = self.service.resolve_adapted_record(adapted_record_id=str(adapted.id))
        self.assertEqual(mapping.status, "resolved")
        self.assertEqual(mapping.resolution_method, "address_fallback")
        self.assertEqual(mapping.parcel_id, parcel.id)

    def test_provenance_links_adapted_to_crosswalk_and_parcel(self):
        adapted = self._adapted_row({"attributes": {"HANDLE": "H-400"}})
        mapping = self.service.resolve_adapted_record(adapted_record_id=str(adapted.id))
        links = models.ProvenanceLink.objects.filter(workspace=self.workspace).order_by("relationship_type")
        self.assertTrue(
            links.filter(
                relationship_type="parcel_crosswalk_derived_from",
                target_ref_json__object_family="parcel_crosswalk_mapping",
                target_ref_json__object_id=str(mapping.id),
            ).exists()
        )
        self.assertTrue(
            links.filter(
                relationship_type="parcel_crosswalk_resolved_to",
                source_ref_json__object_family="parcel_crosswalk_mapping",
                source_ref_json__object_id=str(mapping.id),
            ).exists()
        )

    def test_crosswalk_can_reference_selected_geocode_evidence(self):
        adapted = self._adapted_row({"attributes": {"HANDLE": "H-450", "ADDRESS": "123 N Main St"}})
        geocode = models.GeocodeEnrichmentResult.objects.create(
            workspace=self.workspace,
            source_connector=self.source,
            orchestration_run=self.run,
            adapted_record=adapted,
            provider_kind="arcgis_rest_geocoder",
            provider_name="arcgis_rest_geocoder",
            provider_version="1",
            provider_endpoint_url="https://example.local/geocode",
            input_address_raw="123 N Main St",
            input_address_normalized="123 n main st",
            idempotency_key=f"geo-{uuid.uuid4().hex}",
            request_fingerprint=uuid.uuid4().hex,
            status="selected",
        )
        candidate = models.GeocodeEnrichmentCandidate.objects.create(
            result_set=geocode,
            candidate_rank=1,
            provider_score=97.0,
            matched_address="123 N MAIN ST",
            geometry_json={"x": -90.2, "y": 38.6},
            is_selected=True,
        )
        geocode.selected_candidate = candidate
        geocode.selection_reason = "highest_score_then_rank"
        geocode.save(update_fields=["selected_candidate", "selection_reason", "updated_at"])

        mapping = self.service.resolve_adapted_record(adapted_record_id=str(adapted.id))
        geocode_evidence = mapping.explanation_json.get("geocoding_evidence")
        self.assertIsInstance(geocode_evidence, dict)
        self.assertEqual(str(geocode_evidence.get("geocode_result_id") or ""), str(geocode.id))
        self.assertTrue(
            models.ProvenanceLink.objects.filter(
                workspace=self.workspace,
                relationship_type="parcel_crosswalk_enriched_by_geocode",
                source_ref_json__object_id=str(geocode.id),
                target_ref_json__object_id=str(mapping.id),
            ).exists()
        )

    def test_geocode_point_containment_calibrated_resolves_to_handle(self):
        parcel_source = models.SourceConnector.objects.create(
            workspace=self.workspace,
            key=f"parcel-geometry-{uuid.uuid4().hex[:8]}",
            name="Parcel Geometry Source",
            source_type="parcel_geometry",
            source_mode="remote_url",
        )
        parcel_artifact = models.IngestArtifactRecord.objects.create(
            workspace=self.workspace,
            source_connector=parcel_source,
            orchestration_run=self.run,
            artifact_id=uuid.uuid4(),
            original_filename="prcl_shape.zip",
            sha256="b" * 64,
        )
        models.IngestAdaptedRecord.objects.create(
            workspace=self.workspace,
            source_connector=parcel_source,
            orchestration_run=self.run,
            artifact=parcel_artifact,
            adapter_kind="shapefile",
            source_format="shp",
            adapted_payload_json={"attributes": {"HANDLE": "H-900"}},
            geometry_payload_json={
                "type": "Polygon",
                "coordinates": [[[560, 1000], [570, 1000], [570, 1010], [560, 1010], [560, 1000]]],
            },
            status="ok",
        )
        models.IngestAdaptedRecord.objects.create(
            workspace=self.workspace,
            source_connector=parcel_source,
            orchestration_run=self.run,
            artifact=parcel_artifact,
            adapter_kind="shapefile",
            source_format="shp",
            adapted_payload_json={"attributes": {"HANDLE": "H-901"}},
            geometry_payload_json={
                "type": "Polygon",
                "coordinates": [[[590, 1000], [600, 1000], [600, 1010], [590, 1010], [590, 1000]]],
            },
            status="ok",
        )

        adapted = self._adapted_row({"record": {"PROBADDRESS": "2205 S JEFFERSON AVE"}})

        # Anchor selected geocode points establish the geocoder extent for calibration.
        for idx, point in enumerate(((800, 1000), (850, 1010)), start=1):
            anchor = models.GeocodeEnrichmentResult.objects.create(
                workspace=self.workspace,
                source_connector=self.source,
                orchestration_run=self.run,
                adapted_record=adapted,
                provider_kind="arcgis_rest_geocoder",
                provider_name="arcgis_rest_geocoder",
                provider_version="1",
                provider_endpoint_url="https://example.local/geocode",
                input_address_raw=f"anchor-{idx}",
                input_address_normalized=f"anchor-{idx}",
                idempotency_key=f"geo-anchor-{idx}-{uuid.uuid4().hex}",
                request_fingerprint=uuid.uuid4().hex,
                status="selected",
            )
            models.GeocodeEnrichmentCandidate.objects.create(
                result_set=anchor,
                candidate_rank=1,
                provider_score=90.0,
                matched_address=f"anchor-{idx}",
                geometry_json={"x": point[0], "y": point[1]},
                spatial_reference_json={"wkid": 102696},
                is_selected=True,
            )

        geocode = models.GeocodeEnrichmentResult.objects.create(
            workspace=self.workspace,
            source_connector=self.source,
            orchestration_run=self.run,
            adapted_record=adapted,
            provider_kind="arcgis_rest_geocoder",
            provider_name="arcgis_rest_geocoder",
            provider_version="1",
            provider_endpoint_url="https://example.local/geocode",
            input_address_raw="2205 S JEFFERSON AVE",
            input_address_normalized="2205 s jefferson ave",
            idempotency_key=f"geo-calibrated-{uuid.uuid4().hex}",
            request_fingerprint=uuid.uuid4().hex,
            status="selected",
        )
        candidate = models.GeocodeEnrichmentCandidate.objects.create(
            result_set=geocode,
            candidate_rank=1,
            provider_score=97.0,
            matched_address="2205 S JEFFERSON AVE",
            geometry_json={"x": 810, "y": 1005},
            spatial_reference_json={"wkid": 102696},
            is_selected=True,
        )
        geocode.selected_candidate = candidate
        geocode.selection_reason = "highest_score_then_rank"
        geocode.save(update_fields=["selected_candidate", "selection_reason", "updated_at"])

        mapping = self.service.resolve_adapted_record(adapted_record_id=str(adapted.id))
        self.assertEqual(mapping.status, "resolved")
        self.assertEqual(mapping.resolution_method, "geocode_point_containment_calibrated")
        self.assertEqual(mapping.namespace, "handle")
        self.assertEqual(mapping.identifier_value_normalized, "h900")
        self.assertTrue(mapping.explanation_json.get("geocoding_evidence", {}).get("calibrated_point"))

    def test_api_lookup_and_crosswalk_resolution(self):
        adapted = self._adapted_row({"attributes": {"HANDLE": "H-500"}})
        payload = {"workspace_id": str(self.workspace.id), "adapted_record_id": str(adapted.id)}
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            resolve_response = parcel_crosswalks_resolve_adapted(
                self._request("/xyn/api/parcel-crosswalks/resolve-adapted", method="post", data=json.dumps(payload))
            )
        self.assertEqual(resolve_response.status_code, 201)
        resolve_body = json.loads(resolve_response.content)
        self.assertEqual(resolve_body["count"], 1)
        parcel_id = resolve_body["crosswalks"][0]["parcel_id"]
        self.assertTrue(parcel_id)

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            lookup_response = parcel_identity_lookup(
                self._request(
                    "/xyn/api/parcel-identities/lookup",
                    data={"workspace_id": str(self.workspace.id), "namespace": "handle", "value": "h500"},
                )
            )
        self.assertEqual(lookup_response.status_code, 200)
        lookup_body = json.loads(lookup_response.content)
        self.assertEqual(lookup_body["parcel"]["id"], parcel_id)

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            list_response = parcel_crosswalks_collection(
                self._request(
                    "/xyn/api/parcel-crosswalks",
                    data={"workspace_id": str(self.workspace.id), "status": "resolved"},
                )
            )
        self.assertEqual(list_response.status_code, 200)
        list_body = json.loads(list_response.content)
        self.assertTrue(any(row["parcel_id"] == parcel_id for row in list_body["crosswalks"]))
