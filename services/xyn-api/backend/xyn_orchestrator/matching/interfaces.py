from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence


MATCH_DECISION_EXACT = "exact_match"
MATCH_DECISION_PROBABLE = "probable_match"
MATCH_DECISION_POSSIBLE = "possible_match"
MATCH_DECISION_NON = "non_match"
MATCH_DECISION_REVIEW = "needs_review"

MATCH_DECISIONS: tuple[str, ...] = (
    MATCH_DECISION_EXACT,
    MATCH_DECISION_PROBABLE,
    MATCH_DECISION_POSSIBLE,
    MATCH_DECISION_NON,
    MATCH_DECISION_REVIEW,
)


@dataclass(frozen=True)
class MatchableRecordRef:
    source_namespace: str
    source_record_type: str
    source_record_id: str
    workspace_id: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)

    def normalized_identity(self) -> str:
        return ":".join(
            (
                str(self.source_namespace or "").strip().lower(),
                str(self.source_record_type or "").strip().lower(),
                str(self.source_record_id or "").strip().lower(),
            )
        )


@dataclass(frozen=True)
class MatchSignal:
    signal_key: str
    strategy_key: str
    score: float
    weight: float
    matched: bool
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MatchEvaluation:
    candidate_a: MatchableRecordRef
    candidate_b: MatchableRecordRef
    strategy_key: str
    score: float
    decision: str
    confidence: str
    explanation: list[str] = field(default_factory=list)
    signals: tuple[MatchSignal, ...] = tuple()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyContext:
    workspace_id: str = ""
    run_id: str = ""
    correlation_id: str = ""
    chain_id: str = ""
    idempotency_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyOutcome:
    score: float
    signals: tuple[MatchSignal, ...]
    explanation: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DecisionThresholds:
    exact_min: float = 0.99
    probable_min: float = 0.85
    possible_min: float = 0.65
    review_min: float = 0.5


@dataclass(frozen=True)
class MatchCandidate:
    candidate: MatchableRecordRef
    evaluation: MatchEvaluation


class MatchStrategy(Protocol):
    key: str

    def evaluate(
        self,
        *,
        candidate_a: MatchableRecordRef,
        candidate_b: MatchableRecordRef,
        context: StrategyContext,
    ) -> StrategyOutcome:
        ...


class MatchResultRepository(Protocol):
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
    ) -> Any:
        ...


def classify_decision(score: float, *, thresholds: DecisionThresholds | None = None) -> str:
    policy = thresholds or DecisionThresholds()
    if score >= policy.exact_min:
        return MATCH_DECISION_EXACT
    if score >= policy.probable_min:
        return MATCH_DECISION_PROBABLE
    if score >= policy.possible_min:
        return MATCH_DECISION_POSSIBLE
    if score >= policy.review_min:
        return MATCH_DECISION_REVIEW
    return MATCH_DECISION_NON


def confidence_from_decision(decision: str) -> str:
    normalized = str(decision or "").strip().lower()
    if normalized == MATCH_DECISION_EXACT:
        return "exact"
    if normalized == MATCH_DECISION_PROBABLE:
        return "high"
    if normalized == MATCH_DECISION_POSSIBLE:
        return "medium"
    if normalized == MATCH_DECISION_REVIEW:
        return "low"
    return "none"


def choose_best_candidate(candidates: Sequence[MatchCandidate]) -> MatchCandidate | None:
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item.evaluation.score, reverse=True)[0]
