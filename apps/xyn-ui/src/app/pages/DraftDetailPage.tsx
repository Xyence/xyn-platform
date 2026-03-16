import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import Tabs from "../components/ui/Tabs";
import { getAppIntentDraft, getDraftWorkflow, listAppExecutionNotes, listAppJobs, submitAppIntentDraft, updateAppIntentDraft } from "../../api/xyn";
import type { AppExecutionNote, AppIntentDraft, AppJob, DraftWorkflow } from "../../api/types";
import WorkspaceContextBar from "../components/common/WorkspaceContextBar";
import { toWorkspacePath } from "../routing/workspaceRouting";
import { useNotifications } from "../state/notificationsStore";
import { useXynConsole } from "../state/xynConsoleStore";
import { getAppDraftViewDescriptor } from "../drafts/appDraftView";

type DraftDetailTab = "editor" | "meta";
type DraftStatusValue = "draft" | "ready" | "submitted" | "archived";

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
  const [activeTab, setActiveTab] = useState<DraftDetailTab>("editor");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [latestJobId, setLatestJobId] = useState<string>(String(linkedJobId || "").trim());
  const [relatedJobs, setRelatedJobs] = useState<AppJob[]>([]);
  const [workflow, setWorkflow] = useState<DraftWorkflow | null>(null);
  const [workflowLoading, setWorkflowLoading] = useState(false);
  const [executionNotes, setExecutionNotes] = useState<AppExecutionNote[]>([]);
  const [executionNotesLoading, setExecutionNotesLoading] = useState(false);
  const [executionNotesError, setExecutionNotesError] = useState<string | null>(null);
  const [executionTraceExpanded, setExecutionTraceExpanded] = useState(false);
  const { push } = useNotifications();
  const { setInputText, setOpen, setLastArtifactHint, clearContext } = useXynConsole();
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

  const buildStatus = useMemo(() => {
    if (relatedJobs.some((job) => normalizeJobStatus(job.status) === "failed")) return "failed";
    if (relatedJobs.some((job) => job.type === "smoke_test" && normalizeJobStatus(job.status) === "succeeded")) return "succeeded";
    if (relatedJobs.some((job) => {
      const status = normalizeJobStatus(job.status);
      return status === "queued" || status === "running";
    })) {
      return "running";
    }
    if (String(draft?.status || status).toLowerCase() === "submitted") return "running";
    return "draft";
  }, [draft?.status, relatedJobs, status]);

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
  const revisionUrl = useMemo(() => {
    const artifactSlug = siblingInstalledArtifact?.artifactSlug || applicationDefinition?.artifactSlug || "";
    const artifactTitle = applicationDefinition?.title || installedCapability?.title || draft?.title || "Generated application";
    const siblingWorkspaceId = String(siblingInstalledArtifact?.workspaceId || "").trim();
    if (!deploymentUrls.siblingUiUrl || !siblingWorkspaceId) return "";
    const workbenchPath = new URL(`/w/${encodeURIComponent(siblingWorkspaceId)}/workbench`, deploymentUrls.siblingUiUrl);
    workbenchPath.searchParams.set("revise", "1");
    workbenchPath.searchParams.set("prompt", "Add ");
    if (artifactSlug) workbenchPath.searchParams.set("artifact_slug", artifactSlug);
    if (artifactTitle) workbenchPath.searchParams.set("artifact_title", artifactTitle);
    const authLogin = new URL("/auth/login", deploymentUrls.siblingUiUrl);
    authLogin.searchParams.set("appId", "xyn-ui");
    authLogin.searchParams.set("returnTo", `${workbenchPath.pathname}${workbenchPath.search}`);
    return authLogin.toString();
  }, [
    applicationDefinition?.artifactSlug,
    applicationDefinition?.title,
    deploymentUrls.siblingUiUrl,
    draft?.title,
    installedCapability?.title,
    siblingInstalledArtifact?.artifactSlug,
    siblingInstalledArtifact?.workspaceId,
  ]);

  const openRevisionPrompt = useCallback(() => {
    const artifactSlug = siblingInstalledArtifact?.artifactSlug || applicationDefinition?.artifactSlug || "";
    const artifactTitle = applicationDefinition?.title || installedCapability?.title || draft?.title || "Generated application";
    if (revisionUrl) {
      window.location.assign(revisionUrl);
      return;
    }
    clearContext();
    setLastArtifactHint(
      artifactSlug
        ? {
            artifact_id: siblingInstalledArtifact?.artifactId || artifactSlug,
            artifact_type: "GeneratedApplication",
            artifact_state: "installed",
            title: artifactTitle,
            route: toWorkspacePath(workspaceId, "workbench"),
          }
        : null,
    );
    setInputText("Add ");
    setOpen(true);
    setMessage(`Revision prompt scoped to ${artifactTitle}${artifactSlug ? ` (${artifactSlug})` : ""}.`);
  }, [
    applicationDefinition?.artifactSlug,
    applicationDefinition?.title,
    clearContext,
    draft?.title,
    installedCapability?.title,
    revisionUrl,
    setInputText,
    setLastArtifactHint,
    setOpen,
    siblingInstalledArtifact?.artifactId,
    siblingInstalledArtifact?.artifactSlug,
    workspaceId,
  ]);

  const continueInWorkbench = useCallback(() => {
    clearContext();
    if (siblingInstalledArtifact?.artifactSlug || applicationDefinition?.artifactSlug) {
      const artifactSlug = siblingInstalledArtifact?.artifactSlug || applicationDefinition?.artifactSlug || "";
      const artifactTitle = applicationDefinition?.title || installedCapability?.title || draft?.title || title || "Generated application";
      setLastArtifactHint(
        artifactSlug
          ? {
              artifact_id: siblingInstalledArtifact?.artifactId || artifactSlug,
              artifact_type: "GeneratedApplication",
              artifact_state: "installed",
              title: artifactTitle,
              route: toWorkspacePath(workspaceId, "workbench"),
            }
          : null,
      );
      setInputText("Add ");
    } else {
      setLastArtifactHint(null);
      setInputText(rawPrompt || `Continue application design for ${draft?.title || title || "this draft"}`);
    }
    setOpen(true);
    navigate(toWorkspacePath(workspaceId, "workbench"));
  }, [
    applicationDefinition?.artifactSlug,
    applicationDefinition?.title,
    clearContext,
    draft?.title,
    installedCapability?.title,
    navigate,
    rawPrompt,
    setInputText,
    setLastArtifactHint,
    setOpen,
    siblingInstalledArtifact?.artifactId,
    siblingInstalledArtifact?.artifactSlug,
    title,
    workspaceId,
  ]);

  useEffect(() => {
    if (!relatedJobs.length) return;
    if (buildStatus !== "succeeded" && buildStatus !== "failed") return;
    push({
      level: buildStatus === "succeeded" ? "success" : "error",
      title: buildStatus === "succeeded" ? "App build completed" : "App build failed",
      message:
        buildStatus === "succeeded"
          ? draft?.title || "Draft build succeeded."
          : (relatedJobs.find((job) => normalizeJobStatus(job.status) === "failed")?.logs_text || "Review build pipeline logs."),
      entityType: "run",
      entityId: latestJobId || draftId,
      status: buildStatus,
      href: deploymentUrls.siblingUiUrl || deploymentUrls.appUrl || undefined,
      ctaLabel: deploymentUrls.siblingUiUrl || deploymentUrls.appUrl ? "Open" : undefined,
      dedupeKey: `app-build:${draftId}:${buildStatus}`,
    });
  }, [buildStatus, deploymentUrls.appUrl, deploymentUrls.siblingUiUrl, draft?.title, draftId, latestJobId, push, relatedJobs]);

  useEffect(() => {
    if (buildStatus !== "running") return;
    const interval = window.setInterval(() => {
      void loadJobs();
      void loadWorkflow();
    }, 4000);
    return () => window.clearInterval(interval);
  }, [buildStatus, loadJobs, loadWorkflow]);

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
          <p className="muted">Review the application intent, track progress, and continue designing the application in the workbench.</p>
        </div>
        <div className="inline-actions">
          <button className="ghost" onClick={() => (onBack ? onBack() : navigate(toWorkspacePath(workspaceId, "drafts")))}>
            {onBack ? "Back" : "Back to Drafts"}
          </button>
          <button className="ghost" type="button" onClick={continueInWorkbench} disabled={!workspaceId}>
            Continue in Workbench
          </button>
          {latestJobId ? (
            <button className="ghost" onClick={() => (onOpenJob ? onOpenJob(latestJobId) : navigate(toWorkspacePath(workspaceId, `jobs/${latestJobId}`)))}>
              View Execution Status
            </button>
          ) : null}
          <button className="ghost" onClick={() => setMessage("Regenerate is not implemented yet.")}>
            Regenerate
          </button>
          <button className="ghost" onClick={() => void save()} disabled={saving || !workspaceId}>
            {saving ? "Saving..." : "Save"}
          </button>
          <button className="primary" onClick={() => void submit()} disabled={submitting || !workspaceId}>
            {submitting ? "Submitting..." : "Submit"}
          </button>
        </div>
      </div>
      {message && <InlineMessage tone="info" title="Draft" body={message} />}
      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      <InlineMessage
        tone="info"
        title="Application workspace"
        body={`This draft is routed through the ${draftDescriptor.editorKey.replace(/_/g, " ")} shell. Use Continue in Workbench to continue application design with the composer and related workbench tools.`}
      />

      <section className="card">
        <div className="card-header">
          <h3>{draftDescriptor.title || "Application Draft"}</h3>
          <span className="chip">{draft?.status || status || "draft"}</span>
        </div>
        <div className="detail-grid" style={{ marginTop: 12, marginBottom: 12 }}>
          <div>
            <strong>Application stage</strong>
            <p className="muted small">{workflowLoading ? "Loading..." : draftWorkflowStateLabel(workflow?.state)}</p>
          </div>
          <div>
            <strong>Coordination thread</strong>
            <p className="muted small">{workflow?.thread_id || "Not linked yet"}</p>
          </div>
          <div>
            <strong>Execution run</strong>
            <p className="muted small">{workflow?.active_run_id || "Not started yet"}</p>
          </div>
          <div>
            <strong>Execution status</strong>
            <p className="muted small">{workflow?.last_run_status || "—"}</p>
          </div>
          <div>
            <strong>Build readiness</strong>
            <p className="muted small">{buildStatus}</p>
          </div>
          <div>
            <strong>Tracked jobs</strong>
            <p className="muted small">{relatedJobs.length || 0}</p>
          </div>
          <div>
            <strong>Plan state</strong>
            <p className="muted small">{workflow?.plan_available ? "Available" : "Not available yet"}</p>
          </div>
          <div>
            <strong>Generated capability</strong>
            {installedCapability ? (
              <>
                <p className="muted small">{installedCapability.title}</p>
                <p className="muted small">{installedCapability.appSlug}</p>
              </>
            ) : (
              <p className="muted small">AppSpec not available yet</p>
            )}
          </div>
          <div>
            <strong>Open sibling Xyn</strong>
            {deploymentUrls.siblingUiUrl ? (
              <>
                <p className="muted small">
                  <a
                    className="button-link"
                    href={deploymentUrls.siblingUiUrl}
                    target="_blank"
                    rel="noreferrer"
                    aria-label="Open sibling Xyn"
                  >
                    Open sibling Xyn
                  </a>
                </p>
                <p className="muted small">{deploymentUrls.siblingUiUrl}</p>
              </>
            ) : (
              <p className="muted small">Not provisioned yet</p>
            )}
          </div>
        </div>
        {installedCapability || siblingInstalledArtifact ? (
          <InlineMessage
            tone="info"
            title="Application state"
            body={
              siblingInstalledArtifact
                ? `${installedCapability?.title || siblingInstalledArtifact.artifactSlug} has a local runtime deployed from the generated AppSpec, and the sibling Xyn instance has the generated artifact ${siblingInstalledArtifact.artifactSlug} installed for capability visibility and workbench access.`
                : `${installedCapability?.title || "This app"} currently has a local runtime deployed from the generated AppSpec. No sibling artifact installation has been recorded yet.`
            }
          />
        ) : null}
        {applicationDefinition ? (
          <div className="card capability-card" style={{ marginBottom: 12 }}>
            <div className="card-header">
              <h3>Application Design</h3>
              <span className="chip">definition-driven</span>
            </div>
            <div className="detail-grid" style={{ marginTop: 12 }}>
              <div>
                <strong>Originating prompt</strong>
                <p className="muted small">{rawPrompt || "Prompt unavailable."}</p>
              </div>
              <div>
                <strong>Application artifact</strong>
                <p className="muted small">{applicationDefinition.artifactSlug}</p>
              </div>
              <div>
                <strong>Application shape</strong>
                <p className="muted small">{applicationDefinition.entities.join(", ") || "No entities recorded"}</p>
              </div>
              <div>
                <strong>Reports</strong>
                <p className="muted small">{applicationDefinition.reports.join(", ") || "No reports recorded"}</p>
              </div>
              <div className="span-full">
                <strong>Revision model</strong>
                <p className="muted small">
                  The generated artifact is the canonical installed identity. Follow-up prompts revise this application in place rather than creating a separate app.
                </p>
              </div>
              <div className="span-full">
                <strong>Revision entry point</strong>
                <p className="muted small">
                  Revise the installed capability from the sibling workbench so the prompt runs in the application workspace and targets the current generated artifact.
                </p>
              </div>
            </div>
            <div className="inline-actions" style={{ marginTop: 12 }}>
              {revisionUrl ? (
                <a className="primary button-link" href={revisionUrl}>
                  Open Application Workbench
                </a>
              ) : (
                <button className="primary" type="button" onClick={openRevisionPrompt}>
                  Open Application Workbench
                </button>
              )}
              <button className="ghost" type="button" onClick={continueInWorkbench}>
                Continue Application Design
              </button>
            </div>
          </div>
        ) : null}
        {installedCapability ? (
          <div className="card capability-card" style={{ marginBottom: 12 }}>
            <div className="card-header">
              <h3>Application Runtime</h3>
              <span className="chip">runtime deployed</span>
            </div>
            <div className="detail-grid" style={{ marginTop: 12 }}>
              <div>
                <strong>Generated AppSpec</strong>
                <p className="muted small">{installedCapability.title}</p>
              </div>
              <div>
                <strong>Root instance state</strong>
                <p className="muted small">Local runtime deployed</p>
              </div>
              <div>
                <strong>Sibling instance state</strong>
                <p className="muted small">
                  {siblingInstalledArtifact
                    ? `Generated artifact installed (${siblingInstalledArtifact.artifactSlug})`
                    : "No sibling artifact install recorded"}
                </p>
              </div>
              <div className="span-full">
                <strong>Operate with palette</strong>
                <ul className="muted small" style={{ margin: "6px 0 0 18px" }}>
                  <li><code>show devices</code></li>
                  <li><code>show devices by status</code></li>
                  <li><code>show artifacts of kind app_spec</code></li>
                </ul>
              </div>
              <div className="span-full">
                <strong>Semantics</strong>
                <p className="muted small">
                  The root instance currently deploys the generated app as local runtime containers. The sibling instance installs the generated artifact and executes against its own sibling-owned runtime target.
                </p>
              </div>
              {installedCapability.reports.length > 0 ? (
                <div className="span-full">
                  <strong>Generated reports</strong>
                  <p className="muted small">{installedCapability.reports.join(", ")}</p>
                </div>
              ) : null}
            </div>
            {onOpenArtifacts ? (
              <div className="inline-actions" style={{ marginTop: 12 }}>
                <button className="ghost" type="button" onClick={() => onOpenArtifacts("app_spec")}>
                  View Application Artifacts
                </button>
              </div>
            ) : null}
          </div>
        ) : null}
        {relatedJobs.length > 0 ? (
          <div className="card" style={{ marginBottom: 12 }}>
            <div className="card-header">
              <h3>Execution Timeline</h3>
            </div>
            <div className="canvas-table-wrap">
              <table className="canvas-table">
                <thead>
                  <tr>
                    <th>Step</th>
                    <th>Status</th>
                    <th>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {relatedJobs.map((job) => (
                    <tr key={job.id}>
                      <td>
                        <button className="ghost small" type="button" onClick={() => (onOpenJob ? onOpenJob(job.id) : navigate(toWorkspacePath(workspaceId, `jobs/${job.id}`)))}>
                          {job.type}
                        </button>
                      </td>
                      <td><span className="chip">{job.status}</span></td>
                      <td>{job.updated_at || job.created_at || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}
        {(String(draft?.status || status).toLowerCase() === "submitted" || relatedJobs.length > 0) ? (
          <div className="card" style={{ marginBottom: 12 }}>
            <div className="card-header">
              <h3>Execution Findings</h3>
              {executionNote ? <span className="chip">{executionNote.status}</span> : null}
            </div>
            {executionNotesLoading ? <p className="muted small">Loading execution trace…</p> : null}
            {executionNotesError ? <InlineMessage tone="error" title="Trace unavailable" body={executionNotesError} /> : null}
            {!executionNotesLoading && !executionNotesError && !executionNote ? (
              <p className="muted small">Execution trace not yet linked to this build.</p>
            ) : null}
            {executionNote ? (
              <>
                <div className="detail-grid" style={{ marginTop: 12, marginBottom: 12 }}>
                  <div>
                    <strong>Recorded</strong>
                    <p className="muted small">{formatTimestamp(executionNote.updated_at || executionNote.timestamp)}</p>
                  </div>
                  <div>
                    <strong>Match</strong>
                    <p className="muted small">{executionNote.match_reason.replace(/_/g, " ")}</p>
                  </div>
                  <div className="span-full">
                    <strong>Request</strong>
                    <p className="muted small">{executionNote.prompt_or_request || "—"}</p>
                  </div>
                  <div>
                    <strong>Findings</strong>
                    <ul className="muted small" style={{ margin: "6px 0 0 18px" }}>
                      {(executionNote.findings || []).slice(0, 3).map((item, index) => <li key={`finding-${index}`}>{item}</li>)}
                    </ul>
                  </div>
                  <div>
                    <strong>Proposed Fix</strong>
                    <p className="muted small">{executionNote.proposed_fix || "—"}</p>
                  </div>
                  <div>
                    <strong>Validation</strong>
                    <ul className="muted small" style={{ margin: "6px 0 0 18px" }}>
                      {(executionNote.validation_summary || []).slice(0, 4).map((item, index) => <li key={`validation-${index}`}>{item}</li>)}
                    </ul>
                  </div>
                  <div>
                    <strong>Debt / Warnings</strong>
                    {executionNote.debt_recorded && executionNote.debt_recorded.length > 0 ? (
                      <ul className="muted small" style={{ margin: "6px 0 0 18px" }}>
                        {executionNote.debt_recorded.slice(0, 3).map((item, index) => <li key={`debt-${index}`}>{item}</li>)}
                      </ul>
                    ) : (
                      <p className="muted small">None recorded.</p>
                    )}
                  </div>
                </div>
                {executionNotes.length > 1 ? (
                  <p className="muted small">Showing latest of {executionNotes.length} explicitly linked execution traces.</p>
                ) : null}
                <button className="ghost small" type="button" onClick={() => setExecutionTraceExpanded((value) => !value)}>
                  {executionTraceExpanded ? "Hide full execution note" : "View full execution note"}
                </button>
                {executionTraceExpanded ? (
                  <pre className="code-block" style={{ marginTop: 12 }}>{prettyJson(executionNote)}</pre>
                ) : null}
              </>
            ) : null}
          </div>
        ) : null}
        <Tabs
          value={activeTab}
          onChange={(next) => setActiveTab(next)}
          options={[
            { value: "editor", label: "Editor" },
            { value: "meta", label: "Meta" },
          ]}
          ariaLabel="Draft detail tabs"
        />
        {activeTab === "editor" && (
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
        )}
        {activeTab === "meta" && (
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
        )}
      </section>
    </>
  );
}
