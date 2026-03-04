import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import Tabs from "../components/ui/Tabs";
import {
  createAiAgent,
  createAiCredential,
  createAiModelConfig,
  createAiPurpose,
  deleteAiAgent,
  deleteAiCredential,
  deleteAiModelConfig,
  deleteAiPurpose,
  listAiAgents,
  listAiCredentials,
  listAiModelConfigs,
  listAiProviders,
  listAiPurposes,
  listContextPacks,
  updateAiAgent,
  updateAiCredential,
  updateAiModelConfig,
  updateAiPurpose,
} from "../../api/xyn";
import type { AiAgent, AiCredential, AiModelConfig, AiProvider, AiPurpose, ContextPackSummary } from "../../api/types";
import { useNotifications } from "../state/notificationsStore";

type AiConfigTab = "credentials" | "model-configs" | "agents" | "purposes";
type CreateModalType = AiConfigTab | null;

const AI_TABS: Array<{ value: AiConfigTab; label: string }> = [
  { value: "agents", label: "Agents" },
  { value: "credentials", label: "Credentials" },
  { value: "model-configs", label: "Model Configs" },
  { value: "purposes", label: "Purposes" },
];
const PURPOSE_SLUG_RE = /^[a-z0-9][a-z0-9-]{1,62}$/;
const PREAMBLE_MAX = 1000;

function toCreateLabel(tab: AiConfigTab): string {
  if (tab === "credentials") return "Create credential";
  if (tab === "model-configs") return "Create model config";
  if (tab === "agents") return "Create agent";
  return "Create purpose";
}

function slugifyPurpose(value: string): string {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 63);
}

function slugifyAgent(value: string): string {
  return slugifyPurpose(value);
}

type AgentEditForm = {
  id: string;
  slug: string;
  name: string;
  model_config_id: string;
  override_prompt_text: string;
  default_context_pack_refs_json: Array<{ id: string }>;
  purposes: string[];
  enabled: boolean;
  is_default: boolean;
};

type ModelConfigEditForm = {
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

export default function AIConfigPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { push } = useNotifications();
  const createButtonRef = useRef<HTMLButtonElement | null>(null);
  const modalFirstFieldRef = useRef<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement | null>(null);

  const tabParam = String(searchParams.get("tab") || "").trim();
  const activeTab: AiConfigTab = (AI_TABS.find((item) => item.value === tabParam)?.value || "agents") as AiConfigTab;

  useEffect(() => {
    if (tabParam && AI_TABS.some((item) => item.value === tabParam)) return;
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set("tab", "agents");
    setSearchParams(nextParams, { replace: true });
  }, [searchParams, setSearchParams, tabParam]);

  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [createModal, setCreateModal] = useState<CreateModalType>(null);
  const [returnToCreate, setReturnToCreate] = useState<CreateModalType>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [providers, setProviders] = useState<AiProvider[]>([]);
  const [credentials, setCredentials] = useState<AiCredential[]>([]);
  const [modelConfigs, setModelConfigs] = useState<AiModelConfig[]>([]);
  const [purposes, setPurposes] = useState<AiPurpose[]>([]);
  const [contextPacks, setContextPacks] = useState<ContextPackSummary[]>([]);
  const [agents, setAgents] = useState<AiAgent[]>([]);

  const [filterPurpose, setFilterPurpose] = useState("all");

  const [selectedCredentialId, setSelectedCredentialId] = useState<string | null>(null);
  const [selectedModelConfigId, setSelectedModelConfigId] = useState<string | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [selectedPurposeSlug, setSelectedPurposeSlug] = useState<string | null>(null);

  const [modelConfigEdit, setModelConfigEdit] = useState<ModelConfigEditForm | null>(null);
  const [agentEdit, setAgentEdit] = useState<AgentEditForm | null>(null);
  const [purposeEdit, setPurposeEdit] = useState<AiPurpose | null>(null);

  const [createCredentialForm, setCreateCredentialForm] = useState({
    provider: "openai" as "openai" | "anthropic" | "google",
    name: "",
    auth_type: "api_key" as "api_key" | "env_ref",
    api_key: "",
    env_var_name: "",
  });
  const [createModelForm, setCreateModelForm] = useState({
    provider: "openai" as "openai" | "anthropic" | "google",
    credential_id: "",
    model_name: "",
    temperature: "0.2",
    max_tokens: "1200",
    top_p: "1",
    frequency_penalty: "0",
    presence_penalty: "0",
  });
  const [createAgentForm, setCreateAgentForm] = useState({
    name: "",
    slug: "",
    model_config_id: "",
    purposes: [] as string[],
    default_context_pack_refs_json: [] as Array<{ id: string }>,
    override_prompt_text: "",
  });
  const [agentSlugEdited, setAgentSlugEdited] = useState(false);
  const [createPurposeForm, setCreatePurposeForm] = useState({
    name: "",
    slug: "",
    description: "",
    status: "active" as "active" | "deprecated",
    preamble: "",
  });
  const [purposeSlugEdited, setPurposeSlugEdited] = useState(false);

  const openCreateModal = (target: CreateModalType) => setCreateModal(target);
  const closeCreateModal = useCallback(() => {
    setCreateModal(null);
    setReturnToCreate(null);
    window.setTimeout(() => createButtonRef.current?.focus(), 0);
  }, []);

  useEffect(() => {
    if (!createModal) return;
    const timer = window.setTimeout(() => modalFirstFieldRef.current?.focus(), 0);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !saving) {
        event.preventDefault();
        closeCreateModal();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [closeCreateModal, createModal, saving]);

  const updateTab = (next: AiConfigTab) => {
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set("tab", next);
    setSearchParams(nextParams, { replace: true });
  };

  const syncSelections = useCallback(() => {
    setSelectedCredentialId((prev) => (prev && credentials.some((item) => item.id === prev) ? prev : credentials[0]?.id || null));
    setSelectedModelConfigId((prev) => (prev && modelConfigs.some((item) => item.id === prev) ? prev : modelConfigs[0]?.id || null));
    setSelectedAgentId((prev) => (prev && agents.some((item) => item.id === prev) ? prev : agents[0]?.id || null));
    setSelectedPurposeSlug((prev) => (prev && purposes.some((item) => item.slug === prev) ? prev : purposes[0]?.slug || null));
  }, [agents, credentials, modelConfigs, purposes]);

  const loadCredentials = useCallback(async () => {
    const [providerRes, credRes] = await Promise.all([listAiProviders(), listAiCredentials()]);
    setProviders(providerRes.providers || []);
    setCredentials(credRes.credentials || []);
  }, []);

  const loadModelConfigs = useCallback(async () => {
    const [providerRes, credRes, modelRes] = await Promise.all([listAiProviders(), listAiCredentials(), listAiModelConfigs()]);
    setProviders(providerRes.providers || []);
    setCredentials(credRes.credentials || []);
    setModelConfigs(modelRes.model_configs || []);
  }, []);

  const loadAgents = useCallback(async () => {
    const [purposeRes, modelRes, agentRes, packRes] = await Promise.all([
      listAiPurposes(),
      listAiModelConfigs(),
      listAiAgents(filterPurpose !== "all" ? { purpose: filterPurpose } : undefined),
      listContextPacks(),
    ]);
    const normalizedPurposes = (purposeRes.purposes || []).map((item) => ({ ...item, status: item.status || (item.enabled ? "active" : "deprecated") }));
    setPurposes(normalizedPurposes);
    setModelConfigs(modelRes.model_configs || []);
    setAgents(agentRes.agents || []);
    setContextPacks(packRes.context_packs || []);
  }, [filterPurpose]);

  const loadPurposes = useCallback(async () => {
    const purposeRes = await listAiPurposes();
    const normalizedPurposes = (purposeRes.purposes || []).map((item) => ({ ...item, status: item.status || (item.enabled ? "active" : "deprecated") }));
    setPurposes(normalizedPurposes);
  }, []);

  const refreshActiveTab = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      if (activeTab === "credentials") await loadCredentials();
      if (activeTab === "model-configs") await loadModelConfigs();
      if (activeTab === "agents") await loadAgents();
      if (activeTab === "purposes") await loadPurposes();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [activeTab, loadAgents, loadCredentials, loadModelConfigs, loadPurposes]);

  useEffect(() => {
    void refreshActiveTab();
  }, [refreshActiveTab]);

  useEffect(() => {
    syncSelections();
  }, [syncSelections]);

  useEffect(() => {
    const selected = modelConfigs.find((item) => item.id === selectedModelConfigId) || null;
    if (!selected) {
      setModelConfigEdit(null);
      return;
    }
    setModelConfigEdit({
      id: selected.id,
      provider: selected.provider,
      credential_id: selected.credential_id || "",
      model_name: selected.model_name || "",
      temperature: String(selected.temperature ?? 0.2),
      max_tokens: String(selected.max_tokens ?? 1200),
      top_p: String(selected.top_p ?? 1),
      frequency_penalty: String(selected.frequency_penalty ?? 0),
      presence_penalty: String(selected.presence_penalty ?? 0),
      enabled: Boolean(selected.enabled),
    });
  }, [modelConfigs, selectedModelConfigId]);

  useEffect(() => {
    const selected = agents.find((item) => item.id === selectedAgentId) || null;
    if (!selected) {
      setAgentEdit(null);
      return;
    }
    setAgentEdit({
      id: selected.id,
      slug: selected.slug,
      name: selected.name,
      model_config_id: selected.model_config_id,
      override_prompt_text: selected.override_prompt_text || selected.system_prompt_text || "",
      default_context_pack_refs_json: (
        Array.isArray(selected.default_context_pack_refs_json)
          ? selected.default_context_pack_refs_json
          : Array.isArray(selected.context_pack_refs_json)
            ? selected.context_pack_refs_json
            : []
      )
        .map((entry) => {
          if (!entry || typeof entry !== "object") return null;
          const id = String((entry as { id?: string }).id || "").trim();
          return id ? { id } : null;
        })
        .filter((entry): entry is { id: string } => Boolean(entry?.id)),
      purposes: selected.purposes || [],
      enabled: selected.enabled,
      is_default: Boolean(selected.is_default),
    });
  }, [agents, selectedAgentId]);

  useEffect(() => {
    const selected = purposes.find((item) => item.slug === selectedPurposeSlug) || null;
    setPurposeEdit(selected);
  }, [purposes, selectedPurposeSlug]);

  const selectedCredential = useMemo(() => credentials.find((item) => item.id === selectedCredentialId) || null, [credentials, selectedCredentialId]);
  const selectedModelConfig = useMemo(() => modelConfigs.find((item) => item.id === selectedModelConfigId) || null, [modelConfigs, selectedModelConfigId]);
  const selectedAgent = useMemo(() => agents.find((item) => item.id === selectedAgentId) || null, [agents, selectedAgentId]);

  const filteredPurposes = useMemo(
    () => purposes.filter((item) => (item.status || "active") === "active"),
    [purposes]
  );

  const onCreateCredential = async () => {
    try {
      setSaving(true);
      setError(null);
      const result = await createAiCredential({
        provider: createCredentialForm.provider,
        name: createCredentialForm.name.trim(),
        auth_type: createCredentialForm.auth_type,
        api_key: createCredentialForm.auth_type === "api_key" ? createCredentialForm.api_key : undefined,
        env_var_name: createCredentialForm.auth_type === "env_ref" ? createCredentialForm.env_var_name : undefined,
        enabled: true,
      });
      const createdId = result.credential.id;
      await loadCredentials();
      setSelectedCredentialId(createdId);
      push({ level: "success", title: "Credential created", message: result.credential.name });
      setCreateCredentialForm((prev) => ({ ...prev, name: "", api_key: "", env_var_name: "" }));
      if (returnToCreate === "model-configs") {
        setCreateModelForm((prev) => ({ ...prev, credential_id: createdId, provider: result.credential.provider }));
        setCreateModal("model-configs");
        setReturnToCreate(null);
      } else {
        closeCreateModal();
      }
    } catch (err) {
      const msg = (err as Error).message;
      setError(msg);
      push({ level: "error", title: "Create credential failed", message: msg });
    } finally {
      setSaving(false);
    }
  };

  const onCreateModelConfig = async () => {
    try {
      setSaving(true);
      setError(null);
      const result = await createAiModelConfig({
        provider: createModelForm.provider,
        credential_id: createModelForm.credential_id || undefined,
        model_name: createModelForm.model_name.trim(),
        temperature: Number(createModelForm.temperature),
        max_tokens: Number(createModelForm.max_tokens),
        top_p: Number(createModelForm.top_p),
        frequency_penalty: Number(createModelForm.frequency_penalty),
        presence_penalty: Number(createModelForm.presence_penalty),
        enabled: true,
      });
      const createdId = result.model_config.id;
      await loadModelConfigs();
      setSelectedModelConfigId(createdId);
      push({ level: "success", title: "Model config created", message: result.model_config.model_name });
      setCreateModelForm((prev) => ({ ...prev, model_name: "" }));
      if (returnToCreate === "agents") {
        setCreateAgentForm((prev) => ({ ...prev, model_config_id: createdId }));
        setCreateModal("agents");
        setReturnToCreate(null);
      } else {
        closeCreateModal();
      }
    } catch (err) {
      const msg = (err as Error).message;
      setError(msg);
      push({ level: "error", title: "Create model config failed", message: msg });
    } finally {
      setSaving(false);
    }
  };

  const onCreateAgent = async () => {
    try {
      setSaving(true);
      setError(null);
      const result = await createAiAgent({
        slug: createAgentForm.slug.trim(),
        name: createAgentForm.name.trim(),
        model_config_id: createAgentForm.model_config_id,
        purposes: createAgentForm.purposes,
        default_context_pack_refs_json: createAgentForm.default_context_pack_refs_json,
        override_prompt_text: createAgentForm.override_prompt_text,
        enabled: true,
      });
      await loadAgents();
      setSelectedAgentId(result.agent.id);
      push({ level: "success", title: "Agent created", message: result.agent.name });
      setCreateAgentForm((prev) => ({
        ...prev,
        name: "",
        slug: "",
        override_prompt_text: "",
        default_context_pack_refs_json: [],
      }));
      setAgentSlugEdited(false);
      closeCreateModal();
    } catch (err) {
      const msg = (err as Error).message;
      setError(msg);
      push({ level: "error", title: "Create agent failed", message: msg });
    } finally {
      setSaving(false);
    }
  };

  const onCreatePurpose = async () => {
    try {
      setSaving(true);
      setError(null);
      const result = await createAiPurpose({
        slug: createPurposeForm.slug.trim(),
        name: createPurposeForm.name.trim(),
        description: createPurposeForm.description.trim(),
        status: createPurposeForm.status,
        preamble: createPurposeForm.preamble.slice(0, PREAMBLE_MAX),
      });
      await loadPurposes();
      setSelectedPurposeSlug(result.purpose.slug);
      push({ level: "success", title: "Purpose created", message: result.purpose.slug });
      setCreatePurposeForm({ name: "", slug: "", description: "", status: "active", preamble: "" });
      setPurposeSlugEdited(false);
      closeCreateModal();
    } catch (err) {
      const msg = (err as Error).message;
      setError(msg);
      push({ level: "error", title: "Create purpose failed", message: msg });
    } finally {
      setSaving(false);
    }
  };

  const renderCredentialsTab = () => (
    <section className="card">
      <div className="card-header"><h3>Credentials</h3></div>
      <div className="instance-list">
        {credentials.map((item) => (
          <button key={item.id} type="button" className={`instance-row ${selectedCredentialId === item.id ? "selected" : ""}`} onClick={() => setSelectedCredentialId(item.id)}>
            <div>
              <strong>{item.name}</strong>
              <span className="muted small">{item.provider} · {item.auth_type} · {item.secret?.masked || "not configured"}{item.is_default ? " · default" : ""}</span>
            </div>
            <span className="muted">{item.enabled ? "enabled" : "disabled"}</span>
          </button>
        ))}
        {!credentials.length && <p className="muted">No credentials configured.</p>}
      </div>
      {selectedCredential && (
        <div className="inline-actions">
          <button className="ghost" onClick={async () => {
            await updateAiCredential(selectedCredential.id, { enabled: !selectedCredential.enabled });
            await loadCredentials();
          }}>
            {selectedCredential.enabled ? "Disable" : "Enable"}
          </button>
          <button className="danger" onClick={async () => {
            if (!window.confirm(`Delete credential '${selectedCredential.name}'?`)) return;
            await deleteAiCredential(selectedCredential.id);
            await loadCredentials();
          }}>
            Delete
          </button>
        </div>
      )}
    </section>
  );

  const renderModelConfigsTab = () => (
    <div className="layout">
      <section className="card">
        <div className="card-header"><h3>Model configs</h3></div>
        <div className="instance-list">
          {modelConfigs.map((item) => (
            <button key={item.id} type="button" className={`instance-row ${selectedModelConfigId === item.id ? "selected" : ""}`} onClick={() => setSelectedModelConfigId(item.id)}>
              <div>
                <strong>{item.model_name}</strong>
                <span className="muted small">{item.provider} · max {item.max_tokens ?? "n/a"}</span>
              </div>
              <span className="muted">{item.enabled ? "active" : "deprecated"}</span>
            </button>
          ))}
          {!modelConfigs.length && <p className="muted">No model configs configured.</p>}
        </div>
      </section>
      <section className="card">
        <div className="card-header"><h3>Model config detail</h3></div>
        {!selectedModelConfig || !modelConfigEdit ? (
          <p className="muted">Select a model config.</p>
        ) : (
          <>
            <div className="form-grid">
              <label>Provider
                <select value={modelConfigEdit.provider} onChange={(event) => setModelConfigEdit({ ...modelConfigEdit, provider: event.target.value as "openai" | "anthropic" | "google", credential_id: "" })}>
                  {providers.map((provider) => <option key={provider.slug} value={provider.slug}>{provider.name}</option>)}
                </select>
              </label>
              <label>Credential (optional)
                <select value={modelConfigEdit.credential_id} onChange={(event) => setModelConfigEdit({ ...modelConfigEdit, credential_id: event.target.value })}>
                  <option value="">None (env fallback)</option>
                  {credentials.filter((item) => item.provider === modelConfigEdit.provider).map((credential) => (
                    <option key={credential.id} value={credential.id}>{credential.name}</option>
                  ))}
                </select>
              </label>
              <label>Model name
                <input className="input" value={modelConfigEdit.model_name} onChange={(event) => setModelConfigEdit({ ...modelConfigEdit, model_name: event.target.value })} />
              </label>
              <label>Temperature
                <input className="input" value={modelConfigEdit.temperature} onChange={(event) => setModelConfigEdit({ ...modelConfigEdit, temperature: event.target.value })} />
              </label>
              <label>Top P
                <input className="input" value={modelConfigEdit.top_p} onChange={(event) => setModelConfigEdit({ ...modelConfigEdit, top_p: event.target.value })} />
              </label>
              <label>Max tokens
                <input className="input" value={modelConfigEdit.max_tokens} onChange={(event) => setModelConfigEdit({ ...modelConfigEdit, max_tokens: event.target.value })} />
              </label>
              <label>Frequency penalty
                <input className="input" value={modelConfigEdit.frequency_penalty} onChange={(event) => setModelConfigEdit({ ...modelConfigEdit, frequency_penalty: event.target.value })} />
              </label>
              <label>Presence penalty
                <input className="input" value={modelConfigEdit.presence_penalty} onChange={(event) => setModelConfigEdit({ ...modelConfigEdit, presence_penalty: event.target.value })} />
              </label>
              <label>Status
                <select value={modelConfigEdit.enabled ? "active" : "deprecated"} onChange={(event) => setModelConfigEdit({ ...modelConfigEdit, enabled: event.target.value === "active" })}>
                  <option value="active">Active</option>
                  <option value="deprecated">Deprecated</option>
                </select>
              </label>
            </div>
            <div className="inline-actions">
              <button className="primary" onClick={async () => {
                await updateAiModelConfig(modelConfigEdit.id, {
                  provider: modelConfigEdit.provider,
                  credential_id: modelConfigEdit.credential_id || null,
                  model_name: modelConfigEdit.model_name.trim(),
                  temperature: Number(modelConfigEdit.temperature),
                  max_tokens: Number(modelConfigEdit.max_tokens),
                  top_p: Number(modelConfigEdit.top_p),
                  frequency_penalty: Number(modelConfigEdit.frequency_penalty),
                  presence_penalty: Number(modelConfigEdit.presence_penalty),
                  enabled: modelConfigEdit.enabled,
                });
                await loadModelConfigs();
              }} disabled={!modelConfigEdit.model_name.trim()}>
                Save changes
              </button>
              <button className="danger" onClick={async () => {
                if (!window.confirm(`Deprecate model config '${selectedModelConfig.model_name}'?`)) return;
                await deleteAiModelConfig(selectedModelConfig.id);
                await loadModelConfigs();
              }}>
                Deprecate
              </button>
            </div>
          </>
        )}
      </section>
    </div>
  );

  const renderAgentsTab = () => (
    <div className="layout">
      <section className="card">
        <div className="card-header">
          <h3>Agents</h3>
          <select value={filterPurpose} onChange={(event) => setFilterPurpose(event.target.value)}>
            <option value="all">All purposes</option>
            {filteredPurposes.map((purpose) => (
              <option key={purpose.slug} value={purpose.slug}>{purpose.slug}</option>
            ))}
          </select>
        </div>
        <div className="instance-list">
          {agents.map((item) => (
            <button key={item.id} type="button" className={`instance-row ${selectedAgentId === item.id ? "selected" : ""}`} onClick={() => setSelectedAgentId(item.id)}>
              <div>
                <strong>{item.name}</strong>
                <span className="muted small">
                  {item.slug} · {item.model_config?.provider}:{item.model_config?.model_name} · {(item.purposes || []).join(", ") || "no purposes"} · defaults {(item.default_context_packs || []).length}
                </span>
              </div>
              <span className="muted">{item.enabled ? "enabled" : "disabled"}</span>
            </button>
          ))}
          {!agents.length && <p className="muted">No agents configured.</p>}
        </div>
      </section>
      <section className="card">
        <div className="card-header"><h3>Agent detail</h3></div>
        {!selectedAgent || !agentEdit ? (
          <p className="muted">Select an agent.</p>
        ) : (
          <>
            <div className="form-grid">
              <label>Slug
                <input className="input" value={agentEdit.slug} disabled />
              </label>
              <label>Name
                <input className="input" value={agentEdit.name} onChange={(event) => setAgentEdit({ ...agentEdit, name: event.target.value })} />
              </label>
              <label>Model config
                <select value={agentEdit.model_config_id} onChange={(event) => setAgentEdit({ ...agentEdit, model_config_id: event.target.value })}>
                  {modelConfigs.map((item) => (
                    <option key={item.id} value={item.id}>{item.provider}:{item.model_name}</option>
                  ))}
                </select>
              </label>
              <label>Purposes (multi-select)
                <select multiple className="input" value={agentEdit.purposes} onChange={(event) => setAgentEdit({ ...agentEdit, purposes: Array.from(event.target.selectedOptions).map((option) => option.value) })}>
                  {filteredPurposes.map((purpose) => (
                    <option key={purpose.slug} value={purpose.slug}>{purpose.slug}</option>
                  ))}
                </select>
              </label>
              <label>Enabled
                <select value={agentEdit.enabled ? "yes" : "no"} onChange={(event) => setAgentEdit({ ...agentEdit, enabled: event.target.value === "yes" })}>
                  <option value="yes">Yes</option>
                  <option value="no">No</option>
                </select>
              </label>
              <label>Default agent
                <select value={agentEdit.is_default ? "yes" : "no"} onChange={(event) => setAgentEdit({ ...agentEdit, is_default: event.target.value === "yes" })}>
                  <option value="yes">Yes</option>
                  <option value="no">No</option>
                </select>
              </label>
              <label>Default context packs
                <select
                  multiple
                  className="input"
                  value={agentEdit.default_context_pack_refs_json.map((entry) => entry.id)}
                  onChange={(event) =>
                    setAgentEdit({
                      ...agentEdit,
                      default_context_pack_refs_json: Array.from(event.target.selectedOptions).map((option) => ({ id: option.value })),
                    })
                  }
                >
                  {contextPacks.map((pack) => (
                    <option key={pack.id} value={pack.id}>
                      {pack.name} · v{pack.version} · {pack.is_active ? "canonical" : "deprecated"}
                    </option>
                  ))}
                </select>
              </label>
              <label>Override prompt (advanced / not recommended)
                <textarea className="input" rows={8} value={agentEdit.override_prompt_text} onChange={(event) => setAgentEdit({ ...agentEdit, override_prompt_text: event.target.value })} />
              </label>
            </div>
            <div className="inline-actions">
              <button className="primary" onClick={async () => {
                await updateAiAgent(agentEdit.id, {
                  name: agentEdit.name.trim(),
                  model_config_id: agentEdit.model_config_id,
                  override_prompt_text: agentEdit.override_prompt_text,
                  default_context_pack_refs_json: agentEdit.default_context_pack_refs_json,
                  purposes: agentEdit.purposes,
                  enabled: agentEdit.enabled,
                  is_default: agentEdit.is_default,
                });
                await loadAgents();
              }} disabled={!agentEdit.name.trim() || !agentEdit.model_config_id}>
                Save changes
              </button>
              <button className="danger" onClick={async () => {
                if (!window.confirm(`Delete agent '${selectedAgent.name}'?`)) return;
                await deleteAiAgent(selectedAgent.id);
                await loadAgents();
              }}>
                Delete agent
              </button>
            </div>
          </>
        )}
      </section>
    </div>
  );

  const renderPurposesTab = () => (
    <div className="layout">
      <section className="card">
        <div className="card-header"><h3>Purposes</h3></div>
        <div className="instance-list">
          {purposes.map((item) => (
            <button key={item.slug} type="button" className={`instance-row ${selectedPurposeSlug === item.slug ? "selected" : ""}`} onClick={() => setSelectedPurposeSlug(item.slug)}>
              <div>
                <strong>{item.name || item.slug}</strong>
                <span className="muted small">{item.slug}</span>
              </div>
              <span className="muted">{item.status || "active"}</span>
            </button>
          ))}
          {!purposes.length && <p className="muted">No purposes configured.</p>}
        </div>
      </section>
      <section className="card">
        <div className="card-header"><h3>Purpose detail</h3></div>
        {!purposeEdit ? (
          <p className="muted">Select a purpose.</p>
        ) : (
          <>
            <div className="form-grid">
              <label>Slug
                <input className="input" value={purposeEdit.slug} disabled />
              </label>
              <label>Name
                <input className="input" value={purposeEdit.name || ""} onChange={(event) => setPurposeEdit({ ...purposeEdit, name: event.target.value })} />
              </label>
              <label>Description
                <input className="input" value={purposeEdit.description || ""} onChange={(event) => setPurposeEdit({ ...purposeEdit, description: event.target.value })} />
              </label>
              <label>Status
                <select value={purposeEdit.status || "active"} onChange={(event) => setPurposeEdit({ ...purposeEdit, status: event.target.value as "active" | "deprecated" })}>
                  <option value="active">Active</option>
                  <option value="deprecated">Deprecated</option>
                </select>
              </label>
              <label>Preamble
                <textarea className="input" rows={10} maxLength={PREAMBLE_MAX} value={purposeEdit.preamble || ""} onChange={(event) => setPurposeEdit({ ...purposeEdit, preamble: event.target.value })} />
              </label>
            </div>
            <div className="inline-actions">
              <button className="primary" onClick={async () => {
                await updateAiPurpose(purposeEdit.slug, {
                  name: purposeEdit.name || "",
                  description: purposeEdit.description || "",
                  status: purposeEdit.status || "active",
                  preamble: (purposeEdit.preamble || "").slice(0, PREAMBLE_MAX),
                });
                await loadPurposes();
              }}>
                Save changes
              </button>
              <button className="danger" onClick={async () => {
                if (!window.confirm(`Deprecate purpose '${purposeEdit.slug}'?`)) return;
                await deleteAiPurpose(purposeEdit.slug);
                await loadPurposes();
              }}>
                Deprecate
              </button>
            </div>
          </>
        )}
      </section>
    </div>
  );

  return (
    <>
      <div className="page-header">
        <div>
          <h2>AI Agents</h2>
          <p className="muted">Manage credentials, model configs, agents, and purposes.</p>
        </div>
        <div className="inline-actions">
          <button ref={createButtonRef} className="primary" onClick={() => openCreateModal(activeTab)}>{toCreateLabel(activeTab)}</button>
          <button className="ghost" onClick={() => void refreshActiveTab()} disabled={loading}>{loading ? "Refreshing..." : "Refresh"}</button>
        </div>
      </div>
      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {message && <InlineMessage tone="info" title="Update" body={message} />}

      <div className="page-tabs">
        <Tabs
          ariaLabel="AI Agents tabs"
          value={activeTab}
          onChange={updateTab}
          options={AI_TABS.map((item) => ({ value: item.value, label: item.label }))}
        />
      </div>

      {activeTab === "credentials" && renderCredentialsTab()}
      {activeTab === "model-configs" && renderModelConfigsTab()}
      {activeTab === "agents" && renderAgentsTab()}
      {activeTab === "purposes" && renderPurposesTab()}

      {createModal && (
        <div className="modal-backdrop" onClick={saving ? undefined : closeCreateModal}>
          <section className="modal" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            {createModal === "credentials" && (
              <>
                <h3>Create credential</h3>
                <div className="form-grid">
                  <label>Provider
                    <select ref={modalFirstFieldRef as React.RefObject<HTMLSelectElement>} value={createCredentialForm.provider} onChange={(event) => setCreateCredentialForm((prev) => ({ ...prev, provider: event.target.value as "openai" | "anthropic" | "google" }))}>
                      {(providers.length ? providers : [{ slug: "openai", name: "OpenAI" }, { slug: "anthropic", name: "Anthropic" }, { slug: "google", name: "Google" }]).map((provider) => (
                        <option key={provider.slug} value={provider.slug}>{provider.name}</option>
                      ))}
                    </select>
                  </label>
                  <label>Name
                    <input className="input" value={createCredentialForm.name} onChange={(event) => setCreateCredentialForm((prev) => ({ ...prev, name: event.target.value }))} />
                  </label>
                  <label>Auth type
                    <select value={createCredentialForm.auth_type} onChange={(event) => setCreateCredentialForm((prev) => ({ ...prev, auth_type: event.target.value as "api_key" | "env_ref" }))}>
                      <option value="api_key">api_key</option>
                      <option value="env_ref">env_ref</option>
                    </select>
                  </label>
                  {createCredentialForm.auth_type === "api_key" ? (
                    <label>API key
                      <input className="input" type="password" value={createCredentialForm.api_key} onChange={(event) => setCreateCredentialForm((prev) => ({ ...prev, api_key: event.target.value }))} />
                    </label>
                  ) : (
                    <label>Env var name
                      <input className="input" value={createCredentialForm.env_var_name} onChange={(event) => setCreateCredentialForm((prev) => ({ ...prev, env_var_name: event.target.value }))} />
                    </label>
                  )}
                </div>
                <div className="inline-actions" style={{ marginTop: 12 }}>
                  <button className="ghost" onClick={closeCreateModal} disabled={saving}>Cancel</button>
                  <button className="primary" onClick={() => void onCreateCredential()} disabled={saving || !createCredentialForm.name.trim()}>
                    {saving ? "Creating..." : "Create credential"}
                  </button>
                </div>
              </>
            )}
            {createModal === "model-configs" && (
              <>
                <h3>Create model config</h3>
                <div className="form-grid">
                  <label>Provider
                    <select ref={modalFirstFieldRef as React.RefObject<HTMLSelectElement>} value={createModelForm.provider} onChange={(event) => setCreateModelForm((prev) => ({ ...prev, provider: event.target.value as "openai" | "anthropic" | "google", credential_id: "" }))}>
                      {(providers.length ? providers : [{ slug: "openai", name: "OpenAI" }, { slug: "anthropic", name: "Anthropic" }, { slug: "google", name: "Google" }]).map((provider) => (
                        <option key={provider.slug} value={provider.slug}>{provider.name}</option>
                      ))}
                    </select>
                  </label>
                  <label>Credential (optional)
                    <select value={createModelForm.credential_id} onChange={(event) => setCreateModelForm((prev) => ({ ...prev, credential_id: event.target.value }))}>
                      <option value="">None (env fallback)</option>
                      {credentials.filter((item) => item.provider === createModelForm.provider).map((credential) => (
                        <option key={credential.id} value={credential.id}>{credential.name}</option>
                      ))}
                    </select>
                  </label>
                  <button type="button" className="ghost sm" onClick={() => { setReturnToCreate("model-configs"); setCreateModal("credentials"); }}>
                    Add credential
                  </button>
                  <label>Model name
                    <input className="input" value={createModelForm.model_name} onChange={(event) => setCreateModelForm((prev) => ({ ...prev, model_name: event.target.value }))} />
                  </label>
                  <label>Temperature
                    <input className="input" value={createModelForm.temperature} onChange={(event) => setCreateModelForm((prev) => ({ ...prev, temperature: event.target.value }))} />
                  </label>
                  <label>Max tokens
                    <input className="input" value={createModelForm.max_tokens} onChange={(event) => setCreateModelForm((prev) => ({ ...prev, max_tokens: event.target.value }))} />
                  </label>
                  <label>Top P
                    <input className="input" value={createModelForm.top_p} onChange={(event) => setCreateModelForm((prev) => ({ ...prev, top_p: event.target.value }))} />
                  </label>
                  <label>Frequency penalty
                    <input className="input" value={createModelForm.frequency_penalty} onChange={(event) => setCreateModelForm((prev) => ({ ...prev, frequency_penalty: event.target.value }))} />
                  </label>
                  <label>Presence penalty
                    <input className="input" value={createModelForm.presence_penalty} onChange={(event) => setCreateModelForm((prev) => ({ ...prev, presence_penalty: event.target.value }))} />
                  </label>
                </div>
                <div className="inline-actions" style={{ marginTop: 12 }}>
                  <button className="ghost" onClick={closeCreateModal} disabled={saving}>Cancel</button>
                  <button className="primary" onClick={() => void onCreateModelConfig()} disabled={saving || !createModelForm.model_name.trim()}>
                    {saving ? "Creating..." : "Create model config"}
                  </button>
                </div>
              </>
            )}
            {createModal === "agents" && (
              <>
                <h3>Create agent</h3>
                <div className="form-grid">
                  <label>Name
                    <input
                      ref={modalFirstFieldRef as React.RefObject<HTMLInputElement>}
                      className="input"
                      value={createAgentForm.name}
                      onChange={(event) => {
                        const name = event.target.value;
                        setCreateAgentForm((prev) => ({ ...prev, name, slug: agentSlugEdited ? prev.slug : slugifyAgent(name) }));
                      }}
                    />
                  </label>
                  <label>Slug
                    <input className="input" value={createAgentForm.slug} onChange={(event) => { setAgentSlugEdited(true); setCreateAgentForm((prev) => ({ ...prev, slug: slugifyAgent(event.target.value) })); }} />
                  </label>
                  <label>Model config
                    <select value={createAgentForm.model_config_id} onChange={(event) => setCreateAgentForm((prev) => ({ ...prev, model_config_id: event.target.value }))}>
                      <option value="">Select model config</option>
                      {modelConfigs.map((item) => (
                        <option key={item.id} value={item.id}>{item.provider}:{item.model_name}</option>
                      ))}
                    </select>
                  </label>
                  <button type="button" className="ghost sm" onClick={() => { setReturnToCreate("agents"); setCreateModal("model-configs"); }}>
                    Add model config
                  </button>
                  <label>Purposes (multi-select)
                    <select multiple className="input" value={createAgentForm.purposes} onChange={(event) => setCreateAgentForm((prev) => ({ ...prev, purposes: Array.from(event.target.selectedOptions).map((option) => option.value) }))}>
                      {filteredPurposes.map((purpose) => (
                        <option key={purpose.slug} value={purpose.slug}>{purpose.slug}</option>
                      ))}
                    </select>
                  </label>
                  <label>Default context packs
                    <select
                      multiple
                      className="input"
                      value={createAgentForm.default_context_pack_refs_json.map((entry) => entry.id)}
                      onChange={(event) =>
                        setCreateAgentForm((prev) => ({
                          ...prev,
                          default_context_pack_refs_json: Array.from(event.target.selectedOptions).map((option) => ({ id: option.value })),
                        }))
                      }
                    >
                      {contextPacks.map((pack) => (
                        <option key={pack.id} value={pack.id}>
                          {pack.name} · v{pack.version} · {pack.is_active ? "canonical" : "deprecated"}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>Override prompt (advanced / not recommended)
                    <textarea
                      className="input"
                      rows={6}
                      value={createAgentForm.override_prompt_text}
                      onChange={(event) => setCreateAgentForm((prev) => ({ ...prev, override_prompt_text: event.target.value }))}
                    />
                  </label>
                </div>
                <div className="inline-actions" style={{ marginTop: 12 }}>
                  <button className="ghost" onClick={closeCreateModal} disabled={saving}>Cancel</button>
                  <button className="primary" onClick={() => void onCreateAgent()} disabled={saving || !createAgentForm.name.trim() || !createAgentForm.slug.trim() || !createAgentForm.model_config_id}>
                    {saving ? "Creating..." : "Create agent"}
                  </button>
                </div>
              </>
            )}
            {createModal === "purposes" && (
              <>
                <h3>Create purpose</h3>
                <div className="form-grid">
                  <label>Name
                    <input
                      ref={modalFirstFieldRef as React.RefObject<HTMLInputElement>}
                      className="input"
                      value={createPurposeForm.name}
                      onChange={(event) => {
                        const name = event.target.value;
                        setCreatePurposeForm((prev) => ({ ...prev, name, slug: purposeSlugEdited ? prev.slug : slugifyPurpose(name) }));
                      }}
                    />
                  </label>
                  <label>Slug
                    <input className="input" value={createPurposeForm.slug} onChange={(event) => { setPurposeSlugEdited(true); setCreatePurposeForm((prev) => ({ ...prev, slug: slugifyPurpose(event.target.value) })); }} />
                  </label>
                  <label>Description
                    <input className="input" value={createPurposeForm.description} onChange={(event) => setCreatePurposeForm((prev) => ({ ...prev, description: event.target.value }))} />
                  </label>
                  <label>Status
                    <select value={createPurposeForm.status} onChange={(event) => setCreatePurposeForm((prev) => ({ ...prev, status: event.target.value as "active" | "deprecated" }))}>
                      <option value="active">Active</option>
                      <option value="deprecated">Deprecated</option>
                    </select>
                  </label>
                  <label>Preamble
                    <textarea className="input" rows={6} maxLength={PREAMBLE_MAX} value={createPurposeForm.preamble} onChange={(event) => setCreatePurposeForm((prev) => ({ ...prev, preamble: event.target.value }))} />
                  </label>
                </div>
                <div className="inline-actions" style={{ marginTop: 12 }}>
                  <button className="ghost" onClick={closeCreateModal} disabled={saving}>Cancel</button>
                  <button className="primary" onClick={() => void onCreatePurpose()} disabled={saving || !createPurposeForm.name.trim() || !PURPOSE_SLUG_RE.test(createPurposeForm.slug)}>
                    {saving ? "Creating..." : "Create purpose"}
                  </button>
                </div>
              </>
            )}
          </section>
        </div>
      )}
    </>
  );
}
