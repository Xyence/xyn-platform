import { useEffect, useMemo, useState } from "react";
import { Bot, RefreshCw, X } from "lucide-react";
import { listAiActivity, listAppJobs } from "../../../api/xyn";
import type { AiActivityEntry, AppJob } from "../../../api/types";
import { useOperations } from "../../state/operationRegistry";
import { runtimeEventToActivityEntry, subscribeRuntimeEventStream, upsertActivityEntry } from "../../utils/runtimeEventStream";

type Props = {
  open: boolean;
  onClose: () => void;
  workspaceId?: string;
  artifactId?: string;
  threadId?: string;
};

function relativeTime(value?: string): string {
  if (!value) return "now";
  const ts = new Date(value).getTime();
  if (Number.isNaN(ts)) return value;
  const delta = Math.max(1, Math.floor((Date.now() - ts) / 1000));
  if (delta < 60) return `${delta}s ago`;
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
  return `${Math.floor(delta / 86400)}d ago`;
}

function mapJobStatus(status?: string): "running" | "succeeded" | "failed" {
  const token = String(status || "").trim().toLowerCase();
  if (token === "succeeded" || token === "completed") return "succeeded";
  if (token === "failed") return "failed";
  return "running";
}

function mapAppJobToActivity(job: AppJob): AiActivityEntry {
  const input = job.input_json && typeof job.input_json === "object" ? job.input_json : {};
  return {
    id: `app-job:${job.id}`,
    event_type: "app_builder_job",
    status: mapJobStatus(job.status),
    summary: `Build step ${job.type} ${job.status}`,
    created_at: job.updated_at || job.created_at,
    actor_id: null,
    agent_slug: "xyn-app-builder",
    provider: "",
    model_name: "",
    artifact_id: undefined,
    artifact_type: "",
    artifact_title: "",
    request_type: "app_builder.job",
    prompt: "",
    workspace_id: job.workspace_id,
    draft_id: typeof input.draft_id === "string" ? input.draft_id : null,
    job_id: job.id,
    error: mapJobStatus(job.status) === "failed" ? String(job.logs_text || "").split("\n").slice(-1)[0] || "" : "",
    source: "app_job",
  };
}

function interpretationSummary(item: AiActivityEntry): string {
  const interpretation = item.prompt_interpretation;
  if (!interpretation) return "";
  const fieldSummary = (interpretation.fields || [])
    .filter((field) => field.state !== "missing" && field.value != null && String(field.value).trim())
    .slice(0, 2)
    .map((field) => `${field.name}=${String(field.value)}`);
  const parts = [
    interpretation.action?.label,
    interpretation.target_entity?.label || interpretation.target_work_item?.label || interpretation.target_run?.label,
    interpretation.target_record?.reference,
    interpretation.target_work_item?.reference ? `work item ${interpretation.target_work_item.reference}` : "",
    interpretation.target_run?.id ? `run ${interpretation.target_run.id}` : "",
    fieldSummary.length ? fieldSummary.join(", ") : "",
    interpretation.needs_clarification ? "clarification required" : "",
    interpretation.execution_mode ? interpretation.execution_mode.replace(/_/g, " ") : "",
  ].filter(Boolean);
  return parts.join(" · ");
}

function conversationRuntimeSummary(item: AiActivityEntry): string {
  const message = item.conversation_message;
  if (!message) return "";
  const refs = message.refs || {};
  const parts = [
    refs.run_id ? `run ${refs.run_id}` : "",
    refs.work_item_id ? `work item ${refs.work_item_id}` : "",
    refs.step_key ? `step ${refs.step_key}` : "",
    refs.artifact_type ? `artifact ${refs.artifact_type}` : "",
  ].filter(Boolean);
  return parts.join(" · ");
}

function humanizePurpose(purpose?: string): string {
  const token = String(purpose || "").trim();
  if (!token) return "default";
  return token.replace(/[_-]+/g, " ");
}

function sourceLabel(source?: string, purpose?: string): string {
  const normalizedPurpose = humanizePurpose(purpose);
  if (source === "explicit") return `Explicit ${normalizedPurpose} assignment`;
  if (source === "default_fallback") return "Default fallback";
  return source || "Unknown";
}

function activityResolutionSummary(item: AiActivityEntry): { actor: string; source: string; reason: string } | null {
  const resolution = item.agent_resolution;
  const actor = String(resolution?.resolved_agent_name || item.agent_name || item.agent_slug || "").trim();
  if (!actor) return null;
  const purpose = String(resolution?.purpose || item.purpose || "").trim();
  return {
    actor,
    source: sourceLabel(String(resolution?.resolution_source || "").trim(), purpose),
    reason: String(resolution?.reason || "").trim(),
  };
}

export default function AgentActivityDrawer({ open, onClose, workspaceId, artifactId, threadId }: Props) {
  const normalizedWorkspaceId = String(workspaceId || "").trim();
  const [items, setItems] = useState<AiActivityEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [artifactOnly, setArtifactOnly] = useState(Boolean(artifactId));
  const [degradedMode, setDegradedMode] = useState(false);
  const { operations } = useOperations();

  useEffect(() => {
    setArtifactOnly(Boolean(artifactId));
  }, [artifactId]);

  const load = async () => {
    if (!normalizedWorkspaceId) {
      setItems([]);
      return;
    }
    try {
      setError(null);
      setLoading(true);
      const [activityResult, appJobs] = await Promise.all([
        listAiActivity({
          workspaceId: normalizedWorkspaceId,
          threadId,
          artifactId: artifactOnly ? artifactId : undefined,
        }),
        listAppJobs(normalizedWorkspaceId),
      ]);
      const merged = [...(activityResult.items || []), ...appJobs.map(mapAppJobToActivity)];
      merged.sort((left, right) => {
        const leftTs = new Date(left.created_at || 0).getTime();
        const rightTs = new Date(right.created_at || 0).getTime();
        return rightTs - leftTs;
      });
      setItems(merged);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    void load();
  }, [open, normalizedWorkspaceId, threadId, artifactId, artifactOnly]);

  useEffect(() => {
    if (!open || !normalizedWorkspaceId || artifactOnly) return;
    const subscription = subscribeRuntimeEventStream({
      workspaceId: normalizedWorkspaceId,
      threadId,
      onOpen: () => setDegradedMode(false),
      onError: () => setDegradedMode(true),
      onEvent: (event) => {
        setDegradedMode(false);
        setItems((current) => upsertActivityEntry(current, runtimeEventToActivityEntry(event)));
      },
    });
    return () => subscription.close();
  }, [open, normalizedWorkspaceId, threadId, artifactOnly]);

  useEffect(() => {
    if (!open || !degradedMode) return;
    const interval = window.setInterval(() => void load(), 30000);
    return () => window.clearInterval(interval);
  }, [open, degradedMode, normalizedWorkspaceId, threadId, artifactId, artifactOnly]);

  const badgeCount = useMemo(() => items.filter((item) => item.status === "running").length, [items]);
  const runningOps = useMemo(() => operations.filter((entry) => entry.status === "running"), [operations]);

  return (
    <>
      {open && <button type="button" className="notification-backdrop" aria-label="Close agent activity" onClick={onClose} />}
      <aside className={`notification-drawer agent-activity-drawer ${open ? "open" : ""}`} aria-label="Agent activity">
        <div className="notification-drawer-header">
          <h3>Agent Activity</h3>
          <button type="button" className="ghost" onClick={onClose} aria-label="Close agent activity">
            <X size={14} />
          </button>
        </div>
        <div className="notification-actions">
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={artifactOnly}
              disabled={!artifactId}
              onChange={(event) => setArtifactOnly(event.target.checked)}
            />
            This artifact only
          </label>
          <button type="button" className="ghost small" onClick={() => void load()} disabled={loading}>
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
        <div className="notification-list">
          {degradedMode ? <p className="muted small">Live runtime stream unavailable. Falling back to periodic refresh.</p> : null}
          {runningOps.length > 0 && (
            <section className="notification-item running-ops-card" aria-label="Currently running operations">
              <div className="notification-text">
                <strong>Currently running</strong>
                {runningOps.map((entry) => (
                  <span key={entry.id} className="muted small">
                    {entry.type.toUpperCase()} · {entry.label}
                  </span>
                ))}
              </div>
            </section>
          )}
          {loading && <p className="muted">Loading activity…</p>}
          {error && <p className="muted">{error}</p>}
          {!loading && !error && items.length === 0 && <p className="muted">No agent activity yet.</p>}
          {items.map((item) => (
            <article
              key={item.id}
              className={`notification-item ${
                item.conversation_message?.message_type === "system_runtime"
                  ? "system-runtime-message"
                  : item.conversation_message?.message_type === "escalation"
                    ? "system-runtime-message escalation-message"
                    : item.conversation_message?.message_type === "execution_summary"
                      ? "system-runtime-message execution-summary-message"
                      : ""
              }`}
            >
              <span className={`notification-icon ${item.status === "failed" ? "error" : item.status === "succeeded" ? "success" : "info"}`}>
                <Bot size={15} />
              </span>
              <div className="notification-text">
                {(() => {
                  const summary = activityResolutionSummary(item);
                  if (!summary) return null;
                  return (
                    <>
                      <span className="muted small">Planned with: {summary.actor}</span>
                      <span className="muted small">Source: {summary.source}</span>
                      {summary.reason ? <span className="muted small">{summary.reason}</span> : null}
                    </>
                  );
                })()}
                <strong>{item.summary || item.event_type}</strong>
                {item.prompt ? <span className="muted small">{item.prompt}</span> : null}
                {item.conversation_message?.body ? (
                  <span className="muted small">{item.conversation_message.body}</span>
                ) : null}
                {item.conversation_message?.reason ? <span className="muted small">{item.conversation_message.reason}</span> : null}
                {(item.conversation_message?.options || []).length ? (
                  <span className="muted small">{(item.conversation_message?.options || []).join(" · ")}</span>
                ) : null}
                <span className="muted small">
                  {item.request_type || item.provider || item.model_name || item.agent_slug
                    ? [item.request_type, item.provider, item.model_name, item.agent_slug].filter(Boolean).join(" · ")
                    : "activity"}
                </span>
                {interpretationSummary(item) ? <span className="muted small">{interpretationSummary(item)}</span> : null}
                {conversationRuntimeSummary(item) ? <span className="muted small">{conversationRuntimeSummary(item)}</span> : null}
                <span className="muted small">
                  {item.artifact_type || "artifact"} {item.artifact_id || "—"} · {item.status} · {relativeTime(item.created_at)}
                  {item.draft_id ? ` · draft ${item.draft_id}` : ""}
                  {item.job_id ? ` · job ${item.job_id}` : ""}
                </span>
                {item.error ? <span className="muted small">{item.error}</span> : null}
              </div>
            </article>
          ))}
          {badgeCount > 0 && <p className="muted small">{badgeCount} running operation(s).</p>}
        </div>
      </aside>
    </>
  );
}
