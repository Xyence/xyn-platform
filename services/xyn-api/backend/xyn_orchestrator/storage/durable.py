from __future__ import annotations

import hashlib
import io
import os
import secrets
import uuid
from dataclasses import dataclass
from typing import Any, BinaryIO

import requests

from .contract import DurableArtifactStore, StoredArtifact
from ..managed_storage import store_local_artifact


def _core_base_url() -> str:
    return str(os.environ.get("XYN_CORE_BASE_URL") or "http://xyn-core:8000").strip().rstrip("/")


def _core_timeout_seconds() -> int:
    raw = str(os.environ.get("XYN_CORE_REQUEST_TIMEOUT_SECONDS") or "300").strip()
    try:
        return max(5, min(int(raw), 1800))
    except ValueError:
        return 300


@dataclass(frozen=True)
class RuntimeArtifactStoreClient(DurableArtifactStore):
    base_url: str
    timeout: int = 300

    @staticmethod
    def _multipart_stream(
        *,
        boundary: str,
        field_name: str,
        filename: str,
        content_type: str,
        stream: BinaryIO,
        chunk_size: int = 1024 * 1024,
    ) -> tuple[object, int]:
        # Build a streaming multipart body to avoid buffering entire artifacts in memory.
        preamble = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
        epilogue = f"\r\n--{boundary}--\r\n".encode("utf-8")

        try:
            start = stream.tell()
            stream.seek(0, os.SEEK_END)
            size = stream.tell() - start
            stream.seek(start, os.SEEK_SET)
        except Exception as exc:  # pragma: no cover - defensive fallback
            raise RuntimeError("artifact stream must be seekable for streaming upload") from exc

        class _BodyIterable:
            def __init__(self) -> None:
                self._length = len(preamble) + max(0, int(size)) + len(epilogue)

            def __len__(self) -> int:
                return self._length

            def __iter__(self):
                yield preamble
                stream.seek(start, os.SEEK_SET)
                while True:
                    chunk = stream.read(chunk_size)
                    if not chunk:
                        break
                    if not isinstance(chunk, (bytes, bytearray)):
                        chunk = bytes(chunk)
                    yield bytes(chunk)
                yield epilogue

            def read(self, amt: int = 1024 * 1024) -> bytes:
                # requests can consume iterables directly; expose a conservative read() for compatibility.
                if amt is None or amt <= 0:
                    amt = 1024 * 1024
                if not hasattr(self, "_iter"):
                    self._iter = iter(self)
                    self._buffer = b""
                out = bytearray()
                while len(out) < amt:
                    if self._buffer:
                        take = min(len(self._buffer), amt - len(out))
                        out.extend(self._buffer[:take])
                        self._buffer = self._buffer[take:]
                        continue
                    try:
                        nxt = next(self._iter)
                    except StopIteration:
                        break
                    if len(out) + len(nxt) <= amt:
                        out.extend(nxt)
                    else:
                        overflow_at = amt - len(out)
                        out.extend(nxt[:overflow_at])
                        self._buffer = nxt[overflow_at:]
                return bytes(out)

        content_length = len(preamble) + max(0, int(size)) + len(epilogue)
        return _BodyIterable(), content_length

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
        boundary = f"xyn-{secrets.token_hex(12)}"
        body_stream, content_length = self._multipart_stream(
            boundary=boundary,
            field_name="file",
            filename=name,
            content_type=content_type,
            stream=stream,
        )
        # xyn-core artifact endpoint currently models non-file inputs as query parameters.
        params = {
            "name": name,
            "kind": kind,
            "content_type": content_type,
            "storage_scope": storage_scope,
            "sync_state": sync_state,
        }
        # xyn-platform workspace IDs are not guaranteed to exist in xyn-core.
        # Keep artifact durability cross-runtime by avoiding hard workspace coupling here.
        response = requests.post(
            self._url("/api/v1/artifacts"),
            params=params,
            data=body_stream,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(content_length),
            },
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
    return RuntimeArtifactStoreClient(base_url=_core_base_url(), timeout=_core_timeout_seconds())
