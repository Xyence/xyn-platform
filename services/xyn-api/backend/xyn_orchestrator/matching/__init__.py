from .interfaces import (
    MATCH_DECISIONS,
    DecisionThresholds,
    MatchEvaluation,
    MatchSignal,
    MatchableRecordRef,
    StrategyContext,
)
from .normalization import normalize_address, normalize_identifier, normalize_text
from .registry import MatchStrategyRegistry
from .repository import DjangoMatchResultRepository
from .service import MatchServiceConfig, RecordMatchingService, evaluation_as_dict
from .strategies import (
    AddressNormalizedExactMatchStrategy,
    BUILTIN_MATCH_STRATEGIES,
    ExactIdentifierMatchStrategy,
    FuzzyTextSimilarityStrategy,
    NormalizedTextExactMatchStrategy,
    WeightedCompositeMatchStrategy,
)

__all__ = [
    "MATCH_DECISIONS",
    "DecisionThresholds",
    "MatchEvaluation",
    "MatchSignal",
    "MatchableRecordRef",
    "StrategyContext",
    "normalize_text",
    "normalize_identifier",
    "normalize_address",
    "MatchStrategyRegistry",
    "DjangoMatchResultRepository",
    "MatchServiceConfig",
    "RecordMatchingService",
    "evaluation_as_dict",
    "ExactIdentifierMatchStrategy",
    "NormalizedTextExactMatchStrategy",
    "AddressNormalizedExactMatchStrategy",
    "FuzzyTextSimilarityStrategy",
    "WeightedCompositeMatchStrategy",
    "BUILTIN_MATCH_STRATEGIES",
]
