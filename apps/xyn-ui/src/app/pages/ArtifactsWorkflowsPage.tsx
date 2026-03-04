import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import {
  createWorkflow,
  getWorkflow,
  listArticleCategories,
  listWorkflowActions,
  listWorkflows,
  transitionWorkflow,
  updateWorkflowSpec,
} from "../../api/xyn";
import type { ArticleCategoryRecord, WorkflowActionCatalogItem, WorkflowDetail, WorkflowSpec, WorkflowStep, WorkflowSummary } from "../../api/types";
import ArtifactCredibilityLayer from "../components/artifacts/ArtifactCredibilityLayer";

const emptySpec = (title: string, category: string): WorkflowSpec => ({
  profile: "tour",
  schema_version: 1,
  title,
  description: "",
  category_slug: category,
  entry: { route: "/app/home" },
  settings: { allow_skip: true, show_progress: true },
  steps: [
    {
      id: "step-1",
      type: "modal",
      title: "Welcome",
      body_md: "Describe this step.",
      route: "/app/home",
      ui: { highlight: false, block_interaction: false, allow_back: false },
    },
  ],
});

function makeStepId(idx: number): string {
  return `step-${idx + 1}`;
}

export default function ArtifactsWorkflowsPage({ workspaceId, canCreate }: { workspaceId: string; canCreate: boolean }) {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [items, setItems] = useState<WorkflowSummary[]>([]);
  const [categories, setCategories] = useState<ArticleCategoryRecord[]>([]);
  const [actions, setActions] = useState<WorkflowActionCatalogItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [selectedId, setSelectedId] = useState<string>(searchParams.get("workflow") || "");
  const [selected, setSelected] = useState<WorkflowDetail | null>(null);
  const [activeStepId, setActiveStepId] = useState<string>("");
  const [createForm, setCreateForm] = useState({
    title: "",
    category_slug: "xyn_usage",
    profile: "tour" as const,
    visibility_type: "authenticated" as "public" | "authenticated" | "role_based" | "private",
  });
  const [q, setQ] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("xyn_usage");

  const load = useCallback(async () => {
    if (!workspaceId) return;
    try {
      setLoading(true);
      setError(null);
      const [wf, cat, act] = await Promise.all([
        listWorkflows({ workspace_id: workspaceId, include_unpublished: true, profile: "tour" }),
        listArticleCategories(),
        listWorkflowActions(),
      ]);
      setItems(wf.workflows || []);
      setCategories(cat.categories || []);
      setActions(act.actions || []);
      if (!selectedId && wf.workflows?.length) {
        const firstId = wf.workflows[0].id;
        setSelectedId(firstId);
        setSearchParams((prev) => {
          const next = new URLSearchParams(prev);
          next.set("workflow", firstId);
          return next;
        });
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [workspaceId, selectedId, setSearchParams]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const id = searchParams.get("workflow") || "";
    if (id && id !== selectedId) setSelectedId(id);
  }, [searchParams, selectedId]);

  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      return;
    }
    (async () => {
      try {
        const detail = await getWorkflow(selectedId);
        setSelected(detail.workflow);
        const first = detail.workflow.workflow_spec_json?.steps?.[0]?.id || "";
        setActiveStepId((prev) => prev || first);
      } catch (err) {
        setError((err as Error).message);
      }
    })();
  }, [selectedId]);

  const filtered = useMemo(() => {
    const search = q.trim().toLowerCase();
    return items.filter((item) => {
      if (categoryFilter && item.category !== categoryFilter) return false;
      if (!search) return true;
      const haystack = `${item.title} ${item.slug} ${item.description || ""}`.toLowerCase();
      return haystack.includes(search);
    });
  }, [items, categoryFilter, q]);

  const selectedSpec = selected?.workflow_spec_json;
  const activeStep = useMemo(() => {
    if (!selectedSpec?.steps?.length) return null;
    return selectedSpec.steps.find((step) => step.id === activeStepId) || selectedSpec.steps[0] || null;
  }, [selectedSpec, activeStepId]);

  const setSelectedSpec = (nextSpec: WorkflowSpec) => {
    if (!selected) return;
    setSelected({ ...selected, workflow_spec_json: nextSpec });
  };

  const updateActiveStep = (patch: Partial<WorkflowStep>) => {
    if (!selectedSpec || !activeStep) return;
    const steps = selectedSpec.steps.map((step) => (step.id === activeStep.id ? { ...step, ...patch } : step));
    setSelectedSpec({ ...selectedSpec, steps });
  };

  const addStep = () => {
    if (!selectedSpec) return;
    const nextId = makeStepId(selectedSpec.steps.length);
    const nextStep: WorkflowStep = {
      id: nextId,
      type: "modal",
      title: `Step ${selectedSpec.steps.length + 1}`,
      body_md: "",
      route: selectedSpec.entry?.route || "/app/home",
      ui: { highlight: false, block_interaction: false, allow_back: true },
    };
    setSelectedSpec({ ...selectedSpec, steps: [...selectedSpec.steps, nextStep] });
    setActiveStepId(nextId);
  };

  const removeStep = () => {
    if (!selectedSpec || !activeStep) return;
    if (selectedSpec.steps.length <= 1) {
      setError("A workflow must have at least one step.");
      return;
    }
    const nextSteps = selectedSpec.steps.filter((step) => step.id !== activeStep.id);
    setSelectedSpec({ ...selectedSpec, steps: nextSteps });
    setActiveStepId(nextSteps[0]?.id || "");
  };

  const moveStep = (direction: -1 | 1) => {
    if (!selectedSpec || !activeStep) return;
    const idx = selectedSpec.steps.findIndex((step) => step.id === activeStep.id);
    const target = idx + direction;
    if (idx < 0 || target < 0 || target >= selectedSpec.steps.length) return;
    const next = [...selectedSpec.steps];
    const [row] = next.splice(idx, 1);
    next.splice(target, 0, row);
    setSelectedSpec({ ...selectedSpec, steps: next });
  };

  const saveWorkflow = async () => {
    if (!selected) return;
    try {
      setSaving(true);
      setError(null);
      setMessage(null);
      const result = await updateWorkflowSpec(selected.id, {
        title: selected.title,
        category_slug: selected.category,
        visibility_type: selected.visibility_type,
        workflow_spec_json: selected.workflow_spec_json,
      });
      setSelected(result.workflow);
      setMessage("Workflow saved.");
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const publishWorkflow = async () => {
    if (!selected) return;
    try {
      setSaving(true);
      setError(null);
      const result = await transitionWorkflow(selected.id, "published");
      setSelected(result.workflow);
      setMessage("Workflow published.");
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const createNew = async () => {
    if (!createForm.title.trim()) {
      setError("Title is required.");
      return;
    }
    try {
      setSaving(true);
      const created = await createWorkflow({
        workspace_id: workspaceId,
        title: createForm.title.trim(),
        profile: "tour",
        category_slug: createForm.category_slug,
        visibility_type: createForm.visibility_type,
        workflow_spec_json: emptySpec(createForm.title.trim(), createForm.category_slug),
      });
      setShowCreateModal(false);
      setSelectedId(created.workflow.id);
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set("workflow", created.workflow.id);
        return next;
      });
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Workflows</h2>
          <p className="muted">Governed workflow artifacts. Tours in Observe are published tour workflows.</p>
        </div>
        <div className="inline-actions">
          <button className="ghost" onClick={() => void load()} disabled={loading || saving}>Refresh</button>
          {canCreate && (
            <button className="primary" onClick={() => setShowCreateModal(true)} disabled={saving}>New Workflow</button>
          )}
        </div>
      </div>
      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {message && <InlineMessage tone="info" title="Update" body={message} />}

      <div className="layout">
        <section className="card list-pane">
          <div className="card-header">
            <h3>Workflow list</h3>
          </div>
          <div className="form-grid compact">
            <label>
              Search
              <input className="input" value={q} onChange={(event) => setQ(event.target.value)} placeholder="Find workflow" />
            </label>
            <label>
              Category
              <select className="input" value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}>
                <option value="">All</option>
                {categories.map((row) => (
                  <option key={row.slug} value={row.slug}>{row.name}</option>
                ))}
              </select>
            </label>
          </div>
          <div className="list-scroll">
            {filtered.map((row) => (
              <button
                key={row.id}
                className={`list-row ${selectedId === row.id ? "active" : ""}`}
                onClick={() => {
                  setSelectedId(row.id);
                  setSearchParams((prev) => {
                    const next = new URLSearchParams(prev);
                    next.set("workflow", row.id);
                    return next;
                  });
                }}
              >
                <strong>{row.title}</strong>
                <span className="muted small">{row.slug} · {row.status} · {row.category_name || row.category}</span>
              </button>
            ))}
            {!filtered.length && <p className="muted">No workflows found.</p>}
          </div>
        </section>

        <section className="card detail-pane">
          {!selected ? (
            <p className="muted">Select a workflow.</p>
          ) : (
            <>
              <div className="card-header">
                <h3>{selected.title}</h3>
                <div className="inline-actions">
                  <button className="ghost sm" onClick={() => void saveWorkflow()} disabled={saving}>Save</button>
                  <button className="primary sm" onClick={() => void publishWorkflow()} disabled={saving || selected.status === "published"}>Publish</button>
                  <Link className="ghost sm" to="/app/tours">Open Tours</Link>
                </div>
              </div>
              <ArtifactCredibilityLayer
                artifactId={selected.artifact_id || selected.id}
                titleFallback={selected.title}
                busy={saving}
              />
              <div className="form-grid">
                <label>
                  Title
                  <input className="input" value={selected.title} onChange={(event) => setSelected({ ...selected, title: event.target.value })} />
                </label>
                <label>
                  Category
                  <select
                    className="input"
                    value={selected.category}
                    onChange={(event) => setSelected({ ...selected, category: event.target.value, workflow_spec_json: { ...selected.workflow_spec_json, category_slug: event.target.value } })}
                  >
                    {categories.map((row) => (
                      <option key={row.slug} value={row.slug}>{row.name}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Visibility
                  <select className="input" value={selected.visibility_type} onChange={(event) => setSelected({ ...selected, visibility_type: event.target.value as WorkflowDetail["visibility_type"] })}>
                    <option value="private">private</option>
                    <option value="authenticated">authenticated</option>
                    <option value="public">public</option>
                    <option value="role_based">role_based</option>
                  </select>
                </label>
                <label>
                  Description
                  <textarea
                    className="input"
                    rows={2}
                    value={selected.workflow_spec_json.description || ""}
                    onChange={(event) => setSelectedSpec({ ...selected.workflow_spec_json, description: event.target.value })}
                  />
                </label>
              </div>

              <div className="workflow-editor-grid">
                <div className="workflow-step-list">
                  <div className="inline-actions workflow-step-toolbar">
                    <button className="ghost sm" onClick={addStep}>Add step</button>
                    <button className="ghost sm" onClick={removeStep} disabled={!activeStep}>Delete</button>
                  </div>
                  {(selected.workflow_spec_json.steps || []).map((step, index) => (
                    <button key={step.id} className={`list-row workflow-step-row ${activeStepId === step.id ? "active" : ""}`} onClick={() => setActiveStepId(step.id)}>
                      <span className="workflow-step-index">{index + 1}</span>
                      <span className="workflow-step-copy">
                        <strong>{step.title || step.id}</strong>
                        <span className="muted small">{step.type} · {step.route || "(no route)"}</span>
                      </span>
                    </button>
                  ))}
                </div>
                <div className="workflow-step-editor">
                  {!activeStep ? (
                    <p className="muted">Select a step.</p>
                  ) : (
                    <div className="form-grid">
                      <div className="inline-actions">
                        <button className="ghost sm" onClick={() => moveStep(-1)}>Up</button>
                        <button className="ghost sm" onClick={() => moveStep(1)}>Down</button>
                      </div>
                      <label>
                        Step ID
                        <input className="input" value={activeStep.id} onChange={(event) => updateActiveStep({ id: event.target.value })} />
                      </label>
                      <label>
                        Type
                        <select className="input" value={activeStep.type} onChange={(event) => updateActiveStep({ type: event.target.value as WorkflowStep["type"] })}>
                          <option value="callout">callout</option>
                          <option value="modal">modal</option>
                          <option value="check">check</option>
                          <option value="copy">copy</option>
                          <option value="action">action</option>
                        </select>
                      </label>
                      <label>
                        Title
                        <input className="input" value={activeStep.title} onChange={(event) => updateActiveStep({ title: event.target.value })} />
                      </label>
                      <label>
                        Route
                        <input className="input" value={activeStep.route || ""} onChange={(event) => updateActiveStep({ route: event.target.value })} />
                      </label>
                      <label>
                        Body (markdown)
                        <textarea className="input" rows={4} value={activeStep.body_md} onChange={(event) => updateActiveStep({ body_md: event.target.value })} />
                      </label>
                      <label>
                        Anchor test id
                        <input
                          className="input"
                          value={activeStep.anchor?.test_id || ""}
                          onChange={(event) => updateActiveStep({ anchor: { ...(activeStep.anchor || {}), test_id: event.target.value } })}
                        />
                      </label>
                      <label>
                        Anchor placement
                        <select
                          className="input"
                          value={activeStep.anchor?.placement || "bottom"}
                          onChange={(event) => updateActiveStep({ anchor: { ...(activeStep.anchor || {}), placement: event.target.value as "top" | "right" | "bottom" | "left" } })}
                        >
                          <option value="top">top</option>
                          <option value="right">right</option>
                          <option value="bottom">bottom</option>
                          <option value="left">left</option>
                        </select>
                      </label>
                      {activeStep.type === "copy" && (
                        <label>
                          Clipboard text
                          <textarea className="input" rows={3} value={activeStep.clipboard_text || ""} onChange={(event) => updateActiveStep({ clipboard_text: event.target.value })} />
                        </label>
                      )}
                      {activeStep.type === "action" && (
                        <>
                          <label>
                            Action
                            <select className="input" value={activeStep.action_id || ""} onChange={(event) => updateActiveStep({ action_id: event.target.value })}>
                              <option value="">Select action</option>
                              {actions.map((row) => (
                                <option key={row.action_id} value={row.action_id}>{row.name} ({row.action_id})</option>
                              ))}
                            </select>
                          </label>
                          <label>
                            Action params (JSON)
                            <textarea
                              className="input"
                              rows={6}
                              value={JSON.stringify(activeStep.params || {}, null, 2)}
                              onChange={(event) => {
                                try {
                                  const parsed = JSON.parse(event.target.value);
                                  updateActiveStep({ params: parsed });
                                } catch {
                                  // keep editable even when invalid
                                }
                              }}
                            />
                          </label>
                        </>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </>
          )}
        </section>
      </div>

      {showCreateModal && (
        <div className="modal-backdrop" role="presentation" onClick={() => !saving && setShowCreateModal(false)}>
          <div className="modal-card articles-create-modal" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <h3>New Workflow</h3>
            <label>
              Title
              <input className="input" value={createForm.title} onChange={(event) => setCreateForm((prev) => ({ ...prev, title: event.target.value }))} />
            </label>
            <label>
              Category
              <select className="input" value={createForm.category_slug} onChange={(event) => setCreateForm((prev) => ({ ...prev, category_slug: event.target.value }))}>
                {categories.map((row) => (
                  <option key={row.slug} value={row.slug}>{row.name}</option>
                ))}
              </select>
            </label>
            <label>
              Visibility
              <select className="input" value={createForm.visibility_type} onChange={(event) => setCreateForm((prev) => ({ ...prev, visibility_type: event.target.value as typeof prev.visibility_type }))}>
                <option value="private">private</option>
                <option value="authenticated">authenticated</option>
                <option value="public">public</option>
                <option value="role_based">role_based</option>
              </select>
            </label>
            <div className="inline-actions" style={{ marginTop: 12 }}>
              <button className="primary" onClick={() => void createNew()} disabled={saving}>Create workflow</button>
              <button className="ghost" onClick={() => setShowCreateModal(false)} disabled={saving}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
