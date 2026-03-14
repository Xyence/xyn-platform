from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from django.conf import settings


_SAFE_COMPONENT_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _safe_component(value: Any, *, default: str) -> str:
    token = _SAFE_COMPONENT_RE.sub("-", str(value or "").strip()).strip(".-")
    return token or default


def _media_root_path() -> Path:
    raw = str(getattr(settings, "MEDIA_ROOT", "") or "").strip() or "/app/media"
    return Path(raw).resolve()


def managed_artifact_root() -> Path:
    raw = (
        str(getattr(settings, "MEDIA_ROOT", "") or "").strip()
        or str(os.environ.get("XYN_ARTIFACT_ROOT", "")).strip()
        or str(os.environ.get("XYENCE_ARTIFACT_ROOT", "")).strip()
        or str(os.environ.get("XYN_MEDIA_ROOT", "")).strip()
        or str(os.environ.get("XYENCE_MEDIA_ROOT", "")).strip()
        or str(_media_root_path())
    )
    root = Path(raw).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def managed_workspace_root() -> Path:
    raw = (
        str(os.environ.get("XYN_WORKSPACE_ROOT", "")).strip()
        or str(os.environ.get("XYENCE_CODEGEN_WORKDIR", "")).strip()
        or "/app/workspaces"
    )
    root = Path(raw).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def workspace_retention_days() -> int:
    raw = str(os.environ.get("XYN_WORKSPACE_RETENTION_DAYS", "14")).strip() or "14"
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 14


def _safe_relative_path(parts: Iterable[Any]) -> Path:
    cleaned = [_safe_component(part, default="item") for part in parts if str(part or "").strip()]
    return Path(*cleaned) if cleaned else Path("item")


def managed_workspace_path(*parts: Any) -> Path:
    return managed_workspace_root() / _safe_relative_path(parts)


def materialize_managed_workspace(*parts: Any, reset: bool = False) -> Path:
    workspace = managed_workspace_path(*parts)
    root = managed_workspace_root()
    if not str(workspace).startswith(str(root)):
        raise ValueError("workspace path escapes managed workspace root")
    if reset and workspace.exists():
        shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True, exist_ok=True)
    marker = workspace / ".xyn-workspace.json"
    if not marker.exists():
        marker.write_text(
            json.dumps(
                {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "path": str(workspace.relative_to(root)),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return workspace


def codegen_task_workspace(task_id: Any, *, reset: bool = False) -> Path:
    return materialize_managed_workspace("codegen", "tasks", task_id, reset=reset)


@dataclass(frozen=True)
class WorkspaceCleanupCandidate:
    path: str
    relative_path: str
    last_modified_at: str
    age_days: int


def stale_workspace_candidates(*, now: Optional[datetime] = None) -> list[WorkspaceCleanupCandidate]:
    root = managed_workspace_root()
    reference = now or datetime.now(timezone.utc)
    cutoff_seconds = workspace_retention_days() * 86400
    rows: list[WorkspaceCleanupCandidate] = []
    for child in sorted(root.glob("**/.xyn-workspace.json")):
        workspace_dir = child.parent
        try:
            stat = workspace_dir.stat()
        except OSError:
            continue
        age_seconds = max(0, reference.timestamp() - stat.st_mtime)
        if age_seconds < cutoff_seconds:
            continue
        modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        rows.append(
            WorkspaceCleanupCandidate(
                path=str(workspace_dir),
                relative_path=str(workspace_dir.relative_to(root)),
                last_modified_at=modified_at.isoformat(),
                age_days=int(age_seconds // 86400),
            )
        )
    return rows


@dataclass(frozen=True)
class StoredLocalArtifact:
    provider: str
    key: str
    path: str
    url: str
    size_bytes: int
    metadata: dict[str, Any]


def _serialize_content(content: str | bytes | dict | list) -> tuple[bytes, str]:
    if isinstance(content, bytes):
        return content, "application/octet-stream"
    if isinstance(content, (dict, list)):
        return json.dumps(content, indent=2).encode("utf-8"), "application/json"
    return str(content).encode("utf-8"), "text/plain"


def store_local_artifact(namespace: str, owner_id: Any, filename: str, content: str | bytes | dict | list) -> StoredLocalArtifact:
    artifact_root = managed_artifact_root()
    safe_namespace = _safe_relative_path(str(namespace or "artifacts").replace("\\", "/").split("/"))
    safe_owner = _safe_component(owner_id, default="owner")
    safe_filename = _safe_component(filename, default="artifact")
    rel_key = safe_namespace / safe_owner / safe_filename
    target = artifact_root / rel_key
    target.parent.mkdir(parents=True, exist_ok=True)
    payload, content_type = _serialize_content(content)
    target.write_bytes(payload)
    media_prefix = str(getattr(settings, "MEDIA_URL", "/media/") or "/media/").rstrip("/")
    metadata = {
        "provider": "local",
        "key": str(rel_key),
        "path": str(target),
        "size_bytes": len(payload),
        "content_type": content_type,
        "managed_root": str(artifact_root),
    }
    return StoredLocalArtifact(
        provider="local",
        key=str(rel_key),
        path=str(target),
        url=f"{media_prefix}/{rel_key.as_posix()}",
        size_bytes=len(payload),
        metadata=metadata,
    )


def resolve_local_artifact_path(*, url: str = "", storage_path: str = "", storage_key: str = "") -> Optional[Path]:
    if storage_path:
        candidate = Path(storage_path)
        return candidate if candidate.exists() else None
    if storage_key:
        candidate = managed_artifact_root() / storage_key
        return candidate if candidate.exists() else None
    if not url:
        return None
    media_url = str(getattr(settings, "MEDIA_URL", "/media/") or "/media/").rstrip("/") + "/"
    if url.startswith("/media/"):
        rel = url.replace("/media/", "", 1)
    elif url.startswith(media_url):
        rel = url.replace(media_url, "", 1)
    else:
        return None
    candidate = managed_artifact_root() / rel
    return candidate if candidate.exists() else None


def load_local_artifact_json(*, url: str = "", storage_path: str = "", storage_key: str = "") -> Optional[dict[str, Any]]:
    candidate = resolve_local_artifact_path(url=url, storage_path=storage_path, storage_key=storage_key)
    if not candidate:
        return None
    try:
        return json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_local_artifact_text(*, url: str = "", storage_path: str = "", storage_key: str = "") -> Optional[str]:
    candidate = resolve_local_artifact_path(url=url, storage_path=storage_path, storage_key=storage_key)
    if not candidate:
        return None
    try:
        return candidate.read_text(encoding="utf-8")
    except OSError:
        return None


def delete_local_artifact(*, url: str = "", storage_path: str = "", storage_key: str = "") -> None:
    candidate = resolve_local_artifact_path(url=url, storage_path=storage_path, storage_key=storage_key)
    if not candidate:
        return
    try:
        candidate.unlink(missing_ok=True)
    except OSError:
        return
