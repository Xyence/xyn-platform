from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from .development_targets import DevelopmentTargetResolution, resolve_development_target
from .models import DevTask


EXECUTION_BRIEF_SCHEMA_VERSION = "v1"


@dataclass(frozen=True)
class ExecutionBriefResolution:
    brief: Dict[str, Any]
    target: DevelopmentTargetResolution
    source_kind: str
    structured: bool


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_list(values: Iterable[Any]) -> List[str]:
    cleaned: List[str] = []
    for value in values:
        text = _clean_text(value)
        if text:
            cleaned.append(text)
    return cleaned


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
) -> Dict[str, Any]:
    # Keep the brief intentionally small and durable. It is a bounded handoff,
    # not a second planning language.
    return {
        "schema_version": EXECUTION_BRIEF_SCHEMA_VERSION,
        "summary": _clean_text(summary),
        "objective": _clean_text(objective),
        "implementation_intent": _clean_text(implementation_intent),
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
        return brief
    return None


def _brief_from_work_item(work_item: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(work_item, dict):
        return None
    brief = work_item.get("execution_brief")
    if isinstance(brief, dict) and _clean_text(brief.get("summary")):
        return brief
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
    )


def resolve_execution_brief(task: DevTask, *, work_item: Optional[Dict[str, Any]] = None) -> ExecutionBriefResolution:
    target = resolve_development_target(task=task, work_item=work_item)
    brief = _brief_from_task(task)
    source_kind = "task_execution_brief"
    structured = True
    if brief is None:
        brief = _brief_from_work_item(work_item)
        source_kind = "work_item_execution_brief"
    if brief is None:
        brief = _fallback_execution_brief(task, work_item=work_item, target=target)
        source_kind = "fallback"
        structured = False
    resolved = dict(brief)
    resolved["target"] = {
        **(resolved.get("target") if isinstance(resolved.get("target"), dict) else {}),
        "repository_slug": _clean_text(target.repository_slug) or None,
        "branch": _clean_text(target.branch) or None,
        "source_kind": _clean_text(target.source_kind) or None,
        "application_id": _clean_text(target.application_id) or None,
        "application_plan_id": _clean_text(target.application_plan_id) or None,
        "goal_id": _clean_text(target.goal_id) or None,
        "unresolved_reason": _clean_text(target.unresolved_reason) or None,
    }
    return ExecutionBriefResolution(
        brief=resolved,
        target=target,
        source_kind=source_kind,
        structured=structured,
    )

