"""Canonical DealFinder-era application role/capability model.

This module is the canonical home for reusable app/platform authorization shape
for DealFinder-era primitives. It intentionally stays capability-first and thin.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Mapping, Sequence, Set

ROLE_APPLICATION_ADMIN = "application_admin"
ROLE_CAMPAIGN_OPERATOR = "campaign_operator"
ROLE_READ_ONLY_ANALYST = "read_only_analyst"

APP_ROLE_IDS: Set[str] = {
    ROLE_APPLICATION_ADMIN,
    ROLE_CAMPAIGN_OPERATOR,
    ROLE_READ_ONLY_ANALYST,
}

CAP_PLATFORM_ACCESS_READ = "platform.access.read"
CAP_JURISDICTIONS_MANAGE = "app.jurisdictions.manage"
CAP_SOURCES_MANAGE = "app.sources.manage"
CAP_MAPPINGS_INSPECT = "app.mappings.inspect"
CAP_REFRESHES_RUN = "app.refreshes.run"
CAP_INGEST_RUNS_READ = "app.ingest_runs.read"
CAP_FAILURES_READ = "app.failures.read"
CAP_ARTIFACTS_READ = "app.artifacts.read"
CAP_PROVENANCE_READ = "app.provenance.read"
CAP_DATASETS_PUBLISH = "app.datasets.publish"
CAP_SOURCE_DIAGNOSTICS_READ = "app.sources.diagnostics.read"
CAP_CAMPAIGNS_MANAGE = "app.campaigns.manage"
CAP_WATCHES_MANAGE = "app.watches.manage"
CAP_SUBSCRIBERS_MANAGE = "app.subscribers.manage"
CAP_NOTIFICATION_TARGETS_MANAGE = "app.notification_targets.manage"
CAP_MATCH_REVIEW = "app.matches.review"
CAP_SIGNALS_REVIEW = "app.signals.review"
CAP_CAMPAIGN_HISTORY_READ = "app.campaign_history.read"
CAP_NOTIFICATIONS_READ = "app.notifications.read"
CAP_APP_READ = "app.read"

ROLE_CAPABILITY_MAP: Mapping[str, Set[str]] = {
    ROLE_APPLICATION_ADMIN: {
        CAP_PLATFORM_ACCESS_READ,
        CAP_JURISDICTIONS_MANAGE,
        CAP_SOURCES_MANAGE,
        CAP_MAPPINGS_INSPECT,
        CAP_REFRESHES_RUN,
        CAP_INGEST_RUNS_READ,
        CAP_FAILURES_READ,
        CAP_ARTIFACTS_READ,
        CAP_PROVENANCE_READ,
        CAP_DATASETS_PUBLISH,
        CAP_SOURCE_DIAGNOSTICS_READ,
        CAP_CAMPAIGNS_MANAGE,
        CAP_WATCHES_MANAGE,
        CAP_SUBSCRIBERS_MANAGE,
        CAP_NOTIFICATION_TARGETS_MANAGE,
        CAP_MATCH_REVIEW,
        CAP_SIGNALS_REVIEW,
        CAP_CAMPAIGN_HISTORY_READ,
        CAP_NOTIFICATIONS_READ,
        CAP_APP_READ,
    },
    ROLE_CAMPAIGN_OPERATOR: {
        CAP_PLATFORM_ACCESS_READ,
        CAP_CAMPAIGNS_MANAGE,
        CAP_WATCHES_MANAGE,
        CAP_SUBSCRIBERS_MANAGE,
        CAP_NOTIFICATION_TARGETS_MANAGE,
        CAP_MATCH_REVIEW,
        CAP_SIGNALS_REVIEW,
        CAP_CAMPAIGN_HISTORY_READ,
        CAP_NOTIFICATIONS_READ,
        CAP_INGEST_RUNS_READ,
        CAP_FAILURES_READ,
        CAP_APP_READ,
    },
    ROLE_READ_ONLY_ANALYST: {
        CAP_PLATFORM_ACCESS_READ,
        CAP_INGEST_RUNS_READ,
        CAP_FAILURES_READ,
        CAP_CAMPAIGN_HISTORY_READ,
        CAP_NOTIFICATIONS_READ,
        CAP_SIGNALS_REVIEW,
        CAP_MATCH_REVIEW,
        CAP_APP_READ,
    },
}

_WORKSPACE_TO_APP_ROLE: Mapping[str, str] = {
    "admin": ROLE_APPLICATION_ADMIN,
    "publisher": ROLE_APPLICATION_ADMIN,
    "moderator": ROLE_APPLICATION_ADMIN,
    "contributor": ROLE_CAMPAIGN_OPERATOR,
    "reader": ROLE_READ_ONLY_ANALYST,
}

_PLATFORM_TO_APP_ROLE: Mapping[str, str] = {
    "platform_owner": ROLE_APPLICATION_ADMIN,
    "platform_admin": ROLE_APPLICATION_ADMIN,
    "platform_architect": ROLE_APPLICATION_ADMIN,
    "platform_operator": ROLE_CAMPAIGN_OPERATOR,
    "app_user": ROLE_READ_ONLY_ANALYST,
}


def normalize_role_slug(role: str) -> str:
    return str(role or "").strip().lower().replace("-", "_")


def normalize_capability_slug(capability: str) -> str:
    return str(capability or "").strip().lower()


def effective_capabilities_for_roles(roles: Sequence[str]) -> List[str]:
    effective: Set[str] = set()
    for role in roles:
        effective.update(ROLE_CAPABILITY_MAP.get(normalize_role_slug(role), set()))
    return sorted(effective)


def map_workspace_role_to_app_role(workspace_role: str) -> str:
    return _WORKSPACE_TO_APP_ROLE.get(normalize_role_slug(workspace_role), ROLE_READ_ONLY_ANALYST)


def map_platform_role_to_app_role(platform_role: str) -> str | None:
    return _PLATFORM_TO_APP_ROLE.get(normalize_role_slug(platform_role))


def effective_app_roles(
    *,
    workspace_role: str = "",
    platform_roles: Iterable[str] = (),
    explicit_roles: Iterable[str] = (),
) -> List[str]:
    resolved: Set[str] = set()
    for role in explicit_roles:
        normalized = normalize_role_slug(role)
        if normalized in APP_ROLE_IDS:
            resolved.add(normalized)
    if workspace_role:
        resolved.add(map_workspace_role_to_app_role(workspace_role))
    for role in platform_roles:
        mapped = map_platform_role_to_app_role(role)
        if mapped:
            resolved.add(mapped)
    if not resolved:
        resolved.add(ROLE_READ_ONLY_ANALYST)
    return sorted(resolved)


def role_capability_catalog() -> Dict[str, List[str]]:
    return {role: sorted(capabilities) for role, capabilities in ROLE_CAPABILITY_MAP.items()}


def canonical_model_payload() -> Dict[str, object]:
    return {
        "schema_version": "xyn.application_access_model.v1",
        "roles": role_capability_catalog(),
        "workspace_role_mapping": dict(_WORKSPACE_TO_APP_ROLE),
        "platform_role_mapping": dict(_PLATFORM_TO_APP_ROLE),
    }


def has_required_capabilities(
    *,
    effective_capabilities: Sequence[str],
    required_capabilities: Sequence[str],
    require_all: bool = True,
) -> bool:
    required = [normalize_capability_slug(cap) for cap in required_capabilities if normalize_capability_slug(cap)]
    if not required:
        return True
    caps = {normalize_capability_slug(cap) for cap in effective_capabilities if normalize_capability_slug(cap)}
    if require_all:
        return all(cap in caps for cap in required)
    return any(cap in caps for cap in required)
