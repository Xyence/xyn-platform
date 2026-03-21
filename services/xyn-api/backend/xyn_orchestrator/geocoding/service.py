from __future__ import annotations

import hashlib
import json
from typing import Any

from django.db import transaction

from xyn_orchestrator import models
from xyn_orchestrator.matching.normalization import normalize_address_record
from xyn_orchestrator.provenance import ProvenanceLinkInput, ProvenanceService, object_ref

from .interfaces import GeocodeProvider, GeocodeProviderCandidate, GeocodeProviderRequest
from .providers import ArcGisGeocoderProvider


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _extract_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for token in [part.strip() for part in str(path or "").split(".") if part.strip()]:
        if not isinstance(current, dict):
            return None
        current = current.get(token)
    return current


def _stable_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class GeocodingService:
    DEFAULT_ADDRESS_FIELDS: tuple[str, ...] = (
        "record.address",
        "record.ADDRESS",
        "record.site_address",
        "record.SITEADDR",
        "attributes.address",
        "attributes.ADDRESS",
        "attributes.site_address",
        "attributes.SITEADDR",
    )

    def __init__(self, *, providers: dict[str, GeocodeProvider] | None = None):
        builtins = {"arcgis_rest_geocoder": ArcGisGeocoderProvider()}
        self._providers = {**builtins, **(providers or {})}

    def _provider_config(self, source: models.SourceConnector | None) -> dict[str, Any]:
        if source is None:
            return {}
        config = _safe_dict(source.configuration_json)
        geocode_cfg = _safe_dict(config.get("geocoding"))
        if not geocode_cfg:
            geocode_cfg = _safe_dict(config.get("geocoder"))
        return geocode_cfg

    def _extract_address(self, *, adapted: models.IngestAdaptedRecord, provider_config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        payload = _safe_dict(adapted.adapted_payload_json)
        fields = _safe_list(provider_config.get("address_fields"))
        field_paths = [str(item).strip() for item in fields if str(item).strip()]
        if not field_paths:
            field_paths = list(self.DEFAULT_ADDRESS_FIELDS)
        found: dict[str, Any] = {}
        for path in field_paths:
            value = _extract_path(payload, path)
            value_text = str(value or "").strip()
            if value_text:
                found[path] = value_text
        raw_address = ""
        if found:
            raw_address = str(next(iter(found.values())))
        return raw_address, found

    def _provider(self, kind: str) -> GeocodeProvider | None:
        return self._providers.get(str(kind or "").strip().lower())

    def _idempotency_key(
        self,
        *,
        adapted: models.IngestAdaptedRecord,
        provider_kind: str,
        provider_url: str,
        normalized_address: str,
        provider_params: dict[str, Any],
    ) -> str:
        raw = {
            "adapted_record_id": str(adapted.id),
            "provider_kind": str(provider_kind or "").strip().lower(),
            "provider_url": str(provider_url or "").strip(),
            "normalized_address": str(normalized_address or "").strip(),
            "provider_params": provider_params,
        }
        return _stable_hash(raw)

    def _select_candidate(self, candidates: list[GeocodeProviderCandidate]) -> tuple[int | None, str]:
        if not candidates:
            return None, ""
        sorted_rows = sorted(
            enumerate(candidates),
            key=lambda row: (
                -(float(row[1].score) if row[1].score is not None else -1.0),
                int(row[1].rank or row[0] + 1),
            ),
        )
        return int(sorted_rows[0][0]), "highest_score_then_rank"

    @transaction.atomic
    def geocode_adapted_record(self, *, adapted_record_id: str) -> models.GeocodeEnrichmentResult:
        adapted = models.IngestAdaptedRecord.objects.select_related("workspace", "source_connector", "orchestration_run").get(
            id=adapted_record_id
        )
        workspace = adapted.workspace
        source = adapted.source_connector
        provider_config = self._provider_config(source)
        provider_kind = str(provider_config.get("provider_kind") or "").strip().lower()
        provider_url = str(provider_config.get("url") or "").strip()
        raw_address, address_fields = self._extract_address(adapted=adapted, provider_config=provider_config)
        jurisdiction = str(getattr(adapted.orchestration_run, "scope_jurisdiction", "") or "")
        normalized = normalize_address_record(raw_address, jurisdiction=jurisdiction or None)
        normalized_address = str(normalized.get("normalized") or "").strip()

        idempotency_key = self._idempotency_key(
            adapted=adapted,
            provider_kind=provider_kind,
            provider_url=provider_url,
            normalized_address=normalized_address,
            provider_params=_safe_dict(provider_config.get("params")),
        )
        existing = models.GeocodeEnrichmentResult.objects.filter(workspace=workspace, idempotency_key=idempotency_key).first()
        if existing is not None:
            return existing

        if not provider_kind or not provider_url:
            return models.GeocodeEnrichmentResult.objects.create(
                workspace=workspace,
                source_connector=source,
                orchestration_run=adapted.orchestration_run,
                job_run=adapted.job_run,
                adapted_record=adapted,
                provider_kind=provider_kind,
                provider_name=provider_kind,
                provider_version="",
                provider_endpoint_url=provider_url,
                input_address_raw=raw_address,
                input_address_normalized=normalized_address,
                input_address_fields_json=address_fields,
                request_fingerprint=idempotency_key,
                idempotency_key=idempotency_key,
                status="provider_not_configured",
                failure_category="provider_not_configured",
                failure_reason="geocoder provider_kind/url not configured on source connector",
            )

        if not normalized_address:
            return models.GeocodeEnrichmentResult.objects.create(
                workspace=workspace,
                source_connector=source,
                orchestration_run=adapted.orchestration_run,
                job_run=adapted.job_run,
                adapted_record=adapted,
                provider_kind=provider_kind,
                provider_name=provider_kind,
                provider_version="",
                provider_endpoint_url=provider_url,
                input_address_raw=raw_address,
                input_address_normalized="",
                input_address_fields_json=address_fields,
                request_fingerprint=idempotency_key,
                idempotency_key=idempotency_key,
                status="invalid_input",
                failure_category="invalid_input",
                failure_reason="missing or unparseable address input",
            )

        provider = self._provider(provider_kind)
        if provider is None:
            return models.GeocodeEnrichmentResult.objects.create(
                workspace=workspace,
                source_connector=source,
                orchestration_run=adapted.orchestration_run,
                job_run=adapted.job_run,
                adapted_record=adapted,
                provider_kind=provider_kind,
                provider_name=provider_kind,
                provider_version="",
                provider_endpoint_url=provider_url,
                input_address_raw=raw_address,
                input_address_normalized=normalized_address,
                input_address_fields_json=address_fields,
                request_fingerprint=idempotency_key,
                idempotency_key=idempotency_key,
                status="provider_error",
                failure_category="provider_not_installed",
                failure_reason=f"provider '{provider_kind}' not registered",
            )

        response = provider.geocode(
            request=GeocodeProviderRequest(
                raw_address=raw_address,
                normalized_address=normalized_address,
                address_fields=address_fields,
                provider_config=provider_config,
                context={
                    "workspace_id": str(workspace.id),
                    "source_id": str(source.id) if source else "",
                    "adapted_record_id": str(adapted.id),
                },
            )
        )
        result_status = "provider_error"
        failure_category = ""
        failure_reason = ""
        if response.status == "success":
            result_status = "no_selection"
        elif response.status == "no_candidates":
            result_status = "no_candidates"
        elif response.status == "shape_error":
            result_status = "shape_error"
            failure_category = response.error_category or "shape_error"
            failure_reason = response.error_message or "geocoder response shape is invalid"
        elif response.status == "provider_not_configured":
            result_status = "provider_not_configured"
            failure_category = response.error_category or "provider_not_configured"
            failure_reason = response.error_message or "provider is not configured"
        else:
            result_status = "provider_error"
            failure_category = response.error_category or "provider_error"
            failure_reason = response.error_message or "geocoder provider call failed"

        row = models.GeocodeEnrichmentResult.objects.create(
            workspace=workspace,
            source_connector=source,
            orchestration_run=adapted.orchestration_run,
            job_run=adapted.job_run,
            adapted_record=adapted,
            provider_kind=provider.kind,
            provider_name=provider.name,
            provider_version=provider.version,
            provider_endpoint_url=provider_url,
            input_address_raw=raw_address,
            input_address_normalized=normalized_address,
            input_address_fields_json=address_fields,
            request_fingerprint=idempotency_key,
            idempotency_key=idempotency_key,
            status=result_status,
            request_context_json=_safe_dict(response.request_context),
            response_context_json=_safe_dict(response.response_context),
            failure_category=failure_category,
            failure_reason=failure_reason,
        )

        selected_index, selection_reason = self._select_candidate(list(response.candidates))
        selected_candidate_id: str = ""
        for idx, candidate in enumerate(response.candidates):
            cand = models.GeocodeEnrichmentCandidate.objects.create(
                result_set=row,
                candidate_rank=int(candidate.rank or idx + 1),
                provider_score=candidate.score,
                provider_confidence=candidate.confidence,
                matched_label=str(candidate.label or ""),
                matched_address=str(candidate.matched_address or ""),
                geometry_json=_safe_dict(candidate.location),
                spatial_reference_json=_safe_dict(candidate.spatial_reference),
                provider_attributes_json=_safe_dict(candidate.attributes),
                warnings_json=_safe_list(candidate.warnings),
                is_selected=selected_index == idx,
                status="ok" if selected_index == idx or not candidate.warnings else "warning",
            )
            if selected_index == idx:
                selected_candidate_id = str(cand.id)

        if selected_candidate_id:
            selected = models.GeocodeEnrichmentCandidate.objects.get(id=selected_candidate_id)
            row.selected_candidate = selected
            row.selection_reason = selection_reason
            row.status = "selected"
            row.save(update_fields=["selected_candidate", "selection_reason", "status", "updated_at"])

        provenance = ProvenanceService()
        geocode_result_ref = object_ref(
            object_family="geocode_enrichment_result",
            object_id=str(row.id),
            workspace_id=str(workspace.id),
            attributes={
                "provider_kind": row.provider_kind,
                "status": row.status,
            },
        )
        adapted_ref = object_ref(
            object_family="ingest_adapted_record",
            object_id=str(adapted.id),
            workspace_id=str(workspace.id),
        )
        provenance.record_provenance_link(
            ProvenanceLinkInput(
                workspace_id=str(workspace.id),
                relationship_type="geocode_enrichment_from_adapted",
                source_ref=adapted_ref,
                target_ref=geocode_result_ref,
                reason="geocoding enrichment evaluated from adapted record",
                run_id=str(adapted.orchestration_run_id or ""),
                idempotency_key=f"geocode.from_adapted:{row.id}",
            )
        )
        if row.selected_candidate_id:
            selected_ref = object_ref(
                object_family="geocode_enrichment_candidate",
                object_id=str(row.selected_candidate_id),
                workspace_id=str(workspace.id),
            )
            provenance.record_provenance_link(
                ProvenanceLinkInput(
                    workspace_id=str(workspace.id),
                    relationship_type="geocode_selected_candidate",
                    source_ref=geocode_result_ref,
                    target_ref=selected_ref,
                    reason="deterministic candidate selection",
                    run_id=str(adapted.orchestration_run_id or ""),
                    idempotency_key=f"geocode.selected:{row.id}",
                )
            )
        return row

    def geocode_for_source(
        self,
        *,
        workspace_id: str,
        source_id: str,
        run_id: str = "",
        limit: int = 500,
    ) -> list[models.GeocodeEnrichmentResult]:
        qs = models.IngestAdaptedRecord.objects.filter(workspace_id=workspace_id, source_connector_id=source_id).order_by("created_at", "id")
        if run_id:
            qs = qs.filter(orchestration_run_id=run_id)
        rows = list(qs[: max(1, min(5000, int(limit or 500)))])
        return [self.geocode_adapted_record(adapted_record_id=str(row.id)) for row in rows]

    def selected_for_adapted_record(self, *, adapted_record_id: str) -> models.GeocodeEnrichmentResult | None:
        return (
            models.GeocodeEnrichmentResult.objects.filter(adapted_record_id=adapted_record_id, status="selected")
            .select_related("selected_candidate")
            .order_by("-created_at")
            .first()
        )


def serialize_geocode_candidate(row: models.GeocodeEnrichmentCandidate) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "result_set_id": str(row.result_set_id),
        "candidate_rank": int(row.candidate_rank or 0),
        "provider_score": float(row.provider_score) if row.provider_score is not None else None,
        "provider_confidence": float(row.provider_confidence) if row.provider_confidence is not None else None,
        "matched_label": str(row.matched_label or ""),
        "matched_address": str(row.matched_address or ""),
        "geometry": _safe_dict(row.geometry_json),
        "spatial_reference": _safe_dict(row.spatial_reference_json),
        "provider_attributes": _safe_dict(row.provider_attributes_json),
        "warnings": _safe_list(row.warnings_json),
        "is_selected": bool(row.is_selected),
        "status": str(row.status or ""),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def serialize_geocode_result(row: models.GeocodeEnrichmentResult, *, include_candidates: bool = False) -> dict[str, Any]:
    selected_summary = None
    if row.selected_candidate_id:
        selected = row.selected_candidate
        if selected is not None:
            selected_summary = {
                "id": str(selected.id),
                "candidate_rank": int(selected.candidate_rank or 0),
                "provider_score": float(selected.provider_score) if selected.provider_score is not None else None,
                "matched_address": str(selected.matched_address or ""),
                "geometry": _safe_dict(selected.geometry_json),
            }
    payload = {
        "id": str(row.id),
        "workspace_id": str(row.workspace_id),
        "source_id": str(row.source_connector_id) if row.source_connector_id else None,
        "run_id": str(row.orchestration_run_id) if row.orchestration_run_id else None,
        "job_run_id": str(row.job_run_id) if row.job_run_id else None,
        "adapted_record_id": str(row.adapted_record_id) if row.adapted_record_id else None,
        "provider_kind": str(row.provider_kind or ""),
        "provider_name": str(row.provider_name or ""),
        "provider_version": str(row.provider_version or ""),
        "provider_endpoint_url": str(row.provider_endpoint_url or ""),
        "input_address_raw": str(row.input_address_raw or ""),
        "input_address_normalized": str(row.input_address_normalized or ""),
        "input_address_fields": _safe_dict(row.input_address_fields_json),
        "request_fingerprint": str(row.request_fingerprint or ""),
        "idempotency_key": str(row.idempotency_key or ""),
        "status": str(row.status or ""),
        "failure_category": str(row.failure_category or ""),
        "failure_reason": str(row.failure_reason or ""),
        "selection_reason": str(row.selection_reason or ""),
        "selected_candidate": selected_summary,
        "request_context": _safe_dict(row.request_context_json),
        "response_context": _safe_dict(row.response_context_json),
        "metadata": _safe_dict(row.metadata_json),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    if include_candidates:
        payload["candidates"] = [serialize_geocode_candidate(item) for item in row.candidates.order_by("candidate_rank", "created_at")]
    return payload

