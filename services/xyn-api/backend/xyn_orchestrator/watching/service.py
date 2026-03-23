from __future__ import annotations

import hashlib
import json
from typing import Any

from xyn_orchestrator.jurisdiction import require_canonical_jurisdiction
from xyn_orchestrator.models import WatchDefinition, WatchMatchEvent, WatchSubscriber
from xyn_orchestrator.orchestration.definitions import STAGE_SIGNAL_MATCHING
from xyn_orchestrator.orchestration.domain_events import DomainEventInput, DomainEventService
from xyn_orchestrator.provenance import (
    AuditWithProvenanceInput,
    AuditEventInput,
    ProvenanceLinkInput,
    ProvenanceService,
    object_ref,
)

from .interfaces import (
    WATCH_LIFECYCLE_STATES,
    WATCH_SUBSCRIBER_TYPES,
    WatchEvaluationInput,
    WatchEvaluationResult,
    WatchRegistration,
    WatchSubscriberInput,
    normalize_watch_key,
)
from .repository import WatchRepository


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _lookup_value(document: dict[str, Any], dotted_key: str) -> Any:
    current: Any = document
    for piece in str(dotted_key or "").split("."):
        key = piece.strip()
        if not key:
            continue
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _matches_rule(event_ref: dict[str, Any], rule_key: str, expected: Any) -> tuple[bool, str]:
    actual = _lookup_value(event_ref, rule_key)
    if isinstance(expected, dict):
        if "eq" in expected:
            ok = actual == expected.get("eq")
            return ok, f"{rule_key} {'==' if ok else '!='} {expected.get('eq')!r}"
        if "in" in expected and isinstance(expected.get("in"), list):
            options = expected.get("in")
            ok = actual in options
            return ok, f"{rule_key} {'in' if ok else 'not in'} options"
        if "contains" in expected:
            needle = str(expected.get("contains") or "")
            haystack = str(actual or "")
            ok = needle.lower() in haystack.lower() if needle else False
            return ok, f"{rule_key} {'contains' if ok else 'does not contain'} {needle!r}"
        if "gte" in expected:
            try:
                ok = float(actual) >= float(expected.get("gte"))
            except (TypeError, ValueError):
                ok = False
            return ok, f"{rule_key} {'>=' if ok else '<'} {expected.get('gte')!r}"
        if "lte" in expected:
            try:
                ok = float(actual) <= float(expected.get("lte"))
            except (TypeError, ValueError):
                ok = False
            return ok, f"{rule_key} {'<=' if ok else '>'} {expected.get('lte')!r}"
        return False, f"{rule_key} unsupported operator"
    if isinstance(expected, list):
        ok = actual in expected
        return ok, f"{rule_key} {'in' if ok else 'not in'} list"
    ok = actual == expected
    return ok, f"{rule_key} {'==' if ok else '!='} {expected!r}"


def _evaluate_watch_match(
    *,
    watch: WatchDefinition,
    event_key: str,
    event_ref: dict[str, Any],
) -> WatchEvaluationResult:
    explanation: list[str] = []
    matched = True

    target_kind = str(watch.target_kind or "").strip().lower()
    event_target_kind = str(event_ref.get("target_kind") or "").strip().lower()
    if target_kind and target_kind != "generic" and event_target_kind and event_target_kind != target_kind:
        matched = False
        explanation.append(f"target_kind mismatch: watch={target_kind} event={event_target_kind}")

    target_ref = _as_dict(watch.target_ref_json)
    for key, expected in target_ref.items():
        ok, detail = _matches_rule(event_ref, str(key), expected)
        explanation.append(f"target_ref:{detail}")
        if not ok:
            matched = False

    filter_criteria = _as_dict(watch.filter_criteria_json)
    for key, expected in filter_criteria.items():
        ok, detail = _matches_rule(event_ref, str(key), expected)
        explanation.append(f"filter:{detail}")
        if not ok:
            matched = False

    active_subscribers = watch.subscribers.filter(enabled=True).count()
    if active_subscribers == 0:
        explanation.append("watch has no enabled subscribers")

    if matched:
        reason = "matched target and filter criteria"
        score = 1.0
        notification_intent = {
            "action": "notify_subscribers",
            "subscriber_count": int(active_subscribers),
            "event_key": str(event_key or ""),
            "watch_id": str(watch.id),
            "watch_key": str(watch.key),
        }
    else:
        reason = "did not satisfy watch criteria"
        score = 0.0
        notification_intent = {}

    return WatchEvaluationResult(
        watch_id=str(watch.id),
        watch_key=str(watch.key),
        matched=matched,
        score=score,
        reason=reason,
        explanation=explanation,
        notification_intent=notification_intent,
    )


def _json_fingerprint(payload: dict[str, Any]) -> str:
    body = payload if isinstance(payload, dict) else {}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class WatchService:
    def __init__(self, *, repository: WatchRepository | None = None):
        self._repository = repository or WatchRepository()

    def register_watch(self, registration: WatchRegistration) -> WatchDefinition:
        key = normalize_watch_key(registration.key)
        name = str(registration.name or "").strip()
        if not key:
            raise ValueError("watch key is required")
        if not name:
            raise ValueError("watch name is required")
        lifecycle_state = str(registration.lifecycle_state or "draft").strip().lower()
        if lifecycle_state not in WATCH_LIFECYCLE_STATES:
            raise ValueError(f"unsupported lifecycle_state '{lifecycle_state}'")
        target_kind = str(registration.target_kind or "generic").strip().lower() or "generic"
        return self._repository.create_watch(
            workspace_id=registration.workspace_id,
            key=key,
            name=name,
            target_kind=target_kind,
            target_ref=registration.target_ref if isinstance(registration.target_ref, dict) else {},
            filter_criteria=registration.filter_criteria if isinstance(registration.filter_criteria, dict) else {},
            lifecycle_state=lifecycle_state,
            metadata=registration.metadata if isinstance(registration.metadata, dict) else {},
            linked_campaign_id=str(registration.linked_campaign_id or "").strip(),
            created_by_id=str(registration.created_by_id or "").strip(),
        )

    def list_watches(self, *, workspace_id: str):
        return self._repository.list_watches(workspace_id=workspace_id)

    def get_watch(self, *, watch_id: str) -> WatchDefinition:
        return self._repository.get_watch(watch_id=watch_id)

    def update_watch_lifecycle(self, *, watch_id: str, lifecycle_state: str) -> WatchDefinition:
        watch = self._repository.get_watch(watch_id=watch_id)
        next_state = str(lifecycle_state or "").strip().lower()
        if next_state not in WATCH_LIFECYCLE_STATES:
            raise ValueError(f"unsupported lifecycle_state '{next_state}'")
        watch.lifecycle_state = next_state
        return self._repository.update_watch(watch=watch, update_fields=["lifecycle_state"])

    def add_subscriber(self, payload: WatchSubscriberInput) -> WatchSubscriber:
        watch = self._repository.get_watch(watch_id=payload.watch_id)
        subscriber_type = str(payload.subscriber_type or "").strip().lower()
        if subscriber_type not in WATCH_SUBSCRIBER_TYPES:
            raise ValueError(f"unsupported subscriber_type '{subscriber_type}'")
        subscriber_ref = str(payload.subscriber_ref or "").strip()
        if not subscriber_ref:
            raise ValueError("subscriber_ref is required")
        return self._repository.upsert_subscriber(
            watch=watch,
            subscriber_type=subscriber_type,
            subscriber_ref=subscriber_ref,
            destination=payload.destination if isinstance(payload.destination, dict) else {},
            preferences=payload.preferences if isinstance(payload.preferences, dict) else {},
            enabled=bool(payload.enabled),
            created_by_id=str(payload.created_by_id or "").strip(),
        )

    def list_subscribers(self, *, watch_id: str):
        watch = self._repository.get_watch(watch_id=watch_id)
        return self._repository.list_subscribers(watch=watch)

    def evaluate(self, payload: WatchEvaluationInput, *, persist: bool = True) -> list[WatchEvaluationResult]:
        workspace_id = str(payload.workspace_id or "").strip()
        if not workspace_id:
            raise ValueError("workspace_id is required")
        scope_jurisdiction = require_canonical_jurisdiction(
            str(payload.scope_jurisdiction or "").strip(),
            context="jurisdiction",
        )
        if not scope_jurisdiction:
            raise ValueError("jurisdiction is required")
        event_ref = payload.event_ref if isinstance(payload.event_ref, dict) else {}
        reconciled_state_version = str(payload.reconciled_state_version or "").strip()
        qs = self._repository.list_watches(workspace_id=workspace_id)
        if payload.watch_ids:
            qs = qs.filter(id__in=list(payload.watch_ids))
        else:
            qs = qs.filter(lifecycle_state="active")
        watches = list(qs)
        results: list[WatchEvaluationResult] = []
        for watch in watches:
            result = _evaluate_watch_match(
                watch=watch,
                event_key=str(payload.event_key or ""),
                event_ref=event_ref,
            )
            if persist:
                event_fingerprint = _json_fingerprint(event_ref)
                explicit_idempotency_key = str(payload.idempotency_key or "").strip()
                resolved_idempotency_key = explicit_idempotency_key or hashlib.sha256(
                    "|".join(
                        [
                            str(workspace_id),
                            str(watch.id),
                            str(payload.event_key or "").strip(),
                            event_fingerprint,
                            str(payload.run_id or "").strip(),
                            str(payload.correlation_id or "").strip(),
                            str(payload.chain_id or "").strip(),
                        ]
                    ).encode("utf-8")
                ).hexdigest()
                row = self._repository.create_match_event(
                    watch=watch,
                    workspace_id=workspace_id,
                    event_key=str(payload.event_key or ""),
                    matched=result.matched,
                    score=result.score,
                    reason=result.reason,
                    explanation={"summary": list(result.explanation)},
                    event_ref=event_ref,
                    filter_snapshot=_as_dict(watch.filter_criteria_json),
                    notification_intent=result.notification_intent,
                    event_fingerprint=event_fingerprint,
                    idempotency_key=resolved_idempotency_key,
                    scope_jurisdiction=scope_jurisdiction,
                    reconciled_state_version=reconciled_state_version,
                    run_id=str(payload.run_id or ""),
                    correlation_id=str(payload.correlation_id or ""),
                    chain_id=str(payload.chain_id or ""),
                )
                provenance = ProvenanceService()
                watch_ref = object_ref(
                    object_family="watch_definition",
                    object_id=str(watch.id),
                    workspace_id=workspace_id,
                    attributes={"key": str(watch.key)},
                )
                match_ref = object_ref(
                    object_family="watch_match_event",
                    object_id=str(row.id),
                    workspace_id=workspace_id,
                    attributes={"matched": bool(result.matched), "score": float(result.score)},
                )
                links = [
                    ProvenanceLinkInput(
                        workspace_id=workspace_id,
                        relationship_type="watch_match_emitted_from_watch",
                        source_ref=watch_ref,
                        target_ref=match_ref,
                        reason="watch definition evaluated and emitted watch match event",
                        explanation={"event_key": str(payload.event_key or "")},
                        run_id=str(payload.run_id or ""),
                        correlation_id=str(payload.correlation_id or ""),
                        chain_id=str(payload.chain_id or ""),
                    )
                ]
                event_object_id = str(event_ref.get("object_id") or "").strip()
                if event_object_id:
                    links.append(
                        ProvenanceLinkInput(
                            workspace_id=workspace_id,
                            relationship_type="watch_match_caused_by_event",
                            source_ref=object_ref(
                                object_family=str(event_ref.get("object_type") or event_ref.get("target_kind") or "event"),
                                object_id=event_object_id,
                                workspace_id=str(event_ref.get("workspace_id") or workspace_id),
                                namespace=str(event_ref.get("namespace") or ""),
                                attributes=event_ref,
                            ),
                            target_ref=match_ref,
                            reason="incoming event payload contributed to watch match",
                            explanation={"event_key": str(payload.event_key or "")},
                            run_id=str(payload.run_id or ""),
                            correlation_id=str(payload.correlation_id or ""),
                            chain_id=str(payload.chain_id or ""),
                        )
                    )
                provenance.record_audit_with_provenance(
                    AuditWithProvenanceInput(
                        event=AuditEventInput(
                            workspace_id=workspace_id,
                            event_type="watch.evaluated",
                            subject_ref=match_ref,
                            summary=f"Watch evaluation for {watch.key}",
                            reason=result.reason,
                            cause_ref=watch_ref,
                            metadata={
                                "watch_id": str(watch.id),
                                "watch_key": str(watch.key),
                                "matched": bool(result.matched),
                                "score": float(result.score),
                                "event_key": str(payload.event_key or ""),
                            },
                            run_id=str(payload.run_id or ""),
                            correlation_id=str(payload.correlation_id or ""),
                            chain_id=str(payload.chain_id or ""),
                            idempotency_key=f"watch.audit:{resolved_idempotency_key}",
                        ),
                        provenance_links=tuple(links),
                        idempotency_scope=f"watch.eval:{resolved_idempotency_key}",
                    )
                )
                if result.matched:
                    signal_token = hashlib.sha256(
                        "|".join(
                            [
                                str(workspace_id),
                                str(watch.id),
                                str(payload.event_key or "").strip(),
                                str(row.id),
                                str(reconciled_state_version or ""),
                            ]
                        ).encode("utf-8")
                    ).hexdigest()
                    event_row = DomainEventService().record(
                        DomainEventInput(
                            workspace_id=workspace_id,
                            event_type="signal.watch_match_detected",
                            idempotency_key=f"signal.watch:{resolved_idempotency_key}",
                            stage_key=STAGE_SIGNAL_MATCHING,
                            run_id=str(payload.run_id or ""),
                            scope_jurisdiction=scope_jurisdiction,
                            scope_source=str(event_ref.get("source") or ""),
                            reconciled_state_version=str(reconciled_state_version or ""),
                            signal_set_version=signal_token,
                            correlation_id=str(payload.correlation_id or ""),
                            chain_id=str(payload.chain_id or ""),
                            subject_ref={
                                "kind": "watch_match_event",
                                "id": str(row.id),
                                "watch_id": str(watch.id),
                            },
                            payload={
                                "watch_id": str(watch.id),
                                "watch_key": str(watch.key),
                                "watch_match_event_id": str(row.id),
                                "event_key": str(payload.event_key or ""),
                                "matched": bool(result.matched),
                                "score": float(result.score),
                                "reason": str(result.reason),
                                "event_ref": event_ref,
                            },
                            metadata={
                                "materialized_from": "watch.evaluated",
                            },
                        )
                    )
                    try:
                        from xyn_orchestrator.signal_read_model import SignalReadProjectionService

                        SignalReadProjectionService().project_domain_event(event=event_row)
                    except Exception:
                        # Projection is a read-model concern; retain canonical match/domain-event durability.
                        pass
            results.append(result)
        return results


def serialize_watch(watch: WatchDefinition) -> dict[str, Any]:
    active_subscribers = watch.subscribers.filter(enabled=True).count()
    return {
        "id": str(watch.id),
        "workspace_id": str(watch.workspace_id),
        "key": watch.key,
        "name": watch.name,
        "target_kind": watch.target_kind,
        "target_ref": _as_dict(watch.target_ref_json),
        "filter_criteria": _as_dict(watch.filter_criteria_json),
        "lifecycle_state": watch.lifecycle_state,
        "linked_campaign_id": str(watch.linked_campaign_id) if watch.linked_campaign_id else None,
        "metadata": _as_dict(watch.metadata_json),
        "active_subscriber_count": int(active_subscribers),
        "created_by_id": str(watch.created_by_id) if watch.created_by_id else None,
        "created_at": watch.created_at.isoformat() if watch.created_at else None,
        "updated_at": watch.updated_at.isoformat() if watch.updated_at else None,
    }


def serialize_watch_subscriber(row: WatchSubscriber) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "watch_id": str(row.watch_id),
        "subscriber_type": row.subscriber_type,
        "subscriber_ref": row.subscriber_ref,
        "destination": _as_dict(row.destination_json),
        "preferences": _as_dict(row.preferences_json),
        "enabled": bool(row.enabled),
        "created_by_id": str(row.created_by_id) if row.created_by_id else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def serialize_watch_match(row: WatchMatchEvent) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "workspace_id": str(row.workspace_id),
        "watch_id": str(row.watch_id),
        "watch_key": str(row.watch.key),
        "event_key": str(row.event_key or ""),
        "matched": bool(row.matched),
        "score": float(row.score or 0.0),
        "reason": str(row.reason or ""),
        "explanation": _as_dict(row.explanation_json),
        "event_ref": _as_dict(row.event_ref_json),
        "filter_snapshot": _as_dict(row.filter_snapshot_json),
        "notification_intent": _as_dict(row.notification_intent_json),
        "event_fingerprint": str(row.event_fingerprint or ""),
        "idempotency_key": str(row.idempotency_key or ""),
        "scope_jurisdiction": str(row.scope_jurisdiction or ""),
        "reconciled_state_version": str(row.reconciled_state_version or ""),
        "run_id": str(row.run_id) if row.run_id else None,
        "correlation_id": str(row.correlation_id or ""),
        "chain_id": str(row.chain_id or ""),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def serialize_watch_evaluation(result: WatchEvaluationResult) -> dict[str, Any]:
    return {
        "watch_id": result.watch_id,
        "watch_key": result.watch_key,
        "matched": bool(result.matched),
        "score": float(result.score),
        "reason": result.reason,
        "explanation": list(result.explanation),
        "notification_intent": result.notification_intent if isinstance(result.notification_intent, dict) else {},
    }
