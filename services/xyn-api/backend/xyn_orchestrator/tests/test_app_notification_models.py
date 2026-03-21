from django.db import IntegrityError, transaction
from django.test import TestCase
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


class AppNotificationModelTests(TestCase):
    def setUp(self):
        self.workspace = Workspace.objects.create(slug="notif-ws", name="Notifications Workspace")
        self.creator = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer",
            subject="creator",
            email="creator@example.com",
        )
        self.recipient = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer",
            subject="recipient",
            email="recipient@example.com",
        )

    def _create_notification(self, *, source_entity_id: str = "deal-123") -> AppNotification:
        return AppNotification.objects.create(
            workspace=self.workspace,
            source_app_key="deal-finder",
            category="application",
            notification_type_key="daily_distress_result",
            title="New distress candidate",
            summary="A new deal candidate matched your criteria.",
            payload_json={"score": 92, "county": "Jackson"},
            deep_link="/app/deals/123",
            source_entity_type="deal",
            source_entity_id=source_entity_id,
            source_metadata_json={"job_id": "job-1"},
            created_by=self.creator,
        )

    def test_models_create_and_persist_relationships(self):
        notification = self._create_notification()
        recipient_row = NotificationRecipient.objects.create(
            notification=notification,
            recipient=self.recipient,
            unread=True,
        )
        target = DeliveryTarget.objects.create(
            owner=self.recipient,
            channel="email",
            address="recipient@example.com",
            enabled=True,
            verification_status="verified",
            is_primary=True,
        )
        preference = DeliveryPreference.objects.create(
            owner=self.recipient,
            workspace=self.workspace,
            source_app_key="deal-finder",
            notification_type_key="daily_distress_result",
            in_app_enabled=True,
            email_enabled=True,
        )
        attempt = DeliveryAttempt.objects.create(
            notification=notification,
            recipient=recipient_row,
            target=target,
            channel="email",
            status="pending",
            retry_count=0,
            provider_name="ses",
        )

        self.assertEqual(notification.source_app_key, "deal-finder")
        self.assertEqual(recipient_row.notification_id, notification.id)
        self.assertTrue(recipient_row.unread)
        self.assertEqual(target.owner_id, self.recipient.id)
        self.assertEqual(preference.workspace_id, self.workspace.id)
        self.assertEqual(attempt.notification_id, notification.id)
        self.assertEqual(attempt.target_id, target.id)

    def test_notification_recipient_unique_constraint(self):
        notification = self._create_notification()
        NotificationRecipient.objects.create(notification=notification, recipient=self.recipient)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                NotificationRecipient.objects.create(notification=notification, recipient=self.recipient)

    def test_notification_recipient_read_state_basics(self):
        notification = self._create_notification()
        recipient_row = NotificationRecipient.objects.create(notification=notification, recipient=self.recipient)
        self.assertTrue(recipient_row.unread)
        self.assertIsNone(recipient_row.read_at)

        recipient_row.unread = False
        recipient_row.read_at = timezone.now()
        recipient_row.save(update_fields=["unread", "read_at", "updated_at"])
        recipient_row.refresh_from_db()

        self.assertFalse(recipient_row.unread)
        self.assertIsNotNone(recipient_row.read_at)

    def test_delivery_target_primary_uniqueness_per_owner_channel(self):
        DeliveryTarget.objects.create(
            owner=self.recipient,
            channel="email",
            address="first@example.com",
            is_primary=True,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DeliveryTarget.objects.create(
                    owner=self.recipient,
                    channel="email",
                    address="second@example.com",
                    is_primary=True,
                )

    def test_delivery_preference_scope_uniqueness(self):
        DeliveryPreference.objects.create(
            owner=self.recipient,
            workspace=None,
            source_app_key="deal-finder",
            notification_type_key="daily_distress_result",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DeliveryPreference.objects.create(
                    owner=self.recipient,
                    workspace=None,
                    source_app_key="deal-finder",
                    notification_type_key="daily_distress_result",
                )

        DeliveryPreference.objects.create(
            owner=self.recipient,
            workspace=self.workspace,
            source_app_key="deal-finder",
            notification_type_key="daily_distress_result",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DeliveryPreference.objects.create(
                    owner=self.recipient,
                    workspace=self.workspace,
                    source_app_key="deal-finder",
                    notification_type_key="daily_distress_result",
                )

