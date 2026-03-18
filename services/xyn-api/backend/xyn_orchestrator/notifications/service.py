from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from django.db import transaction
from django.db.utils import IntegrityError
from django.db.models import Q, QuerySet
from django.utils import timezone

from xyn_orchestrator.models import (
    AppNotification,
    DeliveryAttempt,
    DeliveryPreference,
    DeliveryTarget,
    NotificationRecipient,
    UserIdentity,
    Workspace,
)


def _normalize_limit(value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 50
    return max(1, min(parsed, 200))


def _normalize_offset(value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 0
    return max(0, parsed)


def _recipient_workspace_ids(recipient: UserIdentity) -> List[str]:
    return [str(value) for value in recipient.workspace_memberships.values_list("workspace_id", flat=True)]


def _recipient_feed_queryset(recipient: UserIdentity) -> QuerySet[NotificationRecipient]:
    workspace_ids = _recipient_workspace_ids(recipient)
    scope_filter = Q(notification__workspace__isnull=True)
    if workspace_ids:
        scope_filter = scope_filter | Q(notification__workspace_id__in=workspace_ids)
    return (
        NotificationRecipient.objects.filter(recipient=recipient)
        .filter(scope_filter)
        .select_related("notification", "notification__workspace")
    )


def _serialize_notification_recipient(row: NotificationRecipient) -> Dict[str, Any]:
    notification = row.notification
    return {
        "notification_id": str(notification.id),
        "recipient_row_id": str(row.id),
        "source_app_key": str(notification.source_app_key or ""),
        "category": str(notification.category or ""),
        "notification_type_key": str(notification.notification_type_key or ""),
        "title": str(notification.title or ""),
        "summary": str(notification.summary or ""),
        "payload": notification.payload_json if isinstance(notification.payload_json, dict) else {},
        "deep_link": str(notification.deep_link or ""),
        "source_entity_type": str(notification.source_entity_type or ""),
        "source_entity_id": str(notification.source_entity_id or ""),
        "source_metadata": notification.source_metadata_json if isinstance(notification.source_metadata_json, dict) else {},
        "workspace_id": str(notification.workspace_id) if notification.workspace_id else None,
        "unread": bool(row.unread),
        "read_at": row.read_at.isoformat() if row.read_at else None,
        "created_at": notification.created_at.isoformat() if notification.created_at else "",
    }


@transaction.atomic
def create_app_notification(
    *,
    source_app_key: str,
    notification_type_key: str,
    title: str,
    recipients: Iterable[UserIdentity],
    workspace: Optional[Workspace] = None,
    category: str = "application",
    summary: str = "",
    payload: Optional[Dict[str, Any]] = None,
    deep_link: str = "",
    source_entity_type: str = "",
    source_entity_id: str = "",
    source_metadata: Optional[Dict[str, Any]] = None,
    created_by: Optional[UserIdentity] = None,
    enqueue_email_delivery: bool = False,
) -> Tuple[AppNotification, List[NotificationRecipient]]:
    deduped_recipients = {
        str(identity.id): identity
        for identity in recipients
        if isinstance(identity, UserIdentity)
    }
    if not deduped_recipients:
        raise ValueError("at least one recipient is required")
    if not str(source_app_key or "").strip():
        raise ValueError("source_app_key is required")
    if not str(notification_type_key or "").strip():
        raise ValueError("notification_type_key is required")
    if not str(title or "").strip():
        raise ValueError("title is required")

    notification = AppNotification.objects.create(
        workspace=workspace,
        source_app_key=str(source_app_key).strip(),
        category=str(category or "application").strip() or "application",
        notification_type_key=str(notification_type_key).strip(),
        title=str(title).strip(),
        summary=str(summary or "").strip(),
        payload_json=payload if isinstance(payload, dict) else {},
        deep_link=str(deep_link or "").strip(),
        source_entity_type=str(source_entity_type or "").strip(),
        source_entity_id=str(source_entity_id or "").strip(),
        source_metadata_json=source_metadata if isinstance(source_metadata, dict) else {},
        created_by=created_by,
    )

    recipient_rows = NotificationRecipient.objects.bulk_create(
        [
            NotificationRecipient(
                notification=notification,
                recipient=identity,
                unread=True,
            )
            for identity in deduped_recipients.values()
        ]
    )
    if enqueue_email_delivery:
        # Keep notification creation store-first; delivery is always queued asynchronously.
        from .delivery import enqueue_notification_email_delivery

        enqueue_notification_email_delivery(notification=notification, recipient_rows=recipient_rows)
    return notification, recipient_rows


def list_notifications_for_recipient(
    *,
    recipient: UserIdentity,
    limit: int = 50,
    offset: int = 0,
    unread_only: bool = False,
    source_app_key: str = "",
    category: str = "",
    workspace: Optional[Workspace] = None,
) -> Dict[str, Any]:
    qs = _recipient_feed_queryset(recipient)
    if unread_only:
        qs = qs.filter(unread=True)
    if source_app_key:
        qs = qs.filter(notification__source_app_key=str(source_app_key).strip())
    if category:
        qs = qs.filter(notification__category=str(category).strip())
    if workspace is not None:
        qs = qs.filter(notification__workspace=workspace)
    qs = qs.order_by("-notification__created_at", "-created_at")

    normalized_limit = _normalize_limit(limit)
    normalized_offset = _normalize_offset(offset)
    total = qs.count()
    rows = list(qs[normalized_offset : normalized_offset + normalized_limit])
    return {
        "notifications": [_serialize_notification_recipient(row) for row in rows],
        "count": total,
        "limit": normalized_limit,
        "offset": normalized_offset,
    }


def get_unread_count_for_recipient(*, recipient: UserIdentity) -> int:
    return _recipient_feed_queryset(recipient).filter(unread=True).count()


@transaction.atomic
def mark_notification_as_read(
    *,
    recipient: UserIdentity,
    notification_id: str,
) -> bool:
    now = timezone.now()
    updated = (
        _recipient_feed_queryset(recipient)
        .filter(notification_id=notification_id, unread=True)
        .update(unread=False, read_at=now, updated_at=now)
    )
    return bool(updated)


@transaction.atomic
def mark_all_notifications_as_read(*, recipient: UserIdentity) -> int:
    now = timezone.now()
    return _recipient_feed_queryset(recipient).filter(unread=True).update(unread=False, read_at=now, updated_at=now)


def _preference_candidates(
    *,
    owner: UserIdentity,
    workspace: Optional[Workspace],
) -> QuerySet[DeliveryPreference]:
    qs = DeliveryPreference.objects.filter(owner=owner)
    if workspace is None:
        return qs.filter(workspace__isnull=True)
    return qs.filter(Q(workspace=workspace) | Q(workspace__isnull=True))


def _match_preference(
    rows: Sequence[DeliveryPreference],
    *,
    workspace: Optional[Workspace],
    source_app_key: str,
    notification_type_key: str,
) -> Optional[DeliveryPreference]:
    target_workspace_id = str(workspace.id) if workspace else None
    source_key = str(source_app_key or "").strip()
    type_key = str(notification_type_key or "").strip()
    rank = [
        (target_workspace_id, source_key, type_key),
        (target_workspace_id, source_key, ""),
        (target_workspace_id, "", type_key),
        (target_workspace_id, "", ""),
        (None, source_key, type_key),
        (None, source_key, ""),
        (None, "", type_key),
        (None, "", ""),
    ]
    for workspace_id, source_match, type_match in rank:
        for row in rows:
            if (str(row.workspace_id) if row.workspace_id else None) != workspace_id:
                continue
            if str(row.source_app_key or "").strip() != source_match:
                continue
            if str(row.notification_type_key or "").strip() != type_match:
                continue
            return row
    return None


def resolve_delivery_targets_and_preference(
    *,
    owner: UserIdentity,
    workspace: Optional[Workspace] = None,
    source_app_key: str = "",
    notification_type_key: str = "",
) -> Dict[str, Any]:
    targets = list(
        DeliveryTarget.objects.filter(owner=owner, enabled=True).order_by("-is_primary", "-updated_at", "-created_at")
    )
    candidate_preferences = list(_preference_candidates(owner=owner, workspace=workspace))
    preference = _match_preference(
        candidate_preferences,
        workspace=workspace,
        source_app_key=source_app_key,
        notification_type_key=notification_type_key,
    )
    return {
        "targets": targets,
        "preference": preference,
        "effective": {
            "in_app_enabled": bool(preference.in_app_enabled) if preference else True,
            "email_enabled": bool(preference.email_enabled) if preference else True,
        },
    }


def _serialize_delivery_target(target: DeliveryTarget) -> Dict[str, Any]:
    return {
        "id": str(target.id),
        "owner_id": str(target.owner_id),
        "channel": str(target.channel or ""),
        "address": str(target.address or ""),
        "enabled": bool(target.enabled),
        "verification_status": str(target.verification_status or ""),
        "is_primary": bool(target.is_primary),
        "metadata": target.metadata_json if isinstance(target.metadata_json, dict) else {},
        "created_at": target.created_at.isoformat() if target.created_at else None,
        "updated_at": target.updated_at.isoformat() if target.updated_at else None,
    }


def list_delivery_targets(*, owner: UserIdentity) -> List[Dict[str, Any]]:
    rows = DeliveryTarget.objects.filter(owner=owner).order_by("-is_primary", "-updated_at", "-created_at")
    return [_serialize_delivery_target(row) for row in rows]


@transaction.atomic
def create_delivery_target(
    *,
    owner: UserIdentity,
    address: str,
    channel: str = "email",
    enabled: bool = True,
    is_primary: bool = False,
) -> DeliveryTarget:
    if str(channel or "").strip().lower() != "email":
        raise ValueError("only email delivery targets are supported")
    normalized_address = str(address or "").strip().lower()
    if not normalized_address:
        raise ValueError("address is required")
    try:
        row = DeliveryTarget.objects.create(
            owner=owner,
            channel="email",
            address=normalized_address,
            enabled=bool(enabled),
            verification_status="unverified",
            is_primary=bool(is_primary),
        )
    except IntegrityError as exc:
        raise ValueError("delivery target already exists") from exc
    return row


@transaction.atomic
def set_delivery_target_enabled(
    *,
    owner: UserIdentity,
    target_id: str,
    enabled: bool,
) -> Optional[DeliveryTarget]:
    row = DeliveryTarget.objects.filter(owner=owner, id=target_id).first()
    if row is None:
        return None
    row.enabled = bool(enabled)
    row.save(update_fields=["enabled", "updated_at"])
    return row


@transaction.atomic
def remove_delivery_target(
    *,
    owner: UserIdentity,
    target_id: str,
) -> bool:
    deleted, _ = DeliveryTarget.objects.filter(owner=owner, id=target_id).delete()
    return bool(deleted)


def get_delivery_preference(
    *,
    owner: UserIdentity,
    source_app_key: str = "",
) -> Dict[str, Any]:
    source_key = str(source_app_key or "").strip()
    row = (
        DeliveryPreference.objects.filter(
            owner=owner,
            workspace__isnull=True,
            source_app_key=source_key,
            notification_type_key="",
        )
        .order_by("-updated_at", "-created_at")
        .first()
    )
    if row is None:
        return {
            "source_app_key": source_key,
            "in_app_enabled": True,
            "email_enabled": True,
            "created_at": None,
            "updated_at": None,
        }
    return {
        "source_app_key": str(row.source_app_key or ""),
        "in_app_enabled": bool(row.in_app_enabled),
        "email_enabled": bool(row.email_enabled),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@transaction.atomic
def set_delivery_preference(
    *,
    owner: UserIdentity,
    source_app_key: str = "",
    in_app_enabled: bool,
    email_enabled: bool,
) -> DeliveryPreference:
    source_key = str(source_app_key or "").strip()
    row, _created = DeliveryPreference.objects.update_or_create(
        owner=owner,
        workspace=None,
        source_app_key=source_key,
        notification_type_key="",
        defaults={
            "in_app_enabled": bool(in_app_enabled),
            "email_enabled": bool(email_enabled),
        },
    )
    return row


@transaction.atomic
def record_delivery_attempt(
    *,
    notification: AppNotification,
    channel: str,
    status: str = "pending",
    retry_count: int = 0,
    recipient_row: Optional[NotificationRecipient] = None,
    target: Optional[DeliveryTarget] = None,
    provider_name: str = "",
    provider_message_id: str = "",
    error_text: str = "",
    error_details: Optional[Dict[str, Any]] = None,
    attempted_at=None,
    delivered_at=None,
) -> DeliveryAttempt:
    if recipient_row and recipient_row.notification_id != notification.id:
        raise ValueError("recipient_row must belong to notification")
    if target and recipient_row and target.owner_id != recipient_row.recipient_id:
        raise ValueError("target owner must match recipient owner")
    return DeliveryAttempt.objects.create(
        notification=notification,
        recipient=recipient_row,
        target=target,
        channel=str(channel or "").strip() or "email",
        status=str(status or "").strip() or "pending",
        retry_count=max(0, int(retry_count or 0)),
        provider_name=str(provider_name or "").strip(),
        provider_message_id=str(provider_message_id or "").strip(),
        error_text=str(error_text or ""),
        error_details_json=error_details if isinstance(error_details, dict) else None,
        attempted_at=attempted_at or timezone.now(),
        delivered_at=delivered_at,
    )
