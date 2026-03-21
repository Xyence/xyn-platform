from __future__ import annotations

import io
import logging
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

from django.db import transaction

from xyn_orchestrator import models
from xyn_orchestrator.storage import IngestStorageService, RetentionClass

from .classification import classify_file

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExpandedMember:
    member_id: str
    member_path: str
    classified_type: str
    group_key: str
    raw_bytes: bytes


def _safe_member_path(raw: str) -> str:
    normalized = str(raw or "").replace("\\", "/").strip().lstrip("/")
    pure = PurePosixPath(normalized)
    if not normalized or ".." in pure.parts:
        raise ValueError(f"invalid archive member path: {raw}")
    return str(pure)


class ZipArchiveExpander:
    def __init__(self, *, storage: IngestStorageService | None = None) -> None:
        self._storage = storage or IngestStorageService()

    def expand(
        self,
        *,
        parent_artifact: models.IngestArtifactRecord,
        zip_bytes: bytes,
    ) -> list[ExpandedMember]:
        members: list[ExpandedMember] = []
        workspace = parent_artifact.workspace
        source_connector = parent_artifact.source_connector
        orchestration_run = parent_artifact.orchestration_run
        job_run = parent_artifact.job_run
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                member_path = _safe_member_path(info.filename)
                member_name = member_path.rsplit("/", 1)[-1]
                classification = classify_file(filename=member_name)
                member_bytes = archive.read(info)
                stored = self._storage.store_snapshot_bytes(
                    workspace=workspace,
                    name=member_name,
                    content_type="application/octet-stream",
                    content=member_bytes,
                    snapshot_type="archive_member",
                    retention_class=RetentionClass.SNAPSHOT,
                    source_connector=source_connector,
                    orchestration_run=orchestration_run,
                    job_run=job_run,
                    scope_jurisdiction=str(parent_artifact.scope_jurisdiction or ""),
                    scope_source=str(parent_artifact.scope_source or ""),
                    metadata={
                        "parent_artifact_id": str(parent_artifact.id),
                        "member_path": member_path,
                    },
                )
                with transaction.atomic():
                    row, _ = models.IngestArtifactMember.objects.update_or_create(
                        parent_artifact=parent_artifact,
                        member_path=member_path,
                        defaults={
                            "workspace": workspace,
                            "source_connector": source_connector,
                            "orchestration_run": orchestration_run,
                            "job_run": job_run,
                            "member_artifact": stored.record,
                            "member_basename": member_name,
                            "group_key": classification.group_key,
                            "extension": classification.extension,
                            "classified_type": classification.kind,
                            "byte_length": len(member_bytes),
                            "status": "pending",
                        },
                    )
                members.append(
                    ExpandedMember(
                        member_id=str(row.id),
                        member_path=member_path,
                        classified_type=classification.kind,
                        group_key=classification.group_key,
                        raw_bytes=member_bytes,
                    )
                )
        logger.info("ingestion.archive.expanded", extra={"parent_artifact_id": str(parent_artifact.id), "members": len(members)})
        return members
