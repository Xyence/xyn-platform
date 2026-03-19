from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models import Q
from django.db.models import QuerySet

from xyn_orchestrator.models import OrchestrationRun, PlatformAuditEvent, ProvenanceLink, Workspace

from .interfaces import ObjectRef, normalize_object_ref


def _ref_payload(ref: ObjectRef | None) -> dict[str, Any]:
    if ref is None:
        return {}
    normalized = normalize_object_ref(ref)
    return {
        "object_family": normalized.object_family,
        "object_id": normalized.object_id,
        "workspace_id": normalized.workspace_id or None,
        "namespace": normalized.namespace or "",
        "attributes": normalized.attributes if isinstance(normalized.attributes, dict) else {},
    }


class ProvenanceRepository:
    @transaction.atomic
    def create_audit_event(
        self,
        *,
        workspace_id: str,
        event_type: str,
        subject_ref: ObjectRef,
        summary: str,
        reason: str,
        actor_ref: ObjectRef | None,
        cause_ref: ObjectRef | None,
        metadata: dict[str, Any],
        run_id: str = "",
        correlation_id: str = "",
        chain_id: str = "",
    ) -> PlatformAuditEvent:
        workspace = Workspace.objects.get(id=workspace_id)
        run = OrchestrationRun.objects.filter(id=run_id, workspace=workspace).first() if run_id else None
        normalized_subject = normalize_object_ref(subject_ref)
        payload_subject = _ref_payload(normalized_subject)
        payload_actor = _ref_payload(actor_ref)
        payload_cause = _ref_payload(cause_ref)
        return PlatformAuditEvent.objects.create(
            workspace=workspace,
            event_type=str(event_type or "").strip(),
            subject_type=normalized_subject.object_family,
            subject_id=normalized_subject.object_id,
            subject_namespace=normalized_subject.namespace,
            subject_ref_json=payload_subject,
            actor_type=str(payload_actor.get("object_family") or "").strip(),
            actor_id=str(payload_actor.get("object_id") or "").strip(),
            actor_namespace=str(payload_actor.get("namespace") or "").strip(),
            actor_ref_json=payload_actor,
            cause_type=str(payload_cause.get("object_family") or "").strip(),
            cause_id=str(payload_cause.get("object_id") or "").strip(),
            cause_namespace=str(payload_cause.get("namespace") or "").strip(),
            cause_ref_json=payload_cause,
            summary=str(summary or "").strip(),
            reason=str(reason or "").strip(),
            metadata_json=metadata if isinstance(metadata, dict) else {},
            run=run,
            correlation_id=str(correlation_id or "").strip(),
            chain_id=str(chain_id or "").strip(),
        )

    @transaction.atomic
    def create_provenance_link(
        self,
        *,
        workspace_id: str,
        relationship_type: str,
        source_ref: ObjectRef,
        target_ref: ObjectRef,
        reason: str,
        explanation: dict[str, Any],
        metadata: dict[str, Any],
        origin_event_id: str = "",
        run_id: str = "",
        correlation_id: str = "",
        chain_id: str = "",
    ) -> ProvenanceLink:
        workspace = Workspace.objects.get(id=workspace_id)
        run = OrchestrationRun.objects.filter(id=run_id, workspace=workspace).first() if run_id else None
        origin_event = PlatformAuditEvent.objects.filter(id=origin_event_id, workspace=workspace).first() if origin_event_id else None
        normalized_source = normalize_object_ref(source_ref)
        normalized_target = normalize_object_ref(target_ref)
        return ProvenanceLink.objects.create(
            workspace=workspace,
            relationship_type=str(relationship_type or "").strip(),
            source_type=normalized_source.object_family,
            source_id=normalized_source.object_id,
            source_namespace=normalized_source.namespace,
            source_ref_json=_ref_payload(normalized_source),
            target_type=normalized_target.object_family,
            target_id=normalized_target.object_id,
            target_namespace=normalized_target.namespace,
            target_ref_json=_ref_payload(normalized_target),
            reason=str(reason or "").strip(),
            explanation_json=explanation if isinstance(explanation, dict) else {},
            metadata_json=metadata if isinstance(metadata, dict) else {},
            origin_event=origin_event,
            run=run,
            correlation_id=str(correlation_id or "").strip(),
            chain_id=str(chain_id or "").strip(),
        )

    def audit_history(
        self,
        *,
        workspace_id: str,
        object_type: str,
        object_id: str,
    ) -> QuerySet[PlatformAuditEvent]:
        return (
            PlatformAuditEvent.objects.filter(
                workspace_id=workspace_id,
                subject_type=str(object_type or "").strip().lower(),
                subject_id=str(object_id or "").strip(),
            )
            .select_related("run")
            .order_by("-created_at", "-id")
        )

    def provenance_for_object(
        self,
        *,
        workspace_id: str,
        object_type: str,
        object_id: str,
        direction: str,
    ) -> QuerySet[ProvenanceLink]:
        base = ProvenanceLink.objects.filter(workspace_id=workspace_id).select_related("origin_event", "run")
        normalized_type = str(object_type or "").strip().lower()
        normalized_id = str(object_id or "").strip()
        if direction == "upstream":
            return base.filter(target_type=normalized_type, target_id=normalized_id).order_by("-created_at", "-id")
        if direction == "downstream":
            return base.filter(source_type=normalized_type, source_id=normalized_id).order_by("-created_at", "-id")
        return base.filter(
            Q(source_type=normalized_type, source_id=normalized_id)
            | Q(target_type=normalized_type, target_id=normalized_id)
        ).order_by("-created_at", "-id")
