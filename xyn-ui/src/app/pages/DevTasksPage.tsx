import { useCallback, useEffect, useState } from "react";
import InlineMessage from "../../components/InlineMessage";
import StatusPill from "../../components/StatusPill";
import { cancelDevTask, getDevTask, listDevTasks, retryDevTask, runDevTask } from "../../api/xyn";
import type { DevTaskDetail, DevTaskSummary } from "../../api/types";

const STATUS_OPTIONS = ["", "queued", "running", "succeeded", "failed", "canceled"];
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

export default function DevTasksPage() {
  const [items, setItems] = useState<DevTaskSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<DevTaskDetail | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [totalCount, setTotalCount] = useState(0);
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [prevPage, setPrevPage] = useState<number | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    try {
      setError(null);
      const data = await listDevTasks(statusFilter || undefined, query || undefined, page, pageSize);
      setItems(data.dev_tasks);
      setTotalCount(data.count ?? 0);
      setNextPage(data.next ?? null);
      setPrevPage(data.prev ?? null);
      if (!selectedId && data.dev_tasks[0]) {
        setSelectedId(data.dev_tasks[0].id);
      }
    } catch (err) {
      setError((err as Error).message);
    }
  }, [selectedId, statusFilter, query, page, pageSize]);

  const loadSelected = useCallback(async () => {
    if (!selectedId) {
      setSelected(null);
      return;
    }
    try {
      const detail = await getDevTask(selectedId);
      setSelected(detail);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [selectedId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    setPage(1);
  }, [statusFilter, query]);

  useEffect(() => {
    loadSelected();
  }, [loadSelected]);

  useEffect(() => {
    if (!autoRefresh) return;
    const interval = window.setInterval(async () => {
      await load();
      await loadSelected();
    }, 5000);
    return () => window.clearInterval(interval);
  }, [autoRefresh, load, loadSelected]);

  const handleRefresh = async () => {
    try {
      setLoading(true);
      setError(null);
      await load();
      await loadSelected();
      setMessage("Dev tasks refreshed.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleRun = async () => {
    if (!selectedId) return;
    try {
      setLoading(true);
      setError(null);
      const result = await runDevTask(selectedId);
      setMessage(`Run queued: ${result.run_id}`);
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = async () => {
    if (!selectedId) return;
    try {
      setLoading(true);
      setError(null);
      await cancelDevTask(selectedId);
      setMessage("Task canceled.");
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleRetry = async () => {
    if (!selectedId) return;
    try {
      setLoading(true);
      setError(null);
      const result = await retryDevTask(selectedId);
      setMessage(`Retry queued: ${result.run_id}`);
      await load();
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
          <h2>Dev Tasks</h2>
          <p className="muted">Queued and running development tasks.</p>
        </div>
        <div className="inline-actions">
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
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search tasks..."
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
            <h3>Tasks</h3>
          </div>
          <div className="instance-list">
            {items.map((item) => (
              <button
                key={item.id}
                className={`instance-row ${selectedId === item.id ? "active" : ""}`}
                onClick={() => setSelectedId(item.id)}
              >
                <div>
                  <strong>{item.title}</strong>
                  <span className="muted small">{item.task_type}</span>
                  {item.created_at && (
                    <span className="muted small"> · {formatRelativeTime(item.created_at)}</span>
                  )}
                </div>
                <StatusPill status={item.status} />
              </button>
            ))}
            {items.length === 0 && <p className="muted">No dev tasks found.</p>}
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
            <h3>Task detail</h3>
          </div>
          {!selected ? (
            <p className="muted">Select a task to inspect.</p>
          ) : (
            <>
              <div className="detail-grid">
                <div>
                  <div className="label">Task type</div>
                  <strong>{selected.task_type}</strong>
                </div>
                <div>
                  <div className="label">Status</div>
                  <StatusPill status={selected.status} />
                </div>
                <div>
                  <div className="label">Target instance</div>
                  <span className="muted">{selected.target_instance_id ?? "—"}</span>
                </div>
                <div>
                  <div className="label">Attempts</div>
                  <span className="muted">
                    {selected.attempts}/{selected.max_attempts}
                  </span>
                </div>
                <div>
                  <div className="label">Context purpose</div>
                  <span className="muted">{selected.context_purpose}</span>
                </div>
                <div>
                  <div className="label">Result run</div>
                  {selected.result_run ? (
                    <a className="link" href={`/app/runs?run=${selected.result_run}`}>
                      {selected.result_run}
                    </a>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </div>
              </div>
              {selected.last_error && (
                <InlineMessage tone="error" title="Last error" body={selected.last_error} />
              )}
              {selected.result_run_detail?.error && (
                <InlineMessage tone="error" title="Run error" body={selected.result_run_detail.error} />
              )}
              <div className="form-actions">
                <button className="primary" onClick={handleRun} disabled={loading}>
                  Run task
                </button>
                <button
                  className="ghost"
                  onClick={handleRetry}
                  disabled={loading || !["failed", "canceled"].includes(selected.status)}
                >
                  Retry
                </button>
                <button className="danger" onClick={handleCancel} disabled={loading}>
                  Cancel
                </button>
              </div>
              <div className="stack">
                <strong>Context packs</strong>
                {(selected.context_packs || []).map((pack) => (
                  <div key={pack.id} className="item-row">
                    <div>
                      <strong>{pack.name}</strong>
                      <span className="muted small">
                        {pack.purpose} · {pack.scope} · {pack.version}
                      </span>
                    </div>
                  </div>
                ))}
                {(selected.context_packs || []).length === 0 && (
                  <span className="muted">No context packs attached.</span>
                )}
              </div>
              {selected.result_run_detail && (
                <div className="stack">
                  <strong>Run detail</strong>
                  <div className="detail-grid">
                    <div>
                      <div className="label">Run status</div>
                      <span className="muted">{selected.result_run_detail.status ?? "—"}</span>
                    </div>
                    <div>
                      <div className="label">Run summary</div>
                      <span className="muted">{selected.result_run_detail.summary ?? "—"}</span>
                    </div>
                    <div>
                      <div className="label">Started</div>
                      <span className="muted">{selected.result_run_detail.started_at ?? "—"}</span>
                    </div>
                    <div>
                      <div className="label">Finished</div>
                      <span className="muted">{selected.result_run_detail.finished_at ?? "—"}</span>
                    </div>
                  </div>
                  {selected.result_run_detail.log_text && (
                    <pre className="code-block">{selected.result_run_detail.log_text}</pre>
                  )}
                </div>
              )}
              {selected.result_run_artifacts && selected.result_run_artifacts.length > 0 && (
                <div className="stack">
                  <strong>Artifacts</strong>
                  {selected.result_run_artifacts.map((artifact) => (
                    <div key={artifact.id} className="item-row">
                      <div>
                        <strong>{artifact.name}</strong>
                        <span className="muted small">{artifact.kind ?? "artifact"}</span>
                      </div>
                      {artifact.url ? (
                        <a className="link" href={artifact.url} target="_blank" rel="noreferrer">
                          Open
                        </a>
                      ) : (
                        <span className="muted small">No URL</span>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {selected.result_run_commands && selected.result_run_commands.length > 0 && (
                <div className="stack">
                  <strong>Command executions</strong>
                  {selected.result_run_commands.map((cmd) => (
                    <div key={cmd.id} className="item-row">
                      <div>
                        <strong>
                          {cmd.step_name || "Command"}#{cmd.command_index ?? 0}
                        </strong>
                        <span className="muted small">
                          exit={cmd.exit_code ?? "—"} · {cmd.status ?? "unknown"}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </>
  );
}
