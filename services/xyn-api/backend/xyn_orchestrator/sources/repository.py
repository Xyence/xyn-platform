from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db import transaction
from django.db.models import QuerySet

from xyn_orchestrator.models import (
    OrchestrationRun,
    SourceConnector,
    SourceInspectionProfile,
    SourceMapping,
    UserIdentity,
    Workspace,
)


class SourceConnectorRepository:
    def list_sources(self, *, workspace_id: str) -> QuerySet[SourceConnector]:
        return SourceConnector.objects.filter(workspace_id=workspace_id).select_related("last_run", "created_by").order_by("-updated_at", "-created_at")

    def get_source(self, *, source_id: str) -> SourceConnector:
        return SourceConnector.objects.select_related("workspace", "last_run", "created_by").get(id=source_id)

    @transaction.atomic
    def create_source(
        self,
        *,
        workspace_id: str,
        key: str,
        name: str,
        source_type: str,
        source_mode: str,
        refresh_cadence_seconds: int,
        orchestration_pipeline_key: str,
        configuration: dict[str, Any],
        provenance: dict[str, Any],
        metadata: dict[str, Any],
        created_by_id: str = "",
    ) -> SourceConnector:
        workspace = Workspace.objects.get(id=workspace_id)
        created_by = UserIdentity.objects.filter(id=created_by_id).first() if created_by_id else None
        return SourceConnector.objects.create(
            workspace=workspace,
            key=key,
            name=name,
            source_type=source_type,
            source_mode=source_mode,
            refresh_cadence_seconds=max(0, int(refresh_cadence_seconds or 0)),
            orchestration_pipeline_key=orchestration_pipeline_key,
            configuration_json=configuration,
            provenance_json=provenance,
            metadata_json=metadata,
            created_by=created_by,
        )

    @transaction.atomic
    def update_source(self, *, source: SourceConnector, update_fields: list[str]) -> SourceConnector:
        normalized = [field for field in update_fields if field]
        if "updated_at" not in normalized:
            normalized.append("updated_at")
        source.save(update_fields=normalized)
        return source

    @transaction.atomic
    def create_inspection(
        self,
        *,
        source: SourceConnector,
        status: str,
        detected_format: str,
        discovered_fields: list[dict[str, Any]],
        sample_metadata: dict[str, Any],
        validation_findings: list[dict[str, Any]],
        inspected_by_id: str = "",
        inspection_run_id: str = "",
    ) -> SourceInspectionProfile:
        inspected_by = UserIdentity.objects.filter(id=inspected_by_id).first() if inspected_by_id else None
        inspection_run = OrchestrationRun.objects.filter(id=inspection_run_id, workspace=source.workspace).first() if inspection_run_id else None
        row = SourceInspectionProfile.objects.create(
            source_connector=source,
            status=status,
            detected_format=detected_format,
            discovered_fields_json=discovered_fields,
            sample_metadata_json=sample_metadata,
            validation_findings_json=validation_findings,
            inspected_by=inspected_by,
            inspection_run=inspection_run,
        )
        source.last_inspected_at = row.inspected_at
        return row

    def list_inspections(self, *, source: SourceConnector) -> QuerySet[SourceInspectionProfile]:
        return source.inspections.select_related("inspected_by", "inspection_run").order_by("-inspected_at", "-id")

    @transaction.atomic
    def create_mapping(
        self,
        *,
        source: SourceConnector,
        status: str,
        field_mapping: dict[str, Any],
        transformation_hints: dict[str, Any],
        validation_state: dict[str, Any],
        validated_by_id: str = "",
        validation_run_id: str = "",
        now: datetime | None = None,
    ) -> SourceMapping:
        current = source.mappings.filter(is_current=True)
        for row in current:
            row.is_current = False
            row.save(update_fields=["is_current", "updated_at"])
        next_version = int(source.mappings.count()) + 1
        validated_by = UserIdentity.objects.filter(id=validated_by_id).first() if validated_by_id else None
        validation_run = OrchestrationRun.objects.filter(id=validation_run_id, workspace=source.workspace).first() if validation_run_id else None
        mapping = SourceMapping.objects.create(
            source_connector=source,
            version=next_version,
            status=status,
            is_current=True,
            field_mapping_json=field_mapping,
            transformation_hints_json=transformation_hints,
            validation_state_json=validation_state,
            validated_at=now if status in {"validated", "active"} else None,
            validated_by=validated_by,
            validation_run=validation_run,
            created_by=validated_by,
        )
        return mapping

    def list_mappings(self, *, source: SourceConnector) -> QuerySet[SourceMapping]:
        return source.mappings.select_related("validated_by", "validation_run", "created_by").order_by("-version", "-created_at")
