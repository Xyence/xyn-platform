from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from xyn_orchestrator.bootstrap_guard import schema_bootstrap_readiness


class BootstrapGuardTests(SimpleTestCase):
    def test_ready_when_no_pending_migrations_and_required_tables_exist(self):
        fake_connection = mock.Mock()
        fake_connection.introspection.table_names.return_value = [
            "xyn_orchestrator_workspace",
            "xyn_orchestrator_seedpack",
            "xyn_orchestrator_provisionedinstance",
        ]
        fake_executor = mock.Mock()
        fake_executor.loader.graph.leaf_nodes.return_value = [("xyn_orchestrator", "0151")]
        fake_executor.migration_plan.return_value = []

        with mock.patch("xyn_orchestrator.bootstrap_guard.connection", fake_connection), mock.patch(
            "xyn_orchestrator.bootstrap_guard.MigrationExecutor",
            return_value=fake_executor,
        ):
            readiness = schema_bootstrap_readiness(
                required_tables={
                    "xyn_orchestrator_workspace",
                    "xyn_orchestrator_seedpack",
                    "xyn_orchestrator_provisionedinstance",
                }
            )

        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.reason, "ready")
        fake_connection.ensure_connection.assert_called_once()

    def test_not_ready_when_pending_migrations_exist(self):
        fake_connection = mock.Mock()
        fake_connection.introspection.table_names.return_value = ["xyn_orchestrator_workspace"]
        fake_executor = mock.Mock()
        fake_executor.loader.graph.leaf_nodes.return_value = [("xyn_orchestrator", "0151")]
        fake_executor.migration_plan.return_value = [(SimpleNamespace(), False)]

        with mock.patch("xyn_orchestrator.bootstrap_guard.connection", fake_connection), mock.patch(
            "xyn_orchestrator.bootstrap_guard.MigrationExecutor",
            return_value=fake_executor,
        ):
            readiness = schema_bootstrap_readiness(required_tables={"xyn_orchestrator_workspace"})

        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.reason, "pending_migrations")

    def test_not_ready_when_required_tables_missing(self):
        fake_connection = mock.Mock()
        fake_connection.introspection.table_names.return_value = ["xyn_orchestrator_workspace"]
        fake_executor = mock.Mock()
        fake_executor.loader.graph.leaf_nodes.return_value = [("xyn_orchestrator", "0151")]
        fake_executor.migration_plan.return_value = []

        with mock.patch("xyn_orchestrator.bootstrap_guard.connection", fake_connection), mock.patch(
            "xyn_orchestrator.bootstrap_guard.MigrationExecutor",
            return_value=fake_executor,
        ):
            readiness = schema_bootstrap_readiness(
                required_tables={"xyn_orchestrator_workspace", "xyn_orchestrator_seedpack"}
            )

        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.reason, "missing_tables:xyn_orchestrator_seedpack")
