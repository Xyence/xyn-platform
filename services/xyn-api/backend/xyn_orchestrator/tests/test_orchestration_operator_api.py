import json
import uuid
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from xyn_orchestrator.models import (
    OrchestrationJobDefinition,
    OrchestrationJobDependency,
    OrchestrationJobRun,
    OrchestrationJobSchedule,
    OrchestrationPipeline,
    OrchestrationRun,
    UserIdentity,
    Workspace,
    WorkspaceMembership,
)
from xyn_orchestrator.orchestration.interfaces import ExecutionScope, RunCreateRequest, RunTrigger
from xyn_orchestrator.orchestration.lifecycle import OrchestrationLifecycleService, OutputRecord
from xyn_orchestrator.xyn_api import (
    orchestration_dependency_graph,
    orchestration_job_definitions_collection,
    orchestration_run_cancel,
    orchestration_run_detail,
    orchestration_run_failure_ack,
    orchestration_run_rerun,
    orchestration_runs_collection,
    orchestration_schedules_collection,
)


class OrchestrationOperatorApiTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        suffix = uuid.uuid4().hex[:8]
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username=f"operator-{suffix}",
            email=f"operator-{suffix}@example.com",
            password="password",
        )
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example",
            subject=f"operator-{suffix}",
            email=f"operator-{suffix}@example.com",
        )
        self.workspace = Workspace.objects.create(name="Ops Workspace", slug=f"ops-{suffix}")
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user_identity=self.identity,
            role="admin",
            termination_authority=True,
        )

        self.pipeline = OrchestrationPipeline.objects.create(
            workspace=self.workspace,
            key="sample_data_sync",
            name="Sample Data Sync",
            max_concurrency=3,
            stale_run_timeout_seconds=1200,
            created_by=self.identity,
        )
        self.job_refresh = OrchestrationJobDefinition.objects.create(
            pipeline=self.pipeline,
            job_key="refresh_source",
            stage_key="source_refresh",
            name="Refresh Source",
            handler_key="platform.jobs.refresh_source",
            retry_max_attempts=3,
            backoff_initial_seconds=10,
            backoff_max_seconds=120,
            backoff_multiplier=2.0,
            runs_per_jurisdiction=True,
            runs_per_source=True,
        )
        self.job_normalize = OrchestrationJobDefinition.objects.create(
            pipeline=self.pipeline,
            job_key="normalize_source",
            stage_key="source_normalization",
            name="Normalize Source",
            handler_key="platform.jobs.normalize_source",
            only_if_upstream_changed=True,
        )
        OrchestrationJobDependency.objects.create(
            pipeline=self.pipeline,
            upstream_job=self.job_refresh,
            downstream_job=self.job_normalize,
        )
        OrchestrationJobSchedule.objects.create(
            job_definition=self.job_refresh,
            schedule_key="hourly",
            schedule_kind="interval",
            interval_seconds=3600,
            enabled=True,
            next_fire_at=timezone.now() + timedelta(minutes=5),
            metadata_json={"jurisdictions": ["tx"], "sources": ["mls"]},
        )
        self.lifecycle = OrchestrationLifecycleService()

    def _request(self, path: str, *, method: str = "get", data=None):
        request = getattr(self.factory, method.lower())(path, data=data or {}, content_type="application/json")
        request.user = self.user
        return request

    def _create_run(self, *, status: str = "pending") -> OrchestrationRun:
        run = self.lifecycle.create_run(
            RunCreateRequest(
                workspace_id=str(self.workspace.id),
                pipeline_key=self.pipeline.key,
                trigger=RunTrigger(trigger_cause="manual", trigger_key="test"),
                initiated_by_id=str(self.identity.id),
                scope=ExecutionScope(jurisdiction="tx", source="mls"),
                metadata={"correlation_id": "corr-1", "chain_id": "chain-1"},
            )
        )
        if status != "pending":
            run.status = status
            run.save(update_fields=["status", "updated_at"])
        return run

    def test_operator_can_list_job_definitions_schedules_and_dependency_graph(self):
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            jobs_response = orchestration_job_definitions_collection(
                self._request(
                    "/xyn/api/orchestration/jobs",
                    data={"workspace_id": str(self.workspace.id), "pipeline_key": self.pipeline.key},
                )
            )
            schedules_response = orchestration_schedules_collection(
                self._request(
                    "/xyn/api/orchestration/schedules",
                    data={"workspace_id": str(self.workspace.id), "pipeline_key": self.pipeline.key},
                )
            )
            graph_response = orchestration_dependency_graph(
                self._request(
                    "/xyn/api/orchestration/dependency-graph",
                    data={"workspace_id": str(self.workspace.id), "pipeline_key": self.pipeline.key},
                )
            )

        jobs_payload = json.loads(jobs_response.content)
        schedules_payload = json.loads(schedules_response.content)
        graph_payload = json.loads(graph_response.content)
        self.assertEqual(jobs_response.status_code, 200)
        self.assertEqual(schedules_response.status_code, 200)
        self.assertEqual(graph_response.status_code, 200)
        self.assertEqual(len(jobs_payload["job_definitions"]), 2)
        self.assertEqual(len(schedules_payload["schedules"]), 1)
        self.assertEqual(schedules_payload["supported_schedule_kinds"], ["manual", "interval"])
        self.assertEqual(schedules_payload["unsupported_schedule_kinds"], ["cron"])
        self.assertTrue(schedules_payload["schedules"][0]["supported_in_v1"])
        self.assertEqual(len(graph_payload["edges"]), 1)
        self.assertEqual(graph_payload["edges"][0]["upstream_job_key"], "refresh_source")

    def test_operator_can_manually_trigger_list_and_filter_runs(self):
        create_payload = {
            "workspace_id": str(self.workspace.id),
            "pipeline_key": self.pipeline.key,
            "jurisdiction": "tx",
            "source": "mls",
            "trigger_key": "manual_operator",
            "metadata": {"correlation_id": "corr-manual", "chain_id": "chain-manual"},
            "parameters": {"force_refresh": "true"},
        }
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            create_response = orchestration_runs_collection(
                self._request("/xyn/api/orchestration/runs", method="post", data=json.dumps(create_payload))
            )
        self.assertEqual(create_response.status_code, 201)
        created = json.loads(create_response.content)
        run_id = created["id"]

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            list_response = orchestration_runs_collection(
                self._request(
                    "/xyn/api/orchestration/runs",
                    data={
                        "workspace_id": str(self.workspace.id),
                        "job_key": "refresh_source",
                        "trigger_cause": "manual",
                        "jurisdiction": "tx",
                        "source": "mls",
                        "correlation_id": "corr-manual",
                        "chain_id": "chain-manual",
                        "created_after": (timezone.now() - timedelta(minutes=5)).isoformat(),
                        "created_before": (timezone.now() + timedelta(minutes=5)).isoformat(),
                    },
                )
            )
        payload = json.loads(list_response.content)
        self.assertEqual(list_response.status_code, 200)
        self.assertTrue(any(item["id"] == run_id for item in payload["runs"]))

    def test_operator_can_inspect_run_detail_with_attempts_outputs_and_dependency_context(self):
        run = self._create_run()
        refresh_job_run = OrchestrationJobRun.objects.get(run=run, job_definition=self.job_refresh)
        normalize_job_run = OrchestrationJobRun.objects.get(run=run, job_definition=self.job_normalize)
        self.lifecycle.mark_job_queued(job_run_id=str(refresh_job_run.id), now=timezone.now())
        self.lifecycle.mark_job_running(job_run_id=str(refresh_job_run.id), now=timezone.now())
        self.lifecycle.mark_job_succeeded(
            job_run_id=str(refresh_job_run.id),
            now=timezone.now(),
            summary="refresh complete",
            metrics={"records": 12},
            outputs=[OutputRecord(output_key="raw_snapshot", output_type="dataset", output_uri="s3://bucket/raw.json", output_change_token="tok-1")],
            output_change_token="tok-1",
        )
        self.lifecycle.mark_job_skipped(job_run_id=str(normalize_job_run.id), reason="upstream_unchanged", summary="no changes")

        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            response = orchestration_run_detail(
                self._request(
                    f"/xyn/api/orchestration/runs/{run.id}",
                    data={"workspace_id": str(self.workspace.id)},
                ),
                str(run.id),
            )
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["id"], str(run.id))
        self.assertIn("dependency_context", payload)
        self.assertEqual(payload["dependency_context"]["normalize_source"], ["refresh_source"])
        refresh_row = next(item for item in payload["jobs"] if item["job_key"] == "refresh_source")
        self.assertEqual(refresh_row["status"], "succeeded")
        self.assertEqual(len(refresh_row["attempts"]), 1)
        self.assertEqual(len(refresh_row["outputs"]), 1)

    def test_operator_can_request_rerun_and_cancel_pending_run(self):
        run = self._create_run(status="queued")
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            rerun_response = orchestration_run_rerun(
                self._request(
                    f"/xyn/api/orchestration/runs/{run.id}/rerun",
                    method="post",
                    data=json.dumps({"workspace_id": str(self.workspace.id)}),
                ),
                str(run.id),
            )
        rerun_payload = json.loads(rerun_response.content)
        self.assertEqual(rerun_response.status_code, 201)
        self.assertEqual(rerun_payload["trigger_cause"], "retry")

        run_to_cancel = self._create_run(status="queued")
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            cancel_response = orchestration_run_cancel(
                self._request(
                    f"/xyn/api/orchestration/runs/{run_to_cancel.id}/cancel",
                    method="post",
                    data=json.dumps({"workspace_id": str(self.workspace.id), "summary": "operator cancel"}),
                ),
                str(run_to_cancel.id),
            )
        cancel_payload = json.loads(cancel_response.content)
        self.assertEqual(cancel_response.status_code, 200)
        self.assertEqual(cancel_payload["status"], "cancelled")

    def test_operator_can_acknowledge_failed_or_stale_runs(self):
        run = self._create_run(status="failed")
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity), mock.patch(
            "xyn_orchestrator.xyn_api._notify_orchestration_failure"
        ) as notify_mock:
            response = orchestration_run_failure_ack(
                self._request(
                    f"/xyn/api/orchestration/runs/{run.id}/ack-failure",
                    method="post",
                    data=json.dumps({"workspace_id": str(self.workspace.id), "note": "investigating"}),
                ),
                str(run.id),
            )
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertIn("operator_ack", payload["metadata"])
        notify_mock.assert_called_once()

    def test_operator_schedule_listing_marks_legacy_cron_rows_unsupported(self):
        OrchestrationJobSchedule.objects.bulk_create(
            [
                OrchestrationJobSchedule(
                    job_definition=self.job_refresh,
                    schedule_key="legacy-cron",
                    schedule_kind="cron",
                    cron_expression="0 * * * *",
                    timezone_name="UTC",
                    enabled=True,
                    next_fire_at=timezone.now() + timedelta(minutes=5),
                )
            ]
        )
        with mock.patch("xyn_orchestrator.xyn_api._require_authenticated", return_value=self.identity):
            schedules_response = orchestration_schedules_collection(
                self._request(
                    "/xyn/api/orchestration/schedules",
                    data={"workspace_id": str(self.workspace.id), "pipeline_key": self.pipeline.key},
                )
            )
        payload = json.loads(schedules_response.content)
        self.assertEqual(schedules_response.status_code, 200)
        cron_row = next(item for item in payload["schedules"] if item["schedule_key"] == "legacy-cron")
        self.assertFalse(cron_row["supported_in_v1"])


if __name__ == "__main__":
    import unittest

    unittest.main()
