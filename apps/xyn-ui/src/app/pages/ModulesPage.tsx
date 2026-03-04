import { useCallback, useEffect, useState } from "react";
import InlineMessage from "../../components/InlineMessage";
import {
  createModule,
  deleteModule,
  getModule,
  listModules,
  updateModule,
} from "../../api/xyn";
import type { ModuleCreatePayload, ModuleDetail, ModuleSummary } from "../../api/types";
import ArtifactCredibilityLayer from "../components/artifacts/ArtifactCredibilityLayer";

const emptyForm: ModuleCreatePayload = {
  name: "",
  namespace: "core",
  type: "service",
  current_version: "0.1.0",
  status: "active",
};

const MODULE_TYPES = ["adapter", "service", "ui", "workflow", "schema", "infra", "lib"];

export default function ModulesPage() {
  const [items, setItems] = useState<ModuleSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<ModuleDetail | null>(null);
  const [form, setForm] = useState<ModuleCreatePayload>(emptyForm);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const data = await listModules();
      setItems(data.modules);
      if (!selectedId && data.modules[0]) {
        setSelectedId(data.modules[0].id);
      }
    } catch (err) {
      setError((err as Error).message);
    }
  }, [selectedId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      load();
    }, 15000);
    return () => window.clearInterval(interval);
  }, [load]);

  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      return;
    }
    (async () => {
      try {
        const detail = await getModule(selectedId);
        setSelected(detail);
        setForm({
          name: detail.name,
          namespace: detail.namespace,
          type: detail.type,
          current_version: detail.current_version,
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
      await createModule(form);
      setForm(emptyForm);
      await load();
      setMessage("Module created.");
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
      await updateModule(selectedId, form);
      await load();
      setMessage("Module updated.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedId) return;
    if (!confirm("Delete this module?")) return;
    try {
      setLoading(true);
      setError(null);
      await deleteModule(selectedId);
      setSelectedId(null);
      setSelected(null);
      setForm(emptyForm);
      await load();
      setMessage("Module deleted.");
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
          <h2>Modules</h2>
          <p className="muted">Catalog reusable platform modules.</p>
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
            <h3>Modules</h3>
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
                  <span className="muted small">{item.namespace}</span>
                </div>
                <span className="muted small">{item.type}</span>
              </button>
            ))}
            {items.length === 0 && <p className="muted">No modules yet.</p>}
          </div>
        </section>

        <section className="card">
          <div className="card-header">
            <h3>{selected ? "Module detail" : "Create module"}</h3>
          </div>
          {selected?.artifact_id && (
            <ArtifactCredibilityLayer
              artifactId={selected.artifact_id}
              titleFallback={selected.name}
              busy={loading}
            />
          )}
          <div className="form-grid">
            <label>
              Name
              <input
                value={form.name ?? ""}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
              />
            </label>
            <label>
              Namespace
              <input
                value={form.namespace ?? ""}
                onChange={(event) => setForm({ ...form, namespace: event.target.value })}
              />
            </label>
            <label>
              Type
              <select
                value={form.type ?? "service"}
                onChange={(event) => setForm({ ...form, type: event.target.value })}
              >
                {MODULE_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Version
              <input
                value={form.current_version ?? ""}
                onChange={(event) => setForm({ ...form, current_version: event.target.value })}
              />
            </label>
            <label>
              Status
              <input
                value={form.status ?? ""}
                onChange={(event) => setForm({ ...form, status: event.target.value })}
              />
            </label>
          </div>
          <div className="form-actions">
            <button className="primary" onClick={selected ? handleUpdate : handleCreate} disabled={loading}>
              {selected ? "Save changes" : "Create"}
            </button>
            {selected && (
              <button className="danger" onClick={handleDelete} disabled={loading}>
                Delete
              </button>
            )}
          </div>
          {selected && (
            <div className="detail-grid">
              <div>
                <div className="label">FQN</div>
                <span className="muted">{selected.fqn}</span>
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
