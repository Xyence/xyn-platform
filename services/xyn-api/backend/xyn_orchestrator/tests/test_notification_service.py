from django.test import TestCase

from xyn_orchestrator.models import DeliveryPreference, DeliveryTarget, UserIdentity, Workspace, WorkspaceMembership
from xyn_orchestrator.notifications.service import (
    create_app_notification,
    get_unread_count_for_recipient,
    list_notifications_for_recipient,
    mark_all_notifications_as_read,
    mark_notification_as_read,
    record_delivery_attempt,
    resolve_delivery_targets_and_preference,
)


class NotificationServiceTests(TestCase):
    def setUp(self):
        self.workspace_a = Workspace.objects.create(slug="notif-a", name="Notifications A")
        self.workspace_b = Workspace.objects.create(slug="notif-b", name="Notifications B")
        self.creator = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer",
            subject="creator",
            email="creator@example.com",
        )
        self.user_a = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer",
            subject="user-a",
            email="user-a@example.com",
        )
        self.user_b = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer",
            subject="user-b",
            email="user-b@example.com",
        )
        WorkspaceMembership.objects.create(workspace=self.workspace_a, user_identity=self.user_a, role="reader")
        WorkspaceMembership.objects.create(workspace=self.workspace_a, user_identity=self.user_b, role="reader")

    def test_create_notification_with_single_recipient(self):
        notification, rows = create_app_notification(
            source_app_key="deal-finder",
            notification_type_key="daily_result",
            title="Daily distress result",
            summary="One new candidate",
            payload={"deal_id": "d-1"},
            deep_link="/app/deals/d-1",
            source_entity_type="deal",
            source_entity_id="d-1",
            source_metadata={"run_id": "run-1"},
            workspace=self.workspace_a,
            created_by=self.creator,
            recipients=[self.user_a],
        )
        self.assertEqual(notification.source_app_key, "deal-finder")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].recipient_id, self.user_a.id)
        self.assertTrue(rows[0].unread)

    def test_create_notification_with_multiple_recipients(self):
        notification, rows = create_app_notification(
            source_app_key="deal-finder",
            notification_type_key="daily_result",
            title="Daily distress result",
            recipients=[self.user_a, self.user_b],
            workspace=self.workspace_a,
        )
        self.assertEqual(notification.recipients.count(), 2)
        self.assertEqual(len(rows), 2)

    def test_list_is_scoped_to_current_recipient(self):
        create_app_notification(
            source_app_key="deal-finder",
            notification_type_key="daily_result",
            title="A visible to A",
            workspace=self.workspace_a,
            recipients=[self.user_a],
        )
        create_app_notification(
            source_app_key="deal-finder",
            notification_type_key="daily_result",
            title="B only",
            workspace=self.workspace_a,
            recipients=[self.user_b],
        )
        # user_a is not a member of workspace_b, so this must be hidden from user_a
        create_app_notification(
            source_app_key="deal-finder",
            notification_type_key="daily_result",
            title="B workspace only",
            workspace=self.workspace_b,
            recipients=[self.user_a],
        )
        result = list_notifications_for_recipient(recipient=self.user_a, limit=20, offset=0)
        titles = [item["title"] for item in result["notifications"]]
        self.assertEqual(result["count"], 1)
        self.assertIn("A visible to A", titles)
        self.assertNotIn("B only", titles)
        self.assertNotIn("B workspace only", titles)

    def test_unread_count_and_mark_single_as_read(self):
        notification, _rows = create_app_notification(
            source_app_key="deal-finder",
            notification_type_key="daily_result",
            title="To read",
            workspace=self.workspace_a,
            recipients=[self.user_a],
        )
        self.assertEqual(get_unread_count_for_recipient(recipient=self.user_a), 1)
        changed = mark_notification_as_read(recipient=self.user_a, notification_id=str(notification.id))
        self.assertTrue(changed)
        self.assertEqual(get_unread_count_for_recipient(recipient=self.user_a), 0)
        # Cross-user safety: user_b cannot mutate user_a recipient row.
        changed_other = mark_notification_as_read(recipient=self.user_b, notification_id=str(notification.id))
        self.assertFalse(changed_other)

    def test_mark_all_notifications_as_read(self):
        create_app_notification(
            source_app_key="deal-finder",
            notification_type_key="daily_result",
            title="First",
            workspace=self.workspace_a,
            recipients=[self.user_a],
        )
        create_app_notification(
            source_app_key="deal-finder",
            notification_type_key="daily_result",
            title="Second",
            workspace=self.workspace_a,
            recipients=[self.user_a],
        )
        self.assertEqual(get_unread_count_for_recipient(recipient=self.user_a), 2)
        updated = mark_all_notifications_as_read(recipient=self.user_a)
        self.assertEqual(updated, 2)
        self.assertEqual(get_unread_count_for_recipient(recipient=self.user_a), 0)

    def test_target_and_preference_resolution_basics(self):
        DeliveryTarget.objects.create(
            owner=self.user_a,
            channel="email",
            address="a-primary@example.com",
            enabled=True,
            verification_status="verified",
            is_primary=True,
        )
        DeliveryTarget.objects.create(
            owner=self.user_a,
            channel="email",
            address="a-disabled@example.com",
            enabled=False,
            verification_status="verified",
            is_primary=False,
        )
        DeliveryPreference.objects.create(
            owner=self.user_a,
            workspace=self.workspace_a,
            source_app_key="deal-finder",
            notification_type_key="daily_result",
            in_app_enabled=True,
            email_enabled=False,
        )
        resolved = resolve_delivery_targets_and_preference(
            owner=self.user_a,
            workspace=self.workspace_a,
            source_app_key="deal-finder",
            notification_type_key="daily_result",
        )
        self.assertEqual(len(resolved["targets"]), 1)
        self.assertEqual(resolved["targets"][0].address, "a-primary@example.com")
        self.assertFalse(resolved["effective"]["email_enabled"])
        self.assertTrue(resolved["effective"]["in_app_enabled"])

    def test_record_delivery_attempt_persists(self):
        notification, rows = create_app_notification(
            source_app_key="deal-finder",
            notification_type_key="daily_result",
            title="Attempt me",
            workspace=self.workspace_a,
            recipients=[self.user_a],
        )
        target = DeliveryTarget.objects.create(
            owner=self.user_a,
            channel="email",
            address="a-primary@example.com",
            enabled=True,
            verification_status="verified",
            is_primary=True,
        )
        attempt = record_delivery_attempt(
            notification=notification,
            recipient_row=rows[0],
            target=target,
            channel="email",
            status="pending",
            retry_count=1,
            provider_name="ses",
            provider_message_id="msg-1",
        )
        self.assertEqual(attempt.notification_id, notification.id)
        self.assertEqual(attempt.recipient_id, rows[0].id)
        self.assertEqual(attempt.target_id, target.id)
        self.assertEqual(attempt.retry_count, 1)

    def test_create_notification_replay_with_idempotency_key(self):
        first, first_rows = create_app_notification(
            source_app_key="deal-finder",
            notification_type_key="daily_result",
            title="Replay-safe",
            workspace=self.workspace_a,
            recipients=[self.user_a],
            idempotency_key="notif-idem-1",
        )
        second, second_rows = create_app_notification(
            source_app_key="deal-finder",
            notification_type_key="daily_result",
            title="Replay-safe",
            workspace=self.workspace_a,
            recipients=[self.user_a],
            idempotency_key="notif-idem-1",
        )
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(first_rows), 1)
        self.assertEqual(len(second_rows), 1)
