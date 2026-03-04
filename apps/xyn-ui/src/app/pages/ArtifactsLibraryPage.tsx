import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import { installWorkspaceArtifact, listArtifactsCatalog } from "../../api/xyn";
import type { CatalogArtifactSummary } from "../../api/types";
import { toWorkspacePath } from "../routing/workspaceRouting";

function formatDate(value?: string): string {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "-";
  return parsed.toLocaleString();
}

export default function ArtifactsLibraryPage({ workspaceId, workspaceName }: { workspaceId: string; workspaceName: string }) {
  const navigate = useNavigate();
  const [rows, setRows] = useState<CatalogArtifactSummary[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("");
  const [loading, setLoading] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const payload = await listArtifactsCatalog({
        query: query.trim() || undefined,
        kind: kind || undefined,
        workspace_id: workspaceId || undefined,
      });
      const artifacts = payload.artifacts || [];
      setRows(artifacts);
      if (!selectedId && artifacts[0]?.id) setSelectedId(artifacts[0].id);
      if (selectedId && !artifacts.some((row) => row.id === selectedId)) setSelectedId(artifacts[0]?.id || "");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [kind, query, selectedId, workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const selected = useMemo(() => rows.find((row) => row.id === selectedId) || null, [rows, selectedId]);
  const kinds = useMemo(() => Array.from(new Set(rows.map((row) => String(row.kind || "").trim()).filter(Boolean))).sort(), [rows]);

  const install = async () => {
    if (!workspaceId || !selected) return;
    try {
      setInstalling(true);
      setError(null);
      setMessage(null);
      await installWorkspaceArtifact(workspaceId, { artifact_id: selected.slug || selected.id, enabled: true });
      setMessage(`Installed "${selected.title}" to workspace ${workspaceName || workspaceId}.`);
      window.dispatchEvent(new Event("xyn:workspace-artifacts-changed"));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setInstalling(false);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Catalog</h2>
          <p className="muted">Global artifact definitions. Install into the active workspace.</p>
        </div>
        <div className="inline-actions">
          <input
            className="input"
            placeholder="Search catalog"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="Search catalog"
          />
          <select value={kind} onChange={(event) => setKind(event.target.value)} aria-label="Filter by kind">
            <option value="">All kinds</option>
            {kinds.map((entry) => (
              <option key={entry} value={entry}>
                {entry}
              </option>
            ))}
          </select>
          <button className="ghost" onClick={() => void load()} disabled={loading}>
            Refresh
          </button>
        </div>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {message && <InlineMessage tone="info" title="Catalog update" body={message} />}

      <div className="layout">
        <section className="card">
          <div className="card-header">
            <h3>Artifacts</h3>
          </div>
          <div className="instance-list" role="table" aria-label="Catalog artifacts">
            {rows.map((artifact) => (
              <button
                key={artifact.id}
                type="button"
                className={`instance-row ${artifact.id === selectedId ? "active" : ""}`}
                onClick={() => setSelectedId(artifact.id)}
              >
                <div>
                  <strong>{artifact.title}</strong>
                  <span className="muted small">{artifact.kind || "-"} · v{artifact.version || "-"}</span>
                </div>
                <div className="muted small">{formatDate(artifact.updated_at)}</div>
              </button>
            ))}
            {!loading && rows.length === 0 && <p className="muted">No catalog artifacts matched your filters.</p>}
          </div>
        </section>

        <section className="card">
          <div className="card-header">
            <h3>Details</h3>
          </div>
          {!selected ? (
            <p className="muted">Select a catalog artifact.</p>
          ) : (
            <>
              <p>
                <strong>{selected.title}</strong>
              </p>
              <p className="muted small">{selected.description || "No description provided."}</p>
              <p className="muted small">
                Kind: {selected.kind || "-"} · Version: {selected.version || "-"} · Updated: {formatDate(selected.updated_at)}
              </p>
              <p className="muted small">Slug: {selected.slug || "-"}</p>

              <h4>Roles</h4>
              <p className="muted small">{selected.manifest_summary?.roles?.length ? selected.manifest_summary.roles.join(", ") : "None declared"}</p>
              <p className="muted small">UI mount scope: {selected.manifest_summary?.ui_mount_scope || "workspace"}</p>

              <h4>Surfaces</h4>
              <p className="muted small">
                nav: {selected.manifest_summary?.surfaces?.nav?.length || 0} · manage: {selected.manifest_summary?.surfaces?.manage?.length || 0} · docs:{" "}
                {selected.manifest_summary?.surfaces?.docs?.length || 0}
              </p>
              {(selected.manifest_summary?.surfaces?.docs?.length || 0) > 0 && (
                <p className="muted small">
                  Docs:{" "}
                  {selected.manifest_summary.surfaces.docs.map((entry) => (
                    <a key={`${entry.path}-${entry.label}`} href={entry.path} style={{ marginRight: 8 }}>
                      {entry.label}
                    </a>
                  ))}
                </p>
              )}
              <pre className="code-block">{JSON.stringify(selected.manifest_summary?.surfaces || {}, null, 2)}</pre>

              <div className="inline-actions">
                <button className="primary" onClick={() => void install()} disabled={installing || !workspaceId}>
                  {installing ? "Installing..." : `Install to Workspace: ${workspaceName || workspaceId}`}
                </button>
                <button className="ghost" onClick={() => navigate(toWorkspacePath(workspaceId, "build/artifacts"))} disabled={!workspaceId}>
                  View Installed
                </button>
              </div>
            </>
          )}
        </section>
      </div>
    </>
  );
}
