from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Callable, Dict, List, Optional

from xyn_orchestrator.models import Artifact

from .contracts import DraftIntakeContractRegistry
from .proposal_provider import IntentContextPackMissingError, IntentProposalProvider
from .types import (
    ALLOWED_ACTIONS,
    ALLOWED_ARTIFACT_TYPES,
    ClarificationOption,
    ClarificationReason,
    ConversationExecutionContext,
    IntentEnvelope,
    IntentFamily,
    IntentType,
    ResolutionResult,
)


@dataclass
class ResolutionContext:
    artifact: Optional[Artifact] = None
    workspace_id: str = ""
    user_identity_id: str = ""
    worker_mention_token: str = ""
    requested_worker_type: str = ""
    requested_worker_id: str = ""
    requested_worker_status: str = ""
    requested_worker_capabilities: List[str] | None = None
    worker_mention_error: str = ""
    conversation_context: ConversationExecutionContext | None = None


class IntentResolutionEngine:
    def __init__(
        self,
        *,
        proposal_provider: IntentProposalProvider,
        contracts: DraftIntakeContractRegistry,
        context_pack_target_lookup=None,
        work_item_lookup: Optional[Callable[[str, str], List[Dict[str, Any]]]] = None,
        run_lookup: Optional[Callable[[str, str], List[Dict[str, Any]]]] = None,
        capability_manifest_lookup: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
        app_operation_lookup: Optional[Callable[[str, Dict[str, Any]], Optional[Dict[str, Any]]]] = None,
    ):
        self.proposal_provider = proposal_provider
        self.contracts = contracts
        self.context_pack_target_lookup = context_pack_target_lookup
        self.work_item_lookup = work_item_lookup
        self.run_lookup = run_lookup
        self.capability_manifest_lookup = capability_manifest_lookup
        self.app_operation_lookup = app_operation_lookup

    @staticmethod
    def _apply_worker_request(envelope: IntentEnvelope, context: ResolutionContext) -> IntentEnvelope:
        worker_type = str(context.requested_worker_type or "").strip()
        if not worker_type:
            return envelope
        target_context = dict(envelope.target_context or {})
        action_payload = dict(envelope.action_payload or {})
        resolved_subject = dict(envelope.resolved_subject or {})
        resolution_notes = list(envelope.resolution_notes or [])
        target_context.update(
            {
                "requested_worker_type": worker_type,
                "requested_worker_id": str(context.requested_worker_id or "") or None,
                "worker_mention_token": str(context.worker_mention_token or "") or None,
            }
        )
        action_payload.update(
            {
                "worker_type": worker_type,
                "worker_id": str(context.requested_worker_id or "") or None,
                "worker_mention_token": str(context.worker_mention_token or "") or None,
            }
        )
        if context.requested_worker_capabilities:
            action_payload["worker_capabilities"] = list(context.requested_worker_capabilities)
        if context.requested_worker_status:
            resolved_subject.setdefault("worker_status", str(context.requested_worker_status or ""))
        mention_note = f"worker mention resolved to {worker_type}"
        if mention_note not in resolution_notes:
            resolution_notes.append(mention_note)
        return envelope.model_copy(
            update={
                "target_context": target_context,
                "action_payload": action_payload,
                "resolved_subject": resolved_subject,
                "resolution_notes": resolution_notes,
            }
        )

    @staticmethod
    def _intent_envelope(
        *,
        intent_family: IntentFamily,
        intent_type: IntentType | str,
        target_context: Optional[Dict[str, Any]] = None,
        resolved_subject: Optional[Dict[str, Any]] = None,
        action_payload: Optional[Dict[str, Any]] = None,
        policy: Optional[Dict[str, Any]] = None,
        confidence: float = 0.0,
        needs_clarification: bool = False,
        clarification_reason: Optional[ClarificationReason | str] = None,
        clarification_options: Optional[List[Dict[str, Any]]] = None,
        resolution_notes: Optional[List[str]] = None,
    ) -> IntentEnvelope:
        return IntentEnvelope(
            intent_family=intent_family.value,
            intent_type=intent_type.value if isinstance(intent_type, IntentType) else str(intent_type),
            target_context=dict(target_context or {}),
            resolved_subject=dict(resolved_subject or {}),
            action_payload=dict(action_payload or {}),
            policy=dict(policy or {}),
            confidence=max(0.0, min(1.0, float(confidence or 0.0))),
            needs_clarification=bool(needs_clarification),
            clarification_reason=(
                clarification_reason.value
                if isinstance(clarification_reason, ClarificationReason)
                else str(clarification_reason or "") or None
            ),
            clarification_options=[
                ClarificationOption.model_validate(option if isinstance(option, dict) else {})
                for option in (clarification_options or [])
            ],
            resolution_notes=[str(note) for note in (resolution_notes or []) if str(note).strip()],
        )

    @staticmethod
    def _extract_policy(message: str) -> Dict[str, Any]:
        text = str(message or "").strip().lower()
        return {
            "auto_continue": bool(re.search(r"\b(continue automatically|auto[- ]?continue)\b", text)),
            "pause_on_ambiguity": bool(re.search(r"\bpause\s+(?:if|on)\s+ambigu", text)),
            "require_human_review_on_failure": bool(re.search(r"\b(require|needs?)\s+(?:human\s+)?review\s+on\s+failure\b", text)),
            "run_tests": bool(re.search(r"\b(run|execute)\s+tests?\b|\btest\b", text)),
        }

    @staticmethod
    def _clean_reference(value: str) -> str:
        cleaned = re.sub(
            r"\b(?:implementation|the implementation|using the current plan|current plan|run tests?|tests?|with tests?|and tests?|pause if ambiguity appears|pause on ambiguity|require review on failure|continue automatically)\b",
            "",
            str(value or ""),
            flags=re.IGNORECASE,
        )
        return re.sub(r"\s+", " ", cleaned).strip(" ,.")

    @classmethod
    def _extract_work_reference(cls, message: str) -> str:
        text = str(message or "").strip()
        work_item_match = re.search(r"\b(?:work\s+item|item)\s+([A-Za-z0-9._:-]+)\b", text, flags=re.IGNORECASE)
        if work_item_match:
            return cls._clean_reference(work_item_match.group(1))
        epic_match = re.search(r"\b(Epic\s+[A-Z0-9-]+)\b", text, flags=re.IGNORECASE)
        if epic_match:
            return cls._clean_reference(epic_match.group(1))
        patterns = [
            r"^\s*(?:continue|resume|work on)\s+(.+)$",
            r"^\s*(?:start with|implement)\s+(.+)$",
        ]
        for pattern in patterns:
            match = re.match(pattern, text, flags=re.IGNORECASE)
            if match:
                return cls._clean_reference(match.group(1))
        return ""

    @classmethod
    def _extract_run_reference(cls, message: str) -> str:
        text = str(message or "").strip()
        match = re.search(r"\b(?:run|execution)\s+([A-Za-z0-9._:-]+)\b", text, flags=re.IGNORECASE)
        if not match:
            return ""
        candidate = cls._clean_reference(match.group(1))
        if candidate.lower() in {"the", "current", "last", "logs", "artifacts", "failed"}:
            return ""
        return candidate

    @staticmethod
    def _clarification_from_candidates(
        *,
        family: IntentFamily,
        intent_type: IntentType,
        target_context: Dict[str, Any],
        policy: Dict[str, Any],
        candidates: List[Dict[str, Any]],
        notes: List[str],
    ) -> IntentEnvelope:
        return IntentResolutionEngine._intent_envelope(
            intent_family=family,
            intent_type=intent_type,
            target_context=target_context,
            policy=policy,
            confidence=0.42,
            needs_clarification=True,
            clarification_reason=ClarificationReason.AMBIGUOUS_TARGET,
            clarification_options=[
                {
                    "id": str(candidate.get("id") or ""),
                    "label": str(candidate.get("label") or candidate.get("title") or candidate.get("id") or ""),
                    "kind": str(candidate.get("kind") or ""),
                    "payload": {
                        key: value
                        for key, value in candidate.items()
                        if key in {"status", "task_type", "run_id", "work_item_id", "workspace_id"}
                    },
                }
                for candidate in candidates
            ],
            resolution_notes=notes,
        )

    def _resolve_development_intent(self, *, message: str, context: ResolutionContext) -> Optional[IntentEnvelope]:
        text = str(message or "").strip()
        lowered = text.lower()
        workspace_id = str(context.workspace_id or "").strip()
        policy = self._extract_policy(text)
        work_reference = self._extract_work_reference(text)
        run_reference = self._extract_run_reference(text)
        notes: List[str] = []
        conversation_context = context.conversation_context or ConversationExecutionContext()
        if work_reference:
            notes.append(f"work_reference={work_reference}")
        if run_reference:
            notes.append(f"run_reference={run_reference}")
        work_candidates = self.work_item_lookup(work_reference or text, workspace_id) if callable(self.work_item_lookup) else []
        run_candidates = self.run_lookup(run_reference or work_reference or text, workspace_id) if callable(self.run_lookup) else []

        if not work_reference and not work_candidates and conversation_context.current_work_item_id:
            work_candidates = self.work_item_lookup(str(conversation_context.current_work_item_id), workspace_id) if callable(self.work_item_lookup) else []
            if work_candidates:
                notes.append(f"context_work_item={conversation_context.current_work_item_id}")
        if not run_reference and not work_reference and not run_candidates and conversation_context.current_run_id:
            run_candidates = self.run_lookup(str(conversation_context.current_run_id), workspace_id) if callable(self.run_lookup) else []
            if run_candidates:
                notes.append(f"context_run={conversation_context.current_run_id}")

        if re.search(r"\b(request review|review this|await review|wait for review)\b", lowered) and not re.search(r"\b(pause|hold)\b", lowered):
            return self._intent_envelope(
                intent_family=IntentFamily.RUN_SUPERVISION,
                intent_type=IntentType.REQUEST_REVIEW,
                target_context={"workspace_id": workspace_id},
                resolved_subject=run_candidates[0] if len(run_candidates) == 1 else {},
                action_payload={"reference": run_reference or work_reference or text},
                policy=policy,
                confidence=0.9,
                needs_clarification=len(run_candidates) > 1,
                clarification_reason=ClarificationReason.AMBIGUOUS_TARGET if len(run_candidates) > 1 else None,
                clarification_options=[
                    {"id": str(candidate.get("id") or ""), "label": str(candidate.get("label") or candidate.get("id") or ""), "kind": "run"}
                    for candidate in run_candidates
                ] if len(run_candidates) > 1 else [],
                resolution_notes=notes or ["review_requested"],
            )

        if re.search(r"\b(pause|hold)\b", lowered):
            if not work_reference and not run_candidates and re.search(r"\b(it|the work|the run)\b", lowered):
                return self._intent_envelope(
                    intent_family=IntentFamily.RUN_SUPERVISION,
                    intent_type=IntentType.PAUSE_OR_HOLD,
                    target_context={"workspace_id": workspace_id},
                    policy=policy,
                    confidence=0.45,
                    needs_clarification=True,
                    clarification_reason=ClarificationReason.AMBIGUOUS_TARGET,
                    clarification_options=[],
                    resolution_notes=["pause target is ambiguous"],
                )
            if len(run_candidates) > 1:
                return self._clarification_from_candidates(
                    family=IntentFamily.RUN_SUPERVISION,
                    intent_type=IntentType.PAUSE_OR_HOLD,
                    target_context={"workspace_id": workspace_id},
                    policy=policy,
                    candidates=run_candidates,
                    notes=notes or ["multiple run candidates matched pause request"],
                )
            return self._intent_envelope(
                intent_family=IntentFamily.RUN_SUPERVISION,
                intent_type=IntentType.PAUSE_OR_HOLD,
                target_context={"workspace_id": workspace_id},
                resolved_subject=run_candidates[0] if len(run_candidates) == 1 else {},
                action_payload={"reference": run_reference or work_reference or text},
                policy=policy,
                confidence=0.86,
                resolution_notes=notes or ["pause requested"],
            )

        if re.search(r"\b(continue|resume)\b.*\b(?:run|execution)\b|\bcontinue the run\b", lowered):
            if not run_candidates and re.search(r"\b(it|the run|execution)\b", lowered):
                return self._intent_envelope(
                    intent_family=IntentFamily.RUN_SUPERVISION,
                    intent_type=IntentType.CONTINUE_RUN,
                    target_context={"workspace_id": workspace_id},
                    policy=policy,
                    confidence=0.4,
                    needs_clarification=True,
                    clarification_reason=ClarificationReason.AMBIGUOUS_TARGET,
                    clarification_options=[],
                    resolution_notes=["continue target is ambiguous"],
                )
            if len(run_candidates) > 1:
                return self._clarification_from_candidates(
                    family=IntentFamily.RUN_SUPERVISION,
                    intent_type=IntentType.CONTINUE_RUN,
                    target_context={"workspace_id": workspace_id},
                    policy=policy,
                    candidates=run_candidates,
                    notes=notes or ["multiple run candidates matched continue request"],
                )
            return self._intent_envelope(
                intent_family=IntentFamily.RUN_SUPERVISION,
                intent_type=IntentType.CONTINUE_RUN,
                target_context={"workspace_id": workspace_id},
                resolved_subject=run_candidates[0] if len(run_candidates) == 1 else {},
                action_payload={"reference": run_reference or work_reference or text},
                policy=policy,
                confidence=0.86,
                resolution_notes=notes or ["continue requested"],
            )

        if re.search(r"\b(retry|rerun)\b", lowered):
            if not run_candidates and re.search(r"\b(it|the run)\b", lowered):
                return self._intent_envelope(
                    intent_family=IntentFamily.RUN_SUPERVISION,
                    intent_type=IntentType.RETRY_RUN,
                    target_context={"workspace_id": workspace_id},
                    policy=policy,
                    confidence=0.4,
                    needs_clarification=True,
                    clarification_reason=ClarificationReason.AMBIGUOUS_TARGET,
                    clarification_options=[],
                    resolution_notes=["retry target is ambiguous"],
                )
            if len(run_candidates) > 1:
                return self._clarification_from_candidates(
                    family=IntentFamily.RUN_SUPERVISION,
                    intent_type=IntentType.RETRY_RUN,
                    target_context={"workspace_id": workspace_id},
                    policy=policy,
                    candidates=run_candidates,
                    notes=notes or ["multiple run candidates matched retry request"],
                )
            return self._intent_envelope(
                intent_family=IntentFamily.RUN_SUPERVISION,
                intent_type=IntentType.RETRY_RUN,
                target_context={"workspace_id": workspace_id},
                resolved_subject=run_candidates[0] if len(run_candidates) == 1 else {},
                action_payload={"reference": run_reference or work_reference or text},
                policy=policy,
                confidence=0.88,
                resolution_notes=notes or ["retry requested"],
            )

        if re.search(r"\b(show status|status of|what(?:'s| is) the status)\b", lowered):
            if len(run_candidates) > 1:
                return self._clarification_from_candidates(
                    family=IntentFamily.RUN_SUPERVISION,
                    intent_type=IntentType.SHOW_STATUS,
                    target_context={"workspace_id": workspace_id},
                    policy=policy,
                    candidates=run_candidates,
                    notes=notes or ["multiple run candidates matched status request"],
                )
            return self._intent_envelope(
                intent_family=IntentFamily.RUN_SUPERVISION,
                intent_type=IntentType.SHOW_STATUS,
                target_context={"workspace_id": workspace_id},
                resolved_subject=run_candidates[0] if len(run_candidates) == 1 else {},
                action_payload={"reference": work_reference or text},
                policy=policy,
                confidence=0.84,
                resolution_notes=notes or ["status requested"],
            )

        if re.search(r"\b(show|open)\s+logs?\b", lowered):
            if len(run_candidates) > 1:
                return self._clarification_from_candidates(
                    family=IntentFamily.RUN_SUPERVISION,
                    intent_type=IntentType.SHOW_STATUS,
                    target_context={"workspace_id": workspace_id},
                    policy=policy,
                    candidates=run_candidates,
                    notes=notes or ["multiple run candidates matched logs request"],
                )
            return self._intent_envelope(
                intent_family=IntentFamily.RUN_SUPERVISION,
                intent_type=IntentType.SHOW_STATUS,
                target_context={"workspace_id": workspace_id},
                resolved_subject=run_candidates[0] if len(run_candidates) == 1 else {},
                action_payload={"reference": run_reference or work_reference or text, "detail_view": "logs"},
                policy=policy,
                confidence=0.84,
                resolution_notes=notes or ["logs requested"],
            )

        if re.search(r"\b(show|open)\s+artifacts?\b", lowered):
            if len(run_candidates) > 1:
                return self._clarification_from_candidates(
                    family=IntentFamily.RUN_SUPERVISION,
                    intent_type=IntentType.SHOW_STATUS,
                    target_context={"workspace_id": workspace_id},
                    policy=policy,
                    candidates=run_candidates,
                    notes=notes or ["multiple run candidates matched artifacts request"],
                )
            return self._intent_envelope(
                intent_family=IntentFamily.RUN_SUPERVISION,
                intent_type=IntentType.SHOW_STATUS,
                target_context={"workspace_id": workspace_id},
                resolved_subject=run_candidates[0] if len(run_candidates) == 1 else {},
                action_payload={"reference": run_reference or work_reference or text, "detail_view": "artifacts"},
                policy=policy,
                confidence=0.84,
                resolution_notes=notes or ["artifacts requested"],
            )

        if re.search(r"\b(show me what failed|what failed|show failures?)\b", lowered):
            if len(run_candidates) > 1:
                return self._clarification_from_candidates(
                    family=IntentFamily.RUN_SUPERVISION,
                    intent_type=IntentType.SHOW_STATUS,
                    target_context={"workspace_id": workspace_id},
                    policy=policy,
                    candidates=run_candidates,
                    notes=notes or ["multiple run candidates matched failure-status request"],
                )
            return self._intent_envelope(
                intent_family=IntentFamily.RUN_SUPERVISION,
                intent_type=IntentType.SHOW_STATUS,
                target_context={"workspace_id": workspace_id},
                resolved_subject=run_candidates[0] if len(run_candidates) == 1 else {},
                action_payload={"reference": run_reference or work_reference or text, "status_filter": "failed"},
                policy=policy,
                confidence=0.86,
                resolution_notes=notes or ["failure status requested"],
            )

        if re.search(r"\b(summarize run|summarize the run|summarize the current run|what happened)\b", lowered):
            if len(run_candidates) > 1:
                return self._clarification_from_candidates(
                    family=IntentFamily.RUN_SUPERVISION,
                    intent_type=IntentType.SUMMARIZE_RUN,
                    target_context={"workspace_id": workspace_id},
                    policy=policy,
                    candidates=run_candidates,
                    notes=notes or ["multiple run candidates matched summary request"],
                )
            return self._intent_envelope(
                intent_family=IntentFamily.RUN_SUPERVISION,
                intent_type=IntentType.SUMMARIZE_RUN,
                target_context={"workspace_id": workspace_id},
                resolved_subject=run_candidates[0] if len(run_candidates) == 1 else {},
                action_payload={"reference": run_reference or work_reference or text},
                policy=policy,
                confidence=0.82,
                resolution_notes=notes or ["summary requested"],
            )

        if re.search(r"\binvestigat", lowered) or ("failure" in lowered and "investigate" in lowered) or ("look into" in lowered and ("failure" in lowered or "error" in lowered)):
            if len(run_candidates) > 1:
                return self._clarification_from_candidates(
                    family=IntentFamily.DEVELOPMENT_WORK,
                    intent_type=IntentType.INVESTIGATE_ISSUE,
                    target_context={"workspace_id": workspace_id},
                    policy=policy,
                    candidates=run_candidates,
                    notes=notes or ["multiple run candidates matched investigate request"],
                )
            return self._intent_envelope(
                intent_family=IntentFamily.DEVELOPMENT_WORK,
                intent_type=IntentType.INVESTIGATE_ISSUE,
                target_context={"workspace_id": workspace_id},
                resolved_subject=run_candidates[0] if len(run_candidates) == 1 else {},
                action_payload={"reference": run_reference or work_reference or text},
                policy=policy,
                confidence=0.88,
                resolution_notes=notes or ["investigation requested"],
            )

        if re.search(r"\b(run|execute)\s+tests?\b|\brun validation\b", lowered):
            if len(work_candidates) > 1:
                return self._clarification_from_candidates(
                    family=IntentFamily.DEVELOPMENT_WORK,
                    intent_type=IntentType.RUN_VALIDATION,
                    target_context={"workspace_id": workspace_id},
                    policy=policy,
                    candidates=work_candidates,
                    notes=notes or ["multiple work item candidates matched validation request"],
                )
            return self._intent_envelope(
                intent_family=IntentFamily.DEVELOPMENT_WORK,
                intent_type=IntentType.RUN_VALIDATION,
                target_context={"workspace_id": workspace_id},
                resolved_subject=work_candidates[0] if len(work_candidates) == 1 else {},
                action_payload={"reference": work_reference or text},
                policy=policy,
                confidence=0.91,
                resolution_notes=notes or ["validation requested"],
            )

        execution_requested = bool(re.search(r"\b(implement|start with|resume|continue)\b", lowered))
        if re.search(r"\b(continue|resume)\s+(?:the\s+)?(work|it)\b", lowered):
            if not work_candidates and callable(self.work_item_lookup):
                work_candidates = self.work_item_lookup("", workspace_id)
            if len(work_candidates) > 1:
                return self._clarification_from_candidates(
                    family=IntentFamily.DEVELOPMENT_WORK,
                    intent_type=IntentType.CONTINUE_WORK_ITEM,
                    target_context={"workspace_id": workspace_id},
                    policy=policy,
                    candidates=work_candidates,
                    notes=notes or ["generic continue request matched multiple work items"],
                )
            if len(work_candidates) == 1:
                return self._intent_envelope(
                    intent_family=IntentFamily.DEVELOPMENT_WORK,
                    intent_type=IntentType.CONTINUE_WORK_ITEM,
                    target_context={"workspace_id": workspace_id},
                    resolved_subject=work_candidates[0],
                    action_payload={"reference": text, "work_item_action": "continue"},
                    policy=policy,
                    confidence=0.74,
                    resolution_notes=notes or ["generic continue request resolved to the only matching work item"],
                )
            return self._intent_envelope(
                intent_family=IntentFamily.DEVELOPMENT_WORK,
                intent_type=IntentType.CONTINUE_WORK_ITEM,
                target_context={"workspace_id": workspace_id},
                policy=policy,
                confidence=0.4,
                needs_clarification=True,
                clarification_reason=ClarificationReason.AMBIGUOUS_TARGET,
                clarification_options=[],
                resolution_notes=["generic continue request did not identify a unique work item"],
            )
        if execution_requested and (work_reference or "epic " in lowered or "implementation" in lowered):
            if not work_reference and re.search(r"\b(the work|it)\b", lowered):
                return self._intent_envelope(
                    intent_family=IntentFamily.DEVELOPMENT_WORK,
                    intent_type=IntentType.CONTINUE_WORK_ITEM,
                    target_context={"workspace_id": workspace_id},
                    policy=policy,
                    confidence=0.4,
                    needs_clarification=True,
                    clarification_reason=ClarificationReason.AMBIGUOUS_TARGET,
                    clarification_options=[],
                    resolution_notes=["work item reference is ambiguous"],
                )
            if len(work_candidates) > 1:
                return self._clarification_from_candidates(
                    family=IntentFamily.DEVELOPMENT_WORK,
                    intent_type=IntentType.CONTINUE_WORK_ITEM,
                    target_context={"workspace_id": workspace_id},
                    policy=policy,
                    candidates=work_candidates,
                    notes=notes or ["multiple work item candidates matched request"],
                )
            chosen = work_candidates[0] if len(work_candidates) == 1 else {}
            intent_type: IntentType = (
                IntentType.CREATE_AND_DISPATCH_RUN
                if ("implementation" in lowered or "start with" in lowered or policy.get("run_tests"))
                else IntentType.CONTINUE_WORK_ITEM
            )
            if chosen:
                notes.append("reused existing work item")
                return self._intent_envelope(
                    intent_family=IntentFamily.DEVELOPMENT_WORK,
                    intent_type=intent_type,
                    target_context={"workspace_id": workspace_id},
                    resolved_subject=chosen,
                    action_payload={"reference": work_reference or text, "work_item_action": "continue"},
                    policy=policy,
                    confidence=0.9,
                    resolution_notes=notes,
                )
            notes.append("no matching work item found; create new")
            return self._intent_envelope(
                intent_family=IntentFamily.DEVELOPMENT_WORK,
                intent_type=IntentType.CREATE_WORK_ITEM if intent_type == IntentType.CONTINUE_WORK_ITEM else intent_type,
                target_context={"workspace_id": workspace_id},
                resolved_subject={},
                action_payload={"reference": work_reference or text, "work_item_action": "create"},
                policy=policy,
                confidence=0.78,
                resolution_notes=notes,
            )
        return None

    def _resolve_app_operation_intent(self, *, message: str, context: ResolutionContext) -> Optional[IntentEnvelope]:
        workspace_id = str(context.workspace_id or "").strip()
        if not workspace_id or not callable(self.capability_manifest_lookup):
            return None
        manifest = self.capability_manifest_lookup(workspace_id)
        if not isinstance(manifest, dict):
            if re.search(r"\b(show|list|create|add|update|change|rename|delete|remove)\b.*\b(device|devices|location|locations|interface|interfaces|record)\b", str(message or ""), flags=re.IGNORECASE):
                return self._intent_envelope(
                    intent_family=IntentFamily.APP_OPERATION,
                    intent_type=IntentType.UNSUPPORTED_INTENT,
                    target_context={"workspace_id": workspace_id},
                    confidence=0.45,
                    needs_clarification=True,
                    clarification_reason=ClarificationReason.MISSING_WORKSPACE_CONTEXT,
                    clarification_options=[],
                    resolution_notes=["workspace capability manifest is unavailable"],
                )
            return None
        if re.search(r"\b(update|delete|rename)\s+(?:the\s+)?record\b", str(message or ""), flags=re.IGNORECASE):
            entity_options = []
            for entity in manifest.get("entities") if isinstance(manifest.get("entities"), list) else []:
                if not isinstance(entity, dict):
                    continue
                entity_options.append(
                    {
                        "id": str(entity.get("key") or ""),
                        "label": str(entity.get("plural_label") or entity.get("key") or ""),
                        "kind": "entity",
                        "payload": {"entity_key": str(entity.get("key") or "")},
                    }
                )
            return self._intent_envelope(
                intent_family=IntentFamily.APP_OPERATION,
                intent_type=IntentType.UPDATE_RECORD,
                target_context={"workspace_id": workspace_id},
                confidence=0.4,
                needs_clarification=True,
                clarification_reason=ClarificationReason.AMBIGUOUS_TARGET,
                clarification_options=entity_options,
                resolution_notes=["record target is ambiguous"],
            )
        app_resolution = self.app_operation_lookup(message, manifest) if callable(self.app_operation_lookup) else None
        if not isinstance(app_resolution, dict):
            return None
        notes = [str(note) for note in (app_resolution.get("resolution_notes") or []) if str(note).strip()]
        if app_resolution.get("needs_clarification"):
            return self._intent_envelope(
                intent_family=IntentFamily.APP_OPERATION,
                intent_type=str(app_resolution.get("intent_type") or IntentType.UNSUPPORTED_INTENT.value),
                target_context={"workspace_id": workspace_id},
                resolved_subject=app_resolution.get("resolved_subject") if isinstance(app_resolution.get("resolved_subject"), dict) else {},
                action_payload=app_resolution.get("action_payload") if isinstance(app_resolution.get("action_payload"), dict) else {},
                policy={},
                confidence=float(app_resolution.get("confidence") or 0.45),
                needs_clarification=True,
                clarification_reason=str(app_resolution.get("clarification_reason") or ClarificationReason.AMBIGUOUS_TARGET.value),
                clarification_options=app_resolution.get("clarification_options") if isinstance(app_resolution.get("clarification_options"), list) else [],
                resolution_notes=notes,
            )
        return self._intent_envelope(
            intent_family=IntentFamily.APP_OPERATION,
            intent_type=str(app_resolution.get("intent_type") or IntentType.UNSUPPORTED_INTENT.value),
            target_context={"workspace_id": workspace_id},
            resolved_subject=app_resolution.get("resolved_subject") if isinstance(app_resolution.get("resolved_subject"), dict) else {},
            action_payload=app_resolution.get("action_payload") if isinstance(app_resolution.get("action_payload"), dict) else {},
            policy={},
            confidence=float(app_resolution.get("confidence") or 0.86),
            needs_clarification=bool(app_resolution.get("needs_clarification")),
            clarification_reason=str(app_resolution.get("clarification_reason") or "") or None,
            clarification_options=app_resolution.get("clarification_options") if isinstance(app_resolution.get("clarification_options"), list) else [],
            resolution_notes=notes,
        )

    def resolve_intent(self, *, user_message: str, context: ResolutionContext) -> IntentEnvelope:
        if str(context.worker_mention_error or "").strip():
            return self._intent_envelope(
                intent_family=IntentFamily.DEVELOPMENT_WORK,
                intent_type=IntentType.UNSUPPORTED_INTENT,
                target_context={"workspace_id": str(context.workspace_id or "").strip()},
                action_payload={
                    "worker_mention_token": str(context.worker_mention_token or "").strip(),
                    "error": str(context.worker_mention_error or "").strip(),
                },
                confidence=0.0,
                resolution_notes=[str(context.worker_mention_error or "").strip()],
            )
        development = self._resolve_development_intent(message=user_message, context=context)
        app_operation = self._resolve_app_operation_intent(message=user_message, context=context)
        envelope = development or app_operation or self._intent_envelope(
            intent_family=IntentFamily.DEVELOPMENT_WORK,
            intent_type=IntentType.UNSUPPORTED_INTENT,
            target_context={"workspace_id": str(context.workspace_id or "").strip()},
            confidence=0.0,
            resolution_notes=["no Epic D resolver matched the message"],
        )
        return self._apply_worker_request(envelope, context)

    def _base_result(self, *, action_type: str, artifact_type: Optional[str], request_id: str, confidence: float, llm_model: str) -> ResolutionResult:
        return {
            "status": "UnsupportedIntent",
            "action_type": action_type,
            "artifact_type": artifact_type,
            "artifact_id": None,
            "summary": "Unsupported intent.",
            "next_actions": [],
            "audit": {
                "request_id": request_id,
                "confidence": confidence,
                "llm_model": llm_model,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }

    @staticmethod
    def _heuristic_proposal(*, message: str, has_context: bool) -> Optional[Dict[str, Any]]:
        prompt = str(message or "").strip().lower()
        if not prompt:
            return None

        if any(token in prompt for token in ["show options", "what categories", "what formats", "available categories", "available formats"]):
            field = "category" if "categor" in prompt else "format" if "format" in prompt else "category"
            return {
                "action_type": "ShowOptions",
                "artifact_type": "ArticleDraft",
                "inferred_fields": {"field": field},
                "confidence": 0.56,
                "_model": "heuristic",
            }

        if re.search(r"\bcontext\s*pack\b", prompt) and re.search(r"\b(add|set|update|rewrite|change|edit|patch)\b", prompt):
            return {
                "action_type": "ProposePatch",
                "artifact_type": "ContextPack",
                "inferred_fields": {},
                "confidence": 0.56,
                "_model": "heuristic",
            }

        if has_context and re.search(r"\b(add|set|update|rewrite|change|edit|patch)\b", prompt):
            return {
                "action_type": "ProposePatch",
                "artifact_type": "ArticleDraft",
                "inferred_fields": {},
                "confidence": 0.56,
                "_model": "heuristic",
            }

        create_verbs = re.search(r"\b(create|make|start|new|draft|write|build)\b", prompt)
        artifact_tokens = re.search(r"\b(article|guide|tour|explainer|video)\b", prompt)
        if create_verbs and artifact_tokens:
            inferred_fields: Dict[str, Any] = {}
            if "explainer" in prompt or "video" in prompt:
                inferred_fields["format"] = "explainer_video"
            elif "guide" in prompt:
                inferred_fields["format"] = "guide"
            elif "tour" in prompt:
                inferred_fields["format"] = "tour"
            else:
                inferred_fields["format"] = "article"
            return {
                "action_type": "CreateDraft",
                "artifact_type": "ArticleDraft",
                "inferred_fields": inferred_fields,
                "confidence": 0.56,
                "_model": "heuristic",
            }
        return None

    def resolve(self, *, message: str, context: ResolutionContext) -> tuple[ResolutionResult, Dict[str, Any]]:
        request_id = str(uuid.uuid4())
        artifact_type_hint = "ContextPack" if context.artifact and context.artifact.source_ref_type == "ContextPack" else "ArticleDraft"
        has_context = context.artifact is not None

        try:
            proposal = self.proposal_provider.propose(
                message=message,
                artifact_type_hint=artifact_type_hint,
                has_artifact_context=has_context,
            )
        except IntentContextPackMissingError as exc:
            result = self._base_result(
                action_type="ValidateDraft",
                artifact_type=artifact_type_hint,
                request_id=request_id,
                confidence=0.0,
                llm_model="",
            )
            result["status"] = "UnsupportedIntent"
            result["summary"] = str(exc)
            result["audit"] = {
                **(result.get("audit") or {}),
                "context_pack_slug": exc.slug,
                "context_pack_version": "",
                "context_pack_hash": "",
            }
            return result, {}
        action_type = str(proposal.get("action_type") or "").strip()
        artifact_type = proposal.get("artifact_type")
        confidence = float(proposal.get("confidence") or 0.0)
        llm_model = str(proposal.get("_model") or "")
        context_pack_slug = str(proposal.get("_context_pack_slug") or "")
        context_pack_version = str(proposal.get("_context_pack_version") or "")
        context_pack_hash = str(proposal.get("_context_pack_hash") or "")

        if confidence < 0.55:
            heuristic = self._heuristic_proposal(message=message, has_context=has_context)
            if heuristic:
                proposal = heuristic
                action_type = str(proposal.get("action_type") or "").strip()
                artifact_type = proposal.get("artifact_type")
                confidence = float(proposal.get("confidence") or confidence)
                llm_model = str(proposal.get("_model") or llm_model)

        result = self._base_result(
            action_type=action_type or "ValidateDraft",
            artifact_type=str(artifact_type) if artifact_type else artifact_type_hint,
            request_id=request_id,
            confidence=confidence,
            llm_model=llm_model,
        )
        result["audit"] = {
            **(result.get("audit") or {}),
            "context_pack_slug": context_pack_slug,
            "context_pack_version": context_pack_version,
            "context_pack_hash": context_pack_hash,
        }

        if action_type not in ALLOWED_ACTIONS:
            result["status"] = "UnsupportedIntent"
            result["summary"] = "Intent action is unsupported."
            return result, proposal

        if action_type in {"CreateDraft", "ProposePatch", "ValidateDraft"}:
            target_type = str(artifact_type or artifact_type_hint)
            if target_type not in ALLOWED_ARTIFACT_TYPES:
                result["status"] = "UnsupportedIntent"
                result["summary"] = "Artifact type is unsupported for intent resolution."
                return result, proposal

        if confidence < 0.55:
            result["status"] = "UnsupportedIntent"
            result["summary"] = "Intent is ambiguous; provide clearer draft instructions."
            result["next_actions"] = [
                {"label": "Show category options", "action": "ShowOptions", "field": "category"},
                {"label": "Show format options", "action": "ShowOptions", "field": "format"},
            ]
            return result, proposal

        inferred_fields = proposal.get("inferred_fields") if isinstance(proposal.get("inferred_fields"), dict) else {}

        if action_type == "ShowOptions":
            field_name = str(inferred_fields.get("field") or proposal.get("field") or "").strip().lower()
            target_type = str(artifact_type or artifact_type_hint)
            allowed_fields = {"category", "format", "duration"} if target_type == "ArticleDraft" else {"format"}
            if field_name not in allowed_fields:
                result["status"] = "ValidationError"
                result["summary"] = "Options field is required."
                result["validation_errors"] = [f"field must be one of: {', '.join(sorted(allowed_fields))}"]
                return result, proposal
            contract = self.contracts.get(target_type)
            options = contract.options_for_field(field_name) if contract else []
            result["status"] = "DraftReady"
            result["summary"] = f"Options ready for {field_name}."
            result["options"] = options
            result["next_actions"] = []
            return result, proposal

        target_type = str(artifact_type or artifact_type_hint)
        contract = self.contracts.get(target_type)
        if contract is None:
            result["status"] = "UnsupportedIntent"
            result["summary"] = f"{target_type} intake contract is unavailable."
            return result, proposal

        inferred_fields = contract.infer_fields(message=message, inferred_fields=inferred_fields)
        merged = contract.merge_defaults(inferred_fields)

        if action_type == "ProposePatch":
            target_artifact = context.artifact
            if target_artifact is None and target_type == "ContextPack" and callable(self.context_pack_target_lookup):
                target_artifact = self.context_pack_target_lookup(message=message, proposal=proposal)
            if target_artifact is None:
                result["status"] = "ValidationError"
                result["summary"] = "Artifact context is required to propose a patch."
                result["validation_errors"] = ["artifact context missing"]
                return result, proposal
            if target_type == "ContextPack":
                patch_object = {key: value for key, value in inferred_fields.items() if key in {"title", "summary", "tags", "content", "format"}}
            else:
                patch_object = {
                    key: value
                    for key, value in inferred_fields.items()
                    if key in {"title", "category", "format", "intent", "duration", "scenes", "tags", "summary", "body"}
                }
            if not patch_object:
                result["status"] = "ValidationError"
                result["summary"] = "No patch fields were inferred from the intent."
                result["validation_errors"] = ["empty patch"]
                return result, proposal
            from .patch_service import PatchValidationError, validate_context_pack_patch, validate_patch

            try:
                if target_type == "ContextPack":
                    from xyn_orchestrator.models import ContextPack

                    pack = (
                        ContextPack.objects.filter(id=target_artifact.source_ref_id).first()
                        if str(target_artifact.source_ref_type or "") == "ContextPack"
                        else None
                    )
                    if pack is None:
                        raise PatchValidationError("context pack target is unavailable")
                    normalized_patch, changes = validate_context_pack_patch(
                        pack=pack,
                        patch_object=patch_object,
                    )
                else:
                    allowed_categories = [str(opt.get("slug") if isinstance(opt, dict) else opt).strip().lower() for opt in contract.options_for_field("category")]
                    normalized_patch, changes = validate_patch(
                        artifact=target_artifact,
                        patch_object=patch_object,
                        allowed_categories=allowed_categories,
                    )
            except PatchValidationError as exc:
                result["status"] = "ValidationError"
                result["summary"] = "Patch proposal failed deterministic validation."
                result["validation_errors"] = [str(exc)]
                return result, proposal
            result["status"] = "ProposedPatch"
            result["artifact_id"] = str(target_artifact.id)
            result["artifact_type"] = target_type
            result["summary"] = "Patch proposal is ready for confirmation."
            result["proposed_patch"] = {
                "changes": changes,
                "patch_object": normalized_patch,
                "requires_confirmation": True,
            }
            result["next_actions"] = [{"label": "Apply", "action": "ApplyPatch"}]
            return result, proposal

        if action_type in {"CreateDraft", "ValidateDraft"}:
            if target_type == "ContextPack" and action_type == "CreateDraft":
                result["status"] = "UnsupportedIntent"
                result["summary"] = "CreateDraft is not supported for ContextPack."
                result["next_actions"] = [{"label": "Propose patch", "action": "ProposePatch"}]
                return result, proposal
            normalized_values = dict(merged)
            if "format" in normalized_values:
                normalized_values["format"] = contract.normalize_format(normalized_values.get("format"))
            missing = contract.missing_fields(normalized_values)
            if missing:
                result["status"] = "MissingFields"
                result["summary"] = "Draft requires additional fields before it can proceed."
                result["missing_fields"] = [
                    {
                        "field": field_name,
                        "reason": "required by intake contract",
                        "options_available": contract.options_available(field_name),
                    }
                    for field_name in missing
                ]
                result["next_actions"] = [{"label": "Show options", "action": "ShowOptions"}]
                return result, proposal

            result["status"] = "DraftReady"
            if target_type == "ContextPack":
                result["summary"] = "Context pack payload is valid."
                result["draft_payload"] = {
                    "title": str(normalized_values.get("title") or "").strip(),
                    "format": str(normalized_values.get("format") or "json"),
                    "summary": str(normalized_values.get("summary") or ""),
                    "tags": normalized_values.get("tags") if isinstance(normalized_values.get("tags"), list) else [],
                    "content": str(normalized_values.get("content") or ""),
                }
                result["next_actions"] = [{"label": "Propose patch", "action": "ProposePatch"}]
            else:
                result["summary"] = "Draft payload is ready for apply."
                result["draft_payload"] = {
                    "title": str(normalized_values.get("title") or "").strip(),
                    "category": str(normalized_values.get("category") or "").strip().lower(),
                    "format": str(normalized_values.get("format") or "article"),
                    "intent": str(normalized_values.get("intent") or "").strip(),
                    "duration": str(normalized_values.get("duration") or "").strip(),
                    "tags": normalized_values.get("tags") if isinstance(normalized_values.get("tags"), list) else [],
                    "summary": str(normalized_values.get("summary") or ""),
                    "body": str(normalized_values.get("body") or ""),
                }
                result["next_actions"] = [{"label": "Create draft", "action": "CreateDraft"}]
            return result, proposal

        result["status"] = "UnsupportedIntent"
        result["summary"] = "Intent action is unsupported."
        return result, proposal
