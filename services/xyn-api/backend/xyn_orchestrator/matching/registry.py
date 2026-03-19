from __future__ import annotations

from dataclasses import dataclass

from .interfaces import MatchStrategy


@dataclass
class MatchStrategyRegistry:
    _strategies: dict[str, MatchStrategy]

    def __init__(self):
        self._strategies = {}

    def register(self, strategy: MatchStrategy) -> None:
        key = str(getattr(strategy, "key", "") or "").strip()
        if not key:
            raise ValueError("strategy key is required")
        if key in self._strategies:
            raise ValueError(f"strategy '{key}' is already registered")
        self._strategies[key] = strategy

    def replace(self, strategy: MatchStrategy) -> None:
        key = str(getattr(strategy, "key", "") or "").strip()
        if not key:
            raise ValueError("strategy key is required")
        self._strategies[key] = strategy

    def get(self, key: str) -> MatchStrategy:
        normalized = str(key or "").strip()
        if normalized not in self._strategies:
            raise KeyError(f"unknown match strategy '{normalized}'")
        return self._strategies[normalized]

    def keys(self) -> list[str]:
        return sorted(self._strategies.keys())

    def all(self) -> tuple[MatchStrategy, ...]:
        return tuple(self._strategies[key] for key in self.keys())
