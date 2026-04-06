"""Schema/bootstrap readiness guards.

These checks intentionally separate schema readiness from data bootstrap logic:
- migrations remain the sole source of schema truth
- runtime/bootstrap code runs only when schema is fully ready
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from django.db import connection
from django.db.migrations.executor import MigrationExecutor

DEFAULT_BOOTSTRAP_REQUIRED_TABLES = frozenset(
    {
        "xyn_orchestrator_workspace",
        "xyn_orchestrator_seedpack",
        "xyn_orchestrator_provisionedinstance",
    }
)


@dataclass(frozen=True)
class BootstrapReadiness:
    ready: bool
    reason: str


def schema_bootstrap_readiness(*, required_tables: Iterable[str]) -> BootstrapReadiness:
    required = {str(name).strip() for name in required_tables if str(name).strip()}
    try:
        connection.ensure_connection()
    except Exception as exc:
        return BootstrapReadiness(False, f"db_unavailable:{exc.__class__.__name__}")

    try:
        executor = MigrationExecutor(connection)
        targets = executor.loader.graph.leaf_nodes()
        pending = executor.migration_plan(targets)
    except Exception as exc:
        return BootstrapReadiness(False, f"migration_state_unavailable:{exc.__class__.__name__}")

    if pending:
        return BootstrapReadiness(False, "pending_migrations")

    try:
        tables = set(connection.introspection.table_names())
    except Exception as exc:
        return BootstrapReadiness(False, f"table_introspection_failed:{exc.__class__.__name__}")

    missing = sorted(required - tables)
    if missing:
        return BootstrapReadiness(False, f"missing_tables:{','.join(missing)}")
    return BootstrapReadiness(True, "ready")
