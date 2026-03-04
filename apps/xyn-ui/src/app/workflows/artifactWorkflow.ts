import type { ArticleDetail } from "../../api/types";

export type WorkflowActionId =
  | "mark_reviewed"
  | "mark_ratified"
  | "publish"
  | "deprecate"
  | "save_revision"
  | "view_revisions"
  | "endorse"
  | "oppose"
  | "neutral";

export type WorkflowActionGroup = "workflow" | "revision" | "position" | "danger";
export type WorkflowActionIntent = "primary" | "secondary" | "danger";

export type WorkflowConfirmationConfig = {
  title: string;
  body: string;
  confirmLabel: string;
};

export type WorkflowAction = {
  id: WorkflowActionId;
  label: string;
  group: WorkflowActionGroup;
  intent: WorkflowActionIntent;
  enabled: boolean;
  hidden: boolean;
  disabledReason?: string;
  helpText?: string;
  confirmation?: WorkflowConfirmationConfig;
};

export type ArtifactWorkflowView = {
  statusLabel: string;
  statusTone: "info" | "warn" | "good" | "bad" | "neutral";
  nextStepLabel: string;
  blockers: string[];
  primaryAction: WorkflowAction | null;
  secondaryActions: WorkflowAction[];
};

export type ArtifactWorkflowResolverInput = {
  artifactType: "article";
  article: Pick<ArticleDetail, "status" | "visibility_type" | "allowed_roles" | "published_to"> & {
    title?: string;
    summary?: string;
  };
  validation: {
    hasBodyMarkdown: boolean;
    hasSummary: boolean;
  };
  capabilities: {
    canManageLifecycle: boolean;
    canSaveRevision: boolean;
    canReact: boolean;
    canViewRevisions: boolean;
  };
};

const STATUS_TONE: Record<string, ArtifactWorkflowView["statusTone"]> = {
  draft: "neutral",
  reviewed: "info",
  ratified: "warn",
  published: "good",
  deprecated: "bad",
};

const TRANSITIONS: Record<string, WorkflowActionId[]> = {
  draft: ["mark_reviewed", "publish", "deprecate"],
  reviewed: ["mark_ratified", "publish", "deprecate"],
  ratified: ["publish", "deprecate"],
  published: ["deprecate"],
  deprecated: [],
};

const PRIMARY_TRANSITION_BY_STATUS: Partial<Record<string, WorkflowActionId>> = {
  draft: "mark_reviewed",
  reviewed: "mark_ratified",
  ratified: "publish",
};

function _hasPublishBinding(article: ArtifactWorkflowResolverInput["article"]): boolean {
  return Boolean((article.published_to || []).length > 0);
}

function _validationBlockers(input: ArtifactWorkflowResolverInput): string[] {
  const blockers: string[] = [];
  if (!input.validation.hasBodyMarkdown) blockers.push("Body markdown is required.");
  if (!input.validation.hasSummary) blockers.push("Summary is required.");
  if (input.article.visibility_type === "role_based" && (input.article.allowed_roles || []).length === 0) {
    blockers.push("At least one allowed role is required for role-based visibility.");
  }
  return blockers;
}

function _actionLabel(id: WorkflowActionId): string {
  switch (id) {
    case "mark_reviewed":
      return "Mark reviewed";
    case "mark_ratified":
      return "Mark ratified";
    case "publish":
      return "Publish";
    case "deprecate":
      return "Deprecate";
    case "save_revision":
      return "Save revision";
    case "view_revisions":
      return "View revisions";
    case "endorse":
      return "Endorse";
    case "oppose":
      return "Oppose";
    case "neutral":
      return "Neutral";
    default:
      return id;
  }
}

function _actionConfirmation(id: WorkflowActionId, input: ArtifactWorkflowResolverInput): WorkflowConfirmationConfig | undefined {
  if (id === "publish") {
    const visibilityTarget = _hasPublishBinding(input.article) ? "configured publish surfaces" : "its default visibility targets";
    return {
      title: "Publish article",
      body: `This will move the article to Published and make it visible on ${visibilityTarget}.`,
      confirmLabel: "Confirm publish",
    };
  }
  if (id === "deprecate") {
    return {
      title: "Deprecate article",
      body: "This marks the article as deprecated and removes it from normal active workflows.",
      confirmLabel: "Confirm deprecate",
    };
  }
  return undefined;
}

function _nextStepLabel(status: string): string {
  if (status === "draft") return "Next required step: mark as reviewed.";
  if (status === "reviewed") return "Next required step: mark as ratified.";
  if (status === "ratified") return "Next required step: publish.";
  if (status === "published") return "No required lifecycle step. Optional: deprecate if superseded.";
  if (status === "deprecated") return "Lifecycle complete. This artifact is deprecated.";
  return "Next step unavailable.";
}

function _buildTransitionAction(id: WorkflowActionId, input: ArtifactWorkflowResolverInput, blockers: string[]): WorkflowAction {
  const status = input.article.status;
  const allowed = new Set(TRANSITIONS[status] || []);
  const hidden = !allowed.has(id);
  const lifecycleBlocked = id === "mark_reviewed" || id === "publish";
  const transitionBlockers = lifecycleBlocked ? blockers : [];
  let disabledReason: string | undefined;
  let enabled = true;
  if (!input.capabilities.canManageLifecycle) {
    enabled = false;
    disabledReason = "You do not have permission to run lifecycle transitions.";
  } else if (transitionBlockers.length > 0) {
    enabled = false;
    disabledReason = transitionBlockers[0];
  }
  return {
    id,
    label: _actionLabel(id),
    group: id === "deprecate" ? "danger" : "workflow",
    intent: id === "deprecate" ? "danger" : "secondary",
    enabled,
    hidden,
    disabledReason,
    confirmation: _actionConfirmation(id, input),
  };
}

/**
 * Reusable resolver for artifact workflow action UX.
 * To add new artifact types later, keep this API and branch on artifactType
 * with a dedicated state transition map + rule set.
 */
export function resolveArtifactWorkflowActions(input: ArtifactWorkflowResolverInput): ArtifactWorkflowView {
  const status = input.article.status || "draft";
  const blockers = _validationBlockers(input);
  const statusTone = STATUS_TONE[status] || "neutral";
  const nextStepLabel = _nextStepLabel(status);

  const actions: WorkflowAction[] = [
    _buildTransitionAction("mark_reviewed", input, blockers),
    _buildTransitionAction("mark_ratified", input, blockers),
    _buildTransitionAction("publish", input, blockers),
    _buildTransitionAction("deprecate", input, blockers),
    {
      id: "save_revision",
      label: "Save revision",
      group: "revision",
      intent: "secondary",
      enabled: input.capabilities.canSaveRevision,
      hidden: false,
      disabledReason: input.capabilities.canSaveRevision ? undefined : "You do not have permission to save revisions.",
    },
    {
      id: "view_revisions",
      label: "View revisions",
      group: "revision",
      intent: "secondary",
      enabled: input.capabilities.canViewRevisions,
      hidden: false,
      disabledReason: input.capabilities.canViewRevisions ? undefined : "Revision history is unavailable.",
    },
    {
      id: "endorse",
      label: "Endorse",
      group: "position",
      intent: "secondary",
      enabled: input.capabilities.canReact,
      hidden: false,
      disabledReason: input.capabilities.canReact ? undefined : "You do not have permission to set a position.",
    },
    {
      id: "oppose",
      label: "Oppose",
      group: "position",
      intent: "secondary",
      enabled: input.capabilities.canReact,
      hidden: false,
      disabledReason: input.capabilities.canReact ? undefined : "You do not have permission to set a position.",
    },
    {
      id: "neutral",
      label: "Neutral",
      group: "position",
      intent: "secondary",
      enabled: input.capabilities.canReact,
      hidden: false,
      disabledReason: input.capabilities.canReact ? undefined : "You do not have permission to set a position.",
    },
  ];

  const primaryTransition = PRIMARY_TRANSITION_BY_STATUS[status];
  const primaryAction = primaryTransition ? actions.find((action) => action.id === primaryTransition) || null : null;
  const secondaryActions = actions.filter((action) => !action.hidden && action.id !== primaryAction?.id);

  return {
    statusLabel: status,
    statusTone,
    nextStepLabel,
    blockers,
    primaryAction,
    secondaryActions,
  };
}
