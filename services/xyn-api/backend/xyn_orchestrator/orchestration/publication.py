from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from xyn_orchestrator.models import (
    OrchestrationJobRun,
    OrchestrationPipeline,
    OrchestrationStagePublication,
    ReconciledStateCurrentPointer,
)

from .domain_events import DomainEventService
from .definitions import (
    STAGE_PROPERTY_GRAPH_REBUILD,
    STAGE_RULE_EVALUATION,
    STAGE_SIGNAL_MATCHING,
    STAGE_SOURCE_NORMALIZATION,
)


@dataclass(frozen=True)
class EvaluationReadiness:
    ready: bool
    reason: str
    publication_id: str = ""
    reconciled_state_version: str = ""
    signal_set_version: str = ""


class StagePublicationService:
    """Stage publication contract for changed-data downstream readiness."""

    @staticmethod
    def _extract_marker(outputs: list[dict[str, Any]], *, keys: tuple[str, ...]) -> str:
        for item in outputs:
            if not isinstance(item, dict):
                continue
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            for key in keys:
                value = str(payload.get(key) or metadata.get(key) or item.get(key) or "").strip()
                if value:
                    return value
        return ""

    @staticmethod
    def _serialize_outputs(job_run: OrchestrationJobRun) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for output in job_run.outputs.all().order_by("created_at", "output_key"):
            rows.append(
                {
                    "output_key": str(output.output_key or ""),
                    "output_type": str(output.output_type or ""),
                    "output_uri": str(output.output_uri or ""),
                    "output_change_token": str(output.output_change_token or ""),
                    "payload": output.payload_json if isinstance(output.payload_json, dict) else {},
                    "metadata": output.metadata_json if isinstance(output.metadata_json, dict) else {},
                }
            )
        return rows

    def latest_reconciled_publication(
        self,
        *,
        workspace_id: str,
        jurisdiction: str = "",
        source: str = "",
        pipeline_id: str = "",
        pipeline_key: str = "",
    ) -> OrchestrationStagePublication | None:
        qs = OrchestrationStagePublication.objects.filter(
            workspace_id=workspace_id,
            stage_key=STAGE_PROPERTY_GRAPH_REBUILD,
            stage_state="published",
        ).exclude(reconciled_state_version="")
        if pipeline_id:
            qs = qs.filter(pipeline_id=pipeline_id)
        elif pipeline_key:
            pipeline = OrchestrationPipeline.objects.filter(
                workspace_id=workspace_id,
                key=str(pipeline_key or "").strip(),
            ).first()
            if pipeline is None:
                return None
            qs = qs.filter(pipeline=pipeline)
        qs = qs.filter(
            scope_jurisdiction=str(jurisdiction or "").strip(),
            scope_source=str(source or "").strip(),
        )
        return qs.order_by("-published_at", "-updated_at").first()

    def evaluation_readiness(
        self,
        *,
        workspace_id: str,
        jurisdiction: str = "",
        source: str = "",
        pipeline_id: str = "",
        pipeline_key: str = "",
        required_reconciled_state_version: str = "",
    ) -> EvaluationReadiness:
        required_version = str(required_reconciled_state_version or "").strip()
        if required_version:
            published = OrchestrationStagePublication.objects.filter(
                workspace_id=workspace_id,
                stage_key=STAGE_PROPERTY_GRAPH_REBUILD,
                stage_state="published",
                scope_jurisdiction=str(jurisdiction or "").strip(),
                scope_source=str(source or "").strip(),
                reconciled_state_version=required_version,
            )
            if pipeline_id:
                published = published.filter(pipeline_id=pipeline_id)
            elif pipeline_key:
                pipeline = OrchestrationPipeline.objects.filter(
                    workspace_id=workspace_id,
                    key=str(pipeline_key or "").strip(),
                ).first()
                if pipeline is None:
                    return EvaluationReadiness(
                        ready=False,
                        reason="reconciled_state_not_published",
                    )
                published = published.filter(pipeline=pipeline)
            row = published.order_by("-published_at", "-updated_at").first()
            if row is None:
                return EvaluationReadiness(
                    ready=False,
                    reason="reconciled_state_version_not_published",
                )
            return EvaluationReadiness(
                ready=True,
                reason="ready",
                publication_id=str(row.id),
                reconciled_state_version=str(row.reconciled_state_version or ""),
                signal_set_version=str(row.signal_set_version or ""),
            )

        pointer = ReconciledStateCurrentPointer.objects.filter(
            workspace_id=workspace_id,
            scope_jurisdiction=str(jurisdiction or "").strip(),
            scope_source=str(source or "").strip(),
        )
        if pipeline_id:
            pointer = pointer.filter(pipeline_id=pipeline_id)
        elif pipeline_key:
            pipeline = OrchestrationPipeline.objects.filter(
                workspace_id=workspace_id,
                key=str(pipeline_key or "").strip(),
            ).first()
            if pipeline is None:
                return EvaluationReadiness(ready=False, reason="reconciled_state_not_published")
            pointer = pointer.filter(pipeline=pipeline)
        pointer_row = pointer.order_by("-promoted_at", "-updated_at").first()
        if pointer_row and pointer_row.reconciled_state_version:
            return EvaluationReadiness(
                ready=True,
                reason="ready",
                publication_id=str(pointer_row.publication_id or ""),
                reconciled_state_version=str(pointer_row.reconciled_state_version or ""),
                signal_set_version=str(getattr(pointer_row.publication, "signal_set_version", "") or ""),
            )

        publication = self.latest_reconciled_publication(
            workspace_id=workspace_id,
            jurisdiction=jurisdiction,
            source=source,
            pipeline_id=pipeline_id,
            pipeline_key=pipeline_key,
        )
        if publication is None:
            return EvaluationReadiness(ready=False, reason="reconciled_state_not_published")
        return EvaluationReadiness(
            ready=True,
            reason="ready",
            publication_id=str(publication.id),
            reconciled_state_version=str(publication.reconciled_state_version or ""),
            signal_set_version=str(publication.signal_set_version or ""),
        )

    def promote_reconciled_publication(
        self, *, publication: OrchestrationStagePublication
    ) -> ReconciledStateCurrentPointer:
        if str(publication.stage_key or "") != STAGE_PROPERTY_GRAPH_REBUILD:
            raise ValueError("Only property_graph_rebuild publications can be promoted.")
        if str(publication.stage_state or "") != "published":
            raise ValueError("Publication is not marked as published.")
        version = str(publication.reconciled_state_version or "").strip()
        if not version:
            raise ValueError("Publication does not include a reconciled_state_version.")

        pointer, _created = ReconciledStateCurrentPointer.objects.update_or_create(
            workspace_id=publication.workspace_id,
            pipeline_id=publication.pipeline_id,
            scope_jurisdiction=str(publication.scope_jurisdiction or "").strip(),
            scope_source=str(publication.scope_source or "").strip(),
            defaults={
                "publication": publication,
                "reconciled_state_version": version,
                "promoted_at": timezone.now(),
                "metadata_json": {
                    "publication_id": str(publication.id),
                    "run_id": str(publication.run_id),
                    "job_run_id": str(publication.job_run_id),
                },
            },
        )
        return pointer

    def promote_reconciled_state_version(
        self,
        *,
        workspace_id: str,
        pipeline_id: str = "",
        pipeline_key: str = "",
        jurisdiction: str = "",
        source: str = "",
        reconciled_state_version: str,
    ) -> ReconciledStateCurrentPointer:
        version = str(reconciled_state_version or "").strip()
        if not version:
            raise ValueError("reconciled_state_version is required.")

        qs = OrchestrationStagePublication.objects.filter(
            workspace_id=workspace_id,
            stage_key=STAGE_PROPERTY_GRAPH_REBUILD,
            stage_state="published",
            scope_jurisdiction=str(jurisdiction or "").strip(),
            scope_source=str(source or "").strip(),
            reconciled_state_version=version,
        )
        if pipeline_id:
            qs = qs.filter(pipeline_id=pipeline_id)
        elif pipeline_key:
            pipeline = OrchestrationPipeline.objects.filter(
                workspace_id=workspace_id,
                key=str(pipeline_key or "").strip(),
            ).first()
            if pipeline is None:
                raise ValueError("Pipeline not found for promotion.")
            qs = qs.filter(pipeline=pipeline)

        publication = qs.order_by("-published_at", "-updated_at").first()
        if publication is None:
            raise ValueError("Reconciled publication not found for promotion.")
        return self.promote_reconciled_publication(publication=publication)

    @transaction.atomic
    def record_stage_publication(self, *, job_run: OrchestrationJobRun) -> OrchestrationStagePublication | None:
        if str(job_run.status) != "succeeded":
            return None

        stage_key = str(job_run.job_definition.stage_key or "").strip()
        if stage_key not in {
            STAGE_SOURCE_NORMALIZATION,
            STAGE_PROPERTY_GRAPH_REBUILD,
            STAGE_SIGNAL_MATCHING,
            STAGE_RULE_EVALUATION,
        }:
            return None

        outputs = self._serialize_outputs(job_run)

        normalized_snapshot_ref = self._extract_marker(
            outputs,
            keys=("normalized_snapshot_ref", "output_uri"),
        )
        normalized_change_token = self._extract_marker(
            outputs,
            keys=("normalized_change_token", "output_change_token"),
        ) or str(job_run.output_change_token or "").strip()

        reconciled_state_version = self._extract_marker(
            outputs,
            keys=("reconciled_state_version", "published_state_version", "entity_graph_version", "output_change_token"),
        )
        signal_set_version = self._extract_marker(
            outputs,
            keys=("signal_set_version", "output_change_token"),
        )
        if stage_key == STAGE_SIGNAL_MATCHING and not signal_set_version:
            signal_set_version = str(job_run.output_change_token or "").strip()

        if stage_key == STAGE_PROPERTY_GRAPH_REBUILD and not reconciled_state_version:
            reconciled_state_version = str(job_run.output_change_token or "").strip() or f"{job_run.run_id}:{job_run.id}"

        if stage_key == STAGE_SIGNAL_MATCHING and not reconciled_state_version:
            latest = self.latest_reconciled_publication(
                workspace_id=str(job_run.workspace_id),
                pipeline_id=str(job_run.pipeline_id),
                jurisdiction=str(job_run.scope_jurisdiction or ""),
                source=str(job_run.scope_source or ""),
            )
            if latest is not None:
                reconciled_state_version = str(latest.reconciled_state_version or "")

        stage_state = "completed"
        if stage_key == STAGE_PROPERTY_GRAPH_REBUILD and reconciled_state_version:
            stage_state = "published"
        if stage_key == STAGE_SIGNAL_MATCHING and signal_set_version:
            stage_state = "published"

        publication, _created = OrchestrationStagePublication.objects.update_or_create(
            job_run=job_run,
            defaults={
                "workspace_id": job_run.workspace_id,
                "pipeline_id": job_run.pipeline_id,
                "run_id": job_run.run_id,
                "stage_key": stage_key,
                "stage_state": stage_state,
                "scope_jurisdiction": str(job_run.scope_jurisdiction or "").strip(),
                "scope_source": str(job_run.scope_source or "").strip(),
                "normalized_snapshot_ref": normalized_snapshot_ref,
                "normalized_change_token": normalized_change_token,
                "reconciled_state_version": reconciled_state_version,
                "signal_set_version": signal_set_version,
                "publication_metadata_json": {
                    "job_key": str(job_run.job_definition.job_key or ""),
                    "run_id": str(job_run.run_id),
                    "job_run_id": str(job_run.id),
                },
            },
        )
        if stage_key == STAGE_SIGNAL_MATCHING and publication.signal_set_version and publication.reconciled_state_version:
            (
                OrchestrationStagePublication.objects.filter(
                    id=publication.id,
                ).update(
                    stage_state="published",
                )
            )
            publication.refresh_from_db()
        if stage_key == STAGE_PROPERTY_GRAPH_REBUILD and publication.stage_state == "published":
            self.promote_reconciled_publication(publication=publication)
        DomainEventService().emit_for_stage_publication(publication)
        return publication
