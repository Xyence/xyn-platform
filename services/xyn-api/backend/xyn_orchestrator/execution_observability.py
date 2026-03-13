from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from .models import CoordinationEvent, CoordinationThread, DevTask, Workspace
from .xco import work_item_is_blocked


@dataclass(frozen=True)
class ThreadTimelineEntry:
    id: str
    event_type: str
    source: str
    created_at: datetime
    work_item_id: Optional[str] = None
    work_item_title: Optional[str] = None
    run_id: Optional[str] = None
    status: Optional[str] = None
    summary: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None


def _task_lookup(thread: CoordinationThread) -> Callable[[str], Optional[DevTask]]:
    tasks = list(thread.goal.work_items.all()) if thread.goal_id else list(thread.work_items.all())
    task_map = {
        str(task.work_item_id or "").strip(): task
        for task in tasks
        if str(task.work_item_id or "").strip()
    }
    return lambda work_item_id: task_map.get(str(work_item_id or "").strip())


def _append_task_lifecycle_entries(
    entries: List[ThreadTimelineEntry],
    *,
    thread: CoordinationThread,
    task: DevTask,
    runtime_detail: Optional[Dict[str, Any]],
    task_lookup: Callable[[str], Optional[DevTask]],
) -> None:
    work_item_id = str(task.work_item_id or task.id)
    work_item_title = str(task.title or work_item_id)
    status = str(task.status or "").strip().lower()

    entries.append(
        ThreadTimelineEntry(
            id=f"task-queued:{task.id}",
            event_type="work_item_queued",
            source="work_item",
            created_at=task.created_at,
            work_item_id=work_item_id,
            work_item_title=work_item_title,
            status="queued",
            summary=f"{work_item_title} was queued.",
            payload={},
        )
    )

    if runtime_detail:
        run_id = str(runtime_detail.get("run_id") or runtime_detail.get("id") or "").strip() or None
        started_at = runtime_detail.get("started_at")
        if isinstance(started_at, datetime):
            entries.append(
                ThreadTimelineEntry(
                    id=f"task-running:{task.id}",
                    event_type="work_item_running",
                    source="run",
                    created_at=started_at,
                    work_item_id=work_item_id,
                    work_item_title=work_item_title,
                    run_id=run_id,
                    status="running",
                    summary=f"{work_item_title} started running.",
                    payload={},
                )
            )
        completed_at = runtime_detail.get("completed_at")
        runtime_status = str(runtime_detail.get("status") or status).strip().lower()
        if isinstance(completed_at, datetime) and runtime_status in {"completed", "failed", "blocked"}:
            event_type = (
                "work_item_completed"
                if runtime_status == "completed"
                else "work_item_failed"
                if runtime_status == "failed"
                else "work_item_blocked"
            )
            entries.append(
                ThreadTimelineEntry(
                    id=f"task-terminal:{task.id}:{runtime_status}",
                    event_type=event_type,
                    source="run",
                    created_at=completed_at,
                    work_item_id=work_item_id,
                    work_item_title=work_item_title,
                    run_id=run_id,
                    status=runtime_status,
                    summary=str(runtime_detail.get("summary") or f"{work_item_title} {runtime_status}.").strip(),
                    payload={},
                )
            )
            return

    if status in {"completed", "succeeded", "failed", "canceled", "awaiting_review"}:
        event_type = (
            "work_item_completed"
            if status in {"completed", "succeeded"}
            else "work_item_failed"
            if status == "failed"
            else "work_item_canceled"
            if status == "canceled"
            else "work_item_blocked"
        )
        entries.append(
            ThreadTimelineEntry(
                id=f"task-status:{task.id}:{status}",
                event_type=event_type,
                source="work_item",
                created_at=task.updated_at,
                work_item_id=work_item_id,
                work_item_title=work_item_title,
                run_id=str(task.runtime_run_id) if task.runtime_run_id else None,
                status=status,
                summary=f"{work_item_title} is {status.replace('_', ' ')}.",
                payload={},
            )
        )
        return

    if work_item_is_blocked(task, status_lookup=lambda candidate: str(getattr(candidate, "status", "") or ""), task_lookup=task_lookup):
        entries.append(
            ThreadTimelineEntry(
                id=f"task-blocked:{task.id}",
                event_type="work_item_blocked",
                source="work_item",
                created_at=task.updated_at,
                work_item_id=work_item_id,
                work_item_title=work_item_title,
                run_id=str(task.runtime_run_id) if task.runtime_run_id else None,
                status="blocked",
                summary=f"{work_item_title} is blocked.",
                payload={},
            )
        )


def build_thread_timeline(
    thread: CoordinationThread,
    *,
    runtime_detail_lookup: Optional[Callable[[DevTask], Optional[Dict[str, Any]]]] = None,
) -> List[ThreadTimelineEntry]:
    entries: List[ThreadTimelineEntry] = []
    task_lookup = _task_lookup(thread)

    for event in thread.events.all().order_by("created_at", "id"):
        payload = event.payload_json if isinstance(event.payload_json, dict) else {}
        entries.append(
            ThreadTimelineEntry(
                id=str(event.id),
                event_type=str(event.event_type or "").strip(),
                source="coordination_event",
                created_at=event.created_at,
                work_item_id=str(event.work_item.work_item_id or event.work_item_id) if event.work_item_id else None,
                work_item_title=str(event.work_item.title) if event.work_item_id else None,
                run_id=str(event.run_id) if event.run_id else None,
                status=str(payload.get("status") or "").strip() or None,
                summary=str(payload.get("summary") or "").strip() or None,
                payload=payload,
            )
        )

    for task in thread.work_items.all().order_by("created_at", "id"):
        detail = runtime_detail_lookup(task) if callable(runtime_detail_lookup) else None
        _append_task_lifecycle_entries(
            entries,
            thread=thread,
            task=task,
            runtime_detail=detail,
            task_lookup=task_lookup,
        )

    entries.sort(
        key=lambda entry: (
            entry.created_at,
            entry.event_type,
            entry.work_item_id or "",
            entry.run_id or "",
            entry.id,
        )
    )
    return entries


def serialize_thread_timeline(entries: List[ThreadTimelineEntry]) -> List[Dict[str, Any]]:
    return [
        {
            "id": entry.id,
            "event_type": entry.event_type,
            "source": entry.source,
            "work_item_id": entry.work_item_id,
            "work_item_title": entry.work_item_title,
            "run_id": entry.run_id,
            "status": entry.status,
            "summary": entry.summary,
            "payload": entry.payload or {},
            "created_at": entry.created_at,
        }
        for entry in entries
    ]


def build_artifact_evolution(
    *,
    workspace: Workspace,
    current_run_id: str,
    current_artifact_id: str,
    current_artifact: Dict[str, Any],
    runtime_detail_lookup: Callable[[DevTask], Optional[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    artifact_type = str(current_artifact.get("artifact_type") or "").strip()
    label = str(current_artifact.get("label") or "").strip()
    current_work_item_id = str(current_artifact.get("work_item_id") or "").strip()
    current_key = (
        current_work_item_id.lower() if current_work_item_id else "",
        artifact_type.lower(),
        label.lower(),
    )

    rows: List[Dict[str, Any]] = []
    for task in DevTask.objects.filter(runtime_workspace_id=workspace.id).order_by("created_at", "id"):
        detail = runtime_detail_lookup(task)
        if not isinstance(detail, dict):
            continue
        run_id = str(detail.get("id") or detail.get("run_id") or "").strip()
        artifacts = detail.get("artifacts") if isinstance(detail.get("artifacts"), list) else []
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            candidate_type = str(artifact.get("artifact_type") or "").strip()
            candidate_label = str(artifact.get("label") or "").strip()
            candidate_work_item_id = str(task.work_item_id or "").strip()
            candidate_key = (
                candidate_work_item_id.lower() if current_work_item_id else "",
                candidate_type.lower(),
                candidate_label.lower(),
            )
            if candidate_key != current_key:
                continue
            rows.append(
                {
                    "artifact_id": str(artifact.get("id") or ""),
                    "run_id": run_id,
                    "work_item_id": candidate_work_item_id or None,
                    "artifact_type": candidate_type,
                    "label": candidate_label,
                    "uri": str(artifact.get("uri") or ""),
                    "created_at": artifact.get("created_at"),
                    "is_current": str(artifact.get("id") or "") == current_artifact_id and run_id == current_run_id,
                }
            )

    rows.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("run_id") or ""), str(item.get("artifact_id") or "")))
    return rows
