from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from django.db import transaction

from xyn_orchestrator import models
from xyn_orchestrator.matching.normalization import normalize_address_record, normalize_parcel_id, normalize_text
from xyn_orchestrator.provenance import ProvenanceLinkInput, ProvenanceService, object_ref


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _normalized_namespace(value: Any) -> str:
    token = str(value or "").strip().lower().replace(" ", "_")
    return token


def _extract_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for token in [part.strip() for part in str(path or "").split(".") if part.strip()]:
        if not isinstance(current, dict):
            return None
        current = current.get(token)
    return current


@dataclass(frozen=True)
class IdentifierCandidate:
    namespace: str
    raw_value: str
    normalized_value: str
    source_path: str = ""
    is_composite: bool = False
    parts: tuple[dict[str, Any], ...] = tuple()


class ParcelIdentityResolverService:
    DEFAULT_IDENTIFIER_FIELDS: tuple[tuple[str, str], ...] = (
        ("handle", "attributes.HANDLE"),
        ("handle", "attributes.handle"),
        ("handle", "record.HANDLE"),
        ("handle", "record.handle"),
        ("parcel", "attributes.PARCEL"),
        ("parcel", "attributes.parcel"),
        ("parcel", "record.PARCEL"),
        ("parcel", "record.parcel"),
        ("cityblock", "attributes.CITYBLOCK"),
        ("cityblock", "attributes.cityblock"),
        ("cityblock", "record.CITYBLOCK"),
        ("cityblock", "record.cityblock"),
        ("ref_id", "attributes.Ref_ID"),
        ("ref_id", "attributes.REF_ID"),
        ("ref_id", "attributes.ref_id"),
        ("ref_id", "record.Ref_ID"),
        ("ref_id", "record.REF_ID"),
        ("source_key", "record.id"),
        ("source_key", "record.source_key"),
    )
    DEFAULT_ADDRESS_FIELDS: tuple[tuple[str, str], ...] = (
        ("address", "attributes.address"),
        ("address", "attributes.ADDRESS"),
        ("address", "attributes.siteaddress"),
        ("address", "attributes.site_addr"),
        ("address", "attributes.site_address"),
        ("address", "attributes.SITEADDR"),
        ("address", "record.address"),
        ("address", "record.ADDRESS"),
        ("address", "record.site_address"),
        ("address", "record.SITEADDR"),
    )
    DEFAULT_COMPOSITES: tuple[dict[str, Any], ...] = (
        {
            "namespace": "cityblock_parcel",
            "parts": (
                {"namespace": "cityblock", "path": "attributes.CITYBLOCK"},
                {"namespace": "parcel", "path": "attributes.PARCEL"},
            ),
            "delimiter": "|",
        },
    )

    def _normalize_identifier(self, *, namespace: str, raw_value: Any, jurisdiction: str = "") -> str:
        token = _normalized_namespace(namespace)
        raw = str(raw_value or "").strip()
        if not raw:
            return ""
        if token in {"address", "site_address"}:
            return str(normalize_address_record(raw, jurisdiction=jurisdiction or None).get("normalized") or "").strip()
        if token in {"parcel", "parcel_id", "handle", "cityblock", "cityblock_parcel", "ref_id", "apn"}:
            return str(normalize_parcel_id(raw, jurisdiction=jurisdiction or None).get("normalized") or "").strip()
        return normalize_text(raw)

    def _configuration(self, source: models.SourceConnector) -> dict[str, Any]:
        cfg = _safe_dict(source.configuration_json)
        parcel_cfg = _safe_dict(cfg.get("parcel_identity"))
        return parcel_cfg

    def _extract_candidates(self, *, adapted: models.IngestAdaptedRecord) -> tuple[list[IdentifierCandidate], list[IdentifierCandidate]]:
        payload = _safe_dict(adapted.adapted_payload_json)
        source = adapted.source_connector
        run = getattr(adapted, "orchestration_run", None)
        jurisdiction = str(getattr(run, "scope_jurisdiction", "") or "")
        config = self._configuration(source) if source else {}
        identifier_fields = _safe_list(config.get("identifier_fields"))
        if not identifier_fields:
            identifier_fields = [{"namespace": ns, "path": path} for ns, path in self.DEFAULT_IDENTIFIER_FIELDS]
        address_fields = _safe_list(config.get("address_fields"))
        if not address_fields:
            address_fields = [{"namespace": ns, "path": path} for ns, path in self.DEFAULT_ADDRESS_FIELDS]
        composites = _safe_list(config.get("composite_identifiers"))
        if not composites:
            composites = [dict(item) for item in self.DEFAULT_COMPOSITES]

        identifiers: list[IdentifierCandidate] = []
        for row in identifier_fields:
            if not isinstance(row, dict):
                continue
            namespace = _normalized_namespace(row.get("namespace") or "")
            path = str(row.get("path") or "").strip()
            if not namespace or not path:
                continue
            raw = _extract_path(payload, path)
            raw_value = str(raw or "").strip()
            normalized = self._normalize_identifier(namespace=namespace, raw_value=raw_value, jurisdiction=jurisdiction)
            if not normalized:
                continue
            identifiers.append(
                IdentifierCandidate(
                    namespace=namespace,
                    raw_value=raw_value,
                    normalized_value=normalized,
                    source_path=path,
                )
            )

        for row in composites:
            if not isinstance(row, dict):
                continue
            namespace = _normalized_namespace(row.get("namespace") or "")
            parts = _safe_list(row.get("parts"))
            delimiter = str(row.get("delimiter") or "|")
            if not namespace or not parts:
                continue
            part_rows: list[dict[str, Any]] = []
            normalized_parts: list[str] = []
            raw_parts: list[str] = []
            for part in parts:
                if not isinstance(part, dict):
                    continue
                part_ns = _normalized_namespace(part.get("namespace") or "")
                path = str(part.get("path") or "").strip()
                if not part_ns or not path:
                    continue
                raw = _extract_path(payload, path)
                raw_value = str(raw or "").strip()
                normalized = self._normalize_identifier(namespace=part_ns, raw_value=raw_value, jurisdiction=jurisdiction)
                if not normalized:
                    part_rows = []
                    break
                raw_parts.append(raw_value)
                normalized_parts.append(normalized)
                part_rows.append({"namespace": part_ns, "path": path, "raw": raw_value, "normalized": normalized})
            if not part_rows:
                continue
            identifiers.append(
                IdentifierCandidate(
                    namespace=namespace,
                    raw_value=delimiter.join(raw_parts),
                    normalized_value=delimiter.join(normalized_parts),
                    source_path="composite",
                    is_composite=True,
                    parts=tuple(part_rows),
                )
            )

        addresses: list[IdentifierCandidate] = []
        for row in address_fields:
            if not isinstance(row, dict):
                continue
            namespace = _normalized_namespace(row.get("namespace") or "address")
            path = str(row.get("path") or "").strip()
            if not path:
                continue
            raw = _extract_path(payload, path)
            raw_value = str(raw or "").strip()
            normalized = self._normalize_identifier(namespace=namespace, raw_value=raw_value, jurisdiction=jurisdiction)
            if not normalized:
                continue
            addresses.append(
                IdentifierCandidate(
                    namespace=namespace or "address",
                    raw_value=raw_value,
                    normalized_value=normalized,
                    source_path=path,
                )
            )
        return identifiers, addresses

    def _find_by_alias(self, *, workspace: models.Workspace, namespace: str, normalized_value: str) -> models.ParcelCanonicalIdentity | None:
        alias = (
            models.ParcelIdentifierAlias.objects.filter(
                workspace=workspace,
                namespace=_normalized_namespace(namespace),
                value_normalized=normalized_value,
                status="active",
            )
            .select_related("parcel")
            .order_by("-is_canonical", "-confidence", "-created_at")
            .first()
        )
        return alias.parcel if alias else None

    def _create_canonical(self, *, workspace: models.Workspace, candidate: IdentifierCandidate | None) -> models.ParcelCanonicalIdentity:
        namespace = _normalized_namespace(candidate.namespace if candidate else "")
        raw_value = candidate.raw_value if candidate else ""
        normalized_value = candidate.normalized_value if candidate else ""
        if namespace and normalized_value:
            existing = models.ParcelCanonicalIdentity.objects.filter(
                workspace=workspace,
                canonical_namespace=namespace,
                canonical_value_normalized=normalized_value,
                status="active",
            ).first()
            if existing is not None:
                return existing
        return models.ParcelCanonicalIdentity.objects.create(
            workspace=workspace,
            canonical_namespace=namespace,
            canonical_value_raw=raw_value,
            canonical_value_normalized=normalized_value,
            status="active",
        )

    def _ensure_alias(
        self,
        *,
        workspace: models.Workspace,
        parcel: models.ParcelCanonicalIdentity,
        source_connector: models.SourceConnector | None,
        candidate: IdentifierCandidate,
        is_canonical: bool,
        confidence: float,
    ) -> models.ParcelIdentifierAlias:
        namespace = _normalized_namespace(candidate.namespace)
        alias, _ = models.ParcelIdentifierAlias.objects.get_or_create(
            workspace=workspace,
            parcel=parcel,
            namespace=namespace,
            value_normalized=candidate.normalized_value,
            defaults={
                "value_raw": candidate.raw_value,
                "source_connector": source_connector,
                "is_canonical": is_canonical,
                "confidence": confidence,
                "status": "active",
                "metadata_json": {"source_path": candidate.source_path, "is_composite": bool(candidate.is_composite), "parts": list(candidate.parts)},
            },
        )
        return alias

    def _crosswalk_idempotency_key(self, *, adapted: models.IngestAdaptedRecord) -> str:
        return hashlib.sha256(
            f"parcel-crosswalk|{adapted.workspace_id}|{adapted.id}|{adapted.updated_at.isoformat() if adapted.updated_at else adapted.created_at.isoformat()}".encode(
                "utf-8"
            )
        ).hexdigest()

    @transaction.atomic
    def resolve_adapted_record(self, *, adapted_record_id: str, idempotency_key: str = "") -> models.ParcelCrosswalkMapping:
        adapted = models.IngestAdaptedRecord.objects.select_related("workspace", "source_connector", "orchestration_run").get(
            id=adapted_record_id
        )
        workspace = adapted.workspace
        source_connector = adapted.source_connector
        normalized_idempotency_key = str(idempotency_key or "").strip() or self._crosswalk_idempotency_key(adapted=adapted)
        existing = models.ParcelCrosswalkMapping.objects.filter(
            workspace=workspace,
            idempotency_key=normalized_idempotency_key,
        ).first()
        if existing is not None:
            return existing

        identifiers, addresses = self._extract_candidates(adapted=adapted)
        parcel: models.ParcelCanonicalIdentity | None = None
        method = "unresolved"
        status = "unresolved"
        confidence = 0.0
        reason = "no usable parcel identifiers found"
        primary_candidate: IdentifierCandidate | None = identifiers[0] if identifiers else None
        explanation: dict[str, Any] = {
            "identifier_candidates": [
                {
                    "namespace": item.namespace,
                    "raw_value": item.raw_value,
                    "normalized_value": item.normalized_value,
                    "source_path": item.source_path,
                    "is_composite": bool(item.is_composite),
                    "parts": list(item.parts),
                }
                for item in identifiers
            ],
            "address_candidates": [
                {
                    "namespace": item.namespace,
                    "raw_value": item.raw_value,
                    "normalized_value": item.normalized_value,
                    "source_path": item.source_path,
                }
                for item in addresses
            ],
        }
        geocode_result = None
        try:
            from xyn_orchestrator.geocoding.service import GeocodingService

            geocode_result = GeocodingService().selected_for_adapted_record(adapted_record_id=str(adapted.id))
        except Exception:
            geocode_result = None
        if geocode_result is not None:
            selected = geocode_result.selected_candidate
            explanation["geocoding_evidence"] = {
                "geocode_result_id": str(geocode_result.id),
                "status": str(geocode_result.status or ""),
                "provider_kind": str(geocode_result.provider_kind or ""),
                "selected_candidate_id": str(selected.id) if selected else None,
                "selected_score": float(selected.provider_score) if selected and selected.provider_score is not None else None,
                "selected_address": str(selected.matched_address or "") if selected else "",
            }

        for candidate in identifiers:
            found = self._find_by_alias(workspace=workspace, namespace=candidate.namespace, normalized_value=candidate.normalized_value)
            if found is not None:
                parcel = found
                method = "deterministic_composite" if candidate.is_composite else "deterministic_identifier"
                status = "resolved"
                confidence = 1.0
                reason = "matched existing parcel alias"
                primary_candidate = candidate
                break

        if parcel is None and identifiers:
            primary_candidate = identifiers[0]
            parcel = self._create_canonical(workspace=workspace, candidate=primary_candidate)
            method = "deterministic_composite" if primary_candidate.is_composite else "deterministic_identifier"
            status = "resolved"
            confidence = 1.0
            reason = "created canonical parcel from deterministic identifier"

        if parcel is None and addresses:
            for candidate in addresses:
                found = self._find_by_alias(workspace=workspace, namespace="address", normalized_value=candidate.normalized_value)
                if found is not None:
                    parcel = found
                    method = "address_fallback"
                    status = "resolved"
                    confidence = 0.55
                    reason = "matched canonical parcel via normalized address fallback"
                    primary_candidate = candidate
                    break

        if parcel is None and adapted.geometry_payload_json:
            method = "deferred_geospatial"
            status = "deferred"
            confidence = 0.25
            reason = "no deterministic identifier match; geospatial fallback not configured in this pass"

        if parcel is not None and primary_candidate is not None:
            self._ensure_alias(
                workspace=workspace,
                parcel=parcel,
                source_connector=source_connector,
                candidate=primary_candidate,
                is_canonical=True if method.startswith("deterministic") and parcel.canonical_namespace == _normalized_namespace(primary_candidate.namespace) else False,
                confidence=confidence,
            )
            for candidate in identifiers:
                self._ensure_alias(
                    workspace=workspace,
                    parcel=parcel,
                    source_connector=source_connector,
                    candidate=candidate,
                    is_canonical=False,
                    confidence=1.0 if candidate.is_composite else confidence,
                )
            for candidate in addresses:
                self._ensure_alias(
                    workspace=workspace,
                    parcel=parcel,
                    source_connector=source_connector,
                    candidate=candidate,
                    is_canonical=False,
                    confidence=0.55,
                )

        mapping = models.ParcelCrosswalkMapping.objects.create(
            workspace=workspace,
            source_connector=source_connector,
            adapted_record=adapted,
            parcel=parcel,
            namespace=_normalized_namespace(primary_candidate.namespace if primary_candidate else ""),
            identifier_value_raw=primary_candidate.raw_value if primary_candidate else "",
            identifier_value_normalized=primary_candidate.normalized_value if primary_candidate else "",
            composite_key_normalized=primary_candidate.normalized_value if (primary_candidate and primary_candidate.is_composite) else "",
            status=status,
            resolution_method=method,
            confidence=confidence,
            reason=reason,
            explanation_json=explanation,
            metadata_json={
                "adapter_kind": str(adapted.adapter_kind or ""),
                "source_format": str(adapted.source_format or ""),
                "adapted_record_id": str(adapted.id),
            },
            idempotency_key=normalized_idempotency_key,
        )

        provenance = ProvenanceService()
        crosswalk_ref = object_ref(
            object_family="parcel_crosswalk_mapping",
            object_id=str(mapping.id),
            workspace_id=str(workspace.id),
            attributes={"resolution_method": mapping.resolution_method, "status": mapping.status, "confidence": float(mapping.confidence)},
        )
        adapted_ref = object_ref(
            object_family="ingest_adapted_record",
            object_id=str(adapted.id),
            workspace_id=str(workspace.id),
            attributes={"adapter_kind": str(adapted.adapter_kind or ""), "source_format": str(adapted.source_format or "")},
        )
        provenance.record_provenance_link(
            ProvenanceLinkInput(
                workspace_id=str(workspace.id),
                relationship_type="parcel_crosswalk_derived_from",
                source_ref=adapted_ref,
                target_ref=crosswalk_ref,
                reason="parcel resolver processed adapted record",
                explanation={"resolution_method": mapping.resolution_method},
                run_id=str(adapted.orchestration_run_id or ""),
                idempotency_key=f"parcel.crosswalk.from_adapted:{mapping.id}",
            )
        )
        if parcel is not None:
            parcel_ref = object_ref(
                object_family="parcel_canonical_identity",
                object_id=str(parcel.id),
                workspace_id=str(workspace.id),
                attributes={
                    "canonical_namespace": str(parcel.canonical_namespace or ""),
                    "canonical_value_normalized": str(parcel.canonical_value_normalized or ""),
                },
            )
            provenance.record_provenance_link(
                ProvenanceLinkInput(
                    workspace_id=str(workspace.id),
                    relationship_type="parcel_crosswalk_resolved_to",
                    source_ref=crosswalk_ref,
                    target_ref=parcel_ref,
                    reason="crosswalk resolved to canonical parcel",
                    explanation={"resolution_method": mapping.resolution_method, "confidence": float(mapping.confidence)},
                    run_id=str(adapted.orchestration_run_id or ""),
                    idempotency_key=f"parcel.crosswalk.to_parcel:{mapping.id}",
                )
            )
        if geocode_result is not None:
            geocode_ref = object_ref(
                object_family="geocode_enrichment_result",
                object_id=str(geocode_result.id),
                workspace_id=str(workspace.id),
                attributes={
                    "provider_kind": str(geocode_result.provider_kind or ""),
                    "status": str(geocode_result.status or ""),
                },
            )
            provenance.record_provenance_link(
                ProvenanceLinkInput(
                    workspace_id=str(workspace.id),
                    relationship_type="parcel_crosswalk_enriched_by_geocode",
                    source_ref=geocode_ref,
                    target_ref=crosswalk_ref,
                    reason="parcel crosswalk resolution included geocoding evidence",
                    run_id=str(adapted.orchestration_run_id or ""),
                    idempotency_key=f"parcel.crosswalk.geocode:{mapping.id}:{geocode_result.id}",
                )
            )

        return mapping

    @transaction.atomic
    def resolve_for_source(
        self,
        *,
        workspace_id: str,
        source_id: str,
        run_id: str = "",
        limit: int = 500,
    ) -> list[models.ParcelCrosswalkMapping]:
        source = models.SourceConnector.objects.select_related("workspace").get(id=source_id, workspace_id=workspace_id)
        queryset = models.IngestAdaptedRecord.objects.filter(workspace_id=workspace_id, source_connector=source).order_by("created_at", "id")
        if run_id:
            queryset = queryset.filter(orchestration_run_id=run_id)
        rows = list(queryset[: max(1, min(5000, int(limit or 500)))])
        return [self.resolve_adapted_record(adapted_record_id=str(row.id)) for row in rows]

    def lookup_by_identifier(self, *, workspace_id: str, namespace: str, value: str) -> models.ParcelCanonicalIdentity | None:
        normalized = self._normalize_identifier(namespace=namespace, raw_value=value)
        if not normalized:
            return None
        alias = (
            models.ParcelIdentifierAlias.objects.filter(
                workspace_id=workspace_id,
                namespace=_normalized_namespace(namespace),
                value_normalized=normalized,
                status="active",
            )
            .select_related("parcel")
            .order_by("-is_canonical", "-confidence", "-created_at")
            .first()
        )
        return alias.parcel if alias else None


def serialize_parcel_identity(parcel: models.ParcelCanonicalIdentity) -> dict[str, Any]:
    aliases = list(parcel.aliases.order_by("-is_canonical", "-confidence", "-created_at"))
    return {
        "id": str(parcel.id),
        "workspace_id": str(parcel.workspace_id),
        "canonical_namespace": str(parcel.canonical_namespace or ""),
        "canonical_value_raw": str(parcel.canonical_value_raw or ""),
        "canonical_value_normalized": str(parcel.canonical_value_normalized or ""),
        "status": parcel.status,
        "metadata": _safe_dict(parcel.metadata_json),
        "aliases": [
            {
                "id": str(alias.id),
                "namespace": str(alias.namespace or ""),
                "value_raw": str(alias.value_raw or ""),
                "value_normalized": str(alias.value_normalized or ""),
                "source_id": str(alias.source_connector_id) if alias.source_connector_id else None,
                "is_canonical": bool(alias.is_canonical),
                "confidence": float(alias.confidence or 0.0),
                "status": alias.status,
                "valid_from": alias.valid_from.isoformat() if alias.valid_from else None,
                "valid_to": alias.valid_to.isoformat() if alias.valid_to else None,
                "metadata": _safe_dict(alias.metadata_json),
                "created_at": alias.created_at.isoformat() if alias.created_at else None,
            }
            for alias in aliases
        ],
        "created_at": parcel.created_at.isoformat() if parcel.created_at else None,
        "updated_at": parcel.updated_at.isoformat() if parcel.updated_at else None,
    }


def serialize_parcel_crosswalk(row: models.ParcelCrosswalkMapping) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "workspace_id": str(row.workspace_id),
        "source_id": str(row.source_connector_id) if row.source_connector_id else None,
        "adapted_record_id": str(row.adapted_record_id) if row.adapted_record_id else None,
        "parcel_id": str(row.parcel_id) if row.parcel_id else None,
        "record_match_evaluation_id": str(row.record_match_evaluation_id) if row.record_match_evaluation_id else None,
        "namespace": str(row.namespace or ""),
        "identifier_value_raw": str(row.identifier_value_raw or ""),
        "identifier_value_normalized": str(row.identifier_value_normalized or ""),
        "composite_key_normalized": str(row.composite_key_normalized or ""),
        "status": row.status,
        "resolution_method": row.resolution_method,
        "confidence": float(row.confidence or 0.0),
        "reason": str(row.reason or ""),
        "explanation": _safe_dict(row.explanation_json),
        "metadata": _safe_dict(row.metadata_json),
        "valid_from": row.valid_from.isoformat() if row.valid_from else None,
        "valid_to": row.valid_to.isoformat() if row.valid_to else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
