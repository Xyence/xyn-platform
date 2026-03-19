import unittest

from xyn_orchestrator.orchestration import (
    CRON_UNSUPPORTED_MESSAGE,
    ConcurrencyPolicy,
    OrchestrationRegistry,
    PartitionStrategy,
    RetryPolicy,
    StalePolicy,
    build_sample_data_pipeline,
    build_sample_data_pipeline_demo_executors,
    compose_pipeline,
    define_job,
    supported_schedule_kinds,
    unsupported_schedule_kinds,
    validate_pipeline_registration,
)
from xyn_orchestrator.orchestration.interfaces import ExecutionScope, JobExecutionContext, JobExecutionResult
from xyn_orchestrator.orchestration.scheduling import ScheduledTrigger


class _NoopExecutor:
    def execute(self, context):
        return JobExecutionResult(status="succeeded", summary="ok")


class OrchestrationRegistryTests(unittest.TestCase):
    def _register_standard_handlers(self, registry: OrchestrationRegistry) -> None:
        registry.register_handler(handler_key="platform.jobs.refresh_source", executor=_NoopExecutor())
        registry.register_handler(handler_key="platform.jobs.normalize_source", executor=_NoopExecutor())
        registry.register_handler(handler_key="platform.jobs.rebuild_entities", executor=_NoopExecutor())
        registry.register_handler(handler_key="platform.jobs.match_signals", executor=_NoopExecutor())
        registry.register_handler(handler_key="platform.jobs.evaluate_rules", executor=_NoopExecutor())
        registry.register_handler(handler_key="platform.jobs.emit_notifications", executor=_NoopExecutor())

    def test_pipeline_composition_and_registration(self):
        registry = OrchestrationRegistry()
        self._register_standard_handlers(registry)

        composer = compose_pipeline(
            key="test_pipeline",
            display_name="Test Pipeline",
            description="pipeline for testing",
            max_concurrency=2,
            stale_run_timeout_seconds=1800,
        )
        composer.add_manual_parameter(key="force_refresh", required=False, default_value="false")
        refresh = define_job(
            key="refresh_source",
            stage_key="source_refresh",
            display_name="Refresh",
            handler_key="platform.jobs.refresh_source",
            schedules=(ScheduledTrigger(key="hourly", kind="interval", interval_seconds=3600),),
            retry_policy=RetryPolicy(max_attempts=3, initial_backoff_seconds=30, max_backoff_seconds=600, multiplier=2.0),
            concurrency_policy=ConcurrencyPolicy(max_concurrency=1, per_partition_limit=1),
            stale_policy=StalePolicy(timeout_seconds=900),
            partition_strategy=PartitionStrategy(per_jurisdiction=True, per_source=True),
        )
        normalize = define_job(
            key="normalize_source",
            stage_key="source_normalization",
            display_name="Normalize",
            handler_key="platform.jobs.normalize_source",
            only_if_upstream_changed=True,
            partition_strategy=PartitionStrategy(per_jurisdiction=True, per_source=True),
        )
        composer.add_job(refresh)
        composer.add_job(normalize, depends_on=("refresh_source",))

        pipeline = composer.compose()
        validate_pipeline_registration(pipeline=pipeline, handler_keys=registry.handler_keys())
        registry.register_pipeline(pipeline)

        stored = registry.get_pipeline(pipeline_key="test_pipeline")
        self.assertIsNotNone(stored)
        self.assertEqual(stored.key, "test_pipeline")
        self.assertEqual(len(stored.jobs), 2)
        self.assertEqual(stored.jobs[1].dependencies, ("refresh_source",))
        runtime = stored.as_runtime_pipeline()
        self.assertEqual(runtime.key, "test_pipeline")
        self.assertEqual(runtime.max_concurrency, 2)
        self.assertEqual(len(runtime.jobs), 2)

    def test_validation_rejects_missing_handler(self):
        registry = OrchestrationRegistry()
        composer = compose_pipeline(key="missing_handler", display_name="Missing Handler")
        composer.add_job(
            define_job(
                key="refresh_source",
                stage_key="source_refresh",
                display_name="Refresh",
                handler_key="platform.jobs.missing",
            )
        )
        pipeline = composer.compose()
        with self.assertRaises(ValueError):
            validate_pipeline_registration(pipeline=pipeline, handler_keys=registry.handler_keys())

    def test_validation_rejects_cycle(self):
        registry = OrchestrationRegistry()
        registry.register_handler(handler_key="h.a", executor=_NoopExecutor())
        registry.register_handler(handler_key="h.b", executor=_NoopExecutor())
        composer = compose_pipeline(key="cyclic", display_name="Cyclic")
        composer.add_job(
            define_job(
                key="job_a",
                stage_key="a",
                display_name="A",
                handler_key="h.a",
                dependencies=("job_b",),
            )
        )
        composer.add_job(
            define_job(
                key="job_b",
                stage_key="b",
                display_name="B",
                handler_key="h.b",
                dependencies=("job_a",),
            )
        )
        with self.assertRaises(ValueError):
            validate_pipeline_registration(pipeline=composer.compose(), handler_keys=registry.handler_keys())

    def test_validation_rejects_invalid_schedule(self):
        registry = OrchestrationRegistry()
        registry.register_handler(handler_key="h.refresh", executor=_NoopExecutor())
        composer = compose_pipeline(key="bad_schedule", display_name="Bad Schedule")
        composer.add_job(
            define_job(
                key="refresh",
                stage_key="source_refresh",
                display_name="Refresh",
                handler_key="h.refresh",
                schedules=(ScheduledTrigger(key="every", kind="interval", interval_seconds=0),),
            )
        )
        with self.assertRaises(ValueError):
            validate_pipeline_registration(pipeline=composer.compose(), handler_keys=registry.handler_keys())

    def test_validation_rejects_cron_schedule_in_v1(self):
        registry = OrchestrationRegistry()
        registry.register_handler(handler_key="h.refresh", executor=_NoopExecutor())
        composer = compose_pipeline(key="cron_not_supported", display_name="Cron Not Supported")
        composer.add_job(
            define_job(
                key="refresh",
                stage_key="source_refresh",
                display_name="Refresh",
                handler_key="h.refresh",
                schedules=(ScheduledTrigger(key="hourly", kind="cron", cron_expression="0 * * * *"),),
            )
        )
        with self.assertRaisesRegex(ValueError, "intentionally unsupported"):
            validate_pipeline_registration(pipeline=composer.compose(), handler_keys=registry.handler_keys())

    def test_schedule_policy_constants_are_canonical(self):
        self.assertEqual(supported_schedule_kinds(), ("manual", "interval"))
        self.assertEqual(unsupported_schedule_kinds(), ("cron",))
        self.assertIn("intentionally unsupported", CRON_UNSUPPORTED_MESSAGE)

    def test_sample_pipeline_is_generic_and_valid(self):
        registry = OrchestrationRegistry()
        self._register_standard_handlers(registry)
        pipeline = build_sample_data_pipeline()
        validate_pipeline_registration(pipeline=pipeline, handler_keys=registry.handler_keys())
        self.assertEqual(pipeline.key, "sample_data_sync")
        self.assertEqual([job.key for job in pipeline.jobs], [
            "refresh_source",
            "normalize_source",
            "rebuild_entities",
            "match_signals",
            "evaluate_rules",
            "emit_notifications",
        ])
        self.assertEqual(pipeline.jobs[1].dependencies, ("refresh_source",))
        self.assertTrue(pipeline.jobs[1].only_if_upstream_changed)

    def test_demo_executors_expose_retry_and_artifact_outputs(self):
        executors = build_sample_data_pipeline_demo_executors()
        self.assertIn("platform.jobs.normalize_source", executors)
        context_retry_first = JobExecutionContext(
            workspace_id="ws",
            run_id="run-1",
            job_run_id="jr-1",
            pipeline_key="sample_data_sync",
            job_key="normalize_source",
            attempt_count=1,
            scope=ExecutionScope(jurisdiction="tx", source="mls"),
            metadata={"run_metadata": {"manual_parameters": {"simulate_retry_once": "true"}}},
        )
        first = executors["platform.jobs.normalize_source"].execute(context_retry_first)
        self.assertEqual(first.status, "failed")
        self.assertTrue(first.retryable)

        context_retry_second = JobExecutionContext(
            workspace_id="ws",
            run_id="run-1",
            job_run_id="jr-1",
            pipeline_key="sample_data_sync",
            job_key="normalize_source",
            attempt_count=2,
            scope=ExecutionScope(jurisdiction="tx", source="mls"),
            metadata={"run_metadata": {"manual_parameters": {"simulate_retry_once": "true"}}},
        )
        second = executors["platform.jobs.normalize_source"].execute(context_retry_second)
        self.assertEqual(second.status, "succeeded")
        self.assertTrue(isinstance(second.output_payload, dict))
        outputs = second.output_payload.get("outputs") if isinstance(second.output_payload.get("outputs"), list) else []
        self.assertEqual(len(outputs), 1)


if __name__ == "__main__":
    unittest.main()
