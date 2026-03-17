from typing import Optional

from .draft_lifecycle import COMPLETED, DRAFT, DraftLifecycle, EXECUTING, FAILED, PLAN_READY, QUEUED, SUBMITTED


def summarize_draft_lifecycle(
    *,
    draft_id: str,
    plan_available: bool,
    draft_status: Optional[str] = None,
    thread_id: Optional[str] = None,
    run_id: Optional[str] = None,
    run_status: Optional[str] = None,
) -> DraftLifecycle:
    normalized_draft_status = str(draft_status or "").strip().lower()
    normalized_run_status = str(run_status or "").strip().lower()

    state = DRAFT
    if plan_available:
        state = PLAN_READY
    if thread_id or normalized_draft_status == "submitted":
        state = SUBMITTED

    if normalized_run_status in {"queued", "pending"}:
        state = QUEUED
    elif normalized_run_status in {"running", "in_progress"}:
        state = EXECUTING
    elif normalized_run_status in {"completed", "succeeded"}:
        state = COMPLETED
    elif normalized_run_status == "failed":
        state = FAILED

    return DraftLifecycle(
        draft_id=str(draft_id or "").strip(),
        state=state,
        plan_available=bool(plan_available),
        thread_id=str(thread_id or "").strip() or None,
        active_run_id=str(run_id or "").strip() or None,
        last_run_status=normalized_run_status or None,
    )
