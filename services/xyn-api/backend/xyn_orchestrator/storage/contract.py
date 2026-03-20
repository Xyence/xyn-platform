from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, BinaryIO, Protocol


class RetentionClass(str, Enum):
    EPHEMERAL = "ephemeral"
    SNAPSHOT = "snapshot"
    PUBLISHED = "published"


class SnapshotType(str, Enum):
    RAW = "raw"
    NORMALIZED = "normalized"
    RECONCILED = "reconciled"
    SIGNALS = "signals"
    DERIVED = "derived"


@dataclass(frozen=True)
class StoredArtifact:
    artifact_id: str
    uri: str
    storage_provider: str
    storage_key: str
    content_type: str
    byte_length: int
    sha256: str | None


@dataclass(frozen=True)
class IngestArtifactMetadata:
    workspace_id: str
    artifact_id: str
    artifact_uri: str
    storage_provider: str
    storage_key: str
    content_type: str
    byte_length: int
    sha256: str | None
    snapshot_type: str
    retention_class: str
    source_connector_id: str = ""
    orchestration_run_id: str = ""
    job_run_id: str = ""
    scope_jurisdiction: str = ""
    scope_source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


class DurableArtifactStore(Protocol):
    def store_bytes(
        self,
        *,
        name: str,
        kind: str,
        content_type: str,
        content: bytes,
        workspace_id: str = "",
        storage_scope: str = "instance-local",
        sync_state: str = "local",
    ) -> StoredArtifact:
        ...

    def store_stream(
        self,
        *,
        name: str,
        kind: str,
        content_type: str,
        stream: BinaryIO,
        workspace_id: str = "",
        storage_scope: str = "instance-local",
        sync_state: str = "local",
    ) -> StoredArtifact:
        ...

    def get_metadata(self, *, artifact_id: str) -> StoredArtifact | None:
        ...
