from django.contrib.auth import get_user_model
from django.test import TestCase

from xyn_orchestrator.models import NotificationRecipient, UserIdentity, Workspace, WorkspaceMembership
from xyn_orchestrator.notifications.service import create_app_notification, get_unread_count_for_recipient


class NotificationsApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user_a_auth = user_model.objects.create_user(username="notif-api-a", password="pass", is_staff=True)
        self.user_b_auth = user_model.objects.create_user(username="notif-api-b", password="pass", is_staff=True)
        self.user_a = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer",
            subject="notif-api-a",
            email="notif-api-a@example.com",
        )
        self.user_b = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer",
            subject="notif-api-b",
            email="notif-api-b@example.com",
        )
        self.workspace_a = Workspace.objects.create(slug="notif-api-a", name="Notification API A")
        self.workspace_b = Workspace.objects.create(slug="notif-api-b", name="Notification API B")
        WorkspaceMembership.objects.create(workspace=self.workspace_a, user_identity=self.user_a, role="reader")
        WorkspaceMembership.objects.create(workspace=self.workspace_a, user_identity=self.user_b, role="reader")

    def _login_identity(self, user, identity: UserIdentity) -> None:
        self.client.force_login(user)
        session = self.client.session
        session["user_identity_id"] = str(identity.id)
        session.save()

    def test_list_notifications_returns_current_recipient_feed(self):
        self._login_identity(self.user_a_auth, self.user_a)
        create_app_notification(
            source_app_key="deal-finder",
            notification_type_key="daily_result",
            title="Visible for user A",
            summary="summary-a",
            deep_link="/app/deals/1",
            payload={"deal_id": "d-1"},
            workspace=self.workspace_a,
            recipients=[self.user_a],
        )
        create_app_notification(
            source_app_key="deal-finder",
            notification_type_key="daily_result",
            title="Only user B",
            workspace=self.workspace_a,
            recipients=[self.user_b],
        )
        create_app_notification(
            source_app_key="deal-finder",
            notification_type_key="daily_result",
            title="Hidden workspace",
            workspace=self.workspace_b,
            recipients=[self.user_a],
        )

        response = self.client.get("/xyn/api/notifications", {"limit": 10, "offset": 0})
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("count"), 1)
        self.assertEqual(payload.get("unread_count"), 1)
        rows = payload.get("notifications") or []
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("title"), "Visible for user A")
        self.assertTrue(rows[0].get("unread"))
        self.assertEqual(rows[0].get("deep_link"), "/app/deals/1")

    def test_unread_count_endpoint_returns_current_user_count(self):
        self._login_identity(self.user_a_auth, self.user_a)
        create_app_notification(
            source_app_key="deal-finder",
            notification_type_key="daily_result",
            title="Unread one",
            workspace=self.workspace_a,
            recipients=[self.user_a],
        )
        response = self.client.get("/xyn/api/notifications/unread-count")
        self.assertEqual(response.status_code, 200, response.content.decode())
        self.assertEqual(response.json().get("unread_count"), 1)

    def test_mark_single_notification_as_read(self):
        self._login_identity(self.user_a_auth, self.user_a)
        notification, _rows = create_app_notification(
            source_app_key="deal-finder",
            notification_type_key="daily_result",
            title="Mark me",
            workspace=self.workspace_a,
            recipients=[self.user_a],
        )

        response = self.client.post(f"/xyn/api/notifications/{notification.id}/read")
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertEqual(str(payload.get("notification_id")), str(notification.id))
        self.assertFalse(payload.get("unread"))
        self.assertEqual(payload.get("unread_count"), 0)
        row = NotificationRecipient.objects.get(notification=notification, recipient=self.user_a)
        self.assertFalse(row.unread)
        self.assertIsNotNone(row.read_at)

    def test_mark_all_notifications_as_read(self):
        self._login_identity(self.user_a_auth, self.user_a)
        create_app_notification(
            source_app_key="deal-finder",
            notification_type_key="daily_result",
            title="Unread one",
            workspace=self.workspace_a,
            recipients=[self.user_a],
        )
        create_app_notification(
            source_app_key="deal-finder",
            notification_type_key="daily_result",
            title="Unread two",
            workspace=self.workspace_a,
            recipients=[self.user_a],
        )

        response = self.client.post("/xyn/api/notifications/read-all")
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json()
        self.assertEqual(payload.get("updated"), 2)
        self.assertEqual(payload.get("unread_count"), 0)
        self.assertEqual(get_unread_count_for_recipient(recipient=self.user_a), 0)

    def test_cross_user_mark_read_does_not_expose_or_mutate_other_feed(self):
        notification, _rows = create_app_notification(
            source_app_key="deal-finder",
            notification_type_key="daily_result",
            title="User A only",
            workspace=self.workspace_a,
            recipients=[self.user_a],
        )
        self._login_identity(self.user_b_auth, self.user_b)

        response = self.client.post(f"/xyn/api/notifications/{notification.id}/read")
        self.assertEqual(response.status_code, 404, response.content.decode())
        self.assertEqual(get_unread_count_for_recipient(recipient=self.user_a), 1)
        self.assertEqual(get_unread_count_for_recipient(recipient=self.user_b), 0)

    def test_unauthenticated_requests_do_not_expose_feed_data(self):
        response = self.client.get("/xyn/api/notifications")
        self.assertIn(response.status_code, {302, 401})
