from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from xyn_orchestrator.models import OrchestrationStagePublication, PlatformDomainEvent

from .definitions import STAGE_PROPERTY_GRAPH_REBUILD, STAGE_SIGNAL_MATCHING, STAGE_SOURCE_NORMALIZATION

EVENT_SOURCE_NORMALIZED = "source_normalized"
EVENT_RECONCILED_STATE_PUBLISHED = "reconciled_state_published"
EVENT_SIGNAL_SET_PUBLISHED = "signal_set_published"
EVENT_EVALUATION_READY = "evaluation_ready"


@dataclass(frozen=True)
class DomainEventInput:
    workspace_id: str
    event_type: str
    idempotency_key: str
    stage_key: str = ""
    pipeline_id: str = ""
    run_id: str = ""
    job_run_id: str = ""
    publication_id: str = ""
    scope_jurisdiction: str = ""
    scope_source: str = ""
    subject_ref: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    normalized_snapshot_ref: str = ""
    normalized_change_token: str = ""
    reconciled_state_version: str = ""
    signal_set_version: str = ""
    correlation_id: str = ""
    chain_id: str = ""


@dataclass(frozen=True)
class DomainEventQuery:
    workspace_id: str
    event_type: str = ""
    stage_key: str = ""
    pipeline_id: str = ""
    jurisdiction: str = ""
    source: str = ""
    reconciled_state_version: str = ""
    signal_set_version: str = ""
    run_id: str = ""
    publication_id: str = ""
    chain_id: str = ""
    correlation_id: str = ""
    since: datetime | None = None
    limit: int = 200


class DomainEventService:
    """Durable outbox-style domain event recording for publication transitions."""

    @staticmethod
    def _safe_dict(value: dict[str, Any] | None) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _normalize(value: str) -> str:
        return str(value or "").strip()

    @staticmethod
    def _event_token(publication: OrchestrationStagePublication, *, event_type: str) -> str:
        if event_type == EVENT_SOURCE_NORMALIZED:
            return (
                str(publication.normalized_change_token or "").strip()
                or str(publication.normalized_snapshot_ref or "").strip()
                or str(publication.job_run_id)
            )
        if event_type in {EVENT_RECONCILED_STATE_PUBLISHED, EVENT_EVALUATION_READY}:
            return str(publication.reconciled_state_version or "").strip() or str(publication.job_run_id)
        if event_type == EVENT_SIGNAL_SET_PUBLISHED:
            return str(publication.signal_set_version or "").strip() or str(publication.job_run_id)
        return str(publication.job_run_id)

    @classmethod
    def _idempotency_key_for_publication(cls, *, publication: OrchestrationStagePublication, event_type: str) -> str:
        token = cls._event_token(publication, event_type=event_type)
        return "|".join(
            [
                "stage-publication-event",
                str(event_type),
                str(publication.workspace_id),
                str(publication.pipeline_id),
                str(publication.stage_key or ""),
                str(publication.scope_jurisdiction or ""),
                str(publication.scope_source or ""),
                token,
            ]
        )

    @transaction.atomic
    def record(self, payload: DomainEventInput) -> PlatformDomainEvent:
        workspace_id = self._normalize(payload.workspace_id)
        event_type = self._normalize(payload.event_type)
        idempotency_key = self._normalize(payload.idempotency_key)
        if not workspace_id:
            raise ValueError("workspace_id is required")
        if not event_type:
            raise ValueError("event_type is required")

        if idempotency_key:
            existing = PlatformDomainEvent.objects.filter(
                workspace_id=workspace_id,
                idempotency_key=idempotency_key,
            ).first()
            if existing is not None:
                return existing

        try:
            return PlatformDomainEvent.objects.create(
                workspace_id=workspace_id,
                pipeline_id=self._normalize(payload.pipeline_id) or None,
                run_id=self._normalize(payload.run_id) or None,
                job_run_id=self._normalize(payload.job_run_id) or None,
                publication_id=self._normalize(payload.publication_id) or None,
                event_type=event_type,
                stage_key=self._normalize(payload.stage_key),
                scope_jurisdiction=self._normalize(payload.scope_jurisdiction),
                scope_source=self._normalize(payload.scope_source),
                subject_ref_json=self._safe_dict(payload.subject_ref),
                payload_json=self._safe_dict(payload.payload),
                metadata_json=self._safe_dict(payload.metadata),
                normalized_snapshot_ref=self._normalize(payload.normalized_snapshot_ref),
                normalized_change_token=self._normalize(payload.normalized_change_token),
                reconciled_state_version=self._normalize(payload.reconciled_state_version),
                signal_set_version=self._normalize(payload.signal_set_version),
                correlation_id=self._normalize(payload.correlation_id),
                chain_id=self._normalize(payload.chain_id),
                idempotency_key=idempotency_key,
            )
        except IntegrityError:
            if not idempotency_key:
                raise
            existing = PlatformDomainEvent.objects.filter(
                workspace_id=workspace_id,
                idempotency_key=idempotency_key,
            ).first()
            if existing is None:
                raise
            return existing

    def list_events(self, query: DomainEventQuery) -> QuerySet[PlatformDomainEvent]:
        qs = PlatformDomainEvent.objects.filter(workspace_id=self._normalize(query.workspace_id))
        if query.event_type:
            qs = qs.filter(event_type=self._normalize(query.event_type))
        if query.stage_key:
            qs = qs.filter(stage_key=self._normalize(query.stage_key))
        if query.pipeline_id:
            qs = qs.filter(pipeline_id=self._normalize(query.pipeline_id))
        if query.jurisdiction:
            qs = qs.filter(scope_jurisdiction=self._normalize(query.jurisdiction))
        if query.source:
            qs = qs.filter(scope_source=self._normalize(query.source))
        if query.reconciled_state_version:
            qs = qs.filter(reconciled_state_version=self._normalize(query.reconciled_state_version))
        if query.signal_set_version:
            qs = qs.filter(signal_set_version=self._normalize(query.signal_set_version))
        if query.run_id:
            qs = qs.filter(run_id=self._normalize(query.run_id))
        if query.publication_id:
            qs = qs.filter(publication_id=self._normalize(query.publication_id))
        if query.correlation_id:
            qs = qs.filter(correlation_id=self._normalize(query.correlation_id))
        if query.chain_id:
            qs = qs.filter(chain_id=self._normalize(query.chain_id))
        if query.since:
            qs = qs.filter(created_at__gte=query.since)
        limit = max(1, min(int(query.limit or 200), 1000))
        return qs.order_by("-created_at", "-id")[:limit]

    def emit_for_stage_publication(self, publication: OrchestrationStagePublication) -> list[PlatformDomainEvent]:
        stage = str(publication.stage_key or "").strip()
        events: list[PlatformDomainEvent] = []

        def _record(event_type: str) -> PlatformDomainEvent:
            return self.record(
                DomainEventInput(
                    workspace_id=str(publication.workspace_id),
                    pipeline_id=str(publication.pipeline_id),
                    run_id=str(publication.run_id),
                    job_run_id=str(publication.job_run_id),
                    publication_id=str(publication.id),
                    event_type=event_type,
                    idempotency_key=self._idempotency_key_for_publication(publication=publication, event_type=event_type),
                    stage_key=stage,
                    scope_jurisdiction=str(publication.scope_jurisdiction or ""),
                    scope_source=str(publication.scope_source or ""),
                    normalized_snapshot_ref=str(publication.normalized_snapshot_ref or ""),
                    normalized_change_token=str(publication.normalized_change_token or ""),
                    reconciled_state_version=str(publication.reconciled_state_version or ""),
                    signal_set_version=str(publication.signal_set_version or ""),
                    correlation_id=str(getattr(publication.run, "correlation_id", "") or ""),
                    chain_id=str(getattr(publication.run, "chain_id", "") or ""),
                    subject_ref={
                        "kind": "orchestration_stage_publication",
                        "id": str(publication.id),
                        "stage_key": stage,
                        "workspace_id": str(publication.workspace_id),
                        "pipeline_id": str(publication.pipeline_id),
                        "run_id": str(publication.run_id),
                        "job_run_id": str(publication.job_run_id),
                    },
                    payload={
                        "stage_key": stage,
                        "stage_state": str(publication.stage_state or ""),
                        "normalized_snapshot_ref": str(publication.normalized_snapshot_ref or ""),
                        "normalized_change_token": str(publication.normalized_change_token or ""),
                        "reconciled_state_version": str(publication.reconciled_state_version or ""),
                        "signal_set_version": str(publication.signal_set_version or ""),
                    },
                )
            )

        if stage == STAGE_SOURCE_NORMALIZATION and (
            publication.normalized_change_token or publication.normalized_snapshot_ref
        ):
            events.append(_record(EVENT_SOURCE_NORMALIZED))

        if (
            stage == STAGE_PROPERTY_GRAPH_REBUILD
            and str(publication.stage_state or "") == "published"
            and str(publication.reconciled_state_version or "").strip()
        ):
            events.append(_record(EVENT_RECONCILED_STATE_PUBLISHED))
            events.append(_record(EVENT_EVALUATION_READY))

        if (
            stage == STAGE_SIGNAL_MATCHING
            and str(publication.stage_state or "") == "published"
            and str(publication.signal_set_version or "").strip()
        ):
            events.append(_record(EVENT_SIGNAL_SET_PUBLISHED))

        return events
