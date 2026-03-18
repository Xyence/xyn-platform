from django.contrib.auth import get_user_model
from django.test import TestCase

from xyn_orchestrator.models import DeliveryPreference, DeliveryTarget, UserIdentity


class NotificationSettingsApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user_a_auth = user_model.objects.create_user(username="notif-settings-a", password="pass", is_staff=True)
        self.user_b_auth = user_model.objects.create_user(username="notif-settings-b", password="pass", is_staff=True)
        self.user_a = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer",
            subject="notif-settings-a",
            email="notif-settings-a@example.com",
        )
        self.user_b = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer",
            subject="notif-settings-b",
            email="notif-settings-b@example.com",
        )

    def _login_identity(self, user, identity: UserIdentity) -> None:
        self.client.force_login(user)
        session = self.client.session
        session["user_identity_id"] = str(identity.id)
        session.save()

    def test_list_own_targets(self):
        DeliveryTarget.objects.create(
            owner=self.user_a,
            channel="email",
            address="a@example.com",
            enabled=True,
            verification_status="verified",
        )
        DeliveryTarget.objects.create(
            owner=self.user_b,
            channel="email",
            address="b@example.com",
            enabled=True,
            verification_status="verified",
        )
        self._login_identity(self.user_a_auth, self.user_a)
        response = self.client.get("/xyn/api/notifications/targets")
        self.assertEqual(response.status_code, 200, response.content.decode())
        targets = response.json().get("targets") or []
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].get("address"), "a@example.com")

    def test_add_own_target_and_validate_invalid_email(self):
        self._login_identity(self.user_a_auth, self.user_a)
        invalid_response = self.client.post(
            "/xyn/api/notifications/targets",
            data='{"address":"not-an-email"}',
            content_type="application/json",
        )
        self.assertEqual(invalid_response.status_code, 400, invalid_response.content.decode())

        response = self.client.post(
            "/xyn/api/notifications/targets",
            data='{"address":"new-target@example.com","enabled":true}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content.decode())
        payload = response.json()
        self.assertEqual((payload.get("target") or {}).get("address"), "new-target@example.com")
        self.assertEqual(DeliveryTarget.objects.filter(owner=self.user_a).count(), 1)

    def test_enable_disable_and_cross_user_mutation_is_blocked(self):
        target = DeliveryTarget.objects.create(
            owner=self.user_a,
            channel="email",
            address="toggle@example.com",
            enabled=True,
            verification_status="verified",
        )
        self._login_identity(self.user_b_auth, self.user_b)
        cross_user_response = self.client.patch(
            f"/xyn/api/notifications/targets/{target.id}",
            data='{"enabled":false}',
            content_type="application/json",
        )
        self.assertEqual(cross_user_response.status_code, 404, cross_user_response.content.decode())
        target.refresh_from_db()
        self.assertTrue(target.enabled)

        self._login_identity(self.user_a_auth, self.user_a)
        response = self.client.patch(
            f"/xyn/api/notifications/targets/{target.id}",
            data='{"enabled":false}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content.decode())
        target.refresh_from_db()
        self.assertFalse(target.enabled)

    def test_remove_target(self):
        target = DeliveryTarget.objects.create(
            owner=self.user_a,
            channel="email",
            address="delete-me@example.com",
            enabled=True,
            verification_status="verified",
        )
        self._login_identity(self.user_a_auth, self.user_a)
        response = self.client.delete(f"/xyn/api/notifications/targets/{target.id}")
        self.assertEqual(response.status_code, 200, response.content.decode())
        self.assertFalse(DeliveryTarget.objects.filter(id=target.id).exists())

    def test_get_and_set_preferences(self):
        self._login_identity(self.user_a_auth, self.user_a)
        get_default = self.client.get("/xyn/api/notifications/preferences")
        self.assertEqual(get_default.status_code, 200, get_default.content.decode())
        self.assertTrue((get_default.json().get("preference") or {}).get("in_app_enabled"))
        self.assertTrue((get_default.json().get("preference") or {}).get("email_enabled"))

        set_response = self.client.put(
            "/xyn/api/notifications/preferences",
            data='{"source_app_key":"deal-finder","in_app_enabled":true,"email_enabled":false}',
            content_type="application/json",
        )
        self.assertEqual(set_response.status_code, 200, set_response.content.decode())
        row = DeliveryPreference.objects.get(owner=self.user_a, workspace__isnull=True, source_app_key="deal-finder")
        self.assertTrue(row.in_app_enabled)
        self.assertFalse(row.email_enabled)

        get_scoped = self.client.get("/xyn/api/notifications/preferences", {"source_app_key": "deal-finder"})
        self.assertEqual(get_scoped.status_code, 200, get_scoped.content.decode())
        scoped_pref = get_scoped.json().get("preference") or {}
        self.assertEqual(scoped_pref.get("source_app_key"), "deal-finder")
        self.assertTrue(scoped_pref.get("in_app_enabled"))
        self.assertFalse(scoped_pref.get("email_enabled"))

    def test_cross_user_preference_isolated(self):
        DeliveryPreference.objects.create(
            owner=self.user_a,
            workspace=None,
            source_app_key="deal-finder",
            notification_type_key="",
            in_app_enabled=False,
            email_enabled=False,
        )
        self._login_identity(self.user_b_auth, self.user_b)
        response = self.client.get("/xyn/api/notifications/preferences", {"source_app_key": "deal-finder"})
        self.assertEqual(response.status_code, 200, response.content.decode())
        payload = response.json().get("preference") or {}
        self.assertTrue(payload.get("in_app_enabled"))
        self.assertTrue(payload.get("email_enabled"))
