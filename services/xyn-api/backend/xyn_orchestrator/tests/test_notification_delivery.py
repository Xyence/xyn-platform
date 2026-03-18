from unittest import mock

from django.test import TestCase

from xyn_orchestrator.models import DeliveryAttempt, DeliveryPreference, DeliveryTarget, UserIdentity, Workspace, WorkspaceMembership
from xyn_orchestrator.notifications.delivery import deliver_notification_email_attempt, enqueue_notification_email_delivery
from xyn_orchestrator.notifications.service import create_app_notification, record_delivery_attempt


class _FakeSender:
    provider_name = "fake_sender"

    def __init__(self, fail: bool = False):
        self.fail = fail

    def send_email(self, message):
        if self.fail:
            raise RuntimeError("simulated email delivery failure")
        return "provider-msg-1"


class NotificationDeliveryTests(TestCase):
    def setUp(self):
        self.workspace = Workspace.objects.create(slug="notif-delivery", name="Notification Delivery")
        self.owner = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer",
            subject="notif-owner",
            email="owner@example.com",
        )
        WorkspaceMembership.objects.create(workspace=self.workspace, user_identity=self.owner, role="reader")
        self.target = DeliveryTarget.objects.create(
            owner=self.owner,
            channel="email",
            address="owner@example.com",
            enabled=True,
            verification_status="verified",
            is_primary=True,
        )
        self.notification, self.rows = create_app_notification(
            source_app_key="deal-finder",
            notification_type_key="daily_result",
            title="Deal finder result",
            summary="One new opportunity",
            workspace=self.workspace,
            recipients=[self.owner],
        )

    @mock.patch("xyn_orchestrator.notifications.delivery.resolve_email_sender")
    @mock.patch("xyn_orchestrator.notifications.delivery._enqueue_delivery_attempt", return_value="job-1")
    def test_enqueue_creates_pending_attempt_and_does_not_send_sync(self, enqueue_mock, resolve_sender_mock):
        result = enqueue_notification_email_delivery(notification=self.notification, recipient_rows=self.rows)
        self.assertEqual(result["queued"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(DeliveryAttempt.objects.count(), 1)
        attempt = DeliveryAttempt.objects.first()
        self.assertEqual(attempt.status, "pending")
        enqueue_mock.assert_called_once()
        resolve_sender_mock.assert_not_called()

    @mock.patch("xyn_orchestrator.notifications.delivery._enqueue_delivery_attempt", return_value="job-1")
    def test_enqueue_gates_by_preference_email_enabled(self, _enqueue_mock):
        DeliveryPreference.objects.create(
            owner=self.owner,
            workspace=None,
            source_app_key="deal-finder",
            notification_type_key="daily_result",
            in_app_enabled=True,
            email_enabled=False,
        )
        result = enqueue_notification_email_delivery(notification=self.notification, recipient_rows=self.rows)
        self.assertEqual(result["queued"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(DeliveryAttempt.objects.count(), 0)

    @mock.patch("xyn_orchestrator.notifications.delivery.resolve_email_sender", return_value=_FakeSender(fail=False))
    def test_delivery_attempt_success_updates_status(self, _resolve_sender):
        attempt = record_delivery_attempt(
            notification=self.notification,
            recipient_row=self.rows[0],
            target=self.target,
            channel="email",
            status="pending",
            retry_count=0,
            provider_name="fake",
        )
        deliver_notification_email_attempt(str(attempt.id))
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, "delivered")
        self.assertEqual(attempt.provider_name, "fake_sender")
        self.assertEqual(attempt.provider_message_id, "provider-msg-1")
        self.assertIsNotNone(attempt.delivered_at)

    @mock.patch.dict("os.environ", {"XYN_NOTIFICATION_EMAIL_MAX_ATTEMPTS": "2"})
    @mock.patch("xyn_orchestrator.notifications.delivery.resolve_email_sender", return_value=_FakeSender(fail=True))
    def test_delivery_attempt_failure_retries_then_marks_failed(self, _resolve_sender):
        attempt = record_delivery_attempt(
            notification=self.notification,
            recipient_row=self.rows[0],
            target=self.target,
            channel="email",
            status="pending",
            retry_count=0,
            provider_name="fake",
        )
        with self.assertRaises(RuntimeError):
            deliver_notification_email_attempt(str(attempt.id))
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, "pending")
        self.assertEqual(attempt.retry_count, 1)
        self.assertIn("simulated email delivery failure", attempt.error_text)

        deliver_notification_email_attempt(str(attempt.id))
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, "failed")
        self.assertEqual(attempt.retry_count, 2)

    @mock.patch("xyn_orchestrator.notifications.delivery.enqueue_notification_email_delivery")
    def test_create_notification_can_trigger_async_enqueue(self, enqueue_mock):
        create_app_notification(
            source_app_key="deal-finder",
            notification_type_key="daily_result",
            title="Queue me",
            workspace=self.workspace,
            recipients=[self.owner],
            enqueue_email_delivery=True,
        )
        enqueue_mock.assert_called_once()
