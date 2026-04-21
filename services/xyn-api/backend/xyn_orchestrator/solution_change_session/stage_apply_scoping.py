import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from django.utils.text import slugify

from ..models import Artifact, SolutionChangeSession


def solution_change_stage_work_item_seed(*, session: SolutionChangeSession, artifact: Artifact, sequence: int) -> str:
    base = slugify(f"solution-{session.id}-{artifact.slug or artifact.id}")[:72]
    token = base or f"solution-change-{str(artifact.id).replace('-', '')[:12]}"
    return f"{token}-{sequence}"


def solution_change_stage_repo_work_item_seed(*, session: SolutionChangeSession, repo_slug: str, sequence: int) -> str:
    base = slugify(f"solution-{session.id}-{repo_slug}")[:72]
    token = base or f"solution-change-{str(session.id).replace('-', '')[:12]}"
    return f"{token}-{sequence}"


def solution_change_stage_artifact_plan_steps(
    *,
    artifact_id: str,
    session: SolutionChangeSession,
    plan: Dict[str, Any],
    planned_work_by_artifact: Dict[str, List[str]],
) -> List[str]:
    planned = [str(item).strip() for item in (planned_work_by_artifact.get(artifact_id) or []) if str(item).strip()]
    if planned:
        return planned
    proposed_work = [
        str(item).strip()
        for item in (plan.get("proposed_work") if isinstance(plan.get("proposed_work"), list) else [])
        if str(item).strip()
    ]
    if proposed_work:
        return proposed_work
    implementation_steps = [
        str(item).strip()
        for item in (plan.get("implementation_steps") if isinstance(plan.get("implementation_steps"), list) else [])
        if str(item).strip()
    ]
    if implementation_steps:
        return implementation_steps[:4]
    objective = str(session.request_text or "").strip()
    if objective:
        return [f"Implement requested change: {objective}"]
    return ["Implement the approved solution change for this artifact."]


def resolve_stage_apply_target_branch(
    *,
    repo_slug: str,
    fallback_branch: str,
    resolve_local_repo_root: Callable[[str], Path | None],
    session: SolutionChangeSession | None = None,
) -> Tuple[str, str, str]:
    token = str(repo_slug or "").strip()
    fallback = str(fallback_branch or "").strip() or "develop"
    if not token:
        return "", "unresolved", "missing_repo_slug"
    repo_root = resolve_local_repo_root(token)
    if repo_root is None:
        return "", "unresolved", f"unable to resolve local runtime repo root for {token}"

    safe_directory = str(repo_root).strip()

    def _git_stdout(args: List[str]) -> str:
        try:
            proc = subprocess.run(
                ["git", "-c", f"safe.directory={safe_directory}", *args],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
        except Exception:
            return ""
        if int(proc.returncode or 0) != 0:
            return ""
        return str(proc.stdout or "").strip()

    branch = _git_stdout(["-C", str(repo_root), "branch", "--show-current"])
    if branch and branch != "HEAD":
        if session is None:
            return branch, "runtime_repo_checkout", ""
        return _ensure_session_isolated_branch(
            repo_root=repo_root,
            safe_directory=safe_directory,
            repo_slug=token,
            session=session,
            fallback_branch=fallback,
            current_branch=branch,
        )
    branch = _git_stdout(["-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"])
    if branch and branch != "HEAD":
        if session is None:
            return branch, "runtime_repo_checkout", ""
        return _ensure_session_isolated_branch(
            repo_root=repo_root,
            safe_directory=safe_directory,
            repo_slug=token,
            session=session,
            fallback_branch=fallback,
            current_branch=branch,
        )
    if session is None:
        return "", "runtime_repo_checkout", (
            f"unable to determine checked out branch for {token} at {repo_root}; "
            f"fallback branch '{fallback}' was not used for safety"
        )
    return _ensure_session_isolated_branch(
        repo_root=repo_root,
        safe_directory=safe_directory,
        repo_slug=token,
        session=session,
        fallback_branch=fallback,
        current_branch="",
    )


def _session_isolated_branch_name(*, session: SolutionChangeSession, repo_slug: str) -> str:
    repo_token = slugify(str(repo_slug or "").strip())[:24] or "repo"
    session_token = str(session.id).replace("-", "")[:12] or "session"
    return f"xyn/session/{repo_token}-{session_token}"[:80]


def _ensure_session_isolated_branch(
    *,
    repo_root: Path,
    safe_directory: str,
    repo_slug: str,
    session: SolutionChangeSession,
    fallback_branch: str,
    current_branch: str,
) -> Tuple[str, str, str]:
    branch_name = _session_isolated_branch_name(session=session, repo_slug=repo_slug)
    normalized_current_branch = str(current_branch or "").strip()
    base_branch = normalized_current_branch or str(fallback_branch or "").strip() or "develop"

    def _git(args: List[str], timeout_seconds: int = 10) -> Tuple[int, str, str]:
        try:
            proc = subprocess.run(
                ["git", "-c", f"safe.directory={safe_directory}", "-C", str(repo_root), *args],
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout_seconds,
            )
        except Exception as exc:  # pragma: no cover - defensive
            return 1, "", str(exc)
        return int(proc.returncode or 0), str(proc.stdout or "").strip(), str(proc.stderr or "").strip()

    exists_code, _exists_out, _exists_err = _git(["rev-parse", "--verify", "--quiet", branch_name])
    if exists_code != 0:
        create_code, _create_out, create_err = _git(["branch", branch_name, base_branch])
        if create_code != 0:
            return "", "session_isolated_branch", (
                f"failed to allocate isolated branch '{branch_name}' from '{base_branch}' for repo '{repo_slug}': "
                f"{create_err or 'git branch failed'}"
            )
    if normalized_current_branch != branch_name:
        checkout_code, _checkout_out, checkout_err = _git(["checkout", branch_name], timeout_seconds=20)
        if checkout_code != 0:
            return "", "session_isolated_branch", (
                f"failed to check out isolated branch '{branch_name}' for repo '{repo_slug}': "
                f"{checkout_err or 'git checkout failed'}"
            )
    return branch_name, "session_isolated_branch", ""


def solution_change_commit_message(session: SolutionChangeSession) -> str:
    request_text = str(session.request_text or "").strip()
    title = str(session.title or "").strip()
    summary = title or request_text or "Apply validated solution change"
    summary = re.sub(r"\s+", " ", summary).strip()
    if len(summary) > 120:
        summary = summary[:117].rstrip() + "..."
    return f"Xyn session {session.id}: {summary}"


def solution_change_commit_repo_scopes(
    session: SolutionChangeSession,
    *,
    solution_change_session_selected_artifact_ids: Callable[[SolutionChangeSession], List[str]],
    resolve_artifact_ownership: Callable[[Artifact], Dict[str, Any]],
) -> Dict[str, List[str]]:
    selected_ids = set(solution_change_session_selected_artifact_ids(session))
    if not selected_ids:
        staged = session.staged_changes_json if isinstance(session.staged_changes_json, dict) else {}
        selected_ids = {str(item).strip() for item in (staged.get("selected_artifact_ids") or []) if str(item).strip()}
    if not selected_ids:
        return {}
    artifacts = list(Artifact.objects.filter(id__in=selected_ids))
    repo_scopes: Dict[str, List[str]] = {}
    for artifact in artifacts:
        ownership = resolve_artifact_ownership(artifact)
        if str(ownership.get("edit_mode") or "").strip().lower() != "repo_backed":
            continue
        repo_slug = str(ownership.get("repo_slug") or "").strip()
        allowed_paths = [str(item).strip() for item in (ownership.get("allowed_paths") or []) if str(item).strip()]
        if not repo_slug or not allowed_paths:
            continue
        existing = repo_scopes.setdefault(repo_slug, [])
        for path in allowed_paths:
            if path not in existing:
                existing.append(path)
    return repo_scopes
