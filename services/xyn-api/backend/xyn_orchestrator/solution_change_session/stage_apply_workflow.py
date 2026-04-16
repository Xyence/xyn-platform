import uuid
from typing import Any, Callable, Dict, List

from django.utils import timezone

from ..models import ApplicationArtifactMembership, SolutionChangeSession, SolutionPlanningCheckpoint
from .stage_apply_dispatch import stage_solution_change_dispatch_dev_tasks
from .stage_apply_git import git_changed_files_for_paths, git_repo_command, git_repo_dirty_files
from .stage_apply_scoping import (
    resolve_stage_apply_target_branch,
    solution_change_commit_message,
    solution_change_commit_repo_scopes,
    solution_change_stage_artifact_plan_steps,
    solution_change_stage_repo_work_item_seed,
    solution_change_stage_work_item_seed,
)


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
