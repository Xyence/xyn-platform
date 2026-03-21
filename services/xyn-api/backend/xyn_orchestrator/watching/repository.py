from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models import QuerySet

from xyn_orchestrator.models import (
    Campaign,
    OrchestrationRun,
    UserIdentity,
    WatchDefinition,
    WatchMatchEvent,
    WatchSubscriber,
    Workspace,
)


class WatchRepository:
    def list_watches(self, *, workspace_id: str) -> QuerySet[WatchDefinition]:
        return (
            WatchDefinition.objects.filter(workspace_id=workspace_id)
            .select_related("linked_campaign", "created_by")
            .order_by("-updated_at", "-created_at")
        )

    def get_watch(self, *, watch_id: str) -> WatchDefinition:
        return WatchDefinition.objects.select_related("workspace", "linked_campaign", "created_by").get(id=watch_id)

    @transaction.atomic
    def create_watch(
        self,
        *,
        workspace_id: str,
        key: str,
        name: str,
        target_kind: str,
        target_ref: dict[str, Any],
        filter_criteria: dict[str, Any],
        lifecycle_state: str,
        metadata: dict[str, Any],
        linked_campaign_id: str = "",
        created_by_id: str = "",
    ) -> WatchDefinition:
        workspace = Workspace.objects.get(id=workspace_id)
        linked_campaign = None
        if linked_campaign_id:
            linked_campaign = Campaign.objects.filter(id=linked_campaign_id, workspace=workspace).first()
            if linked_campaign is None:
                raise ValueError("linked_campaign_id is not valid for this workspace")
        created_by = UserIdentity.objects.filter(id=created_by_id).first() if created_by_id else None
        return WatchDefinition.objects.create(
            workspace=workspace,
            key=key,
            name=name,
            target_kind=target_kind,
            target_ref_json=target_ref,
            filter_criteria_json=filter_criteria,
            lifecycle_state=lifecycle_state,
            linked_campaign=linked_campaign,
            metadata_json=metadata,
            created_by=created_by,
        )

    @transaction.atomic
    def update_watch(self, *, watch: WatchDefinition, update_fields: list[str]) -> WatchDefinition:
        normalized = [field for field in update_fields if field]
        if "updated_at" not in normalized:
            normalized.append("updated_at")
        watch.save(update_fields=normalized)
        return watch

    def list_subscribers(self, *, watch: WatchDefinition) -> QuerySet[WatchSubscriber]:
        return watch.subscribers.select_related("created_by").order_by("-created_at", "-id")

    @transaction.atomic
    def upsert_subscriber(
        self,
        *,
        watch: WatchDefinition,
        subscriber_type: str,
        subscriber_ref: str,
        destination: dict[str, Any],
        preferences: dict[str, Any],
        enabled: bool,
        created_by_id: str = "",
    ) -> WatchSubscriber:
        created_by = UserIdentity.objects.filter(id=created_by_id).first() if created_by_id else None
        row = WatchSubscriber.objects.filter(
            watch=watch,
            subscriber_type=subscriber_type,
            subscriber_ref=subscriber_ref,
        ).first()
        if row is None:
            row = WatchSubscriber.objects.create(
                watch=watch,
                subscriber_type=subscriber_type,
                subscriber_ref=subscriber_ref,
                destination_json=destination,
                preferences_json=preferences,
                enabled=enabled,
                created_by=created_by,
            )
            return row
        row.destination_json = destination
        row.preferences_json = preferences
        row.enabled = enabled
        if created_by is not None:
            row.created_by = created_by
        row.save(update_fields=["destination_json", "preferences_json", "enabled", "created_by", "updated_at"])
        return row

    def list_matches(self, *, workspace_id: str) -> QuerySet[WatchMatchEvent]:
        return (
            WatchMatchEvent.objects.filter(workspace_id=workspace_id)
            .select_related("watch", "run")
            .order_by("-created_at", "-id")
        )

    @transaction.atomic
    def create_match_event(
        self,
        *,
        watch: WatchDefinition,
        workspace_id: str,
        event_key: str,
        matched: bool,
        score: float,
        reason: str,
        explanation: dict[str, Any],
        event_ref: dict[str, Any],
        filter_snapshot: dict[str, Any],
        notification_intent: dict[str, Any],
        event_fingerprint: str = "",
        idempotency_key: str = "",
        scope_jurisdiction: str = "",
        reconciled_state_version: str = "",
        run_id: str = "",
        correlation_id: str = "",
        chain_id: str = "",
    ) -> WatchMatchEvent:
        run = OrchestrationRun.objects.filter(id=run_id, workspace_id=workspace_id).first() if run_id else None
        normalized_idempotency_key = str(idempotency_key or "").strip()
        if normalized_idempotency_key:
            existing = WatchMatchEvent.objects.filter(
                workspace_id=workspace_id,
                watch=watch,
                idempotency_key=normalized_idempotency_key,
            ).first()
            if existing is not None:
                return existing
        return WatchMatchEvent.objects.create(
            workspace_id=workspace_id,
            watch=watch,
            event_key=event_key,
            matched=matched,
            score=float(score),
            reason=reason,
            explanation_json=explanation,
            event_ref_json=event_ref,
            filter_snapshot_json=filter_snapshot,
            notification_intent_json=notification_intent,
            event_fingerprint=str(event_fingerprint or "").strip(),
            idempotency_key=normalized_idempotency_key,
            scope_jurisdiction=str(scope_jurisdiction or "").strip(),
            reconciled_state_version=str(reconciled_state_version or "").strip(),
            run=run,
            correlation_id=str(correlation_id or ""),
            chain_id=str(chain_id or ""),
        )
