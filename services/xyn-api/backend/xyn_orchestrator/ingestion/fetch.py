from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests

from xyn_orchestrator.models import SourceConnector, Workspace
from xyn_orchestrator.storage import IngestStorageService, RetentionClass, SnapshotType

from .interfaces import FetchRequest, FetchResult

logger = logging.getLogger(__name__)


class HttpArtifactFetcher:
    def __init__(self, *, storage: IngestStorageService | None = None) -> None:
        self._storage = storage or IngestStorageService()

    @staticmethod
    def _filename_from_response(url: str, headers: dict[str, Any]) -> str:
        content_disposition = str(headers.get("content-disposition") or "")
        if "filename=" in content_disposition:
            part = content_disposition.split("filename=", 1)[-1].strip().strip('"').strip("'")
            if part:
                return os.path.basename(part)
        path_name = os.path.basename(urlparse(url).path)
        return path_name or "download.bin"

    def fetch_to_artifact(
        self,
        *,
        workspace: Workspace,
        source_connector: SourceConnector,
        orchestration_run,
        scope_jurisdiction: str,
        scope_source: str,
        request: FetchRequest,
    ) -> FetchResult:
        source_url = str(request.source_url or "").strip()
        if not source_url:
            raise ValueError("source_url is required")
        timeout = (max(1, int(request.connect_timeout_seconds or 10)), max(1, int(request.timeout_seconds or 60)))
        fetched_at = datetime.now(timezone.utc)
        response_status = 0
        final_url = source_url
        headers: dict[str, Any] = {}
        sha256_hash = hashlib.sha256()
        tmp = tempfile.NamedTemporaryFile(prefix="xyn-ingest-fetch-", suffix=".bin", delete=False)
        tmp_path = tmp.name
        try:
            logger.info("ingestion.fetch.start", extra={"source_url": source_url})
            with requests.get(source_url, stream=True, timeout=timeout, headers=request.headers or {}) as response:
                response.raise_for_status()
                response_status = int(response.status_code)
                final_url = str(response.url or source_url)
                headers = dict(response.headers)
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    sha256_hash.update(chunk)
                    tmp.write(chunk)
            tmp.flush()
            tmp.close()
            content_type = str(headers.get("content-type") or "application/octet-stream").split(";", 1)[0].strip()
            original_filename = self._filename_from_response(final_url, headers)
            with open(tmp_path, "rb") as stream:
                stored = self._storage.store_snapshot_stream(
                    workspace=workspace,
                    name=original_filename,
                    content_type=content_type,
                    stream=stream,
                    snapshot_type=SnapshotType.RAW,
                    retention_class=RetentionClass.SNAPSHOT,
                    source_connector=source_connector,
                    orchestration_run=orchestration_run,
                    scope_jurisdiction=scope_jurisdiction,
                    scope_source=scope_source,
                    metadata={"source_url": source_url, "final_url": final_url},
                )
            row = stored.record
            row.source_url = source_url
            row.final_url = final_url
            row.original_filename = original_filename
            row.response_status = response_status
            row.etag = str(headers.get("etag") or "")
            row.last_modified = str(headers.get("last-modified") or "")
            row.fetched_at = fetched_at
            row.sha256 = sha256_hash.hexdigest()
            row.save(
                update_fields=[
                    "source_url",
                    "final_url",
                    "original_filename",
                    "response_status",
                    "etag",
                    "last_modified",
                    "fetched_at",
                    "sha256",
                ]
            )
            logger.info("ingestion.fetch.success", extra={"artifact_id": str(row.id), "source_url": source_url})
            length_raw = headers.get("content-length")
            content_length = int(length_raw) if str(length_raw or "").isdigit() else None
            return FetchResult(
                source_url=source_url,
                final_url=final_url,
                response_status=response_status,
                content_type=content_type,
                content_length=content_length,
                etag=row.etag,
                last_modified=row.last_modified,
                sha256=row.sha256,
                fetched_at_iso=fetched_at.isoformat(),
                original_filename=original_filename,
                local_path=tmp_path,
                artifact_record_id=str(row.id),
            )
        except Exception:
            if not tmp.closed:
                tmp.close()
            logger.exception("ingestion.fetch.failed", extra={"source_url": source_url})
            raise
