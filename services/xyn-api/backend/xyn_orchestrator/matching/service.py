from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .interfaces import (
    DecisionThresholds,
    MatchCandidate,
    MatchEvaluation,
    MatchResultRepository,
    MatchSignal,
    MatchableRecordRef,
    StrategyContext,
    StrategyOutcome,
    classify_decision,
    confidence_from_decision,
)
from .registry import MatchStrategyRegistry
from .strategies import (
    BUILTIN_MATCH_STRATEGIES,
    WeightedCompositeMatchStrategy,
)


@dataclass(frozen=True)
class MatchServiceConfig:
    default_strategy_key: str = "weighted_composite"
    thresholds: DecisionThresholds = DecisionThresholds()


class RecordMatchingService:
    def __init__(
        self,
        *,
        repository: MatchResultRepository | None = None,
        registry: MatchStrategyRegistry | None = None,
        config: MatchServiceConfig | None = None,
    ):
        self._repository = repository
        self._registry = registry or MatchStrategyRegistry()
        self._config = config or MatchServiceConfig()
        self._register_builtins_if_missing()

    @property
    def registry(self) -> MatchStrategyRegistry:
        return self._registry

    def _register_builtins_if_missing(self) -> None:
        existing = set(self._registry.keys())
        for strategy in BUILTIN_MATCH_STRATEGIES:
            if strategy.key in existing:
                continue
            self._registry.register(strategy)
            existing.add(strategy.key)
        if "weighted_composite" not in existing:
            self._registry.register(WeightedCompositeMatchStrategy())

    def _evaluate_strategy(
        self,
        *,
        strategy_key: str,
        candidate_a: MatchableRecordRef,
        candidate_b: MatchableRecordRef,
        context: StrategyContext,
    ) -> StrategyOutcome:
        strategy = self._registry.get(strategy_key)
        return strategy.evaluate(candidate_a=candidate_a, candidate_b=candidate_b, context=context)

    def _compose(
        self,
        *,
        candidate_a: MatchableRecordRef,
        candidate_b: MatchableRecordRef,
        context: StrategyContext,
        strategy_key: str,
        metadata: dict[str, Any] | None,
    ) -> MatchEvaluation:
        resolved = str(strategy_key or "").strip() or self._config.default_strategy_key
        if resolved == "weighted_composite":
            component_outcomes = {
                key: self._evaluate_strategy(
                    strategy_key=key,
                    candidate_a=candidate_a,
                    candidate_b=candidate_b,
                    context=context,
                )
                for key in self._registry.keys()
                if key != "weighted_composite"
            }
            composite = self._registry.get("weighted_composite")
            outcome = composite.evaluate(
                candidate_a=candidate_a,
                candidate_b=candidate_b,
                context=context,
                component_outcomes=component_outcomes,
            )
        else:
            outcome = self._evaluate_strategy(
                strategy_key=resolved,
                candidate_a=candidate_a,
                candidate_b=candidate_b,
                context=context,
            )
        score = max(0.0, min(1.0, float(outcome.score or 0.0)))
        decision = classify_decision(score, thresholds=self._config.thresholds)
        confidence = confidence_from_decision(decision)
        return MatchEvaluation(
            candidate_a=candidate_a,
            candidate_b=candidate_b,
            strategy_key=resolved,
            score=score,
            decision=decision,
            confidence=confidence,
            explanation=list(outcome.explanation or []),
            signals=tuple(outcome.signals or tuple()),
            metadata=metadata if isinstance(metadata, dict) else {},
        )

    def evaluate_pair(
        self,
        *,
        workspace_id: str,
        candidate_a: MatchableRecordRef,
        candidate_b: MatchableRecordRef,
        strategy_key: str = "",
        context: StrategyContext | None = None,
        persist: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> MatchEvaluation:
        if not str(workspace_id or "").strip():
            raise ValueError("workspace_id is required")
        resolved_context = context or StrategyContext(workspace_id=workspace_id)
        evaluation = self._compose(
            candidate_a=candidate_a,
            candidate_b=candidate_b,
            context=resolved_context,
            strategy_key=strategy_key,
            metadata=metadata,
        )
        if persist and self._repository is not None:
            self._repository.persist_evaluation(
                workspace_id=workspace_id,
                evaluation=evaluation,
                run_id=resolved_context.run_id,
                correlation_id=resolved_context.correlation_id,
                chain_id=resolved_context.chain_id,
                idempotency_key=resolved_context.idempotency_key or str((metadata or {}).get("idempotency_key") or ""),
                metadata=metadata,
            )
        return evaluation

    def evaluate_candidates(
        self,
        *,
        workspace_id: str,
        target: MatchableRecordRef,
        candidates: Sequence[MatchableRecordRef],
        strategy_key: str = "",
        context: StrategyContext | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[MatchCandidate]:
        rows: list[MatchCandidate] = []
        for candidate in candidates:
            evaluation = self.evaluate_pair(
                workspace_id=workspace_id,
                candidate_a=target,
                candidate_b=candidate,
                strategy_key=strategy_key,
                context=context,
                persist=True,
                metadata=metadata,
            )
            rows.append(MatchCandidate(candidate=candidate, evaluation=evaluation))
        return sorted(rows, key=lambda row: row.evaluation.score, reverse=True)


def evaluation_as_dict(evaluation: MatchEvaluation) -> dict[str, Any]:
    return {
        "candidate_a": {
            "source_namespace": evaluation.candidate_a.source_namespace,
            "source_record_type": evaluation.candidate_a.source_record_type,
            "source_record_id": evaluation.candidate_a.source_record_id,
            "workspace_id": evaluation.candidate_a.workspace_id or None,
            "attributes": evaluation.candidate_a.attributes,
        },
        "candidate_b": {
            "source_namespace": evaluation.candidate_b.source_namespace,
            "source_record_type": evaluation.candidate_b.source_record_type,
            "source_record_id": evaluation.candidate_b.source_record_id,
            "workspace_id": evaluation.candidate_b.workspace_id or None,
            "attributes": evaluation.candidate_b.attributes,
        },
        "strategy_key": evaluation.strategy_key,
        "score": float(evaluation.score),
        "decision": evaluation.decision,
        "confidence": evaluation.confidence,
        "explanation": list(evaluation.explanation),
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
        "metadata": evaluation.metadata if isinstance(evaluation.metadata, dict) else {},
    }
