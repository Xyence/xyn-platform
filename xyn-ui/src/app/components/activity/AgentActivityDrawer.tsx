import { useEffect, useMemo, useState } from "react";
import { Bot, RefreshCw, X } from "lucide-react";
import { listAiActivity } from "../../../api/xyn";
import type { AiActivityEntry } from "../../../api/types";
import { useOperations } from "../../state/operationRegistry";

type Props = {
  open: boolean;
  onClose: () => void;
  workspaceId?: string;
  artifactId?: string;
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

export default function AgentActivityDrawer({ open, onClose, workspaceId, artifactId }: Props) {
  const [items, setItems] = useState<AiActivityEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [artifactOnly, setArtifactOnly] = useState(Boolean(artifactId));
  const { operations } = useOperations();

  useEffect(() => {
    setArtifactOnly(Boolean(artifactId));
  }, [artifactId]);

  const load = async () => {
    if (!workspaceId) {
      setItems([]);
      return;
    }
    try {
      setError(null);
      setLoading(true);
      const result = await listAiActivity({
        workspaceId,
        artifactId: artifactOnly ? artifactId : undefined,
      });
      setItems(result.items || []);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    void load();
  }, [open, workspaceId, artifactId, artifactOnly]);

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
            <article key={item.id} className="notification-item">
              <span className={`notification-icon ${item.status === "failed" ? "error" : item.status === "succeeded" ? "success" : "info"}`}>
                <Bot size={15} />
              </span>
              <div className="notification-text">
                <strong>{item.summary || item.event_type}</strong>
                <span className="muted small">
                  {item.provider} · {item.model_name} · {item.agent_slug}
                </span>
                <span className="muted small">
                  {item.artifact_type || "artifact"} {item.artifact_id || "—"} · {item.status} · {relativeTime(item.created_at)}
                </span>
              </div>
            </article>
          ))}
          {badgeCount > 0 && <p className="muted small">{badgeCount} running operation(s).</p>}
        </div>
      </aside>
    </>
  );
}
