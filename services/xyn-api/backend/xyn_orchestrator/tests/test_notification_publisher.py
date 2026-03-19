from unittest import mock

from django.test import TestCase

from xyn_orchestrator.models import (
    AppNotification,
    DeliveryAttempt,
    DeliveryPreference,
    DeliveryTarget,
    NotificationRecipient,
    UserIdentity,
    Workspace,
)
from xyn_orchestrator.notifications.publisher import publish_application_notification


class NotificationPublisherTests(TestCase):
    def setUp(self):
        self.workspace = Workspace.objects.create(slug="publisher", name="Publisher")
        self.creator = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer",
            subject="publisher-creator",
            email="creator@example.com",
        )
        self.recipient_a = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer",
            subject="publisher-a",
            email="a@example.com",
        )
        self.recipient_b = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer",
            subject="publisher-b",
            email="b@example.com",
        )

    def test_publish_creates_notification_and_preserves_generic_metadata(self):
        result = publish_application_notification(
            source_app="portfolio-ops",
            notification_type="status_update",
            recipient_ids=[str(self.recipient_a.id), str(self.recipient_b.id)],
            title="Status updated",
            body="Execution finished with warnings",
            payload={"run_id": "run-123", "warning_count": 2},
            deep_link="/app/runs/run-123",
            source_entity_type="run",
            source_entity_id="run-123",
            source_metadata={"origin": "system-check"},
            workspace_id=str(self.workspace.id),
            created_by_id=str(self.creator.id),
            request_delivery=False,
        )

        notification = AppNotification.objects.get(id=result.notification_id)
        self.assertEqual(notification.source_app_key, "portfolio-ops")
        self.assertEqual(notification.notification_type_key, "status_update")
        self.assertEqual(notification.title, "Status updated")
        self.assertEqual(notification.summary, "Execution finished with warnings")
        self.assertEqual(notification.payload_json, {"run_id": "run-123", "warning_count": 2})
        self.assertEqual(notification.deep_link, "/app/runs/run-123")
        self.assertEqual(notification.source_entity_type, "run")
        self.assertEqual(notification.source_entity_id, "run-123")
        self.assertEqual(notification.source_metadata_json, {"origin": "system-check"})
        self.assertEqual(notification.workspace_id, self.workspace.id)
        self.assertEqual(notification.created_by_id, self.creator.id)

        attached = set(NotificationRecipient.objects.filter(notification=notification).values_list("recipient_id", flat=True))
        self.assertEqual(attached, {self.recipient_a.id, self.recipient_b.id})
        self.assertEqual(set(result.recipient_ids), {str(self.recipient_a.id), str(self.recipient_b.id)})
        self.assertIsNone(result.delivery)
        self.assertEqual(DeliveryAttempt.objects.count(), 0)

    @mock.patch("xyn_orchestrator.notifications.delivery._enqueue_delivery_attempt", return_value="job-1")
    def test_publish_delivery_requested_and_allowed_queues_attempt(self, _enqueue_mock):
        DeliveryTarget.objects.create(
            owner=self.recipient_a,
            channel="email",
            address="a@example.com",
            enabled=True,
            verification_status="verified",
            is_primary=True,
        )

        result = publish_application_notification(
            source_app="portfolio-ops",
            notification_type="status_update",
            recipient_ids=[str(self.recipient_a.id)],
            title="Queued update",
            workspace_id=str(self.workspace.id),
            request_delivery=True,
        )

        self.assertEqual(result.delivery, {"queued": 1, "skipped": 0, "failed": 0})
        self.assertEqual(DeliveryAttempt.objects.count(), 1)
        attempt = DeliveryAttempt.objects.first()
        self.assertEqual(str(attempt.notification_id), result.notification_id)
        self.assertEqual(attempt.status, "pending")

    @mock.patch("xyn_orchestrator.notifications.delivery._enqueue_delivery_attempt", return_value="job-1")
    def test_publish_delivery_requested_respects_preference_and_skips(self, _enqueue_mock):
        DeliveryTarget.objects.create(
            owner=self.recipient_a,
            channel="email",
            address="a@example.com",
            enabled=True,
            verification_status="verified",
            is_primary=True,
        )
        DeliveryPreference.objects.create(
            owner=self.recipient_a,
            workspace=self.workspace,
            source_app_key="portfolio-ops",
            notification_type_key="status_update",
            in_app_enabled=True,
            email_enabled=False,
        )

        result = publish_application_notification(
            source_app="portfolio-ops",
            notification_type="status_update",
            recipient_ids=[str(self.recipient_a.id)],
            title="No email expected",
            workspace_id=str(self.workspace.id),
            request_delivery=True,
        )

        self.assertEqual(result.delivery, {"queued": 0, "skipped": 1, "failed": 0})
        self.assertEqual(DeliveryAttempt.objects.count(), 0)
        _enqueue_mock.assert_not_called()

    def test_publish_rejects_invalid_recipient_id(self):
        with self.assertRaisesMessage(ValueError, "invalid recipient id: missing-id"):
            publish_application_notification(
                source_app="portfolio-ops",
                notification_type="status_update",
                recipient_ids=["missing-id"],
                title="Invalid recipient",
            )

    @mock.patch("xyn_orchestrator.notifications.delivery._enqueue_delivery_attempt", return_value="job-1")
    def test_publish_replay_with_idempotency_key_returns_existing_notification(self, _enqueue_mock):
        DeliveryTarget.objects.create(
            owner=self.recipient_a,
            channel="email",
            address="a@example.com",
            enabled=True,
            verification_status="verified",
            is_primary=True,
        )
        first = publish_application_notification(
            source_app="portfolio-ops",
            notification_type="status_update",
            recipient_ids=[str(self.recipient_a.id)],
            title="Status updated",
            workspace_id=str(self.workspace.id),
            request_delivery=True,
            idempotency_key="idem-123",
        )
        second = publish_application_notification(
            source_app="portfolio-ops",
            notification_type="status_update",
            recipient_ids=[str(self.recipient_a.id)],
            title="Status updated",
            workspace_id=str(self.workspace.id),
            request_delivery=True,
            idempotency_key="idem-123",
        )
        self.assertEqual(first.notification_id, second.notification_id)
        self.assertEqual(AppNotification.objects.count(), 1)
        self.assertEqual(NotificationRecipient.objects.count(), 1)
        self.assertEqual(DeliveryAttempt.objects.count(), 1)
