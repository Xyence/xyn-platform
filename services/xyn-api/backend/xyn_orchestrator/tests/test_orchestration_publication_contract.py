import uuid

from django.test import TestCase

from xyn_orchestrator.models import (
    OrchestrationJobDefinition,
    OrchestrationJobDependency,
    OrchestrationJobRun,
    OrchestrationPipeline,
    OrchestrationStagePublication,
    PlatformDomainEvent,
    ReconciledStateCurrentPointer,
    UserIdentity,
    Workspace,
)
from xyn_orchestrator.orchestration.definitions import (
    STAGE_NOTIFICATION_EMISSION,
    STAGE_PROPERTY_GRAPH_REBUILD,
    STAGE_RULE_EVALUATION,
    STAGE_SIGNAL_MATCHING,
    STAGE_SOURCE_NORMALIZATION,
)
from xyn_orchestrator.orchestration.domain_events import (
    DomainEventInput,
    DomainEventQuery,
    DomainEventService,
    EVENT_EVALUATION_READY,
    EVENT_RECONCILED_STATE_PUBLISHED,
    EVENT_SIGNAL_SET_PUBLISHED,
    EVENT_SOURCE_NORMALIZED,
)
from xyn_orchestrator.orchestration.engine import DependencyResolver
from xyn_orchestrator.orchestration.interfaces import ExecutionScope, RunCreateRequest, RunTrigger
from xyn_orchestrator.orchestration.interfaces import OutputRecord
from xyn_orchestrator.orchestration.lifecycle import OrchestrationLifecycleService
from xyn_orchestrator.orchestration.publication import StagePublicationService


class OrchestrationPublicationContractTests(TestCase):
    def setUp(self):
        suffix = uuid.uuid4().hex[:8]
        self.workspace = Workspace.objects.create(slug=f"stage-{suffix}", name="Stage Workspace")
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example",
            subject=f"stage-user-{suffix}",
            email=f"stage-{suffix}@example.com",
        )
        self.pipeline = OrchestrationPipeline.objects.create(
            workspace=self.workspace,
            key=f"pub-pipeline-{suffix}",
            name="Publication Contract Pipeline",
            created_by=self.identity,
        )
        self.normalize_job = OrchestrationJobDefinition.objects.create(
            pipeline=self.pipeline,
            job_key="normalize_source",
            stage_key=STAGE_SOURCE_NORMALIZATION,
            name="Normalize",
            handler_key="handler.normalize",
        )
        self.rebuild_job = OrchestrationJobDefinition.objects.create(
            pipeline=self.pipeline,
            job_key="rebuild_entities",
            stage_key=STAGE_PROPERTY_GRAPH_REBUILD,
            name="Rebuild",
            handler_key="handler.rebuild",
        )
        self.signal_job = OrchestrationJobDefinition.objects.create(
            pipeline=self.pipeline,
            job_key="match_signals",
            stage_key=STAGE_SIGNAL_MATCHING,
            name="Signals",
            handler_key="handler.signals",
        )
        self.eval_job = OrchestrationJobDefinition.objects.create(
            pipeline=self.pipeline,
            job_key="evaluate_rules",
            stage_key=STAGE_RULE_EVALUATION,
            name="Evaluate",
            handler_key="handler.evaluate",
        )
        self.notify_job = OrchestrationJobDefinition.objects.create(
            pipeline=self.pipeline,
            job_key="emit_notifications",
            stage_key=STAGE_NOTIFICATION_EMISSION,
            name="Notify",
            handler_key="handler.notify",
        )
        OrchestrationJobDependency.objects.create(
            pipeline=self.pipeline,
            upstream_job=self.signal_job,
            downstream_job=self.eval_job,
        )
        OrchestrationJobDependency.objects.create(
            pipeline=self.pipeline,
            upstream_job=self.eval_job,
            downstream_job=self.notify_job,
        )
        self.lifecycle = OrchestrationLifecycleService()
        self.publication = StagePublicationService()
        self.domain_events = DomainEventService()

    def _new_run(self, *, jurisdiction: str = "tx-travis-county", source: str = "mls"):
        return self.lifecycle.create_run(
            RunCreateRequest(
                workspace_id=str(self.workspace.id),
                pipeline_key=self.pipeline.key,
                trigger=RunTrigger(trigger_cause="manual", trigger_key="test"),
                initiated_by_id=str(self.identity.id),
                scope=ExecutionScope(jurisdiction=jurisdiction, source=source),
            )
        )

    def _succeed_job(
        self,
        *,
        run_id: str,
        job: OrchestrationJobDefinition,
        output_change_token: str = "",
        outputs: list[OutputRecord] | None = None,
    ):
        job_run = OrchestrationJobRun.objects.get(run_id=run_id, job_definition=job)
        self.lifecycle.mark_job_running(job_run_id=str(job_run.id), summary="running")
        self.lifecycle.mark_job_succeeded(
            job_run_id=str(job_run.id),
            summary="done",
            output_change_token=output_change_token,
            outputs=outputs,
        )
        return OrchestrationJobRun.objects.get(id=job_run.id)

    def test_normalization_stage_does_not_mark_evaluation_ready(self):
        run = self._new_run()
        self._succeed_job(run_id=str(run.id), job=self.normalize_job, output_change_token="norm-v1")
        readiness = self.publication.evaluation_readiness(
            workspace_id=str(self.workspace.id),
            pipeline_id=str(self.pipeline.id),
            jurisdiction="tx-travis-county",
            source="mls",
        )
        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.reason, "reconciled_state_not_published")
        self.assertEqual(
            PlatformDomainEvent.objects.filter(
                workspace=self.workspace,
                event_type=EVENT_SOURCE_NORMALIZED,
                scope_jurisdiction="tx-travis-county",
                scope_source="mls",
            ).count(),
            1,
        )
        self.assertFalse(
            PlatformDomainEvent.objects.filter(
                workspace=self.workspace,
                event_type=EVENT_EVALUATION_READY,
                scope_jurisdiction="tx-travis-county",
                scope_source="mls",
            ).exists()
        )

    def test_rebuild_stage_marks_reconciled_publication_ready(self):
        run = self._new_run()
        self._succeed_job(run_id=str(run.id), job=self.rebuild_job, output_change_token="recon-v1")
        readiness = self.publication.evaluation_readiness(
            workspace_id=str(self.workspace.id),
            pipeline_id=str(self.pipeline.id),
            jurisdiction="tx-travis-county",
            source="mls",
        )
        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.reconciled_state_version, "recon-v1")

    def test_current_pointer_created_on_first_publish(self):
        run = self._new_run()
        self._succeed_job(run_id=str(run.id), job=self.rebuild_job, output_change_token="recon-v1")
        pointer = ReconciledStateCurrentPointer.objects.get(
            workspace=self.workspace,
            pipeline=self.pipeline,
            scope_jurisdiction="tx-travis-county",
            scope_source="mls",
        )
        self.assertEqual(pointer.reconciled_state_version, "recon-v1")
        self.assertIsNotNone(pointer.publication_id)

    def test_current_pointer_updates_on_new_publish(self):
        run1 = self._new_run()
        self._succeed_job(run_id=str(run1.id), job=self.rebuild_job, output_change_token="recon-v1")
        run2 = self._new_run()
        self._succeed_job(run_id=str(run2.id), job=self.rebuild_job, output_change_token="recon-v2")
        pointer = ReconciledStateCurrentPointer.objects.get(
            workspace=self.workspace,
            pipeline=self.pipeline,
            scope_jurisdiction="tx-travis-county",
            scope_source="mls",
        )
        self.assertEqual(pointer.reconciled_state_version, "recon-v2")
        self.assertEqual(
            OrchestrationJobRun.objects.filter(job_definition=self.rebuild_job).count(),
            2,
        )
        self.assertEqual(
            OrchestrationStagePublication.objects.filter(
                workspace=self.workspace,
                pipeline=self.pipeline,
                stage_key=STAGE_PROPERTY_GRAPH_REBUILD,
            ).count(),
            2,
        )
        self.assertEqual(
            pointer.publication.reconciled_state_version,
            "recon-v2",
        )

    def test_promotion_requires_existing_publication(self):
        with self.assertRaises(ValueError):
            self.publication.promote_reconciled_state_version(
                workspace_id=str(self.workspace.id),
                pipeline_id=str(self.pipeline.id),
                jurisdiction="tx-travis-county",
                source="mls",
                reconciled_state_version="missing-v1",
            )

    def test_readiness_requires_current_pointer(self):
        run = self._new_run()
        self._succeed_job(run_id=str(run.id), job=self.rebuild_job, output_change_token="recon-v1")
        ReconciledStateCurrentPointer.objects.filter(
            workspace=self.workspace,
            pipeline=self.pipeline,
            scope_jurisdiction="tx-travis-county",
            scope_source="mls",
        ).delete()
        readiness = self.publication.evaluation_readiness(
            workspace_id=str(self.workspace.id),
            pipeline_id=str(self.pipeline.id),
            jurisdiction="tx-travis-county",
            source="mls",
        )
        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.reason, "reconciled_state_not_published")

    def test_signal_publication_links_to_latest_reconciled_state_version(self):
        run = self._new_run()
        self._succeed_job(run_id=str(run.id), job=self.rebuild_job, output_change_token="recon-v2")
        self._succeed_job(run_id=str(run.id), job=self.signal_job, output_change_token="signal-v2")
        signal_publication = self.publication.latest_reconciled_publication(
            workspace_id=str(self.workspace.id),
            pipeline_id=str(self.pipeline.id),
            jurisdiction="tx-travis-county",
            source="mls",
        )
        self.assertIsNotNone(signal_publication)
        signal_stage = OrchestrationJobRun.objects.get(run_id=run.id, job_definition=self.signal_job).stage_publication
        self.assertEqual(signal_stage.signal_set_version, "signal-v2")
        self.assertEqual(signal_stage.reconciled_state_version, "recon-v2")
        signal_events = self.domain_events.list_events(
            DomainEventQuery(
                workspace_id=str(self.workspace.id),
                event_type=EVENT_SIGNAL_SET_PUBLISHED,
                jurisdiction="tx-travis-county",
                source="mls",
                signal_set_version="signal-v2",
            )
        )
        self.assertEqual(signal_events.count(), 1)

    def test_readiness_is_partition_aware(self):
        run = self._new_run(jurisdiction="tx-travis-county", source="mls")
        self._succeed_job(run_id=str(run.id), job=self.rebuild_job, output_change_token="recon-tx-mls")
        tx_ready = self.publication.evaluation_readiness(
            workspace_id=str(self.workspace.id),
            pipeline_id=str(self.pipeline.id),
            jurisdiction="tx-travis-county",
            source="mls",
        )
        county_ready = self.publication.evaluation_readiness(
            workspace_id=str(self.workspace.id),
            pipeline_id=str(self.pipeline.id),
            jurisdiction="tx-travis-county",
            source="county",
        )
        self.assertTrue(tx_ready.ready)
        self.assertFalse(county_ready.ready)

    def test_rule_evaluation_is_skipped_until_reconciled_publication_exists(self):
        run = self._new_run()
        self._succeed_job(run_id=str(run.id), job=self.signal_job, output_change_token="signal-without-recon")
        queued = DependencyResolver(lifecycle=self.lifecycle).queue_ready_jobs(run=run)
        self.assertIsInstance(queued, list)
        eval_job_run = OrchestrationJobRun.objects.get(run=run, job_definition=self.eval_job)
        self.assertEqual(eval_job_run.status, "skipped")
        self.assertEqual(eval_job_run.skipped_reason, "reconciled_state_not_published")

        prior_run = self._new_run()
        self._succeed_job(run_id=str(prior_run.id), job=self.rebuild_job, output_change_token="recon-ready")

        retry_run = self._new_run()
        self._succeed_job(run_id=str(retry_run.id), job=self.signal_job, output_change_token="signal-after-recon")
        queued_retry = DependencyResolver(lifecycle=self.lifecycle).queue_ready_jobs(run=retry_run)
        eval_retry = OrchestrationJobRun.objects.get(run=retry_run, job_definition=self.eval_job)
        self.assertIn(str(eval_retry.id), queued_retry)

    def test_reconciled_publication_event_emission_is_replay_safe_by_version(self):
        first_run = self._new_run()
        self._succeed_job(run_id=str(first_run.id), job=self.rebuild_job, output_change_token="recon-v9")
        replay_run = self._new_run()
        self._succeed_job(run_id=str(replay_run.id), job=self.rebuild_job, output_change_token="recon-v9")

        self.assertEqual(
            PlatformDomainEvent.objects.filter(
                workspace=self.workspace,
                event_type=EVENT_RECONCILED_STATE_PUBLISHED,
                scope_jurisdiction="tx-travis-county",
                scope_source="mls",
                reconciled_state_version="recon-v9",
            ).count(),
            1,
        )
        self.assertEqual(
            PlatformDomainEvent.objects.filter(
                workspace=self.workspace,
                event_type=EVENT_EVALUATION_READY,
                scope_jurisdiction="tx-travis-county",
                scope_source="mls",
                reconciled_state_version="recon-v9",
            ).count(),
            1,
        )

    def test_domain_event_record_is_idempotent_by_workspace_and_key(self):
        payload = DomainEventInput(
            workspace_id=str(self.workspace.id),
            event_type="test.domain_event",
            idempotency_key="unit-test-key",
            stage_key=STAGE_SOURCE_NORMALIZATION,
            scope_jurisdiction="tx-travis-county",
            scope_source="mls",
            payload={"marker": "v1"},
        )
        created = self.domain_events.record(payload)
        replayed = self.domain_events.record(payload)

        self.assertEqual(created.id, replayed.id)
        self.assertEqual(
            PlatformDomainEvent.objects.filter(
                workspace=self.workspace,
                event_type="test.domain_event",
                idempotency_key="unit-test-key",
            ).count(),
            1,
        )

    def test_rule_evaluation_requires_reconciled_version_referenced_by_signal_publication(self):
        run = self._new_run()
        self._succeed_job(run_id=str(run.id), job=self.rebuild_job, output_change_token="recon-v7")

        signal_job_run = OrchestrationJobRun.objects.get(run=run, job_definition=self.signal_job)
        self.lifecycle.mark_job_running(job_run_id=str(signal_job_run.id), summary="running")
        self.lifecycle.mark_job_succeeded(
            job_run_id=str(signal_job_run.id),
            summary="done",
            output_change_token="signal-v7",
            outputs=[
                OutputRecord(
                    output_key="signal_matches",
                    output_type="signal_matches",
                    output_change_token="signal-v7",
                    payload={
                        "reconciled_state_version": "recon-v-missing",
                        "signal_set_version": "signal-v7",
                    },
                )
            ],
        )

        queued = DependencyResolver(lifecycle=self.lifecycle).queue_ready_jobs(run=run)
        eval_job_run = OrchestrationJobRun.objects.get(run=run, job_definition=self.eval_job)
        self.assertNotIn(str(eval_job_run.id), queued)
        self.assertEqual(eval_job_run.status, "skipped")
        self.assertEqual(eval_job_run.skipped_reason, "reconciled_state_version_not_published")

    def test_notification_stage_requires_stage_e_outputs(self):
        run = self._new_run()
        self._succeed_job(run_id=str(run.id), job=self.rebuild_job, output_change_token="recon-v8")
        self._succeed_job(run_id=str(run.id), job=self.signal_job, output_change_token="signal-v8")
        self._succeed_job(run_id=str(run.id), job=self.eval_job, output_change_token="eval-v8")

        queued = DependencyResolver(lifecycle=self.lifecycle).queue_ready_jobs(run=run)
        notify_job_run = OrchestrationJobRun.objects.get(run=run, job_definition=self.notify_job)
        self.assertNotIn(str(notify_job_run.id), queued)
        self.assertEqual(notify_job_run.status, "skipped")
        self.assertEqual(notify_job_run.skipped_reason, "evaluation_output_missing")

        run_with_output = self._new_run()
        self._succeed_job(run_id=str(run_with_output.id), job=self.rebuild_job, output_change_token="recon-v8b")
        self._succeed_job(run_id=str(run_with_output.id), job=self.signal_job, output_change_token="signal-v8b")
        self._succeed_job(
            run_id=str(run_with_output.id),
            job=self.eval_job,
            output_change_token="eval-v8b",
            outputs=[
                OutputRecord(
                    output_key="rule_evaluation_summary",
                    output_type="rule_summary",
                    output_change_token="eval-v8b",
                    payload={"evaluated": 3},
                )
            ],
        )
        queued_after = DependencyResolver(lifecycle=self.lifecycle).queue_ready_jobs(run=run_with_output)
        notify_after = OrchestrationJobRun.objects.get(run=run_with_output, job_definition=self.notify_job)
        self.assertIn(str(notify_after.id), queued_after)
