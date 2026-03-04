import { useEffect, useMemo, useState } from "react";
import InlineMessage from "../../components/InlineMessage";
import type { AiAgent, AiModelConfig, AiPurpose } from "../../api/types";
import { createAiAgent, deleteAiAgent, invokeAi, listAiAgents, listAiModelConfigs, listAiPurposes, updateAiAgent } from "../../api/xyn";

type AgentFormState = {
  id: string;
  slug: string;
  name: string;
  model_config_id: string;
  system_prompt_text: string;
  purposes: string[];
  enabled: boolean;
  is_default: boolean;
};

function toAgentForm(item: AiAgent): AgentFormState {
  return {
    id: item.id,
    slug: item.slug,
    name: item.name,
    model_config_id: item.model_config_id,
    system_prompt_text: item.system_prompt_text || "",
    purposes: item.purposes || [],
    enabled: item.enabled,
    is_default: Boolean(item.is_default),
  };
}

export default function AIAgentsPage() {
  const [purposes, setPurposes] = useState<AiPurpose[]>([]);
  const [modelConfigs, setModelConfigs] = useState<AiModelConfig[]>([]);
  const [items, setItems] = useState<AiAgent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [filterPurpose, setFilterPurpose] = useState("all");
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<AgentFormState | null>(null);
  const [testPrompt, setTestPrompt] = useState("Reply with a short health check confirming credentials and model responsiveness.");
  const [testRunning, setTestRunning] = useState(false);
  const [testResult, setTestResult] = useState<{ provider: string; model: string; content: string } | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const [form, setForm] = useState({
    slug: "",
    name: "",
    model_config_id: "",
    system_prompt_text: "",
    purposes: ["documentation"] as string[],
  });

  const selectedAgent = useMemo(() => items.find((item) => item.id === selectedAgentId) || null, [items, selectedAgentId]);

  const load = async () => {
    try {
      setError(null);
      const [purposeData, modelData, agentData] = await Promise.all([
        listAiPurposes(),
        listAiModelConfigs(),
        listAiAgents(filterPurpose !== "all" ? { purpose: filterPurpose } : undefined),
      ]);
      const activePurposes = (purposeData.purposes || []).filter((item) => (item.status || (item.enabled ? "active" : "deprecated")) === "active");
      const nextItems = agentData.agents || [];
      setPurposes(activePurposes);
      setModelConfigs((modelData.model_configs || []).filter((item) => item.enabled));
      setItems(nextItems);
      if (!form.model_config_id && modelData.model_configs?.[0]?.id) {
        setForm((prev) => ({ ...prev, model_config_id: modelData.model_configs?.[0]?.id || "" }));
      }
      const nextSelected = selectedAgentId && nextItems.some((item) => item.id === selectedAgentId)
        ? nextItems.find((item) => item.id === selectedAgentId) || null
        : nextItems[0] || null;
      setSelectedAgentId(nextSelected?.id || null);
      setEditForm(nextSelected ? toAgentForm(nextSelected) : null);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  useEffect(() => {
    load();
  }, [filterPurpose]);

  useEffect(() => {
    setTestResult(null);
    setTestError(null);
  }, [selectedAgentId]);

  const create = async () => {
    try {
      setError(null);
      setMessage(null);
      await createAiAgent({
        slug: form.slug.trim(),
        name: form.name.trim(),
        model_config_id: form.model_config_id,
        system_prompt_text: form.system_prompt_text,
        enabled: true,
        purposes: form.purposes,
      });
      setForm({ ...form, slug: "", name: "", system_prompt_text: "" });
      setMessage("Agent created.");
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
      await updateAiAgent(editForm.id, {
        name: editForm.name.trim(),
        model_config_id: editForm.model_config_id,
        system_prompt_text: editForm.system_prompt_text,
        purposes: editForm.purposes,
        enabled: editForm.enabled,
        is_default: editForm.is_default,
      });
      setMessage("Agent updated.");
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const remove = async (item: AiAgent) => {
    if (!window.confirm(`Delete agent '${item.name}'?`)) return;
    try {
      setError(null);
      setMessage(null);
      await deleteAiAgent(item.id);
      setMessage("Agent deleted.");
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const runAgentTest = async () => {
    if (!selectedAgent || !testPrompt.trim()) return;
    try {
      setTestRunning(true);
      setTestError(null);
      setTestResult(null);
      const response = await invokeAi({
        agent_slug: selectedAgent.slug,
        messages: [{ role: "user", content: testPrompt.trim() }],
        metadata: {
          feature: "ai_agents_page_test",
          source: "platform_ai_agents",
          agent_id: selectedAgent.id,
        },
      });
      setTestResult({
        provider: response.provider,
        model: response.model,
        content: response.content || "",
      });
    } catch (err) {
      setTestError((err as Error).message || "Test invocation failed.");
    } finally {
      setTestRunning(false);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h2>AI Agents</h2>
          <p className="muted">Bind model configs + system prompts and tag by purpose.</p>
        </div>
        <div className="inline-actions">
          <select value={filterPurpose} onChange={(event) => setFilterPurpose(event.target.value)}>
            <option value="all">All purposes</option>
            {purposes.map((purpose) => (
              <option key={purpose.slug} value={purpose.slug}>{purpose.slug}</option>
            ))}
          </select>
          <button className="ghost" onClick={load}>Refresh</button>
        </div>
      </div>
      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {message && <InlineMessage tone="info" title="Update" body={message} />}

      <section className="card">
        <div className="card-header"><h3>Create agent</h3></div>
        <div className="muted small">New agents are enabled by default. Use Agent detail to modify existing agents.</div>
        <div className="form-grid">
          <label>
            Name
            <input className="input" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="Xyn Default Assistant" />
          </label>
          <label>
            Slug
            <input className="input" value={form.slug} onChange={(event) => setForm({ ...form, slug: event.target.value })} placeholder="default-assistant" />
          </label>
          <label>
            Model config
            <select value={form.model_config_id} onChange={(event) => setForm({ ...form, model_config_id: event.target.value })}>
              {modelConfigs.map((item) => (
                <option key={item.id} value={item.id}>{item.provider}:{item.model_name}</option>
              ))}
            </select>
          </label>
          <label>
            Purposes (multi-select)
            <select
              multiple
              className="input"
              value={form.purposes}
              onChange={(event) => setForm({ ...form, purposes: Array.from(event.target.selectedOptions).map((option) => option.value) })}
            >
              {purposes.map((purpose) => (
                <option key={purpose.slug} value={purpose.slug}>{purpose.slug}</option>
              ))}
            </select>
          </label>
          <label>
            System prompt
            <textarea className="input" rows={6} value={form.system_prompt_text} onChange={(event) => setForm({ ...form, system_prompt_text: event.target.value })} />
          </label>
        </div>
        <div className="inline-actions" style={{ marginTop: 12, flexWrap: "wrap" }}>
          <button className="primary" onClick={create} disabled={!form.slug.trim() || !form.name.trim() || !form.model_config_id}>Create</button>
        </div>
      </section>

      <div className="layout">
        <section className="card">
          <div className="card-header"><h3>Agents</h3></div>
          <div className="instance-list">
            {items.map((item) => (
              <button
                type="button"
                className={`instance-row ${selectedAgentId === item.id ? "selected" : ""}`}
                key={item.id}
                onClick={() => {
                  setSelectedAgentId(item.id);
                  setEditForm(toAgentForm(item));
                }}
              >
                <div>
                  <strong>{item.name}</strong>
                  <span className="muted small">{item.slug} · {item.model_config?.provider}:{item.model_config?.model_name} · {item.purposes.join(", ") || "no purposes"}{item.is_default ? " · default" : ""}</span>
                </div>
                <span className="muted">{item.enabled ? "enabled" : "disabled"}</span>
              </button>
            ))}
            {!items.length && <p className="muted">No agents configured.</p>}
          </div>
        </section>

        <section className="card">
          <div className="card-header"><h3>Agent detail</h3></div>
          {!selectedAgent || !editForm ? (
            <p className="muted">Select an agent to view and edit details.</p>
          ) : (
            <>
              <div className="form-grid">
                <label>
                  Slug
                  <input className="input" value={editForm.slug} disabled />
                </label>
                <label>
                  Name
                  <input className="input" value={editForm.name} onChange={(event) => setEditForm({ ...editForm, name: event.target.value })} />
                </label>
                <label>
                  Model config
                  <select value={editForm.model_config_id} onChange={(event) => setEditForm({ ...editForm, model_config_id: event.target.value })}>
                    {modelConfigs.map((item) => (
                      <option key={item.id} value={item.id}>{item.provider}:{item.model_name}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Purposes (multi-select)
                  <select
                    multiple
                    className="input"
                    value={editForm.purposes}
                    onChange={(event) => setEditForm({ ...editForm, purposes: Array.from(event.target.selectedOptions).map((option) => option.value) })}
                  >
                    {purposes.map((purpose) => (
                      <option key={purpose.slug} value={purpose.slug}>{purpose.slug}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Enabled
                  <select value={editForm.enabled ? "yes" : "no"} onChange={(event) => setEditForm({ ...editForm, enabled: event.target.value === "yes" })}>
                    <option value="yes">Yes</option>
                    <option value="no">No</option>
                  </select>
                </label>
                <label>
                  Default agent
                  <select value={editForm.is_default ? "yes" : "no"} onChange={(event) => setEditForm({ ...editForm, is_default: event.target.value === "yes" })}>
                    <option value="yes">Yes</option>
                    <option value="no">No</option>
                  </select>
                </label>
                <label>
                  System prompt
                  <textarea className="input" rows={14} value={editForm.system_prompt_text} onChange={(event) => setEditForm({ ...editForm, system_prompt_text: event.target.value })} />
                </label>
              </div>
              <div className="inline-actions" style={{ marginTop: 12 }}>
                <button className="primary" onClick={saveEdit} disabled={!editForm.name.trim() || !editForm.model_config_id}>Save changes</button>
                <button className="danger" onClick={() => remove(selectedAgent)}>Delete agent</button>
              </div>
              <div style={{ marginTop: 18 }}>
                <h4>Test agent</h4>
                <p className="muted small">Run a simple prompt through this agent to verify credentials and model responsiveness.</p>
                <div className="stacked-field">
                  <span>Test prompt</span>
                  <textarea
                    className="input"
                    rows={4}
                    value={testPrompt}
                    onChange={(event) => setTestPrompt(event.target.value)}
                    placeholder="Enter a short test prompt"
                  />
                </div>
                <div className="inline-actions" style={{ marginTop: 10 }}>
                  <button className="ghost" onClick={runAgentTest} disabled={testRunning || !testPrompt.trim()}>
                    {testRunning ? "Testing..." : "Run test"}
                  </button>
                </div>
                {testError && <InlineMessage tone="error" title="Test failed" body={testError} />}
                {testResult && (
                  <div className="card" style={{ marginTop: 10 }}>
                    <div className="muted small">Provider: {testResult.provider} · Model: {testResult.model}</div>
                    <pre style={{ whiteSpace: "pre-wrap", margin: "8px 0 0 0" }}>{testResult.content || "(no content)"}</pre>
                  </div>
                )}
              </div>
            </>
          )}
        </section>
      </div>
    </>
  );
}
