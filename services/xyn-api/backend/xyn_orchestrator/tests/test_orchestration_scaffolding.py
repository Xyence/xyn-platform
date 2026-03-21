import unittest

from xyn_orchestrator.orchestration import (
    DependencySnapshot,
    JobDefinition,
    JobDependencyGraph,
    RetryPolicy,
    exponential_backoff_seconds,
)


class OrchestrationScaffoldingTests(unittest.TestCase):
    def test_dependency_graph_topological_order_and_ready_jobs(self):
        refresh = JobDefinition(key="refresh", stage_key="source_refresh", name="Refresh", handler_key="refresh")
        normalize = JobDefinition(
            key="normalize",
            stage_key="source_normalization",
            name="Normalize",
            handler_key="normalize",
            dependencies=("refresh",),
        )
        match = JobDefinition(
            key="match",
            stage_key="signal_matching",
            name="Match",
            handler_key="match",
            dependencies=("normalize",),
            only_if_upstream_changed=True,
        )

        graph = JobDependencyGraph((refresh, normalize, match))
        self.assertEqual([job.key for job in graph.topological_order()], ["refresh", "normalize", "match"])

        ready_without_change = graph.ready_jobs(
            DependencySnapshot(completed=frozenset({"refresh", "normalize"}), failed=frozenset(), changed=frozenset())
        )
        self.assertEqual([job.key for job in ready_without_change], [])

        ready_with_change = graph.ready_jobs(
            DependencySnapshot(completed=frozenset({"refresh", "normalize"}), failed=frozenset(), changed=frozenset({"normalize"}))
        )
        self.assertEqual([job.key for job in ready_with_change], ["match"])

    def test_dependency_graph_rejects_unknown_dependency(self):
        with self.assertRaises(ValueError):
            JobDependencyGraph(
                (
                    JobDefinition(
                        key="normalize",
                        stage_key="source_normalization",
                        name="Normalize",
                        handler_key="normalize",
                        dependencies=("missing",),
                    ),
                )
            )

    def test_exponential_backoff_clamps_to_max(self):
        policy = RetryPolicy(max_attempts=6, initial_backoff_seconds=5, max_backoff_seconds=20, multiplier=2.0)
        self.assertEqual(exponential_backoff_seconds(attempt=1, policy=policy), 5)
        self.assertEqual(exponential_backoff_seconds(attempt=2, policy=policy), 10)
        self.assertEqual(exponential_backoff_seconds(attempt=3, policy=policy), 20)
        self.assertEqual(exponential_backoff_seconds(attempt=7, policy=policy), 20)


if __name__ == "__main__":
    unittest.main()
