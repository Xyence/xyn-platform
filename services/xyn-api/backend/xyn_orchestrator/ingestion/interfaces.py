from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, BinaryIO, Iterable, Protocol


FILE_KIND_ZIP = "zip"
FILE_KIND_CSV = "csv"
FILE_KIND_TSV = "tsv"
FILE_KIND_GEOJSON = "geojson"
FILE_KIND_JSON = "json"
FILE_KIND_XLSX = "xlsx"
FILE_KIND_XLS = "xls"
FILE_KIND_SHP = "shp"
FILE_KIND_DBF = "dbf"
FILE_KIND_SHX = "shx"
FILE_KIND_PRJ = "prj"
FILE_KIND_CPG = "cpg"
FILE_KIND_MDB = "mdb"
FILE_KIND_ACCDB = "accdb"
FILE_KIND_XML = "xml"
FILE_KIND_PDF = "pdf"
FILE_KIND_UNKNOWN_BINARY = "unknown_binary"


@dataclass(frozen=True)
class FileClassification:
    kind: str
    extension: str
    group_key: str = ""
    mime_type: str = ""


@dataclass(frozen=True)
class FetchRequest:
    source_url: str
    timeout_seconds: int = 60
    connect_timeout_seconds: int = 10
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class FetchResult:
    source_url: str
    final_url: str
    response_status: int
    content_type: str
    content_length: int | None
    etag: str
    last_modified: str
    sha256: str
    fetched_at_iso: str
    original_filename: str
    local_path: str
    artifact_record_id: str


@dataclass(frozen=True)
class ParseTarget:
    workspace_id: str
    source_connector_id: str
    orchestration_run_id: str
    artifact_record_id: str
    member_id: str = ""
    source_path: str = ""
    classified_kind: str = ""
    group_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedRecordEnvelope:
    source_payload: dict[str, Any]
    normalized_payload: dict[str, Any]
    source_schema: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    status: str = "ok"
    record_index: int | None = None


@dataclass(frozen=True)
class ParseOutcome:
    parser_name: str
    parser_version: str
    normalization_version: str
    records: tuple[ParsedRecordEnvelope, ...]
    warnings: tuple[str, ...] = tuple()


class IngestionParser(Protocol):
    name: str
    version: str
    supported_kinds: tuple[str, ...]

    def parse(self, *, target: ParseTarget, stream: BinaryIO) -> ParseOutcome:
        ...


class IngestionParserRegistry(Protocol):
    def register(self, parser: IngestionParser) -> None:
        ...

    def resolve(self, kind: str) -> IngestionParser | None:
        ...

    def supported_kinds(self) -> Iterable[str]:
        ...
