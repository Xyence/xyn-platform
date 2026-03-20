from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..managed_storage import materialize_managed_workspace, managed_workspace_root, managed_workspace_path


@dataclass(frozen=True)
class IngestWorkspace:
    path: Path
    workspace_id: str
    source_key: str
    run_key: str
    created_at: datetime
    retention_class: str


class IngestWorkspaceManager:
    def _normalize_source_key(self, source_key: str) -> str:
        token = str(source_key or "").strip()
        return token or "default"

    def create(
        self,
        *,
        workspace_id: str,
        source_key: str,
        run_key: str,
        retention_class: str = "ephemeral",
        reset: bool = False,
    ) -> IngestWorkspace:
        normalized_source = self._normalize_source_key(source_key)
        path = materialize_managed_workspace("ingest", workspace_id, normalized_source, run_key, reset=reset)
        return IngestWorkspace(
            path=path,
            workspace_id=workspace_id,
            source_key=normalized_source,
            run_key=run_key,
            created_at=datetime.now(timezone.utc),
            retention_class=retention_class,
        )

    def resolve(self, workspace: IngestWorkspace, *parts: Any) -> Path:
        return workspace.path.joinpath(*[str(part) for part in parts if str(part or "").strip()])

    def cleanup(self, workspace: IngestWorkspace) -> bool:
        root = managed_workspace_root()
        if not str(workspace.path).startswith(str(root)):
            raise ValueError("ingest workspace path escapes managed root")
        if not workspace.path.exists():
            return False
        shutil.rmtree(workspace.path, ignore_errors=True)
        return True

    def cleanup_for_run(
        self,
        *,
        workspace_id: str,
        source_key: str,
        run_key: str,
        retention_class: str = "ephemeral",
    ) -> bool:
        if str(retention_class or "").strip().lower() not in {"ephemeral", "temp", "temporary"}:
            return False
        normalized_source = self._normalize_source_key(source_key)
        path = managed_workspace_path("ingest", workspace_id, normalized_source, run_key)
        if not path.exists():
            return False
        return self.cleanup(
            IngestWorkspace(
                path=path,
                workspace_id=workspace_id,
                source_key=normalized_source,
                run_key=run_key,
                created_at=datetime.now(timezone.utc),
                retention_class=retention_class,
            )
        )
