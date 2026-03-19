from __future__ import annotations

import hashlib
from typing import Any

from .interfaces import FailureNotifier


class AppNotificationFailureNotifier(FailureNotifier):
    """Failure notifier adapter backed by AppNotification records.

    TODO: wire recipient resolution from workspace on-call policy and delivery preferences.
    """

    def __init__(self, *, recipient_ids: list[str] | None = None):
        self._recipient_ids = [str(value or "").strip() for value in (recipient_ids or []) if str(value or "").strip()]

    def notify_run_failure(
        self,
        *,
        workspace_id: str,
        run_id: str,
        pipeline_key: str,
        job_key: str,
        error_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self._recipient_ids:
            return
        from xyn_orchestrator.notifications.publisher import publish_application_notification

        normalized_error = str(error_text or "").strip()
        key_material = "|".join(
            [
                str(workspace_id or "").strip(),
                str(run_id or "").strip(),
                str(pipeline_key or "").strip(),
                str(job_key or "").strip(),
                normalized_error[:512],
            ]
        )
        idempotency_key = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
        publish_application_notification(
            source_app="platform.orchestration",
            notification_type="orchestration_job_failed",
            workspace_id=workspace_id,
            recipient_ids=self._recipient_ids,
            title=f"Orchestration job failed: {pipeline_key}.{job_key}",
            body=normalized_error[:4000],
            payload={
                "run_id": run_id,
                "pipeline_key": pipeline_key,
                "job_key": job_key,
                "metadata": metadata or {},
            },
            source_entity_type="orchestration_run",
            source_entity_id=run_id,
            request_delivery=True,
            idempotency_key=idempotency_key,
        )
