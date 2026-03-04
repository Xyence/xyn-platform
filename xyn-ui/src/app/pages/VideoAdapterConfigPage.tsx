import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import {
  createSecretValue,
  getVideoAdapterConfig,
  listSecretRefs,
  listSecretStores,
  listVideoAdapters,
  updateVideoAdapterConfig,
} from "../../api/xyn";
import type {
  SecretRefMetadata,
  SecretStore,
  VideoAdapterConfigRecord,
  VideoAdapterDefinition,
} from "../../api/types";

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return "{}";
  }
}

function validateAdapterCredential(adapter: string, rawValue: string): string | null {
  const adapterId = String(adapter || "").trim().toLowerCase();
  const value = String(rawValue || "").trim();
  if (!value) return "API key is required.";
  if (adapterId !== "google_veo") {
    return null;
  }
  if (value.startsWith("AIza")) {
    return null;
  }
  try {
    const parsed = JSON.parse(value);
    if (parsed && typeof parsed === "object") {
      const obj = parsed as Record<string, unknown>;
      const maybeKey = String(obj.api_key ?? obj.apiKey ?? obj.key ?? "").trim();
      if (maybeKey.startsWith("AIza")) {
        return null;
      }
    }
  } catch {
    // Intentionally ignored; handled by returning validation guidance below.
  }
  return "Google Veo credential must be a Google API key (starts with 'AIza') or JSON containing api_key/apiKey/key.";
}

export default function VideoAdapterConfigPage() {
  const navigate = useNavigate();
  const { artifactId = "" } = useParams();
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [record, setRecord] = useState<VideoAdapterConfigRecord | null>(null);
  const [adapters, setAdapters] = useState<VideoAdapterDefinition[]>([]);
  const [secretStores, setSecretStores] = useState<SecretStore[]>([]);
  const [platformSecretRefs, setPlatformSecretRefs] = useState<SecretRefMetadata[]>([]);

  const [title, setTitle] = useState("");
  const [slug, setSlug] = useState("");
  const [artifactState, setArtifactState] = useState("provisional");
  const [adapterId, setAdapterId] = useState("");
  const [configJsonText, setConfigJsonText] = useState("{}");
  const [secretStoreId, setSecretStoreId] = useState("");
  const [secretName, setSecretName] = useState("");
  const [secretValue, setSecretValue] = useState("");

  const activeAdapter = useMemo(
    () => adapters.find((item) => item.id === adapterId) || null,
    [adapters, adapterId]
  );

  const load = async () => {
    if (!artifactId) return;
    try {
      setLoading(true);
      setError(null);
      const [detail, adapterList, storeList, refList] = await Promise.all([
        getVideoAdapterConfig(artifactId),
        listVideoAdapters(),
        listSecretStores(),
        listSecretRefs({ scope_kind: "platform" }),
      ]);
      const next = detail.config;
      setRecord(next);
      setAdapters(adapterList.adapters || []);
      setSecretStores(storeList.secret_stores || []);
      setPlatformSecretRefs(refList.secret_refs || []);
      setTitle(next.title || "");
      setSlug(next.slug || "");
      setArtifactState(next.artifact_state || "provisional");
      setAdapterId(next.adapter_id || "");
      setConfigJsonText(prettyJson(next.config_json || {}));
      const defaultStore = (storeList.secret_stores || []).find((item) => item.is_default) || (storeList.secret_stores || [])[0];
      setSecretStoreId(defaultStore?.id || "");
      const normalizedSlug = (next.slug || "video-adapter-config").replace(/[^a-zA-Z0-9_-]/g, "-").toLowerCase();
      setSecretName(`video/${next.adapter_id || "adapter"}/${normalizedSlug}/api_key`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [artifactId]);

  const parsedConfig = useMemo(() => {
    try {
      const parsed = JSON.parse(configJsonText || "{}");
      return typeof parsed === "object" && parsed !== null ? (parsed as Record<string, unknown>) : null;
    } catch {
      return null;
    }
  }, [configJsonText]);
  const currentCredentialRef = String(parsedConfig?.credential_ref || "").trim();
  const resolvedSecretRef = useMemo(() => {
    if (!currentCredentialRef) return null;
    if (currentCredentialRef.startsWith("secret_ref:")) {
      const id = currentCredentialRef.split(":", 2)[1];
      return platformSecretRefs.find((item) => item.id === id) || null;
    }
    return platformSecretRefs.find((item) => item.name === currentCredentialRef) || null;
  }, [currentCredentialRef, platformSecretRefs]);

  const save = async () => {
    if (!artifactId) return;
    try {
      setLoading(true);
      setError(null);
      setMessage(null);
      let parsed: Record<string, unknown>;
      try {
        parsed = JSON.parse(configJsonText || "{}");
      } catch {
        setError("Config JSON is invalid.");
        setLoading(false);
        return;
      }
      parsed.adapter_id = adapterId;
      const result = await updateVideoAdapterConfig(artifactId, {
        title,
        slug,
        artifact_state: artifactState,
        adapter_id: adapterId,
        config_json: parsed,
      });
      setRecord(result.config);
      setConfigJsonText(prettyJson(result.config.config_json || {}));
      setMessage("Adapter config saved.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const storeApiKeyAndAttach = async () => {
    if (!artifactId) return;
    const credentialError = validateAdapterCredential(adapterId, secretValue);
    if (credentialError) {
      setError(credentialError);
      return;
    }
    if (!secretName.trim()) {
      setError("Secret name is required.");
      return;
    }
    if (!secretStoreId) {
      setError("Select a secret store first.");
      return;
    }
    if (!parsedConfig) {
      setError("Config JSON must be valid before storing secret.");
      return;
    }
    try {
      setLoading(true);
      setError(null);
      setMessage(null);
      const secretResult = await createSecretValue({
        name: secretName.trim(),
        scope_kind: "platform",
        store_id: secretStoreId,
        value: secretValue,
        description: `Video adapter credential for ${adapterId || "adapter"}`,
      });
      const nextCredentialRef = `secret_ref:${secretResult.secret_ref.id}`;
      const updatedConfig = {
        ...parsedConfig,
        adapter_id: adapterId,
        credential_ref: nextCredentialRef,
      };
      const updateResult = await updateVideoAdapterConfig(artifactId, {
        title,
        slug,
        artifact_state: artifactState,
        adapter_id: adapterId,
        config_json: updatedConfig,
      });
      setRecord(updateResult.config);
      setConfigJsonText(prettyJson(updateResult.config.config_json || {}));
      setSecretValue("");
      const refList = await listSecretRefs({ scope_kind: "platform" });
      setPlatformSecretRefs(refList.secret_refs || []);
      setMessage(`Stored API key in Secret Store and updated credential_ref to ${nextCredentialRef}.`);
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
          <h2>Video Adapter Config</h2>
          <p className="muted">Governed renderer adapter configuration.</p>
        </div>
        <div className="inline-actions">
          <button className="ghost" onClick={() => navigate("/app/platform/settings")}>
            Back to settings
          </button>
          <button className="ghost" onClick={load} disabled={loading}>
            Refresh
          </button>
          <button className="primary" onClick={save} disabled={loading || !artifactId}>
            Save
          </button>
        </div>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {message && <InlineMessage tone="info" title="Update" body={message} />}

      <section className="card">
        <div className="form-grid">
          <label>
            Title
            <input className="input" value={title} onChange={(event) => setTitle(event.target.value)} />
          </label>
          <label>
            Slug
            <input className="input" value={slug} onChange={(event) => setSlug(event.target.value)} />
          </label>
          <label>
            State
            <select value={artifactState} onChange={(event) => setArtifactState(event.target.value)}>
              <option value="provisional">provisional</option>
              <option value="canonical">canonical</option>
              <option value="deprecated">deprecated</option>
            </select>
          </label>
          <label>
            Adapter
            <select value={adapterId} onChange={(event) => setAdapterId(event.target.value)}>
              <option value="">Select adapter</option>
              {adapters.map((adapter) => (
                <option key={adapter.id} value={adapter.id}>
                  {adapter.name}
                </option>
              ))}
            </select>
            <span className="muted small">{activeAdapter?.description || ""}</span>
          </label>
          <label style={{ gridColumn: "1 / -1" }}>
            Config JSON
            <textarea
              className="input"
              style={{ minHeight: 360, fontFamily: "monospace" }}
              value={configJsonText}
              onChange={(event) => setConfigJsonText(event.target.value)}
            />
          </label>
        </div>
      </section>

      <section className="card">
        <div className="card-header">
          <h3>Credential Helper</h3>
        </div>
        <div className="form-grid">
          <label>
            Secret store
            <select value={secretStoreId} onChange={(event) => setSecretStoreId(event.target.value)}>
              <option value="">Select store</option>
              {secretStores.map((store) => (
                <option key={store.id} value={store.id}>
                  {store.name} {store.is_default ? "(default)" : ""}
                </option>
              ))}
            </select>
          </label>
          <label>
            Secret name
            <input
              className="input"
              value={secretName}
              onChange={(event) => setSecretName(event.target.value)}
              placeholder="video/google_veo/my-config/api_key"
            />
          </label>
          <label style={{ gridColumn: "1 / -1" }}>
            API key / token
            <input
              className="input"
              type="password"
              value={secretValue}
              onChange={(event) => setSecretValue(event.target.value)}
              placeholder="Paste provider API key or service credential"
            />
          </label>
          <div className="inline-actions">
            <button
              type="button"
              className="primary"
              onClick={storeApiKeyAndAttach}
              disabled={loading || !secretStoreId || !secretName.trim() || !secretValue.trim()}
            >
              Store API key and attach
            </button>
          </div>
          <p className="muted small" style={{ gridColumn: "1 / -1" }}>
            Current credential_ref: <code>{currentCredentialRef || "(none)"}</code>
            {resolvedSecretRef ? ` · resolves to secret '${resolvedSecretRef.name}'` : ""}
          </p>
          {String(adapterId || "").trim().toLowerCase() === "google_veo" ? (
            <p className="muted small" style={{ gridColumn: "1 / -1" }}>
              For Google Veo, use a Google API key (`AIza...`) or JSON containing `api_key`.
            </p>
          ) : null}
        </div>
      </section>

      {record ? (
        <p className="muted small">
          Artifact: {record.artifact_id} · Version: {record.version} · Hash: {record.content_hash || "-"}
        </p>
      ) : null}
    </>
  );
}
