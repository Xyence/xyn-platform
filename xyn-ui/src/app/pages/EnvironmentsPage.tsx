import { useCallback, useEffect, useState } from "react";
import InlineMessage from "../../components/InlineMessage";
import { createEnvironment, deleteEnvironment, listEnvironments, updateEnvironment } from "../../api/xyn";
import type { EnvironmentCreatePayload, EnvironmentSummary } from "../../api/types";

const emptyForm: EnvironmentCreatePayload = {
  name: "",
  slug: "",
  base_domain: "",
  aws_region: "",
};

export default function EnvironmentsPage() {
  const [items, setItems] = useState<EnvironmentSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [form, setForm] = useState<EnvironmentCreatePayload>(emptyForm);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const data = await listEnvironments();
      setItems(data.environments);
      if (!selectedId && data.environments[0]) {
        setSelectedId(data.environments[0].id);
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
      setForm(emptyForm);
      return;
    }
    const selected = items.find((item) => item.id === selectedId);
    if (selected) {
      setForm({
        name: selected.name,
        slug: selected.slug,
        base_domain: selected.base_domain ?? "",
        aws_region: selected.aws_region ?? "",
      });
    }
  }, [items, selectedId]);

  const handleCreate = async () => {
    try {
      setLoading(true);
      setError(null);
      setMessage(null);
      await createEnvironment(form);
      setForm(emptyForm);
      await load();
      setMessage("Environment created.");
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
      await updateEnvironment(selectedId, form);
      await load();
      setMessage("Environment updated.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedId) return;
    if (!confirm("Delete this environment?")) return;
    try {
      setLoading(true);
      setError(null);
      await deleteEnvironment(selectedId);
      setSelectedId(null);
      setForm(emptyForm);
      await load();
      setMessage("Environment deleted.");
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
          <h2>Environments</h2>
          <p className="muted">Manage deployment environments.</p>
        </div>
        <div className="inline-actions">
          <button className="ghost" onClick={load} disabled={loading}>
            Refresh
          </button>
        </div>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {message && <InlineMessage tone="info" title="Update" body={message} />}

      <div className="layout">
        <section className="card">
          <div className="card-header">
            <h3>Environments</h3>
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
                  <span className="muted small">{item.slug}</span>
                </div>
                <div className="muted small">
                  <div>{item.aws_region || "—"}</div>
                  <div>{item.base_domain || "—"}</div>
                </div>
              </button>
            ))}
            {items.length === 0 && <p className="muted">No environments yet.</p>}
          </div>
        </section>

        <section className="card">
          <div className="card-header">
            <h3>{selectedId ? "Edit environment" : "Create environment"}</h3>
          </div>
          <div className="form-grid">
            <label>
              Name
              <input
                className="input"
                value={form.name || ""}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
              />
            </label>
            <label>
              Slug
              <input
                className="input"
                value={form.slug || ""}
                onChange={(event) => setForm({ ...form, slug: event.target.value })}
              />
            </label>
            <label>
              Base domain
              <input
                className="input"
                value={form.base_domain || ""}
                onChange={(event) => setForm({ ...form, base_domain: event.target.value })}
              />
            </label>
            <label>
              AWS region
              <input
                className="input"
                value={form.aws_region || ""}
                onChange={(event) => setForm({ ...form, aws_region: event.target.value })}
              />
            </label>
          </div>
          <div className="form-actions">
            <button className="primary" onClick={handleCreate} disabled={loading || !form.name || !form.slug}>
              Create
            </button>
            <button className="ghost" onClick={handleUpdate} disabled={loading || !selectedId}>
              Update
            </button>
            <button className="danger" onClick={handleDelete} disabled={loading || !selectedId}>
              Delete
            </button>
          </div>
        </section>
      </div>
    </>
  );
}
