from django.apps import AppConfig
from django.db import connection
import os
import sys
import logging


logger = logging.getLogger(__name__)


def _bootstrap_db_ready() -> bool:
    try:
        connection.ensure_connection()
        tables = set(connection.introspection.table_names())
    except Exception:
        return False
    required_tables = {
        "xyn_orchestrator_workspace",
        "xyn_orchestrator_seedpack",
        "xyn_orchestrator_provisionedinstance",
    }
    return required_tables.issubset(tables)


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
        if not _bootstrap_db_ready():
            logger.info("Skipping startup bootstrap until DB schema is ready.")
            return
        try:
            from xyn_orchestrator.ai_runtime import ensure_default_ai_seeds
            from xyn_orchestrator.instances.bootstrap import bootstrap_instance_registration
            from xyn_orchestrator.seeds import auto_apply_core_seed_packs

            ensure_default_ai_seeds()
            bootstrap_instance_registration()
            auto_apply_core_seed_packs()
        except Exception as exc:
            logger.warning("Startup bootstrap did not complete: %s", exc)
            return
