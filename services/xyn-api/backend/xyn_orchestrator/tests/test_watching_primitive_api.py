import json
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from xyn_orchestrator.models import Campaign, WatchDefinition, WatchMatchEvent, WatchSubscriber, UserIdentity, Workspace, WorkspaceMembership
from xyn_orchestrator.xyn_api import (
    watch_activate,
    watch_detail,
    watch_matches_collection,
    watch_matches_evaluate,
    watch_pause,
    watch_subscribers_collection,
    watches_collection,
)


class WatchingPrimitiveApiTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        suffix = uuid.uuid4().hex[:8]
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username=f"watch-admin-{suffix}",
            email=f"watch-admin-{suffix}@example.com",
            password="password",
        )
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example",
            subject=f"watch-admin-{suffix}",
            email=f"watch-admin-{suffix}@example.com",
        )
        self.workspace = Workspace.objects.create(slug=f"watch-{suffix}", name="Watch Workspace")
        self.other_workspace = Workspace.objects.create(slug=f"watch-other-{suffix}", name="Other Watch Workspace")
        WorkspaceMembership.objects.create(workspace=self.workspace, user_identity=self.identity, role="admin")

    def _request(self, path: str, *, method: str = "get", data=None):
        request = getattr(self.factory, method.lower())(path, data=data or {}, content_type="application/json")
        request.user = self.user
        return request

    def _create_watch(self, *, lifecycle_state: str = "draft") -> dict:
        payload = {
            "workspace_id": str(self.workspace.id),
            "key": f"watch-{uuid.uuid4().hex[:6]}",
            "name": "Parcel Watch",
            "target_kind": "area",
            "target_ref": {"region": "north"},
            "filter_criteria": {"event_type": {"in": ["change", "create"]}},
            "lifecycle_state": lifecycle_state,
            "metadata": {"notes": "seed"},
        }
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = watches_collection(
                self._request("/xyn/api/watches", method="post", data=json.dumps(payload))
            )
        self.assertEqual(response.status_code, 201)
        return json.loads(response.content)

    def test_create_and_list_watches(self):
        watch = self._create_watch()
        self.assertEqual(watch["lifecycle_state"], "draft")
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = watches_collection(
                self._request(
                    "/xyn/api/watches",
                    data={"workspace_id": str(self.workspace.id), "target_kind": "area"},
                )
            )
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(len(payload["watches"]), 1)
        self.assertEqual(payload["watches"][0]["id"], watch["id"])

    def test_watch_subscriber_management(self):
        watch = self._create_watch()
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            create_response = watch_subscribers_collection(
                self._request(
                    f"/xyn/api/watches/{watch['id']}/subscribers",
                    method="post",
                    data=json.dumps(
                        {
                            "workspace_id": str(self.workspace.id),
                            "subscriber_type": "user_identity",
                            "subscriber_ref": str(self.identity.id),
                            "destination": {"channel": "in_app"},
                            "preferences": {"digest": "daily"},
                        }
                    ),
                ),
                watch["id"],
            )
        self.assertEqual(create_response.status_code, 201)
        subscriber = json.loads(create_response.content)
        self.assertEqual(subscriber["subscriber_type"], "user_identity")

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            list_response = watch_subscribers_collection(
                self._request(
                    f"/xyn/api/watches/{watch['id']}/subscribers",
                    data={"workspace_id": str(self.workspace.id)},
                ),
                watch["id"],
            )
        self.assertEqual(list_response.status_code, 200)
        body = json.loads(list_response.content)
        self.assertEqual(len(body["subscribers"]), 1)
        self.assertEqual(body["subscribers"][0]["id"], subscriber["id"])

    def test_activate_pause_and_evaluate_matches(self):
        watch = self._create_watch(lifecycle_state="draft")
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            activate_response = watch_activate(
                self._request(
                    f"/xyn/api/watches/{watch['id']}/activate",
                    method="post",
                    data=json.dumps({"workspace_id": str(self.workspace.id)}),
                ),
                watch["id"],
            )
        self.assertEqual(activate_response.status_code, 200)

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            watch_subscribers_collection(
                self._request(
                    f"/xyn/api/watches/{watch['id']}/subscribers",
                    method="post",
                    data=json.dumps(
                        {
                            "workspace_id": str(self.workspace.id),
                            "subscriber_type": "external_endpoint",
                            "subscriber_ref": "ops-webhook",
                            "destination": {"url": "https://example.com/hook"},
                        }
                    ),
                ),
                watch["id"],
            )

        evaluate_payload = {
            "workspace_id": str(self.workspace.id),
            "event_key": "parcel_change",
            "event_ref": {"target_kind": "area", "region": "north", "event_type": "change"},
            "persist": True,
            "correlation_id": "corr-watch",
            "chain_id": "chain-watch",
        }
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            evaluate_response = watch_matches_evaluate(
                self._request(
                    "/xyn/api/watches/matches/evaluate",
                    method="post",
                    data=json.dumps(evaluate_payload),
                )
            )
        self.assertEqual(evaluate_response.status_code, 201)
        evaluation = json.loads(evaluate_response.content)
        self.assertEqual(len(evaluation["results"]), 1)
        self.assertTrue(evaluation["results"][0]["matched"])
        self.assertEqual(evaluation["results"][0]["notification_intent"]["action"], "notify_subscribers")

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            list_response = watch_matches_collection(
                self._request(
                    "/xyn/api/watches/matches",
                    data={"workspace_id": str(self.workspace.id), "matched": "true"},
                )
            )
        self.assertEqual(list_response.status_code, 200)
        rows = json.loads(list_response.content)["matches"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["correlation_id"], "corr-watch")

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            pause_response = watch_pause(
                self._request(
                    f"/xyn/api/watches/{watch['id']}/pause",
                    method="post",
                    data=json.dumps({"workspace_id": str(self.workspace.id)}),
                ),
                watch["id"],
            )
        self.assertEqual(pause_response.status_code, 200)
        self.assertEqual(json.loads(pause_response.content)["lifecycle_state"], "paused")

    def test_workspace_isolation_and_campaign_link_validation(self):
        campaign = Campaign.objects.create(
            workspace=self.workspace,
            slug=f"camp-{uuid.uuid4().hex[:6]}",
            name="Watch Campaign",
            campaign_type="generic",
            status="draft",
            created_by=self.identity,
        )
        watch_payload = {
            "workspace_id": str(self.workspace.id),
            "key": "watch-with-campaign",
            "name": "Campaign-linked Watch",
            "linked_campaign_id": str(campaign.id),
        }
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            create_response = watches_collection(
                self._request("/xyn/api/watches", method="post", data=json.dumps(watch_payload))
            )
        self.assertEqual(create_response.status_code, 201)
        watch = json.loads(create_response.content)
        self.assertEqual(watch["linked_campaign_id"], str(campaign.id))

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            forbidden = watch_detail(
                self._request(
                    f"/xyn/api/watches/{watch['id']}",
                    data={"workspace_id": str(self.other_workspace.id)},
                ),
                watch["id"],
            )
        self.assertEqual(forbidden.status_code, 404)

    def test_models_exist(self):
        watch = self._create_watch()
        self.assertEqual(WatchDefinition.objects.filter(workspace=self.workspace).count(), 1)
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            watch_subscribers_collection(
                self._request(
                    f"/xyn/api/watches/{watch['id']}/subscribers",
                    method="post",
                    data=json.dumps(
                        {
                            "workspace_id": str(self.workspace.id),
                            "subscriber_type": "user_identity",
                            "subscriber_ref": str(self.identity.id),
                        }
                    ),
                ),
                watch["id"],
            )
            watch_matches_evaluate(
                self._request(
                    "/xyn/api/watches/matches/evaluate",
                    method="post",
                    data=json.dumps(
                        {
                            "workspace_id": str(self.workspace.id),
                            "watch_ids": [watch["id"]],
                            "event_ref": {"target_kind": "area"},
                        }
                    ),
                )
            )
        self.assertEqual(WatchSubscriber.objects.filter(watch_id=watch["id"]).count(), 1)
        self.assertEqual(WatchMatchEvent.objects.filter(watch_id=watch["id"]).count(), 1)
