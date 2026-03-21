from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class GeocodeProviderCandidate:
    rank: int
    score: float | None = None
    confidence: float | None = None
    label: str = ""
    matched_address: str = ""
    location: dict[str, Any] = field(default_factory=dict)
    spatial_reference: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class GeocodeProviderRequest:
    raw_address: str
    normalized_address: str
    address_fields: dict[str, Any] = field(default_factory=dict)
    provider_config: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GeocodeProviderResponse:
    status: str
    candidates: tuple[GeocodeProviderCandidate, ...] = tuple()
    request_context: dict[str, Any] = field(default_factory=dict)
    response_context: dict[str, Any] = field(default_factory=dict)
    error_category: str = ""
    error_message: str = ""
    warnings: tuple[str, ...] = tuple()


class GeocodeProvider(Protocol):
    kind: str
    name: str
    version: str

    def geocode(self, *, request: GeocodeProviderRequest) -> GeocodeProviderResponse:
        ...

