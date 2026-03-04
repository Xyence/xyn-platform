import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import { listTenants } from "../../api/xyn";
import type { Tenant } from "../../api/types";

export default function MyTenantsPage() {
  const [items, setItems] = useState<Tenant[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const data = await listTenants();
      setItems(data.tenants);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <>
      <div className="page-header">
        <div>
          <h2>My Tenants</h2>
          <p className="muted">Tenants you have access to.</p>
        </div>
        <button className="ghost" onClick={load}>
          Refresh
        </button>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}

      <section className="card">
        <div className="card-header">
          <h3>Tenants</h3>
        </div>
        <div className="instance-list">
          {items.map((item) => (
            <div key={item.id} className="instance-row">
              <div>
                <strong>{item.name}</strong>
                <span className="muted small">{item.slug}</span>
              </div>
              <span className="muted small">{(item as Tenant & { membership_role?: string }).membership_role || ""}</span>
              <Link className="ghost" to={`/app/tenants/${item.id}`}>
                View contacts
              </Link>
            </div>
          ))}
          {items.length === 0 && <p className="muted">No tenant access assigned.</p>}
        </div>
      </section>
    </>
  );
}
