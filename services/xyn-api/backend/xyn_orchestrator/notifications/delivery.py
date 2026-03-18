from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass
from typing import Dict, Iterable, Optional

import boto3
import redis
from rq import Queue, Retry

from django.utils import timezone

from xyn_orchestrator.models import AppNotification, DeliveryAttempt, DeliveryTarget, NotificationRecipient

from .service import record_delivery_attempt, resolve_delivery_targets_and_preference

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailMessage:
    to_address: str
    subject: str
    text_body: str
    html_body: str


class EmailSender:
    provider_name = "log"

    def send_email(self, message: EmailMessage) -> str:
        logger.info(
            "notification email provider=log to=%s subject=%s",
            message.to_address,
            message.subject,
        )
        return f"log-{uuid.uuid4()}"


class AwsSesEmailSender(EmailSender):
    provider_name = "aws_ses"

    def __init__(self, from_address: str, region: str = ""):
        self.from_address = str(from_address or "").strip()
        self.region = str(region or "").strip()
        if not self.from_address:
            raise ValueError("XYN_NOTIFICATION_EMAIL_FROM is required for aws_ses provider")

    def send_email(self, message: EmailMessage) -> str:
        client = boto3.client("sesv2", region_name=self.region) if self.region else boto3.client("sesv2")
        response = client.send_email(
            FromEmailAddress=self.from_address,
            Destination={"ToAddresses": [message.to_address]},
            Content={
                "Simple": {
                    "Subject": {"Data": message.subject[:240]},
                    "Body": {
                        "Text": {"Data": message.text_body},
                        "Html": {"Data": message.html_body},
                    },
                }
            },
        )
        return str(response.get("MessageId") or "")


def _email_provider_name() -> str:
    return str(os.environ.get("XYN_NOTIFICATION_EMAIL_PROVIDER", "log") or "log").strip().lower()


def resolve_email_sender() -> EmailSender:
    provider = _email_provider_name()
    if provider in {"aws_ses", "ses"}:
        return AwsSesEmailSender(
            from_address=str(os.environ.get("XYN_NOTIFICATION_EMAIL_FROM", "") or "").strip(),
            region=str(os.environ.get("XYN_NOTIFICATION_EMAIL_REGION", "") or "").strip(),
        )
    return EmailSender()


def _max_attempts() -> int:
    raw = str(os.environ.get("XYN_NOTIFICATION_EMAIL_MAX_ATTEMPTS", "3") or "3").strip()
    try:
        parsed = int(raw)
    except ValueError:
        parsed = 3
    return max(1, min(parsed, 8))


def _retry_intervals() -> list[int]:
    return [30, 120, 300, 600, 1200]


def _enqueue_delivery_attempt(attempt_id: str) -> str:
    redis_url = os.environ.get("XYENCE_JOBS_REDIS_URL", "redis://redis:6379/0")
    queue = Queue("default", connection=redis.Redis.from_url(redis_url))
    max_attempts = _max_attempts()
    retry = Retry(max=max_attempts - 1, interval=_retry_intervals()[: max(0, max_attempts - 1)]) if max_attempts > 1 else None
    job = queue.enqueue(
        "xyn_orchestrator.worker_tasks.deliver_notification_email_attempt",
        str(attempt_id),
        job_timeout=300,
        retry=retry,
    )
    return str(job.id)


def _render_email_message(notification: AppNotification, target: DeliveryTarget) -> EmailMessage:
    title = str(notification.title or "").strip() or "Application notification"
    summary = str(notification.summary or "").strip()
    deep_link = str(notification.deep_link or "").strip()
    payload = notification.payload_json if isinstance(notification.payload_json, dict) else {}
    payload_text = json.dumps(payload, sort_keys=True, indent=2) if payload else ""
    body_lines = [title]
    if summary:
        body_lines.append("")
        body_lines.append(summary)
    if deep_link:
        body_lines.append("")
        body_lines.append(f"Open: {deep_link}")
    if payload_text:
        body_lines.append("")
        body_lines.append("Details:")
        body_lines.append(payload_text)
    text_body = "\n".join(body_lines).strip()
    html_body = "<br/>".join(line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") for line in body_lines).strip()
    return EmailMessage(
        to_address=str(target.address or "").strip(),
        subject=title,
        text_body=text_body,
        html_body=f"<p>{html_body}</p>" if html_body else "<p>Application notification</p>",
    )


def enqueue_notification_email_delivery(
    *,
    notification: AppNotification,
    recipient_rows: Optional[Iterable[NotificationRecipient]] = None,
) -> Dict[str, int]:
    rows = list(recipient_rows) if recipient_rows is not None else list(
        NotificationRecipient.objects.filter(notification=notification).select_related("recipient")
    )
    queued = 0
    skipped = 0
    failed = 0
    for row in rows:
        if row.recipient_id is None:
            skipped += 1
            continue
        resolved = resolve_delivery_targets_and_preference(
            owner=row.recipient,
            workspace=notification.workspace,
            source_app_key=notification.source_app_key,
            notification_type_key=notification.notification_type_key,
        )
        if not bool((resolved.get("effective") or {}).get("email_enabled")):
            skipped += 1
            continue
        targets = [
            target
            for target in (resolved.get("targets") or [])
            if isinstance(target, DeliveryTarget) and str(target.channel or "").lower() == "email" and bool(target.enabled)
        ]
        if not targets:
            skipped += 1
            continue
        for target in targets:
            attempt = record_delivery_attempt(
                notification=notification,
                recipient_row=row,
                target=target,
                channel="email",
                status="pending",
                retry_count=0,
                provider_name=_email_provider_name(),
            )
            try:
                _enqueue_delivery_attempt(str(attempt.id))
                queued += 1
            except Exception as exc:
                failed += 1
                attempt.status = "failed"
                attempt.error_text = str(exc)
                attempt.error_details_json = {"stage": "enqueue", "error_type": exc.__class__.__name__}
                attempt.save(update_fields=["status", "error_text", "error_details_json", "updated_at"])
    return {"queued": queued, "skipped": skipped, "failed": failed}


def deliver_notification_email_attempt(attempt_id: str) -> None:
    attempt = (
        DeliveryAttempt.objects.select_related("notification", "target", "recipient", "recipient__recipient")
        .filter(id=attempt_id)
        .first()
    )
    if attempt is None:
        return
    now = timezone.now()
    attempt.attempted_at = now
    attempt.save(update_fields=["attempted_at", "updated_at"])
    if not attempt.notification_id or not attempt.target_id:
        attempt.status = "failed"
        attempt.error_text = "delivery attempt missing notification or target"
        attempt.error_details_json = {"stage": "send", "error_type": "invalid_attempt"}
        attempt.save(update_fields=["status", "error_text", "error_details_json", "updated_at"])
        return
    try:
        sender = resolve_email_sender()
        message = _render_email_message(attempt.notification, attempt.target)
        provider_message_id = sender.send_email(message)
        attempt.status = "delivered"
        attempt.provider_name = str(getattr(sender, "provider_name", "") or attempt.provider_name or "email")
        attempt.provider_message_id = str(provider_message_id or "")
        attempt.delivered_at = timezone.now()
        attempt.error_text = ""
        attempt.error_details_json = None
        attempt.save(
            update_fields=[
                "status",
                "provider_name",
                "provider_message_id",
                "delivered_at",
                "error_text",
                "error_details_json",
                "updated_at",
            ]
        )
        return
    except Exception as exc:
        next_retry_count = int(attempt.retry_count or 0) + 1
        attempt.retry_count = next_retry_count
        attempt.error_text = str(exc)
        attempt.error_details_json = {"stage": "send", "error_type": exc.__class__.__name__}
        if next_retry_count >= _max_attempts():
            attempt.status = "failed"
            attempt.save(update_fields=["retry_count", "status", "error_text", "error_details_json", "updated_at"])
            return
        attempt.status = "pending"
        attempt.save(update_fields=["retry_count", "status", "error_text", "error_details_json", "updated_at"])
        raise
