from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, BinaryIO, Optional

from django.db import transaction

from .contract import IngestArtifactMetadata, RetentionClass, SnapshotType
from .durable import DurableArtifactStore, get_durable_artifact_store
from .staging import IngestWorkspaceManager
from .. import models
from ..provenance import ProvenanceLinkInput, ProvenanceService, object_ref
from ..orchestration.interfaces import OutputRecord


@dataclass(frozen=True)
class IngestStoreResult:
    artifact: IngestArtifactMetadata
    record: models.IngestArtifactRecord


class IngestStorageService:
    def __init__(
        self,
        *,
        durable_store: Optional[DurableArtifactStore] = None,
        workspace_manager: Optional[IngestWorkspaceManager] = None,
    ) -> None:
        self._durable_store = durable_store or get_durable_artifact_store()
        self._workspaces = workspace_manager or IngestWorkspaceManager()

    @property
    def workspaces(self) -> IngestWorkspaceManager:
        return self._workspaces

    def create_ingest_workspace(
        self,
        *,
        workspace_id: str,
        source_key: str,
        run_key: str,
        retention_class: str = RetentionClass.EPHEMERAL.value,
        reset: bool = False,
    ):
        return self._workspaces.create(
            workspace_id=workspace_id,
            source_key=source_key,
            run_key=run_key,
            retention_class=retention_class,
            reset=reset,
        )

    def store_snapshot_bytes(
        self,
        *,
        workspace: models.Workspace,
        name: str,
        content_type: str,
        content: bytes,
        snapshot_type: SnapshotType | str = SnapshotType.RAW,
        retention_class: RetentionClass | str = RetentionClass.SNAPSHOT,
        source_connector: Optional[models.SourceConnector] = None,
        orchestration_run: Optional[models.OrchestrationRun] = None,
        job_run: Optional[models.OrchestrationJobRun] = None,
        scope_jurisdiction: str = "",
        scope_source: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> IngestStoreResult:
        stored = self._durable_store.store_bytes(
            name=name,
            kind="ingest-snapshot",
            content_type=content_type,
            content=content,
            workspace_id=str(workspace.id),
            storage_scope="durable",
            sync_state="remote" if content else "local",
        )
        return self._persist_record(
            workspace=workspace,
            stored=stored,
            snapshot_type=snapshot_type,
            retention_class=retention_class,
            source_connector=source_connector,
            orchestration_run=orchestration_run,
            job_run=job_run,
            scope_jurisdiction=scope_jurisdiction,
            scope_source=scope_source,
            metadata=metadata,
        )

    def store_snapshot_stream(
        self,
        *,
        workspace: models.Workspace,
        name: str,
        content_type: str,
        stream: BinaryIO,
        snapshot_type: SnapshotType | str = SnapshotType.RAW,
        retention_class: RetentionClass | str = RetentionClass.SNAPSHOT,
        source_connector: Optional[models.SourceConnector] = None,
        orchestration_run: Optional[models.OrchestrationRun] = None,
        job_run: Optional[models.OrchestrationJobRun] = None,
        scope_jurisdiction: str = "",
        scope_source: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> IngestStoreResult:
        stored = self._durable_store.store_stream(
            name=name,
            kind="ingest-snapshot",
            content_type=content_type,
            stream=stream,
            workspace_id=str(workspace.id),
            storage_scope="durable",
            sync_state="remote",
        )
        return self._persist_record(
            workspace=workspace,
            stored=stored,
            snapshot_type=snapshot_type,
            retention_class=retention_class,
            source_connector=source_connector,
            orchestration_run=orchestration_run,
            job_run=job_run,
            scope_jurisdiction=scope_jurisdiction,
            scope_source=scope_source,
            metadata=metadata,
        )

    def _persist_record(
        self,
        *,
        workspace: models.Workspace,
        stored: Any,
        snapshot_type: SnapshotType | str,
        retention_class: RetentionClass | str,
        source_connector: Optional[models.SourceConnector],
        orchestration_run: Optional[models.OrchestrationRun],
        job_run: Optional[models.OrchestrationJobRun],
        scope_jurisdiction: str,
        scope_source: str,
        metadata: Optional[dict[str, Any]],
    ) -> IngestStoreResult:
        created_at = datetime.now(timezone.utc)
        snapshot_value = str(getattr(snapshot_type, "value", snapshot_type) or "").strip() or "raw"
        retention_value = str(getattr(retention_class, "value", retention_class) or "").strip() or "snapshot"
        record_metadata = metadata or {}
        with transaction.atomic():
            record = models.IngestArtifactRecord.objects.create(
                workspace=workspace,
                source_connector=source_connector,
                orchestration_run=orchestration_run,
                job_run=job_run,
                artifact_id=stored.artifact_id,
                artifact_uri=stored.uri,
                storage_provider=stored.storage_provider,
                storage_key=stored.storage_key,
                content_type=stored.content_type,
                byte_length=stored.byte_length,
                sha256=stored.sha256 or "",
                snapshot_type=snapshot_value,
                retention_class=retention_value,
                scope_jurisdiction=scope_jurisdiction,
                scope_source=scope_source,
                metadata_json=record_metadata,
                created_at=created_at,
            )
            if source_connector is not None:
                provenance = ProvenanceService()
                provenance.record_provenance_link(
                    ProvenanceLinkInput(
                        workspace_id=str(workspace.id),
                        relationship_type="ingest_snapshot",
                        source_ref=object_ref(
                            object_family="source_connector",
                            object_id=str(source_connector.id),
                            workspace_id=str(workspace.id),
                        ),
                        target_ref=object_ref(
                            object_family="runtime_artifact",
                            object_id=str(stored.artifact_id),
                            workspace_id=str(workspace.id),
                        ),
                        reason="source snapshot stored",
                        metadata={
                            "snapshot_type": snapshot_value,
                            "retention_class": retention_value,
                            "artifact_uri": stored.uri,
                        },
                        run_id=str(orchestration_run.id) if orchestration_run else "",
                    )
                )
        metadata_out = IngestArtifactMetadata(
            workspace_id=str(workspace.id),
            artifact_id=str(stored.artifact_id),
            artifact_uri=stored.uri,
            storage_provider=stored.storage_provider,
            storage_key=stored.storage_key,
            content_type=stored.content_type,
            byte_length=stored.byte_length,
            sha256=stored.sha256,
            snapshot_type=snapshot_value,
            retention_class=retention_value,
            source_connector_id=str(source_connector.id) if source_connector else "",
            orchestration_run_id=str(orchestration_run.id) if orchestration_run else "",
            job_run_id=str(job_run.id) if job_run else "",
            scope_jurisdiction=scope_jurisdiction,
            scope_source=scope_source,
            metadata=record_metadata,
            created_at=created_at,
        )
        return IngestStoreResult(artifact=metadata_out, record=record)


def prepare_ingest_run_metadata(
    *,
    workspace_id: str,
    source_key: str,
    run_key: str,
    retention_class: str = RetentionClass.EPHEMERAL.value,
) -> dict[str, Any]:
    manager = IngestWorkspaceManager()
    workspace = manager.create(
        workspace_id=workspace_id,
        source_key=source_key,
        run_key=run_key,
        retention_class=retention_class,
    )
    return {
        "source_key": workspace.source_key,
        "run_key": workspace.run_key,
        "retention_class": workspace.retention_class,
        "workspace_path": str(workspace.path),
        "created_at": workspace.created_at.isoformat(),
    }


def snapshot_output_record(
    *,
    stored: IngestStoreResult,
    output_key: str = "raw_snapshot",
    output_type: str = "dataset_snapshot",
) -> OutputRecord:
    metadata = {
        "snapshot_type": stored.record.snapshot_type,
        "retention_class": stored.record.retention_class,
        "ingest_artifact_id": str(stored.record.id),
        "source_connector_id": str(stored.record.source_connector_id or ""),
        "runtime_artifact_id": str(stored.record.artifact_id),
        "artifact_sha256": str(stored.record.sha256 or ""),
    }
    return OutputRecord(
        output_key=output_key,
        output_type=output_type,
        output_uri=str(stored.record.artifact_uri or ""),
        output_change_token=str(stored.record.sha256 or ""),
        artifact_id="",
        metadata=metadata,
    )
