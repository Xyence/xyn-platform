from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..models import CoordinationThread, DevTask, Run, Workspace
from .workflow_summary import summarize_draft_lifecycle


def _payload_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _plan_available(draft: Dict[str, Any]) -> bool:
    draft_status = _text(draft.get("status")).lower()
    if draft_status in {"ready", "submitted", "archived"}:
        return True
    content = _payload_dict(draft.get("content_json"))
    initial_intent = _payload_dict(content.get("initial_intent"))
    return bool(initial_intent)


def _normalize_job_status(status: Any) -> str:
    token = _text(status).lower()
    if token in {"queued", "pending"}:
        return "queued"
    if token in {"running", "in_progress"}:
        return "running"
    if token in {"completed", "succeeded"}:
        return "completed"
    if token == "failed":
        return "failed"
    return token


def _find_related_jobs(draft_id: str, jobs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    related_ids: set[str] = set()
    normalized_draft_id = _text(draft_id)
    job_rows = [job for job in jobs if isinstance(job, dict)]

    for job in job_rows:
        input_json = _payload_dict(job.get("input_json"))
        if normalized_draft_id and _text(input_json.get("draft_id")) == normalized_draft_id:
            related_ids.add(_text(job.get("id")))

    changed = True
    while changed:
        changed = False
        for job in job_rows:
            if _text(job.get("id")) in related_ids:
                continue
            input_json = _payload_dict(job.get("input_json"))
            if _text(input_json.get("source_job_id")) in related_ids:
                related_ids.add(_text(job.get("id")))
                changed = True

    rows = [job for job in job_rows if _text(job.get("id")) in related_ids]
    rows.sort(key=lambda item: _text(item.get("updated_at")) or _text(item.get("created_at")) or _text(item.get("id")))
    return rows


def _job_payload_values(related_jobs: Iterable[Dict[str, Any]], *keys: str) -> List[str]:
    values: List[str] = []
    for job in related_jobs:
        for payload in (_payload_dict(job.get("input_json")), _payload_dict(job.get("output_json"))):
            for key in keys:
                token = _text(payload.get(key))
                if token:
                    values.append(token)
    return values


def _load_run_by_id(run_id: str) -> Optional[Run]:
    token = _text(run_id)
    if not token:
        return None
    try:
        parsed = uuid.UUID(token)
    except (TypeError, ValueError, AttributeError):
        return None
    return Run.objects.filter(id=parsed).first()


def _resolve_thread_from_jobs(workspace: Workspace, related_jobs: List[Dict[str, Any]]) -> Tuple[Optional[CoordinationThread], Optional[Run], Optional[str], Optional[str], Optional[str]]:
    explicit_thread_id = next(iter(_job_payload_values(related_jobs, "thread_id", "coordination_thread_id")), "")
    explicit_run_id = next(iter(_job_payload_values(related_jobs, "run_id", "runtime_run_id")), "")
    explicit_work_item_id = next(iter(_job_payload_values(related_jobs, "work_item_id")), "")

    thread: Optional[CoordinationThread] = None
    if explicit_thread_id:
        try:
            thread = CoordinationThread.objects.filter(id=explicit_thread_id, workspace=workspace).first()
        except (TypeError, ValueError):
            thread = None

    task: Optional[DevTask] = None
    if thread is None and explicit_work_item_id:
        task = (
            DevTask.objects.select_related("coordination_thread", "result_run", "source_run")
            .filter(coordination_thread__workspace=workspace)
            .filter(work_item_id=explicit_work_item_id)
            .first()
        )
        if task and task.coordination_thread_id:
            thread = task.coordination_thread

    if task is None and thread is not None:
        task = (
            DevTask.objects.select_related("coordination_thread", "result_run", "source_run")
            .filter(coordination_thread=thread)
            .order_by("-updated_at", "-created_at")
            .first()
        )

    run = _load_run_by_id(explicit_run_id)
    if run is None and task is not None:
        if task.result_run_id:
            run = task.result_run
        elif task.source_run_id:
            run = task.source_run
        elif task.runtime_run_id:
            run = _load_run_by_id(str(task.runtime_run_id))
        else:
            run = Run.objects.filter(entity_type="dev_task", entity_id=task.id).order_by("-created_at").first()

    thread_id = str(thread.id) if thread else (explicit_thread_id or None)
    run_id = str(run.id) if run else (explicit_run_id or None)
    run_status = str(run.status) if run else None
    return thread, run, thread_id, run_id, run_status


def get_draft_workflow(*, workspace: Workspace, draft: Dict[str, Any], jobs: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    draft_id = _text(draft.get("id"))
    related_jobs = _find_related_jobs(draft_id, jobs)
    _thread, _run, thread_id, run_id, run_status = _resolve_thread_from_jobs(workspace, related_jobs)
    if not run_status and related_jobs:
        run_status = _normalize_job_status(related_jobs[-1].get("status")) or None

    lifecycle = summarize_draft_lifecycle(
        draft_id=draft_id,
        plan_available=_plan_available(draft),
        draft_status=_text(draft.get("status")),
        thread_id=thread_id,
        run_id=run_id,
        run_status=run_status,
    )
    return asdict(lifecycle)
