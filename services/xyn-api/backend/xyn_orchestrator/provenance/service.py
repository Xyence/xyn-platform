from __future__ import annotations

from typing import Any

from xyn_orchestrator.models import PlatformAuditEvent, ProvenanceLink

from .interfaces import (
    PROVENANCE_DIRECTIONS,
    AuditEventInput,
    AuditWithProvenanceInput,
    ObjectRef,
    ProvenanceLinkInput,
    normalize_object_ref,
)
from .repository import ProvenanceRepository


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


class ProvenanceService:
    def __init__(self, *, repository: ProvenanceRepository | None = None):
        self._repository = repository or ProvenanceRepository()

    def record_audit_event(self, payload: AuditEventInput) -> PlatformAuditEvent:
        workspace_id = str(payload.workspace_id or "").strip()
        if not workspace_id:
            raise ValueError("workspace_id is required")
        event_type = str(payload.event_type or "").strip().lower()
        if not event_type:
            raise ValueError("event_type is required")
        subject_ref = normalize_object_ref(payload.subject_ref)
        if not subject_ref.object_family or not subject_ref.object_id:
            raise ValueError("subject_ref.object_family and subject_ref.object_id are required")
        return self._repository.create_audit_event(
            workspace_id=workspace_id,
            event_type=event_type,
            subject_ref=subject_ref,
            summary=str(payload.summary or "").strip(),
            reason=str(payload.reason or "").strip(),
            actor_ref=normalize_object_ref(payload.actor_ref) if payload.actor_ref else None,
            cause_ref=normalize_object_ref(payload.cause_ref) if payload.cause_ref else None,
            metadata=_as_dict(payload.metadata),
            run_id=str(payload.run_id or "").strip(),
            correlation_id=str(payload.correlation_id or "").strip(),
            chain_id=str(payload.chain_id or "").strip(),
        )

    def record_provenance_link(self, payload: ProvenanceLinkInput) -> ProvenanceLink:
        workspace_id = str(payload.workspace_id or "").strip()
        if not workspace_id:
            raise ValueError("workspace_id is required")
        relationship_type = str(payload.relationship_type or "").strip().lower()
        if not relationship_type:
            raise ValueError("relationship_type is required")
        source_ref = normalize_object_ref(payload.source_ref)
        target_ref = normalize_object_ref(payload.target_ref)
        if not source_ref.object_family or not source_ref.object_id:
            raise ValueError("source_ref.object_family and source_ref.object_id are required")
        if not target_ref.object_family or not target_ref.object_id:
            raise ValueError("target_ref.object_family and target_ref.object_id are required")
        return self._repository.create_provenance_link(
            workspace_id=workspace_id,
            relationship_type=relationship_type,
            source_ref=source_ref,
            target_ref=target_ref,
            reason=str(payload.reason or "").strip(),
            explanation=_as_dict(payload.explanation),
            metadata=_as_dict(payload.metadata),
            origin_event_id=str(payload.origin_event_id or "").strip(),
            run_id=str(payload.run_id or "").strip(),
            correlation_id=str(payload.correlation_id or "").strip(),
            chain_id=str(payload.chain_id or "").strip(),
        )

    def record_audit_with_provenance(self, payload: AuditWithProvenanceInput) -> tuple[PlatformAuditEvent, list[ProvenanceLink]]:
        event = self.record_audit_event(payload.event)
        links: list[ProvenanceLink] = []
        for link in payload.provenance_links:
            links.append(
                self.record_provenance_link(
                    ProvenanceLinkInput(
                        workspace_id=link.workspace_id,
                        relationship_type=link.relationship_type,
                        source_ref=link.source_ref,
                        target_ref=link.target_ref,
                        reason=link.reason,
                        explanation=link.explanation,
                        metadata=link.metadata,
                        origin_event_id=str(event.id),
                        run_id=link.run_id,
                        correlation_id=link.correlation_id,
                        chain_id=link.chain_id,
                    )
                )
            )
        return event, links

    def audit_history(self, *, workspace_id: str, object_type: str, object_id: str):
        return self._repository.audit_history(
            workspace_id=workspace_id,
            object_type=object_type,
            object_id=object_id,
        )

    def provenance_for_object(self, *, workspace_id: str, object_type: str, object_id: str, direction: str = "both"):
        next_direction = str(direction or "both").strip().lower() or "both"
        if next_direction not in PROVENANCE_DIRECTIONS:
            raise ValueError(f"direction must be one of {', '.join(PROVENANCE_DIRECTIONS)}")
        return self._repository.provenance_for_object(
            workspace_id=workspace_id,
            object_type=object_type,
            object_id=object_id,
            direction=next_direction,
        )


def serialize_object_ref(ref_json: dict[str, Any]) -> dict[str, Any]:
    payload = _as_dict(ref_json)
    return {
        "object_family": str(payload.get("object_family") or "").strip().lower(),
        "object_id": str(payload.get("object_id") or "").strip(),
        "workspace_id": str(payload.get("workspace_id") or "").strip() or None,
        "namespace": str(payload.get("namespace") or "").strip().lower(),
        "attributes": payload.get("attributes") if isinstance(payload.get("attributes"), dict) else {},
    }


def serialize_audit_event(row: PlatformAuditEvent) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "workspace_id": str(row.workspace_id),
        "event_type": row.event_type,
        "subject": serialize_object_ref(row.subject_ref_json),
        "actor": serialize_object_ref(row.actor_ref_json),
        "cause": serialize_object_ref(row.cause_ref_json),
        "summary": row.summary,
        "reason": row.reason,
        "metadata": _as_dict(row.metadata_json),
        "run_id": str(row.run_id) if row.run_id else None,
        "correlation_id": row.correlation_id or "",
        "chain_id": row.chain_id or "",
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def serialize_provenance_link(row: ProvenanceLink) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "workspace_id": str(row.workspace_id),
        "relationship_type": row.relationship_type,
        "source": serialize_object_ref(row.source_ref_json),
        "target": serialize_object_ref(row.target_ref_json),
        "reason": row.reason,
        "explanation": _as_dict(row.explanation_json),
        "metadata": _as_dict(row.metadata_json),
        "origin_event_id": str(row.origin_event_id) if row.origin_event_id else None,
        "run_id": str(row.run_id) if row.run_id else None,
        "correlation_id": row.correlation_id or "",
        "chain_id": row.chain_id or "",
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def object_ref(*, object_family: str, object_id: str, workspace_id: str = "", namespace: str = "", attributes: dict[str, Any] | None = None) -> ObjectRef:
    return ObjectRef(
        object_family=object_family,
        object_id=object_id,
        workspace_id=workspace_id,
        namespace=namespace,
        attributes=attributes if isinstance(attributes, dict) else {},
    )
