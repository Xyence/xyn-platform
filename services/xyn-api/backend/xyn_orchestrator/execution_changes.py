from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from .development_targets import resolve_development_target
from .managed_storage import load_local_artifact_text, managed_workspace_path
from .models import DevTask


_DIFF_HEADER_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_NAME_STATUS_RE = re.compile(r"^(?P<status>[A-Z][0-9]{0,3})\t(?P<paths>.+)$")


def _run_git(args: List[str], *, cwd: Path) -> Optional[str]:
    proc = subprocess.run(
        args,
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def _change_type_label(token: str) -> str:
    value = str(token or "").strip().upper()
    if value.startswith("A"):
        return "added"
    if value.startswith("D"):
        return "deleted"
    if value.startswith("R"):
        return "renamed"
    if value.startswith("C"):
        return "copied"
    if value.startswith("U"):
        return "conflicted"
    return "modified"


def _parse_name_status(output: str, *, patch_available: bool) -> List[Dict[str, Any]]:
    files: List[Dict[str, Any]] = []
    for raw_line in str(output or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _NAME_STATUS_RE.match(line)
        if not match:
            continue
        status = match.group("status")
        parts = [part.strip() for part in match.group("paths").split("\t") if part.strip()]
        if not parts:
            continue
        path = parts[-1]
        previous_path = parts[0] if len(parts) > 1 and status.startswith("R") else None
        files.append(
            {
                "path": path,
                "change_type": _change_type_label(status),
                "status_code": status,
                "previous_path": previous_path,
                "patch_available": patch_available,
            }
        )
    return files


def _parse_diff_text(diff_text: str, *, patch_available: bool) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for raw_line in str(diff_text or "").splitlines():
        header = _DIFF_HEADER_RE.match(raw_line)
        if header:
            if current:
                rows.append(current)
            before_path = header.group(1)
            after_path = header.group(2)
            path = after_path if after_path != "/dev/null" else before_path
            current = {
                "path": path,
                "change_type": "modified",
                "status_code": "M",
                "previous_path": None,
                "patch_available": patch_available,
            }
            continue
        if current is None:
            continue
        if raw_line.startswith("new file mode"):
            current["change_type"] = "added"
            current["status_code"] = "A"
        elif raw_line.startswith("deleted file mode"):
            current["change_type"] = "deleted"
            current["status_code"] = "D"
        elif raw_line.startswith("rename from "):
            current["change_type"] = "renamed"
            current["status_code"] = "R"
            current["previous_path"] = raw_line[len("rename from ") :].strip()
        elif raw_line.startswith("rename to "):
            current["path"] = raw_line[len("rename to ") :].strip() or current["path"]
    if current:
        rows.append(current)
    return rows


def _workspace_repo_path(task: DevTask, repo_slug: str) -> Path:
    return managed_workspace_path("codegen", "tasks", task.id, "repos", repo_slug)


def _workspace_change_set(task: DevTask, *, repo_slug: str, include_diff: bool) -> Optional[Dict[str, Any]]:
    repo_dir = _workspace_repo_path(task, repo_slug)
    if not (repo_dir / ".git").exists():
        return None
    diff_text = _run_git(["git", "diff", "--cached", "--patch", "-M"], cwd=repo_dir) or ""
    files = _parse_name_status(
        _run_git(["git", "diff", "--cached", "--name-status", "-M"], cwd=repo_dir) or "",
        patch_available=bool(diff_text.strip()),
    )
    if not files and diff_text.strip():
        files = _parse_diff_text(diff_text, patch_available=True)
    has_changes = bool(files) or bool(diff_text.strip())
    return {
        "available": True,
        "status": "changed" if has_changes else "no_changes",
        "has_changes": has_changes,
        "source": "workspace",
        "repository_slug": repo_slug,
        "workspace_path": str(repo_dir),
        "changed_file_count": len(files),
        "files": files,
        "patch_available": bool(diff_text.strip()),
        "diff_text": diff_text if include_diff and diff_text.strip() else None,
        "patch_artifact_name": None,
        "patch_artifact_url": None,
        "message": (
            f"{len(files)} file{'s' if len(files) != 1 else ''} changed in the managed workspace."
            if has_changes
            else "No managed workspace changes detected."
        ),
    }


def _artifact_patch_text(artifact: Dict[str, Any]) -> Optional[str]:
    url = str(artifact.get("url") or "").strip()
    metadata = artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}
    uri = str(metadata.get("uri") or "").strip()
    return (
        load_local_artifact_text(url=url)
        or load_local_artifact_text(url=uri)
        or None
    )


def _patch_artifact_rows(artifacts_payload: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for artifact in artifacts_payload:
        if not isinstance(artifact, dict):
            continue
        name = str(artifact.get("name") or "").strip()
        kind = str(artifact.get("kind") or "").strip().lower()
        metadata = artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}
        uri = str(metadata.get("uri") or "").strip()
        if name.lower().endswith((".diff", ".patch")) or kind in {"patch", "diff"} or uri.endswith((".diff", ".patch")):
            rows.append(artifact)
    return rows


def _artifact_change_set(
    *,
    repo_slug: Optional[str],
    artifacts_payload: List[Dict[str, Any]],
    include_diff: bool,
) -> Optional[Dict[str, Any]]:
    for artifact in _patch_artifact_rows(artifacts_payload):
        diff_text = _artifact_patch_text(artifact) or ""
        if not diff_text.strip():
            continue
        files = _parse_diff_text(diff_text, patch_available=True)
        return {
            "available": True,
            "status": "changed" if files or diff_text.strip() else "no_changes",
            "has_changes": bool(files) or bool(diff_text.strip()),
            "source": "artifact",
            "repository_slug": repo_slug,
            "workspace_path": None,
            "changed_file_count": len(files),
            "files": files,
            "patch_available": True,
            "diff_text": diff_text if include_diff else None,
            "patch_artifact_name": str(artifact.get("name") or "").strip() or None,
            "patch_artifact_url": str(artifact.get("url") or "").strip() or None,
            "message": f"{len(files)} file{'s' if len(files) != 1 else ''} changed in the latest stored patch artifact.",
        }
    return None


def resolve_dev_task_change_set(
    task: DevTask,
    *,
    execution_payload: Optional[Dict[str, Any]] = None,
    include_diff: bool = False,
) -> Dict[str, Any]:
    resolution = resolve_development_target(task=task)
    repo_slug = str(resolution.repository_slug or task.target_repo or "").strip() or None
    if repo_slug:
        workspace_change_set = _workspace_change_set(task, repo_slug=repo_slug, include_diff=include_diff)
        if workspace_change_set is not None:
            return workspace_change_set
    artifacts_payload = []
    if isinstance(execution_payload, dict):
        rows = execution_payload.get("artifacts_payload")
        if isinstance(rows, list):
            artifacts_payload = [row for row in rows if isinstance(row, dict)]
    if not artifacts_payload and getattr(task, "result_run_id", None) and getattr(task, "result_run", None) is not None:
        artifacts_payload = [
            {
                "id": str(artifact.id),
                "name": artifact.name,
                "kind": artifact.kind,
                "url": artifact.url,
                "metadata": artifact.metadata_json,
            }
            for artifact in task.result_run.artifacts.all().order_by("created_at")
        ]
    artifact_change_set = _artifact_change_set(repo_slug=repo_slug, artifacts_payload=artifacts_payload, include_diff=include_diff)
    if artifact_change_set is not None:
        return artifact_change_set
    if repo_slug:
        return {
            "available": False,
            "status": "unavailable",
            "has_changes": False,
            "source": None,
            "repository_slug": repo_slug,
            "workspace_path": None,
            "changed_file_count": 0,
            "files": [],
            "patch_available": False,
            "diff_text": None,
            "patch_artifact_name": None,
            "patch_artifact_url": None,
            "message": "No managed repository workspace or stored patch is available for change inspection.",
        }
    return {
        "available": False,
        "status": "unavailable",
        "has_changes": False,
        "source": None,
        "repository_slug": None,
        "workspace_path": None,
        "changed_file_count": 0,
        "files": [],
        "patch_available": False,
        "diff_text": None,
        "patch_artifact_name": None,
        "patch_artifact_url": None,
        "message": "This task does not have a repository-backed change set available.",
    }


def serialize_dev_task_change_summary(
    task: DevTask,
    *,
    execution_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = resolve_dev_task_change_set(task, execution_payload=execution_payload, include_diff=False)
    return {
        "available": payload["available"],
        "status": payload["status"],
        "has_changes": payload["has_changes"],
        "source": payload["source"],
        "repository_slug": payload["repository_slug"],
        "changed_file_count": payload["changed_file_count"],
        "files": payload["files"],
        "patch_available": payload["patch_available"],
        "patch_artifact_name": payload["patch_artifact_name"],
        "patch_artifact_url": payload["patch_artifact_url"],
        "message": payload["message"],
    }
