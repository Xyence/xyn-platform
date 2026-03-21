import os
import tempfile
import uuid
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from xyn_orchestrator.models import (
    OrchestrationJobDefinition,
    OrchestrationJobDependency,
    OrchestrationJobRun,
    OrchestrationJobRunAttempt,
    OrchestrationJobRunOutput,
    OrchestrationJobSchedule,
    OrchestrationPipeline,
    OrchestrationRun,
    UserIdentity,
    Workspace,
)
from xyn_orchestrator.orchestration.interfaces import ExecutionScope, RunCreateRequest, RunTrigger
from xyn_orchestrator.orchestration.interfaces import OutputRecord
from xyn_orchestrator.orchestration.lifecycle import OrchestrationLifecycleService
from xyn_orchestrator.orchestration.repository import DjangoOrchestrationRepository
from xyn_orchestrator.orchestration.service import JobOrchestrationService


class OrchestrationLifecycleTests(TestCase):
    def setUp(self):
        self._workspace_root = tempfile.TemporaryDirectory()
        self._prior_workspace_root = os.environ.get("XYN_WORKSPACE_ROOT")
        os.environ["XYN_WORKSPACE_ROOT"] = self._workspace_root.name
        self.addCleanup(self._workspace_root.cleanup)
        self.addCleanup(self._restore_workspace_root)
        suffix = uuid.uuid4().hex[:8]
        self.workspace = Workspace.objects.create(slug=f"orch-{suffix}", name="Orchestration Workspace")
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example",
            subject=f"orch-user-{suffix}",
            email=f"orch-{suffix}@example.com",
        )
        self.pipeline = OrchestrationPipeline.objects.create(
            workspace=self.workspace,
            key=f"deal-sync-{suffix}",
            name="Deal Sync",
            stale_run_timeout_seconds=900,
            created_by=self.identity,
        )
        self.job_a = OrchestrationJobDefinition.objects.create(
            pipeline=self.pipeline,
            job_key="source_refresh",
            stage_key="source_refresh",
            name="Source Refresh",
            handler_key="jobs.source.refresh",
            retry_max_attempts=3,
            backoff_initial_seconds=10,
            backoff_max_seconds=120,
            backoff_multiplier=2.0,
            runs_per_jurisdiction=True,
            runs_per_source=True,
        )
        self.job_b = OrchestrationJobDefinition.objects.create(
            pipeline=self.pipeline,
            job_key="source_normalization",
            stage_key="source_normalization",
            name="Source Normalization",
            handler_key="jobs.source.normalize",
            retry_max_attempts=2,
            only_if_upstream_changed=True,
        )
        OrchestrationJobDependency.objects.create(pipeline=self.pipeline, upstream_job=self.job_a, downstream_job=self.job_b)
        OrchestrationJobSchedule.objects.create(
            job_definition=self.job_a,
            schedule_key="hourly",
            schedule_kind="interval",
            interval_seconds=3600,
            timezone_name="UTC",
            enabled=True,
            next_fire_at=timezone.now() + timedelta(hours=1),
        )
        self.repository = DjangoOrchestrationRepository()
        self.lifecycle = OrchestrationLifecycleService(repository=self.repository)

    def _restore_workspace_root(self) -> None:
        if self._prior_workspace_root is None:
            os.environ.pop("XYN_WORKSPACE_ROOT", None)
        else:
            os.environ["XYN_WORKSPACE_ROOT"] = self._prior_workspace_root

    def _create_run(self) -> OrchestrationRun:
        return self.lifecycle.create_run(
            RunCreateRequest(
                workspace_id=str(self.workspace.id),
                pipeline_key=self.pipeline.key,
                trigger=RunTrigger(trigger_cause="manual", trigger_key="test"),
                run_type="ingest.import",
                target_ref={"target_type": "source", "target_id": "mls:tx-travis-county"},
                initiated_by_id=str(self.identity.id),
                scope=ExecutionScope(jurisdiction="tx-travis-county", source="mls"),
                metadata={
                    "correlation_id": "corr-1",
                    "chain_id": "chain-1",
                    "idempotency_key": f"idem-{uuid.uuid4().hex[:8]}",
                    "dedupe_key": "deal-sync:tx:mls",
                },
            )
        )

    def test_create_run_persists_partition_trigger_and_job_rows(self):
        run = self._create_run()
        self.assertEqual(run.trigger_cause, "manual")
        self.assertEqual(run.scope_jurisdiction, "tx-travis-county")
        self.assertEqual(run.scope_source, "mls")
        self.assertEqual(run.run_type, "ingest.import")
        self.assertEqual(run.target_ref_json, {"target_type": "source", "target_id": "mls:tx-travis-county"})
        self.assertEqual(run.correlation_id, "corr-1")
        self.assertEqual(run.chain_id, "chain-1")
        self.assertIn("ingest_workspace", run.metadata_json)
        ingest_meta = run.metadata_json.get("ingest_workspace")
        self.assertEqual(ingest_meta.get("source_key"), "mls")
        self.assertEqual(ingest_meta.get("run_key"), str(run.id))
        self.assertEqual(ingest_meta.get("retention_class"), "ephemeral")

        job_rows = list(OrchestrationJobRun.objects.filter(run=run).order_by("job_definition__job_key"))
        self.assertEqual(len(job_rows), 2)
        self.assertEqual({row.status for row in job_rows}, {"pending"})
        self.assertEqual({row.scope_jurisdiction for row in job_rows}, {"tx-travis-county"})
        self.assertEqual({row.scope_source for row in job_rows}, {"mls"})

    def test_invalid_jurisdiction_is_rejected(self):
        with self.assertRaises(ValueError):
            self.lifecycle.create_run(
                RunCreateRequest(
                    workspace_id=str(self.workspace.id),
                    pipeline_key=self.pipeline.key,
                    trigger=RunTrigger(trigger_cause="manual", trigger_key="test"),
                    run_type="ingest.import",
                    target_ref={"target_type": "source", "target_id": "mls:tx-travis-county"},
                    initiated_by_id=str(self.identity.id),
                    scope=ExecutionScope(jurisdiction="tx", source="mls"),
                    metadata={
                        "correlation_id": "corr-2",
                        "chain_id": "chain-2",
                        "idempotency_key": f"idem-{uuid.uuid4().hex[:8]}",
                        "dedupe_key": "deal-sync:tx:mls",
                    },
                )
            )

        filtered = OrchestrationJobRun.objects.filter(
            workspace=self.workspace,
            job_definition=self.job_a,
            status="pending",
            scope_jurisdiction="tx-travis-county",
            scope_source="mls",
            correlation_id="corr-1",
            chain_id="chain-1",
        )
        self.assertEqual(filtered.count(), 0)

    def test_non_ingest_run_does_not_stamp_workspace_metadata(self):
        run = self.lifecycle.create_run(
            RunCreateRequest(
                workspace_id=str(self.workspace.id),
                pipeline_key=self.pipeline.key,
                trigger=RunTrigger(trigger_cause="manual", trigger_key="test"),
                run_type="analysis.debug",
                target_ref={"target_type": "goal", "target_id": "test"},
                initiated_by_id=str(self.identity.id),
                scope=ExecutionScope(jurisdiction="", source=""),
                metadata={
                    "correlation_id": "corr-2",
                },
            )
        )
        self.assertNotIn("ingest_workspace", run.metadata_json)

    def test_illegal_transition_is_rejected(self):
        run = self._create_run()
        job_run = OrchestrationJobRun.objects.filter(run=run, job_definition=self.job_a).first()
        self.assertIsNotNone(job_run)
        with self.assertRaises(ValueError):
            self.lifecycle.mark_job_succeeded(job_run_id=str(job_run.id), summary="should fail")

    def test_running_success_and_output_persistence(self):
        run = self._create_run()
        job_a_run = OrchestrationJobRun.objects.get(run=run, job_definition=self.job_a)
        job_b_run = OrchestrationJobRun.objects.get(run=run, job_definition=self.job_b)

        self.lifecycle.mark_job_queued(job_run_id=str(job_a_run.id), summary="queued")
        self.lifecycle.mark_job_running(job_run_id=str(job_a_run.id), summary="running")
        self.lifecycle.mark_job_succeeded(
            job_run_id=str(job_a_run.id),
            summary="completed refresh",
            metrics={"records": 42, "duration_ms": 1200},
            outputs=[
                OutputRecord(
                    output_key="refresh_snapshot",
                    output_type="dataset",
                    output_uri="s3://bucket/snapshot.json",
                    output_change_token="tok-1",
                    payload={"rows": 42},
                )
            ],
            output_change_token="tok-1",
        )
        self.lifecycle.mark_job_skipped(job_run_id=str(job_b_run.id), reason="no upstream change", summary="skip normalize")

        job_a_run.refresh_from_db()
        job_b_run.refresh_from_db()
        run.refresh_from_db()

        self.assertEqual(job_a_run.status, "succeeded")
        self.assertEqual(job_b_run.status, "skipped")
        self.assertEqual(run.status, "succeeded")

        attempts = OrchestrationJobRunAttempt.objects.filter(job_run=job_a_run)
        self.assertEqual(attempts.count(), 1)
        self.assertEqual(attempts.first().status, "succeeded")

        outputs = OrchestrationJobRunOutput.objects.filter(job_run=job_a_run)
        self.assertEqual(outputs.count(), 1)
        self.assertEqual(outputs.first().output_key, "refresh_snapshot")
        self.assertEqual(outputs.first().output_change_token, "tok-1")

    def test_failed_retry_transitions_to_waiting_retry(self):
        run = self._create_run()
        job_run = OrchestrationJobRun.objects.get(run=run, job_definition=self.job_a)

        self.lifecycle.mark_job_queued(job_run_id=str(job_run.id))
        self.lifecycle.mark_job_running(job_run_id=str(job_run.id))
        self.lifecycle.mark_job_failed(
            job_run_id=str(job_run.id),
            summary="temporary error",
            error_text="upstream timeout",
            error_details={"code": "timeout"},
            retryable=True,
        )

        job_run.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(job_run.status, "waiting_retry")
        self.assertIsNotNone(job_run.next_attempt_at)
        self.assertEqual(run.status, "queued")

    def test_attempt_count_increments_for_each_retry_attempt(self):
        run = self._create_run()
        job_run = OrchestrationJobRun.objects.get(run=run, job_definition=self.job_a)

        self.lifecycle.mark_job_queued(job_run_id=str(job_run.id))
        self.lifecycle.mark_job_running(job_run_id=str(job_run.id))
        self.lifecycle.mark_job_failed(
            job_run_id=str(job_run.id),
            summary="temporary error",
            error_text="upstream timeout",
            retryable=True,
        )
        job_run.refresh_from_db()
        self.assertEqual(job_run.attempt_count, 1)
        self.assertEqual(job_run.status, "waiting_retry")

        self.lifecycle.mark_job_running(job_run_id=str(job_run.id))
        self.lifecycle.mark_job_failed(
            job_run_id=str(job_run.id),
            summary="second error",
            error_text="another timeout",
            retryable=False,
        )
        job_run.refresh_from_db()
        self.assertEqual(job_run.attempt_count, 2)
        self.assertEqual(job_run.status, "failed")

    def test_request_rerun_creates_correlated_child_run(self):
        original = self._create_run()
        rerun = self.lifecycle.request_rerun(run_id=str(original.id), requested_by_id=str(self.identity.id))

        self.assertEqual(rerun.rerun_of_id, original.id)
        self.assertEqual(rerun.trigger_cause, "retry")
        self.assertEqual(rerun.scope_jurisdiction, original.scope_jurisdiction)
        self.assertEqual(rerun.scope_source, original.scope_source)
        self.assertTrue(str(rerun.chain_id or "").strip())
        self.assertEqual(OrchestrationJobRun.objects.filter(run=rerun).count(), 2)

    def test_model_rejects_cron_schedule_kind_in_v1(self):
        with self.assertRaises(ValidationError):
            OrchestrationJobSchedule.objects.create(
                job_definition=self.job_a,
                schedule_key="legacy-cron",
                schedule_kind="cron",
                cron_expression="0 * * * *",
                timezone_name="UTC",
                enabled=True,
                next_fire_at=timezone.now() + timedelta(hours=1),
            )

    def test_service_layer_rejects_legacy_cron_rows_loudly(self):
        # Emulate legacy persisted data created before v1 schedule constraints.
        OrchestrationJobSchedule.objects.bulk_create(
            [
                OrchestrationJobSchedule(
                    job_definition=self.job_a,
                    schedule_key="legacy-cron",
                    schedule_kind="cron",
                    cron_expression="0 * * * *",
                    timezone_name="UTC",
                    enabled=True,
                    next_fire_at=timezone.now() + timedelta(minutes=5),
                )
            ]
        )
        service = JobOrchestrationService(repository=self.repository)
        with self.assertRaisesRegex(ValueError, "intentionally unsupported"):
            service.create_run(
                RunCreateRequest(
                    workspace_id=str(self.workspace.id),
                    pipeline_key=self.pipeline.key,
                    trigger=RunTrigger(trigger_cause="manual", trigger_key="test"),
                    initiated_by_id=str(self.identity.id),
                    scope=ExecutionScope(jurisdiction="tx-travis-county", source="mls"),
                    metadata={"correlation_id": "corr-2", "chain_id": "chain-2"},
                )
            )
