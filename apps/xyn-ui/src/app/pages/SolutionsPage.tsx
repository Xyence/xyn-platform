import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { listApplications } from "../../api/xyn";
import type { ApplicationSummary } from "../../api/types";

type SolutionsPageProps = {
  workspaceId: string;
  workspaceName: string;
};

export default function SolutionsPage({ workspaceId, workspaceName }: SolutionsPageProps) {
  const [items, setItems] = useState<ApplicationSummary[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    let ignore = false;
    async function run() {
      if (!workspaceId) {
        setItems([]);
        setLoading(false);
        return;
      }
      setLoading(true);
      setError("");
      try {
        const payload = await listApplications(workspaceId);
        if (!ignore) setItems(payload.applications || []);
      } catch (err) {
        if (!ignore) setError(err instanceof Error ? err.message : "Failed to load solutions.");
      } finally {
        if (!ignore) setLoading(false);
      }
    }
    void run();
    return () => {
      ignore = true;
    };
  }, [workspaceId]);

  const sorted = useMemo(
    () => [...items].sort((a, b) => (a.updated_at > b.updated_at ? -1 : 1)),
    [items]
  );

  return (
    <div className="stack">
      <section className="card">
        <h2>Solutions</h2>
        <p className="muted">
          Multi-artifact development groups for <strong>{workspaceName || "this workspace"}</strong>.
        </p>
      </section>
      <section className="card">
        {loading ? <p className="muted">Loading solutions…</p> : null}
        {!loading && error ? <p className="muted">{error}</p> : null}
        {!loading && !error && sorted.length === 0 ? (
          <p className="muted">No solutions have been registered yet.</p>
        ) : null}
        {!loading && !error && sorted.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Status</th>
                  <th>Goals</th>
                  <th>Artifacts</th>
                  <th>Updated</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {sorted.map((item) => (
                  <tr key={item.id}>
                    <td>{item.name}</td>
                    <td>{item.status}</td>
                    <td>{item.goal_count || 0}</td>
                    <td>{item.artifact_member_count || 0}</td>
                    <td>{item.updated_at ? new Date(item.updated_at).toLocaleString() : "—"}</td>
                    <td>
                      <Link className="ghost sm" to={`/w/${encodeURIComponent(workspaceId)}/solutions/${encodeURIComponent(item.id)}`}>
                        Open
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </div>
  );
}

