from __future__ import annotations

from typing import Any

from django.db import transaction

from xyn_orchestrator.models import OrchestrationRun, RecordMatchEvaluation, Workspace

from .interfaces import MatchEvaluation


def _serialize_ref(ref: Any) -> dict[str, Any]:
    return {
        "source_namespace": str(getattr(ref, "source_namespace", "") or "").strip(),
        "source_record_type": str(getattr(ref, "source_record_type", "") or "").strip(),
        "source_record_id": str(getattr(ref, "source_record_id", "") or "").strip(),
        "workspace_id": str(getattr(ref, "workspace_id", "") or "").strip() or None,
        "attributes": getattr(ref, "attributes", {}) if isinstance(getattr(ref, "attributes", {}), dict) else {},
    }


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
        metadata: dict[str, Any] | None = None,
    ) -> RecordMatchEvaluation:
        workspace = Workspace.objects.get(id=workspace_id)
        run = OrchestrationRun.objects.filter(id=run_id, workspace=workspace).first() if run_id else None
        row = RecordMatchEvaluation.objects.create(
            workspace=workspace,
            candidate_a_namespace=str(evaluation.candidate_a.source_namespace or "").strip(),
            candidate_a_type=str(evaluation.candidate_a.source_record_type or "").strip(),
            candidate_a_id=str(evaluation.candidate_a.source_record_id or "").strip(),
            candidate_b_namespace=str(evaluation.candidate_b.source_namespace or "").strip(),
            candidate_b_type=str(evaluation.candidate_b.source_record_type or "").strip(),
            candidate_b_id=str(evaluation.candidate_b.source_record_id or "").strip(),
            strategy_key=str(evaluation.strategy_key or "").strip(),
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
        return row
