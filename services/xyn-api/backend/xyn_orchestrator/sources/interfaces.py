from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

SOURCE_LIFECYCLE_STATES: tuple[str, ...] = (
    "registered",
    "inspected",
    "mapped",
    "validated",
    "active",
    "failing",
    "paused",
)

SOURCE_MODES: tuple[str, ...] = (
    "file_upload",
    "remote_url",
    "api_polling",
    "manual",
)

SOURCE_HEALTH_STATES: tuple[str, ...] = (
    "unknown",
    "healthy",
    "warning",
    "failing",
    "paused",
)


@dataclass(frozen=True)
class SourceRegistration:
    workspace_id: str
    key: str
    name: str
    source_type: str = "generic"
    source_mode: str = "manual"
    refresh_cadence_seconds: int = 0
    orchestration_pipeline_key: str = ""
    configuration: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_by_id: str = ""


@dataclass(frozen=True)
class SourceInspectionInput:
    source_id: str
    status: str = "ok"
    detected_format: str = ""
    discovered_fields: list[dict[str, Any]] = field(default_factory=list)
    sample_metadata: dict[str, Any] = field(default_factory=dict)
    validation_findings: list[dict[str, Any]] = field(default_factory=list)
    inspected_by_id: str = ""
    inspection_run_id: str = ""
    idempotency_key: str = ""


@dataclass(frozen=True)
class SourceMappingInput:
    source_id: str
    status: str = "draft"
    field_mapping: dict[str, Any] = field(default_factory=dict)
    transformation_hints: dict[str, Any] = field(default_factory=dict)
    validation_state: dict[str, Any] = field(default_factory=dict)
    validated_by_id: str = ""
    validation_run_id: str = ""
    idempotency_key: str = ""


@dataclass(frozen=True)
class SourceReadiness:
    source_id: str
    ready: bool
    lifecycle_state: str
    reasons: tuple[str, ...] = tuple()
    checked_at: datetime | None = None


@dataclass(frozen=True)
class SourceHealthUpdate:
    source_id: str
    health_status: str
    lifecycle_state: str | None = None
    success: bool = False
    failure_reason: str = ""
    run_id: str = ""
