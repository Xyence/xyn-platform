import { useEffect, useMemo, useState } from "react";
import InlineMessage from "../../components/InlineMessage";
import type { AiCredential, AiModelConfig, AiModelConfigCompat, AiPurpose } from "../../api/types";
import {
  createAiModelConfig,
  deleteAiModelConfig,
  getAiModelConfigCompat,
  listAiCredentials,
  listAiModelConfigs,
  listAiProviders,
  listAiPurposes,
  updateAiModelConfig,
} from "../../api/xyn";

type ModelConfigForm = {
  id: string;
  provider: "openai" | "anthropic" | "google";
  credential_id: string;
  model_name: string;
  temperature: string;
  max_tokens: string;
  top_p: string;
  frequency_penalty: string;
  presence_penalty: string;
  enabled: boolean;
};

function toEditForm(item: AiModelConfig): ModelConfigForm {
  return {
    id: item.id,
    provider: item.provider,
    credential_id: item.credential_id || "",
    model_name: item.model_name || "",
    temperature: String(item.temperature ?? 0.2),
    max_tokens: String(item.max_tokens ?? 1200),
    top_p: String(item.top_p ?? 1.0),
    frequency_penalty: String(item.frequency_penalty ?? 0),
    presence_penalty: String(item.presence_penalty ?? 0),
    enabled: Boolean(item.enabled),
  };
}

function isOpenAIGpt5Model(provider: string, modelName: string): boolean {
  return provider === "openai" && /^gpt-5($|-)/i.test((modelName || "").trim());
}

export default function AIModelConfigsPage() {
  const [providers, setProviders] = useState<Array<{ slug: "openai" | "anthropic" | "google"; name: string }>>([]);
  const [credentials, setCredentials] = useState<AiCredential[]>([]);
  const [items, setItems] = useState<AiModelConfig[]>([]);
  const [purposes, setPurposes] = useState<AiPurpose[]>([]);
  const [compatByModelConfigId, setCompatByModelConfigId] = useState<Record<string, AiModelConfigCompat>>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<ModelConfigForm | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [form, setForm] = useState({
    provider: "openai" as "openai" | "anthropic" | "google",
    credential_id: "",
    model_name: "",
    temperature: "0.2",
    max_tokens: "1200",
  });

  const selectedConfig = useMemo(() => items.find((item) => item.id === selectedId) || null, [items, selectedId]);
  const providerCredentials = credentials.filter((item) => item.provider === form.provider);
  const editProviderCredentials = credentials.filter((item) => item.provider === (editForm?.provider || "openai"));
  const createFormTemperatureIgnored = isOpenAIGpt5Model(form.provider, form.model_name);
  const selectedCompat = editForm ? compatByModelConfigId[editForm.id] : null;
  const selectedTemperatureIgnored = Boolean(selectedCompat?.warnings?.some((warning) => warning.param === "temperature"));

  const load = async () => {
    try {
      setError(null);
      const [providerData, credentialData, modelData, purposeData] = await Promise.all([
        listAiProviders(),
        listAiCredentials(),
        listAiModelConfigs(),
        listAiPurposes(),
      ]);
      const nextItems = modelData.model_configs || [];
      setProviders(providerData.providers.map((item) => ({ slug: item.slug, name: item.name })));
      setCredentials(credentialData.credentials || []);
      setItems(nextItems);
      setPurposes(purposeData.purposes || []);
      const compatPairs = await Promise.all(
        nextItems.map(async (item) => {
          try {
            const compat = await getAiModelConfigCompat(item.id);
            return [item.id, compat] as const;
          } catch {
            return [item.id, { provider: item.provider, model_name: item.model_name, effective_params: {}, warnings: [] } as AiModelConfigCompat] as const;
          }
        })
      );
      setCompatByModelConfigId(Object.fromEntries(compatPairs));
      if (!form.credential_id && credentialData.credentials?.some((entry) => entry.provider === form.provider)) {
        const first = credentialData.credentials.find((entry) => entry.provider === form.provider);
        if (first) {
          setForm((prev) => ({ ...prev, credential_id: first.id }));
        }
      }
      const nextSelected = selectedId && nextItems.some((item) => item.id === selectedId)
        ? nextItems.find((item) => item.id === selectedId) || null
        : nextItems[0] || null;
      setSelectedId(nextSelected?.id || null);
      setEditForm(nextSelected ? toEditForm(nextSelected) : null);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const create = async () => {
    try {
      setError(null);
      setMessage(null);
      await createAiModelConfig({
        provider: form.provider,
        credential_id: form.credential_id || undefined,
        model_name: form.model_name.trim(),
        temperature: Number(form.temperature),
        max_tokens: Number(form.max_tokens),
        enabled: true,
      });
      setForm({ ...form, model_name: "" });
      setMessage("Model config created.");
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const saveEdit = async () => {
    if (!editForm) return;
    try {
      setError(null);
      setMessage(null);
      await updateAiModelConfig(editForm.id, {
        provider: editForm.provider,
        credential_id: editForm.credential_id || null,
        model_name: editForm.model_name.trim(),
        temperature: Number(editForm.temperature),
        max_tokens: Number(editForm.max_tokens),
        top_p: Number(editForm.top_p),
        frequency_penalty: Number(editForm.frequency_penalty),
        presence_penalty: Number(editForm.presence_penalty),
        enabled: editForm.enabled,
      });
      setMessage("Model config updated.");
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const deprecateSelected = async () => {
    if (!selectedConfig) return;
    if (!window.confirm(`Deprecate model config '${selectedConfig.model_name}'?`)) return;
    try {
      setError(null);
      setMessage(null);
      await deleteAiModelConfig(selectedConfig.id);
      setMessage("Model config deprecated.");
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h2>AI Model Configs</h2>
          <p className="muted">Provider/model parameters with optional credential binding.</p>
        </div>
        <div className="inline-actions"><button className="ghost" onClick={load}>Refresh</button></div>
      </div>
      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {message && <InlineMessage tone="info" title="Update" body={message} />}

      <section className="card">
        <div className="card-header"><h3>Create model config</h3></div>
        <div className="muted small">New model configs are enabled by default. Use the detail pane below to edit existing configs.</div>
        <div className="form-grid">
          <label>
            Provider
            <select value={form.provider} onChange={(event) => setForm({ ...form, provider: event.target.value as "openai" | "anthropic" | "google", credential_id: "" })}>
              {(providers.length ? providers : [{ slug: "openai", name: "OpenAI" }, { slug: "anthropic", name: "Anthropic" }, { slug: "google", name: "Google" }]).map((provider) => (
                <option key={provider.slug} value={provider.slug}>{provider.name}</option>
              ))}
            </select>
          </label>
          <label>
            Credential (optional)
            <select value={form.credential_id} onChange={(event) => setForm({ ...form, credential_id: event.target.value })}>
              <option value="">None (env fallback)</option>
              {providerCredentials.map((credential) => (
                <option key={credential.id} value={credential.id}>{credential.name}</option>
              ))}
            </select>
          </label>
          <label>
            Model name
            <input className="input" value={form.model_name} onChange={(event) => setForm({ ...form, model_name: event.target.value })} placeholder="gpt-4o-mini" />
          </label>
          <label>
            Temperature
            <input className="input" value={form.temperature} onChange={(event) => setForm({ ...form, temperature: event.target.value })} />
            {createFormTemperatureIgnored && (
              <span className="muted small">This model does not support temperature; it will be ignored during invocation.</span>
            )}
          </label>
          <label>
            Max tokens
            <input className="input" value={form.max_tokens} onChange={(event) => setForm({ ...form, max_tokens: event.target.value })} />
          </label>
        </div>
        <div className="inline-actions" style={{ marginTop: 12 }}>
          <button className="primary" onClick={create} disabled={!form.model_name.trim()}>Create</button>
        </div>
      </section>

      <div className="layout">
        <section className="card">
          <div className="card-header"><h3>Model configs</h3></div>
          <div className="instance-list">
            {items.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`instance-row ${selectedId === item.id ? "selected" : ""}`}
                onClick={() => {
                  setSelectedId(item.id);
                  setEditForm(toEditForm(item));
                }}
              >
                <div>
                  <strong>{item.model_name}</strong>
                  <span className="muted small">
                    {item.provider}
                    {typeof compatByModelConfigId[item.id]?.effective_params?.temperature === "number"
                      ? ` · temp ${compatByModelConfigId[item.id]?.effective_params?.temperature}`
                      : ""}
                    {typeof compatByModelConfigId[item.id]?.effective_params?.top_p === "number"
                      ? ` · top_p ${compatByModelConfigId[item.id]?.effective_params?.top_p}`
                      : ""}
                    {typeof compatByModelConfigId[item.id]?.effective_params?.max_tokens === "number"
                      ? ` · max ${compatByModelConfigId[item.id]?.effective_params?.max_tokens}`
                      : ""}
                    {" · purposes: "}
                    {purposes
                      .filter((purpose) => purpose.model_config?.id === item.id)
                      .map((purpose) => purpose.slug)
                      .join(", ") || "none"}
                    {compatByModelConfigId[item.id]?.warnings?.some((warning) => warning.param === "temperature") && (
                      <> · temperature ignored for this model</>
                    )}
                  </span>
                </div>
                <span className="muted">{item.enabled ? "active" : "deprecated"}</span>
              </button>
            ))}
            {!items.length && <p className="muted">No model configs configured.</p>}
          </div>
        </section>

        <section className="card">
          <div className="card-header"><h3>Model config detail</h3></div>
          {!selectedConfig || !editForm ? (
            <p className="muted">Select a model config to view and edit details.</p>
          ) : (
            <>
              <div className="form-grid">
                <label>
                  ID
                  <input className="input" value={editForm.id} disabled />
                </label>
                <label>
                  Provider
                  <select value={editForm.provider} onChange={(event) => setEditForm({ ...editForm, provider: event.target.value as "openai" | "anthropic" | "google", credential_id: "" })}>
                    {(providers.length ? providers : [{ slug: "openai", name: "OpenAI" }, { slug: "anthropic", name: "Anthropic" }, { slug: "google", name: "Google" }]).map((provider) => (
                      <option key={provider.slug} value={provider.slug}>{provider.name}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Credential (optional)
                  <select value={editForm.credential_id} onChange={(event) => setEditForm({ ...editForm, credential_id: event.target.value })}>
                    <option value="">None (env fallback)</option>
                    {editProviderCredentials.map((credential) => (
                      <option key={credential.id} value={credential.id}>{credential.name}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Model name
                  <input className="input" value={editForm.model_name} onChange={(event) => setEditForm({ ...editForm, model_name: event.target.value })} />
                </label>
                <label>
                  Temperature
                  <input className="input" value={editForm.temperature} onChange={(event) => setEditForm({ ...editForm, temperature: event.target.value })} />
                  {selectedTemperatureIgnored && (
                    <span className="muted small">This model does not support temperature; it will be ignored during invocation.</span>
                  )}
                </label>
                <label>
                  Top P
                  <input className="input" value={editForm.top_p} onChange={(event) => setEditForm({ ...editForm, top_p: event.target.value })} />
                </label>
                <label>
                  Max tokens
                  <input className="input" value={editForm.max_tokens} onChange={(event) => setEditForm({ ...editForm, max_tokens: event.target.value })} />
                </label>
                <label>
                  Frequency penalty
                  <input className="input" value={editForm.frequency_penalty} onChange={(event) => setEditForm({ ...editForm, frequency_penalty: event.target.value })} />
                </label>
                <label>
                  Presence penalty
                  <input className="input" value={editForm.presence_penalty} onChange={(event) => setEditForm({ ...editForm, presence_penalty: event.target.value })} />
                </label>
                <label>
                  Status
                  <select value={editForm.enabled ? "active" : "deprecated"} onChange={(event) => setEditForm({ ...editForm, enabled: event.target.value === "active" })}>
                    <option value="active">Active</option>
                    <option value="deprecated">Deprecated</option>
                  </select>
                </label>
              </div>
              {selectedCompat?.warnings?.length ? (
                <InlineMessage
                  tone="warn"
                  title="Compatibility warnings"
                  body={selectedCompat.warnings.map((item) => item.detail).join(" ")}
                />
              ) : null}
              <div className="inline-actions" style={{ marginTop: 12 }}>
                <button className="primary" onClick={saveEdit} disabled={!editForm.model_name.trim()}>Save changes</button>
                <button className="danger" onClick={deprecateSelected}>Deprecate</button>
              </div>
            </>
          )}
        </section>
      </div>
    </>
  );
}
