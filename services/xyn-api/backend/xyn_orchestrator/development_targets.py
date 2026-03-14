from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from .managed_repositories import ManagedRepositoryError, resolve_managed_repository
from .models import Application, ApplicationPlan, DevTask, Goal, ManagedRepository


@dataclass(frozen=True)
class DevelopmentTargetResolution:
    repository: Optional[ManagedRepository]
    repository_slug: Optional[str]
    branch: Optional[str]
    source_kind: str
    application_id: Optional[str]
    application_plan_id: Optional[str]
    goal_id: Optional[str]
    unresolved_reason: Optional[str] = None


def _task_goal(task: DevTask) -> Optional[Goal]:
    goal = getattr(task, "goal", None)
    if goal is not None:
        return goal
    goal_id = getattr(task, "goal_id", None)
    if not goal_id:
        return None
    return Goal.objects.select_related("application", "application__target_repository").filter(id=goal_id).first()


def _goal_application(goal: Goal) -> Optional[Application]:
    application = getattr(goal, "application", None)
    if application is not None:
        return application
    application_id = getattr(goal, "application_id", None)
    if not application_id:
        return None
    return Application.objects.select_related("target_repository").filter(id=application_id).first()


def _resolve_registered_repository(repo_ref: str) -> Optional[ManagedRepository]:
    token = str(repo_ref or "").strip()
    if not token:
        return None
    try:
        return resolve_managed_repository(token)
    except ManagedRepositoryError:
        return None


def _work_item_repo_candidates(work_item: Optional[Dict[str, Any]]) -> list[tuple[str, str, Optional[ManagedRepository]]]:
    if not isinstance(work_item, dict):
        return []
    rows = work_item.get("repo_targets") if isinstance(work_item.get("repo_targets"), list) else []
    candidates: list[tuple[str, str, Optional[ManagedRepository]]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        repo_name = str(row.get("name") or "").strip()
        branch = str(row.get("ref") or "").strip() or "develop"
        if not repo_name:
            continue
        key = (repo_name, branch)
        if key in seen:
            continue
        seen.add(key)
        candidates.append((repo_name, branch, _resolve_registered_repository(repo_name)))
    return candidates


def resolve_development_target(
    *,
    application: Optional[Application] = None,
    application_plan: Optional[ApplicationPlan] = None,
    goal: Optional[Goal] = None,
    task: Optional[DevTask] = None,
    work_item: Optional[Dict[str, Any]] = None,
) -> DevelopmentTargetResolution:
    if task is not None:
        explicit_repo = str(task.target_repo or "").strip()
        explicit_branch = str(task.target_branch or "").strip()
        if explicit_repo:
            repository = _resolve_registered_repository(explicit_repo)
            return DevelopmentTargetResolution(
                repository=repository,
                repository_slug=repository.slug if repository else explicit_repo,
                branch=explicit_branch or (repository.default_branch if repository else None),
                source_kind="task_explicit",
                application_id=str(getattr(_goal_application(_task_goal(task)) if _task_goal(task) else None, "id", "") or "") or None,
                application_plan_id=None,
                goal_id=str(getattr(_task_goal(task), "id", "") or "") or None,
            )
        goal = goal or _task_goal(task)

    if goal is not None:
        application = application or _goal_application(goal)

    if application is not None and application.target_repository_id:
        repository = getattr(application, "target_repository", None) or ManagedRepository.objects.filter(id=application.target_repository_id).first()
        if repository is not None:
            return DevelopmentTargetResolution(
                repository=repository,
                repository_slug=repository.slug,
                branch=repository.default_branch,
                source_kind="application",
                application_id=str(application.id),
                application_plan_id=None,
                goal_id=str(goal.id) if goal is not None else None,
            )

    if application_plan is not None and application_plan.target_repository_id:
        repository = getattr(application_plan, "target_repository", None) or ManagedRepository.objects.filter(id=application_plan.target_repository_id).first()
        if repository is not None:
            return DevelopmentTargetResolution(
                repository=repository,
                repository_slug=repository.slug,
                branch=repository.default_branch,
                source_kind="application_plan",
                application_id=None,
                application_plan_id=str(application_plan.id),
                goal_id=str(goal.id) if goal is not None else None,
            )

    candidates = _work_item_repo_candidates(work_item)
    if len(candidates) == 1:
        repo_name, branch, repository = candidates[0]
        return DevelopmentTargetResolution(
            repository=repository,
            repository_slug=repository.slug if repository else repo_name,
            branch=branch or (repository.default_branch if repository else None),
            source_kind="work_item_repo_target",
            application_id=str(application.id) if application is not None else None,
            application_plan_id=str(application_plan.id) if application_plan is not None else None,
            goal_id=str(goal.id) if goal is not None else None,
        )
    if len(candidates) > 1:
        return DevelopmentTargetResolution(
            repository=None,
            repository_slug=None,
            branch=None,
            source_kind="unresolved",
            application_id=str(application.id) if application is not None else None,
            application_plan_id=str(application_plan.id) if application_plan is not None else None,
            goal_id=str(goal.id) if goal is not None else None,
            unresolved_reason="ambiguous_repo_targets",
        )

    return DevelopmentTargetResolution(
        repository=None,
        repository_slug=None,
        branch=None,
        source_kind="unresolved",
        application_id=str(application.id) if application is not None else None,
        application_plan_id=str(application_plan.id) if application_plan is not None else None,
        goal_id=str(goal.id) if goal is not None else None,
        unresolved_reason="target_missing",
    )


def repo_target_payload_for_resolution(
    resolution: DevelopmentTargetResolution,
    *,
    branch: str = "",
) -> Optional[Dict[str, Any]]:
    repo_slug = str(resolution.repository_slug or "").strip()
    if not repo_slug:
        return None
    repo_branch = str(branch or resolution.branch or "").strip() or "develop"
    if resolution.repository is not None:
        return {
            "name": resolution.repository.slug,
            "url": resolution.repository.remote_url,
            "ref": repo_branch,
            "auth": resolution.repository.auth_mode or "local",
        }
    return {"name": repo_slug, "ref": repo_branch}
