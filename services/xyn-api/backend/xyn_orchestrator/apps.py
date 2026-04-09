from django.apps import AppConfig
import os
import sys
import logging

from .bootstrap_guard import DEFAULT_BOOTSTRAP_REQUIRED_TABLES, schema_bootstrap_readiness
from .runtime_repo_map_validation import validate_runtime_repo_map_targets


logger = logging.getLogger(__name__)


def _bootstrap_db_ready() -> bool:
    readiness = schema_bootstrap_readiness(required_tables=DEFAULT_BOOTSTRAP_REQUIRED_TABLES)
    return readiness.ready


class XynOrchestratorConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "xyn_orchestrator"
    label = "xyn_orchestrator"

    def ready(self) -> None:
        if os.environ.get("XYENCE_BOOTSTRAP_DISABLE", "").strip() == "1":
            return
        argv = " ".join(sys.argv).lower()
        if any(cmd in argv for cmd in ("migrate", "makemigrations", "collectstatic", "shell", "test", "seed_packs")):
            return
        _validate_runtime_repo_map_startup()
        if not _bootstrap_db_ready():
            logger.info("Skipping startup bootstrap until DB schema is ready.")
            return
        try:
            from xyn_orchestrator.ai_runtime import ensure_default_ai_seeds
            from xyn_orchestrator.instances.bootstrap import bootstrap_instance_registration
            from xyn_orchestrator.seeds import auto_apply_core_seed_packs
            from xyn_orchestrator.solution_bundles import bootstrap_install_solution_bundles_from_env

            ensure_default_ai_seeds()
            bootstrap_instance_registration()
            auto_apply_core_seed_packs()
            bootstrap_install_solution_bundles_from_env(reason="app_ready")
        except Exception as exc:
            logger.warning("Startup bootstrap did not complete: %s", exc)
            return


def _validate_runtime_repo_map_startup() -> None:
    mode = str(os.getenv("XYN_RUNTIME_REPO_MAP_VALIDATION", "warn") or "").strip().lower() or "warn"
    if mode in {"off", "false", "0", "disabled"}:
        return
    should_fail = mode in {"fail", "strict", "error"}
    try:
        warnings = validate_runtime_repo_map_targets()
    except Exception as exc:
        message = f"Runtime repo map configuration is invalid: {exc}"
        if should_fail:
            raise RuntimeError(message) from exc
        logger.warning(message)
        return
    if not warnings:
        return
    for warning in warnings:
        logger.warning(warning)
    if should_fail:
        raise RuntimeError("Runtime repo map validation failed; missing repo-map targets.")
