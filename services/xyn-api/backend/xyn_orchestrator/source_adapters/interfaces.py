from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from xyn_orchestrator import models


ADAPTER_STATUS_OK = "ok"
ADAPTER_STATUS_WARNING = "warning"
ADAPTER_STATUS_ERROR = "error"
ADAPTER_STATUS_UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class AdaptedRecordEnvelope:
    adapter_kind: str
    source_format: str
    source_subtype: str = ""
    adapted_payload: dict[str, Any] = field(default_factory=dict)
    geometry_payload: dict[str, Any] | None = None
    field_metadata: list[dict[str, Any]] = field(default_factory=list)
    schema_hints: dict[str, Any] = field(default_factory=dict)
    source_position: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    status: str = ADAPTER_STATUS_OK
    failure_reason: str = ""
    record_index: int | None = None


@dataclass(frozen=True)
class AdaptationOutcome:
    adapter_name: str
    adapter_version: str
    records: tuple[AdaptedRecordEnvelope, ...]
    warnings: tuple[str, ...] = tuple()


@dataclass(frozen=True)
class AdapterContext:
    source_connector: models.SourceConnector
    parsed_row: models.IngestParsedRecord


class ParsedRecordAdapter(Protocol):
    name: str
    version: str
    adapter_kind: str

    def supports(self, *, context: AdapterContext) -> bool:
        ...

    def adapt(self, *, context: AdapterContext) -> AdaptationOutcome:
        ...
