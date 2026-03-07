import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import Tabs from "../components/ui/Tabs";
import { getAppIntentDraft, listAppJobs, submitAppIntentDraft, updateAppIntentDraft } from "../../api/xyn";
import type { AppIntentDraft, AppJob } from "../../api/types";
import WorkspaceContextBar from "../components/common/WorkspaceContextBar";
import { toWorkspacePath } from "../routing/workspaceRouting";
import { useNotifications } from "../state/notificationsStore";

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

export default function DraftDetailPage({
  workspaceId,
  workspaceName,
  workspaceColor,
  draftId: explicitDraftId,
  onBack,
  onOpenJob,
  linkedJobId,
}: {
  workspaceId: string;
  workspaceName: string;
  workspaceColor?: string;
  draftId?: string;
  onBack?: () => void;
  onOpenJob?: (jobId: string) => void;
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
  const { push } = useNotifications();
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
    const interval = window.setInterval(() => void loadJobs(), 4000);
    return () => window.clearInterval(interval);
  }, [buildStatus, loadJobs]);

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
      <WorkspaceContextBar workspaceName={workspaceName} workspaceColor={workspaceColor} />
      <div className="page-header">
        <div>
          <h2>Draft Detail</h2>
          <p className="muted">Review, edit, and submit the app intent draft.</p>
        </div>
        <div className="inline-actions">
          <button className="ghost" onClick={() => (onBack ? onBack() : navigate(toWorkspacePath(workspaceId, "drafts")))}>
            {onBack ? "Back" : "Back to Drafts"}
          </button>
          {latestJobId ? (
            <button className="ghost" onClick={() => (onOpenJob ? onOpenJob(latestJobId) : navigate(toWorkspacePath(workspaceId, `jobs/${latestJobId}`)))}>
              View Pipeline Job
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

      <section className="card">
        <div className="card-header">
          <h3>{draft?.title || "Draft"}</h3>
          <span className="chip">{draft?.status || status || "draft"}</span>
        </div>
        <div className="detail-grid" style={{ marginTop: 12, marginBottom: 12 }}>
          <div>
            <strong>Build status</strong>
            <p className="muted small">{buildStatus}</p>
          </div>
          <div>
            <strong>Tracked jobs</strong>
            <p className="muted small">{relatedJobs.length || 0}</p>
          </div>
          <div>
            <strong>Running app</strong>
            <p className="muted small">
              {deploymentUrls.appUrl ? <a href={deploymentUrls.appUrl} target="_blank" rel="noreferrer">{deploymentUrls.appUrl}</a> : "Not deployed yet"}
            </p>
          </div>
          <div>
            <strong>Sibling Xyn</strong>
            <p className="muted small">
              {deploymentUrls.siblingUiUrl ? <a href={deploymentUrls.siblingUiUrl} target="_blank" rel="noreferrer">{deploymentUrls.siblingUiUrl}</a> : "Not provisioned yet"}
            </p>
          </div>
        </div>
        {relatedJobs.length > 0 ? (
          <div className="card" style={{ marginBottom: 12 }}>
            <div className="card-header">
              <h3>Build Pipeline</h3>
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
