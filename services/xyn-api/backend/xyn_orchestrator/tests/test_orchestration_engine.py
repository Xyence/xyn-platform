import uuid
from datetime import timedelta

from django.test import TestCase
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
)
from xyn_orchestrator.orchestration.engine import (
    ConcurrencyGuard,
    DependencyResolver,
    DueJobScanner,
    OrchestrationEngine,
    RunDispatcher,
    RunPlanner,
    StaleRunDetector,
)
from xyn_orchestrator.orchestration.interfaces import JobExecutionResult
from xyn_orchestrator.orchestration.lifecycle import OrchestrationLifecycleService
from xyn_orchestrator.orchestration.repository import DjangoOrchestrationRepository


class _StaticExecutor:
    def __init__(self, result: JobExecutionResult):
        self._result = result

    def execute(self, context):
        return self._result


class _FailThenSucceedExecutor:
    def __init__(self):
        self.calls = 0

    def execute(self, context):
        self.calls += 1
        if self.calls == 1:
            return JobExecutionResult(status="failed", summary="transient", error_text="boom", retryable=True)
        return JobExecutionResult(status="succeeded", summary="ok", output_payload={"metrics": {"records": 1}}, output_change_token="tok-2")


class OrchestrationEngineTests(TestCase):
    def setUp(self):
        suffix = uuid.uuid4().hex[:8]
        self.workspace = Workspace.objects.create(slug=f"eng-{suffix}", name="Engine Workspace")
        self.identity = UserIdentity.objects.create(
            provider="oidc",
            issuer="https://issuer.example",
            subject=f"eng-user-{suffix}",
            email=f"eng-{suffix}@example.com",
        )
        self.pipeline = OrchestrationPipeline.objects.create(
            workspace=self.workspace,
            key=f"pipeline-{suffix}",
            name="Pipeline",
            max_concurrency=2,
            stale_run_timeout_seconds=120,
            created_by=self.identity,
        )
        self.job_a = OrchestrationJobDefinition.objects.create(
            pipeline=self.pipeline,
            job_key="a_refresh",
            stage_key="source_refresh",
            name="A",
            handler_key="handler.a",
            retry_max_attempts=3,
            backoff_initial_seconds=5,
            backoff_max_seconds=30,
            backoff_multiplier=2.0,
            runs_per_jurisdiction=True,
            runs_per_source=True,
        )
        self.job_b = OrchestrationJobDefinition.objects.create(
            pipeline=self.pipeline,
            job_key="b_normalize",
            stage_key="source_normalization",
            name="B",
            handler_key="handler.b",
            only_if_upstream_changed=False,
        )
        OrchestrationJobDependency.objects.create(pipeline=self.pipeline, upstream_job=self.job_a, downstream_job=self.job_b)

        self.repository = DjangoOrchestrationRepository()
        self.lifecycle = OrchestrationLifecycleService(repository=self.repository)

    def _create_manual_run(self) -> OrchestrationRun:
        from xyn_orchestrator.orchestration.interfaces import ExecutionScope, RunCreateRequest, RunTrigger

        return self.lifecycle.create_run(
            RunCreateRequest(
                workspace_id=str(self.workspace.id),
                pipeline_key=self.pipeline.key,
                trigger=RunTrigger(trigger_cause="manual", trigger_key="test"),
                initiated_by_id=str(self.identity.id),
                scope=ExecutionScope(jurisdiction="tx", source="mls"),
                metadata={"correlation_id": "corr-engine", "chain_id": "chain-engine"},
            )
        )

    def test_due_schedule_polling_and_partitioned_run_creation(self):
        now = timezone.now()
        schedule = OrchestrationJobSchedule.objects.create(
            job_definition=self.job_a,
            schedule_key="interval-sync",
            schedule_kind="interval",
            interval_seconds=300,
            next_fire_at=now - timedelta(seconds=5),
            metadata_json={"jurisdictions": ["tx"], "sources": ["mls", "county"]},
        )
        scanner = DueJobScanner()
        due = scanner.scan_due_schedules(now=now)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0].schedule_id, str(schedule.id))

        planner = RunPlanner(lifecycle=self.lifecycle, repository=self.repository)
        runs = planner.create_runs_for_due_schedule(due=due[0], now=now)
        self.assertEqual(len(runs), 2)
        self.assertEqual(
            OrchestrationRun.objects.filter(pipeline=self.pipeline, trigger_cause="scheduled").count(),
            2,
        )

    def test_dependency_ordering_and_dispatch(self):
        run = self._create_manual_run()
        resolver = DependencyResolver(lifecycle=self.lifecycle, repository=self.repository)
        dispatcher = RunDispatcher(
            executors={
                "handler.a": _StaticExecutor(JobExecutionResult(status="succeeded", summary="a", output_change_token="tok-a")),
                "handler.b": _StaticExecutor(JobExecutionResult(status="succeeded", summary="b", output_change_token="tok-b")),
            },
            lifecycle=self.lifecycle,
            repository=self.repository,
        )

        queued_first = resolver.queue_ready_jobs(run=run, now=timezone.now())
        self.assertEqual(len(queued_first), 1)
        first_job = OrchestrationJobRun.objects.get(id=queued_first[0])
        self.assertEqual(first_job.job_definition_id, self.job_a.id)

        dispatched_first = dispatcher.dispatch_once(now=timezone.now(), limit=10)
        self.assertEqual(len(dispatched_first), 1)

        queued_second = resolver.queue_ready_jobs(run=run, now=timezone.now())
        self.assertEqual(len(queued_second), 1)
        second_job = OrchestrationJobRun.objects.get(id=queued_second[0])
        self.assertEqual(second_job.job_definition_id, self.job_b.id)

    def test_retry_backoff_behavior(self):
        run = self._create_manual_run()
        resolver = DependencyResolver(lifecycle=self.lifecycle, repository=self.repository)
        queued = resolver.queue_ready_jobs(run=run, now=timezone.now())
        self.assertEqual(len(queued), 1)

        executor = _FailThenSucceedExecutor()
        dispatcher = RunDispatcher(
            executors={"handler.a": executor, "handler.b": _StaticExecutor(JobExecutionResult(status="succeeded", summary="b"))},
            lifecycle=self.lifecycle,
            repository=self.repository,
        )
        dispatcher.dispatch_once(now=timezone.now(), limit=10)

        job_run = OrchestrationJobRun.objects.get(id=queued[0])
        self.assertEqual(job_run.status, "waiting_retry")
        self.assertIsNotNone(job_run.next_attempt_at)

        dispatcher.dispatch_once(now=timezone.now(), limit=10)
        job_run.refresh_from_db()
        self.assertEqual(job_run.status, "waiting_retry")

        later = job_run.next_attempt_at + timedelta(seconds=1)
        dispatcher.dispatch_once(now=later, limit=10)
        job_run.refresh_from_db()
        self.assertEqual(job_run.status, "succeeded")

    def test_concurrency_guard_blocks_when_global_limit_reached(self):
        run = self._create_manual_run()
        job_a_run = OrchestrationJobRun.objects.get(run=run, job_definition=self.job_a)
        self.lifecycle.mark_job_queued(job_run_id=str(job_a_run.id), now=timezone.now())
        self.lifecycle.mark_job_running(job_run_id=str(job_a_run.id), now=timezone.now())

        run2 = self._create_manual_run()
        resolver = DependencyResolver(lifecycle=self.lifecycle, repository=self.repository)
        queued = resolver.queue_ready_jobs(run=run2, now=timezone.now())
        self.assertEqual(len(queued), 1)

        dispatcher = RunDispatcher(
            executors={"handler.a": _StaticExecutor(JobExecutionResult(status="succeeded", summary="ok"))},
            lifecycle=self.lifecycle,
            repository=self.repository,
            concurrency_guard=ConcurrencyGuard(global_limit=1),
        )
        dispatched = dispatcher.dispatch_once(now=timezone.now(), limit=10)
        self.assertEqual(dispatched, [])

    def test_stale_detection_marks_stale(self):
        run = self._create_manual_run()
        job_run = OrchestrationJobRun.objects.get(run=run, job_definition=self.job_a)
        self.lifecycle.mark_job_queued(job_run_id=str(job_run.id), now=timezone.now() - timedelta(minutes=10))
        job_run.refresh_from_db()
        job_run.stale_deadline_at = timezone.now() - timedelta(seconds=1)
        job_run.save(update_fields=["stale_deadline_at", "updated_at"])

        detector = StaleRunDetector(lifecycle=self.lifecycle, default_timeout_seconds=60)
        marked = detector.detect_and_mark_stale(now=timezone.now(), limit=10)
        self.assertIn(str(job_run.id), marked)
        job_run.refresh_from_db()
        self.assertEqual(job_run.status, "stale")

    def test_manual_rerun_flow(self):
        run = self._create_manual_run()
        engine = OrchestrationEngine(executors={}, lifecycle=self.lifecycle)
        rerun = engine.request_manual_rerun(run_id=str(run.id), requested_by_id=str(self.identity.id))
        self.assertEqual(rerun.rerun_of_id, run.id)
        self.assertEqual(rerun.trigger_cause, "retry")

    def test_skip_when_upstream_unchanged(self):
        self.job_b.only_if_upstream_changed = True
        self.job_b.save(update_fields=["only_if_upstream_changed", "updated_at"])

        run = self._create_manual_run()
        resolver = DependencyResolver(lifecycle=self.lifecycle, repository=self.repository)
        dispatcher = RunDispatcher(
            executors={
                "handler.a": _StaticExecutor(JobExecutionResult(status="succeeded", summary="a")),
            },
            lifecycle=self.lifecycle,
            repository=self.repository,
        )

        resolver.queue_ready_jobs(run=run, now=timezone.now())
        dispatcher.dispatch_once(now=timezone.now(), limit=10)
        resolver.queue_ready_jobs(run=run, now=timezone.now())

        job_b_run = OrchestrationJobRun.objects.get(run=run, job_definition=self.job_b)
        self.assertEqual(job_b_run.status, "skipped")
        self.assertEqual(job_b_run.skipped_reason, "upstream_unchanged")
