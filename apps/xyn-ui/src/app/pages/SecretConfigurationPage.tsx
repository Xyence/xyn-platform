import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import Tabs from "../components/ui/Tabs";
import { createSecretStore, listSecretRefs, listSecretStores, setDefaultSecretStore, updateSecretStore } from "../../api/xyn";
import type { SecretRefMetadata, SecretStore } from "../../api/types";

type SecretTab = "stores" | "refs";

const SECRET_TABS: Array<{ value: SecretTab; label: string }> = [
  { value: "stores", label: "Secret Stores" },
  { value: "refs", label: "Secret Refs" },
];

const emptyStoreForm: SecretStore = {
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

export default function SecretConfigurationPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [stores, setStores] = useState<SecretStore[]>([]);
  const [selectedStoreId, setSelectedStoreId] = useState<string | null>(null);
  const [storeForm, setStoreForm] = useState<SecretStore>(emptyStoreForm);
  const [tagsText, setTagsText] = useState<string>(JSON.stringify(emptyStoreForm.config_json.tags, null, 2));
  const [refs, setRefs] = useState<SecretRefMetadata[]>([]);
  const [scopeKind, setScopeKind] = useState<string>("");
  const [scopeId, setScopeId] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState<SecretStore>(emptyStoreForm);
  const [createTagsText, setCreateTagsText] = useState<string>(JSON.stringify(emptyStoreForm.config_json.tags, null, 2));
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const createButtonRef = useRef<HTMLButtonElement | null>(null);
  const modalFirstFieldRef = useRef<HTMLInputElement | null>(null);

  const tabParam = String(searchParams.get("tab") || "").trim();
  const activeTab: SecretTab = (SECRET_TABS.find((item) => item.value === tabParam)?.value || "stores") as SecretTab;
  const selectedStore = useMemo(() => stores.find((item) => item.id === selectedStoreId) || null, [stores, selectedStoreId]);

  const updateTab = (next: string) => {
    const params = new URLSearchParams(searchParams);
    params.set("tab", next);
    setSearchParams(params, { replace: true });
  };

  const parseTags = (raw: string): Record<string, string> => {
    const trimmed = raw.trim();
    if (!trimmed) return {};
    const parsed = JSON.parse(trimmed) as Record<string, unknown>;
    return Object.entries(parsed).reduce<Record<string, string>>((acc, [key, value]) => {
      acc[key] = String(value);
      return acc;
    }, {});
  };

  const loadStores = useCallback(async () => {
    const data = await listSecretStores();
    setStores(data.secret_stores);
    setSelectedStoreId((current) => {
      if (current && data.secret_stores.some((item) => item.id === current)) return current;
      return data.secret_stores[0]?.id || null;
    });
  }, []);

  const loadRefs = useCallback(async () => {
    const data = await listSecretRefs({
      scope_kind: scopeKind || undefined,
      scope_id: scopeId || undefined,
    });
    setRefs(data.secret_refs);
  }, [scopeKind, scopeId]);

  const refreshActiveTab = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      if (activeTab === "stores") await loadStores();
      else await loadRefs();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [activeTab, loadRefs, loadStores]);

  useEffect(() => {
    void refreshActiveTab();
  }, [refreshActiveTab]);

  useEffect(() => {
    if (!selectedStore) {
      setStoreForm(emptyStoreForm);
      setTagsText(JSON.stringify(emptyStoreForm.config_json.tags, null, 2));
      return;
    }
    const tags = selectedStore.config_json?.tags || {};
    setStoreForm({
      ...emptyStoreForm,
      ...selectedStore,
      config_json: {
        aws_region: selectedStore.config_json?.aws_region || "",
        name_prefix: selectedStore.config_json?.name_prefix || "/xyn",
        kms_key_id: selectedStore.config_json?.kms_key_id || "",
        tags,
      },
    });
    setTagsText(JSON.stringify(tags, null, 2));
  }, [selectedStore]);

  useEffect(() => {
    if (!createOpen) return;
    const timer = window.setTimeout(() => modalFirstFieldRef.current?.focus(), 0);
    return () => window.clearTimeout(timer);
  }, [createOpen]);

  const handleCreateStore = async () => {
    try {
      setLoading(true);
      setError(null);
      const payload = {
        name: createForm.name,
        kind: "aws_secrets_manager" as const,
        is_default: createForm.is_default,
        config_json: {
          aws_region: (createForm.config_json?.aws_region || "").trim(),
          name_prefix: (createForm.config_json?.name_prefix || "/xyn").trim(),
          kms_key_id: (createForm.config_json?.kms_key_id || "").trim() || null,
          tags: parseTags(createTagsText),
        },
      };
      const created = await createSecretStore(payload);
      await loadStores();
      if (created?.id) setSelectedStoreId(created.id);
      setMessage("Secret store created.");
      setCreateOpen(false);
      createButtonRef.current?.focus();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleSaveStore = async () => {
    if (!selectedStoreId) return;
    try {
      setLoading(true);
      setError(null);
      await updateSecretStore(selectedStoreId, {
        name: storeForm.name,
        is_default: storeForm.is_default,
        config_json: {
          aws_region: (storeForm.config_json?.aws_region || "").trim(),
          name_prefix: (storeForm.config_json?.name_prefix || "/xyn").trim(),
          kms_key_id: (storeForm.config_json?.kms_key_id || "").trim() || null,
          tags: parseTags(tagsText),
        },
      });
      await loadStores();
      setMessage("Secret store updated.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleSetDefaultStore = async () => {
    if (!selectedStoreId) return;
    try {
      setLoading(true);
      setError(null);
      await setDefaultSecretStore(selectedStoreId);
      await loadStores();
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
          <h2>Secret Configuration</h2>
          <p className="muted">Manage secret stores and secret references.</p>
        </div>
        <div className="inline-actions">
          {activeTab === "stores" ? (
            <button
              ref={createButtonRef}
              className="primary"
              onClick={() => {
                setCreateForm(emptyStoreForm);
                setCreateTagsText(JSON.stringify(emptyStoreForm.config_json.tags, null, 2));
                setCreateOpen(true);
              }}
            >
              Create store
            </button>
          ) : null}
          <button className="ghost" onClick={() => void refreshActiveTab()} disabled={loading}>
            {loading ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {message && <InlineMessage tone="info" title="Update" body={message} />}

      <div className="page-tabs">
        <Tabs
          ariaLabel="Secret Configuration tabs"
          value={activeTab}
          onChange={updateTab}
          options={SECRET_TABS.map((item) => ({ value: item.value, label: item.label }))}
        />
      </div>

      {activeTab === "stores" ? (
        <div className="layout">
          <section className="card">
            <div className="card-header">
              <h3>Stores</h3>
            </div>
            <div className="instance-list">
              {stores.map((item) => (
                <button
                  key={item.id}
                  className={`instance-row ${selectedStoreId === item.id ? "active" : ""}`}
                  onClick={() => setSelectedStoreId(item.id)}
                >
                  <div>
                    <strong>{item.name}</strong>
                    <span className="muted small">{item.kind}</span>
                  </div>
                  <div className="muted small">{item.is_default ? "Default" : ""}</div>
                </button>
              ))}
              {stores.length === 0 && <p className="muted">No secret stores yet.</p>}
            </div>
          </section>
          <section className="card">
            <div className="card-header">
              <h3>Edit store</h3>
            </div>
            {selectedStoreId ? (
              <>
                <div className="form-grid">
                  <label>
                    Name
                    <input className="input" value={storeForm.name} onChange={(event) => setStoreForm({ ...storeForm, name: event.target.value })} />
                  </label>
                  <label>
                    Kind
                    <select value={storeForm.kind} disabled>
                      <option value="aws_secrets_manager">aws_secrets_manager</option>
                    </select>
                  </label>
                  <label>
                    AWS region
                    <input
                      className="input"
                      value={storeForm.config_json?.aws_region || ""}
                      onChange={(event) => setStoreForm({ ...storeForm, config_json: { ...storeForm.config_json, aws_region: event.target.value } })}
                    />
                  </label>
                  <label>
                    Name prefix
                    <input
                      className="input"
                      value={storeForm.config_json?.name_prefix || ""}
                      onChange={(event) => setStoreForm({ ...storeForm, config_json: { ...storeForm.config_json, name_prefix: event.target.value } })}
                    />
                  </label>
                  <label>
                    KMS key ID (optional)
                    <input
                      className="input"
                      value={storeForm.config_json?.kms_key_id || ""}
                      onChange={(event) => setStoreForm({ ...storeForm, config_json: { ...storeForm.config_json, kms_key_id: event.target.value } })}
                    />
                  </label>
                  <label>
                    Default
                    <select value={storeForm.is_default ? "yes" : "no"} onChange={(event) => setStoreForm({ ...storeForm, is_default: event.target.value === "yes" })}>
                      <option value="no">No</option>
                      <option value="yes">Yes</option>
                    </select>
                  </label>
                  <label className="full">
                    Tags JSON
                    <textarea className="input" rows={6} value={tagsText} onChange={(event) => setTagsText(event.target.value)} />
                  </label>
                </div>
                <div className="inline-actions">
                  <button className="primary" onClick={() => void handleSaveStore()} disabled={loading}>Save changes</button>
                  <button className="ghost" onClick={() => void handleSetDefaultStore()} disabled={loading}>Set as default</button>
                </div>
              </>
            ) : (
              <p className="muted">Select a store to edit.</p>
            )}
          </section>
        </div>
      ) : (
        <section className="card">
          <div className="card-header">
            <h3>Secret references</h3>
            <div className="inline-actions">
              <select value={scopeKind} onChange={(event) => setScopeKind(event.target.value)}>
                <option value="">All scopes</option>
                <option value="platform">platform</option>
                <option value="tenant">tenant</option>
                <option value="user">user</option>
                <option value="team">team</option>
              </select>
              <input className="input" placeholder="Scope ID" value={scopeId} onChange={(event) => setScopeId(event.target.value)} />
              <button className="ghost sm" onClick={() => void refreshActiveTab()} disabled={loading}>Apply</button>
            </div>
          </div>
          {refs.length === 0 ? (
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
              {refs.map((item) => (
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
      )}

      {createOpen && (
        <div className="modal-backdrop" onClick={loading ? undefined : () => setCreateOpen(false)}>
          <section className="modal" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <h3>Create store</h3>
            <div className="form-grid">
              <label>
                Name
                <input ref={modalFirstFieldRef} className="input" value={createForm.name} onChange={(event) => setCreateForm({ ...createForm, name: event.target.value })} />
              </label>
              <label>
                Kind
                <select value={createForm.kind} disabled>
                  <option value="aws_secrets_manager">aws_secrets_manager</option>
                </select>
              </label>
              <label>
                AWS region
                <input
                  className="input"
                  value={createForm.config_json?.aws_region || ""}
                  onChange={(event) => setCreateForm({ ...createForm, config_json: { ...createForm.config_json, aws_region: event.target.value } })}
                />
              </label>
              <label>
                Name prefix
                <input
                  className="input"
                  value={createForm.config_json?.name_prefix || ""}
                  onChange={(event) => setCreateForm({ ...createForm, config_json: { ...createForm.config_json, name_prefix: event.target.value } })}
                />
              </label>
              <label>
                KMS key ID (optional)
                <input
                  className="input"
                  value={createForm.config_json?.kms_key_id || ""}
                  onChange={(event) => setCreateForm({ ...createForm, config_json: { ...createForm.config_json, kms_key_id: event.target.value } })}
                />
              </label>
              <label>
                Default
                <select value={createForm.is_default ? "yes" : "no"} onChange={(event) => setCreateForm({ ...createForm, is_default: event.target.value === "yes" })}>
                  <option value="no">No</option>
                  <option value="yes">Yes</option>
                </select>
              </label>
              <label className="full">
                Tags JSON
                <textarea className="input" rows={6} value={createTagsText} onChange={(event) => setCreateTagsText(event.target.value)} />
              </label>
            </div>
            <div className="inline-actions">
              <button className="primary" onClick={() => void handleCreateStore()} disabled={loading || !createForm.name.trim()}>
                {loading ? "Creating..." : "Create store"}
              </button>
              <button className="ghost" onClick={() => setCreateOpen(false)} disabled={loading}>
                Cancel
              </button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
