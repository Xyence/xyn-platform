import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import { getRun, getRunArtifacts, getRunCommands, getRunLogs, listRuns } from "../../api/xyn";
import { fetchArtifactJson } from "../../api/client";
import type { RunArtifact, RunCommandExecution, RunDetail, RunSummary } from "../../api/types";
import StatusPill from "../../components/StatusPill";

const ENTITY_OPTIONS = ["", "blueprint", "registry", "module", "release_plan", "dev_task"];
const STATUS_OPTIONS = ["", "pending", "running", "succeeded", "failed"];
const formatContextPackRef = (ref: unknown) => {
  if (typeof ref === "string") {
    return { key: ref, label: ref };
  }
  if (ref && typeof ref === "object") {
    const obj = ref as Record<string, unknown>;
    const name = typeof obj.name === "string" ? obj.name : "";
    const id = typeof obj.id === "string" ? obj.id : "";
    const purpose = typeof obj.purpose === "string" ? obj.purpose : "";
    const scope = typeof obj.scope === "string" ? obj.scope : "";
    const version = typeof obj.version === "string" ? obj.version : "";
    const contentHash = typeof obj.content_hash === "string" ? obj.content_hash : "";
    const parts = [name || id, purpose, scope, version].filter(Boolean);
    const label = parts.length > 0 ? parts.join(" · ") : contentHash || JSON.stringify(obj);
    const key = id || name || label;
    return { key, label };
  }
  const label = String(ref ?? "");
  return { key: label || "context-pack", label: label || "unknown" };
};
const formatRelativeTime = (value?: string | null) => {
  if (!value) return "";
  const then = new Date(value).getTime();
  if (!Number.isFinite(then)) return "";
  const diffMs = Date.now() - then;
  if (diffMs < 0) return "just now";
  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} d ago`;
  const weeks = Math.floor(days / 7);
  if (weeks < 5) return `${weeks} w ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months} mo ago`;
  const years = Math.floor(days / 365);
  return `${years} yr ago`;
};

export default function RunsPage() {
  const [items, setItems] = useState<RunSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<RunDetail | null>(null);
  const [logs, setLogs] = useState<string | null>(null);
  const [artifacts, setArtifacts] = useState<RunArtifact[]>([]);
  const [commands, setCommands] = useState<RunCommandExecution[]>([]);
  const [imageArtifacts, setImageArtifacts] = useState<{
    releaseManifest?: Record<string, { image_uri?: string; digest?: string }>;
    buildImages?: Array<{ name: string; image_uri: string; digest?: string; tag?: string }>;
  }>({});
  const [entityFilter, setEntityFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [totalCount, setTotalCount] = useState(0);
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [prevPage, setPrevPage] = useState<number | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const runParam = searchParams.get("run");
  const filterPreset = searchParams.get("filter");

  const load = useCallback(async () => {
    try {
      setError(null);
      const data = await listRuns(
        entityFilter || undefined,
        statusFilter || undefined,
        query || undefined,
        page,
        pageSize
      );
      setItems(data.runs);
      setTotalCount(data.count ?? 0);
      setNextPage(data.next ?? null);
      setPrevPage(data.prev ?? null);
      if (!selectedId && data.runs[0]) {
        setSelectedId(data.runs[0].id);
      }
    } catch (err) {
      setError((err as Error).message);
    }
  }, [entityFilter, statusFilter, selectedId, query, page, pageSize]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (runParam) {
      setSelectedId(runParam);
    }
  }, [runParam]);

  useEffect(() => {
    if (filterPreset === "dev_task" && entityFilter !== "dev_task") {
      setEntityFilter("dev_task");
      setPage(1);
    }
  }, [entityFilter, filterPreset]);

  useEffect(() => {
    setPage(1);
  }, [entityFilter, statusFilter]);

  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      setLogs(null);
      setArtifacts([]);
      setCommands([]);
      setImageArtifacts({});
      return;
    }
    (async () => {
      try {
        const detail = await getRun(selectedId);
        setSelected(detail);
        const log = await getRunLogs(selectedId);
        setLogs(log.log ?? "");
        const artifactList = await getRunArtifacts(selectedId);
        setArtifacts(artifactList);
        const commandList = await getRunCommands(selectedId);
        setCommands(commandList);
      } catch (err) {
        setError((err as Error).message);
      }
    })();
  }, [selectedId]);

  useEffect(() => {
    if (!selected || artifacts.length === 0) return;
    (async () => {
      const manifest = artifacts.find((item) => item.name === "release_manifest.json");
      const buildResult = artifacts.find((item) => item.name === "build_result.json");
      const nextArtifacts: {
        releaseManifest?: Record<string, { image_uri?: string; digest?: string }>;
        buildImages?: Array<{ name: string; image_uri: string; digest?: string; tag?: string }>;
      } = {};
      try {
        if (manifest?.url) {
          const payload = await fetchArtifactJson<{ images?: Record<string, { image_uri?: string; digest?: string }> }>(
            manifest.url
          );
          if (payload?.images) {
            nextArtifacts.releaseManifest = payload.images;
          }
        }
        if (buildResult?.url) {
          const payload = await fetchArtifactJson<{ images?: Array<{ name: string; image_uri: string; digest?: string; tag?: string }> }>(
            buildResult.url
          );
          if (payload?.images) {
            nextArtifacts.buildImages = payload.images;
          }
        }
        setImageArtifacts(nextArtifacts);
      } catch {
        setImageArtifacts({});
      }
    })();
  }, [artifacts, selected]);

  useEffect(() => {
    if (!autoRefresh || !selectedId) return;
    const interval = setInterval(async () => {
      try {
        await load();
        const detail = await getRun(selectedId);
        setSelected(detail);
        const log = await getRunLogs(selectedId);
        setLogs(log.log ?? "");
        const artifactList = await getRunArtifacts(selectedId);
        setArtifacts(artifactList);
        const commandList = await getRunCommands(selectedId);
        setCommands(commandList);
      } catch (err) {
        setError((err as Error).message);
      }
    }, 5000);
    return () => clearInterval(interval);
  }, [autoRefresh, selectedId, load]);

  const handleRefresh = async () => {
    try {
      setLoading(true);
      setMessage(null);
      await load();
      if (selectedId) {
        const detail = await getRun(selectedId);
        setSelected(detail);
        const log = await getRunLogs(selectedId);
        setLogs(log.log ?? "");
        const artifactList = await getRunArtifacts(selectedId);
        setArtifacts(artifactList);
      }
      setMessage("Runs refreshed.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Runs</h2>
          <p className="muted">Inspect submission runs and artifacts.</p>
        </div>
        <div className="inline-actions">
          <label className="muted small">Entity</label>
          <select
            value={entityFilter}
            onChange={(event) => {
              const next = event.target.value;
              setEntityFilter(next);
              const params = new URLSearchParams(searchParams);
              if (next === "dev_task") params.set("filter", "dev_task");
              else params.delete("filter");
              setSearchParams(params, { replace: true });
            }}
          >
            {ENTITY_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>
                {opt || "All"}
              </option>
            ))}
          </select>
          <button
            className={entityFilter === "dev_task" ? "primary" : "ghost"}
            onClick={() => {
              setEntityFilter("dev_task");
              setPage(1);
              const params = new URLSearchParams(searchParams);
              params.set("filter", "dev_task");
              setSearchParams(params, { replace: true });
            }}
          >
            Dev Tasks
          </button>
          <button
            className={!entityFilter ? "primary" : "ghost"}
            onClick={() => {
              setEntityFilter("");
              setPage(1);
              const params = new URLSearchParams(searchParams);
              params.delete("filter");
              setSearchParams(params, { replace: true });
            }}
          >
            All Runs
          </button>
          <label className="muted small">Status</label>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            {STATUS_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>
                {opt || "All"}
              </option>
            ))}
          </select>
          <label className="muted small">Search</label>
          <input
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setPage(1);
            }}
            placeholder="Search runs..."
          />
          <label className="muted small">Page size</label>
          <select
            value={pageSize}
            onChange={(event) => {
              setPageSize(Number(event.target.value));
              setPage(1);
            }}
          >
            {[25, 50, 100].map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
          <label className="muted small">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(event) => setAutoRefresh(event.target.checked)}
            />
            Auto-refresh
          </label>
          <button className="ghost" onClick={handleRefresh} disabled={loading}>
            Refresh
          </button>
        </div>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {message && <InlineMessage tone="info" title="Update" body={message} />}

      <div className="layout">
        <section className="card">
          <div className="card-header">
            <h3>Runs</h3>
          </div>
          <div className="instance-list">
            {items.map((item) => (
              <button
                key={item.id}
                className={`instance-row ${selectedId === item.id ? "active" : ""}`}
                onClick={() => {
                  setSelectedId(item.id);
                  setSearchParams({ run: item.id });
                }}
              >
                <div>
                  <strong>{item.entity_type}</strong>
                  <span className="muted small">{item.entity_id}</span>
                  {item.summary && <span className="muted small">{item.summary}</span>}
                  {item.created_at && (
                    <span className="muted small"> · {formatRelativeTime(item.created_at)}</span>
                  )}
                </div>
                <StatusPill status={item.status} />
              </button>
            ))}
            {items.length === 0 && <p className="muted">No runs yet.</p>}
          </div>
          <div className="form-actions">
            <button
              className="ghost"
              onClick={() => setPage(prevPage ?? 1)}
              disabled={!prevPage}
            >
              Prev
            </button>
            <span className="muted small">
              Page {page} · {totalCount} total
            </span>
            <button
              className="ghost"
              onClick={() => setPage(nextPage ?? page)}
              disabled={!nextPage}
            >
              Next
            </button>
          </div>
        </section>

        <section className="card">
          <div className="card-header">
            <h3>Run detail</h3>
          </div>
          {!selected ? (
            <p className="muted">Select a run to see detail.</p>
          ) : (
            <>
              <div className="detail-grid">
                <div>
                  <div className="label">Entity</div>
                  <strong>{selected.entity_type}</strong>
                </div>
                <div>
                  <div className="label">Status</div>
                  <StatusPill status={selected.status} />
                </div>
                <div>
                  <div className="label">Summary</div>
                  <span className="muted">{selected.summary ?? "—"}</span>
                </div>
                <div>
                  <div className="label">Started</div>
                  <span className="muted">{selected.started_at ?? "—"}</span>
                </div>
                <div>
                  <div className="label">Finished</div>
                  <span className="muted">{selected.finished_at ?? "—"}</span>
                </div>
              </div>
              {selected.error && <InlineMessage tone="error" title="Run error" body={selected.error} />}
              {selected.log_text && (
                <div className="stack">
                  <strong>Run log</strong>
                  <pre className="code-block">{selected.log_text}</pre>
                </div>
              )}
              {selected.context_pack_refs && selected.context_pack_refs.length > 0 && (
                <div className="stack">
                  <strong>Context packs</strong>
                  {selected.context_pack_refs.map((ref, index) => {
                    const formatted = formatContextPackRef(ref);
                    return (
                      <div key={`${formatted.key}-${index}`} className="item-row">
                        <span className="muted">{formatted.label}</span>
                      </div>
                    );
                  })}
                </div>
              )}
              {(imageArtifacts.releaseManifest || imageArtifacts.buildImages) && (
                <div className="stack">
                  <strong>Image artifacts</strong>
                  {imageArtifacts.buildImages && imageArtifacts.buildImages.length > 0 && (
                    <div className="stack">
                      <div className="label">Build result</div>
                      {imageArtifacts.buildImages.map((img) => (
                        <div key={`${img.name}-${img.image_uri}`} className="item-row">
                          <div>
                            <strong>{img.name}</strong>
                            <span className="muted small">{img.image_uri}</span>
                          </div>
                          <span className="muted small">{img.digest ?? img.tag ?? "—"}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {imageArtifacts.releaseManifest && (
                    <div className="stack">
                      <div className="label">Release manifest</div>
                      {Object.entries(imageArtifacts.releaseManifest).map(([service, info]) => (
                        <div key={service} className="item-row">
                          <div>
                            <strong>{service}</strong>
                            <span className="muted small">{info.image_uri ?? "—"}</span>
                          </div>
                          <span className="muted small">{info.digest ?? "—"}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </section>

        <section className="card">
          <div className="card-header">
            <h3>Logs</h3>
          </div>
          {logs ? (
            <div className="log-box">
              <pre>{logs}</pre>
            </div>
          ) : (
            <p className="muted">No logs captured.</p>
          )}
        </section>

        <section className="card">
          <div className="card-header">
            <h3>Command executions</h3>
          </div>
          {commands.length === 0 ? (
            <p className="muted">No command executions recorded.</p>
          ) : (
            <div className="stack">
              {commands.map((cmd) => (
                <div key={cmd.id} className="item-row">
                  <div>
                    <strong>{cmd.step_name || "step"}</strong>
                    <span className="muted small">
                      #{cmd.command_index} · {cmd.shell} · {cmd.status}
                    </span>
                  </div>
                  <div className="muted small">exit {cmd.exit_code ?? "—"}</div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="card" data-tour="run-artifacts" data-testid="run-artifacts">
          <div className="card-header">
            <h3>Artifacts</h3>
          </div>
          {artifacts.length === 0 ? (
            <p className="muted">No artifacts recorded.</p>
          ) : (
            <div className="stack">
              {artifacts.map((artifact) => (
                <div key={artifact.id} className="item-row">
                  <div>
                    <strong>{artifact.name}</strong>
                    <span className="muted small">{artifact.kind}</span>
                  </div>
                  {artifact.url && (
                    <a className="muted small" href={artifact.url} target="_blank" rel="noreferrer">
                      Open
                    </a>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </>
  );
}
