from .interfaces import (
    MATCH_DECISIONS,
    DecisionThresholds,
    MatchEvaluation,
    MatchSignal,
    MatchableRecordRef,
    StrategyContext,
)
from .normalization import (
    normalize_address,
    normalize_address_record,
    normalize_field_value,
    normalize_identifier,
    normalize_owner_name,
    normalize_parcel_id,
    normalize_text,
    register_address_adapter,
    register_parcel_adapter,
)
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
    "normalize_address_record",
    "normalize_field_value",
    "normalize_owner_name",
    "normalize_parcel_id",
    "register_address_adapter",
    "register_parcel_adapter",
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
