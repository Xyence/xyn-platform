from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from django.utils import timezone

from .development_targets import DevelopmentTargetResolution, resolve_development_target
from .models import DevTask


EXECUTION_BRIEF_SCHEMA_VERSION = "v1"
EXECUTION_BRIEF_REVIEW_STATES = {"draft", "ready", "approved", "rejected", "superseded"}
EXECUTION_BRIEF_READY_STATES = {"ready", "approved"}
EXECUTION_BRIEF_TERMINAL_BLOCK_STATES = {"rejected", "superseded"}
EXECUTION_BRIEF_TRANSITIONS = {
    "draft": {"draft", "ready", "approved", "rejected", "superseded"},
    "ready": {"ready", "draft", "approved", "rejected", "superseded"},
    "approved": {"approved", "superseded", "rejected"},
    "rejected": {"rejected", "draft", "ready", "approved", "superseded"},
    "superseded": {"superseded"},
}


@dataclass(frozen=True)
class ExecutionBriefResolution:
    brief: Dict[str, Any]
    target: DevelopmentTargetResolution
    source_kind: str
    structured: bool
    revision: int
    history: List[Dict[str, Any]]


@dataclass(frozen=True)
class ExecutionBriefReadiness:
    executable: bool
    gated: bool
    structured_brief: bool
    review_state: str
    reason: Optional[str]
    message: str


def execution_brief_available_actions(task: DevTask) -> List[str]:
    brief = task.execution_brief if isinstance(task.execution_brief, dict) else {}
    if not brief:
        return []
    state = normalize_execution_brief_review_state(getattr(task, "execution_brief_review_state", "draft"))
    if state == "draft":
        return ["mark_ready", "approve", "reject", "regenerate"]
    if state == "ready":
        return ["approve", "reject", "regenerate"]
    if state == "approved":
        return ["reject", "regenerate"]
    if state == "rejected":
        return ["mark_ready", "approve", "regenerate"]
    return []


def serialize_execution_brief_review(task: DevTask, *, work_item: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    resolution = resolve_execution_brief(task, work_item=work_item)
    readiness = execution_brief_readiness(task, work_item=work_item)
    brief = resolution.brief if isinstance(resolution.brief, dict) else {}
    target = brief.get("target") if isinstance(brief.get("target"), dict) else {}
    return {
        "has_brief": readiness.structured_brief,
        "review_state": readiness.review_state,
        "revision": resolution.revision,
        "history_count": len(resolution.history),
        "summary": _clean_text(brief.get("summary")) or None,
        "objective": _clean_text(brief.get("objective")) or None,
        "target_repository_slug": _clean_text(target.get("repository_slug")) or None,
        "target_branch": _clean_text(target.get("branch")) or None,
        "gated": readiness.gated,
        "ready": readiness.executable,
        "blocked": not readiness.executable,
        "blocked_reason": readiness.reason,
        "blocked_message": readiness.message,
        "review_notes": _clean_text(getattr(task, "execution_brief_review_notes", "")) or None,
        "available_actions": execution_brief_available_actions(task),
    }


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_list(values: Iterable[Any]) -> List[str]:
    cleaned: List[str] = []
    for value in values:
        text = _clean_text(value)
        if text:
            cleaned.append(text)
    return cleaned


def _history_rows(task: DevTask) -> List[Dict[str, Any]]:
    rows = task.execution_brief_history if isinstance(task.execution_brief_history, list) else []
    return [row for row in rows if isinstance(row, dict)]


def _next_brief_revision(task: DevTask) -> int:
    current = task.execution_brief if isinstance(task.execution_brief, dict) else {}
    current_revision = current.get("revision")
    try:
        current_revision_int = int(current_revision)
    except (TypeError, ValueError):
        current_revision_int = 1 if current else 0
    history_max = 0
    for row in _history_rows(task):
        try:
            history_max = max(history_max, int(row.get("revision") or 0))
        except (TypeError, ValueError):
            continue
    return max(current_revision_int, history_max) + 1 if max(current_revision_int, history_max) > 0 else 1


def normalize_execution_brief_review_state(value: Any) -> str:
    state = _clean_text(value).lower() or "draft"
    return state if state in EXECUTION_BRIEF_REVIEW_STATES else "draft"


def valid_execution_brief_review_transition(current_state: Any, next_state: Any) -> bool:
    current = normalize_execution_brief_review_state(current_state)
    nxt = normalize_execution_brief_review_state(next_state)
    return nxt in EXECUTION_BRIEF_TRANSITIONS.get(current, {"draft"})


def build_execution_brief(
    *,
    summary: str,
    objective: str = "",
    implementation_intent: str = "",
    target: Optional[DevelopmentTargetResolution] = None,
    allowed_areas: Optional[Iterable[Any]] = None,
    allowed_files: Optional[Iterable[Any]] = None,
    acceptance_criteria: Optional[Iterable[Any]] = None,
    validation_commands: Optional[Iterable[Any]] = None,
    boundaries: Optional[Iterable[Any]] = None,
    source_context: Optional[Dict[str, Any]] = None,
    revision: int = 1,
    revision_reason: str = "initial",
    supersedes_revision: Optional[int] = None,
) -> Dict[str, Any]:
    return {
        "schema_version": EXECUTION_BRIEF_SCHEMA_VERSION,
        "summary": _clean_text(summary),
        "objective": _clean_text(objective),
        "implementation_intent": _clean_text(implementation_intent),
        "revision": int(revision or 1),
        "revision_reason": _clean_text(revision_reason) or "initial",
        "supersedes_revision": int(supersedes_revision) if supersedes_revision else None,
        "target": {
            "repository_slug": _clean_text(getattr(target, "repository_slug", None)) or None,
            "branch": _clean_text(getattr(target, "branch", None)) or None,
            "source_kind": _clean_text(getattr(target, "source_kind", None)) or None,
            "application_id": _clean_text(getattr(target, "application_id", None)) or None,
            "application_plan_id": _clean_text(getattr(target, "application_plan_id", None)) or None,
            "goal_id": _clean_text(getattr(target, "goal_id", None)) or None,
            "unresolved_reason": _clean_text(getattr(target, "unresolved_reason", None)) or None,
        },
        "scope": {
            "allowed_areas": _clean_list(allowed_areas or []),
            "allowed_files": _clean_list(allowed_files or []),
        },
        "validation": {
            "acceptance_criteria": _clean_list(acceptance_criteria or []),
            "commands": _clean_list(validation_commands or []),
        },
        "boundaries": _clean_list(boundaries or []),
        "source_context": source_context if isinstance(source_context, dict) else {},
    }


def _brief_from_task(task: DevTask) -> Optional[Dict[str, Any]]:
    brief = task.execution_brief
    if isinstance(brief, dict) and _clean_text(brief.get("summary")):
        return dict(brief)
    return None


def _brief_from_work_item(work_item: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(work_item, dict):
        return None
    brief = work_item.get("execution_brief")
    if isinstance(brief, dict) and _clean_text(brief.get("summary")):
        return dict(brief)
    return None


def _validation_commands_from_work_item(work_item: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(work_item, dict):
        return []
    verify_rows = work_item.get("verify") if isinstance(work_item.get("verify"), list) else []
    commands: List[str] = []
    for row in verify_rows:
        if not isinstance(row, dict):
            continue
        command = _clean_text(row.get("command"))
        if command:
            commands.append(command)
    return commands


def _acceptance_from_work_item(work_item: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(work_item, dict):
        return []
    acceptance = work_item.get("acceptance_criteria") if isinstance(work_item.get("acceptance_criteria"), list) else []
    return _clean_list(acceptance)


def _fallback_execution_brief(task: DevTask, *, work_item: Optional[Dict[str, Any]], target: DevelopmentTargetResolution) -> Dict[str, Any]:
    title = _clean_text(task.title or (work_item or {}).get("title") or task.work_item_id or f"Dev task {task.id}")
    description = _clean_text((work_item or {}).get("description") or (work_item or {}).get("summary") or task.description)
    revision = _next_brief_revision(task) if task.execution_brief else 1
    return build_execution_brief(
        summary=title,
        objective=description,
        implementation_intent=description or title,
        target=target,
        acceptance_criteria=_acceptance_from_work_item(work_item),
        validation_commands=_validation_commands_from_work_item(work_item),
        boundaries=[
            "Keep changes scoped to the requested work item.",
            "Escalate rather than broadening the change beyond the stated objective.",
        ],
        source_context={
            "dev_task_id": str(task.id),
            "work_item_id": _clean_text(task.work_item_id or (work_item or {}).get("id")) or None,
            "goal_id": _clean_text(getattr(task, "goal_id", None)) or None,
            "source_entity_type": _clean_text(task.source_entity_type) or None,
            "source_entity_id": _clean_text(task.source_entity_id) or None,
        },
        revision=revision,
        revision_reason="fallback",
        supersedes_revision=((task.execution_brief or {}).get("revision") if isinstance(task.execution_brief, dict) else None),
    )


def resolve_execution_brief(task: DevTask, *, work_item: Optional[Dict[str, Any]] = None) -> ExecutionBriefResolution:
    target = resolve_development_target(task=task, work_item=work_item)
    brief = _brief_from_task(task)
    source_kind = "task_execution_brief"
    structured = True
    history = _history_rows(task)
    if brief is None:
        brief = _brief_from_work_item(work_item)
        source_kind = "work_item_execution_brief"
    if brief is None:
        brief = _fallback_execution_brief(task, work_item=work_item, target=target)
        source_kind = "fallback"
        structured = False
    resolved = dict(brief)
    revision = resolved.get("revision")
    try:
        revision_int = int(revision)
    except (TypeError, ValueError):
        revision_int = len(history) + 1 if structured else 0
    resolved["revision"] = revision_int
    resolved_target = resolved.get("target") if isinstance(resolved.get("target"), dict) else {}
    resolved["target"] = {
        **resolved_target,
        "repository_slug": _clean_text(target.repository_slug) or _clean_text(resolved_target.get("repository_slug")) or None,
        "branch": _clean_text(target.branch) or _clean_text(resolved_target.get("branch")) or None,
        "source_kind": _clean_text(target.source_kind) or _clean_text(resolved_target.get("source_kind")) or None,
        "application_id": _clean_text(target.application_id) or _clean_text(resolved_target.get("application_id")) or None,
        "application_plan_id": _clean_text(target.application_plan_id) or _clean_text(resolved_target.get("application_plan_id")) or None,
        "goal_id": _clean_text(target.goal_id) or _clean_text(resolved_target.get("goal_id")) or None,
        "unresolved_reason": _clean_text(target.unresolved_reason) or _clean_text(resolved_target.get("unresolved_reason")) or None,
    }
    return ExecutionBriefResolution(
        brief=resolved,
        target=target,
        source_kind=source_kind,
        structured=structured,
        revision=revision_int,
        history=history,
    )


def execution_brief_gating_enabled(task: DevTask) -> bool:
    policy = task.execution_policy if isinstance(task.execution_policy, dict) else {}
    return bool(policy.get("require_brief_approval"))


def execution_brief_readiness(task: DevTask, *, work_item: Optional[Dict[str, Any]] = None) -> ExecutionBriefReadiness:
    resolution = resolve_execution_brief(task, work_item=work_item)
    structured = resolution.structured and isinstance(task.execution_brief, dict) and bool(task.execution_brief)
    state = normalize_execution_brief_review_state(getattr(task, "execution_brief_review_state", "draft"))
    gated = execution_brief_gating_enabled(task) and structured
    if structured and state in EXECUTION_BRIEF_TERMINAL_BLOCK_STATES:
        return ExecutionBriefReadiness(
            executable=False,
            gated=gated,
            structured_brief=True,
            review_state=state,
            reason=f"brief_{state}",
            message=f"Execution brief is {state} and cannot be executed.",
        )
    if gated and state not in EXECUTION_BRIEF_READY_STATES:
        return ExecutionBriefReadiness(
            executable=False,
            gated=True,
            structured_brief=True,
            review_state=state,
            reason="brief_not_ready",
            message="Execution brief review is required before coding execution can proceed.",
        )
    return ExecutionBriefReadiness(
        executable=True,
        gated=gated,
        structured_brief=structured,
        review_state=state,
        reason=None,
        message="Execution brief is ready for execution." if structured else "Execution can proceed without a structured brief gate.",
    )


def ensure_execution_brief_ready(task: DevTask, *, work_item: Optional[Dict[str, Any]] = None) -> ExecutionBriefReadiness:
    readiness = execution_brief_readiness(task, work_item=work_item)
    if not readiness.executable:
        raise ValueError(readiness.message)
    return readiness


def replace_execution_brief(
    task: DevTask,
    *,
    brief: Dict[str, Any],
    replaced_by=None,
    replacement_reason: str = "revised",
    review_notes: str = "",
) -> Dict[str, Any]:
    history = _history_rows(task)
    current = task.execution_brief if isinstance(task.execution_brief, dict) else None
    current_state = normalize_execution_brief_review_state(task.execution_brief_review_state)
    current_revision = None
    if isinstance(current, dict):
        try:
            current_revision = int(current.get("revision") or 0) or None
        except (TypeError, ValueError):
            current_revision = None
    next_revision = _next_brief_revision(task)
    if current:
        history.append(
            {
                "revision": current_revision or max(next_revision - 1, 1),
                "brief": current,
                "review_state": current_state,
                "review_notes": task.execution_brief_review_notes or "",
                "reviewed_at": task.execution_brief_reviewed_at.isoformat() if task.execution_brief_reviewed_at else None,
                "reviewed_by": str(task.execution_brief_reviewed_by_id) if task.execution_brief_reviewed_by_id else None,
                "superseded_at": timezone.now().isoformat(),
                "superseded_by": str(getattr(replaced_by, "id", "") or "") or None,
                "replacement_reason": _clean_text(replacement_reason) or "revised",
            }
        )
    updated = dict(brief)
    updated["schema_version"] = EXECUTION_BRIEF_SCHEMA_VERSION
    updated["revision"] = next_revision
    updated["revision_reason"] = _clean_text(replacement_reason) or "revised"
    updated["supersedes_revision"] = current_revision
    task.execution_brief = updated
    task.execution_brief_history = history
    task.execution_brief_review_state = "draft"
    task.execution_brief_review_notes = _clean_text(review_notes)
    task.execution_brief_reviewed_at = None
    task.execution_brief_reviewed_by = None
    if replaced_by is not None:
        task.updated_by = replaced_by
    task.save(
        update_fields=[
            "execution_brief",
            "execution_brief_history",
            "execution_brief_review_state",
            "execution_brief_review_notes",
            "execution_brief_reviewed_at",
            "execution_brief_reviewed_by",
            "updated_by",
            "updated_at",
        ]
    )
    return updated


def regenerate_execution_brief(
    task: DevTask,
    *,
    work_item: Optional[Dict[str, Any]] = None,
    regenerated_by=None,
    regeneration_reason: str = "regenerated",
    review_notes: str = "",
) -> Dict[str, Any]:
    resolution = resolve_execution_brief(task, work_item=work_item)
    current = resolution.brief if isinstance(resolution.brief, dict) else {}
    scope = current.get("scope") if isinstance(current.get("scope"), dict) else {}
    validation = current.get("validation") if isinstance(current.get("validation"), dict) else {}
    source_context = current.get("source_context") if isinstance(current.get("source_context"), dict) else {}
    objective = (
        _clean_text((work_item or {}).get("description") if isinstance(work_item, dict) else "")
        or _clean_text((work_item or {}).get("summary") if isinstance(work_item, dict) else "")
        or _clean_text(current.get("objective"))
        or _clean_text(task.description)
        or _clean_text(task.title)
    )
    implementation_intent = (
        _clean_text((work_item or {}).get("description") if isinstance(work_item, dict) else "")
        or _clean_text(current.get("implementation_intent"))
        or objective
    )
    replacement_notes = _clean_text(review_notes or task.execution_brief_review_notes)
    regenerated = build_execution_brief(
        summary=_clean_text((work_item or {}).get("title") if isinstance(work_item, dict) else "") or _clean_text(current.get("summary")) or _clean_text(task.title),
        objective=objective,
        implementation_intent=implementation_intent,
        target=resolution.target,
        allowed_areas=scope.get("allowed_areas") if isinstance(scope.get("allowed_areas"), list) else [],
        allowed_files=scope.get("allowed_files") if isinstance(scope.get("allowed_files"), list) else [],
        acceptance_criteria=_acceptance_from_work_item(work_item) or (validation.get("acceptance_criteria") if isinstance(validation.get("acceptance_criteria"), list) else []),
        validation_commands=_validation_commands_from_work_item(work_item) or (validation.get("commands") if isinstance(validation.get("commands"), list) else []),
        boundaries=current.get("boundaries") if isinstance(current.get("boundaries"), list) else [],
        source_context={
            **source_context,
            "regenerated_from_review_notes": replacement_notes or None,
            "regenerated_from_revision": current.get("revision"),
        },
    )
    return replace_execution_brief(
        task,
        brief=regenerated,
        replaced_by=regenerated_by,
        replacement_reason=regeneration_reason,
        review_notes=review_notes,
    )
