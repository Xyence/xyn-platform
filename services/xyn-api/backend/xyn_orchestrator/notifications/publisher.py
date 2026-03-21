from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

from xyn_orchestrator.models import UserIdentity, Workspace

from .delivery import enqueue_notification_email_delivery
from .service import create_app_notification


@dataclass(frozen=True)
class PublishApplicationNotificationResult:
    notification_id: str
    recipient_ids: List[str]
    delivery: Optional[Dict[str, int]]


def _normalize_identity_ids(identity_ids: Iterable[Any]) -> List[str]:
    ordered: List[str] = []
    seen = set()
    for value in identity_ids:
        resolved = str(value or "").strip()
        if not resolved or resolved in seen:
            continue
        seen.add(resolved)
        ordered.append(resolved)
    return ordered


def _resolve_recipients(recipient_ids: Sequence[str]) -> List[UserIdentity]:
    normalized_uuid_ids: List[str] = []
    for recipient_id in recipient_ids:
        try:
            normalized_uuid_ids.append(str(uuid.UUID(recipient_id)))
        except (TypeError, ValueError):
            raise ValueError(f"invalid recipient id: {recipient_id}") from None

    rows = list(UserIdentity.objects.filter(id__in=normalized_uuid_ids).order_by("created_at"))
    by_id = {str(row.id): row for row in rows}
    missing = [recipient_id for recipient_id in normalized_uuid_ids if recipient_id not in by_id]
    if missing:
        raise ValueError(f"unknown recipient ids: {', '.join(missing)}")
    return [by_id[recipient_id] for recipient_id in normalized_uuid_ids]


def publish_application_notification(
    *,
    source_app: str,
    notification_type: str,
    recipient_ids: Iterable[Any],
    title: str,
    body: str = "",
    payload: Optional[Dict[str, Any]] = None,
    deep_link: str = "",
    source_entity_type: str = "",
    source_entity_id: str = "",
    source_metadata: Optional[Dict[str, Any]] = None,
    workspace_id: Optional[str] = None,
    created_by_id: Optional[str] = None,
    request_delivery: bool = False,
    idempotency_key: str = "",
) -> PublishApplicationNotificationResult:
    normalized_recipient_ids = _normalize_identity_ids(recipient_ids)
    if not normalized_recipient_ids:
        raise ValueError("at least one recipient id is required")

    recipients = _resolve_recipients(normalized_recipient_ids)

    workspace = None
    if workspace_id:
        workspace = Workspace.objects.filter(id=workspace_id).first()
        if workspace is None:
            raise ValueError("workspace_id does not match an existing workspace")

    created_by = None
    if created_by_id:
        created_by = UserIdentity.objects.filter(id=created_by_id).first()
        if created_by is None:
            raise ValueError("created_by_id does not match an existing user identity")

    notification, recipient_rows = create_app_notification(
        source_app_key=source_app,
        notification_type_key=notification_type,
        title=title,
        summary=body,
        payload=payload,
        deep_link=deep_link,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        source_metadata=source_metadata,
        workspace=workspace,
        created_by=created_by,
        recipients=recipients,
        enqueue_email_delivery=False,
        idempotency_key=str(idempotency_key or "").strip(),
    )

    delivery_result = None
    if request_delivery:
        delivery_result = enqueue_notification_email_delivery(
            notification=notification,
            recipient_rows=recipient_rows,
        )

    return PublishApplicationNotificationResult(
        notification_id=str(notification.id),
        recipient_ids=[str(row.recipient_id) for row in recipient_rows],
        delivery=delivery_result,
    )
