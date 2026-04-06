from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from .managed_repositories import ManagedRepositoryError, resolve_managed_repository
from .models import Application, ApplicationPlan, Artifact, DevTask, Goal, ManagedRepository


@dataclass(frozen=True)
class DevelopmentTargetResolution:
    repository: Optional[ManagedRepository]
    repository_slug: Optional[str]
    branch: Optional[str]
    allowed_paths: tuple[str, ...]
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


def _artifact_ids_from_work_item(work_item: Optional[Dict[str, Any]]) -> set[str]:
    if not isinstance(work_item, dict):
        return set()
    candidate_ids: set[str] = set()
    for key in ("artifact_id",):
        token = str(work_item.get(key) or "").strip()
        if token:
            candidate_ids.add(token)
    for key in ("artifact_ids", "selected_artifact_ids", "related_artifact_ids"):
        values = work_item.get(key)
        if isinstance(values, list):
            for value in values:
                token = str(value or "").strip()
                if token:
                    candidate_ids.add(token)
    artifact_payload = work_item.get("artifact")
    if isinstance(artifact_payload, dict):
        token = str(artifact_payload.get("id") or "").strip()
        if token:
            candidate_ids.add(token)
    per_artifact_work = work_item.get("per_artifact_work")
    if isinstance(per_artifact_work, list):
        for row in per_artifact_work:
            if not isinstance(row, dict):
                continue
            token = str(row.get("artifact_id") or "").strip()
            if token:
                candidate_ids.add(token)
    return candidate_ids


def _artifacts_from_context(
    *,
    application: Optional[Application],
    task: Optional[DevTask],
    work_item: Optional[Dict[str, Any]],
) -> list[Artifact]:
    candidate_ids = _artifact_ids_from_work_item(work_item)
    if task is not None and str(task.source_entity_type or "").strip().lower() == "artifact":
        token = str(task.source_entity_id or "").strip()
        if token:
            candidate_ids.add(token)
    if candidate_ids:
        return list(Artifact.objects.filter(id__in=candidate_ids).order_by("created_at"))
    if application is not None:
        return [
            membership.artifact
            for membership in application.artifact_memberships.select_related("artifact").all().order_by("sort_order", "created_at")
            if membership.artifact is not None
        ]
    return []


def _ownership_resolution_for_artifacts(
    *,
    artifacts: Iterable[Artifact],
    application: Optional[Application],
    application_plan: Optional[ApplicationPlan],
    goal: Optional[Goal],
    task: Optional[DevTask],
) -> DevelopmentTargetResolution:
    artifact_rows = [artifact for artifact in artifacts if artifact is not None]
    if not artifact_rows:
        return DevelopmentTargetResolution(
            repository=None,
            repository_slug=None,
            branch=None,
            allowed_paths=(),
            source_kind="unresolved",
            application_id=str(application.id) if application is not None else None,
            application_plan_id=str(application_plan.id) if application_plan is not None else None,
            goal_id=str(goal.id) if goal is not None else None,
            unresolved_reason="artifact_context_missing",
        )
    repo_by_artifact: dict[str, str] = {}
    unresolved = False
    for artifact in artifact_rows:
        repo_slug = str(getattr(artifact, "owner_repo_slug", "") or "").strip()
        if not repo_slug:
            unresolved = True
            continue
        repo_by_artifact[str(artifact.id)] = repo_slug
    if unresolved or not repo_by_artifact:
        return DevelopmentTargetResolution(
            repository=None,
            repository_slug=None,
            branch=None,
            allowed_paths=(),
            source_kind="unresolved",
            application_id=str(application.id) if application is not None else None,
            application_plan_id=str(application_plan.id) if application_plan is not None else None,
            goal_id=str(goal.id) if goal is not None else None,
            unresolved_reason="artifact_owner_repo_missing",
        )
    repo_slugs = sorted(set(repo_by_artifact.values()))
    if len(repo_slugs) > 1:
        return DevelopmentTargetResolution(
            repository=None,
            repository_slug=None,
            branch=None,
            allowed_paths=(),
            source_kind="unresolved",
            application_id=str(application.id) if application is not None else None,
            application_plan_id=str(application_plan.id) if application_plan is not None else None,
            goal_id=str(goal.id) if goal is not None else None,
            unresolved_reason="multiple_artifact_repositories",
        )
    repo_slug = repo_slugs[0]
    repository = _resolve_registered_repository(repo_slug)
    explicit_repo = str(getattr(task, "target_repo", "") or "").strip()
    if explicit_repo and explicit_repo != repo_slug:
        return DevelopmentTargetResolution(
            repository=None,
            repository_slug=None,
            branch=None,
            allowed_paths=(),
            source_kind="unresolved",
            application_id=str(application.id) if application is not None else None,
            application_plan_id=str(application_plan.id) if application_plan is not None else None,
            goal_id=str(goal.id) if goal is not None else None,
            unresolved_reason="artifact_explicit_repo_mismatch",
        )
    allowed_paths: list[str] = []
    seen_paths: set[str] = set()
    for artifact in artifact_rows:
        prefixes = artifact.owner_path_prefixes_json if isinstance(artifact.owner_path_prefixes_json, list) else []
        for value in prefixes:
            token = str(value or "").strip()
            if not token or token in seen_paths:
                continue
            seen_paths.add(token)
            allowed_paths.append(token)
    branch = str(getattr(task, "target_branch", "") or "").strip() or (repository.default_branch if repository else None)
    return DevelopmentTargetResolution(
        repository=repository,
        repository_slug=repo_slug,
        branch=branch,
        allowed_paths=tuple(allowed_paths),
        source_kind="artifact_ownership",
        application_id=str(application.id) if application is not None else None,
        application_plan_id=str(application_plan.id) if application_plan is not None else None,
        goal_id=str(goal.id) if goal is not None else None,
        unresolved_reason=None,
    )


def resolve_development_target(
    *,
    application: Optional[Application] = None,
    application_plan: Optional[ApplicationPlan] = None,
    goal: Optional[Goal] = None,
    task: Optional[DevTask] = None,
    work_item: Optional[Dict[str, Any]] = None,
) -> DevelopmentTargetResolution:
    if task is not None:
        goal = goal or _task_goal(task)

    if goal is not None:
        application = application or _goal_application(goal)

    artifacts = _artifacts_from_context(application=application, task=task, work_item=work_item)
    return _ownership_resolution_for_artifacts(
        artifacts=artifacts,
        application=application,
        application_plan=application_plan,
        goal=goal,
        task=task,
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
