import json
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from xyn_orchestrator.models import (
    Campaign,
    OrchestrationJobDefinition,
    OrchestrationPipeline,
    OrchestrationRun,
    WatchDefinition,
    WatchMatchEvent,
    WatchSubscriber,
    UserIdentity,
    Workspace,
    WorkspaceMembership,
)
from xyn_orchestrator.orchestration.definitions import STAGE_PROPERTY_GRAPH_REBUILD
from xyn_orchestrator.orchestration.interfaces import ExecutionScope, RunCreateRequest, RunTrigger
from xyn_orchestrator.orchestration.lifecycle import OrchestrationLifecycleService
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
        self.lifecycle = OrchestrationLifecycleService()

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

    def _publish_reconciled_state(
        self,
        *,
        jurisdiction: str = "",
        source: str = "",
        pipeline_key: str = "",
        reconciled_state_version: str = "reconciled-v1",
    ) -> str:
        resolved_pipeline_key = pipeline_key or f"watch-eval-{uuid.uuid4().hex[:6]}"
        pipeline = OrchestrationPipeline.objects.create(
            workspace=self.workspace,
            key=resolved_pipeline_key,
            name="Watch Evaluation Pipeline",
            created_by=self.identity,
        )
        rebuild = OrchestrationJobDefinition.objects.create(
            pipeline=pipeline,
            job_key="rebuild_entities",
            stage_key=STAGE_PROPERTY_GRAPH_REBUILD,
            name="Rebuild Entities",
            handler_key="handler.rebuild",
        )
        run = self.lifecycle.create_run(
            RunCreateRequest(
                workspace_id=str(self.workspace.id),
                pipeline_key=pipeline.key,
                trigger=RunTrigger(trigger_cause="manual", trigger_key="test"),
                initiated_by_id=str(self.identity.id),
                scope=ExecutionScope(jurisdiction=jurisdiction, source=source),
            )
        )
        rebuild_run = OrchestrationRun.objects.get(id=run.id).job_runs.get(job_definition=rebuild)
        self.lifecycle.mark_job_running(job_run_id=str(rebuild_run.id), summary="running")
        self.lifecycle.mark_job_succeeded(
            job_run_id=str(rebuild_run.id),
            summary="published",
            output_change_token=reconciled_state_version,
        )
        return pipeline.key

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
        self._publish_reconciled_state()
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

    def test_evaluate_replay_with_idempotency_key_dedupes_match_events(self):
        watch = self._create_watch(lifecycle_state="active")
        self._publish_reconciled_state()
        evaluate_payload = {
            "workspace_id": str(self.workspace.id),
            "event_key": "parcel_change",
            "event_ref": {"target_kind": "area", "region": "north", "event_type": "change"},
            "persist": True,
            "idempotency_key": "watch-eval-idem-1",
        }
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            first = watch_matches_evaluate(
                self._request(
                    "/xyn/api/watches/matches/evaluate",
                    method="post",
                    data=json.dumps(evaluate_payload),
                )
            )
            second = watch_matches_evaluate(
                self._request(
                    "/xyn/api/watches/matches/evaluate",
                    method="post",
                    data=json.dumps(evaluate_payload),
                )
            )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(WatchMatchEvent.objects.filter(workspace=self.workspace).count(), 1)

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
        self._publish_reconciled_state()
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

    def test_evaluate_requires_reconciled_publication_boundary(self):
        watch = self._create_watch(lifecycle_state="active")
        payload = {
            "workspace_id": str(self.workspace.id),
            "watch_ids": [watch["id"]],
            "event_ref": {"target_kind": "area"},
            "persist": True,
        }
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            before = watch_matches_evaluate(
                self._request(
                    "/xyn/api/watches/matches/evaluate",
                    method="post",
                    data=json.dumps(payload),
                )
            )
        self.assertEqual(before.status_code, 409)

        pipeline_key = self._publish_reconciled_state(jurisdiction="tx", source="mls", reconciled_state_version="recon-allow")
        payload_with_partition = {
            **payload,
            "pipeline_key": pipeline_key,
            "jurisdiction": "tx",
            "source": "mls",
        }
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            after = watch_matches_evaluate(
                self._request(
                    "/xyn/api/watches/matches/evaluate",
                    method="post",
                    data=json.dumps(payload_with_partition),
                )
            )
        self.assertEqual(after.status_code, 201)

    def test_evaluate_rejects_when_requested_reconciled_version_is_not_published(self):
        watch = self._create_watch(lifecycle_state="active")
        pipeline_key = self._publish_reconciled_state(
            jurisdiction="tx",
            source="mls",
            reconciled_state_version="recon-published",
        )
        payload = {
            "workspace_id": str(self.workspace.id),
            "watch_ids": [watch["id"]],
            "pipeline_key": pipeline_key,
            "jurisdiction": "tx",
            "source": "mls",
            "reconciled_state_version": "recon-missing",
            "event_ref": {"target_kind": "area", "reconciled_state_version": "recon-missing"},
            "persist": True,
        }
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = watch_matches_evaluate(
                self._request(
                    "/xyn/api/watches/matches/evaluate",
                    method="post",
                    data=json.dumps(payload),
                )
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(WatchMatchEvent.objects.filter(workspace=self.workspace).count(), 0)
