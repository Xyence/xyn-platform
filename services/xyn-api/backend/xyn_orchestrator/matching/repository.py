from __future__ import annotations

import hashlib
import json
from typing import Any

from django.db import transaction

from xyn_orchestrator.models import OrchestrationRun, RecordMatchEvaluation, Workspace
from xyn_orchestrator.provenance import AuditWithProvenanceInput, AuditEventInput, ProvenanceLinkInput, ProvenanceService, object_ref

from .interfaces import MatchEvaluation


def _serialize_ref(ref: Any) -> dict[str, Any]:
    return {
        "source_namespace": str(getattr(ref, "source_namespace", "") or "").strip(),
        "source_record_type": str(getattr(ref, "source_record_type", "") or "").strip(),
        "source_record_id": str(getattr(ref, "source_record_id", "") or "").strip(),
        "workspace_id": str(getattr(ref, "workspace_id", "") or "").strip() or None,
        "attributes": getattr(ref, "attributes", {}) if isinstance(getattr(ref, "attributes", {}), dict) else {},
    }


def _pair_fingerprint(evaluation: MatchEvaluation) -> str:
    left = evaluation.candidate_a.normalized_identity()
    right = evaluation.candidate_b.normalized_identity()
    ordered = sorted([left, right])
    encoded = json.dumps(ordered, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class DjangoMatchResultRepository:
    @transaction.atomic
    def persist_evaluation(
        self,
        *,
        workspace_id: str,
        evaluation: MatchEvaluation,
        run_id: str = "",
        correlation_id: str = "",
        chain_id: str = "",
        idempotency_key: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> RecordMatchEvaluation:
        workspace = Workspace.objects.get(id=workspace_id)
        run = OrchestrationRun.objects.filter(id=run_id, workspace=workspace).first() if run_id else None
        pair_fingerprint = _pair_fingerprint(evaluation)
        normalized_idempotency_key = str(idempotency_key or "").strip()
        if not normalized_idempotency_key:
            normalized_idempotency_key = hashlib.sha256(
                "|".join(
                    [
                        str(workspace_id),
                        str(evaluation.strategy_key or "").strip().lower(),
                        pair_fingerprint,
                        str(run_id or "").strip(),
                        str(correlation_id or "").strip(),
                        str(chain_id or "").strip(),
                    ]
                ).encode("utf-8")
            ).hexdigest()
        existing = RecordMatchEvaluation.objects.filter(
            workspace=workspace,
            idempotency_key=normalized_idempotency_key,
        ).first()
        if existing is not None:
            return existing
        row = RecordMatchEvaluation.objects.create(
            workspace=workspace,
            candidate_a_namespace=str(evaluation.candidate_a.source_namespace or "").strip(),
            candidate_a_type=str(evaluation.candidate_a.source_record_type or "").strip(),
            candidate_a_id=str(evaluation.candidate_a.source_record_id or "").strip(),
            candidate_b_namespace=str(evaluation.candidate_b.source_namespace or "").strip(),
            candidate_b_type=str(evaluation.candidate_b.source_record_type or "").strip(),
            candidate_b_id=str(evaluation.candidate_b.source_record_id or "").strip(),
            strategy_key=str(evaluation.strategy_key or "").strip(),
            pair_fingerprint=pair_fingerprint,
            idempotency_key=normalized_idempotency_key,
            score=float(evaluation.score or 0.0),
            decision=str(evaluation.decision or "non_match").strip(),
            confidence=str(evaluation.confidence or "none").strip(),
            explanation_json={
                "summary": list(evaluation.explanation or []),
                "signals": [
                    {
                        "signal_key": signal.signal_key,
                        "strategy_key": signal.strategy_key,
                        "score": float(signal.score),
                        "weight": float(signal.weight),
                        "matched": bool(signal.matched),
                        "reason": signal.reason,
                        "details": signal.details,
                    }
                    for signal in evaluation.signals
                ],
            },
            metadata_json=evaluation.metadata if isinstance(evaluation.metadata, dict) else {},
            run=run,
            correlation_id=str(correlation_id or "").strip(),
            chain_id=str(chain_id or "").strip(),
            candidate_a_ref_json=_serialize_ref(evaluation.candidate_a),
            candidate_b_ref_json=_serialize_ref(evaluation.candidate_b),
            extra_json=metadata if isinstance(metadata, dict) else {},
        )
        provenance = ProvenanceService()
        result_ref = object_ref(
            object_family="record_match_evaluation",
            object_id=str(row.id),
            workspace_id=str(workspace.id),
            attributes={"decision": row.decision, "score": float(row.score)},
        )
        candidate_a_ref = object_ref(
            object_family=str(row.candidate_a_type or "record"),
            object_id=str(row.candidate_a_id),
            workspace_id=str(workspace.id),
            namespace=str(row.candidate_a_namespace or ""),
        )
        candidate_b_ref = object_ref(
            object_family=str(row.candidate_b_type or "record"),
            object_id=str(row.candidate_b_id),
            workspace_id=str(workspace.id),
            namespace=str(row.candidate_b_namespace or ""),
        )
        provenance.record_audit_with_provenance(
            AuditWithProvenanceInput(
                event=AuditEventInput(
                    workspace_id=str(workspace.id),
                    event_type="record_matching.evaluated",
                    subject_ref=result_ref,
                    summary=f"Record match evaluated via {row.strategy_key}",
                    reason=f"decision={row.decision}",
                    metadata={
                        "strategy_key": row.strategy_key,
                        "score": float(row.score),
                        "confidence": row.confidence,
                    },
                    run_id=str(run.id) if run else "",
                    correlation_id=str(correlation_id or "").strip(),
                    chain_id=str(chain_id or "").strip(),
                    idempotency_key=f"match.audit:{normalized_idempotency_key}",
                ),
                provenance_links=(
                    ProvenanceLinkInput(
                        workspace_id=str(workspace.id),
                        relationship_type="match_evaluated_from",
                        source_ref=candidate_a_ref,
                        target_ref=result_ref,
                        reason="candidate_a contributed to match evaluation",
                        explanation={"candidate_role": "a"},
                        run_id=str(run.id) if run else "",
                        correlation_id=str(correlation_id or "").strip(),
                        chain_id=str(chain_id or "").strip(),
                        idempotency_key=f"match.link:{normalized_idempotency_key}:a",
                    ),
                    ProvenanceLinkInput(
                        workspace_id=str(workspace.id),
                        relationship_type="match_evaluated_from",
                        source_ref=candidate_b_ref,
                        target_ref=result_ref,
                        reason="candidate_b contributed to match evaluation",
                        explanation={"candidate_role": "b"},
                        run_id=str(run.id) if run else "",
                        correlation_id=str(correlation_id or "").strip(),
                        chain_id=str(chain_id or "").strip(),
                        idempotency_key=f"match.link:{normalized_idempotency_key}:b",
                    ),
                ),
                idempotency_scope=f"match.eval:{normalized_idempotency_key}",
            )
        )
        return row
