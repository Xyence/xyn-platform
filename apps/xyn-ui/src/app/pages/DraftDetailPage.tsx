import { AlertTriangle, ExternalLink, FilePenLine, History, RefreshCw, Save, Send, Waypoints } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import ActionRowCard from "../components/ui/ActionRowCard";
import { getAppIntentDraft, getDraftWorkflow, listAppExecutionNotes, listAppJobs, submitAppIntentDraft, updateAppIntentDraft } from "../../api/xyn";
import type { AppExecutionNote, AppIntentDraft, AppJob, DraftWorkflow } from "../../api/types";
import WorkspaceContextBar from "../components/common/WorkspaceContextBar";
import { toWorkspacePath } from "../routing/workspaceRouting";
import { useNotifications } from "../state/notificationsStore";
import { getAppDraftViewDescriptor } from "../drafts/appDraftView";
import { emitCapabilityEvent } from "../events/emitCapabilityEvent";

type DraftStatusValue = "draft" | "ready" | "submitted" | "archived";
type DraftPageOverallState = "draft" | "building" | "build_blocked" | "ready" | "needs_revision" | "unavailable";
type TimelineStepStatus = "complete" | "current" | "pending" | "failed";
type DraftActionId =
  | "review_failure"
  | "retry_validation"
  | "view_build_jobs"
  | "edit_definition"
  | "open_generated_environment"
  | "open_application_workspace"
  | "save_draft"
  | "submit_draft";

type DraftActionCard = {
  id: DraftActionId;
  title: string;
  description: string;
  badge: string;
  available: boolean;
  disabledReason?: string;
  emphasis?: "primary" | "secondary";
};

type DraftTimelineStep = {
  key: string;
  label: string;
  detail: string;
  status: TimelineStepStatus;
};

type DraftPageViewModel = {
  overallState: DraftPageOverallState;
  overallLabel: string;
  currentStep: string;
  plainLanguageStatus: string;
  lastUpdated: string | null;
  succeeded: string[];
  failed: string[];
  appArtifactLabel: string;
  runtimeLabel: string;
  workspaceRoutingLabel: string;
  primaryNextStep: string;
  failureSummaryTitle: string;
  failureSummaryBody: string;
  buildTimeline: DraftTimelineStep[];
  recommendedActions: DraftActionCard[];
};

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return "{}";
  }
}

function parseJsonText(value: string): Record<string, unknown> {
  const parsed = JSON.parse(value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
  return parsed as Record<string, unknown>;
}

function withDocsUrl(url: string): string {
  const raw = String(url || "").trim();
  if (!raw) return "";
  return raw.replace(/\/+$/, "") + "/docs";
}

function normalizeJobStatus(status?: string): "queued" | "running" | "succeeded" | "failed" {
  const token = String(status || "").trim().toLowerCase();
  if (token === "succeeded") return "succeeded";
  if (token === "failed") return "failed";
  if (token === "running") return "running";
  return "queued";
}

function jobTimestamp(job: AppJob): number {
  const value = job.updated_at || job.created_at || "";
  const parsed = new Date(value).getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
}

function collectRelatedJobs(allJobs: AppJob[], draftId: string, seedJobId: string): AppJob[] {
  const related = new Set<string>();
  const trimmedDraftId = String(draftId || "").trim();
  const trimmedSeedJobId = String(seedJobId || "").trim();
  if (trimmedSeedJobId) related.add(trimmedSeedJobId);
  for (const job of allJobs) {
    const input = job.input_json && typeof job.input_json === "object" ? job.input_json : {};
    if (trimmedDraftId && String(input.draft_id || "").trim() === trimmedDraftId) {
      related.add(job.id);
    }
  }
  let changed = true;
  while (changed) {
    changed = false;
    for (const job of allJobs) {
      const input = job.input_json && typeof job.input_json === "object" ? job.input_json : {};
      const sourceJobId = String(input.source_job_id || "").trim();
      if (sourceJobId && related.has(sourceJobId) && !related.has(job.id)) {
        related.add(job.id);
        changed = true;
      }
    }
  }
  return allJobs
    .filter((job) => related.has(job.id))
    .sort((left, right) => jobTimestamp(left) - jobTimestamp(right));
}

function uniqueTokens(values: unknown[]): string[] {
  return Array.from(
    new Set(
      values
        .map((value) => String(value || "").trim())
        .filter((value) => value.length > 0),
    ),
  );
}

function extractBuildSelectors(allJobs: AppJob[]): {
  noteIds: string[];
  jobIds: string[];
  relatedArtifactIds: string[];
} {
  const noteIds: unknown[] = [];
  const jobIds: unknown[] = [];
  const relatedArtifactIds: unknown[] = [];
  for (const job of allJobs) {
    jobIds.push(job.id);
    const payloads = [job.input_json, job.output_json];
    for (const payload of payloads) {
      if (!payload || typeof payload !== "object") continue;
      const record = payload as Record<string, unknown>;
      noteIds.push(record.execution_note_artifact_id);
      relatedArtifactIds.push(record.app_spec_artifact_id);
      const queued = Array.isArray(record.queued_jobs) ? record.queued_jobs : [];
      queued.forEach((item) => {
        if (item && typeof item === "object") {
          const jobRef = item as Record<string, unknown>;
          jobIds.push(jobRef.job_id);
        }
      });
    }
  }
  return {
    noteIds: uniqueTokens(noteIds),
    jobIds: uniqueTokens(jobIds),
    relatedArtifactIds: uniqueTokens(relatedArtifactIds),
  };
}

function extractInstalledCapability(allJobs: AppJob[]): {
  appSlug: string;
  title: string;
  reports: string[];
} | null {
  for (const job of allJobs) {
    const payloads = [job.input_json, job.output_json];
    for (const payload of payloads) {
      if (!payload || typeof payload !== "object") continue;
      const record = payload as Record<string, unknown>;
      const appSpec = record.app_spec && typeof record.app_spec === "object" ? (record.app_spec as Record<string, unknown>) : null;
      if (!appSpec) continue;
      const appSlug = String(appSpec.app_slug || "").trim();
      if (!appSlug) continue;
      return {
        appSlug,
        title: String(appSpec.title || appSlug).trim() || appSlug,
        reports: Array.isArray(appSpec.reports) ? appSpec.reports.map((item) => String(item || "").trim()).filter(Boolean) : [],
      };
    }
  }
  return null;
}

function extractSiblingInstalledArtifact(allJobs: AppJob[]): {
  artifactId: string;
  artifactSlug: string;
  workspaceId: string;
  workspaceSlug: string;
} | null {
  for (const job of allJobs) {
    const payloads = [job.output_json, job.input_json];
    for (const payload of payloads) {
      if (!payload || typeof payload !== "object") continue;
      const record = payload as Record<string, unknown>;
      const sibling = record.sibling_xyn && typeof record.sibling_xyn === "object" ? (record.sibling_xyn as Record<string, unknown>) : {};
      const installed =
        sibling.installed_artifact && typeof sibling.installed_artifact === "object"
          ? (sibling.installed_artifact as Record<string, unknown>)
          : record.installed_artifact && typeof record.installed_artifact === "object"
            ? (record.installed_artifact as Record<string, unknown>)
            : null;
      if (!installed) continue;
      const artifactSlug = String(installed.artifact_slug || "").trim();
      if (!artifactSlug) continue;
      return {
        artifactId: String(installed.artifact_id || "").trim(),
        artifactSlug,
        workspaceId: String(installed.workspace_id || "").trim(),
        workspaceSlug: String(installed.workspace_slug || "").trim(),
      };
    }
  }
  return null;
}

function extractApplicationDefinition(allJobs: AppJob[]): {
  appSlug: string;
  title: string;
  artifactSlug: string;
  entities: string[];
  reports: string[];
} | null {
  for (const job of allJobs) {
    const payloads = [job.output_json, job.input_json];
    for (const payload of payloads) {
      if (!payload || typeof payload !== "object") continue;
      const record = payload as Record<string, unknown>;
      const appSpec = record.app_spec && typeof record.app_spec === "object" ? (record.app_spec as Record<string, unknown>) : null;
      if (!appSpec) continue;
      const appSlug = String(appSpec.app_slug || "").trim();
      if (!appSlug) continue;
      const entities = Array.isArray(appSpec.entities) ? appSpec.entities.map((item) => String(item || "").trim()).filter(Boolean) : [];
      const reports = Array.isArray(appSpec.reports) ? appSpec.reports.map((item) => String(item || "").trim()).filter(Boolean) : [];
      const generatedArtifact =
        record.generated_artifact && typeof record.generated_artifact === "object"
          ? (record.generated_artifact as Record<string, unknown>)
          : {};
      const artifactSlug = String(generatedArtifact.artifact_slug || `app.${appSlug}`).trim() || `app.${appSlug}`;
      return {
        appSlug,
        title: String(appSpec.title || appSlug).trim() || appSlug,
        artifactSlug,
        entities,
        reports,
      };
    }
  }
  return null;
}

function formatTimestamp(value?: string | null): string {
  const raw = String(value || "").trim();
  if (!raw) return "—";
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return raw;
  return parsed.toLocaleString();
}

function draftWorkflowStateLabel(state?: string | null): string {
  switch (String(state || "").trim().toLowerCase()) {
    case "plan_ready":
      return "Plan Ready";
    case "submitted":
      return "Submitted";
    case "queued":
      return "Waiting in Queue";
    case "executing":
      return "Running";
    case "completed":
      return "Completed";
    case "failed":
      return "Failed";
    case "draft":
    default:
      return "Draft";
  }
}

function statusBadgeLabel(value: TimelineStepStatus): string {
  if (value === "complete") return "Done";
  if (value === "current") return "Current";
  if (value === "failed") return "Failed";
  return "Pending";
}

function overallStateLabel(value: DraftPageOverallState): string {
  switch (value) {
    case "building":
      return "Building";
    case "build_blocked":
      return "Build blocked";
    case "ready":
      return "Ready";
    case "needs_revision":
      return "Needs revision";
    case "unavailable":
      return "Unavailable";
    case "draft":
    default:
      return "Draft";
  }
}

function overallStateTone(value: DraftPageOverallState): "success" | "warn" | "danger" | "info" | "muted" {
  switch (value) {
    case "ready":
      return "success";
    case "build_blocked":
    case "needs_revision":
      return "danger";
    case "building":
      return "warn";
    case "unavailable":
      return "muted";
    case "draft":
    default:
      return "info";
  }
}

function actionTone(value: DraftActionCard["emphasis"], available: boolean): string {
  if (!available) return "muted";
  return value === "primary" ? "success" : "info";
}

function actionIcon(actionId: DraftActionId) {
  switch (actionId) {
    case "review_failure":
      return <AlertTriangle size={18} />;
    case "retry_validation":
      return <RefreshCw size={18} />;
    case "view_build_jobs":
      return <History size={18} />;
    case "edit_definition":
      return <FilePenLine size={18} />;
    case "open_generated_environment":
      return <ExternalLink size={18} />;
    case "open_application_workspace":
      return <Waypoints size={18} />;
    case "save_draft":
      return <Save size={18} />;
    case "submit_draft":
      return <Send size={18} />;
    default:
      return <History size={18} />;
  }
}

function matchesJobType(job: AppJob, tokens: string[]): boolean {
  const normalized = String(job.type || "").trim().toLowerCase();
  return tokens.some((token) => normalized.includes(token));
}

function latestMatchingJob(jobs: AppJob[], predicate: (job: AppJob) => boolean): AppJob | null {
  const matches = jobs.filter(predicate);
  return matches.length ? matches[matches.length - 1] : null;
}

function deriveDraftPageViewModel(args: {
  draft: AppIntentDraft | null;
  draftStatus: DraftStatusValue;
  workflow: DraftWorkflow | null;
  relatedJobs: AppJob[];
  executionNote: AppExecutionNote | null;
  applicationDefinition: {
    appSlug: string;
    title: string;
    artifactSlug: string;
    entities: string[];
    reports: string[];
  } | null;
  installedCapability: {
    appSlug: string;
    title: string;
    reports: string[];
  } | null;
  siblingInstalledArtifact: {
    artifactId: string;
    artifactSlug: string;
    workspaceId: string;
    workspaceSlug: string;
  } | null;
  deploymentUrls: {
    appUrl: string;
    siblingUiUrl: string;
    siblingApiUrl: string;
  };
  workspaceId: string;
  saving: boolean;
  submitting: boolean;
}): DraftPageViewModel {
  const {
    draft,
    draftStatus,
    workflow,
    relatedJobs,
    executionNote,
    applicationDefinition,
    installedCapability,
    siblingInstalledArtifact,
    deploymentUrls,
    workspaceId,
    saving,
    submitting,
  } = args;

  const latestFailedJob = latestMatchingJob(relatedJobs, (job) => normalizeJobStatus(job.status) === "failed");
  const runningJob = latestMatchingJob(relatedJobs, (job) => {
    const status = normalizeJobStatus(job.status);
    return status === "queued" || status === "running";
  });
  const smokeJob = latestMatchingJob(relatedJobs, (job) => matchesJobType(job, ["smoke", "verify", "validation"]));
  const smokeFailed = Boolean(smokeJob && normalizeJobStatus(smokeJob.status) === "failed");
  const smokeSucceeded = Boolean(smokeJob && normalizeJobStatus(smokeJob.status) === "succeeded");
  const appArtifactCreated = Boolean(applicationDefinition || installedCapability);
  const runtimeDeployed = Boolean(installedCapability || deploymentUrls.appUrl || deploymentUrls.siblingUiUrl);
  const generatedEnvironmentProvisioned = Boolean(siblingInstalledArtifact || deploymentUrls.siblingUiUrl);
  const workspaceRoutingConfirmed = Boolean(
    deploymentUrls.siblingUiUrl &&
      siblingInstalledArtifact?.workspaceId &&
      siblingInstalledArtifact.workspaceId !== workspaceId,
  );
  const workflowState = String(workflow?.state || "").trim().toLowerCase();
  const hasExecution = Boolean(workflow?.active_run_id || workflow?.last_run_status || relatedJobs.length);

  let overallState: DraftPageOverallState = "draft";
  if (!draft) {
    overallState = "unavailable";
  } else if (smokeFailed && runtimeDeployed) {
    overallState = "build_blocked";
  } else if (latestFailedJob) {
    overallState = appArtifactCreated || runtimeDeployed ? "build_blocked" : "needs_revision";
  } else if (
    runningJob ||
    ["submitted", "queued", "executing"].includes(workflowState) ||
    String(draft.status || draftStatus).trim().toLowerCase() === "submitted"
  ) {
    overallState = "building";
  } else if (smokeSucceeded || (workflowState === "completed" && appArtifactCreated && runtimeDeployed)) {
    overallState = "ready";
  }

  const failedStepLabel = smokeFailed
    ? "Smoke test failed after deploy"
    : latestFailedJob
      ? `${String(latestFailedJob.type || "Build step").replace(/_/g, " ")} failed`
      : overallState === "ready"
        ? "Verification completed"
        : overallState === "building"
          ? String(runningJob?.type || draftWorkflowStateLabel(workflowState)).replace(/_/g, " ")
          : "Draft not yet submitted";

  const succeeded: string[] = [];
  if (appArtifactCreated) succeeded.push("App spec generated");
  if (runtimeDeployed) succeeded.push("Local deploy succeeded");
  if (generatedEnvironmentProvisioned) succeeded.push("Sibling Xyn provisioned");

  const failed: string[] = [];
  if (smokeFailed) {
    failed.push("Smoke test failed");
  } else if (latestFailedJob) {
    failed.push(`${String(latestFailedJob.type || "Build step").replace(/_/g, " ")} failed`);
  }

  const failureSummaryBody =
    overallState === "build_blocked"
      ? "The application definition was generated and deployed, but verification failed afterward. Review the failure details and retry validation after addressing the issue."
      : overallState === "needs_revision"
        ? "The build could not complete successfully. Review the failure details and revise the app definition before retrying."
        : overallState === "ready"
          ? "The generated application passed its current build and verification steps."
          : overallState === "building"
            ? "The build is still running. Watch the active jobs until validation completes."
            : overallState === "draft"
              ? "This draft is editable and has not started a full build yet."
              : "This draft is not currently available for build or revision actions.";

  const buildTimeline: DraftTimelineStep[] = [
    {
      key: "definition",
      label: "App definition",
      detail: draft ? "Draft captured" : "No draft loaded",
      status: draft ? "complete" : "pending",
    },
    {
      key: "artifact",
      label: "App spec generated",
      detail: appArtifactCreated ? "Generated app artifact created" : "Waiting for generated app artifact",
      status: appArtifactCreated ? "complete" : overallState === "building" ? "current" : "pending",
    },
    {
      key: "deploy",
      label: "Runtime deployed",
      detail: runtimeDeployed ? "Local deploy succeeded" : "Runtime not deployed yet",
      status: runtimeDeployed ? "complete" : appArtifactCreated && overallState === "building" ? "current" : "pending",
    },
    {
      key: "environment",
      label: "Generated app environment",
      detail: generatedEnvironmentProvisioned ? "Sibling Xyn provisioned" : "Generated app environment not confirmed",
      status: generatedEnvironmentProvisioned ? "complete" : runtimeDeployed && overallState === "building" ? "current" : "pending",
    },
    {
      key: "verification",
      label: "Smoke test",
      detail: smokeFailed
        ? "Smoke test failed after deploy"
        : smokeSucceeded
          ? "Smoke test passed"
          : hasExecution
            ? "Verification pending"
            : "Verification not started",
      status: smokeFailed ? "failed" : smokeSucceeded ? "complete" : overallState === "building" ? "current" : "pending",
    },
  ];

  // Centralize which actions make sense so the page never shows contradictory
  // "continue/open" affordances without explaining why they are blocked.
  const recommendedActions: DraftActionCard[] = [
    {
      id: "review_failure",
      title: "Review failure summary",
      description: "Inspect the verification failure and the build notes for the blocked step.",
      badge: overallState === "build_blocked" ? "Recommended" : "Available",
      available: overallState === "build_blocked" || overallState === "needs_revision",
      disabledReason: "No build failure summary is available yet.",
      emphasis: "primary",
    },
    {
      id: "retry_validation",
      title: "Retry validation",
      description: "Queue another build attempt after reviewing the failure and making any needed changes.",
      badge: submitting ? "Submitting" : overallState === "build_blocked" ? "Next step" : "Available",
      available: Boolean(draft) && !submitting && overallState !== "building" && overallState !== "unavailable",
      disabledReason: overallState === "building" ? "A build is already in progress." : "This draft cannot be submitted right now.",
      emphasis: "primary",
    },
    {
      id: "view_build_jobs",
      title: "View build jobs",
      description: "Open the recorded build jobs for this draft and inspect step-by-step execution.",
      badge: relatedJobs.length ? "Available" : "Unavailable",
      available: relatedJobs.length > 0,
      disabledReason: "No build jobs have been recorded yet.",
      emphasis: "secondary",
    },
    {
      id: "edit_definition",
      title: "Edit app definition",
      description: "Review the prompt, title, and raw draft JSON for this application draft.",
      badge: saving ? "Saving" : "Available",
      available: Boolean(draft),
      disabledReason: "Draft details are not loaded yet.",
      emphasis: "secondary",
    },
    {
      id: "open_generated_environment",
      title: "Open generated app environment",
      description: "Open the deployed runtime environment that was provisioned for this generated application.",
      badge: deploymentUrls.siblingUiUrl || deploymentUrls.appUrl ? "Available" : "Unavailable",
      available: Boolean(deploymentUrls.siblingUiUrl || deploymentUrls.appUrl),
      disabledReason: "A generated app environment has not been provisioned yet.",
      emphasis: "secondary",
    },
    {
      id: "open_application_workspace",
      title: "Open application workspace",
      description: "Open the generated application workspace once a confirmed route is available.",
      badge: workspaceRoutingConfirmed ? "Available" : "Not confirmed",
      available: workspaceRoutingConfirmed,
      disabledReason: "Workspace routing for the generated application is not confirmed yet.",
      emphasis: "secondary",
    },
  ];

  if (overallState === "draft") {
    recommendedActions.push({
      id: "submit_draft",
      title: "Submit draft",
      description: "Start the application build workflow for this draft.",
      badge: submitting ? "Submitting" : "Primary",
      available: Boolean(draft) && !submitting,
      disabledReason: "Draft details are not loaded yet.",
      emphasis: "primary",
    });
  }

  if (overallState === "draft" || overallState === "needs_revision") {
    recommendedActions.push({
      id: "save_draft",
      title: "Save draft",
      description: "Persist the current title and raw draft JSON without starting a build.",
      badge: saving ? "Saving" : "Available",
      available: Boolean(draft) && !saving,
      disabledReason: "Draft details are not loaded yet.",
      emphasis: "secondary",
    });
  }

  return {
    overallState,
    overallLabel: overallStateLabel(overallState),
    currentStep: failedStepLabel,
    plainLanguageStatus: failureSummaryBody,
    lastUpdated: draft?.updated_at || workflow?.last_run_status || null,
    succeeded,
    failed,
    appArtifactLabel: appArtifactCreated ? "Created" : "Not created",
    runtimeLabel: runtimeDeployed ? "Deployed" : "Not deployed",
    workspaceRoutingLabel: workspaceRoutingConfirmed ? "Confirmed" : "Not confirmed",
    primaryNextStep:
      overallState === "build_blocked"
        ? "Review failure and retry validation"
        : overallState === "building"
          ? "Monitor the active build jobs"
          : overallState === "ready"
            ? "Open the generated app environment"
            : overallState === "draft"
              ? "Review the draft and submit the build"
              : overallState === "needs_revision"
                ? "Edit the app definition and submit again"
                : "Reload the draft details",
    failureSummaryTitle:
      overallState === "build_blocked"
        ? "Build failure summary"
        : overallState === "needs_revision"
          ? "Revision summary"
          : "Build summary",
    failureSummaryBody,
    buildTimeline,
    recommendedActions,
  };
}

export default function DraftDetailPage({
  workspaceId,
  workspaceName,
  workspaceColor,
  workspaceBarVariant = "default",
  draftId: explicitDraftId,
  onBack,
  onOpenJob,
  onOpenArtifacts,
  linkedJobId,
}: {
  workspaceId: string;
  workspaceName: string;
  workspaceColor?: string;
  workspaceBarVariant?: "default" | "compact";
  draftId?: string;
  onBack?: () => void;
  onOpenJob?: (jobId: string) => void;
  onOpenArtifacts?: (kind?: string) => void;
  linkedJobId?: string | null;
}) {
  const params = useParams();
  const navigate = useNavigate();
  const draftId = String(explicitDraftId || params.draftId || "").trim();
  const [draft, setDraft] = useState<AppIntentDraft | null>(null);
  const [title, setTitle] = useState("");
  const [status, setStatus] = useState<DraftStatusValue>("draft");
  const [jsonText, setJsonText] = useState("{}");
  const [saving, setSaving] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [editorExpanded, setEditorExpanded] = useState(false);
  const [metadataExpanded, setMetadataExpanded] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [latestJobId, setLatestJobId] = useState<string>(String(linkedJobId || "").trim());
  const [relatedJobs, setRelatedJobs] = useState<AppJob[]>([]);
  const [workflow, setWorkflow] = useState<DraftWorkflow | null>(null);
  const [workflowLoading, setWorkflowLoading] = useState(false);
  const [executionNotes, setExecutionNotes] = useState<AppExecutionNote[]>([]);
  const [executionNotesLoading, setExecutionNotesLoading] = useState(false);
  const [executionNotesError, setExecutionNotesError] = useState<string | null>(null);
  const { push } = useNotifications();
  const failureSummaryRef = useRef<HTMLElement | null>(null);
  const editorRef = useRef<HTMLDetailsElement | null>(null);
  const draftDescriptor = useMemo(
    () => getAppDraftViewDescriptor({ id: draftId, title: draft?.title || title }, workspaceId),
    [draft?.title, draftId, title, workspaceId]
  );
  const rawPrompt = useMemo(() => {
    if (!draft?.content_json || typeof draft.content_json !== "object") return "";
    return String((draft.content_json as Record<string, unknown>).raw_prompt || "");
  }, [draft?.content_json]);

  const load = useCallback(async () => {
    if (!workspaceId || !draftId) return;
    try {
      setError(null);
      const payload = await getAppIntentDraft(draftId, workspaceId);
      setDraft(payload);
      setTitle(payload.title || "");
      const nextStatus = String(payload.status || "draft").toLowerCase();
      setStatus(nextStatus === "ready" || nextStatus === "submitted" || nextStatus === "archived" ? nextStatus : "draft");
      setJsonText(prettyJson(payload.content_json || {}));
    } catch (err) {
      setError((err as Error).message);
    }
  }, [draftId, workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    setLatestJobId(String(linkedJobId || "").trim());
  }, [linkedJobId]);

  const loadWorkflow = useCallback(async () => {
    if (!workspaceId || !draftId) {
      setWorkflow(null);
      return;
    }
    try {
      setWorkflowLoading(true);
      const payload = await getDraftWorkflow(draftId, workspaceId);
      setWorkflow(payload);
    } catch (err) {
      setWorkflow(null);
      setError((err as Error).message);
    } finally {
      setWorkflowLoading(false);
    }
  }, [draftId, workspaceId]);

  useEffect(() => {
    void loadWorkflow();
  }, [loadWorkflow]);

  useEffect(() => {
    if (!draftId || !workspaceId || !workflow?.state) return;
    void emitCapabilityEvent({
      eventType: "draft_state_changed",
      entityId: draftId,
      workspaceId,
    });
  }, [draftId, workspaceId, workflow?.state]);

  const loadJobs = useCallback(async () => {
    if (!workspaceId || !draftId) {
      setRelatedJobs([]);
      return;
    }
    try {
      const payload = await listAppJobs(workspaceId);
      const related = collectRelatedJobs(payload, draftId, latestJobId);
      setRelatedJobs(related);
      if (!latestJobId && related.length) {
        setLatestJobId(related[0].id);
      }
    } catch (err) {
      setError((err as Error).message);
    }
  }, [draftId, latestJobId, workspaceId]);

  useEffect(() => {
    void loadJobs();
  }, [loadJobs]);

  const buildSelectors = useMemo(() => extractBuildSelectors(relatedJobs), [relatedJobs]);

  const loadExecutionNotes = useCallback(async () => {
    if (!workspaceId) {
      setExecutionNotes([]);
      setExecutionNotesError(null);
      return;
    }
    const hasSelectors =
      buildSelectors.noteIds.length > 0 ||
      buildSelectors.jobIds.length > 0 ||
      buildSelectors.relatedArtifactIds.length > 0;
    if (!hasSelectors) {
      setExecutionNotes([]);
      setExecutionNotesError(null);
      return;
    }
    try {
      setExecutionNotesLoading(true);
      setExecutionNotesError(null);
      const payload = await listAppExecutionNotes(workspaceId, buildSelectors);
      setExecutionNotes(payload);
    } catch (err) {
      setExecutionNotes([]);
      setExecutionNotesError((err as Error).message);
    } finally {
      setExecutionNotesLoading(false);
    }
  }, [buildSelectors, workspaceId]);

  useEffect(() => {
    void loadExecutionNotes();
  }, [loadExecutionNotes]);

  const executionNote = useMemo(() => (executionNotes.length ? executionNotes[0] : null), [executionNotes]);

  const deploymentUrls = useMemo(() => {
    let appUrl = "";
    let siblingUiUrl = "";
    let siblingApiUrl = "";
    for (const job of relatedJobs) {
      const output = job.output_json && typeof job.output_json === "object" ? job.output_json : {};
      if (!appUrl && typeof output.app_url === "string") appUrl = output.app_url;
      if (!siblingUiUrl && typeof output.ui_url === "string") siblingUiUrl = output.ui_url;
      if (!siblingApiUrl && typeof output.api_url === "string") siblingApiUrl = output.api_url;
      const sibling = output.sibling_xyn && typeof output.sibling_xyn === "object" ? output.sibling_xyn as Record<string, unknown> : {};
      if (!siblingUiUrl && typeof sibling.ui_url === "string") siblingUiUrl = sibling.ui_url;
      if (!siblingApiUrl && typeof sibling.api_url === "string") siblingApiUrl = sibling.api_url;
    }
    return { appUrl, siblingUiUrl, siblingApiUrl };
  }, [relatedJobs]);
  const installedCapability = useMemo(() => extractInstalledCapability(relatedJobs), [relatedJobs]);
  const siblingInstalledArtifact = useMemo(() => extractSiblingInstalledArtifact(relatedJobs), [relatedJobs]);
  const applicationDefinition = useMemo(() => extractApplicationDefinition(relatedJobs), [relatedJobs]);
  const viewModel = useMemo(
    () =>
      deriveDraftPageViewModel({
        draft,
        draftStatus: status,
        workflow,
        relatedJobs,
        executionNote,
        applicationDefinition,
        installedCapability,
        siblingInstalledArtifact,
        deploymentUrls,
        workspaceId,
        saving,
        submitting,
      }),
    [
      applicationDefinition,
      deploymentUrls,
      draft,
      executionNote,
      installedCapability,
      relatedJobs,
      saving,
      siblingInstalledArtifact,
      status,
      submitting,
      workflow,
      workspaceId,
    ],
  );

  const latestFailedJob = useMemo(
    () => latestMatchingJob(relatedJobs, (job) => normalizeJobStatus(job.status) === "failed"),
    [relatedJobs],
  );
  const latestJob = relatedJobs.length ? relatedJobs[relatedJobs.length - 1] : null;

  const openGeneratedEnvironment = useCallback(() => {
    const target = deploymentUrls.siblingUiUrl || deploymentUrls.appUrl;
    if (!target) return;
    window.open(target, "_blank", "noopener,noreferrer");
  }, [deploymentUrls.appUrl, deploymentUrls.siblingUiUrl]);

  const reviewFailureSummary = useCallback(() => {
    setMessage(null);
    failureSummaryRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  const openEditor = useCallback(() => {
    setEditorExpanded(true);
    requestAnimationFrame(() => {
      editorRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }, []);

  const handleAction = useCallback(
    (actionId: DraftActionId) => {
      if (actionId === "review_failure") {
        reviewFailureSummary();
        return;
      }
      if (actionId === "retry_validation") {
        void submit();
        return;
      }
      if (actionId === "view_build_jobs") {
        if (!latestJobId) return;
        if (onOpenJob) onOpenJob(latestJobId);
        else navigate(toWorkspacePath(workspaceId, `jobs/${latestJobId}`));
        return;
      }
      if (actionId === "edit_definition") {
        openEditor();
        return;
      }
      if (actionId === "open_generated_environment") {
        openGeneratedEnvironment();
        return;
      }
      if (actionId === "open_application_workspace") {
        setMessage("Generated application workspace routing is not confirmed yet for this build.");
        return;
      }
      if (actionId === "save_draft") {
        void save();
        return;
      }
      if (actionId === "submit_draft") {
        void submit();
      }
    },
    [latestJobId, navigate, onOpenJob, openEditor, openGeneratedEnvironment, reviewFailureSummary, workspaceId],
  );

  useEffect(() => {
    if (!relatedJobs.length) return;
    if (viewModel.overallState !== "ready" && viewModel.overallState !== "build_blocked" && viewModel.overallState !== "needs_revision") return;
    push({
      level: viewModel.overallState === "ready" ? "success" : "error",
      title: viewModel.overallState === "ready" ? "App build completed" : "App build blocked",
      message:
        viewModel.overallState === "ready"
          ? draft?.title || "Draft build succeeded."
          : (latestFailedJob?.logs_text || viewModel.failureSummaryBody),
      entityType: "run",
      entityId: latestJobId || draftId,
      status: viewModel.overallState === "ready" ? "succeeded" : "failed",
      href: deploymentUrls.siblingUiUrl || deploymentUrls.appUrl || undefined,
      ctaLabel: deploymentUrls.siblingUiUrl || deploymentUrls.appUrl ? "Open" : undefined,
      dedupeKey: `app-build:${draftId}:${viewModel.overallState}`,
    });
  }, [
    deploymentUrls.appUrl,
    deploymentUrls.siblingUiUrl,
    draft?.title,
    draftId,
    latestFailedJob?.logs_text,
    latestJobId,
    push,
    relatedJobs.length,
    viewModel.failureSummaryBody,
    viewModel.overallState,
  ]);

  useEffect(() => {
    if (viewModel.overallState !== "building") return;
    const interval = window.setInterval(() => {
      void loadJobs();
      void loadWorkflow();
    }, 4000);
    return () => window.clearInterval(interval);
  }, [loadJobs, loadWorkflow, viewModel.overallState]);

  const save = async () => {
    if (!workspaceId || !draftId) return;
    try {
      setSaving(true);
      setError(null);
      setMessage(null);
      const contentJson = parseJsonText(jsonText);
      const payload = await updateAppIntentDraft(draftId, workspaceId, {
        title: title.trim() || "Untitled Draft",
        status,
        content_json: contentJson,
      });
      setDraft(payload);
      setJsonText(prettyJson(payload.content_json || {}));
      setMessage("Draft saved.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const submit = async () => {
    if (!workspaceId || !draftId) return;
    try {
      setSubmitting(true);
      setError(null);
      setMessage(null);
      const payload = await submitAppIntentDraft(draftId, workspaceId);
      setDraft(payload.draft);
      setStatus("submitted");
      setLatestJobId(String(payload.job_id || ""));
      void loadWorkflow();
      setMessage(`Draft submitted. Job queued: ${payload.job_id}`);
      if (!onOpenJob) {
        navigate(toWorkspacePath(workspaceId, `jobs/${payload.job_id}`));
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <WorkspaceContextBar workspaceName={workspaceName} workspaceColor={workspaceColor} variant={workspaceBarVariant} />
      <div className="page-header">
        <div>
          <h2>Application Draft</h2>
          <p className="muted">Review the current build state, understand what succeeded, and take the next meaningful action.</p>
        </div>
        <div className="inline-actions">
          <button className="ghost" onClick={() => (onBack ? onBack() : navigate(toWorkspacePath(workspaceId, "drafts")))}>
            {onBack ? "Back" : "Back to Drafts"}
          </button>
          <button className="ghost" type="button" onClick={openEditor} disabled={!draft}>
            Edit app definition
          </button>
          {latestJobId ? (
            <button className="ghost" onClick={() => handleAction("view_build_jobs")}>
              View build jobs
            </button>
          ) : null}
          {(deploymentUrls.siblingUiUrl || deploymentUrls.appUrl) ? (
            <button className="ghost" type="button" onClick={openGeneratedEnvironment}>
              Open generated app environment
            </button>
          ) : null}
          <button className="primary" onClick={() => handleAction(viewModel.overallState === "draft" ? "submit_draft" : "retry_validation")} disabled={submitting || !workspaceId}>
            {submitting ? "Submitting..." : viewModel.overallState === "draft" ? "Submit draft" : "Retry validation"}
          </button>
        </div>
      </div>
      {message && <InlineMessage tone="info" title="Draft" body={message} />}
      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      <section className="card app-draft-hero-card">
        <div className="card-header">
          <div>
            <h3>{draftDescriptor.title || draft?.title || "Application Draft"}</h3>
            <p className="muted small">{viewModel.currentStep}</p>
          </div>
          <span className={`chip app-draft-state-chip ${overallStateTone(viewModel.overallState)}`}>{viewModel.overallLabel}</span>
        </div>
        <div className="detail-grid" style={{ marginTop: 12 }}>
          <div>
            <strong>Current step</strong>
            <p className="muted small">{viewModel.currentStep}</p>
          </div>
          <div>
            <strong>Last updated</strong>
            <p className="muted small">{formatTimestamp(draft?.updated_at || latestJob?.updated_at || latestJob?.created_at)}</p>
          </div>
          <div>
            <strong>App artifact</strong>
            <p className="muted small">{viewModel.appArtifactLabel}</p>
          </div>
          <div>
            <strong>Runtime</strong>
            <p className="muted small">{viewModel.runtimeLabel}</p>
          </div>
          <div>
            <strong>Workspace routing</strong>
            <p className="muted small">{viewModel.workspaceRoutingLabel}</p>
          </div>
          <div>
            <strong>Primary next step</strong>
            <p className="muted small">{viewModel.primaryNextStep}</p>
          </div>
          <div className="span-full">
            <strong>Status explanation</strong>
            <p className="muted small">{viewModel.plainLanguageStatus}</p>
          </div>
          <div>
            <strong>What succeeded</strong>
            {viewModel.succeeded.length ? (
              <ul className="muted small app-draft-summary-list">
                {viewModel.succeeded.map((item) => <li key={item}>{item}</li>)}
              </ul>
            ) : (
              <p className="muted small">No completed build steps yet.</p>
            )}
          </div>
          <div>
            <strong>What failed</strong>
            {viewModel.failed.length ? (
              <ul className="muted small app-draft-summary-list">
                {viewModel.failed.map((item) => <li key={item}>{item}</li>)}
              </ul>
            ) : (
              <p className="muted small">No failed build steps recorded.</p>
            )}
          </div>
        </div>
      </section>

      <div className="app-draft-layout">
        <div className="app-draft-main-column">
          <section className="card">
            <div className="card-header">
              <h3>Suggested Actions</h3>
            </div>
            <div className="app-draft-action-list">
              {viewModel.recommendedActions.map((action) => (
                <ActionRowCard
                  key={action.id}
                  title={action.title}
                  description={action.description}
                  badge={<span className={`chip ${actionTone(action.emphasis, action.available)}`}>{action.badge}</span>}
                  icon={actionIcon(action.id)}
                  disabled={!action.available}
                  disabledReason={action.disabledReason}
                  onClick={action.available ? () => handleAction(action.id) : undefined}
                />
              ))}
            </div>
          </section>

          <section className="card">
            <div className="card-header">
              <h3>Build progress</h3>
            </div>
            <div className="app-draft-timeline">
              {viewModel.buildTimeline.map((step) => (
                <div key={step.key} className={`app-draft-timeline-step ${step.status}`}>
                  <div className="app-draft-timeline-marker" />
                  <div>
                    <div className="app-draft-timeline-heading">
                      <strong>{step.label}</strong>
                      <span className={`chip ${actionTone(step.status === "current" ? "primary" : "secondary", step.status !== "pending")}`}>
                        {statusBadgeLabel(step.status)}
                      </span>
                    </div>
                    <p className="muted small">{step.detail}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="card" ref={failureSummaryRef}>
            <div className="card-header">
              <h3>{viewModel.failureSummaryTitle}</h3>
              <span className={`chip ${overallStateTone(viewModel.overallState)}`}>{viewModel.currentStep}</span>
            </div>
            {executionNotesLoading || workflowLoading ? <p className="muted small">Loading build summary…</p> : null}
            {executionNotesError ? <InlineMessage tone="error" title="Diagnostics unavailable" body={executionNotesError} /> : null}
            <p className="muted small">{viewModel.failureSummaryBody}</p>
            <div className="detail-grid" style={{ marginTop: 12 }}>
              <div>
                <strong>Failure stage</strong>
                <p className="muted small">{viewModel.currentStep}</p>
              </div>
              <div>
                <strong>Latest failed step</strong>
                <p className="muted small">{latestFailedJob ? String(latestFailedJob.type || "").replace(/_/g, " ") : "—"}</p>
              </div>
              <div>
                <strong>Recorded note</strong>
                <p className="muted small">{executionNote?.status || "No execution note linked"}</p>
              </div>
              <div className="span-full">
                <strong>Plain-language explanation</strong>
                <p className="muted small">{viewModel.plainLanguageStatus}</p>
              </div>
              {executionNote?.findings?.length ? (
                <div>
                  <strong>Observed issues</strong>
                  <ul className="muted small app-draft-summary-list">
                    {executionNote.findings.slice(0, 4).map((item, index) => <li key={`finding-${index}`}>{item}</li>)}
                  </ul>
                </div>
              ) : null}
              {executionNote?.validation_summary?.length ? (
                <div>
                  <strong>Validation summary</strong>
                  <ul className="muted small app-draft-summary-list">
                    {executionNote.validation_summary.slice(0, 4).map((item, index) => <li key={`validation-${index}`}>{item}</li>)}
                  </ul>
                </div>
              ) : null}
              {executionNote?.proposed_fix ? (
                <div className="span-full">
                  <strong>Suggested next correction</strong>
                  <p className="muted small">{executionNote.proposed_fix}</p>
                </div>
              ) : null}
            </div>
          </section>
        </div>

        <div className="app-draft-side-column">
          <section className="card">
            <div className="card-header">
              <h3>Current state</h3>
            </div>
            <div className="detail-grid" style={{ marginTop: 12 }}>
              <div>
                <strong>Draft stage</strong>
                <p className="muted small">{workflowLoading ? "Loading..." : draftWorkflowStateLabel(workflow?.state)}</p>
              </div>
              <div>
                <strong>Execution run</strong>
                <p className="muted small">{workflow?.active_run_id || "Not started yet"}</p>
              </div>
              <div>
                <strong>Build jobs</strong>
                <p className="muted small">{relatedJobs.length || 0}</p>
              </div>
              <div>
                <strong>Plan state</strong>
                <p className="muted small">{workflow?.plan_available ? "Available" : "Not available yet"}</p>
              </div>
              <div>
                <strong>Generated app</strong>
                <p className="muted small">{installedCapability?.title || applicationDefinition?.title || "Not created yet"}</p>
              </div>
              <div>
                <strong>Generated artifact</strong>
                <p className="muted small">{applicationDefinition?.artifactSlug || siblingInstalledArtifact?.artifactSlug || "Not recorded"}</p>
              </div>
            </div>
          </section>

          <section className="card">
            <div className="card-header">
              <h3>Technical details</h3>
            </div>
            <div className="detail-grid" style={{ marginTop: 12 }}>
              <div>
                <strong>Coordination thread</strong>
                <p className="muted small">{workflow?.thread_id || "Not linked yet"}</p>
              </div>
              <div>
                <strong>Execution status</strong>
                <p className="muted small">{workflow?.last_run_status || "—"}</p>
              </div>
              <div>
                <strong>Generated reports</strong>
                <p className="muted small">{installedCapability?.reports.join(", ") || applicationDefinition?.reports.join(", ") || "None recorded"}</p>
              </div>
              <div>
                <strong>Sibling workspace</strong>
                <p className="muted small">{siblingInstalledArtifact?.workspaceSlug || siblingInstalledArtifact?.workspaceId || "Not recorded"}</p>
              </div>
              <div className="span-full">
                <strong>Originating prompt</strong>
                <p className="muted small">{rawPrompt || "Prompt unavailable."}</p>
              </div>
              <div className="span-full">
                <strong>Application shape</strong>
                <p className="muted small">{applicationDefinition?.entities.join(", ") || "No entities recorded"}</p>
              </div>
            </div>
            {onOpenArtifacts ? (
              <div className="inline-actions" style={{ marginTop: 12 }}>
                <button className="ghost" type="button" onClick={() => onOpenArtifacts("app_spec")}>
                  View application artifacts
                </button>
              </div>
            ) : null}
          </section>

          <details className="card" open={editorExpanded} ref={editorRef} onToggle={(event) => setEditorExpanded((event.currentTarget as HTMLDetailsElement).open)}>
            <summary><strong>Edit app definition</strong></summary>
            <div className="form-grid" style={{ marginTop: 12 }}>
              <label>
                Title
                <input className="input" value={title} onChange={(event) => setTitle(event.target.value)} />
              </label>
              <label>
                Status
                <select className="input" value={status} onChange={(event) => setStatus(event.target.value as DraftStatusValue)}>
                  <option value="draft">draft</option>
                  <option value="ready">ready</option>
                  <option value="submitted">submitted</option>
                  <option value="archived">archived</option>
                </select>
              </label>
              <label className="span-full">
                Raw Prompt
                <textarea className="input" rows={4} value={rawPrompt} readOnly />
              </label>
              <label className="span-full">
                Draft JSON
                <textarea className="input" rows={18} value={jsonText} onChange={(event) => setJsonText(event.target.value)} />
              </label>
            </div>
            <div className="inline-actions" style={{ marginTop: 12 }}>
              <button className="ghost" onClick={() => void save()} disabled={saving || !workspaceId}>
                {saving ? "Saving..." : "Save draft"}
              </button>
              <button className="primary" onClick={() => void submit()} disabled={submitting || !workspaceId}>
                {submitting ? "Submitting..." : "Submit draft"}
              </button>
            </div>
          </details>

          <details className="card" open={metadataExpanded} onToggle={(event) => setMetadataExpanded((event.currentTarget as HTMLDetailsElement).open)}>
            <summary><strong>Technical metadata</strong></summary>
            <div className="detail-grid" style={{ marginTop: 12 }}>
              <div>
                <strong>Draft ID</strong>
                <p className="muted small">{draft?.id || draftId}</p>
              </div>
              <div>
                <strong>Workspace ID</strong>
                <p className="muted small">{draft?.workspace_id || workspaceId}</p>
              </div>
              <div>
                <strong>Created By</strong>
                <p className="muted small">{draft?.created_by || "user"}</p>
              </div>
              <div>
                <strong>Updated</strong>
                <p className="muted small">{draft?.updated_at || "—"}</p>
              </div>
            </div>
          </details>

          <details className="card">
            <summary><strong>Diagnostics and raw logs</strong></summary>
            {executionNote ? (
              <>
                <div className="detail-grid" style={{ marginTop: 12 }}>
                  <div>
                    <strong>Recorded</strong>
                    <p className="muted small">{formatTimestamp(executionNote.updated_at || executionNote.timestamp)}</p>
                  </div>
                  <div>
                    <strong>Match reason</strong>
                    <p className="muted small">{executionNote.match_reason.replace(/_/g, " ")}</p>
                  </div>
                  <div className="span-full">
                    <strong>Request</strong>
                    <p className="muted small">{executionNote.prompt_or_request || "—"}</p>
                  </div>
                </div>
                {executionNote.debt_recorded?.length ? (
                  <>
                    <strong>Recorded debt</strong>
                    <ul className="muted small app-draft-summary-list">
                      {executionNote.debt_recorded.map((item, index) => <li key={`debt-${index}`}>{item}</li>)}
                    </ul>
                  </>
                ) : null}
                <pre className="code-block" style={{ marginTop: 12 }}>{prettyJson(executionNote)}</pre>
              </>
            ) : (
              <p className="muted small" style={{ marginTop: 12 }}>No linked execution note is available for this draft yet.</p>
            )}
            {latestFailedJob?.logs_text ? (
              <>
                <strong>Latest failed job logs</strong>
                <pre className="code-block" style={{ marginTop: 12 }}>{latestFailedJob.logs_text}</pre>
              </>
            ) : null}
            <strong>Raw draft JSON</strong>
            <pre className="code-block" style={{ marginTop: 12 }}>{jsonText}</pre>
          </details>
        </div>
      </div>
    </>
  );
}
