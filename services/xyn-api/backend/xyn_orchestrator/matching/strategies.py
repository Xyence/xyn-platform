from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from .interfaces import MatchSignal, MatchableRecordRef, StrategyContext, StrategyOutcome
from .normalization import normalize_address, normalize_identifier, normalize_text


@dataclass(frozen=True)
class ExactIdentifierMatchStrategy:
    key: str = "exact_identifier"
    identifier_fields: tuple[str, ...] = ("external_id", "id", "identifier")
    score_on_match: float = 1.0

    def evaluate(
        self,
        *,
        candidate_a: MatchableRecordRef,
        candidate_b: MatchableRecordRef,
        context: StrategyContext,
    ) -> StrategyOutcome:
        a_attrs = candidate_a.attributes if isinstance(candidate_a.attributes, dict) else {}
        b_attrs = candidate_b.attributes if isinstance(candidate_b.attributes, dict) else {}
        for field in self.identifier_fields:
            left = normalize_identifier(a_attrs.get(field))
            right = normalize_identifier(b_attrs.get(field))
            if left and right and left == right:
                return StrategyOutcome(
                    score=self.score_on_match,
                    signals=(
                        MatchSignal(
                            signal_key=f"id:{field}",
                            strategy_key=self.key,
                            score=self.score_on_match,
                            weight=1.0,
                            matched=True,
                            reason=f"{field} matched exactly",
                            details={"field": field, "normalized": left},
                        ),
                    ),
                    explanation=[f"Exact identifier match on {field}"],
                )
        same_identity = candidate_a.normalized_identity() == candidate_b.normalized_identity()
        score = self.score_on_match if same_identity else 0.0
        return StrategyOutcome(
            score=score,
            signals=(
                MatchSignal(
                    signal_key="record_identity",
                    strategy_key=self.key,
                    score=score,
                    weight=1.0,
                    matched=bool(same_identity),
                    reason="record references are identical" if same_identity else "record references differ",
                    details={
                        "candidate_a": candidate_a.normalized_identity(),
                        "candidate_b": candidate_b.normalized_identity(),
                    },
                ),
            ),
            explanation=["Record references are identical"] if same_identity else ["No exact identifier signal"],
        )


@dataclass(frozen=True)
class NormalizedTextExactMatchStrategy:
    key: str = "normalized_text_exact"
    field: str = "name"
    weight: float = 1.0

    def evaluate(
        self,
        *,
        candidate_a: MatchableRecordRef,
        candidate_b: MatchableRecordRef,
        context: StrategyContext,
    ) -> StrategyOutcome:
        a_value = normalize_text((candidate_a.attributes or {}).get(self.field))
        b_value = normalize_text((candidate_b.attributes or {}).get(self.field))
        matched = bool(a_value and b_value and a_value == b_value)
        score = 1.0 if matched else 0.0
        return StrategyOutcome(
            score=score,
            signals=(
                MatchSignal(
                    signal_key=f"text_exact:{self.field}",
                    strategy_key=self.key,
                    score=score,
                    weight=float(self.weight),
                    matched=matched,
                    reason=f"normalized {self.field} exact match" if matched else f"normalized {self.field} mismatch",
                    details={"left": a_value, "right": b_value, "field": self.field},
                ),
            ),
            explanation=[f"Normalized {self.field} matched exactly"] if matched else [f"No exact match on normalized {self.field}"],
        )


@dataclass(frozen=True)
class AddressNormalizedExactMatchStrategy:
    key: str = "address_normalized_exact"
    field: str = "address"
    weight: float = 1.0

    def evaluate(
        self,
        *,
        candidate_a: MatchableRecordRef,
        candidate_b: MatchableRecordRef,
        context: StrategyContext,
    ) -> StrategyOutcome:
        left = normalize_address((candidate_a.attributes or {}).get(self.field))
        right = normalize_address((candidate_b.attributes or {}).get(self.field))
        matched = bool(left and right and left == right)
        score = 1.0 if matched else 0.0
        return StrategyOutcome(
            score=score,
            signals=(
                MatchSignal(
                    signal_key=f"address_exact:{self.field}",
                    strategy_key=self.key,
                    score=score,
                    weight=float(self.weight),
                    matched=matched,
                    reason="normalized address matched" if matched else "normalized address mismatch",
                    details={"left": left, "right": right, "field": self.field},
                ),
            ),
            explanation=["Normalized addresses matched"] if matched else ["Address signal did not match"],
        )


@dataclass(frozen=True)
class FuzzyTextSimilarityStrategy:
    key: str = "fuzzy_text_similarity"
    field: str = "name"
    minimum_similarity: float = 0.7
    weight: float = 1.0

    def evaluate(
        self,
        *,
        candidate_a: MatchableRecordRef,
        candidate_b: MatchableRecordRef,
        context: StrategyContext,
    ) -> StrategyOutcome:
        a_value = normalize_text((candidate_a.attributes or {}).get(self.field))
        b_value = normalize_text((candidate_b.attributes or {}).get(self.field))
        if not a_value or not b_value:
            ratio = 0.0
        else:
            ratio = float(SequenceMatcher(None, a_value, b_value).ratio())
        matched = ratio >= float(self.minimum_similarity)
        return StrategyOutcome(
            score=ratio,
            signals=(
                MatchSignal(
                    signal_key=f"fuzzy:{self.field}",
                    strategy_key=self.key,
                    score=ratio,
                    weight=float(self.weight),
                    matched=matched,
                    reason=f"similarity ratio {ratio:.3f}",
                    details={"left": a_value, "right": b_value, "field": self.field},
                ),
            ),
            explanation=[f"Fuzzy {self.field} similarity={ratio:.3f}"],
        )


@dataclass(frozen=True)
class WeightedCompositeMatchStrategy:
    key: str = "weighted_composite"
    components: tuple[tuple[str, float], ...] = (
        ("exact_identifier", 0.55),
        ("normalized_text_exact", 0.25),
        ("fuzzy_text_similarity", 0.20),
    )

    def evaluate(
        self,
        *,
        candidate_a: MatchableRecordRef,
        candidate_b: MatchableRecordRef,
        context: StrategyContext,
        component_outcomes: dict[str, StrategyOutcome] | None = None,
    ) -> StrategyOutcome:
        outcomes = component_outcomes or {}
        total_weight = 0.0
        weighted = 0.0
        merged_signals: list[MatchSignal] = []
        explanations: list[str] = []
        for component_key, raw_weight in self.components:
            weight = max(0.0, float(raw_weight))
            outcome = outcomes.get(component_key)
            if outcome is None:
                continue
            total_weight += weight
            weighted += float(outcome.score) * weight
            merged_signals.extend(outcome.signals)
            explanations.extend(outcome.explanation)
        score = 0.0 if total_weight <= 0 else weighted / total_weight
        explanation_prefix = [f"Composite score={score:.3f} from {len(merged_signals)} signals"]
        return StrategyOutcome(score=score, signals=tuple(merged_signals), explanation=[*explanation_prefix, *explanations])


BUILTIN_MATCH_STRATEGIES: tuple[Any, ...] = (
    ExactIdentifierMatchStrategy(),
    NormalizedTextExactMatchStrategy(),
    AddressNormalizedExactMatchStrategy(),
    FuzzyTextSimilarityStrategy(),
)
