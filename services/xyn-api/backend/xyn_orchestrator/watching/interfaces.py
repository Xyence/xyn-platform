from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

WATCH_LIFECYCLE_STATES: tuple[str, ...] = (
    "draft",
    "active",
    "paused",
    "archived",
)

WATCH_SUBSCRIBER_TYPES: tuple[str, ...] = (
    "user_identity",
    "delivery_target",
    "external_endpoint",
)


@dataclass(frozen=True)
class WatchRegistration:
    workspace_id: str
    key: str
    name: str
    target_kind: str = "generic"
    target_ref: dict[str, Any] = field(default_factory=dict)
    filter_criteria: dict[str, Any] = field(default_factory=dict)
    lifecycle_state: str = "draft"
    linked_campaign_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_by_id: str = ""


@dataclass(frozen=True)
class WatchSubscriberInput:
    watch_id: str
    subscriber_type: str
    subscriber_ref: str
    destination: dict[str, Any] = field(default_factory=dict)
    preferences: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    created_by_id: str = ""


@dataclass(frozen=True)
class WatchEvaluationInput:
    workspace_id: str
    event_key: str = ""
    event_ref: dict[str, Any] = field(default_factory=dict)
    watch_ids: tuple[str, ...] = tuple()
    run_id: str = ""
    correlation_id: str = ""
    chain_id: str = ""
    idempotency_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WatchEvaluationResult:
    watch_id: str
    watch_key: str
    matched: bool
    score: float
    reason: str
    explanation: list[str] = field(default_factory=list)
    notification_intent: dict[str, Any] = field(default_factory=dict)


def normalize_watch_key(value: str) -> str:
    return str(value or "").strip().lower().replace(" ", "_")
