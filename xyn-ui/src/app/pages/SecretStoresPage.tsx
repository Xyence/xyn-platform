import { useCallback, useEffect, useMemo, useState } from "react";
import InlineMessage from "../../components/InlineMessage";
import {
  createSecretStore,
  listSecretStores,
  setDefaultSecretStore,
  updateSecretStore,
} from "../../api/xyn";
import type { SecretStore } from "../../api/types";

const emptyForm: SecretStore = {
  id: "",
  name: "",
  kind: "aws_secrets_manager",
  is_default: false,
  config_json: {
    aws_region: "",
    name_prefix: "/xyn",
    kms_key_id: "",
    tags: { "xyn:managed": "true" },
  },
};

export default function SecretStoresPage() {
  const [items, setItems] = useState<SecretStore[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [form, setForm] = useState<SecretStore>(emptyForm);
  const [tagsText, setTagsText] = useState<string>(JSON.stringify(emptyForm.config_json.tags, null, 2));
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selected = useMemo(() => items.find((item) => item.id === selectedId) || null, [items, selectedId]);

  const load = useCallback(async () => {
    try {
      setError(null);
      const data = await listSecretStores();
      setItems(data.secret_stores);
      if (!selectedId && data.secret_stores[0]) {
        setSelectedId(data.secret_stores[0].id);
      }
    } catch (err) {
      setError((err as Error).message);
    }
  }, [selectedId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!selected) {
      setForm(emptyForm);
      setTagsText(JSON.stringify(emptyForm.config_json.tags, null, 2));
      return;
    }
    const tags = selected.config_json?.tags || {};
    setForm({
      ...emptyForm,
      ...selected,
      config_json: {
        aws_region: selected.config_json?.aws_region || "",
        name_prefix: selected.config_json?.name_prefix || "/xyn",
        kms_key_id: selected.config_json?.kms_key_id || "",
        tags,
      },
    });
    setTagsText(JSON.stringify(tags, null, 2));
  }, [selected]);

  const parseTags = (): Record<string, string> => {
    const raw = tagsText.trim();
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return Object.entries(parsed).reduce<Record<string, string>>((acc, [k, v]) => {
      acc[k] = String(v);
      return acc;
    }, {});
  };

  const payloadFromForm = () => {
    const tags = parseTags();
    return {
      name: form.name,
      kind: "aws_secrets_manager" as const,
      is_default: form.is_default,
      config_json: {
        aws_region: (form.config_json?.aws_region || "").trim(),
        name_prefix: (form.config_json?.name_prefix || "/xyn").trim(),
        kms_key_id: (form.config_json?.kms_key_id || "").trim() || null,
        tags,
      },
    };
  };

  const handleCreate = async () => {
    try {
      setLoading(true);
      setError(null);
      setMessage(null);
      await createSecretStore(payloadFromForm());
      await load();
      setMessage("Secret store created.");
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
      await updateSecretStore(selectedId, payloadFromForm());
      await load();
      setMessage("Secret store updated.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleSetDefault = async () => {
    if (!selectedId) return;
    try {
      setLoading(true);
      setError(null);
      await setDefaultSecretStore(selectedId);
      await load();
      setMessage("Default secret store updated.");
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
          <h2>Secret Stores</h2>
          <p className="muted">Platform-managed secret stores (v1: AWS Secrets Manager).</p>
        </div>
        <div className="inline-actions">
          <button className="ghost" onClick={load} disabled={loading}>
            Refresh
          </button>
          <button
            className="ghost"
            onClick={() => {
              setSelectedId(null);
              setForm(emptyForm);
              setTagsText(JSON.stringify(emptyForm.config_json.tags, null, 2));
            }}
            disabled={loading}
          >
            New store
          </button>
        </div>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {message && <InlineMessage tone="info" title="Update" body={message} />}

      <div className="layout">
        <section className="card">
          <div className="card-header">
            <h3>Stores</h3>
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
                  <span className="muted small">{item.kind}</span>
                </div>
                <div className="muted small">{item.is_default ? "Default" : ""}</div>
              </button>
            ))}
            {items.length === 0 && <p className="muted">No secret stores yet.</p>}
          </div>
        </section>

        <section className="card">
          <div className="card-header">
            <h3>{selectedId ? "Edit store" : "Create store"}</h3>
          </div>
          <div className="form-grid">
            <label>
              Name
              <input
                className="input"
                value={form.name}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
              />
            </label>
            <label>
              Kind
              <select value={form.kind} disabled>
                <option value="aws_secrets_manager">aws_secrets_manager</option>
              </select>
            </label>
            <label>
              AWS region
              <input
                className="input"
                value={form.config_json?.aws_region || ""}
                onChange={(event) =>
                  setForm({
                    ...form,
                    config_json: { ...form.config_json, aws_region: event.target.value },
                  })
                }
              />
            </label>
            <label>
              Name prefix
              <input
                className="input"
                value={form.config_json?.name_prefix || ""}
                onChange={(event) =>
                  setForm({
                    ...form,
                    config_json: { ...form.config_json, name_prefix: event.target.value },
                  })
                }
              />
            </label>
            <label>
              KMS key ID (optional)
              <input
                className="input"
                value={form.config_json?.kms_key_id || ""}
                onChange={(event) =>
                  setForm({
                    ...form,
                    config_json: { ...form.config_json, kms_key_id: event.target.value },
                  })
                }
              />
            </label>
            <label>
              Default
              <select
                value={form.is_default ? "yes" : "no"}
                onChange={(event) => setForm({ ...form, is_default: event.target.value === "yes" })}
              >
                <option value="no">No</option>
                <option value="yes">Yes</option>
              </select>
            </label>
            <label className="span-full">
              Tags JSON
              <textarea value={tagsText} onChange={(event) => setTagsText(event.target.value)} />
            </label>
          </div>
          <div className="form-actions">
            <button className="primary" onClick={selectedId ? handleUpdate : handleCreate} disabled={loading || !form.name}>
              {selectedId ? "Save changes" : "Create"}
            </button>
            <button className="ghost" onClick={handleSetDefault} disabled={loading || !selectedId}>
              Set default
            </button>
          </div>
        </section>
      </div>
    </>
  );
}
