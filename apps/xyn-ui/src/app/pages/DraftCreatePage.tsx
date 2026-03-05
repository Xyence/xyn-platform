import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import { createAppIntentDraft } from "../../api/xyn";
import WorkspaceContextBar from "../components/common/WorkspaceContextBar";
import { toWorkspacePath } from "../routing/workspaceRouting";

const EXAMPLE_PROMPT = "Build a network inventory app that stores devices per workspace, with search and status tracking.";

function makeDefaultTitle(prompt: string): string {
  const token = String(prompt || "").trim();
  if (!token) return "New App Intent";
  const firstLine = token.split("\n")[0] || token;
  return firstLine.slice(0, 80);
}

export default function DraftCreatePage({
  workspaceId,
  workspaceName,
  workspaceColor,
}: {
  workspaceId: string;
  workspaceName: string;
  workspaceColor?: string;
}) {
  const navigate = useNavigate();
  const [prompt, setPrompt] = useState(EXAMPLE_PROMPT);
  const [title, setTitle] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const computedTitle = useMemo(() => (title.trim() ? title.trim() : makeDefaultTitle(prompt)), [prompt, title]);

  const submit = async () => {
    if (!workspaceId) return;
    try {
      setSaving(true);
      setError(null);
      const draft = await createAppIntentDraft(workspaceId, {
        type: "app_intent",
        title: computedTitle,
        content_json: {
          raw_prompt: prompt,
          initial_intent: {},
        },
      });
      navigate(toWorkspacePath(workspaceId, `drafts/${draft.id}`));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <WorkspaceContextBar workspaceName={workspaceName} workspaceColor={workspaceColor} />
      <div className="page-header">
        <div>
          <h2>New Draft</h2>
          <p className="muted">Start from a natural-language app request.</p>
        </div>
        <div className="inline-actions">
          <button className="ghost" onClick={() => navigate(toWorkspacePath(workspaceId, "drafts"))}>
            Cancel
          </button>
          <button className="primary" onClick={() => void submit()} disabled={saving || !workspaceId}>
            {saving ? "Creating..." : "Create Draft"}
          </button>
        </div>
      </div>
      {!workspaceId && <InlineMessage tone="error" title="Workspace required" body="Select a workspace first." />}
      {error && <InlineMessage tone="error" title="Create failed" body={error} />}
      <section className="card">
        <div className="form-grid">
          <label>
            Title (optional)
            <input className="input" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="New App Intent" />
          </label>
          <label className="span-full">
            Prompt
            <textarea
              className="input"
              rows={10}
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder={EXAMPLE_PROMPT}
            />
          </label>
        </div>
      </section>
    </>
  );
}
