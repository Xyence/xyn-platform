from __future__ import annotations

import hashlib
import io
import os
import uuid
from dataclasses import dataclass
from typing import Any, BinaryIO

import requests

from .contract import DurableArtifactStore, StoredArtifact
from ..managed_storage import store_local_artifact


def _core_base_url() -> str:
    return str(os.environ.get("XYN_CORE_BASE_URL") or "http://xyn-core:8000").strip().rstrip("/")


@dataclass(frozen=True)
class RuntimeArtifactStoreClient(DurableArtifactStore):
    base_url: str
    timeout: int = 30

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

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
        return self.store_stream(
            name=name,
            kind=kind,
            content_type=content_type,
            stream=io.BytesIO(content),
            workspace_id=workspace_id,
            storage_scope=storage_scope,
            sync_state=sync_state,
        )

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
        files = {"file": (name, stream, content_type)}
        data = {
            "name": name,
            "kind": kind,
            "content_type": content_type,
            "storage_scope": storage_scope,
            "sync_state": sync_state,
        }
        if workspace_id:
            data["workspace_id"] = workspace_id
        response = requests.post(
            self._url("/api/v1/artifacts"),
            data=data,
            files=files,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Failed to store artifact via xyn-core: {response.status_code} {response.text[:200]}")
        payload = response.json() if response.content else {}
        return StoredArtifact(
            artifact_id=str(payload.get("id") or payload.get("artifact_id") or ""),
            uri=str(payload.get("uri") or ""),
            storage_provider=str(payload.get("storage_scope") or "runtime"),
            storage_key=str(payload.get("storage_path") or payload.get("uri") or ""),
            content_type=str(payload.get("content_type") or content_type),
            byte_length=int(payload.get("byte_length") or 0),
            sha256=str(payload.get("sha256") or "") or None,
        )

    def get_metadata(self, *, artifact_id: str) -> StoredArtifact | None:
        response = requests.get(self._url(f"/api/v1/artifacts/{artifact_id}"), timeout=self.timeout)
        if response.status_code >= 400:
            return None
        payload = response.json() if response.content else {}
        return StoredArtifact(
            artifact_id=str(payload.get("id") or payload.get("artifact_id") or artifact_id),
            uri=str(payload.get("uri") or ""),
            storage_provider=str(payload.get("storage_scope") or "runtime"),
            storage_key=str(payload.get("storage_path") or payload.get("uri") or ""),
            content_type=str(payload.get("content_type") or ""),
            byte_length=int(payload.get("byte_length") or 0),
            sha256=str(payload.get("sha256") or "") or None,
        )


@dataclass(frozen=True)
class LocalDurableArtifactStore(DurableArtifactStore):
    namespace: str = "ingest-artifacts"

    def _persist(self, *, name: str, content: bytes) -> StoredArtifact:
        artifact_id = uuid.uuid4()
        sha256_hash = hashlib.sha256(content).hexdigest()
        filename = f"{artifact_id}-{name}"
        stored = store_local_artifact(self.namespace, "local", filename, content)
        return StoredArtifact(
            artifact_id=str(artifact_id),
            uri=stored.url,
            storage_provider="local",
            storage_key=stored.key,
            content_type=str(stored.metadata.get("content_type") or "application/octet-stream"),
            byte_length=int(stored.size_bytes),
            sha256=sha256_hash,
        )

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
        return self._persist(name=name, content=content)

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
        payload = stream.read()
        if payload is None:
            payload = b""
        if not isinstance(payload, (bytes, bytearray)):
            payload = bytes(payload)
        return self._persist(name=name, content=bytes(payload))

    def get_metadata(self, *, artifact_id: str) -> StoredArtifact | None:
        return None


def get_durable_artifact_store() -> DurableArtifactStore:
    provider = str(os.environ.get("XYN_PLATFORM_DURABLE_ARTIFACT_PROVIDER") or "core").strip().lower()
    if provider == "local":
        return LocalDurableArtifactStore()
    return RuntimeArtifactStoreClient(base_url=_core_base_url())
