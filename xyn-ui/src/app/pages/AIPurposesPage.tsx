import { useEffect, useState } from "react";
import InlineMessage from "../../components/InlineMessage";
import type { AiPurpose } from "../../api/types";
import { createAiPurpose, deleteAiPurpose, listAiPurposes, updateAiPurpose } from "../../api/xyn";

const PREAMBLE_MAX = 1000;
const PURPOSE_SLUG_RE = /^[a-z0-9][a-z0-9-]{1,62}$/;

function slugifyPurpose(value: string): string {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 63);
}

function parseApiError(err: unknown): { error?: string; message: string } {
  const fallback = { message: (err as Error)?.message || "Request failed." };
  const raw = String((err as Error)?.message || "");
  try {
    const parsed = JSON.parse(raw);
    if (typeof parsed === "object" && parsed) {
      return {
        error: typeof parsed.error === "string" ? parsed.error : undefined,
        message: typeof parsed.message === "string" ? parsed.message : raw,
      };
    }
    return fallback;
  } catch {
    return fallback;
  }
}

export default function AIPurposesPage() {
  const [items, setItems] = useState<AiPurpose[]>([]);
  const [selected, setSelected] = useState<AiPurpose | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createForm, setCreateForm] = useState({
    name: "",
    slug: "",
    description: "",
    status: "active" as "active" | "deprecated",
    preamble: "",
  });
  const [createSlugEdited, setCreateSlugEdited] = useState(false);

  const load = async () => {
    try {
      setError(null);
      const data = await listAiPurposes();
      const normalized = (data.purposes || []).map((item) => ({
        ...item,
        status: item.status || (item.enabled ? "active" : "deprecated"),
        preamble: item.preamble ?? item.system_prompt ?? item.system_prompt_markdown ?? "",
      }));
      setItems(normalized);
      setSelected((prev) => (prev ? normalized.find((item) => item.slug === prev.slug) || normalized[0] || null : normalized[0] || null));
    } catch (err) {
      setError((err as Error).message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const save = async () => {
    if (!selected) return;
    try {
      setError(null);
      setMessage(null);
      await updateAiPurpose(selected.slug, {
        name: selected.name || "",
        description: selected.description || "",
        status: selected.status || "active",
        preamble: (selected.preamble || "").slice(0, PREAMBLE_MAX),
      });
      setMessage("Purpose updated.");
      await load();
    } catch (err) {
      setError(parseApiError(err).message);
    }
  };

  const create = async () => {
    try {
      setError(null);
      setMessage(null);
      await createAiPurpose({
        slug: createForm.slug.trim().toLowerCase(),
        name: createForm.name.trim(),
        description: createForm.description.trim(),
        status: createForm.status,
        preamble: createForm.preamble.slice(0, PREAMBLE_MAX),
      });
      setMessage("Purpose created.");
      setShowCreateModal(false);
      setCreateForm({ name: "", slug: "", description: "", status: "active", preamble: "" });
      setCreateSlugEdited(false);
      await load();
    } catch (err) {
      setError(parseApiError(err).message);
    }
  };

  const removeSelected = async () => {
    if (!selected) return;
    if (!window.confirm(`Deprecate purpose '${selected.slug}'?`)) return;
    try {
      setError(null);
      setMessage(null);
      await deleteAiPurpose(selected.slug);
      setMessage("Purpose deprecated.");
      await load();
    } catch (err) {
      setError(parseApiError(err).message);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h2>AI Purposes</h2>
          <p className="muted">Purpose is the routing key used to filter/select agents (coding, documentation, etc.).</p>
        </div>
        <div className="inline-actions">
          <button className="ghost" onClick={load}>Refresh</button>
          <button className="ghost" onClick={() => setShowCreateModal(true)}>Create</button>
          <button className="danger" onClick={removeSelected} disabled={!selected}>Deprecate</button>
          <button className="primary" onClick={save} disabled={!selected}>Save</button>
        </div>
      </div>
      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {message && <InlineMessage tone="info" title="Update" body={message} />}

      <div className="layout">
        <section className="card">
          <div className="card-header"><h3>Purposes</h3></div>
          <div className="instance-list">
            {items.map((item) => (
              <button key={item.slug} className={`instance-row ${selected?.slug === item.slug ? "selected" : ""}`} onClick={() => setSelected(item)}>
                <div>
                  <strong>{item.name || item.slug}</strong>
                  <span className="muted small">{item.slug}</span>
                </div>
                <span className="muted">{item.status || "active"}</span>
              </button>
            ))}
          </div>
        </section>

        <section className="card">
          <div className="card-header"><h3>Purpose detail</h3></div>
          {!selected ? (
            <p className="muted">Select a purpose.</p>
          ) : (
            <div className="form-grid">
              <label>
                Slug
                <input className="input" value={selected.slug} disabled />
              </label>
              <label>
                Name
                <input
                  className="input"
                  value={selected.name || ""}
                  onChange={(event) => setSelected({ ...selected, name: event.target.value })}
                  placeholder="Documentation"
                />
              </label>
              <label>
                Description
                <input
                  className="input"
                  value={selected.description || ""}
                  onChange={(event) => setSelected({ ...selected, description: event.target.value })}
                  placeholder="Purpose routing description"
                />
              </label>
              <label>
                Status
                <select
                  value={selected.status || "active"}
                  onChange={(event) => setSelected({ ...selected, status: event.target.value as "active" | "deprecated" })}
                >
                  <option value="active">Active</option>
                  <option value="deprecated">Deprecated</option>
                </select>
                <span className="muted small">Deprecation hides this purpose from selection but preserves history.</span>
              </label>
              <p className="muted small">Referenced by: {selected.referenced_by?.agents ?? 0} agents</p>
              <label>
                Preamble
                <textarea
                  className="input"
                  rows={8}
                  maxLength={PREAMBLE_MAX}
                  value={selected.preamble || ""}
                  onChange={(event) => setSelected({ ...selected, preamble: event.target.value })}
                />
                <span className="muted small">
                  Short purpose-level guidance prepended to an agent&apos;s system prompt at runtime ({(selected.preamble || "").length}/{PREAMBLE_MAX}).
                </span>
              </label>
            </div>
          )}
        </section>
      </div>
      {showCreateModal && (
        <div className="modal-backdrop" onClick={() => setShowCreateModal(false)}>
          <section className="modal" onClick={(event) => event.stopPropagation()}>
            <h3>Create purpose</h3>
            <div className="form-grid">
              <label>
                Name
                <input
                  className="input"
                  value={createForm.name}
                  onChange={(event) => {
                    const name = event.target.value;
                    setCreateForm((prev) => ({
                      ...prev,
                      name,
                      slug: createSlugEdited ? prev.slug : slugifyPurpose(name),
                    }));
                  }}
                  placeholder="Analysis"
                />
              </label>
              <label>
                Slug
                <input
                  className="input"
                  value={createForm.slug}
                  onChange={(event) => {
                    setCreateSlugEdited(true);
                    setCreateForm((prev) => ({ ...prev, slug: slugifyPurpose(event.target.value) }));
                  }}
                  placeholder="analysis"
                />
                <span className="muted small">Slug is immutable after creation.</span>
              </label>
              <label>
                Description
                <input
                  className="input"
                  value={createForm.description}
                  onChange={(event) => setCreateForm((prev) => ({ ...prev, description: event.target.value }))}
                  placeholder="Purpose routing description"
                />
              </label>
              <label>
                Status
                <select
                  value={createForm.status}
                  onChange={(event) => setCreateForm((prev) => ({ ...prev, status: event.target.value as "active" | "deprecated" }))}
                >
                  <option value="active">Active</option>
                  <option value="deprecated">Deprecated</option>
                </select>
              </label>
              <label>
                Preamble
                <textarea
                  className="input"
                  rows={6}
                  maxLength={PREAMBLE_MAX}
                  value={createForm.preamble}
                  onChange={(event) => setCreateForm((prev) => ({ ...prev, preamble: event.target.value }))}
                />
                <span className="muted small">{createForm.preamble.length}/{PREAMBLE_MAX}</span>
              </label>
            </div>
            <div className="inline-actions" style={{ marginTop: 12 }}>
              <button className="ghost" onClick={() => setShowCreateModal(false)}>Cancel</button>
              <button
                className="primary"
                onClick={create}
                disabled={!createForm.name.trim() || !PURPOSE_SLUG_RE.test(createForm.slug)}
              >
                Create purpose
              </button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
