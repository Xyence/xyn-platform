import re
import subprocess
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from django.utils import timezone
from django.utils.text import slugify

from ..development_targets import DevelopmentTargetResolution
from ..execution_briefs import build_execution_brief
from ..models import (
    ApplicationArtifactMembership,
    Artifact,
    DevTask,
    ManagedRepository,
    SolutionChangeSession,
    SolutionPlanningCheckpoint,
)


def solution_change_stage_work_item_seed(*, session: SolutionChangeSession, artifact: Artifact, sequence: int) -> str:
    base = slugify(f"solution-{session.id}-{artifact.slug or artifact.id}")[:72]
    token = base or f"solution-change-{str(artifact.id).replace('-', '')[:12]}"
    return f"{token}-{sequence}"


def solution_change_stage_repo_work_item_seed(*, session: SolutionChangeSession, repo_slug: str, sequence: int) -> str:
    base = slugify(f"solution-{session.id}-{repo_slug}")[:72]
    token = base or f"solution-change-{str(session.id).replace('-', '')[:12]}"
    return f"{token}-{sequence}"


def resolve_stage_apply_target_branch(
    *,
    repo_slug: str,
    fallback_branch: str,
    resolve_local_repo_root: Callable[[str], Path | None],
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
        return branch, "runtime_repo_checkout", ""
    branch = _git_stdout(["-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"])
    if branch and branch != "HEAD":
        return branch, "runtime_repo_checkout", ""
    return "", "runtime_repo_checkout", (
        f"unable to determine checked out branch for {token} at {repo_root}; "
        f"fallback branch '{fallback}' was not used for safety"
    )


def git_repo_command(
    *,
    repo_root: Path,
    args: List[str],
    timeout_seconds: int = 20,
) -> Tuple[int, str, str]:
    safe_directory = str(repo_root).strip()
    cmd = ["git", "-c", f"safe.directory={safe_directory}", "-C", str(repo_root), *args]
    try:
        proc = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = str(exc.stdout or "").strip()
        stderr = str(exc.stderr or "").strip()
        return 124, stdout, stderr or f"command timed out after {timeout_seconds}s"
    except Exception as exc:  # pragma: no cover - defensive
        return 1, "", str(exc)
    return int(proc.returncode or 0), str(proc.stdout or "").strip(), str(proc.stderr or "").strip()


def git_changed_files_for_paths(
    *,
    repo_root: Path,
    pathspecs: List[str],
    git_repo_command_fn: Callable[..., Tuple[int, str, str]],
) -> List[str]:
    scoped = [str(item).strip() for item in pathspecs if str(item).strip()]
    if not scoped:
        return []
    commands = [
        ["diff", "--name-only", "--", *scoped],
        ["diff", "--cached", "--name-only", "--", *scoped],
        ["ls-files", "--others", "--exclude-standard", "--", *scoped],
    ]
    changed: List[str] = []
    seen_keys: set[str] = set()
    for args in commands:
        code, out, _err = git_repo_command_fn(repo_root=repo_root, args=args)
        if code != 0:
            continue
        for line in (out or "").splitlines():
            token = str(line or "").strip()
            if not token:
                continue
            normalized_display = str(token).replace("\\", "/").strip()
            normalized_key = normalized_display.lower()
            if normalized_display and normalized_key not in seen_keys:
                seen_keys.add(normalized_key)
                changed.append(normalized_display)
    return changed


def git_repo_dirty_files(
    repo_root: Path,
    *,
    git_repo_command_fn: Callable[..., Tuple[int, str, str]],
    normalized_repo_path: Callable[[str], str],
) -> Tuple[List[str], str]:
    code, out, err = git_repo_command_fn(repo_root=repo_root, args=["status", "--porcelain"])
    if code != 0:
        return [], err or "git status failed"
    dirty_files: List[str] = []
    for line in (out or "").splitlines():
        token = str(line or "").strip()
        if not token:
            continue
        path_token = token[3:].strip() if len(token) > 3 else token
        if "->" in path_token:
            path_token = path_token.split("->", 1)[1].strip()
        normalized = normalized_repo_path(path_token)
        if normalized and normalized not in dirty_files:
            dirty_files.append(normalized)
    return dirty_files, ""


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


def stage_solution_change_dispatch_dev_tasks(
    *,
    session: SolutionChangeSession,
    selected_members: List[ApplicationArtifactMembership],
    staged_artifacts: List[Dict[str, Any]],
    planned_work_by_artifact: Dict[str, List[str]],
    plan: Dict[str, Any],
    dispatch_user,
    resolve_artifact_ownership: Callable[[Artifact], Dict[str, Any]],
    artifact_slug: Callable[[Artifact], str],
    solution_change_stage_artifact_plan_steps: Callable[..., List[str]],
    resolve_stage_apply_target_branch: Callable[..., Tuple[str, str, str]],
    resolve_local_repo_root: Callable[[str], Path | None],
    git_repo_dirty_files: Callable[..., Tuple[List[str], str]],
    solution_change_stage_repo_work_item_seed: Callable[..., str],
    submit_dev_task_runtime_run: Callable[..., Dict[str, Any]],
) -> Dict[str, Any]:
    staged_artifacts_by_id = {
        str(row.get("artifact_id") or "").strip(): row
        for row in staged_artifacts
        if isinstance(row, dict) and str(row.get("artifact_id") or "").strip()
    }
    dispatch_results: List[Dict[str, Any]] = []
    per_repo_results: List[Dict[str, Any]] = []
    if dispatch_user is None:
        return {"execution_runs": dispatch_results, "per_repo_results": per_repo_results}

    repo_groups: Dict[str, Dict[str, Any]] = {}
    for index, member in enumerate(selected_members, start=1):
        artifact = member.artifact
        artifact_id = str(artifact.id)
        ownership = resolve_artifact_ownership(artifact)
        repo_slug = str(ownership.get("repo_slug") or "").strip()
        allowed_paths = [str(item).strip() for item in (ownership.get("allowed_paths") or []) if str(item).strip()]
        edit_mode = str(ownership.get("edit_mode") or "").strip().lower()
        staged_row = staged_artifacts_by_id.get(artifact_id)
        if edit_mode != "repo_backed" or not repo_slug or not allowed_paths:
            if isinstance(staged_row, dict):
                staged_row["apply_state"] = "skipped"
            dispatch_results.append(
                {
                    "artifact_id": artifact_id,
                    "artifact_slug": str(artifact_slug(artifact) or ""),
                    "status": "skipped",
                    "reason": "artifact_not_repo_backed_or_not_editable",
                    "owner_repo_slug": repo_slug,
                    "allowed_paths": allowed_paths,
                }
            )
            continue
        implementation_steps = solution_change_stage_artifact_plan_steps(
            artifact_id=artifact_id,
            session=session,
            plan=plan,
            planned_work_by_artifact=planned_work_by_artifact,
        )
        group = repo_groups.setdefault(
            repo_slug,
            {
                "repo_slug": repo_slug,
                "artifacts": [],
                "allowed_paths": [],
                "sequence": index,
            },
        )
        artifact_entry = {
            "artifact_id": artifact_id,
            "artifact": artifact,
            "artifact_slug": str(artifact_slug(artifact) or ""),
            "artifact_title": str(getattr(artifact, "title", "") or ""),
            "allowed_paths": allowed_paths,
            "implementation_steps": implementation_steps,
            "staged_row": staged_row,
        }
        group["artifacts"].append(artifact_entry)
        existing_paths = group["allowed_paths"]
        for path in allowed_paths:
            if path not in existing_paths:
                existing_paths.append(path)

    for repo_slug, group in repo_groups.items():
        artifacts_for_repo = group.get("artifacts") if isinstance(group.get("artifacts"), list) else []
        allowed_paths = [str(item).strip() for item in (group.get("allowed_paths") or []) if str(item).strip()]
        targeted_artifacts = [
            {
                "artifact_id": str(item.get("artifact_id") or ""),
                "artifact_slug": str(item.get("artifact_slug") or ""),
                "artifact_title": str(item.get("artifact_title") or ""),
            }
            for item in artifacts_for_repo
            if isinstance(item, dict)
        ]
        managed_repo = ManagedRepository.objects.filter(slug=repo_slug, is_active=True).first()
        default_branch = str(getattr(managed_repo, "default_branch", "") or "develop").strip() or "develop"
        branch, branch_source, branch_error = resolve_stage_apply_target_branch(
            repo_slug=repo_slug,
            fallback_branch=default_branch,
        )
        if not branch:
            for item in artifacts_for_repo:
                if not isinstance(item, dict):
                    continue
                staged_row = item.get("staged_row") if isinstance(item.get("staged_row"), dict) else None
                if isinstance(staged_row, dict):
                    staged_row["apply_state"] = "failed"
                    staged_row["apply_error"] = branch_error or "target branch could not be resolved"
                    staged_row["branch_source"] = branch_source
                dispatch_results.append(
                    {
                        "artifact_id": str(item.get("artifact_id") or ""),
                        "artifact_slug": str(item.get("artifact_slug") or ""),
                        "status": "failed",
                        "reason": "target_branch_unresolved",
                        "error": branch_error or "target branch could not be resolved",
                        "owner_repo_slug": repo_slug,
                        "target_branch": "",
                        "default_branch": default_branch,
                        "branch_source": branch_source,
                        "allowed_paths": [str(p).strip() for p in (item.get("allowed_paths") or []) if str(p).strip()],
                    }
                )
            per_repo_results.append(
                {
                    "repo_slug": repo_slug,
                    "status": "failed",
                    "blocked_reason": "target_branch_unresolved",
                    "failure_reason": branch_error or "target branch could not be resolved",
                    "target_branch": "",
                    "default_branch": default_branch,
                    "branch_source": branch_source,
                    "targeted_artifacts": targeted_artifacts,
                    "applied_files": [],
                    "skipped_artifacts": [],
                    "preview_can_proceed": False,
                    "next_allowed_actions": ["stage_apply"],
                }
            )
            continue
        repo_root = resolve_local_repo_root(repo_slug)
        if repo_root is None:
            failure_reason = f"unable to resolve local runtime repo root for {repo_slug}"
            for item in artifacts_for_repo:
                if not isinstance(item, dict):
                    continue
                staged_row = item.get("staged_row") if isinstance(item.get("staged_row"), dict) else None
                if isinstance(staged_row, dict):
                    staged_row["apply_state"] = "failed"
                    staged_row["apply_error"] = failure_reason
                dispatch_results.append(
                    {
                        "artifact_id": str(item.get("artifact_id") or ""),
                        "artifact_slug": str(item.get("artifact_slug") or ""),
                        "status": "failed",
                        "reason": "repo_root_unresolved",
                        "error": failure_reason,
                        "owner_repo_slug": repo_slug,
                        "target_branch": branch,
                        "default_branch": default_branch,
                        "branch_source": branch_source,
                        "allowed_paths": [str(p).strip() for p in (item.get("allowed_paths") or []) if str(p).strip()],
                    }
                )
            per_repo_results.append(
                {
                    "repo_slug": repo_slug,
                    "status": "failed",
                    "blocked_reason": "repo_root_unresolved",
                    "failure_reason": failure_reason,
                    "target_branch": branch,
                    "default_branch": default_branch,
                    "branch_source": branch_source,
                    "targeted_artifacts": targeted_artifacts,
                    "applied_files": [],
                    "skipped_artifacts": [],
                    "preview_can_proceed": False,
                    "next_allowed_actions": ["stage_apply"],
                }
            )
            continue
        dirty_files, dirty_error = git_repo_dirty_files(repo_root)
        if dirty_error:
            for item in artifacts_for_repo:
                if not isinstance(item, dict):
                    continue
                staged_row = item.get("staged_row") if isinstance(item.get("staged_row"), dict) else None
                if isinstance(staged_row, dict):
                    staged_row["apply_state"] = "failed"
                    staged_row["apply_error"] = dirty_error
                dispatch_results.append(
                    {
                        "artifact_id": str(item.get("artifact_id") or ""),
                        "artifact_slug": str(item.get("artifact_slug") or ""),
                        "status": "failed",
                        "reason": "repo_status_check_failed",
                        "error": dirty_error,
                        "owner_repo_slug": repo_slug,
                        "target_branch": branch,
                        "default_branch": default_branch,
                        "branch_source": branch_source,
                        "allowed_paths": [str(p).strip() for p in (item.get("allowed_paths") or []) if str(p).strip()],
                    }
                )
            per_repo_results.append(
                {
                    "repo_slug": repo_slug,
                    "status": "failed",
                    "blocked_reason": "repo_status_check_failed",
                    "failure_reason": dirty_error,
                    "target_branch": branch,
                    "default_branch": default_branch,
                    "branch_source": branch_source,
                    "targeted_artifacts": targeted_artifacts,
                    "applied_files": [],
                    "skipped_artifacts": [],
                    "preview_can_proceed": False,
                    "next_allowed_actions": ["stage_apply"],
                }
            )
            continue
        if dirty_files:
            failure_reason = (
                f"Repository '{repo_root.name}' has uncommitted changes; refusing stage apply for repo-coordinated baseline safety."
            )
            for item in artifacts_for_repo:
                if not isinstance(item, dict):
                    continue
                staged_row = item.get("staged_row") if isinstance(item.get("staged_row"), dict) else None
                if isinstance(staged_row, dict):
                    staged_row["apply_state"] = "failed"
                    staged_row["apply_error"] = failure_reason
                dispatch_results.append(
                    {
                        "artifact_id": str(item.get("artifact_id") or ""),
                        "artifact_slug": str(item.get("artifact_slug") or ""),
                        "status": "failed",
                        "reason": "unsafe_repository_state",
                        "error": failure_reason,
                        "owner_repo_slug": repo_slug,
                        "target_branch": branch,
                        "default_branch": default_branch,
                        "branch_source": branch_source,
                        "allowed_paths": [str(p).strip() for p in (item.get("allowed_paths") or []) if str(p).strip()],
                    }
                )
            per_repo_results.append(
                {
                    "repo_slug": repo_slug,
                    "status": "blocked",
                    "blocked_reason": "unsafe_repository_state",
                    "failure_reason": failure_reason,
                    "target_branch": branch,
                    "default_branch": default_branch,
                    "branch_source": branch_source,
                    "targeted_artifacts": targeted_artifacts,
                    "applied_files": [],
                    "dirty_files": dirty_files[:50],
                    "skipped_artifacts": [],
                    "preview_can_proceed": False,
                    "next_allowed_actions": ["review_repo_state", "stage_apply"],
                }
            )
            continue
        aggregate_steps: List[str] = []
        for item in artifacts_for_repo:
            if not isinstance(item, dict):
                continue
            for step in (item.get("implementation_steps") or []):
                token = str(step).strip()
                if token and token not in aggregate_steps:
                    aggregate_steps.append(token)
        summary = f"{session.title or 'Apply solution change'} · {repo_slug} coordinated apply"
        objective = str(session.request_text or "").strip()
        brief_target = DevelopmentTargetResolution(
            repository=managed_repo,
            repository_slug=repo_slug,
            branch=branch,
            allowed_paths=tuple(allowed_paths),
            source_kind="artifact_ownership",
            application_id=str(session.application_id),
            application_plan_id=None,
            goal_id=None,
            unresolved_reason=None,
        )
        execution_brief = build_execution_brief(
            summary=summary,
            objective=objective,
            implementation_intent="; ".join(aggregate_steps[:3]),
            target=brief_target,
            allowed_areas=allowed_paths,
            acceptance_criteria=aggregate_steps[:8],
            validation_commands=[],
            boundaries=[
                "Keep changes scoped to the selected artifact ownership paths.",
                "Do not modify files outside allowed artifact ownership boundaries.",
            ],
            source_context={
                "source": "solution_change_session_stage_apply",
                "solution_change_session_id": str(session.id),
                "application_id": str(session.application_id),
                "artifact_ids": [str(item.get("artifact_id") or "") for item in artifacts_for_repo if isinstance(item, dict)],
                "artifact_slugs": [str(item.get("artifact_slug") or "") for item in artifacts_for_repo if isinstance(item, dict)],
            },
            revision=1,
            revision_reason="stage_apply",
        )
        task = DevTask.objects.create(
            title=summary[:240],
            description="\n".join(aggregate_steps[:10]) or "Apply approved solution change in repo-coordinated mode.",
            task_type="codegen",
            status="queued",
            priority=0,
            max_attempts=2,
            source_entity_type="solution_change_session",
            source_entity_id=session.id,
            source_conversation_id="",
            intent_type="solution_change_apply",
            target_repo=repo_slug,
            target_branch=branch,
            execution_brief=execution_brief,
            execution_brief_history=[],
            execution_brief_review_state="ready",
            execution_brief_review_notes="Auto-generated from approved solution change plan stage apply.",
            execution_policy={
                "auto_continue": True,
                "max_retries": 1,
                "require_human_review_on_failure": True,
                "solution_change_session_id": str(session.id),
                "solution_change_session": {"id": str(session.id), "application_id": str(session.application_id)},
                "coordinated_repo_apply": True,
            },
            runtime_workspace_id=session.workspace_id,
            context_purpose="coding",
            work_item_id=solution_change_stage_repo_work_item_seed(
                session=session,
                repo_slug=repo_slug,
                sequence=int(group.get("sequence") or 1),
            ),
            created_by=dispatch_user,
            updated_by=dispatch_user,
        )
        for item in artifacts_for_repo:
            if not isinstance(item, dict):
                continue
            staged_row = item.get("staged_row") if isinstance(item.get("staged_row"), dict) else None
            if isinstance(staged_row, dict):
                staged_row["dev_task_id"] = str(task.id)
        try:
            run_result = submit_dev_task_runtime_run(task, workspace=session.workspace, user=dispatch_user)
            task.refresh_from_db()
            run_id = str(run_result.get("run_id") or "")
            for item in artifacts_for_repo:
                if not isinstance(item, dict):
                    continue
                staged_row = item.get("staged_row") if isinstance(item.get("staged_row"), dict) else None
                if isinstance(staged_row, dict):
                    staged_row["apply_state"] = "queued"
                dispatch_results.append(
                    {
                        "artifact_id": str(item.get("artifact_id") or ""),
                        "artifact_slug": str(item.get("artifact_slug") or ""),
                        "dev_task_id": str(task.id),
                        "work_item_id": str(task.work_item_id or ""),
                        "status": "queued",
                        "run_id": run_id,
                        "owner_repo_slug": repo_slug,
                        "target_branch": branch,
                        "default_branch": default_branch,
                        "branch_source": branch_source,
                        "allowed_paths": [str(p).strip() for p in (item.get("allowed_paths") or []) if str(p).strip()],
                    }
                )
            per_repo_results.append(
                {
                    "repo_slug": repo_slug,
                    "status": "queued",
                    "blocked_reason": "",
                    "failure_reason": "",
                    "target_branch": branch,
                    "default_branch": default_branch,
                    "branch_source": branch_source,
                    "targeted_artifacts": targeted_artifacts,
                    "dev_task_id": str(task.id),
                    "run_id": run_id,
                    "applied_files": [],
                    "skipped_artifacts": [],
                    "preview_can_proceed": True,
                    "next_allowed_actions": ["prepare_preview"],
                }
            )
        except ValueError as exc:
            task.status = "awaiting_review"
            task.last_error = str(exc)
            task.updated_by = dispatch_user
            task.save(update_fields=["status", "last_error", "updated_by", "updated_at"])
            for item in artifacts_for_repo:
                if not isinstance(item, dict):
                    continue
                staged_row = item.get("staged_row") if isinstance(item.get("staged_row"), dict) else None
                if isinstance(staged_row, dict):
                    staged_row["apply_state"] = "failed"
                dispatch_results.append(
                    {
                        "artifact_id": str(item.get("artifact_id") or ""),
                        "artifact_slug": str(item.get("artifact_slug") or ""),
                        "dev_task_id": str(task.id),
                        "work_item_id": str(task.work_item_id or ""),
                        "status": "failed",
                        "reason": "runtime_submission_validation_failed",
                        "error": str(exc),
                        "owner_repo_slug": repo_slug,
                        "target_branch": branch,
                        "default_branch": default_branch,
                        "branch_source": branch_source,
                        "allowed_paths": [str(p).strip() for p in (item.get("allowed_paths") or []) if str(p).strip()],
                    }
                )
            per_repo_results.append(
                {
                    "repo_slug": repo_slug,
                    "status": "failed",
                    "blocked_reason": "runtime_submission_validation_failed",
                    "failure_reason": str(exc),
                    "target_branch": branch,
                    "default_branch": default_branch,
                    "branch_source": branch_source,
                    "targeted_artifacts": targeted_artifacts,
                    "dev_task_id": str(task.id),
                    "applied_files": [],
                    "skipped_artifacts": [],
                    "preview_can_proceed": False,
                    "next_allowed_actions": ["stage_apply"],
                }
            )
        except RuntimeError as exc:
            task.status = "failed"
            task.last_error = str(exc)
            task.updated_by = dispatch_user
            task.save(update_fields=["status", "last_error", "updated_by", "updated_at"])
            for item in artifacts_for_repo:
                if not isinstance(item, dict):
                    continue
                staged_row = item.get("staged_row") if isinstance(item.get("staged_row"), dict) else None
                if isinstance(staged_row, dict):
                    staged_row["apply_state"] = "failed"
                dispatch_results.append(
                    {
                        "artifact_id": str(item.get("artifact_id") or ""),
                        "artifact_slug": str(item.get("artifact_slug") or ""),
                        "dev_task_id": str(task.id),
                        "work_item_id": str(task.work_item_id or ""),
                        "status": "failed",
                        "reason": "runtime_submission_failed",
                        "error": str(exc),
                        "owner_repo_slug": repo_slug,
                        "target_branch": branch,
                        "default_branch": default_branch,
                        "branch_source": branch_source,
                        "allowed_paths": [str(p).strip() for p in (item.get("allowed_paths") or []) if str(p).strip()],
                    }
                )
            per_repo_results.append(
                {
                    "repo_slug": repo_slug,
                    "status": "failed",
                    "blocked_reason": "runtime_submission_failed",
                    "failure_reason": str(exc),
                    "target_branch": branch,
                    "default_branch": default_branch,
                    "branch_source": branch_source,
                    "targeted_artifacts": targeted_artifacts,
                    "dev_task_id": str(task.id),
                    "applied_files": [],
                    "skipped_artifacts": [],
                    "preview_can_proceed": False,
                    "next_allowed_actions": ["stage_apply"],
                }
            )

    return {"execution_runs": dispatch_results, "per_repo_results": per_repo_results}


def stage_solution_change_session(
    *,
    session: SolutionChangeSession,
    memberships: List[ApplicationArtifactMembership],
    dispatch_runtime: bool = False,
    dispatch_user=None,
    solution_change_session_selected_artifact_ids: Callable[[SolutionChangeSession], List[str]],
    solution_change_session_confirmed_workstreams: Callable[[SolutionChangeSession], List[str]],
    artifact_role_matches_workstreams: Callable[[str, List[str]], bool],
    stage_solution_change_dispatch_dev_tasks: Callable[..., Dict[str, Any]],
) -> Dict[str, Any]:
    selected_ids = set(solution_change_session_selected_artifact_ids(session))
    confirmed_workstreams = solution_change_session_confirmed_workstreams(session)
    selected_members = [member for member in memberships if str(member.artifact_id) in selected_ids]
    if not selected_members and confirmed_workstreams:
        selected_members = [member for member in memberships if artifact_role_matches_workstreams(member.role, confirmed_workstreams)]
    if not selected_members:
        selected_members = memberships
    plan = session.plan_json if isinstance(session.plan_json, dict) else {}
    planned_work_by_artifact: Dict[str, List[str]] = {}
    for row in (plan.get("per_artifact_work") if isinstance(plan.get("per_artifact_work"), list) else []):
        if not isinstance(row, dict):
            continue
        artifact_id = str(row.get("artifact_id") or "").strip()
        if not artifact_id:
            continue
        planned_work_by_artifact[artifact_id] = [
            str(item).strip()
            for item in (row.get("planned_work") if isinstance(row.get("planned_work"), list) else [])
            if str(item).strip()
        ]
    staged_artifacts: List[Dict[str, Any]] = []
    for member in selected_members:
        artifact = member.artifact
        artifact_id = str(artifact.id)
        staged_artifacts.append(
            {
                "artifact_id": artifact_id,
                "artifact_title": artifact.title,
                "artifact_type": artifact.type.slug if artifact.type_id else "",
                "role": member.role,
                "state": "staged",
                "apply_state": "proposed",
                "validation_state": "pending",
                "planned_work": planned_work_by_artifact.get(artifact_id) or [],
                "updated_at": timezone.now().isoformat(),
            }
        )
    staged_payload: Dict[str, Any] = {
        "operation_id": str(uuid.uuid4()),
        "staged_at": timezone.now().isoformat(),
        "overall_state": "staged",
        "artifact_count": len(staged_artifacts),
        "artifact_states": staged_artifacts,
        "selected_artifact_ids": [str(member.artifact_id) for member in selected_members],
        "confirmed_workstreams": confirmed_workstreams,
        "shared_contracts": plan.get("shared_contracts") if isinstance(plan.get("shared_contracts"), list) else [],
        "validation_plan": plan.get("validation_plan") if isinstance(plan.get("validation_plan"), list) else [],
        "preview_implications": plan.get("preview_implications") if isinstance(plan.get("preview_implications"), list) else [],
        "planning_checkpoint_state": {
            "pending_count": SolutionPlanningCheckpoint.objects.filter(session=session, status="pending").count(),
            "approved_count": SolutionPlanningCheckpoint.objects.filter(session=session, status="approved").count(),
            "rejected_count": SolutionPlanningCheckpoint.objects.filter(session=session, status="rejected").count(),
        },
    }
    if dispatch_runtime:
        dispatch_payload = stage_solution_change_dispatch_dev_tasks(
            session=session,
            selected_members=selected_members,
            staged_artifacts=staged_artifacts,
            planned_work_by_artifact=planned_work_by_artifact,
            plan=plan,
            dispatch_user=dispatch_user,
        )
        dispatch_results = dispatch_payload.get("execution_runs") if isinstance(dispatch_payload, dict) else []
        per_repo_results = dispatch_payload.get("per_repo_results") if isinstance(dispatch_payload, dict) else []
        queued_count = sum(1 for row in dispatch_results if isinstance(row, dict) and str(row.get("status") or "") == "queued")
        failed_count = sum(1 for row in dispatch_results if isinstance(row, dict) and str(row.get("status") or "") == "failed")
        skipped_count = sum(1 for row in dispatch_results if isinstance(row, dict) and str(row.get("status") or "") == "skipped")
        blocked_repo_count = sum(
            1
            for row in per_repo_results
            if isinstance(row, dict) and str(row.get("status") or "").strip().lower() in {"blocked", "failed"}
        )
        stage_apply_overall_status = (
            "failed"
            if failed_count > 0 or blocked_repo_count > 0
            else "materialization_queued"
            if queued_count > 0
            else "staged_only"
        )
        staged_payload["execution_runs"] = dispatch_results
        staged_payload["per_repo_results"] = per_repo_results if isinstance(per_repo_results, list) else []
        staged_payload["dev_task_ids"] = [
            str(row.get("dev_task_id") or "").strip()
            for row in dispatch_results
            if isinstance(row, dict) and str(row.get("dev_task_id") or "").strip()
        ]
        staged_payload["execution_summary"] = {
            "queued_count": queued_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "blocked_repo_count": blocked_repo_count,
        }
        staged_payload["stage_apply_result"] = {
            "change_session_id": str(session.id),
            "overall_status": stage_apply_overall_status,
            "per_repo_results": per_repo_results if isinstance(per_repo_results, list) else [],
            "skipped_artifacts": [
                {
                    "artifact_id": str(row.get("artifact_id") or ""),
                    "artifact_slug": str(row.get("artifact_slug") or ""),
                    "reason": str(row.get("reason") or "skipped"),
                }
                for row in dispatch_results
                if isinstance(row, dict) and str(row.get("status") or "") == "skipped"
            ],
            "preview_can_proceed": bool(queued_count > 0 and failed_count == 0 and blocked_repo_count == 0),
            "next_allowed_actions": (
                ["prepare_preview"]
                if queued_count > 0 and failed_count == 0 and blocked_repo_count == 0
                else ["review_stage_apply_results", "stage_apply"]
            ),
        }
    session.staged_changes_json = staged_payload
    session.preview_json = {}
    session.validation_json = {}
    session.execution_status = "staged"
    if session.status == "draft":
        session.status = "planned"
    session.save(update_fields=["staged_changes_json", "preview_json", "validation_json", "execution_status", "status", "updated_at"])
    return staged_payload

