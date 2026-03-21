from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass
from typing import Any

from xyn_orchestrator import models
from xyn_orchestrator.orchestration.interfaces import ExecutionScope, RunCreateRequest, RunTrigger
from xyn_orchestrator.orchestration.lifecycle import OrchestrationLifecycleService
from xyn_orchestrator.provenance import ProvenanceLinkInput, ProvenanceService, object_ref

from .archive import ZipArchiveExpander
from .classification import classify_file
from .fetch import HttpArtifactFetcher
from .interfaces import FILE_KIND_SHP, FILE_KIND_ZIP, FetchRequest, ParseTarget
from .parsers import ParserRegistry, build_default_registry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestionExecutionResult:
    run_id: str
    artifact_record_id: str
    parsed_record_count: int
    warnings: tuple[str, ...]


class IngestionCoordinator:
    def __init__(
        self,
        *,
        fetcher: HttpArtifactFetcher | None = None,
        archive_expander: ZipArchiveExpander | None = None,
        parser_registry: ParserRegistry | None = None,
    ) -> None:
        self._fetcher = fetcher or HttpArtifactFetcher()
        self._archive = archive_expander or ZipArchiveExpander()
        self._registry = parser_registry or build_default_registry()

    def _ensure_pipeline(self, *, workspace: models.Workspace, key: str = "ingestion-runtime") -> models.OrchestrationPipeline:
        pipeline, _ = models.OrchestrationPipeline.objects.get_or_create(
            workspace=workspace,
            key=key,
            defaults={"name": "Ingestion Runtime", "enabled": True},
        )
        return pipeline

    def create_ingest_run(
        self,
        *,
        workspace: models.Workspace,
        source_connector: models.SourceConnector,
        jurisdiction: str,
        source_scope: str,
    ) -> models.OrchestrationRun:
        pipeline = self._ensure_pipeline(
            workspace=workspace,
            key=str(source_connector.orchestration_pipeline_key or "ingestion-runtime").strip() or "ingestion-runtime",
        )
        return OrchestrationLifecycleService().create_run(
            RunCreateRequest(
                workspace_id=str(workspace.id),
                pipeline_key=str(pipeline.key),
                trigger=RunTrigger(trigger_cause="manual", trigger_key="ingestion_runtime"),
                run_type="ingest.binary",
                target_ref={"target_type": "source_connector", "target_id": str(source_connector.id)},
                scope=ExecutionScope(jurisdiction=jurisdiction, source=source_scope),
                metadata={"runtime": "ingestion"},
            )
        )

    def ingest_from_url(
        self,
        *,
        source_connector: models.SourceConnector,
        source_url: str,
        jurisdiction: str,
        source_scope: str,
        timeout_seconds: int = 60,
    ) -> IngestionExecutionResult:
        workspace = source_connector.workspace
        run = self.create_ingest_run(
            workspace=workspace,
            source_connector=source_connector,
            jurisdiction=jurisdiction,
            source_scope=source_scope,
        )
        run.status = "running"
        run.save(update_fields=["status", "updated_at"])
        warnings: list[str] = []
        parsed_count = 0
        try:
            fetch_result = self._fetcher.fetch_to_artifact(
                workspace=workspace,
                source_connector=source_connector,
                orchestration_run=run,
                scope_jurisdiction=jurisdiction,
                scope_source=source_scope,
                request=FetchRequest(source_url=source_url, timeout_seconds=timeout_seconds),
            )
            artifact_row = models.IngestArtifactRecord.objects.get(id=fetch_result.artifact_record_id)
            previous = (
                models.IngestArtifactRecord.objects.filter(
                    workspace=workspace,
                    source_connector=source_connector,
                    sha256=artifact_row.sha256,
                    snapshot_type=artifact_row.snapshot_type,
                )
                .exclude(id=artifact_row.id)
                .order_by("-created_at")
                .first()
            )
            if previous is not None:
                meta = artifact_row.metadata_json if isinstance(artifact_row.metadata_json, dict) else {}
                meta["deduped_from_artifact_id"] = str(previous.id)
                artifact_row.metadata_json = meta
                artifact_row.save(update_fields=["metadata_json", "updated_at"])

            classified = classify_file(filename=fetch_result.original_filename, content_type=fetch_result.content_type)
            with open(fetch_result.local_path, "rb") as fp:
                raw_bytes = fp.read()

            if classified.kind == FILE_KIND_ZIP:
                members = self._archive.expand(parent_artifact=artifact_row, zip_bytes=raw_bytes)
                grouped: dict[str, list[Any]] = {}
                for member in members:
                    grouped.setdefault(member.group_key or member.member_path, []).append(member)
                for _, rows in grouped.items():
                    kinds = {row.classified_type for row in rows}
                    shp_member = next((row for row in rows if row.classified_type == FILE_KIND_SHP), None)
                    if shp_member is not None and kinds.intersection({"dbf", "shx", "prj", "cpg"}):
                        parsed_count += self._parse_grouped_shapefile(
                            workspace=workspace,
                            run=run,
                            source_connector=source_connector,
                            artifact_row=artifact_row,
                            members=rows,
                            warnings=warnings,
                        )
                        continue
                    for row in rows:
                        parsed_count += self._parse_member(
                            workspace=workspace,
                            run=run,
                            source_connector=source_connector,
                            artifact_row=artifact_row,
                            member=models.IngestArtifactMember.objects.get(id=row.member_id),
                            content=row.raw_bytes,
                            warnings=warnings,
                        )
            else:
                parsed_count += self._parse_root_artifact(
                    workspace=workspace,
                    run=run,
                    source_connector=source_connector,
                    artifact_row=artifact_row,
                    kind=classified.kind,
                    filename=fetch_result.original_filename,
                    content=raw_bytes,
                    warnings=warnings,
                )

            run.status = "succeeded"
            run.summary = f"ingestion completed ({parsed_count} parsed records)"
            run.save(update_fields=["status", "summary", "updated_at"])
            return IngestionExecutionResult(
                run_id=str(run.id),
                artifact_record_id=str(artifact_row.id),
                parsed_record_count=parsed_count,
                warnings=tuple(warnings),
            )
        except Exception as exc:
            run.status = "failed"
            run.error_text = str(exc)
            run.summary = "ingestion failed"
            run.save(update_fields=["status", "error_text", "summary", "updated_at"])
            logger.exception("ingestion.coordinator.failed", extra={"run_id": str(run.id), "source_connector_id": str(source_connector.id)})
            raise

    def _parse_root_artifact(
        self,
        *,
        workspace: models.Workspace,
        run: models.OrchestrationRun,
        source_connector: models.SourceConnector,
        artifact_row: models.IngestArtifactRecord,
        kind: str,
        filename: str,
        content: bytes,
        warnings: list[str],
    ) -> int:
        parser = self._registry.resolve(kind)
        if parser is None:
            warnings.append(f"unsupported format: {kind}")
            return 0
        target = ParseTarget(
            workspace_id=str(workspace.id),
            source_connector_id=str(source_connector.id),
            orchestration_run_id=str(run.id),
            artifact_record_id=str(artifact_row.id),
            source_path=filename,
            classified_kind=kind,
        )
        outcome = parser.parse(target=target, stream=io.BytesIO(content))
        warnings.extend(list(outcome.warnings))
        return self._persist_outcome(
            workspace=workspace,
            run=run,
            source_connector=source_connector,
            artifact_row=artifact_row,
            member_row=None,
            outcome=outcome,
        )

    def _parse_member(
        self,
        *,
        workspace: models.Workspace,
        run: models.OrchestrationRun,
        source_connector: models.SourceConnector,
        artifact_row: models.IngestArtifactRecord,
        member: models.IngestArtifactMember,
        content: bytes,
        warnings: list[str],
    ) -> int:
        parser = self._registry.resolve(str(member.classified_type or ""))
        if parser is None:
            member.status = "unsupported"
            member.failure_reason = f"unsupported member type: {member.classified_type}"
            member.save(update_fields=["status", "failure_reason", "updated_at"])
            warnings.append(member.failure_reason)
            return 0
        target = ParseTarget(
            workspace_id=str(workspace.id),
            source_connector_id=str(source_connector.id),
            orchestration_run_id=str(run.id),
            artifact_record_id=str(artifact_row.id),
            member_id=str(member.id),
            source_path=str(member.member_path),
            classified_kind=str(member.classified_type or ""),
            group_key=str(member.group_key or ""),
        )
        outcome = parser.parse(target=target, stream=io.BytesIO(content))
        warnings.extend(list(outcome.warnings))
        return self._persist_outcome(
            workspace=workspace,
            run=run,
            source_connector=source_connector,
            artifact_row=artifact_row,
            member_row=member,
            outcome=outcome,
        )

    def _parse_grouped_shapefile(
        self,
        *,
        workspace: models.Workspace,
        run: models.OrchestrationRun,
        source_connector: models.SourceConnector,
        artifact_row: models.IngestArtifactRecord,
        members: list[Any],
        warnings: list[str],
    ) -> int:
        shp_member = next((row for row in members if row.classified_type == FILE_KIND_SHP), None)
        if shp_member is None:
            return 0
        member_row = models.IngestArtifactMember.objects.get(id=shp_member.member_id)
        parser = self._registry.resolve(FILE_KIND_SHP)
        if parser is None:
            member_row.status = "unsupported"
            member_row.failure_reason = "grouped shapefile parser unavailable"
            member_row.save(update_fields=["status", "failure_reason", "updated_at"])
            warnings.append(member_row.failure_reason)
            return 0
        target = ParseTarget(
            workspace_id=str(workspace.id),
            source_connector_id=str(source_connector.id),
            orchestration_run_id=str(run.id),
            artifact_record_id=str(artifact_row.id),
            member_id=str(member_row.id),
            source_path=str(member_row.member_path or ""),
            classified_kind=FILE_KIND_SHP,
            group_key=str(member_row.group_key or ""),
            metadata={
                "group_member_ids": [str(item.member_id) for item in members],
                "group_member_paths": [str(item.member_path) for item in members],
            },
        )
        outcome = parser.parse(target=target, stream=io.BytesIO(shp_member.raw_bytes))
        warnings.extend(list(outcome.warnings))
        count = self._persist_outcome(
            workspace=workspace,
            run=run,
            source_connector=source_connector,
            artifact_row=artifact_row,
            member_row=member_row,
            outcome=outcome,
            target_metadata=target.metadata,
        )
        for item in members:
            row = models.IngestArtifactMember.objects.get(id=item.member_id)
            row.status = "unsupported"
            row.failure_reason = "grouped shapefile routed but parser not implemented"
            row.save(update_fields=["status", "failure_reason", "updated_at"])
        return count

    def _persist_outcome(
        self,
        *,
        workspace: models.Workspace,
        run: models.OrchestrationRun,
        source_connector: models.SourceConnector,
        artifact_row: models.IngestArtifactRecord,
        member_row: models.IngestArtifactMember | None,
        outcome,
        target_metadata: dict[str, Any] | None = None,
    ) -> int:
        base_meta = target_metadata if isinstance(target_metadata, dict) else {}
        count = 0
        if not outcome.records and outcome.warnings:
            key = hashlib.sha256(
                f"{workspace.id}|{artifact_row.id}|{member_row.id if member_row else ''}|{outcome.parser_name}|warnings".encode("utf-8")
            ).hexdigest()
            models.IngestParsedRecord.objects.get_or_create(
                workspace=workspace,
                idempotency_key=key,
                defaults={
                    "source_connector": source_connector,
                    "orchestration_run": run,
                    "artifact": artifact_row,
                    "member": member_row,
                    "parser_name": str(outcome.parser_name),
                    "parser_version": str(outcome.parser_version),
                    "normalization_version": str(outcome.normalization_version),
                    "status": "warning",
                    "failure_reason": "; ".join(outcome.warnings),
                    "provenance_json": base_meta,
                },
            )
            return 0
        for record in outcome.records:
            key_raw = "|".join(
                [
                    str(workspace.id),
                    str(run.id),
                    str(artifact_row.id),
                    str(member_row.id) if member_row else "",
                    str(outcome.parser_name),
                    str(record.record_index or 0),
                    hashlib.sha256(str(record.normalized_payload).encode("utf-8")).hexdigest(),
                ]
            )
            idempotency_key = hashlib.sha256(key_raw.encode("utf-8")).hexdigest()
            parsed_row, _ = models.IngestParsedRecord.objects.get_or_create(
                workspace=workspace,
                idempotency_key=idempotency_key,
                defaults={
                    "source_connector": source_connector,
                    "orchestration_run": run,
                    "artifact": artifact_row,
                    "member": member_row,
                    "parser_name": str(outcome.parser_name),
                    "parser_version": str(outcome.parser_version),
                    "normalization_version": str(outcome.normalization_version),
                    "record_index": record.record_index,
                    "source_payload_json": record.source_payload,
                    "normalized_payload_json": record.normalized_payload,
                    "source_schema_json": record.source_schema,
                    "provenance_json": {**base_meta, **record.provenance},
                    "warnings_json": list(record.warnings),
                    "status": str(record.status or "ok"),
                },
            )
            source_family = "ingest_artifact_member" if member_row else "ingest_artifact"
            source_id = str(member_row.id) if member_row else str(artifact_row.id)
            ProvenanceService().record_provenance_link(
                ProvenanceLinkInput(
                    workspace_id=str(workspace.id),
                    relationship_type="ingest_parsed_from",
                    source_ref=object_ref(
                        object_family=source_family,
                        object_id=source_id,
                        workspace_id=str(workspace.id),
                    ),
                    target_ref=object_ref(
                        object_family="ingest_parsed_record",
                        object_id=str(parsed_row.id),
                        workspace_id=str(workspace.id),
                    ),
                    reason="parsed output persisted",
                    metadata={
                        "parser_name": str(outcome.parser_name),
                        "parser_version": str(outcome.parser_version),
                        "normalization_version": str(outcome.normalization_version),
                        "orchestration_run_id": str(run.id),
                    },
                    run_id=str(run.id),
                    idempotency_key=f"parsed_link:{parsed_row.id}",
                )
            )
            count += 1
        if member_row is not None:
            member_row.status = "parsed"
            member_row.failure_reason = ""
            member_row.save(update_fields=["status", "failure_reason", "updated_at"])
        return count
