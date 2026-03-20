from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from django.utils import timezone

from xyn_orchestrator.models import SourceConnector, SourceInspectionProfile, SourceMapping
from xyn_orchestrator.provenance import AuditEventInput, ProvenanceService, object_ref
from xyn_orchestrator.geospatial.utils import compute_centroid, extract_bbox, normalize_geometry

from .interfaces import (
    SOURCE_HEALTH_STATES,
    SOURCE_LIFECYCLE_STATES,
    SOURCE_MODES,
    SourceHealthUpdate,
    SourceInspectionInput,
    SourceMappingInput,
    SourceReadiness,
    SourceRegistration,
)
from .repository import SourceConnectorRepository


@dataclass(frozen=True)
class SourceExecutionContract:
    source_id: str
    workspace_id: str
    run_type: str
    target_ref: dict[str, Any]
    scope_source: str
    orchestration_pipeline_key: str


class SourceConnectorService:
    def __init__(self, *, repository: SourceConnectorRepository | None = None):
        self._repository = repository or SourceConnectorRepository()

    def register_source(self, registration: SourceRegistration) -> SourceConnector:
        key = str(registration.key or "").strip().lower().replace(" ", "_")
        name = str(registration.name or "").strip()
        if not key:
            raise ValueError("source key is required")
        if not name:
            raise ValueError("source name is required")
        mode = str(registration.source_mode or "manual").strip().lower()
        if mode not in SOURCE_MODES:
            raise ValueError(f"unsupported source_mode '{mode}'")
        return self._repository.create_source(
            workspace_id=registration.workspace_id,
            key=key,
            name=name,
            source_type=str(registration.source_type or "generic").strip().lower() or "generic",
            source_mode=mode,
            refresh_cadence_seconds=max(0, int(registration.refresh_cadence_seconds or 0)),
            orchestration_pipeline_key=str(registration.orchestration_pipeline_key or "").strip(),
            configuration=registration.configuration if isinstance(registration.configuration, dict) else {},
            provenance=registration.provenance if isinstance(registration.provenance, dict) else {},
            metadata=registration.metadata if isinstance(registration.metadata, dict) else {},
            created_by_id=str(registration.created_by_id or "").strip(),
        )

    def list_sources(self, *, workspace_id: str):
        return self._repository.list_sources(workspace_id=workspace_id)

    def get_source(self, *, source_id: str) -> SourceConnector:
        return self._repository.get_source(source_id=source_id)

    def record_inspection(self, payload: SourceInspectionInput) -> SourceInspectionProfile:
        source = self._repository.get_source(source_id=payload.source_id)
        status = str(payload.status or "ok").strip().lower()
        if status not in {"ok", "warning", "error"}:
            raise ValueError("inspection status must be one of ok, warning, error")
        row = self._repository.create_inspection(
            source=source,
            status=status,
            detected_format=str(payload.detected_format or "").strip(),
            discovered_fields=payload.discovered_fields if isinstance(payload.discovered_fields, list) else [],
            sample_metadata=payload.sample_metadata if isinstance(payload.sample_metadata, dict) else {},
            validation_findings=payload.validation_findings if isinstance(payload.validation_findings, list) else [],
            inspected_by_id=str(payload.inspected_by_id or "").strip(),
            inspection_run_id=str(payload.inspection_run_id or "").strip(),
            idempotency_key=str(payload.idempotency_key or "").strip(),
        )
        source.last_inspected_at = row.inspected_at
        source.lifecycle_state = "inspected"
        self._repository.update_source(source=source, update_fields=["last_inspected_at", "lifecycle_state"])
        return row

    def update_mapping(self, payload: SourceMappingInput) -> SourceMapping:
        source = self._repository.get_source(source_id=payload.source_id)
        status = str(payload.status or "draft").strip().lower()
        if status not in {"draft", "validated", "active"}:
            raise ValueError("mapping status must be one of draft, validated, active")
        now = timezone.now()
        row = self._repository.create_mapping(
            source=source,
            status=status,
            field_mapping=payload.field_mapping if isinstance(payload.field_mapping, dict) else {},
            transformation_hints=payload.transformation_hints if isinstance(payload.transformation_hints, dict) else {},
            validation_state=payload.validation_state if isinstance(payload.validation_state, dict) else {},
            validated_by_id=str(payload.validated_by_id or "").strip(),
            validation_run_id=str(payload.validation_run_id or "").strip(),
            now=now,
            idempotency_key=str(payload.idempotency_key or "").strip(),
        )
        if status in {"validated", "active"}:
            source.last_validated_at = now
            source.lifecycle_state = "validated"
            self._repository.update_source(source=source, update_fields=["last_validated_at", "lifecycle_state"])
        else:
            source.lifecycle_state = "mapped"
            self._repository.update_source(source=source, update_fields=["lifecycle_state"])
        return row

    def validate_readiness(self, *, source_id: str) -> SourceReadiness:
        source = self._repository.get_source(source_id=source_id)
        reasons: list[str] = []
        if source.inspections.count() == 0:
            reasons.append("source has not been inspected")
        current_mapping = source.mappings.filter(is_current=True).order_by("-version").first()
        if current_mapping is None:
            reasons.append("source has no mapping")
        elif current_mapping.status not in {"validated", "active"}:
            reasons.append("current mapping is not validated")
        if source.source_mode in {"remote_url", "api_polling"} and source.refresh_cadence_seconds <= 0:
            reasons.append("refresh cadence must be > 0 for remote/api sources")
        return SourceReadiness(
            source_id=str(source.id),
            ready=len(reasons) == 0,
            lifecycle_state=str(source.lifecycle_state or "registered"),
            reasons=tuple(reasons),
            checked_at=timezone.now(),
        )

    def activate_source(self, *, source_id: str) -> SourceConnector:
        source = self._repository.get_source(source_id=source_id)
        readiness = self.validate_readiness(source_id=source_id)
        if not readiness.ready:
            raise ValueError("source is not ready for activation")
        source.is_active = True
        source.lifecycle_state = "active"
        source.health_status = "healthy" if source.health_status == "unknown" else source.health_status
        source.last_failure_reason = ""
        updated = self._repository.update_source(
            source=source,
            update_fields=["is_active", "lifecycle_state", "health_status", "last_failure_reason"],
        )
        ProvenanceService().record_audit_event(
            AuditEventInput(
                workspace_id=str(updated.workspace_id),
                event_type="source_connector.activated",
                subject_ref=object_ref(
                    object_family="source_connector",
                    object_id=str(updated.id),
                    workspace_id=str(updated.workspace_id),
                    attributes={"key": str(updated.key), "source_type": str(updated.source_type)},
                ),
                summary=f"Source connector {updated.key} activated",
                reason="readiness checks passed",
                metadata={"lifecycle_state": str(updated.lifecycle_state), "health_status": str(updated.health_status)},
                idempotency_key=hashlib.sha256(
                    f"source.activate|{updated.workspace_id}|{updated.id}|{updated.lifecycle_state}".encode("utf-8")
                ).hexdigest(),
            )
        )
        return updated

    def pause_source(self, *, source_id: str) -> SourceConnector:
        source = self._repository.get_source(source_id=source_id)
        source.is_active = False
        source.lifecycle_state = "paused"
        source.health_status = "paused"
        updated = self._repository.update_source(source=source, update_fields=["is_active", "lifecycle_state", "health_status"])
        ProvenanceService().record_audit_event(
            AuditEventInput(
                workspace_id=str(updated.workspace_id),
                event_type="source_connector.paused",
                subject_ref=object_ref(
                    object_family="source_connector",
                    object_id=str(updated.id),
                    workspace_id=str(updated.workspace_id),
                    attributes={"key": str(updated.key), "source_type": str(updated.source_type)},
                ),
                summary=f"Source connector {updated.key} paused",
                reason="paused by platform/operator flow",
                metadata={"lifecycle_state": str(updated.lifecycle_state), "health_status": str(updated.health_status)},
                idempotency_key=hashlib.sha256(
                    f"source.pause|{updated.workspace_id}|{updated.id}|{updated.lifecycle_state}".encode("utf-8")
                ).hexdigest(),
            )
        )
        return updated

    def update_health(self, payload: SourceHealthUpdate) -> SourceConnector:
        source = self._repository.get_source(source_id=payload.source_id)
        next_health = str(payload.health_status or "unknown").strip().lower()
        if next_health not in SOURCE_HEALTH_STATES:
            raise ValueError(f"unsupported health_status '{next_health}'")
        source.health_status = next_health
        update_fields = ["health_status"]
        if payload.lifecycle_state:
            state = str(payload.lifecycle_state or "").strip().lower()
            if state not in SOURCE_LIFECYCLE_STATES:
                raise ValueError(f"unsupported lifecycle_state '{state}'")
            source.lifecycle_state = state
            update_fields.append("lifecycle_state")
        if payload.success:
            source.last_success_at = timezone.now()
            source.last_failure_reason = ""
            update_fields.extend(["last_success_at", "last_failure_reason"])
        if payload.failure_reason:
            source.last_failure_at = timezone.now()
            source.last_failure_reason = str(payload.failure_reason or "").strip()
            source.lifecycle_state = "failing"
            update_fields.extend(["last_failure_at", "last_failure_reason", "lifecycle_state"])
        if payload.run_id:
            run = source.workspace.orchestration_runs.filter(id=payload.run_id).first()
            if run is not None:
                source.last_run = run
                update_fields.append("last_run")
        updated = self._repository.update_source(source=source, update_fields=update_fields)
        ProvenanceService().record_audit_event(
            AuditEventInput(
                workspace_id=str(updated.workspace_id),
                event_type="source_connector.health_updated",
                subject_ref=object_ref(
                    object_family="source_connector",
                    object_id=str(updated.id),
                    workspace_id=str(updated.workspace_id),
                    attributes={"key": str(updated.key), "source_type": str(updated.source_type)},
                ),
                summary=f"Health updated for source connector {updated.key}",
                reason=str(payload.failure_reason or "health state change"),
                metadata={
                    "health_status": str(updated.health_status),
                    "lifecycle_state": str(updated.lifecycle_state),
                    "success": bool(payload.success),
                },
                run_id=str(payload.run_id or ""),
                idempotency_key=hashlib.sha256(
                    "|".join(
                        [
                            "source.health",
                            str(updated.workspace_id),
                            str(updated.id),
                            str(updated.health_status),
                            str(updated.lifecycle_state),
                            str(bool(payload.success)),
                            str(payload.failure_reason or ""),
                            str(payload.run_id or ""),
                        ]
                    ).encode("utf-8")
                ).hexdigest(),
            )
        )
        return updated

    def build_execution_contract(self, *, source_id: str) -> SourceExecutionContract:
        source = self._repository.get_source(source_id=source_id)
        return SourceExecutionContract(
            source_id=str(source.id),
            workspace_id=str(source.workspace_id),
            run_type="ingest.source_refresh",
            target_ref={
                "target_type": "source_connector",
                "target_id": str(source.id),
                "source_key": str(source.key),
                "source_type": str(source.source_type),
            },
            scope_source=str(source.key),
            orchestration_pipeline_key=str(source.orchestration_pipeline_key or "").strip(),
        )


def serialize_source_connector(source: SourceConnector, *, readiness: SourceReadiness | None = None) -> dict[str, Any]:
    current_mapping = source.mappings.filter(is_current=True).order_by("-version").first()
    latest_inspection = source.inspections.order_by("-inspected_at", "-id").first()
    return {
        "id": str(source.id),
        "workspace_id": str(source.workspace_id),
        "key": source.key,
        "name": source.name,
        "source_type": source.source_type,
        "source_mode": source.source_mode,
        "lifecycle_state": source.lifecycle_state,
        "health_status": source.health_status,
        "is_active": bool(source.is_active),
        "refresh_cadence_seconds": int(source.refresh_cadence_seconds or 0),
        "orchestration_pipeline_key": str(source.orchestration_pipeline_key or ""),
        "configuration": source.configuration_json if isinstance(source.configuration_json, dict) else {},
        "provenance": source.provenance_json if isinstance(source.provenance_json, dict) else {},
        "metadata": source.metadata_json if isinstance(source.metadata_json, dict) else {},
        "last_run_id": str(source.last_run_id) if source.last_run_id else None,
        "last_inspected_at": source.last_inspected_at.isoformat() if source.last_inspected_at else None,
        "last_validated_at": source.last_validated_at.isoformat() if source.last_validated_at else None,
        "last_success_at": source.last_success_at.isoformat() if source.last_success_at else None,
        "last_failure_at": source.last_failure_at.isoformat() if source.last_failure_at else None,
        "last_failure_reason": source.last_failure_reason or "",
        "current_mapping": {
            "id": str(current_mapping.id),
            "version": int(current_mapping.version),
            "status": current_mapping.status,
        }
        if current_mapping
        else None,
        "latest_inspection": {
            "id": str(latest_inspection.id),
            "status": latest_inspection.status,
            "detected_format": latest_inspection.detected_format,
            "inspected_at": latest_inspection.inspected_at.isoformat() if latest_inspection.inspected_at else None,
        }
        if latest_inspection
        else None,
        "readiness": {
            "ready": bool(readiness.ready),
            "reasons": list(readiness.reasons),
            "checked_at": readiness.checked_at.isoformat() if readiness.checked_at else None,
        }
        if readiness
        else None,
        "created_by_id": str(source.created_by_id) if source.created_by_id else None,
        "created_at": source.created_at.isoformat() if source.created_at else None,
        "updated_at": source.updated_at.isoformat() if source.updated_at else None,
    }


def serialize_source_inspection(row: SourceInspectionProfile) -> dict[str, Any]:
    sample_metadata = row.sample_metadata_json if isinstance(row.sample_metadata_json, dict) else {}
    discovered_fields = row.discovered_fields_json if isinstance(row.discovered_fields_json, list) else []
    sample_rows = sample_metadata.get("sample_rows")
    if not isinstance(sample_rows, list):
        sample_rows = []
    geometry_summary, geometry_errors = _summarize_geometry(sample_metadata, sample_rows)
    profile_summary = {
        "row_count": _as_int(sample_metadata.get("row_count"))
        or _as_int(sample_metadata.get("total_rows"))
        or _as_int(sample_metadata.get("sample_row_count")),
        "discovered_fields_count": len(discovered_fields),
        "has_sample_rows": bool(sample_rows),
        "has_geometry": bool(geometry_summary and geometry_summary.get("present")),
    }
    enriched_metadata = {**sample_metadata, "sample_rows": sample_rows, "profile_summary": profile_summary}
    if geometry_summary or geometry_errors:
        enriched_metadata["geometry_summary"] = geometry_summary or {"present": False, "errors": geometry_errors}
    elif "geometry_summary" in enriched_metadata:
        enriched_metadata["geometry_summary"] = None
    validation_findings = row.validation_findings_json if isinstance(row.validation_findings_json, list) else []
    if geometry_errors:
        validation_findings = [
            *validation_findings,
            {
                "type": "geometry_summary_error",
                "message": "Geometry metadata could not be summarized for preview.",
                "details": geometry_errors,
            },
        ]
    return {
        "id": str(row.id),
        "source_id": str(row.source_connector_id),
        "status": row.status,
        "detected_format": row.detected_format,
        "discovered_fields": discovered_fields,
        "sample_metadata": enriched_metadata,
        "validation_findings": validation_findings,
        "inspection_fingerprint": str(row.inspection_fingerprint or ""),
        "idempotency_key": str(row.idempotency_key or ""),
        "inspection_run_id": str(row.inspection_run_id) if row.inspection_run_id else None,
        "inspected_by_id": str(row.inspected_by_id) if row.inspected_by_id else None,
        "inspected_at": row.inspected_at.isoformat() if row.inspected_at else None,
    }


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _summarize_geometry(sample_metadata: dict[str, Any], sample_rows: list[dict[str, Any]]):
    geometries: list[dict[str, Any]] = []
    errors: list[str] = []

    def add_geometry(candidate: Any) -> None:
        if not candidate:
            return
        if isinstance(candidate, dict) and "type" in candidate and "coordinates" in candidate:
            geometries.append(candidate)
            return
        if isinstance(candidate, Iterable) and not isinstance(candidate, (str, bytes, dict)):
            for item in candidate:
                add_geometry(item)

    add_geometry(sample_metadata.get("geometry"))
    add_geometry(sample_metadata.get("geometry_geojson"))

    for row in sample_rows:
        if not isinstance(row, dict):
            continue
        add_geometry(row.get("geometry"))
        add_geometry(row.get("geometry_geojson"))
        add_geometry(row.get("geom"))
        add_geometry(row.get("geom_geojson"))

    if not geometries:
        return None, []

    bbox_values: list[float] = []
    centroid_lons: list[float] = []
    centroid_lats: list[float] = []
    geometry_types: set[str] = set()
    for geometry in geometries:
        try:
            normalized = normalize_geometry(geometry)
            geometry_types.add(normalized.get("type", ""))
            bbox = extract_bbox(normalized)
            bbox_values.append(bbox.west)
            bbox_values.append(bbox.south)
            bbox_values.append(bbox.east)
            bbox_values.append(bbox.north)
            centroid = compute_centroid(normalized)
            centroid_lons.append(centroid.lon)
            centroid_lats.append(centroid.lat)
        except Exception as exc:
            errors.append(str(exc))

    if not geometry_types:
        return {"present": False, "errors": errors}, errors

    minx = min(bbox_values[0::4]) if bbox_values else None
    miny = min(bbox_values[1::4]) if bbox_values else None
    maxx = max(bbox_values[2::4]) if bbox_values else None
    maxy = max(bbox_values[3::4]) if bbox_values else None
    centroid = None
    if centroid_lons and centroid_lats:
        centroid = {
            "x": sum(centroid_lons) / len(centroid_lons),
            "y": sum(centroid_lats) / len(centroid_lats),
        }
    summary = {
        "present": True,
        "geometry_types": sorted({item for item in geometry_types if item}),
        "bbox": [minx, miny, maxx, maxy] if None not in (minx, miny, maxx, maxy) else None,
        "centroid": centroid,
    }
    if errors:
        summary["errors"] = errors
    return summary, errors


def serialize_source_mapping(row: SourceMapping) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "source_id": str(row.source_connector_id),
        "version": int(row.version),
        "status": row.status,
        "is_current": bool(row.is_current),
        "field_mapping": row.field_mapping_json if isinstance(row.field_mapping_json, dict) else {},
        "transformation_hints": row.transformation_hints_json if isinstance(row.transformation_hints_json, dict) else {},
        "validation_state": row.validation_state_json if isinstance(row.validation_state_json, dict) else {},
        "mapping_hash": str(row.mapping_hash or ""),
        "idempotency_key": str(row.idempotency_key or ""),
        "validated_at": row.validated_at.isoformat() if row.validated_at else None,
        "validated_by_id": str(row.validated_by_id) if row.validated_by_id else None,
        "validation_run_id": str(row.validation_run_id) if row.validation_run_id else None,
        "created_by_id": str(row.created_by_id) if row.created_by_id else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
