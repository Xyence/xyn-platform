from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..managed_storage import materialize_managed_workspace, managed_workspace_root


@dataclass(frozen=True)
class IngestWorkspace:
    path: Path
    workspace_id: str
    source_key: str
    run_key: str
    created_at: datetime
    retention_class: str


class IngestWorkspaceManager:
    def create(
        self,
        *,
        workspace_id: str,
        source_key: str,
        run_key: str,
        retention_class: str = "ephemeral",
        reset: bool = False,
    ) -> IngestWorkspace:
        path = materialize_managed_workspace("ingest", workspace_id, source_key, run_key, reset=reset)
        return IngestWorkspace(
            path=path,
            workspace_id=workspace_id,
            source_key=source_key,
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
