from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PROVENANCE_DIRECTIONS: tuple[str, ...] = ("upstream", "downstream", "both")


@dataclass(frozen=True)
class ObjectRef:
    object_family: str
    object_id: str
    workspace_id: str = ""
    namespace: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)

    def normalized_family(self) -> str:
        return str(self.object_family or "").strip().lower()

    def normalized_id(self) -> str:
        return str(self.object_id or "").strip()


@dataclass(frozen=True)
class AuditEventInput:
    workspace_id: str
    event_type: str
    subject_ref: ObjectRef
    summary: str = ""
    reason: str = ""
    actor_ref: ObjectRef | None = None
    cause_ref: ObjectRef | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    run_id: str = ""
    correlation_id: str = ""
    chain_id: str = ""
    idempotency_key: str = ""


@dataclass(frozen=True)
class ProvenanceLinkInput:
    workspace_id: str
    relationship_type: str
    source_ref: ObjectRef
    target_ref: ObjectRef
    reason: str = ""
    explanation: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    origin_event_id: str = ""
    run_id: str = ""
    correlation_id: str = ""
    chain_id: str = ""
    idempotency_key: str = ""


@dataclass(frozen=True)
class AuditWithProvenanceInput:
    event: AuditEventInput
    provenance_links: tuple[ProvenanceLinkInput, ...] = tuple()
    idempotency_scope: str = ""


def normalize_object_ref(ref: ObjectRef) -> ObjectRef:
    return ObjectRef(
        object_family=str(ref.object_family or "").strip().lower(),
        object_id=str(ref.object_id or "").strip(),
        workspace_id=str(ref.workspace_id or "").strip(),
        namespace=str(ref.namespace or "").strip().lower(),
        attributes=ref.attributes if isinstance(ref.attributes, dict) else {},
    )
