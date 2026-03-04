import { useCallback, useEffect, useState } from "react";
import InlineMessage from "../../components/InlineMessage";
import { listSecretRefs } from "../../api/xyn";
import type { SecretRefMetadata } from "../../api/types";

export default function SecretRefsPage() {
  const [items, setItems] = useState<SecretRefMetadata[]>([]);
  const [scopeKind, setScopeKind] = useState<string>("");
  const [scopeId, setScopeId] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await listSecretRefs({
        scope_kind: scopeKind || undefined,
        scope_id: scopeId || undefined,
      });
      setItems(data.secret_refs);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [scopeKind, scopeId]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Secret Refs</h2>
          <p className="muted">Metadata only. Secret values are never returned.</p>
        </div>
        <div className="inline-actions">
          <select value={scopeKind} onChange={(event) => setScopeKind(event.target.value)}>
            <option value="">All scopes</option>
            <option value="platform">platform</option>
            <option value="tenant">tenant</option>
            <option value="user">user</option>
            <option value="team">team</option>
          </select>
          <input
            className="input"
            placeholder="Scope ID"
            value={scopeId}
            onChange={(event) => setScopeId(event.target.value)}
          />
          <button className="ghost" onClick={load} disabled={loading}>
            Refresh
          </button>
        </div>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}

      <section className="card">
        <div className="card-header">
          <h3>Secret references</h3>
          <span className="muted">{items.length} item(s)</span>
        </div>
        {items.length === 0 ? (
          <p className="muted">No secret refs found for the selected scope.</p>
        ) : (
          <div className="table">
            <div className="table-row table-head" style={{ gridTemplateColumns: "180px 80px 1fr 160px 1fr 160px" }}>
              <span>Name</span>
              <span>Scope</span>
              <span>Scope ID</span>
              <span>Store</span>
              <span>External ref</span>
              <span>Updated</span>
            </div>
            {items.map((item) => (
              <div key={item.id} className="table-row" style={{ gridTemplateColumns: "180px 80px 1fr 160px 1fr 160px" }}>
                <span>{item.name}</span>
                <span>{item.scope_kind}</span>
                <span className="muted">{item.scope_id || "—"}</span>
                <span>{item.store_name || item.store_id}</span>
                <span className="muted">{item.external_ref}</span>
                <span className="muted">{item.updated_at || "—"}</span>
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  );
}
