import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import { createArticle, listArticles } from "../../api/xyn";
import type { ArticleSummary } from "../../api/types";

export default function ArtifactsPage({ workspaceId }: { workspaceId: string }) {
  const [items, setItems] = useState<ArticleSummary[]>([]);
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState<"web" | "guide" | "core-concepts" | "release-note" | "internal" | "tutorial">("web");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!workspaceId) {
      setItems([]);
      return;
    }
    try {
      setError(null);
      const data = await listArticles({ workspace_id: workspaceId, include_unpublished: true });
      setItems(data.articles || []);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [workspaceId]);

  useEffect(() => {
    load();
  }, [load]);

  const createDraft = async () => {
    if (!title.trim()) return;
    try {
      setLoading(true);
      setError(null);
      await createArticle({ workspace_id: workspaceId, title, category, visibility_type: "private", body_markdown: "" });
      setTitle("");
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
          <h2>Artifacts</h2>
          <p className="muted">Governed artifacts in this workspace.</p>
        </div>
      </div>
      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      <section className="card">
        <div className="form-grid">
          <label>
            New Article Draft
            <input className="input" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Title" />
          </label>
          <label>
            Category
            <select value={category} onChange={(event) => setCategory(event.target.value as typeof category)}>
              <option value="web">web</option>
              <option value="guide">guide</option>
              <option value="core-concepts">core-concepts</option>
              <option value="release-note">release-note</option>
              <option value="internal">internal</option>
              <option value="tutorial">tutorial</option>
            </select>
          </label>
          <button className="primary" onClick={createDraft} disabled={loading || !title.trim()}>
            Create draft
          </button>
        </div>
      </section>
      <section className="card">
        <div className="card-header">
          <h3>Articles</h3>
        </div>
        <div className="instance-list">
          {items.map((item) => (
            <Link className="instance-row" key={item.id} to={`/app/artifacts/${item.id}`}>
              <div>
                <strong>{item.title}</strong>
                <span className="muted small">
                  {item.slug || item.id} · {item.category} · {item.visibility_type}
                </span>
              </div>
              <div className="muted small">{item.status}</div>
            </Link>
          ))}
          {items.length === 0 && <p className="muted">No artifacts yet.</p>}
        </div>
      </section>
    </>
  );
}
