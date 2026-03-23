from __future__ import annotations

import hashlib
import io
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from xyn_orchestrator import models
from xyn_orchestrator.orchestration.definitions import STAGE_PROPERTY_GRAPH_REBUILD
from xyn_orchestrator.orchestration.interfaces import ExecutionScope, OutputRecord, RunCreateRequest, RunTrigger
from xyn_orchestrator.orchestration.lifecycle import OrchestrationLifecycleService
from xyn_orchestrator.provenance import ProvenanceLinkInput, ProvenanceService, object_ref
from xyn_orchestrator.source_governance import SourceGovernanceService
from xyn_orchestrator.source_adapters import SourceAdapterService

from .archive import ZipArchiveExpander
from .classification import classify_file
from .fetch import HttpArtifactFetcher
from .interfaces import (
    FILE_KIND_SHP,
    FILE_KIND_ZIP,
    ISSUE_CATEGORY_NOT_IMPLEMENTED,
    ISSUE_CATEGORY_NOT_INSTALLED,
    ISSUE_CATEGORY_UNSUPPORTED_FORMAT,
    ParseIssue,
    ParseOutcome,
    FetchRequest,
    ParseTarget,
    TARGET_TYPE_FILE,
    TARGET_TYPE_GROUPED,
)
from .parsers import ParserRegistry, build_default_registry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestionExecutionResult:
    run_id: str
    artifact_record_id: str
    parsed_record_count: int
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class IngestionProcessingStats:
    parsed_records_created: int = 0
    warning_rows_created: int = 0
    error_rows_created: int = 0
    unsupported_outcomes: int = 0
    parse_targets: int = 0

    def add(self, other: "IngestionProcessingStats") -> "IngestionProcessingStats":
        return IngestionProcessingStats(
            parsed_records_created=self.parsed_records_created + other.parsed_records_created,
            warning_rows_created=self.warning_rows_created + other.warning_rows_created,
            error_rows_created=self.error_rows_created + other.error_rows_created,
            unsupported_outcomes=self.unsupported_outcomes + other.unsupported_outcomes,
            parse_targets=self.parse_targets + other.parse_targets,
        )


class IngestionCoordinator:
    def __init__(
        self,
        *,
        fetcher: HttpArtifactFetcher | None = None,
        archive_expander: ZipArchiveExpander | None = None,
        parser_registry: ParserRegistry | None = None,
        adapter_service: SourceAdapterService | None = None,
    ) -> None:
        self._fetcher = fetcher or HttpArtifactFetcher()
        self._archive = archive_expander or ZipArchiveExpander()
        self._registry = parser_registry or build_default_registry()
        self._adapters = adapter_service or SourceAdapterService()
        self._governance = SourceGovernanceService()

    def _ensure_pipeline(self, *, workspace: models.Workspace, key: str = "ingestion-runtime") -> models.OrchestrationPipeline:
        pipeline, _ = models.OrchestrationPipeline.objects.get_or_create(
            workspace=workspace,
            key=key,
            defaults={"name": "Ingestion Runtime", "enabled": True},
        )
        job_definition, _ = models.OrchestrationJobDefinition.objects.get_or_create(
            pipeline=pipeline,
            job_key="source_refresh",
            defaults={
                "stage_key": STAGE_PROPERTY_GRAPH_REBUILD,
                "name": "Source Refresh",
                "description": "Canonical source refresh/import execution entrypoint.",
                "handler_key": "platform.jobs.refresh_source",
                "enabled": True,
                "only_if_upstream_changed": False,
                "runs_per_jurisdiction": True,
                "runs_per_source": True,
                "concurrency_limit": 1,
                "retry_max_attempts": 1,
                "backoff_initial_seconds": 10,
                "backoff_max_seconds": 60,
                "backoff_multiplier": 2.0,
                "produces_artifact": True,
                "artifact_kind": "dataset_snapshot",
                "schedule_json": {"seeded": True, "kind": "manual"},
                "metadata_json": {"seeded_by": "IngestionCoordinator._ensure_pipeline"},
            },
        )
        if str(job_definition.stage_key or "") != STAGE_PROPERTY_GRAPH_REBUILD:
            job_definition.stage_key = STAGE_PROPERTY_GRAPH_REBUILD
            job_definition.save(update_fields=["stage_key", "updated_at"])
        models.OrchestrationJobSchedule.objects.get_or_create(
            job_definition=job_definition,
            schedule_key="manual_refresh",
            defaults={
                "schedule_kind": "manual",
                "enabled": True,
                "metadata_json": {"seeded_by": "IngestionCoordinator._ensure_pipeline"},
            },
        )
        return pipeline

    def _expire_stale_runs(
        self,
        *,
        workspace: models.Workspace,
        source_scope: str,
        exclude_run_id: str = "",
        stale_after_seconds: int = 1800,
    ) -> None:
        threshold = datetime.now(timezone.utc) - timedelta(seconds=max(60, int(stale_after_seconds)))
        qs = (
            models.OrchestrationRun.objects.filter(
                workspace=workspace,
                run_type="ingest.binary",
                status="running",
                scope_source=str(source_scope or "").strip(),
                started_at__lt=threshold,
            )
            .order_by("started_at")
        )
        if str(exclude_run_id or "").strip():
            qs = qs.exclude(id=str(exclude_run_id).strip())
        lifecycle = OrchestrationLifecycleService()
        for stale in qs:
            last_seen = stale.heartbeat_at or stale.updated_at or stale.started_at or stale.created_at
            if last_seen and last_seen >= threshold:
                continue
            job_rows = list(
                models.OrchestrationJobRun.objects.filter(run=stale).exclude(
                    status__in=["succeeded", "failed", "cancelled", "skipped", "stale"]
                )
            )
            if job_rows:
                for row in job_rows:
                    try:
                        lifecycle.mark_job_stale(job_run_id=str(row.id), reason="runtime_interrupted")
                    except Exception:
                        continue
                stale.refresh_from_db(fields=["status"])
                if stale.status != "running":
                    continue
            stale.status = "stale"
            stale.summary = "ingestion marked stale after runtime interruption"
            stale.completed_at = datetime.now(timezone.utc)
            stale.save(update_fields=["status", "summary", "completed_at", "updated_at"])

    def _job_run_for_source_refresh(self, *, run: models.OrchestrationRun) -> models.OrchestrationJobRun | None:
        return (
            models.OrchestrationJobRun.objects.filter(
                run=run,
                job_definition__job_key="source_refresh",
            )
            .select_related("job_definition")
            .first()
        )

    def _persist_ingestion_progress(
        self,
        *,
        run: models.OrchestrationRun,
        source_refresh_job: models.OrchestrationJobRun | None,
        ingest_meta: dict[str, Any],
        parsed_count: int,
        stats: IngestionProcessingStats,
        phase: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        run.summary = (
            f"ingestion {phase} ({parsed_count} parsed, "
            f"{stats.warning_rows_created} warnings, {stats.error_rows_created} errors, "
            f"{stats.unsupported_outcomes} unsupported)"
        )[:240]
        run.heartbeat_at = now
        run.metadata_json = {
            **(run.metadata_json if isinstance(run.metadata_json, dict) else {}),
            "ingestion": ingest_meta,
        }
        run.save(update_fields=["summary", "heartbeat_at", "metadata_json", "updated_at"])
        if source_refresh_job is not None:
            try:
                OrchestrationLifecycleService().mark_job_running(
                    job_run_id=str(source_refresh_job.id),
                    summary=run.summary,
                )
            except Exception:
                logger.exception(
                    "ingestion.coordinator.job_progress_heartbeat_failed",
                    extra={"job_run_id": str(source_refresh_job.id), "run_id": str(run.id)},
                )

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
        reprocess_unchanged: bool = False,
    ) -> IngestionExecutionResult:
        started_at = datetime.now(timezone.utc)
        workspace = source_connector.workspace
        self._expire_stale_runs(
            workspace=workspace,
            source_scope=source_scope,
            stale_after_seconds=max(300, int(timeout_seconds or 60) * 3),
        )
        run = self.create_ingest_run(
            workspace=workspace,
            source_connector=source_connector,
            jurisdiction=jurisdiction,
            source_scope=source_scope,
        )
        source_refresh_job = self._job_run_for_source_refresh(run=run)
        run.status = "running"
        run.started_at = run.started_at or started_at
        run.metadata_json = {
            **(run.metadata_json if isinstance(run.metadata_json, dict) else {}),
            "ingestion": {
                "fetch_attempted": False,
                "content_changed": True,
                "no_op_reason": "",
                "parse_ran": False,
                "outcome": "running",
            },
        }
        run.save(update_fields=["status", "started_at", "metadata_json", "updated_at"])
        if source_refresh_job is not None:
            try:
                OrchestrationLifecycleService().mark_job_running(job_run_id=str(source_refresh_job.id), summary="source refresh in progress")
            except Exception:
                logger.exception("ingestion.coordinator.job_running_failed", extra={"job_run_id": str(source_refresh_job.id)})
        warnings: list[str] = []
        stats = IngestionProcessingStats()
        parsed_count = 0
        artifact_row: models.IngestArtifactRecord | None = None
        try:
            governance_decision = self._governance.evaluate(source=source_connector, action="fetch_source")
            if governance_decision.decision != "allow":
                self._governance.emit_audit_event(
                    source=source_connector,
                    decision=governance_decision,
                    run_id=str(run.id),
                    metadata={"stage": "ingestion_precheck"},
                )
                ingest_meta = run.metadata_json.get("ingestion", {}) if isinstance(run.metadata_json, dict) else {}
                if not isinstance(ingest_meta, dict):
                    ingest_meta = {}
                ingest_meta["outcome"] = governance_decision.decision
                ingest_meta["governance_decision"] = governance_decision.as_dict()
                ingest_meta["fetch_attempted"] = False
                run.metadata_json = {**(run.metadata_json if isinstance(run.metadata_json, dict) else {}), "ingestion": ingest_meta}
                run.status = "failed" if governance_decision.decision == "deny" else "skipped"
                run.summary = governance_decision.message[:240]
                run.completed_at = datetime.now(timezone.utc)
                run.save(update_fields=["status", "summary", "metadata_json", "completed_at", "updated_at"])
                return IngestionExecutionResult(
                    run_id=str(run.id),
                    artifact_record_id="",
                    parsed_record_count=0,
                    warnings=(governance_decision.reason_code,),
                )
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
                artifact_row.save(update_fields=["metadata_json"])

            ingest_meta = run.metadata_json.get("ingestion", {}) if isinstance(run.metadata_json, dict) else {}
            if not isinstance(ingest_meta, dict):
                ingest_meta = {}
            ingest_meta["fetch_attempted"] = True
            ingest_meta["artifact_record_id"] = str(artifact_row.id)
            ingest_meta["artifact_sha256"] = str(artifact_row.sha256 or "")
            ingest_meta["content_changed"] = previous is None
            ingest_meta["deduped_from_artifact_id"] = str(previous.id) if previous else ""
            run.metadata_json = {**(run.metadata_json if isinstance(run.metadata_json, dict) else {}), "ingestion": ingest_meta}
            run.heartbeat_at = datetime.now(timezone.utc)
            run.save(update_fields=["metadata_json", "heartbeat_at", "updated_at"])

            if previous is not None and not reprocess_unchanged:
                ingest_meta["no_op_reason"] = "unchanged_artifact_sha256"
                ingest_meta["parse_ran"] = False
                ingest_meta["outcome"] = "no_op"
                run.status = "skipped"
                run.summary = "ingestion skipped (unchanged artifact content)"
                run.metrics_json = {
                    **(run.metrics_json if isinstance(run.metrics_json, dict) else {}),
                    "ingestion": {
                        "fetch_attempted": True,
                        "content_changed": False,
                        "parse_targets": 0,
                        "parsed_records_created": 0,
                        "warning_rows_created": 0,
                        "error_rows_created": 0,
                        "unsupported_outcomes": 0,
                    },
                }
                run.completed_at = datetime.now(timezone.utc)
                run.save(update_fields=["status", "summary", "metadata_json", "metrics_json", "completed_at", "updated_at"])
                if source_refresh_job is not None:
                    try:
                        OrchestrationLifecycleService().mark_job_skipped(
                            job_run_id=str(source_refresh_job.id),
                            reason="unchanged_artifact_sha256",
                            summary="Skipped because artifact content is unchanged.",
                        )
                    except Exception:
                        logger.exception("ingestion.coordinator.job_skipped_failed", extra={"job_run_id": str(source_refresh_job.id)})
                return IngestionExecutionResult(
                    run_id=str(run.id),
                    artifact_record_id=str(artifact_row.id),
                    parsed_record_count=0,
                    warnings=tuple(),
                )
            if previous is not None and reprocess_unchanged:
                ingest_meta["content_changed"] = False
                ingest_meta["no_op_reason"] = "unchanged_artifact_sha256_reprocessed"

            classified = classify_file(filename=fetch_result.original_filename, content_type=fetch_result.content_type)
            with open(fetch_result.local_path, "rb") as fp:
                raw_bytes = fp.read()

            ingest_meta["parse_ran"] = True
            if classified.kind == FILE_KIND_ZIP:
                members = self._archive.expand(parent_artifact=artifact_row, zip_bytes=raw_bytes)
                self._adapters.persist_zip_candidates(
                    source_connector=source_connector,
                    artifact=artifact_row,
                    members=[models.IngestArtifactMember.objects.get(id=item.member_id) for item in members],
                )
                grouped: dict[str, list[Any]] = {}
                for member in members:
                    grouped.setdefault(member.group_key or member.member_path, []).append(member)
                max_parse_targets = max(0, int(os.getenv("XYN_INGEST_MAX_PARSE_TARGETS", "0") or "0"))
                parse_target_limit_hit = False
                for _, rows in grouped.items():
                    if max_parse_targets and stats.parse_targets >= max_parse_targets:
                        parse_target_limit_hit = True
                        break
                    shp_member = next((row for row in rows if row.classified_type == FILE_KIND_SHP), None)
                    if shp_member is not None:
                        result = self._parse_grouped_shapefile(
                            workspace=workspace,
                            run=run,
                            source_connector=source_connector,
                            artifact_row=artifact_row,
                            members=rows,
                            warnings=warnings,
                        )
                        stats = stats.add(result)
                        parsed_count += result.parsed_records_created
                        self._persist_ingestion_progress(
                            run=run,
                            source_refresh_job=source_refresh_job,
                            ingest_meta=ingest_meta,
                            parsed_count=parsed_count,
                            stats=stats,
                            phase="parsing grouped members",
                        )
                        continue
                    for row in rows:
                        if max_parse_targets and stats.parse_targets >= max_parse_targets:
                            parse_target_limit_hit = True
                            break
                        result = self._parse_member(
                            workspace=workspace,
                            run=run,
                            source_connector=source_connector,
                            artifact_row=artifact_row,
                            member=models.IngestArtifactMember.objects.get(id=row.member_id),
                            content=row.raw_bytes,
                            warnings=warnings,
                        )
                        stats = stats.add(result)
                        parsed_count += result.parsed_records_created
                        self._persist_ingestion_progress(
                            run=run,
                            source_refresh_job=source_refresh_job,
                            ingest_meta=ingest_meta,
                            parsed_count=parsed_count,
                            stats=stats,
                            phase="parsing members",
                        )
                    if parse_target_limit_hit:
                        break
                if parse_target_limit_hit:
                    warnings.append(
                        f"zip parse truncated after {max_parse_targets} parse targets"
                    )
            else:
                result = self._parse_root_artifact(
                    workspace=workspace,
                    run=run,
                    source_connector=source_connector,
                    artifact_row=artifact_row,
                    kind=classified.kind,
                    filename=fetch_result.original_filename,
                    content=raw_bytes,
                    warnings=warnings,
                )
                stats = stats.add(result)
                parsed_count += result.parsed_records_created
                self._persist_ingestion_progress(
                    run=run,
                    source_refresh_job=source_refresh_job,
                    ingest_meta=ingest_meta,
                    parsed_count=parsed_count,
                    stats=stats,
                    phase="parsing artifact",
                )

            if parsed_count == 0 and (stats.warning_rows_created > 0 or stats.error_rows_created > 0):
                run.status = "failed" if stats.error_rows_created > 0 else "succeeded"
                ingest_meta["outcome"] = "failed" if run.status == "failed" else "partial"
            elif stats.warning_rows_created > 0 or stats.error_rows_created > 0 or stats.unsupported_outcomes > 0:
                run.status = "succeeded"
                ingest_meta["outcome"] = "partial"
            else:
                run.status = "succeeded"
                ingest_meta["outcome"] = "succeeded"
            run.summary = (
                f"ingestion completed ({parsed_count} parsed, "
                f"{stats.warning_rows_created} warnings, {stats.error_rows_created} errors, "
                f"{stats.unsupported_outcomes} unsupported)"
            )[:240]
            run.metrics_json = {
                **(run.metrics_json if isinstance(run.metrics_json, dict) else {}),
                "ingestion": {
                    "fetch_attempted": True,
                    "content_changed": bool(ingest_meta.get("content_changed", True)),
                    "parse_targets": stats.parse_targets,
                    "parsed_records_created": parsed_count,
                    "warning_rows_created": stats.warning_rows_created,
                    "error_rows_created": stats.error_rows_created,
                    "unsupported_outcomes": stats.unsupported_outcomes,
                },
            }
            run.metadata_json = {**(run.metadata_json if isinstance(run.metadata_json, dict) else {}), "ingestion": ingest_meta}
            run.completed_at = datetime.now(timezone.utc)
            run.save(update_fields=["status", "summary", "metrics_json", "metadata_json", "completed_at", "updated_at"])
            if source_refresh_job is not None:
                try:
                    OrchestrationLifecycleService().mark_job_succeeded(
                        job_run_id=str(source_refresh_job.id),
                        summary=run.summary,
                        metrics=run.metrics_json.get("ingestion") if isinstance(run.metrics_json, dict) else {},
                        output_change_token=str(artifact_row.sha256 or ""),
                        outputs=[
                            OutputRecord(
                                output_key="reconciled_state",
                                output_type="reconciled_state",
                                output_uri=str(artifact_row.artifact_uri or ""),
                                output_change_token=str(artifact_row.sha256 or ""),
                                metadata={
                                    "ingest_artifact_id": str(artifact_row.id),
                                    "source_connector_id": str(source_connector.id),
                                    "runtime_artifact_id": str(artifact_row.artifact_id),
                                },
                                payload={
                                    "reconciled_state_version": str(artifact_row.sha256 or ""),
                                    "normalized_snapshot_ref": str(artifact_row.artifact_uri or ""),
                                    "normalized_change_token": str(artifact_row.sha256 or ""),
                                    "artifact_record_id": str(artifact_row.id),
                                    "source_connector_id": str(source_connector.id),
                                },
                            )
                        ],
                    )
                except Exception:
                    logger.exception("ingestion.coordinator.job_success_failed", extra={"job_run_id": str(source_refresh_job.id)})
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
            run.completed_at = datetime.now(timezone.utc)
            meta = run.metadata_json if isinstance(run.metadata_json, dict) else {}
            ingest_meta = meta.get("ingestion") if isinstance(meta.get("ingestion"), dict) else {}
            ingest_meta["outcome"] = "failed"
            ingest_meta["fetch_attempted"] = bool(ingest_meta.get("fetch_attempted", False))
            if artifact_row is not None:
                ingest_meta["artifact_record_id"] = str(artifact_row.id)
            run.metadata_json = {**meta, "ingestion": ingest_meta}
            run.save(update_fields=["status", "error_text", "summary", "metadata_json", "completed_at", "updated_at"])
            if source_refresh_job is not None:
                try:
                    OrchestrationLifecycleService().mark_job_failed(
                        job_run_id=str(source_refresh_job.id),
                        summary="source refresh failed",
                        error_text=str(exc),
                        error_details={"exception": str(exc)},
                        retryable=False,
                    )
                except Exception:
                    logger.exception("ingestion.coordinator.job_failed_failed", extra={"job_run_id": str(source_refresh_job.id)})
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
    ) -> IngestionProcessingStats:
        parser = self._registry.resolve(kind)
        if parser is None:
            warnings.append(f"unsupported format: {kind}")
            return IngestionProcessingStats(parse_targets=1)
        target = ParseTarget(
            workspace_id=str(workspace.id),
            source_connector_id=str(source_connector.id),
            orchestration_run_id=str(run.id),
            artifact_record_id=str(artifact_row.id),
            source_path=filename,
            classified_kind=kind,
            target_type=TARGET_TYPE_FILE,
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
    ) -> IngestionProcessingStats:
        parser = self._registry.resolve(str(member.classified_type or ""))
        if parser is None:
            member.status = "unsupported"
            member.failure_reason = f"unsupported member type: {member.classified_type}"
            member.save(update_fields=["status", "failure_reason", "updated_at"])
            warnings.append(member.failure_reason)
            self._persist_outcome(
                workspace=workspace,
                run=run,
                source_connector=source_connector,
                artifact_row=artifact_row,
                member_row=member,
                outcome=ParseOutcome(
                    parser_name="unsupported",
                    parser_version="1",
                    normalization_version="0",
                    records=tuple(),
                    warnings=(member.failure_reason,),
                    issues=(
                        ParseIssue(
                            category=ISSUE_CATEGORY_UNSUPPORTED_FORMAT,
                            code="unsupported.member.kind",
                            message=member.failure_reason,
                            severity="warning",
                        ),
                    ),
                ),
            )
            return IngestionProcessingStats(parse_targets=1, warning_rows_created=1, unsupported_outcomes=1)
        target = ParseTarget(
            workspace_id=str(workspace.id),
            source_connector_id=str(source_connector.id),
            orchestration_run_id=str(run.id),
            artifact_record_id=str(artifact_row.id),
            member_id=str(member.id),
            source_path=str(member.member_path),
            classified_kind=str(member.classified_type or ""),
            target_type=TARGET_TYPE_FILE,
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
    ) -> IngestionProcessingStats:
        shp_member = next((row for row in members if row.classified_type == FILE_KIND_SHP), None)
        if shp_member is None:
            return IngestionProcessingStats()
        member_row = models.IngestArtifactMember.objects.get(id=shp_member.member_id)
        parser = self._registry.resolve(FILE_KIND_SHP)
        if parser is None:
            member_row.status = "unsupported"
            member_row.failure_reason = "grouped shapefile parser unavailable"
            member_row.save(update_fields=["status", "failure_reason", "updated_at"])
            warnings.append(member_row.failure_reason)
            return IngestionProcessingStats(parse_targets=1, warning_rows_created=1, unsupported_outcomes=1)
        target = ParseTarget(
            workspace_id=str(workspace.id),
            source_connector_id=str(source_connector.id),
            orchestration_run_id=str(run.id),
            artifact_record_id=str(artifact_row.id),
            member_id=str(member_row.id),
            source_path=str(member_row.member_path or ""),
            classified_kind=FILE_KIND_SHP,
            target_type=TARGET_TYPE_GROUPED,
            group_key=str(member_row.group_key or ""),
            grouped_member_ids=tuple(str(item.member_id) for item in members),
            grouped_member_paths=tuple(str(item.member_path) for item in members),
            metadata={"grouped_member_bytes": {str(item.member_path): bytes(item.raw_bytes) for item in members}},
        )
        outcome = parser.parse(target=target, stream=io.BytesIO(shp_member.raw_bytes))
        warnings.extend(list(outcome.warnings))
        result = self._persist_outcome(
            workspace=workspace,
            run=run,
            source_connector=source_connector,
            artifact_row=artifact_row,
            member_row=member_row,
            outcome=outcome,
            target_metadata={
                "target_type": TARGET_TYPE_GROUPED,
                "group_member_ids": list(target.grouped_member_ids),
                "group_member_paths": list(target.grouped_member_paths),
            },
        )
        unsupported_categories = {
            ISSUE_CATEGORY_UNSUPPORTED_FORMAT,
            ISSUE_CATEGORY_NOT_IMPLEMENTED,
            ISSUE_CATEGORY_NOT_INSTALLED,
        }
        if any(str(issue.category) in unsupported_categories for issue in outcome.issues):
            for item in members:
                row = models.IngestArtifactMember.objects.get(id=item.member_id)
                row.status = "unsupported"
                row.failure_reason = "; ".join(outcome.warnings) or "grouped shapefile not parsed"
                row.save(update_fields=["status", "failure_reason", "updated_at"])
        return result

    def _persist_outcome(
        self,
        *,
        workspace: models.Workspace,
        run: models.OrchestrationRun,
        source_connector: models.SourceConnector,
        artifact_row: models.IngestArtifactRecord,
        member_row: models.IngestArtifactMember | None,
        outcome: ParseOutcome,
        target_metadata: dict[str, Any] | None = None,
    ) -> IngestionProcessingStats:
        base_meta = target_metadata if isinstance(target_metadata, dict) else {}
        if "target_type" not in base_meta:
            base_meta = {**base_meta, "target_type": TARGET_TYPE_FILE}
        parsed_created = 0
        warning_rows_created = 0
        error_rows_created = 0
        unsupported_outcomes = 0
        if not outcome.records and (outcome.warnings or getattr(outcome, "issues", tuple())):
            issue_payload = [
                {
                    "category": str(issue.category),
                    "code": str(issue.code),
                    "message": str(issue.message),
                    "severity": str(issue.severity),
                    "details": issue.details if isinstance(issue.details, dict) else {},
                }
                for issue in getattr(outcome, "issues", tuple())
            ]
            issue_messages = [str(item.get("message") or "") for item in issue_payload if str(item.get("message") or "").strip()]
            has_error_issue = any(str(item.get("severity")) == "error" for item in issue_payload)
            failure_reason = "; ".join(list(outcome.warnings) or issue_messages) or "parser outcome without records"
            unsupported_outcomes = sum(
                1
                for issue in outcome.issues
                if str(issue.category) in {ISSUE_CATEGORY_UNSUPPORTED_FORMAT, ISSUE_CATEGORY_NOT_IMPLEMENTED, ISSUE_CATEGORY_NOT_INSTALLED}
            )
            key = hashlib.sha256(
                (
                    f"{workspace.id}|{source_connector.id}|{artifact_row.sha256}|"
                    f"{member_row.member_path if member_row else artifact_row.original_filename}|"
                    f"{outcome.parser_name}|warnings|{hashlib.sha256(failure_reason.encode('utf-8')).hexdigest()}"
                ).encode("utf-8")
            ).hexdigest()
            _, created = models.IngestParsedRecord.objects.get_or_create(
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
                    "status": "error" if has_error_issue else "warning",
                    "failure_reason": failure_reason,
                    "provenance_json": {
                        **base_meta,
                        "target_type": str(base_meta.get("target_type") or TARGET_TYPE_FILE),
                        "group_member_ids": list(base_meta.get("group_member_ids", [])),
                        "group_member_paths": list(base_meta.get("group_member_paths", [])),
                    },
                    "warnings_json": issue_payload,
                },
            )
            if created:
                if has_error_issue:
                    error_rows_created += 1
                else:
                    warning_rows_created += 1
            return IngestionProcessingStats(
                parsed_records_created=0,
                warning_rows_created=warning_rows_created,
                error_rows_created=error_rows_created,
                unsupported_outcomes=unsupported_outcomes,
                parse_targets=1,
            )
        issue_payload = [
            {
                "category": str(issue.category),
                "code": str(issue.code),
                "message": str(issue.message),
                "severity": str(issue.severity),
                "details": issue.details if isinstance(issue.details, dict) else {},
            }
            for issue in getattr(outcome, "issues", tuple())
        ]
        has_error_issue = any(str(item.get("severity")) == "error" for item in issue_payload)
        heartbeat_interval = 500
        processed_count = 0
        for record in outcome.records:
            processed_count += 1
            normalized_hash = hashlib.sha256(str(record.normalized_payload).encode("utf-8")).hexdigest()
            key_raw = "|".join(
                [
                    str(workspace.id),
                    str(source_connector.id or ""),
                    str(artifact_row.sha256 or ""),
                    str(member_row.member_path if member_row else artifact_row.original_filename),
                    str(outcome.parser_name),
                    str(record.record_index or 0),
                    normalized_hash,
                ]
            )
            idempotency_key = hashlib.sha256(key_raw.encode("utf-8")).hexdigest()
            parsed_row, created = models.IngestParsedRecord.objects.get_or_create(
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
                    "provenance_json": {
                        **base_meta,
                        **record.provenance,
                        "target_type": str(base_meta.get("target_type") or TARGET_TYPE_FILE),
                    },
                    "warnings_json": [*list(record.warnings), *issue_payload],
                    "status": "error" if has_error_issue else str(record.status or "ok"),
                },
            )
            if created:
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
                parsed_created += 1
                self._adapters.adapt_parsed_record(source_connector=source_connector, parsed_row=parsed_row)
            if processed_count % heartbeat_interval == 0:
                now = datetime.now(timezone.utc)
                summary = (
                    f"ingestion persisting parsed rows ({processed_count} processed, {parsed_created} new, "
                    f"{warning_rows_created} warnings, {error_rows_created} errors)"
                )[:240]
                models.OrchestrationRun.objects.filter(id=run.id, status="running").update(
                    summary=summary,
                    heartbeat_at=now,
                    updated_at=now,
                )
        if member_row is not None:
            member_row.status = "parsed"
            member_row.failure_reason = ""
            member_row.save(update_fields=["status", "failure_reason", "updated_at"])
        return IngestionProcessingStats(
            parsed_records_created=parsed_created,
            warning_rows_created=warning_rows_created,
            error_rows_created=error_rows_created,
            unsupported_outcomes=unsupported_outcomes,
            parse_targets=1,
        )
