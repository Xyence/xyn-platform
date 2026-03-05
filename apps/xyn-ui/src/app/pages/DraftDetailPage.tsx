import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import Tabs from "../components/ui/Tabs";
import { getAppIntentDraft, submitAppIntentDraft, updateAppIntentDraft } from "../../api/xyn";
import type { AppIntentDraft } from "../../api/types";
import WorkspaceContextBar from "../components/common/WorkspaceContextBar";
import { toWorkspacePath } from "../routing/workspaceRouting";

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

export default function DraftDetailPage({
  workspaceId,
  workspaceName,
  workspaceColor,
}: {
  workspaceId: string;
  workspaceName: string;
  workspaceColor?: string;
}) {
  const params = useParams();
  const navigate = useNavigate();
  const draftId = String(params.draftId || "").trim();
  const [draft, setDraft] = useState<AppIntentDraft | null>(null);
  const [title, setTitle] = useState("");
  const [status, setStatus] = useState<DraftStatusValue>("draft");
  const [jsonText, setJsonText] = useState("{}");
  const [saving, setSaving] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [activeTab, setActiveTab] = useState<DraftDetailTab>("editor");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
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
      setMessage(`Draft submitted. Job queued: ${payload.job_id}`);
      navigate(toWorkspacePath(workspaceId, `jobs/${payload.job_id}`));
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
          <button className="ghost" onClick={() => navigate(toWorkspacePath(workspaceId, "drafts"))}>
            Back to Drafts
          </button>
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
