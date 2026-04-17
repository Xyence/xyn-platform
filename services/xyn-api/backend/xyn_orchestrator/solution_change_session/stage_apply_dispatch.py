from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from ..development_targets import DevelopmentTargetResolution
from ..execution_briefs import build_execution_brief
from ..models import ApplicationArtifactMembership, DevTask, ManagedRepository, SolutionChangeSession


def stage_solution_change_dispatch_dev_tasks(
    *,
    session: SolutionChangeSession,
    selected_members: List[ApplicationArtifactMembership],
    staged_artifacts: List[Dict[str, Any]],
    planned_work_by_artifact: Dict[str, List[str]],
    plan: Dict[str, Any],
    dispatch_user,
    resolve_artifact_ownership: Callable[[Any], Dict[str, Any]],
    artifact_slug: Callable[[Any], str],
    solution_change_stage_artifact_plan_steps: Callable[..., List[str]],
    resolve_stage_apply_target_branch: Callable[..., Tuple[str, str, str]],
    resolve_local_repo_root: Callable[[str], Path | None],
    git_repo_dirty_files: Callable[..., Tuple[List[str], str]],
    solution_change_stage_repo_work_item_seed: Callable[..., str],
    submit_dev_task_runtime_run: Callable[..., Dict[str, Any]],
    remote_catalog_materialization_by_artifact_id: Dict[str, Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    materialization_map = (
        remote_catalog_materialization_by_artifact_id
        if isinstance(remote_catalog_materialization_by_artifact_id, dict)
        else {}
    )
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
            session=session,
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
                        "isolation_mode": "session_branch" if branch_source == "session_isolated_branch" else "runtime_checkout",
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
                "remote_catalog_materialization": [
                    {
                        "artifact_id": str(item.get("artifact_id") or ""),
                        "artifact_slug": str(item.get("artifact_slug") or ""),
                        "materialization": materialization_map.get(str(item.get("artifact_id") or "")) or {},
                    }
                    for item in artifacts_for_repo
                    if isinstance(item, dict) and str(item.get("artifact_id") or "") in materialization_map
                ],
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
                "remote_catalog_materialization": [
                    {
                        "artifact_id": str(item.get("artifact_id") or ""),
                        "artifact_slug": str(item.get("artifact_slug") or ""),
                        "materialization": materialization_map.get(str(item.get("artifact_id") or "")) or {},
                    }
                    for item in artifacts_for_repo
                    if isinstance(item, dict) and str(item.get("artifact_id") or "") in materialization_map
                ],
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
                    "isolation_mode": "session_branch" if branch_source == "session_isolated_branch" else "runtime_checkout",
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
