import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import { listWorkspaceArtifacts, uninstallWorkspaceArtifact } from "../../api/xyn";
import type { WorkspaceInstalledArtifactSummary } from "../../api/types";
import WorkspaceContextBar from "../components/common/WorkspaceContextBar";
import { toWorkspacePath } from "../routing/workspaceRouting";

function formatDate(value?: string): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString();
}

export default function ArtifactsRegistryPage({
  workspaceId,
  workspaceName,
  workspaceColor,
}: {
  workspaceId: string;
  workspaceName: string;
  workspaceColor?: string;
}) {
  const navigate = useNavigate();
  const [items, setItems] = useState<WorkspaceInstalledArtifactSummary[]>([]);
  const [query, setQuery] = useState("");
  const [uninstallingBindingId, setUninstallingBindingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedUnsupported, setSelectedUnsupported] = useState<WorkspaceInstalledArtifactSummary | null>(null);

  const load = useCallback(async () => {
    if (!workspaceId) {
      setItems([]);
      return;
    }
    try {
      setLoading(true);
      setError(null);
      const payload = await listWorkspaceArtifacts(workspaceId);
      setItems(payload.artifacts || []);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(() => {
    const text = query.trim().toLowerCase();
    return items.filter((item) => {
      if (!text) return true;
      const haystack = `${item.title || item.name || ""} ${item.description || ""} ${item.kind || ""} ${item.installed_state || ""}`.toLowerCase();
      return haystack.includes(text);
    });
  }, [items, query]);

  const notifyWorkspaceArtifactsChanged = () => {
    window.dispatchEvent(new Event("xyn:workspace-artifacts-changed"));
  };

  const uninstall = async (bindingId: string) => {
    if (!workspaceId || !bindingId) return;
    try {
      setUninstallingBindingId(bindingId);
      setError(null);
      await uninstallWorkspaceArtifact(workspaceId, bindingId);
      await load();
      notifyWorkspaceArtifactsChanged();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setUninstallingBindingId(null);
    }
  };

  const handleArtifactOpen = (item: WorkspaceInstalledArtifactSummary) => {
    const manage = item.manifest_summary?.surfaces?.manage || [];
    const firstManage = manage[0];
    if (firstManage?.path) {
      navigate(firstManage.path);
      return;
    }
    if (String(item.kind || "").toLowerCase() === "article") {
      navigate(toWorkspacePath(workspaceId, `build/artifacts/${item.artifact_id}`));
      return;
    }
    setSelectedUnsupported(item);
  };

  return (
    <>
      <WorkspaceContextBar workspaceName={workspaceName} workspaceColor={workspaceColor} />

      <div className="page-header">
        <div>
          <h2>Artifact Explorer</h2>
          <p className="muted">Workspace-installed artifacts.</p>
        </div>
      </div>

      {!workspaceId && <InlineMessage tone="error" title="Workspace required" body="Select a workspace to view installed artifacts." />}
      {error && <InlineMessage tone="error" title="Request failed" body={error} />}

      <section className="card">
        <div className="card-header">
          <h3>Installed Artifacts</h3>
          <div className="inline-actions">
            <input
              className="input artifacts-registry-search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search installed artifacts"
              aria-label="Search installed artifacts"
            />
            <button className="ghost" onClick={() => void load()} disabled={loading || !workspaceId}>
              Refresh
            </button>
          </div>
        </div>
        <div className="instance-list" role="table" aria-label="Workspace installed artifacts">
          <div className="instance-row" role="row">
            <div role="columnheader">
              <strong>Title</strong>
            </div>
            <div role="columnheader" className="muted small">
              Kind · State · Enabled · Updated
            </div>
          </div>
          {filtered.map((item) => (
            <div
              key={item.binding_id}
              className="instance-row"
              role="row"
              tabIndex={0}
              onClick={() => handleArtifactOpen(item)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  handleArtifactOpen(item);
                }
              }}
            >
              <div role="cell">
                <strong>{item.title || item.name}</strong>
                <span className="muted small">{item.description || "-"}</span>
              </div>
              <div role="cell" className="muted small inline-actions">
                {item.kind || "-"} · {item.installed_state || "installed"} · {item.enabled ? "yes" : "no"} · {formatDate(item.updated_at)}
                <details
                  onClick={(event) => {
                    event.stopPropagation();
                  }}
                >
                  <summary className="ghost sm" aria-label={`Actions for ${item.title || item.name}`}>
                    ⋮
                  </summary>
                  <button
                    className="ghost sm"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      void uninstall(item.binding_id);
                    }}
                    disabled={uninstallingBindingId === item.binding_id}
                    aria-label={`Uninstall ${item.title || item.name}`}
                  >
                    {uninstallingBindingId === item.binding_id ? "..." : "Uninstall"}
                  </button>
                </details>
              </div>
            </div>
          ))}
          {!loading && filtered.length === 0 && (
            <div className="instance-row" role="row">
              <div role="cell">
                <strong>No artifacts installed in this workspace.</strong>
                <span className="muted small">Open Catalog to browse and install artifacts.</span>
              </div>
            </div>
          )}
        </div>
      </section>

      {selectedUnsupported && (
        <section className="card">
          <div className="card-header">
            <h3>{selectedUnsupported.title || selectedUnsupported.name}</h3>
          </div>
          <p>No management UI provided.</p>
          <p className="muted small">
            Roles: {(selectedUnsupported.manifest_summary?.roles || []).join(", ") || "none"} · nav surfaces:{" "}
            {selectedUnsupported.manifest_summary?.surfaces?.nav?.length || 0} · manage surfaces:{" "}
            {selectedUnsupported.manifest_summary?.surfaces?.manage?.length || 0} · docs surfaces:{" "}
            {selectedUnsupported.manifest_summary?.surfaces?.docs?.length || 0}
          </p>
          {(selectedUnsupported.manifest_summary?.surfaces?.docs?.length || 0) > 0 && (
            <p className="muted small">
              Docs:{" "}
              {selectedUnsupported.manifest_summary?.surfaces?.docs?.map((entry) => (
                <a key={`${entry.path}-${entry.label}`} href={entry.path} style={{ marginRight: 8 }}>
                  {entry.label}
                </a>
              ))}
            </p>
          )}
          <button className="ghost" type="button" onClick={() => setSelectedUnsupported(null)}>
            Close
          </button>
        </section>
      )}
    </>
  );
}
