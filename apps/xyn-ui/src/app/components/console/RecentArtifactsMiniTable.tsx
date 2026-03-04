import type { KeyboardEvent } from "react";
import type { RecentArtifactItem } from "../../../api/types";

function formatType(value: string): string {
  const key = String(value || "").toLowerCase();
  if (key === "draft_session") return "Draft";
  if (key === "blueprint") return "Blueprint";
  if (key === "article") return "Article";
  if (key === "workflow") return "Workflow";
  if (key === "module") return "Module";
  if (key === "context_pack") return "Context Pack";
  return value || "Artifact";
}

function formatRelativeTime(value?: string): string {
  if (!value) return "—";
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return "—";
  const delta = Date.now() - timestamp;
  const seconds = Math.max(0, Math.round(delta / 1000));
  if (seconds < 60) return "now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo ago`;
  const years = Math.floor(months / 12);
  return `${years}y ago`;
}

export default function RecentArtifactsMiniTable({
  items,
  loading,
  compact,
  maxItems,
  showDeprecatedArticles,
  onOpen,
  onShowMore,
  onRefresh,
  onToggleShowDeprecatedArticles,
  onInsertSuggestion,
}: {
  items: RecentArtifactItem[];
  loading: boolean;
  compact?: boolean;
  maxItems?: number;
  showDeprecatedArticles: boolean;
  onOpen: (item: RecentArtifactItem) => void;
  onShowMore: () => void;
  onRefresh: () => void;
  onToggleShowDeprecatedArticles: (checked: boolean) => void;
  onInsertSuggestion: (text: string) => void;
}) {
  const handleRowKey = (event: KeyboardEvent<HTMLButtonElement>, item: RecentArtifactItem) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onOpen(item);
    }
  };

  const targetSize = typeof maxItems === "number" ? maxItems : compact ? 3 : 8;
  const visibleItems = items.slice(0, Math.max(1, targetSize));

  return (
    <section className={`xyn-console-card xyn-console-recent ${compact ? "compact" : ""}`} aria-label="Recent artifacts">
      <div className="xyn-console-card-head">
        <strong>Recent</strong>
        <div className="inline-actions">
          <label className="muted small xyn-console-recent-toggle">
            <input
              type="checkbox"
              checked={showDeprecatedArticles}
              onChange={(event) => onToggleShowDeprecatedArticles(event.target.checked)}
            />{" "}
            Show deprecated
          </label>
          <button type="button" className="ghost sm" onClick={onShowMore}>
            Show more
          </button>
          <button type="button" className="ghost sm" onClick={onRefresh} disabled={loading}>
            {loading ? "…" : "Refresh"}
          </button>
        </div>
      </div>
      {visibleItems.length ? (
        <div className="xyn-console-recent-list" role="list" aria-label="Recent artifacts">
          {visibleItems.map((item) => (
            <button
              key={`${item.artifact_id}:${item.updated_at || ""}`}
              type="button"
              role="listitem"
              className="xyn-console-recent-row"
              onClick={() => onOpen(item)}
              onKeyDown={(event) => handleRowKey(event, item)}
              title={item.title}
            >
              <span className="xyn-console-recent-title">
                {item.title}
              </span>
              <span className="xyn-console-recent-type muted small">
                {formatType(item.artifact_type)}
              </span>
              <span className="xyn-console-recent-updated muted small" title={item.updated_at ? new Date(item.updated_at).toLocaleString() : ""}>
                {formatRelativeTime(item.updated_at)}
              </span>
            </button>
          ))}
        </div>
      ) : (
        <div className="stack">
          <p className="muted small">No recent artifacts yet. Try: “Create an explainer video about …”</p>
          <div className="xyn-console-options-list">
            <button type="button" className="ghost sm" onClick={() => onInsertSuggestion("Create an explainer video about ...")}>
              Create an explainer video about …
            </button>
            <button type="button" className="ghost sm" onClick={() => onInsertSuggestion("Create a guide about ...")}>
              Create a guide about …
            </button>
            <button type="button" className="ghost sm" onClick={() => onInsertSuggestion("Open my latest draft")}>
              Open my latest draft
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
