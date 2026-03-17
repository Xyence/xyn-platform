from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from .managed_storage import managed_workspace_path, managed_workspace_root
from .models import ManagedRepository


class ManagedRepositoryError(RuntimeError):
    pass


def _safe_repo_slug(value: Any, *, fallback: str = "repository") -> str:
    token = slugify(str(value or "").strip())[:120]
    return token or fallback


def _repo_clone_token() -> str:
    return (
        str(os.environ.get("XYN_CODEGEN_GIT_TOKEN", "")).strip()
        or str(os.environ.get("XYENCE_CODEGEN_GIT_TOKEN", "")).strip()
    )


def _repo_source_slug_from_url(url: str) -> str:
    path = urlparse(url).path or ""
    tail = path.rstrip("/").split("/")[-1] if path else ""
    if tail.endswith(".git"):
        tail = tail[:-4]
    return _safe_repo_slug(tail, fallback="repository")


def _repo_clone_url(repository: ManagedRepository) -> str:
    remote = str(repository.remote_url or "").strip()
    if repository.auth_mode == "https_token":
        token = _repo_clone_token()
        if token and remote.startswith("https://") and "@" not in remote.split("://", 1)[1]:
            return remote.replace("https://", f"https://{token}@")
    return remote


def managed_repository_clone_url(repository: ManagedRepository) -> str:
    return _repo_clone_url(repository)


def repository_cache_root() -> Path:
    root = managed_workspace_path("repositories", "cache")
    root.mkdir(parents=True, exist_ok=True)
    return root


def repository_workspace_path(workspace_root: str | Path, repo_slug: str) -> Path:
    root = Path(workspace_root).resolve()
    managed_root = managed_workspace_root()
    if not str(root).startswith(str(managed_root)):
        raise ManagedRepositoryError("repository workspace root must live under the managed workspace root")
    repo_path = root / "repos" / _safe_repo_slug(repo_slug)
    repo_path.parent.mkdir(parents=True, exist_ok=True)
    return repo_path


def repository_cache_path(repository: ManagedRepository) -> Path:
    return repository_cache_root() / _safe_repo_slug(repository.slug)


def _write_repository_marker(path: Path, *, repository: ManagedRepository, kind: str, extra: Optional[Dict[str, Any]] = None) -> None:
    payload = {
        "kind": kind,
        "repository_slug": repository.slug,
        "remote_url": repository.remote_url,
        "default_branch": repository.default_branch,
        "updated_at": timezone.now().isoformat(),
    }
    if extra:
        payload.update(extra)
    (path / ".xyn-repository.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _run_git(args: list[str], *, cwd: Optional[Path] = None, timeout: Optional[int] = None) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ManagedRepositoryError(f"git command timed out after {timeout or 0}s") from exc
    if proc.returncode != 0:
        detail = proc.stderr or proc.stdout or "git command failed"
        raise ManagedRepositoryError(detail.strip())
    return proc


def validate_managed_repository_registration(
    *,
    remote_url: str,
    default_branch: str = "main",
    auth_mode: str = "",
    verify_remote: bool = True,
) -> Dict[str, Any]:
    remote = str(remote_url or "").strip()
    branch = str(default_branch or "main").strip() or "main"
    normalized_auth = str(auth_mode or "").strip()
    if not remote:
        raise ManagedRepositoryError("repository remote URL is required")
    if normalized_auth not in {"", "local", "https_token"}:
        raise ManagedRepositoryError("repository auth mode must be one of: local, https_token")
    parsed = urlparse(remote)
    is_url = bool(parsed.scheme)
    if is_url and parsed.scheme not in {"https", "ssh", "git", "file"}:
        raise ManagedRepositoryError("repository URL must use https, ssh, git, or file")
    if not is_url:
        candidate = Path(remote).expanduser()
        if not candidate.exists():
            raise ManagedRepositoryError("repository path does not exist")
    if normalized_auth == "https_token":
        if not remote.startswith("https://"):
            raise ManagedRepositoryError("https_token auth requires an https repository URL")
        if not _repo_clone_token():
            raise ManagedRepositoryError(
                "repository uses https_token auth but no XYN_CODEGEN_GIT_TOKEN or XYENCE_CODEGEN_GIT_TOKEN is configured"
            )
    if not verify_remote:
        return {
            "remote_url": remote,
            "branch": branch,
            "auth_mode": normalized_auth or "local",
            "validated": False,
        }
    clone_url = remote if not is_url or parsed.scheme != "https" else _repo_clone_url(
        ManagedRepository(remote_url=remote, auth_mode=normalized_auth)
    )
    try:
        refs = _run_git(["git", "ls-remote", "--heads", clone_url, branch], timeout=8)
    except ManagedRepositoryError as exc:
        raise ManagedRepositoryError(f"unable to access repository remote: {exc}") from exc
    if not refs.stdout.strip():
        raise ManagedRepositoryError(f"repository branch '{branch}' was not found on the remote")
    return {
        "remote_url": remote,
        "branch": branch,
        "auth_mode": normalized_auth or "local",
        "validated": True,
    }


@transaction.atomic
def register_managed_repository(
    *,
    slug: str,
    remote_url: str,
    default_branch: str = "main",
    auth_mode: str = "",
    display_name: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    validate_remote: bool = True,
) -> ManagedRepository:
    validation = validate_managed_repository_registration(
        remote_url=remote_url,
        default_branch=default_branch,
        auth_mode=auth_mode,
        verify_remote=validate_remote,
    )
    normalized_slug = _safe_repo_slug(slug or _repo_source_slug_from_url(remote_url))
    normalized_branch = str(validation["branch"] or "main").strip() or "main"
    normalized_auth = str(validation["auth_mode"] or "").strip()
    defaults = {
        "display_name": str(display_name or slug or normalized_slug).strip(),
        "remote_url": str(validation["remote_url"] or "").strip(),
        "default_branch": normalized_branch,
        "is_active": True,
        "auth_mode": normalized_auth,
        "metadata_json": {**(metadata or {}), "validation": {"validated": bool(validation.get("validated"))}} or None,
    }
    repository, created = ManagedRepository.objects.get_or_create(slug=normalized_slug, defaults=defaults)
    if created:
        return repository
    changed = False
    for field, value in defaults.items():
        if field == "metadata_json":
            if value and repository.metadata_json != value:
                repository.metadata_json = value
                changed = True
            continue
        if getattr(repository, field) != value and value:
            setattr(repository, field, value)
            changed = True
    if not repository.is_active:
        repository.is_active = True
        changed = True
    if changed:
        repository.save(
            update_fields=[
                "display_name",
                "remote_url",
                "default_branch",
                "is_active",
                "auth_mode",
                "metadata_json",
                "updated_at",
            ]
        )
    return repository


def resolve_managed_repository(repo_ref: str) -> ManagedRepository:
    slug = _safe_repo_slug(repo_ref)
    repository = ManagedRepository.objects.filter(slug=slug, is_active=True).first()
    if repository is None:
        raise ManagedRepositoryError(f"repository '{repo_ref}' is not registered")
    return repository


def ensure_registered_repository(repo_target: Dict[str, Any]) -> ManagedRepository:
    if not isinstance(repo_target, dict):
        raise ManagedRepositoryError("repository target payload must be a mapping")
    name = str(repo_target.get("name") or "").strip()
    remote_url = str(repo_target.get("url") or "").strip()
    if name:
        existing = ManagedRepository.objects.filter(slug=_safe_repo_slug(name), is_active=True).first()
        if existing:
            return existing
    if not remote_url:
        raise ManagedRepositoryError("repository target is missing a remote url and no active registration exists")
    return register_managed_repository(
        slug=name or _repo_source_slug_from_url(remote_url),
        remote_url=remote_url,
        default_branch=str(repo_target.get("ref") or "main").strip() or "main",
        auth_mode=str(repo_target.get("auth") or "").strip(),
        display_name=name or _repo_source_slug_from_url(remote_url),
        metadata={"source": "repo_target"},
    )


@dataclass(frozen=True)
class MaterializedRepository:
    repository: ManagedRepository
    cache_path: Path


def ensure_repository_materialized(repo_target: Dict[str, Any] | ManagedRepository | str, *, refresh: bool = True) -> MaterializedRepository:
    if isinstance(repo_target, ManagedRepository):
        repository = repo_target
    elif isinstance(repo_target, str):
        repository = resolve_managed_repository(repo_target)
    else:
        repository = ensure_registered_repository(repo_target)
    if not repository.is_active:
        raise ManagedRepositoryError(f"repository '{repository.slug}' is inactive")
    branch = str(repository.default_branch or "main").strip() or "main"
    cache_path = repository_cache_path(repository)
    clone_url = _repo_clone_url(repository)
    if not (cache_path / ".git").exists():
        shutil.rmtree(cache_path, ignore_errors=True)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        _run_git(["git", "clone", "--branch", branch, clone_url, str(cache_path)])
    elif refresh:
        _run_git(["git", "remote", "set-url", "origin", clone_url], cwd=cache_path)
        _run_git(["git", "fetch", "--prune", "origin"], cwd=cache_path)
        checkout = subprocess.run(
            ["git", "checkout", branch],
            cwd=str(cache_path),
            check=False,
            capture_output=True,
            text=True,
        )
        if checkout.returncode != 0:
            _run_git(["git", "checkout", "-B", branch, f"origin/{branch}"], cwd=cache_path)
        _run_git(["git", "reset", "--hard", f"origin/{branch}"], cwd=cache_path)
        _run_git(["git", "clean", "-fd"], cwd=cache_path)
    repository.local_cache_relpath = str(cache_path.relative_to(managed_workspace_root()))
    repository.last_synced_at = timezone.now()
    repository.save(update_fields=["local_cache_relpath", "last_synced_at", "updated_at"])
    _write_repository_marker(
        cache_path,
        repository=repository,
        kind="cache",
        extra={"relative_path": repository.local_cache_relpath},
    )
    return MaterializedRepository(repository=repository, cache_path=cache_path)


def materialize_repository_workspace(
    repo_target: Dict[str, Any] | ManagedRepository | str,
    *,
    workspace_root: str | Path,
    refresh: bool = True,
    reset: bool = False,
) -> Path:
    materialized = ensure_repository_materialized(repo_target, refresh=refresh)
    branch = str(materialized.repository.default_branch or "main").strip() or "main"
    workspace_path = repository_workspace_path(workspace_root, materialized.repository.slug)
    if reset and workspace_path.exists():
        shutil.rmtree(workspace_path, ignore_errors=True)
    if not (workspace_path / ".git").exists():
        shutil.rmtree(workspace_path, ignore_errors=True)
        _run_git(["git", "clone", "--no-hardlinks", str(materialized.cache_path), str(workspace_path)])
    if refresh:
        _run_git(["git", "fetch", "--prune", "origin"], cwd=workspace_path)
        checkout = subprocess.run(
            ["git", "checkout", branch],
            cwd=str(workspace_path),
            check=False,
            capture_output=True,
            text=True,
        )
        if checkout.returncode != 0:
            _run_git(["git", "checkout", "-B", branch, f"origin/{branch}"], cwd=workspace_path)
        _run_git(["git", "reset", "--hard", f"origin/{branch}"], cwd=workspace_path)
        _run_git(["git", "clean", "-fd"], cwd=workspace_path)
    _write_repository_marker(
        workspace_path,
        repository=materialized.repository,
        kind="workspace",
        extra={"cache_relative_path": materialized.repository.local_cache_relpath},
    )
    return workspace_path
