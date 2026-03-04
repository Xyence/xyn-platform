import { useEffect, useMemo, useState } from "react";
import InlineMessage from "../../components/InlineMessage";
import type { AiCredential } from "../../api/types";
import { createAiCredential, deleteAiCredential, listAiCredentials, listAiProviders, updateAiCredential } from "../../api/xyn";

export default function AICredentialsPage() {
  const [providers, setProviders] = useState<Array<{ slug: "openai" | "anthropic" | "google"; name: string }>>([]);
  const [items, setItems] = useState<AiCredential[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [form, setForm] = useState({
    provider: "openai" as "openai" | "anthropic" | "google",
    name: "",
    auth_type: "api_key" as "api_key" | "env_ref",
    api_key: "",
    env_var_name: "",
  });
  const autofillNonce = useMemo(() => Math.random().toString(36).slice(2, 10), []);

  const load = async () => {
    try {
      setError(null);
      const [providerData, credentialData] = await Promise.all([listAiProviders(), listAiCredentials()]);
      setProviders(providerData.providers.map((item) => ({ slug: item.slug, name: item.name })));
      setItems(credentialData.credentials || []);
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
      await createAiCredential({
        provider: form.provider,
        name: form.name,
        auth_type: form.auth_type,
        api_key: form.auth_type === "api_key" ? form.api_key : undefined,
        env_var_name: form.auth_type === "env_ref" ? form.env_var_name : undefined,
        enabled: true,
      });
      setForm({
        provider: form.provider,
        name: "",
        auth_type: form.auth_type,
        api_key: "",
        env_var_name: "",
      });
      setMessage("Credential created.");
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const toggleEnabled = async (item: AiCredential) => {
    try {
      await updateAiCredential(item.id, { enabled: !item.enabled });
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const remove = async (item: AiCredential) => {
    if (!window.confirm(`Delete credential '${item.name}'?`)) return;
    try {
      await deleteAiCredential(item.id);
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h2>AI Credentials</h2>
          <p className="muted">Manage provider authentication for OpenAI, Anthropic, and Google.</p>
        </div>
        <div className="inline-actions">
          <button className="ghost" onClick={load}>Refresh</button>
        </div>
      </div>
      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {message && <InlineMessage tone="info" title="Update" body={message} />}

      <section className="card">
        <div className="card-header"><h3>Create credential</h3></div>
        <div className="muted small">New credentials are enabled by default. Use the row actions below to disable/re-enable.</div>
        <div className="form-grid">
          {/* Decoy fields reduce browser/password-manager autofill noise in the real create inputs. */}
          <input type="text" autoComplete="username" style={{ display: "none" }} aria-hidden="true" tabIndex={-1} />
          <input type="password" autoComplete="current-password" style={{ display: "none" }} aria-hidden="true" tabIndex={-1} />
          <label>
            Provider
            <select value={form.provider} onChange={(event) => setForm({ ...form, provider: event.target.value as "openai" | "anthropic" | "google" })}>
              {(providers.length ? providers : [{ slug: "openai", name: "OpenAI" }, { slug: "anthropic", name: "Anthropic" }, { slug: "google", name: "Google" }]).map((provider) => (
                <option key={provider.slug} value={provider.slug}>{provider.name}</option>
              ))}
            </select>
          </label>
          <label>
            Name
            <input
              className="input"
              autoComplete="off"
              name={`ai-credential-name-${autofillNonce}`}
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              placeholder="prod-openai"
            />
          </label>
          <label>
            Auth type
            <select value={form.auth_type} onChange={(event) => setForm({ ...form, auth_type: event.target.value as "api_key" | "env_ref" })}>
              <option value="api_key">api_key</option>
              <option value="env_ref">env_ref</option>
            </select>
          </label>
          {form.auth_type === "api_key" ? (
            <label>
              API key
              <input
                className="input"
                type="password"
                autoComplete="new-password"
                name={`ai-credential-api-key-${autofillNonce}`}
                value={form.api_key}
                onChange={(event) => setForm({ ...form, api_key: event.target.value })}
                placeholder="sk-..."
              />
            </label>
          ) : (
            <label>
              Env var name
              <input
                className="input"
                autoComplete="off"
                name={`ai-credential-env-var-${autofillNonce}`}
                value={form.env_var_name}
                onChange={(event) => setForm({ ...form, env_var_name: event.target.value })}
                placeholder="XYN_OPENAI_API_KEY"
              />
            </label>
          )}
        </div>
        <div className="inline-actions" style={{ marginTop: 12 }}>
          <button className="primary" onClick={create} disabled={!form.name.trim()}>
            Create
          </button>
        </div>
      </section>

      <section className="card">
        <div className="card-header"><h3>Credentials</h3></div>
        <div className="instance-list">
          {items.map((item) => (
            <div className="instance-row" key={item.id}>
              <div>
                <strong>{item.name}</strong>
                <span className="muted small">{item.provider} · {item.auth_type} · {item.secret_ref_id ? "secret-store" : "fallback"} · {item.secret?.masked || "not configured"}{item.is_default ? " · default" : ""}</span>
              </div>
              <div className="inline-actions">
                <button className="ghost" onClick={() => toggleEnabled(item)}>{item.enabled ? "Disable" : "Enable"}</button>
                <button className="danger" onClick={() => remove(item)}>Delete</button>
              </div>
            </div>
          ))}
          {!items.length && <p className="muted">No credentials configured.</p>}
        </div>
      </section>
    </>
  );
}
