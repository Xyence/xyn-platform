from __future__ import annotations

import hashlib
import uuid
from typing import Any

from django.db import transaction

from xyn_orchestrator import models


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize_handle(value: Any) -> str:
    token = str(value or "").strip().lower()
    return "".join(ch for ch in token if ch.isalnum())


def _signal_key(*, event: models.PlatformDomainEvent, watch_match: models.WatchMatchEvent | None) -> str:
    if watch_match is not None:
        return f"watch_match:{watch_match.id}"
    if str(event.signal_set_version or "").strip():
        return f"signal_set:{event.signal_set_version}"
    return f"domain_event:{event.id}"


def _coerce_uuid(value: Any) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    try:
        return str(uuid.UUID(token))
    except (ValueError, TypeError, AttributeError):
        return ""


class SignalReadProjectionService:
    """Projects canonical signal domain events into stable read-model rows."""

    @transaction.atomic
    def project_domain_event(self, *, event: models.PlatformDomainEvent) -> models.SignalReadModel | None:
        event_type = str(event.event_type or "").strip().lower()
        if event_type != "signal.watch_match_detected":
            return None
        if event.workspace_id is None:
            return None

        payload = _as_dict(event.payload_json)
        subject = _as_dict(event.subject_ref_json)
        metadata = _as_dict(event.metadata_json)
        event_ref = _as_dict(payload.get("event_ref"))
        watch_match_id = str(subject.get("id") or payload.get("watch_match_event_id") or "").strip()
        watch_match = (
            models.WatchMatchEvent.objects.select_related("watch", "watch__linked_campaign")
            .filter(workspace_id=event.workspace_id, id=watch_match_id)
            .first()
            if watch_match_id
            else None
        )
        watch = watch_match.watch if watch_match is not None else None
        campaign = watch.linked_campaign if watch is not None and watch.linked_campaign_id else None

        parcel_id = _coerce_uuid(event_ref.get("parcel_id"))
        parcel = (
            models.ParcelCanonicalIdentity.objects.filter(workspace_id=event.workspace_id, id=parcel_id).first()
            if parcel_id
            else None
        )
        handle_normalized = _normalize_handle(event_ref.get("handle") or "")

        signal_key = _signal_key(event=event, watch_match=watch_match)
        idempotency_key = hashlib.sha256(f"signal-projection:{event.id}".encode("utf-8")).hexdigest()
        title = str(payload.get("title") or "").strip() or (
            f"Watch match: {str(watch.key or watch.id) if watch is not None else 'signal'}"
        )
        summary = str(payload.get("reason") or payload.get("summary") or "").strip() or "Watch match detected from reconciled state."
        severity = str(payload.get("severity") or metadata.get("severity") or "info").strip().lower() or "info"
        if severity not in {"info", "low", "medium", "high", "critical"}:
            severity = "info"

        row_defaults = {
            "workspace_id": event.workspace_id,
            "watch_match_event": watch_match,
            "watch": watch,
            "campaign": campaign,
            "parcel_identity": parcel,
            "parcel_handle_normalized": handle_normalized,
            "signal_key": signal_key,
            "signal_type": event_type,
            "status": "active",
            "severity": severity,
            "title": title[:240],
            "summary": summary,
            "event_key": str(payload.get("event_key") or (watch_match.event_key if watch_match else "") or "").strip(),
            "source_key": str(event.scope_source or event_ref.get("source") or "").strip(),
            "scope_jurisdiction": str(event.scope_jurisdiction or event_ref.get("jurisdiction") or "").strip(),
            "reconciled_state_version": str(event.reconciled_state_version or "").strip(),
            "signal_set_version": str(event.signal_set_version or "").strip(),
            "occurred_at": event.created_at,
            "payload_json": payload,
            "metadata_json": {
                "projection_source": "platform_domain_event",
                "domain_event_id": str(event.id),
                "watch_match_event_id": str(watch_match.id) if watch_match is not None else "",
            },
            "idempotency_key": idempotency_key,
        }

        existing = models.SignalReadModel.objects.select_for_update().filter(workspace_id=event.workspace_id, domain_event=event).first()
        if existing is None:
            existing = models.SignalReadModel.objects.filter(
                workspace_id=event.workspace_id,
                signal_key=signal_key,
            ).first()
        if existing is None:
            return models.SignalReadModel.objects.create(domain_event=event, **row_defaults)

        for field, value in row_defaults.items():
            setattr(existing, field, value)
        existing.domain_event = event
        existing.save(
            update_fields=[
                "domain_event",
                "watch_match_event",
                "watch",
                "campaign",
                "parcel_identity",
                "parcel_handle_normalized",
                "signal_key",
                "signal_type",
                "status",
                "severity",
                "title",
                "summary",
                "event_key",
                "source_key",
                "scope_jurisdiction",
                "reconciled_state_version",
                "signal_set_version",
                "occurred_at",
                "payload_json",
                "metadata_json",
                "idempotency_key",
                "last_observed_at",
            ]
        )
        return existing

    def project_workspace_events(
        self,
        *,
        workspace_id: str,
        limit: int = 500,
        since_event_id: str = "",
    ) -> list[models.SignalReadModel]:
        qs = models.PlatformDomainEvent.objects.filter(
            workspace_id=workspace_id,
            event_type="signal.watch_match_detected",
        ).order_by("-created_at", "-id")
        if since_event_id:
            qs = qs.exclude(id=since_event_id)
        rows = list(qs[: max(1, min(5000, int(limit or 500)))])
        projected: list[models.SignalReadModel] = []
        for event in rows:
            row = self.project_domain_event(event=event)
            if row is not None:
                projected.append(row)
        return projected


def serialize_signal_read(row: models.SignalReadModel) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "workspace_id": str(row.workspace_id),
        "domain_event_id": str(row.domain_event_id) if row.domain_event_id else None,
        "watch_match_event_id": str(row.watch_match_event_id) if row.watch_match_event_id else None,
        "watch_id": str(row.watch_id) if row.watch_id else None,
        "campaign_id": str(row.campaign_id) if row.campaign_id else None,
        "parcel_identity_id": str(row.parcel_identity_id) if row.parcel_identity_id else None,
        "parcel_handle_normalized": str(row.parcel_handle_normalized or ""),
        "signal_key": str(row.signal_key or ""),
        "signal_type": str(row.signal_type or ""),
        "status": str(row.status or ""),
        "severity": str(row.severity or ""),
        "title": str(row.title or ""),
        "summary": str(row.summary or ""),
        "event_key": str(row.event_key or ""),
        "source_key": str(row.source_key or ""),
        "scope_jurisdiction": str(row.scope_jurisdiction or ""),
        "reconciled_state_version": str(row.reconciled_state_version or ""),
        "signal_set_version": str(row.signal_set_version or ""),
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
        "payload": _as_dict(row.payload_json),
        "metadata": _as_dict(row.metadata_json),
        "first_observed_at": row.first_observed_at.isoformat() if row.first_observed_at else None,
        "last_observed_at": row.last_observed_at.isoformat() if row.last_observed_at else None,
    }
