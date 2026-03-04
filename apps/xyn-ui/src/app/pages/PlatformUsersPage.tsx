import { useCallback, useEffect, useState } from "react";
import InlineMessage from "../../components/InlineMessage";
import { listIdentities } from "../../api/xyn";
import type { IdentitySummary } from "../../api/types";

export default function PlatformUsersPage() {
  const [items, setItems] = useState<IdentitySummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await listIdentities();
      setItems(data.identities);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Users</h2>
          <p className="muted">Platform identities authenticated via OIDC.</p>
        </div>
        <button className="ghost" onClick={load} disabled={loading}>
          Refresh
        </button>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}

      <section className="card">
        <div className="card-header">
          <h3>Identities</h3>
        </div>
        <div className="instance-list">
          {items.map((item) => (
            <div key={item.id} className="instance-row">
              <div>
                <strong>{item.display_name || item.email || item.subject}</strong>
                <span className="muted small">{item.email || item.subject}</span>
                <span className="muted small">
                  Identity provider:{" "}
                  {item.provider_display_name
                    ? `${item.provider_display_name}${item.provider_id ? ` (${item.provider_id})` : ""}`
                    : item.provider_id || item.provider || item.issuer}
                </span>
              </div>
              <span className="muted small">{item.last_login_at || "never"}</span>
            </div>
          ))}
          {items.length === 0 && <p className="muted">No identities yet.</p>}
        </div>
      </section>
    </>
  );
}
