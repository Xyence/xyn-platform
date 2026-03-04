import { useCallback, useEffect, useState } from "react";
import InlineMessage from "../../components/InlineMessage";
import {
  createRegistry,
  deleteRegistry,
  getRegistry,
  listRegistries,
  syncRegistry,
  updateRegistry,
} from "../../api/xyn";
import type { RegistryCreatePayload, RegistryDetail, RegistrySummary } from "../../api/types";

const emptyForm: RegistryCreatePayload = {
  name: "",
  registry_type: "module",
  description: "",
  url: "",
  status: "active",
};

const REGISTRY_TYPES = ["module", "bundle", "blueprint", "release"];

export default function RegistriesPage() {
  const [items, setItems] = useState<RegistrySummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<RegistryDetail | null>(null);
  const [form, setForm] = useState<RegistryCreatePayload>(emptyForm);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const data = await listRegistries();
      setItems(data.registries);
      if (!selectedId && data.registries[0]) {
        setSelectedId(data.registries[0].id);
      }
    } catch (err) {
      setError((err as Error).message);
    }
  }, [selectedId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      return;
    }
    (async () => {
      try {
        const detail = await getRegistry(selectedId);
        setSelected(detail);
        setForm({
          name: detail.name,
          registry_type: detail.registry_type,
          description: detail.description ?? "",
          url: detail.url ?? "",
          status: detail.status,
        });
      } catch (err) {
        setError((err as Error).message);
      }
    })();
  }, [selectedId]);

  const handleCreate = async () => {
    try {
      setLoading(true);
      setError(null);
      setMessage(null);
      await createRegistry(form);
      setForm(emptyForm);
      await load();
      setMessage("Registry created.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleUpdate = async () => {
    if (!selectedId) return;
    try {
      setLoading(true);
      setError(null);
      setMessage(null);
      await updateRegistry(selectedId, form);
      await load();
      setMessage("Registry updated.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedId) return;
    if (!confirm("Delete this registry?")) return;
    try {
      setLoading(true);
      setError(null);
      await deleteRegistry(selectedId);
      setSelectedId(null);
      setSelected(null);
      setForm(emptyForm);
      await load();
      setMessage("Registry deleted.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleSync = async () => {
    if (!selectedId) return;
    try {
      setLoading(true);
      setError(null);
      const result = await syncRegistry(selectedId);
      setMessage(`Registry sync status: ${result.status}`);
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
          <h2>Registries</h2>
          <p className="muted">Track external module, bundle, and release registries.</p>
        </div>
        <button className="ghost" onClick={load} disabled={loading}>
          Refresh
        </button>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {message && <InlineMessage tone="info" title="Update" body={message} />}

      <div className="layout">
        <section className="card">
          <div className="card-header">
            <h3>Registries</h3>
          </div>
          <div className="instance-list">
            {items.map((item) => (
              <button
                key={item.id}
                className={`instance-row ${selectedId === item.id ? "active" : ""}`}
                onClick={() => setSelectedId(item.id)}
              >
                <div>
                  <strong>{item.name}</strong>
                  <span className="muted small">{item.registry_type}</span>
                </div>
                <span className="muted small">{item.status}</span>
              </button>
            ))}
            {items.length === 0 && <p className="muted">No registries yet.</p>}
          </div>
        </section>

        <section className="card">
          <div className="card-header">
            <h3>{selected ? "Registry detail" : "Create registry"}</h3>
          </div>
          <div className="form-grid">
            <label>
              Name
              <input
                value={form.name ?? ""}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
              />
            </label>
            <label>
              Type
              <select
                value={form.registry_type ?? "module"}
                onChange={(event) => setForm({ ...form, registry_type: event.target.value })}
              >
                {REGISTRY_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
            </label>
            <label>
              URL
              <input
                value={form.url ?? ""}
                onChange={(event) => setForm({ ...form, url: event.target.value })}
              />
            </label>
            <label>
              Status
              <input
                value={form.status ?? ""}
                onChange={(event) => setForm({ ...form, status: event.target.value })}
              />
            </label>
            <label>
              Description
              <input
                value={form.description ?? ""}
                onChange={(event) => setForm({ ...form, description: event.target.value })}
              />
            </label>
          </div>
          <div className="form-actions">
            <button className="primary" onClick={selected ? handleUpdate : handleCreate} disabled={loading}>
              {selected ? "Save changes" : "Create"}
            </button>
            {selected && (
              <>
                <button className="ghost" onClick={handleSync} disabled={loading}>
                  Sync
                </button>
                <button className="danger" onClick={handleDelete} disabled={loading}>
                  Delete
                </button>
              </>
            )}
          </div>
          {selected && (
            <div className="detail-grid">
              <div>
                <div className="label">Last sync</div>
                <span className="muted">{selected.last_sync_at ?? "—"}</span>
              </div>
              <div>
                <div className="label">Updated</div>
                <span className="muted">{selected.updated_at ?? "—"}</span>
              </div>
            </div>
          )}
        </section>
      </div>
    </>
  );
}
