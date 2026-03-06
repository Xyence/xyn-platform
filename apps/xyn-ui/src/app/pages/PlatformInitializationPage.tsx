import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import { completePlatformInitialization } from "../../api/xyn";
import { DEFAULT_WORKSPACE_SUBPATH, toWorkspacePath } from "../routing/workspaceRouting";

export default function PlatformInitializationPage() {
  const navigate = useNavigate();
  const [workspaceName, setWorkspaceName] = useState("Company");
  const [workspaceSlug, setWorkspaceSlug] = useState("");
  const [orgName, setOrgName] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const name = workspaceName.trim();
    if (!name || submitting) return;
    setSubmitting(true);
    setError("");
    try {
      const result = await completePlatformInitialization({
        workspace_name: name,
        workspace_slug: workspaceSlug.trim() || undefined,
        org_name: orgName.trim() || undefined,
        description: description.trim() || undefined,
      });
      const workspaceId = String(result.workspace?.id || "").trim();
      if (workspaceId) {
        window.localStorage.setItem("xyn.activeWorkspaceId", workspaceId);
        navigate(toWorkspacePath(workspaceId, DEFAULT_WORKSPACE_SUBPATH), { replace: true });
        return;
      }
      navigate("/app/platform/hub", { replace: true });
    } catch (err) {
      setError((err as Error).message || "Initialization failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="card" style={{ maxWidth: 720 }}>
      <div className="card-header">
        <h2>Initialize Platform</h2>
      </div>
      <p className="muted">
        Complete first-run setup by creating the initial workspace. This is required before normal platform operations in non-dev mode.
      </p>
      {error ? <InlineMessage tone="error" title="Initialization failed" body={error} /> : null}
      <form onSubmit={onSubmit} className="form-grid" style={{ marginTop: 12 }}>
        <label>
          Workspace name
          <input value={workspaceName} onChange={(event) => setWorkspaceName(event.target.value)} required />
        </label>
        <label>
          Workspace slug (optional)
          <input value={workspaceSlug} onChange={(event) => setWorkspaceSlug(event.target.value)} />
        </label>
        <label>
          Organization name (optional)
          <input value={orgName} onChange={(event) => setOrgName(event.target.value)} />
        </label>
        <label>
          Description (optional)
          <textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={3} />
        </label>
        <div className="form-actions">
          <button type="submit" className="primary" disabled={submitting}>
            {submitting ? "Initializing..." : "Initialize Platform"}
          </button>
        </div>
      </form>
    </section>
  );
}

