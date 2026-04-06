from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from django.utils import timezone

from .development_targets import resolve_development_target
from .execution_changes import resolve_dev_task_change_set
from .managed_repositories import managed_repository_clone_url, resolve_managed_repository
from .models import DevTask, ManagedRepository


PUBLISH_REMOTE_NAME = "xyn-publish"


class ExecutionPublishError(RuntimeError):
    pass


def task_publish_branch(task: DevTask) -> str:
    return f"xyn/task/{task.id}"


def task_publish_commit_message(task: DevTask) -> str:
    brief = task.execution_brief if isinstance(task.execution_brief, dict) else {}
    summary = str(brief.get("summary") or task.title or "Publish changes").strip()
    summary = " ".join(summary.split())
    if len(summary) > 72:
        summary = summary[:69].rstrip() + "..."
    return f"Xyn task {task.id}: {summary}"


def _publish_metadata(task: DevTask) -> Dict[str, Any]:
    policy = task.execution_policy if isinstance(task.execution_policy, dict) else {}
    publish = policy.get("publish")
    return publish if isinstance(publish, dict) else {}


def _set_publish_metadata(
    task: DevTask,
    *,
    status: str,
    branch: Optional[str],
    commit: Optional[str],
    push_status: Optional[str],
    message: str,
    repository_slug: Optional[str],
    changed_files: Optional[List[str]] = None,
    published_at: Optional[str] = None,
    pushed_at: Optional[str] = None,
    last_error: Optional[str] = None,
) -> Dict[str, Any]:
    policy = dict(task.execution_policy or {}) if isinstance(task.execution_policy, dict) else {}
    previous = _publish_metadata(task)
    metadata = {
        "status": status,
        "branch": branch,
        "commit": commit,
        "push_status": push_status,
        "message": message,
        "repository_slug": repository_slug,
        "changed_files": changed_files if isinstance(changed_files, list) else previous.get("changed_files") or [],
        "published_at": published_at or previous.get("published_at"),
        "pushed_at": pushed_at or previous.get("pushed_at"),
        "last_error": last_error,
    }
    policy["publish"] = metadata
    task.execution_policy = policy
    return metadata


def _run_git(args: List[str], *, cwd: Path, input_text: Optional[str] = None) -> str:
    proc = subprocess.run(
        args,
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
        input=input_text,
    )
    if proc.returncode != 0:
        raise ExecutionPublishError((proc.stderr or proc.stdout or "git command failed").strip())
    return proc.stdout.strip()


def _git_output(args: List[str], *, cwd: Path) -> str:
    try:
        return _run_git(args, cwd=cwd)
    except ExecutionPublishError:
        return ""


def _workspace_repo(task: DevTask) -> tuple[Path, ManagedRepository, str]:
    resolution = resolve_development_target(task=task)
    repo_slug = str(resolution.repository_slug or task.target_repo or "").strip()
    if not repo_slug:
        raise ExecutionPublishError("repository target is not available for publish")
    repository = resolution.repository
    if repository is None:
        repository = resolve_managed_repository(repo_slug)
    change_set = resolve_dev_task_change_set(task, include_diff=False)
    workspace_path = str(change_set.get("workspace_path") or "").strip()
    if not workspace_path:
        raise ExecutionPublishError("managed repository workspace is not available for publish")
    repo_dir = Path(workspace_path)
    if not (repo_dir / ".git").exists():
        raise ExecutionPublishError("managed repository workspace is not available for publish")
    return repo_dir, repository, repo_slug


def _ensure_git_identity(repo_dir: Path) -> None:
    name = _git_output(["git", "config", "--get", "user.name"], cwd=repo_dir)
    email = _git_output(["git", "config", "--get", "user.email"], cwd=repo_dir)
    if not name:
        _run_git(["git", "config", "user.name", "xyn-codegen"], cwd=repo_dir)
    if not email:
        _run_git(["git", "config", "user.email", "codegen@xyn.local"], cwd=repo_dir)


def _current_branch(repo_dir: Path) -> str:
    return _git_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir)


def _local_branch_exists(repo_dir: Path, branch: str) -> bool:
    return bool(_git_output(["git", "show-ref", "--verify", f"refs/heads/{branch}"], cwd=repo_dir))


def _checkout_publish_branch(repo_dir: Path, branch: str, *, allow_create: bool) -> None:
    current_branch = _current_branch(repo_dir)
    if current_branch == branch:
        return
    if _local_branch_exists(repo_dir, branch):
        _run_git(["git", "checkout", branch], cwd=repo_dir)
        return
    if allow_create:
        _run_git(["git", "checkout", "-B", branch], cwd=repo_dir)
        return
    raise ExecutionPublishError(f"publish branch '{branch}' is not available locally")


def _ensure_publish_remote(repo_dir: Path, repository: ManagedRepository) -> None:
    remote_url = managed_repository_clone_url(repository)
    current = _git_output(["git", "remote", "get-url", PUBLISH_REMOTE_NAME], cwd=repo_dir)
    if current:
        if current != remote_url:
            _run_git(["git", "remote", "set-url", PUBLISH_REMOTE_NAME, remote_url], cwd=repo_dir)
        return
    _run_git(["git", "remote", "add", PUBLISH_REMOTE_NAME, remote_url], cwd=repo_dir)


def _has_workspace_changes(repo_dir: Path) -> bool:
    return bool(_git_output(["git", "status", "--porcelain"], cwd=repo_dir))


def _changed_files_for_commit(repo_dir: Path, commit_sha: Optional[str]) -> List[str]:
    token = str(commit_sha or "").strip()
    if not token:
        return []
    output = _git_output(["git", "show", "--pretty=format:", "--name-only", token], cwd=repo_dir)
    if not output:
        return []
    seen: set[str] = set()
    files: List[str] = []
    for line in output.splitlines():
        path = str(line or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        files.append(path)
    return files


def publish_dev_task(task: DevTask, *, user, push: bool = False) -> Dict[str, Any]:
    repo_dir, repository, repo_slug = _workspace_repo(task)
    branch = task_publish_branch(task)
    metadata = _publish_metadata(task)
    has_changes = _has_workspace_changes(repo_dir)
    commit_sha = str(metadata.get("commit") or "").strip() or None
    changed_files = metadata.get("changed_files") if isinstance(metadata.get("changed_files"), list) else []
    published_at: Optional[str] = None

    if has_changes:
        _checkout_publish_branch(repo_dir, branch, allow_create=True)
        _ensure_git_identity(repo_dir)
        _run_git(["git", "add", "-A"], cwd=repo_dir)
        if not _has_workspace_changes(repo_dir):
            has_changes = False
        else:
            _run_git(["git", "commit", "-m", task_publish_commit_message(task)], cwd=repo_dir)
            commit_sha = _git_output(["git", "rev-parse", "HEAD"], cwd=repo_dir) or None
            changed_files = _changed_files_for_commit(repo_dir, commit_sha)
            published_at = timezone.now().isoformat()

    if push:
        if not commit_sha and not _local_branch_exists(repo_dir, branch) and _current_branch(repo_dir) != branch:
            raise ExecutionPublishError("no committed task branch is available to push")
        _checkout_publish_branch(repo_dir, branch, allow_create=bool(commit_sha))
        _ensure_publish_remote(repo_dir, repository)
        try:
            _run_git(["git", "push", "-u", PUBLISH_REMOTE_NAME, branch], cwd=repo_dir)
        except ExecutionPublishError as exc:
            _set_publish_metadata(
                task,
                status="push_failed",
                branch=branch,
                commit=commit_sha,
                push_status="failed",
                message="Failed to push the task branch.",
                repository_slug=repo_slug,
                changed_files=changed_files,
                published_at=published_at,
                last_error=str(exc),
            )
            task.updated_by = user
            task.save(update_fields=["execution_policy", "updated_by", "updated_at"])
            raise
        pushed_at = timezone.now().isoformat()
        metadata = _set_publish_metadata(
            task,
            status="pushed",
            branch=branch,
            commit=commit_sha,
            push_status="pushed",
            message="Committed changes and pushed the task branch.",
            repository_slug=repo_slug,
            changed_files=changed_files,
            published_at=published_at,
            pushed_at=pushed_at,
        )
        task.updated_by = user
        task.save(update_fields=["execution_policy", "updated_by", "updated_at"])
        return metadata

    if has_changes:
        metadata = _set_publish_metadata(
            task,
            status="committed",
            branch=branch,
            commit=commit_sha,
            push_status="not_pushed",
            message="Committed workspace changes to the task branch.",
            repository_slug=repo_slug,
            changed_files=changed_files,
            published_at=published_at,
        )
    else:
        metadata = _set_publish_metadata(
            task,
            status="no_changes",
            branch=branch if commit_sha or _local_branch_exists(repo_dir, branch) or _current_branch(repo_dir) == branch else None,
            commit=commit_sha,
            push_status=str(metadata.get("push_status") or "").strip() or None,
            message="No changes to publish from the managed workspace.",
            repository_slug=repo_slug,
            changed_files=changed_files,
            last_error=None,
        )
    task.updated_by = user
    task.save(update_fields=["execution_policy", "updated_by", "updated_at"])
    return metadata


def serialize_dev_task_publish_state(task: DevTask, *, change_set: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    metadata = _publish_metadata(task)
    resolution = resolve_development_target(task=task)
    repo_slug = str(metadata.get("repository_slug") or resolution.repository_slug or task.target_repo or "").strip() or None
    branch = str(metadata.get("branch") or "").strip() or (task_publish_branch(task) if repo_slug else None)
    commit = str(metadata.get("commit") or "").strip() or None
    push_status = str(metadata.get("push_status") or "").strip() or None
    status = str(metadata.get("status") or "").strip() or "idle"
    message = str(metadata.get("message") or "").strip()
    if not message:
        message = "No publish action has been recorded yet."
    change_summary = change_set if isinstance(change_set, dict) else resolve_dev_task_change_set(task, include_diff=False)
    available_actions: List[str] = []
    if change_summary.get("source") == "workspace" and change_summary.get("has_changes"):
        available_actions.extend(["commit", "commit_and_push"])
    elif commit and push_status != "pushed":
        available_actions.append("push")
    return {
        "status": status,
        "repository_slug": repo_slug,
        "branch": branch,
        "commit": commit,
        "push_status": push_status,
        "published_at": metadata.get("published_at"),
        "pushed_at": metadata.get("pushed_at"),
        "last_error": metadata.get("last_error"),
        "message": message,
        "changed_files": metadata.get("changed_files") if isinstance(metadata.get("changed_files"), list) else [],
        "available_actions": available_actions,
    }
