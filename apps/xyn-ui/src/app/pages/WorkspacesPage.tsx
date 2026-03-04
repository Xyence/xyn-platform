import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import Tabs from "../components/ui/Tabs";
import type { WorkspaceSummary } from "../../api/types";
import { createWorkspace, listWorkspaces, updateWorkspace } from "../../api/xyn";
import PeopleRolesPage from "./PeopleRolesPage";
import { toWorkspacePath } from "../routing/workspaceRouting";

type WorkspacesTab = "management" | "people_roles";

const WORKSPACE_TABS: Array<{ value: WorkspacesTab; label: string }> = [
  { value: "management", label: "Workspace Management" },
  { value: "people_roles", label: "People & Roles" },
];

const defaultCreateForm = {
  name: "",
  org_name: "",
  slug: "",
  description: "",
  kind: "customer",
  lifecycle_stage: "prospect",
  parent_workspace_id: "",
};

const defaultEditForm = {
  name: "",
  org_name: "",
  slug: "",
  description: "",
  status: "active" as "active" | "deprecated",
  kind: "customer",
  lifecycle_stage: "prospect",
  parent_workspace_id: "",
  metadata_text: "{}",
};

const LIFECYCLE_OPTIONS = ["lead", "prospect", "customer", "churned", "internal"];

export default function WorkspacesPage({
  activeWorkspaceId,
  activeWorkspaceName,
  canWorkspaceAdmin,
  canManageWorkspaces,
}: {
  activeWorkspaceId: string;
  activeWorkspaceName: string;
  canWorkspaceAdmin: boolean;
  canManageWorkspaces: boolean;
}) {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = String(searchParams.get("tab") || "").trim();
  const activeTab: WorkspacesTab = (WORKSPACE_TABS.find((tab) => tab.value === tabParam)?.value || "management") as WorkspacesTab;

  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string>("");
  const [editForm, setEditForm] = useState(defaultEditForm);
  const [createForm, setCreateForm] = useState(defaultCreateForm);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await listWorkspaces();
      const rows = result.workspaces || [];
      setWorkspaces(rows);
      setSelectedWorkspaceId((current) => {
        if (current && rows.some((workspace) => workspace.id === current)) return current;
        if (activeWorkspaceId && rows.some((workspace) => workspace.id === activeWorkspaceId)) return activeWorkspaceId;
        return rows[0]?.id || "";
      });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [activeWorkspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const selectedWorkspace = useMemo(
    () => workspaces.find((workspace) => workspace.id === selectedWorkspaceId) || null,
    [workspaces, selectedWorkspaceId]
  );

  useEffect(() => {
    if (!selectedWorkspace) {
      setEditForm(defaultEditForm);
      return;
    }
    setEditForm({
      name: selectedWorkspace.name || "",
      org_name: selectedWorkspace.org_name || selectedWorkspace.name || "",
      slug: selectedWorkspace.slug || "",
      description: selectedWorkspace.description || "",
      status: selectedWorkspace.status || "active",
      kind: selectedWorkspace.kind || "customer",
      lifecycle_stage: selectedWorkspace.lifecycle_stage || "prospect",
      parent_workspace_id: selectedWorkspace.parent_workspace_id || "",
      metadata_text: JSON.stringify(selectedWorkspace.metadata || {}, null, 2),
    });
  }, [selectedWorkspace]);

  const updateTab = (next: WorkspacesTab) => {
    const params = new URLSearchParams(searchParams);
    params.set("tab", next);
    setSearchParams(params, { replace: true });
  };

  const submitCreate = async (event: FormEvent) => {
    event.preventDefault();
    if (!canManageWorkspaces) return;
    const name = createForm.name.trim();
    if (!name) return;
    try {
      setCreating(true);
      setError(null);
      setMessage(null);
      const payload: {
        name: string;
        slug?: string;
        description?: string;
        org_name?: string;
        kind?: string;
        lifecycle_stage?: string;
        parent_workspace_id?: string | null;
      } = { name };
      if (createForm.org_name.trim()) payload.org_name = createForm.org_name.trim();
      if (createForm.slug.trim()) payload.slug = createForm.slug.trim();
      if (createForm.description.trim()) payload.description = createForm.description.trim();
      payload.kind = createForm.kind || "customer";
      payload.lifecycle_stage = createForm.lifecycle_stage || "prospect";
      if (createForm.parent_workspace_id) payload.parent_workspace_id = createForm.parent_workspace_id;
      const result = await createWorkspace(payload);
      await load();
      setSelectedWorkspaceId(result.workspace.id);
      setCreateForm(defaultCreateForm);
      setMessage(`Workspace "${result.workspace.name}" created.`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setCreating(false);
    }
  };

  const submitUpdate = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedWorkspaceId) return;
    if (!canManageWorkspaces) return;
    try {
      setSaving(true);
      setError(null);
      setMessage(null);
      let parsedMetadata: Record<string, unknown> = {};
      if (editForm.metadata_text.trim()) {
        try {
          const parsed = JSON.parse(editForm.metadata_text);
          if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
            setError("Metadata must be a JSON object.");
            return;
          }
          parsedMetadata = parsed as Record<string, unknown>;
        } catch {
          setError("Metadata must be valid JSON.");
          return;
        }
      }
      const payload = {
        name: editForm.name.trim(),
        slug: editForm.slug.trim(),
        description: editForm.description,
        status: editForm.status,
        org_name: editForm.org_name.trim(),
        kind: editForm.kind || "customer",
        lifecycle_stage: editForm.lifecycle_stage || "prospect",
        parent_workspace_id: editForm.parent_workspace_id || null,
        metadata: parsedMetadata,
      };
      const result = await updateWorkspace(selectedWorkspaceId, payload);
      setWorkspaces((current) =>
        current.map((workspace) => (workspace.id === selectedWorkspaceId ? { ...workspace, ...result.workspace } : workspace))
      );
      setMessage(`Workspace "${result.workspace.name}" updated.`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Workspaces</h2>
          <p className="muted">Current workspace: <strong>{activeWorkspaceName || "Workspace"}</strong></p>
          <p className="muted small">Workspace ID: {activeWorkspaceId || "not selected"}</p>
          <p className="muted small">Workspaces represent tenants across the lifecycle (lead → prospect → customer).</p>
        </div>
        <div className="inline-actions">
          <button className="ghost" type="button" onClick={() => void load()} disabled={loading || saving || creating}>
            {loading ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </div>

      <div className="page-tabs">
        <Tabs
          ariaLabel="Workspaces tabs"
          value={activeTab}
          onChange={updateTab}
          options={WORKSPACE_TABS.map((tab) => ({ value: tab.value, label: tab.label }))}
        />
      </div>

      {error ? <InlineMessage tone="error" title="Request failed" body={error} /> : null}
      {message ? <InlineMessage tone="info" title="Saved" body={message} /> : null}

      {activeTab === "management" ? (
        <div className="workspace-management-grid" style={{ display: "grid", gap: 16, gridTemplateColumns: "minmax(260px, 1fr) minmax(320px, 1.2fr)" }}>
          <section className="card">
            <div className="card-header">
              <h3>Workspace list</h3>
            </div>
            <div className="instance-list">
              {workspaces.map((workspace) => (
                <button
                  key={workspace.id}
                  type="button"
                  className={`instance-row ${workspace.id === selectedWorkspaceId ? "active" : ""}`}
                  onClick={() => setSelectedWorkspaceId(workspace.id)}
                >
                  <div>
                    <strong>{workspace.name}</strong>
                    <span className="muted small">{workspace.slug}</span>
                  </div>
                  <span className={`status-chip ${workspace.status === "deprecated" ? "deprecated" : "active"}`}>
                    {workspace.status || "active"}
                  </span>
                </button>
              ))}
              {workspaces.length === 0 ? <p className="muted">No workspaces found.</p> : null}
            </div>
          </section>

          <section className="card">
            <div className="card-header">
              <h3>Workspace profile</h3>
              {selectedWorkspace && selectedWorkspace.id === activeWorkspaceId ? (
                <span className="status-chip canonical">Current workspace</span>
              ) : null}
            </div>
            {selectedWorkspace ? (
              <div className="inline-actions" style={{ marginBottom: 10 }}>
                <span className={`status-chip ${selectedWorkspace.tenant_auth_status?.sso === "ready" ? "active" : ""}`}>
                  SSO: {selectedWorkspace.tenant_auth_status?.sso === "ready" ? "Ready" : "Not configured"}
                </span>
                <span className={`status-chip ${selectedWorkspace.tenant_auth_status?.local_login === "enabled" ? "active" : ""}`}>
                  Local login: {selectedWorkspace.tenant_auth_status?.local_login === "enabled" ? "enabled" : "disabled"}
                </span>
              </div>
            ) : null}
            {selectedWorkspace ? (
              <form onSubmit={(event) => void submitUpdate(event)} className="form-grid">
                <label>
                  Name
                  <input
                    value={editForm.name}
                    onChange={(event) => setEditForm((current) => ({ ...current, name: event.target.value }))}
                    disabled={!canManageWorkspaces}
                  />
                </label>
                <label>
                  Org name
                  <input
                    value={editForm.org_name}
                    onChange={(event) => setEditForm((current) => ({ ...current, org_name: event.target.value }))}
                    disabled={!canManageWorkspaces}
                  />
                </label>
                <label>
                  Slug
                  <input
                    value={editForm.slug}
                    onChange={(event) => setEditForm((current) => ({ ...current, slug: event.target.value }))}
                    disabled={!canManageWorkspaces}
                  />
                </label>
                <label className="span-full">
                  Description
                  <textarea
                    rows={3}
                    value={editForm.description}
                    onChange={(event) => setEditForm((current) => ({ ...current, description: event.target.value }))}
                    disabled={!canManageWorkspaces}
                  />
                </label>
                <label>
                  Kind
                  <select
                    value={editForm.kind}
                    onChange={(event) => setEditForm((current) => ({ ...current, kind: event.target.value || "customer" }))}
                    disabled={!canManageWorkspaces}
                  >
                    <option value="customer">customer</option>
                    <option value="operator">operator</option>
                    <option value="reseller">reseller</option>
                    <option value="internal">internal</option>
                  </select>
                </label>
                <label>
                  Lifecycle stage
                  <select
                    value={editForm.lifecycle_stage}
                    onChange={(event) => setEditForm((current) => ({ ...current, lifecycle_stage: event.target.value || "prospect" }))}
                    disabled={!canManageWorkspaces}
                  >
                    {LIFECYCLE_OPTIONS.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Parent workspace
                  <select
                    value={editForm.parent_workspace_id}
                    onChange={(event) => setEditForm((current) => ({ ...current, parent_workspace_id: event.target.value }))}
                    disabled={!canManageWorkspaces}
                  >
                    <option value="">(none)</option>
                    {workspaces
                      .filter((workspace) => workspace.id !== selectedWorkspaceId)
                      .map((workspace) => (
                        <option key={workspace.id} value={workspace.id}>
                          {workspace.name}
                        </option>
                      ))}
                  </select>
                </label>
                <label className="span-full">
                  Metadata (JSON)
                  <textarea
                    rows={4}
                    value={editForm.metadata_text}
                    onChange={(event) => setEditForm((current) => ({ ...current, metadata_text: event.target.value }))}
                    disabled={!canManageWorkspaces}
                  />
                </label>
                <label>
                  Status
                  <select
                    value={editForm.status}
                    onChange={(event) =>
                      setEditForm((current) => ({
                        ...current,
                        status: event.target.value === "deprecated" ? "deprecated" : "active",
                      }))
                    }
                    disabled={!canManageWorkspaces}
                  >
                    <option value="active">active</option>
                    <option value="deprecated">deprecated</option>
                  </select>
                </label>
                <div className="inline-actions">
                  <button className="primary" type="submit" disabled={!canManageWorkspaces || saving}>
                    {saving ? "Saving..." : "Save workspace"}
                  </button>
                  <button className="ghost" type="button" onClick={() => navigate(toWorkspacePath(selectedWorkspace.id, "build/artifacts"))}>
                    Open workspace
                  </button>
                </div>
              </form>
            ) : (
              <p className="muted">Select a workspace to view details.</p>
            )}
          </section>

          <section className="card" style={{ gridColumn: "1 / -1" }}>
            <div className="card-header">
              <h3>Create workspace</h3>
            </div>
            {!canManageWorkspaces ? (
              <p className="muted">Only platform admins can create workspaces.</p>
            ) : (
              <form onSubmit={(event) => void submitCreate(event)} className="form-grid">
                <div className="detail-grid">
                  <label>
                    Name
                    <input
                      value={createForm.name}
                      onChange={(event) => setCreateForm((current) => ({ ...current, name: event.target.value }))}
                      placeholder="Platform Build"
                      required
                    />
                  </label>
                  <label>
                    Org name (optional)
                    <input
                      value={createForm.org_name}
                      onChange={(event) => setCreateForm((current) => ({ ...current, org_name: event.target.value }))}
                      placeholder="Acme Utilities"
                    />
                  </label>
                  <label>
                    Slug (optional)
                    <input
                      value={createForm.slug}
                      onChange={(event) => setCreateForm((current) => ({ ...current, slug: event.target.value }))}
                      placeholder="platform-build"
                    />
                  </label>
                </div>
                <div className="detail-grid">
                  <label>
                    Kind
                    <select
                      value={createForm.kind}
                      onChange={(event) => setCreateForm((current) => ({ ...current, kind: event.target.value || "customer" }))}
                    >
                      <option value="customer">customer</option>
                      <option value="operator">operator</option>
                      <option value="reseller">reseller</option>
                      <option value="internal">internal</option>
                    </select>
                  </label>
                  <label>
                    Lifecycle stage
                    <select
                      value={createForm.lifecycle_stage}
                      onChange={(event) => setCreateForm((current) => ({ ...current, lifecycle_stage: event.target.value || "prospect" }))}
                    >
                      {LIFECYCLE_OPTIONS.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Parent workspace (optional)
                    <select
                      value={createForm.parent_workspace_id}
                      onChange={(event) => setCreateForm((current) => ({ ...current, parent_workspace_id: event.target.value }))}
                    >
                      <option value="">(none)</option>
                      {workspaces.map((workspace) => (
                        <option key={workspace.id} value={workspace.id}>
                          {workspace.name}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <label>
                  Description (optional)
                  <textarea
                    rows={2}
                    value={createForm.description}
                    onChange={(event) => setCreateForm((current) => ({ ...current, description: event.target.value }))}
                  />
                </label>
                <div className="inline-actions">
                  <button className="primary" type="submit" disabled={creating || !createForm.name.trim()}>
                    {creating ? "Creating..." : "Create workspace"}
                  </button>
                </div>
              </form>
            )}
          </section>
        </div>
      ) : (
        <PeopleRolesPage workspaceId={activeWorkspaceId} canAdmin={canWorkspaceAdmin} />
      )}
    </>
  );
}
