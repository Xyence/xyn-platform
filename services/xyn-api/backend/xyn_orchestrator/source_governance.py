from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from xyn_orchestrator import models
from xyn_orchestrator.provenance import AuditEventInput, ProvenanceService, object_ref

GOVERNANCE_INGESTION_METHODS: tuple[str, ...] = (
    "download",
    "api",
    "upload",
    "browser_automation",
    "manual",
)

GOVERNANCE_LEGAL_STATUSES: tuple[str, ...] = (
    "allowed",
    "restricted",
    "prohibited",
)

GOVERNANCE_ACTIONS: tuple[str, ...] = (
    "activate_source",
    "run_source",
    "fetch_source",
    "browser_automation",
)

GOVERNANCE_DECISIONS: tuple[str, ...] = (
    "allow",
    "deny",
    "defer",
)

GOVERNANCE_FRESHNESS_STATUSES: tuple[str, ...] = (
    "unknown",
    "fresh",
    "stale",
)


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _normalize_method(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _normalize_action(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_legal_status(value: Any) -> str:
    token = str(value or "").strip().lower()
    return token or "allowed"


def normalize_governance_policy(raw: Any, *, strict: bool = False) -> dict[str, Any]:
    payload = _safe_dict(raw)
    methods = [_normalize_method(item) for item in _safe_list(payload.get("allowed_ingestion_methods")) if _normalize_method(item)]
    unknown_methods = sorted({item for item in methods if item not in GOVERNANCE_INGESTION_METHODS})
    if unknown_methods and strict:
        raise ValueError(f"unknown allowed_ingestion_methods: {', '.join(unknown_methods)}")
    methods = [item for item in methods if item in GOVERNANCE_INGESTION_METHODS]

    legal_status = _normalize_legal_status(payload.get("legal_status"))
    if legal_status not in GOVERNANCE_LEGAL_STATUSES:
        if strict:
            raise ValueError(f"legal_status must be one of {', '.join(GOVERNANCE_LEGAL_STATUSES)}")
        legal_status = "allowed"

    expected_interval = 0
    raw_interval = payload.get("expected_refresh_interval_seconds")
    if raw_interval not in {None, ""}:
        try:
            expected_interval = max(0, int(raw_interval))
        except (TypeError, ValueError):
            if strict:
                raise ValueError("expected_refresh_interval_seconds must be an integer >= 0")
            expected_interval = 0

    legal_reference_urls = [str(item or "").strip() for item in _safe_list(payload.get("legal_reference_urls")) if str(item or "").strip()]
    return {
        "allowed_ingestion_methods": list(dict.fromkeys(methods)),
        "browser_automation_allowed": bool(payload.get("browser_automation_allowed", False)),
        "review_required": bool(payload.get("review_required", False)),
        "legal_status": legal_status,
        "legal_notes": str(payload.get("legal_notes") or "").strip(),
        "legal_reference_urls": legal_reference_urls,
        "expected_refresh_interval_seconds": expected_interval,
        "notes": str(payload.get("notes") or "").strip(),
    }


@dataclass(frozen=True)
class FreshnessStatus:
    status: str
    expected_refresh_interval_seconds: int
    age_seconds: int | None
    stale_by_seconds: int | None
    last_success_at: str


@dataclass(frozen=True)
class GovernanceDecision:
    action: str
    decision: str
    reason_code: str
    message: str
    method: str
    freshness: FreshnessStatus
    governance_policy: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "decision": self.decision,
            "reason_code": self.reason_code,
            "message": self.message,
            "method": self.method,
            "freshness": {
                "status": self.freshness.status,
                "expected_refresh_interval_seconds": int(self.freshness.expected_refresh_interval_seconds or 0),
                "age_seconds": self.freshness.age_seconds,
                "stale_by_seconds": self.freshness.stale_by_seconds,
                "last_success_at": self.freshness.last_success_at,
            },
            "governance_policy": self.governance_policy,
        }


class SourceGovernanceService:
    _DEFAULT_METHOD_BY_SOURCE_MODE = {
        "file_upload": "upload",
        "remote_url": "download",
        "api_polling": "api",
        "manual": "manual",
    }

    def _freshness(self, source: models.SourceConnector, governance: dict[str, Any], *, now: datetime | None = None) -> FreshnessStatus:
        expected_interval = int(governance.get("expected_refresh_interval_seconds") or 0)
        now_dt = now or datetime.now(timezone.utc)
        last_success = source.last_success_at
        if expected_interval <= 0:
            return FreshnessStatus(
                status="unknown",
                expected_refresh_interval_seconds=expected_interval,
                age_seconds=None,
                stale_by_seconds=None,
                last_success_at=last_success.isoformat() if last_success else "",
            )
        if last_success is None:
            return FreshnessStatus(
                status="unknown",
                expected_refresh_interval_seconds=expected_interval,
                age_seconds=None,
                stale_by_seconds=None,
                last_success_at="",
            )
        age = max(0, int((now_dt - last_success).total_seconds()))
        stale_by = age - expected_interval
        return FreshnessStatus(
            status="stale" if stale_by > 0 else "fresh",
            expected_refresh_interval_seconds=expected_interval,
            age_seconds=age,
            stale_by_seconds=stale_by if stale_by > 0 else 0,
            last_success_at=last_success.isoformat(),
        )

    def evaluate(
        self,
        *,
        source: models.SourceConnector,
        action: str,
        method: str = "",
        now: datetime | None = None,
    ) -> GovernanceDecision:
        normalized_action = _normalize_action(action)
        if normalized_action not in GOVERNANCE_ACTIONS:
            raise ValueError(f"unsupported governance action '{normalized_action}'")
        governance = normalize_governance_policy(source.governance_json if isinstance(source.governance_json, dict) else {})
        normalized_method = _normalize_method(method)
        if not normalized_method and normalized_action in {"activate_source", "run_source", "fetch_source"}:
            normalized_method = self._DEFAULT_METHOD_BY_SOURCE_MODE.get(str(source.source_mode or "").strip().lower(), "manual")
        freshness = self._freshness(source, governance, now=now)

        legal_status = str(governance.get("legal_status") or "allowed").strip().lower()
        if legal_status == "prohibited" and normalized_action in {"activate_source", "run_source", "fetch_source", "browser_automation"}:
            return GovernanceDecision(
                action=normalized_action,
                decision="deny",
                reason_code="governance.legal_prohibited",
                message="source legal_status=prohibited blocks execution",
                method=normalized_method,
                freshness=freshness,
                governance_policy=governance,
            )

        if normalized_action == "browser_automation" and not bool(governance.get("browser_automation_allowed", False)):
            return GovernanceDecision(
                action=normalized_action,
                decision="deny",
                reason_code="governance.browser_automation_not_allowed",
                message="browser automation is not allowed for this source",
                method="browser_automation",
                freshness=freshness,
                governance_policy=governance,
            )

        allowed_methods = [str(item) for item in governance.get("allowed_ingestion_methods") or [] if str(item)]
        if normalized_method and allowed_methods and normalized_method not in allowed_methods:
            return GovernanceDecision(
                action=normalized_action,
                decision="deny",
                reason_code="governance.method_not_allowed",
                message=f"ingestion method '{normalized_method}' is not allowed for this source",
                method=normalized_method,
                freshness=freshness,
                governance_policy=governance,
            )

        if bool(governance.get("review_required", False)) and not bool(source.review_approved):
            if normalized_action in {"activate_source", "run_source", "fetch_source"}:
                return GovernanceDecision(
                    action=normalized_action,
                    decision="defer",
                    reason_code="governance.review_required",
                    message="source requires governance review approval before execution",
                    method=normalized_method,
                    freshness=freshness,
                    governance_policy=governance,
                )

        return GovernanceDecision(
            action=normalized_action,
            decision="allow",
            reason_code="governance.allowed",
            message="source governance allows this action",
            method=normalized_method,
            freshness=freshness,
            governance_policy=governance,
        )

    def emit_audit_event(
        self,
        *,
        source: models.SourceConnector,
        decision: GovernanceDecision,
        run_id: str = "",
        actor_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> models.PlatformAuditEvent:
        event_type = {
            ("deny", "run_source"): "source_governance.denied_run",
            ("defer", "run_source"): "source_governance.deferred_run",
            ("deny", "fetch_source"): "source_governance.denied_fetch",
            ("defer", "fetch_source"): "source_governance.deferred_fetch",
            ("deny", "browser_automation"): "source_governance.denied_browser_automation",
            ("defer", "activate_source"): "source_governance.deferred_activation",
            ("deny", "activate_source"): "source_governance.denied_activation",
        }.get((decision.decision, decision.action), "source_governance.decision")
        merged_metadata = {
            "decision": decision.decision,
            "reason_code": decision.reason_code,
            "action": decision.action,
            "method": decision.method,
            "freshness_status": decision.freshness.status,
            **(metadata if isinstance(metadata, dict) else {}),
        }
        actor_ref = None
        if actor_id:
            actor_ref = object_ref(
                object_family="user_identity",
                object_id=str(actor_id),
                workspace_id=str(source.workspace_id),
            )
        return ProvenanceService().record_audit_event(
            AuditEventInput(
                workspace_id=str(source.workspace_id),
                event_type=event_type,
                subject_ref=object_ref(
                    object_family="source_connector",
                    object_id=str(source.id),
                    workspace_id=str(source.workspace_id),
                    attributes={"key": str(source.key or ""), "source_type": str(source.source_type or "")},
                ),
                actor_ref=actor_ref,
                summary=f"Source governance {decision.decision}: {source.key}",
                reason=decision.message,
                metadata=merged_metadata,
                run_id=str(run_id or ""),
                idempotency_key=hashlib.sha256(
                    "|".join(
                        [
                            "source_governance",
                            str(source.workspace_id),
                            str(source.id),
                            str(run_id or ""),
                            decision.action,
                            decision.decision,
                            decision.reason_code,
                            decision.method,
                        ]
                    ).encode("utf-8")
                ).hexdigest(),
            )
        )
