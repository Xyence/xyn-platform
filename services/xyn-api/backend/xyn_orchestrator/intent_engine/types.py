from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, TypedDict

from pydantic import BaseModel, Field


IntentAction = Literal["CreateDraft", "ProposePatch", "ShowOptions", "ValidateDraft"]
IntentStatus = Literal[
    "DraftReady",
    "MissingFields",
    "ProposedPatch",
    "ValidationError",
    "UnsupportedIntent",
]


class MissingFieldItem(TypedDict):
    field: str
    reason: str
    options_available: bool


class PatchChange(TypedDict):
    field: str
    from_value: Any
    to: Any


class ResolutionResult(TypedDict, total=False):
    status: IntentStatus
    action_type: str
    artifact_type: Optional[str]
    artifact_id: Optional[str]
    summary: str
    missing_fields: List[MissingFieldItem]
    options: List[Any]
    proposed_patch: Dict[str, Any]
    draft_payload: Dict[str, Any]
    validation_errors: List[str]
    next_actions: List[Dict[str, Any]]
    audit: Dict[str, Any]


ALLOWED_ACTIONS = {"CreateDraft", "ProposePatch", "ShowOptions", "ValidateDraft"}
ALLOWED_ARTIFACT_TYPES = {"ArticleDraft", "ContextPack"}
ARTICLE_PATCHABLE_FIELDS = {
    "title",
    "category",
    "format",
    "intent",
    "duration",
    "scenes",
    "tags",
    "summary",
    "body",
}
CONTEXT_PACK_PATCHABLE_FIELDS = {"title", "summary", "tags", "content", "format"}


class IntentFamily(str, Enum):
    APP_OPERATION = "app_operation"
    DEVELOPMENT_WORK = "development_work"
    RUN_SUPERVISION = "run_supervision"
    THREAD_COORDINATION = "thread_coordination"
    GOAL_PLANNING = "goal_planning"


class IntentType(str, Enum):
    CREATE_RECORD = "create_record"
    UPDATE_RECORD = "update_record"
    DELETE_RECORD = "delete_record"
    LIST_RECORDS = "list_records"
    GET_RECORD = "get_record"
    CREATE_WORK_ITEM = "create_work_item"
    CONTINUE_WORK_ITEM = "continue_work_item"
    CREATE_AND_DISPATCH_RUN = "create_and_dispatch_run"
    RUN_VALIDATION = "run_validation"
    INVESTIGATE_ISSUE = "investigate_issue"
    SUMMARIZE_RUN = "summarize_run"
    SHOW_STATUS = "show_status"
    CONTINUE_RUN = "continue_run"
    RETRY_RUN = "retry_run"
    PAUSE_OR_HOLD = "pause_or_hold"
    REQUEST_REVIEW = "request_review"
    CREATE_THREAD = "create_thread"
    LIST_THREADS = "list_threads"
    SHOW_THREAD = "show_thread"
    SHOW_THREAD_REVIEW = "show_thread_review"
    PAUSE_THREAD = "pause_thread"
    RESUME_THREAD = "resume_thread"
    PRIORITIZE_THREAD = "prioritize_thread"
    SHOW_ARTIFACT_ANALYSIS = "show_artifact_analysis"
    CREATE_GOAL = "create_goal"
    DECOMPOSE_GOAL = "decompose_goal"
    SUMMARIZE_PLAN = "summarize_plan"
    QUEUE_FIRST_SLICE = "queue_first_slice"
    LIST_GOALS = "list_goals"
    SHOW_GOAL = "show_goal"
    CREATE_CAMPAIGN = "create_campaign"
    LIST_CAMPAIGNS = "list_campaigns"
    SHOW_CAMPAIGN = "show_campaign"
    LIST_APPLICATION_FACTORIES = "list_application_factories"
    OPEN_COMPOSER = "open_composer"
    GENERATE_APPLICATION_PLAN = "generate_application_plan"
    APPLY_APPLICATION_PLAN = "apply_application_plan"
    SHOW_APPLICATION = "show_application"
    APPROVE_PLAN = "approve_plan"
    APPROVE_RECOMMENDATION = "approve_recommendation"
    DEFER_EXECUTION = "defer_execution"
    ADJUST_PLAN = "adjust_plan"
    RECOMMEND_NEXT_SLICE = "recommend_next_slice"
    QUEUE_NEXT_SLICE = "queue_next_slice"
    UNSUPPORTED_DECLARED_ENTITY = "unsupported_declared_entity"
    UNSUPPORTED_INTENT = "unsupported_intent"


class ClarificationReason(str, Enum):
    AMBIGUOUS_TARGET = "ambiguous_target"
    MISSING_TARGET = "missing_target"
    MISSING_WORKSPACE_CONTEXT = "missing_workspace_context"
    UNSUPPORTED_DECLARED_ENTITY = "unsupported_declared_entity"


class ClarificationOption(BaseModel):
    id: str
    label: str
    kind: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)


class IntentEnvelope(BaseModel):
    intent_family: str
    intent_type: str
    target_context: Dict[str, Any] = Field(default_factory=dict)
    resolved_subject: Dict[str, Any] = Field(default_factory=dict)
    action_payload: Dict[str, Any] = Field(default_factory=dict)
    policy: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    needs_clarification: bool = False
    clarification_reason: Optional[str] = None
    clarification_options: List[ClarificationOption] = Field(default_factory=list)
    resolution_notes: List[str] = Field(default_factory=list)


class PromptInterpretationExecutionMode(str, Enum):
    IMMEDIATE_EXECUTION = "immediate_execution"
    QUEUED_RUN = "queued_run"
    WORK_ITEM_CREATION = "work_item_creation"
    WORK_ITEM_CONTINUATION = "work_item_continuation"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    AWAITING_REVIEW = "awaiting_review"
    BLOCKED = "blocked"


class PromptInterpretationCapabilityStateValue(str, Enum):
    ENABLED = "enabled"
    KNOWN_DISABLED = "known_but_disabled"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


class PromptInterpretationCapabilityState(BaseModel):
    state: str
    term: Optional[str] = None
    alternative: Optional[str] = None
    reason: Optional[str] = None


class PromptInterpretationTarget(BaseModel):
    id: Optional[str] = None
    key: Optional[str] = None
    label: Optional[str] = None
    reference: Optional[str] = None
    status: Optional[str] = None


class PromptInterpretationAction(BaseModel):
    verb: str
    label: str


class PromptInterpretationField(BaseModel):
    name: str
    value: Any = None
    kind: str = "field"
    state: str = "resolved"


class PromptInterpretationSpan(BaseModel):
    kind: str
    text: str
    start: int
    end: int
    state: str = "recognized"


class PromptInterpretation(BaseModel):
    intent_family: str
    intent_type: str
    target_application: Optional[PromptInterpretationTarget] = None
    target_application_plan: Optional[PromptInterpretationTarget] = None
    target_goal: Optional[PromptInterpretationTarget] = None
    target_entity: Optional[PromptInterpretationTarget] = None
    target_record: Optional[PromptInterpretationTarget] = None
    target_thread: Optional[PromptInterpretationTarget] = None
    target_work_item: Optional[PromptInterpretationTarget] = None
    target_run: Optional[PromptInterpretationTarget] = None
    action: PromptInterpretationAction
    fields: List[PromptInterpretationField] = Field(default_factory=list)
    execution_mode: str
    confidence: float = 0.0
    needs_clarification: bool = False
    capability_state: PromptInterpretationCapabilityState = Field(
        default_factory=lambda: PromptInterpretationCapabilityState(state=PromptInterpretationCapabilityStateValue.UNKNOWN.value)
    )
    clarification_reason: Optional[str] = None
    clarification_options: List[ClarificationOption] = Field(default_factory=list)
    resolution_notes: List[str] = Field(default_factory=list)
    missing_fields: List[str] = Field(default_factory=list)
    recognized_spans: List[PromptInterpretationSpan] = Field(default_factory=list)


class ConversationActionType(str, Enum):
    CREATE_WORK_ITEM = "create_work_item"
    CONTINUE_WORK_ITEM = "continue_work_item"
    DISPATCH_RUN = "dispatch_run"
    EXECUTE_ENTITY_OPERATION = "execute_entity_operation"
    CONTINUE_RUN = "continue_run"
    RETRY_RUN = "retry_run"
    SUMMARIZE_RUN = "summarize_run"
    SHOW_STATUS = "show_status"
    PAUSE_RUN = "pause_run"
    REQUEST_REVIEW = "request_review"
    CREATE_THREAD = "create_thread"
    LIST_THREADS = "list_threads"
    SHOW_THREAD = "show_thread"
    SHOW_THREAD_REVIEW = "show_thread_review"
    PAUSE_THREAD = "pause_thread"
    RESUME_THREAD = "resume_thread"
    PRIORITIZE_THREAD = "prioritize_thread"
    SHOW_ARTIFACT_ANALYSIS = "show_artifact_analysis"
    CREATE_GOAL = "create_goal"
    DECOMPOSE_GOAL = "decompose_goal"
    SUMMARIZE_PLAN = "summarize_plan"
    QUEUE_FIRST_SLICE = "queue_first_slice"
    LIST_GOALS = "list_goals"
    SHOW_GOAL = "show_goal"
    CREATE_CAMPAIGN = "create_campaign"
    LIST_CAMPAIGNS = "list_campaigns"
    SHOW_CAMPAIGN = "show_campaign"
    LIST_APPLICATION_FACTORIES = "list_application_factories"
    OPEN_COMPOSER = "open_composer"
    GENERATE_APPLICATION_PLAN = "generate_application_plan"
    APPLY_APPLICATION_PLAN = "apply_application_plan"
    SHOW_APPLICATION = "show_application"
    APPROVE_PLAN = "approve_plan"
    APPROVE_RECOMMENDATION = "approve_recommendation"
    DEFER_EXECUTION = "defer_execution"
    ADJUST_PLAN = "adjust_plan"
    RECOMMEND_NEXT_SLICE = "recommend_next_slice"
    QUEUE_NEXT_SLICE = "queue_next_slice"


class ConversationActionTarget(BaseModel):
    kind: str
    id: Optional[str] = None
    key: Optional[str] = None
    label: Optional[str] = None
    reference: Optional[str] = None
    workspace_id: Optional[str] = None


class ConversationAction(BaseModel):
    action_type: str
    source_message_id: str
    thread_id: Optional[str] = None
    intent_type: str
    target_object: ConversationActionTarget
    execution_mode: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class ConversationContextEntity(BaseModel):
    entity_key: Optional[str] = None
    reference: Optional[str] = None
    label: Optional[str] = None


class ConversationContextArtifact(BaseModel):
    artifact_id: Optional[str] = None
    label: Optional[str] = None
    artifact_type: Optional[str] = None
    run_id: Optional[str] = None


class ConversationExecutionContext(BaseModel):
    thread_id: Optional[str] = None
    active_application_id: Optional[str] = None
    active_application_plan_id: Optional[str] = None
    active_goal_id: Optional[str] = None
    active_coordination_thread_id: Optional[str] = None
    current_work_item_id: Optional[str] = None
    current_run_id: Optional[str] = None
    active_epic: Optional[str] = None
    recent_entities: List[ConversationContextEntity] = Field(default_factory=list)
    recent_artifacts: List[ConversationContextArtifact] = Field(default_factory=list)
