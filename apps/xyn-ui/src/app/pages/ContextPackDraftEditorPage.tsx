import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import {
  activateContextPack,
  deactivateContextPack,
  getArtifact,
  getContextPack,
  listArtifactActivity,
  listContextPacks,
  updateArtifactRecord,
  updateContextPack,
} from "../../api/xyn";
import type { ContextPackCreatePayload, ContextPackDetail, LedgerEventSummary, UnifiedArtifact } from "../../api/types";
import { useXynConsole } from "../state/xynConsoleStore";

const emptyForm: ContextPackCreatePayload = {
  name: "",
  purpose: "any",
  scope: "global",
  namespace: "",
  project_key: "",
  version: "0.1.0",
  is_active: false,
  is_default: false,
  content_markdown: "",
  applies_to_json: {},
};

const PURPOSE_OPTIONS = ["any", "planner", "coder", "deployer", "operator", "video_explainer"];
const SCOPE_OPTIONS = ["global", "namespace", "project"];

function formatDate(value?: string) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

function parseGovernance(detail?: ContextPackDetail | null) {
  const root = (detail?.applies_to_json as Record<string, unknown> | null)?.xyn_governance;
  return root && typeof root === "object" ? (root as Record<string, unknown>) : {};
}

function bumpPatch(version: string) {
  const clean = String(version || "").trim();
  const match = clean.match(/^(\d+)\.(\d+)\.(\d+)$/);
  if (!match) return clean ? `${clean}.1` : "0.1.0";
  return `${Number(match[1])}.${Number(match[2])}.${Number(match[3]) + 1}`;
}

export default function ContextPackDraftEditorPage() {
  const { draftId } = useParams();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<ContextPackDetail | null>(null);
  const [artifact, setArtifact] = useState<UnifiedArtifact | null>(null);
  const [form, setForm] = useState<ContextPackCreatePayload>(emptyForm);
  const [appliesText, setAppliesText] = useState("{}");
  const [contentFormat, setContentFormat] = useState<"json" | "yaml" | "text">("json");
  const [activity, setActivity] = useState<LedgerEventSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"editor" | "activity">("editor");
  const [allPacks, setAllPacks] = useState<ContextPackDetail[]>([]);

  const nameFieldRef = useRef<HTMLInputElement | null>(null);
  const contentFieldRef = useRef<HTMLTextAreaElement | null>(null);
  const appliesFieldRef = useRef<HTMLTextAreaElement | null>(null);

  const {
    setContext: setConsoleContext,
    clearContext: clearConsoleContext,
    registerEditorBridge,
    unregisterEditorBridge,
    setLastArtifactHint,
  } = useXynConsole();

  const governance = useMemo(() => parseGovernance(detail), [detail]);
  const stage = useMemo(() => {
    const explicit = String(governance.stage || "").toLowerCase();
    if (explicit === "reviewed") return "reviewed";
    const artifactState = String(artifact?.artifact_state || "").toLowerCase();
    if (artifactState === "canonical") return "canonical";
    if (artifactState === "deprecated") return "deprecated";
    return "draft";
  }, [artifact?.artifact_state, governance.stage]);

  const parentPackId = String(governance.parent_pack_id || "").trim();
  const parentArtifactId = String(governance.parent_artifact_id || "").trim();

  const load = useCallback(async () => {
    if (!draftId) return;
    try {
      setBusy(true);
      setError(null);
      const loadedDetail = await getContextPack(draftId);
      setDetail(loadedDetail);
      setForm({
        name: loadedDetail.name,
        purpose: loadedDetail.purpose,
        scope: loadedDetail.scope,
        namespace: loadedDetail.namespace ?? "",
        project_key: loadedDetail.project_key ?? "",
        version: loadedDetail.version,
        is_active: loadedDetail.is_active,
        is_default: loadedDetail.is_default,
        content_markdown: loadedDetail.content_markdown ?? "",
        applies_to_json: loadedDetail.applies_to_json ?? {},
      });
      setAppliesText(JSON.stringify(loadedDetail.applies_to_json ?? {}, null, 2));
      const hintFormat = String((loadedDetail.applies_to_json as Record<string, unknown> | null)?.content_format || "").toLowerCase();
      setContentFormat(hintFormat === "yaml" || hintFormat === "text" ? hintFormat : "json");

      if (loadedDetail.artifact_id) {
        const [loadedArtifact, events] = await Promise.all([
          getArtifact(loadedDetail.artifact_id),
          listArtifactActivity(loadedDetail.artifact_id, { limit: 40 }),
        ]);
        setArtifact(loadedArtifact);
        setActivity(events.events || []);
      } else {
        setArtifact(null);
        setActivity([]);
      }

      const packs = await listContextPacks({});
      const details = await Promise.all((packs.context_packs || []).map((entry) => getContextPack(entry.id)));
      setAllPacks(details);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }, [draftId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (detail?.artifact_id) {
      setConsoleContext({ artifact_id: detail.artifact_id, artifact_type: "ContextPack" });
      setLastArtifactHint({
        artifact_id: detail.artifact_id,
        artifact_type: "ContextPack",
        artifact_state: artifact?.artifact_state || null,
        title: detail.name,
        route: `/app/context-packs/drafts/${detail.id}`,
      });
      return () => clearConsoleContext();
    }
    clearConsoleContext();
  }, [artifact?.artifact_state, clearConsoleContext, detail?.artifact_id, detail?.id, detail?.name, setConsoleContext, setLastArtifactHint]);

  useEffect(() => {
    if (!detail?.artifact_id) return;
    const context = { artifact_id: detail.artifact_id, artifact_type: "ContextPack" as const };
    registerEditorBridge(context, {
      getFormSnapshot: () => {
        let parsedApplies: Record<string, unknown> = {};
        try {
          parsedApplies = appliesText.trim() ? (JSON.parse(appliesText) as Record<string, unknown>) : {};
        } catch {
          parsedApplies = {};
        }
        return {
          title: String(form.name || "").trim(),
          summary: String(parsedApplies.summary || ""),
          tags: Array.isArray(parsedApplies.tags) ? parsedApplies.tags : [],
          format: contentFormat,
          content: String(form.content_markdown || ""),
        };
      },
      applyPatchToForm: (patch) => {
        const appliedFields: string[] = [];
        const ignoredFields: string[] = [];
        let nextApplies = (() => {
          try {
            return appliesText.trim() ? (JSON.parse(appliesText) as Record<string, unknown>) : {};
          } catch {
            return {};
          }
        })();
        for (const [field, value] of Object.entries(patch || {})) {
          if (field === "title") {
            setForm((current) => ({ ...current, name: String(value || "") }));
            appliedFields.push(field);
          } else if (field === "content") {
            setForm((current) => ({ ...current, content_markdown: String(value || "") }));
            appliedFields.push(field);
          } else if (field === "format") {
            const next = String(value || "").toLowerCase();
            if (next === "json" || next === "yaml" || next === "text") {
              setContentFormat(next);
              appliedFields.push(field);
            } else {
              ignoredFields.push(field);
            }
          } else if (field === "summary") {
            nextApplies = { ...nextApplies, summary: String(value || "") };
            appliedFields.push(field);
          } else if (field === "tags" && Array.isArray(value)) {
            nextApplies = { ...nextApplies, tags: value.map((entry) => String(entry || "").trim()).filter(Boolean) };
            appliedFields.push(field);
          } else {
            ignoredFields.push(field);
          }
        }
        setAppliesText(JSON.stringify({ ...nextApplies, content_format: contentFormat }, null, 2));
        return { appliedFields, ignoredFields };
      },
      focusField: (field) => {
        if (field === "title") {
          nameFieldRef.current?.focus();
          return true;
        }
        if (field === "content") {
          contentFieldRef.current?.focus();
          return true;
        }
        if (field === "summary" || field === "tags" || field === "format") {
          appliesFieldRef.current?.focus();
          return true;
        }
        return false;
      },
      applyFieldValue: (field, value) => {
        if (field === "format") {
          const normalized = String(value || "").toLowerCase();
          if (normalized === "json" || normalized === "yaml" || normalized === "text") {
            setContentFormat(normalized);
            return true;
          }
        }
        return false;
      },
    });
    return () => unregisterEditorBridge(context);
  }, [
    detail?.artifact_id,
    form.name,
    form.content_markdown,
    contentFormat,
    appliesText,
    registerEditorBridge,
    unregisterEditorBridge,
  ]);

  const buildPayload = useCallback(() => {
    const parsedApplies = appliesText.trim() ? (JSON.parse(appliesText) as Record<string, unknown>) : {};
    return {
      ...form,
      applies_to_json: { ...parsedApplies, content_format: contentFormat },
    } as ContextPackCreatePayload;
  }, [appliesText, contentFormat, form]);

  const handleSave = useCallback(async () => {
    if (!detail) return;
    try {
      setBusy(true);
      setError(null);
      setMessage(null);
      const payload = buildPayload();
      const updated = await updateContextPack(detail.id, payload);
      if (updated.artifact_id) {
        await updateArtifactRecord(updated.artifact_id, {
          title: updated.name,
          summary: `${updated.purpose} · ${updated.scope} · v${updated.version}`,
        });
      }
      await load();
      setMessage("Draft saved.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }, [buildPayload, detail, load]);

  const handleMarkReviewed = useCallback(async () => {
    if (!detail) return;
    try {
      setBusy(true);
      setError(null);
      const payload = buildPayload();
      const xynGovernance = {
        ...(payload.applies_to_json?.xyn_governance as Record<string, unknown> || {}),
        stage: "reviewed",
        reviewed_at: new Date().toISOString(),
      };
      payload.applies_to_json = {
        ...(payload.applies_to_json || {}),
        xyn_governance: xynGovernance,
      };
      await updateContextPack(detail.id, payload);
      if (detail.artifact_id) {
        await updateArtifactRecord(detail.artifact_id, { artifact_state: "provisional" });
      }
      await load();
      setMessage("Draft marked reviewed.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }, [buildPayload, detail, load]);

  const handlePromote = useCallback(async () => {
    if (!detail) return;
    try {
      setBusy(true);
      setError(null);
      const payload = buildPayload();
      if (contentFormat === "json") {
        JSON.parse(String(payload.content_markdown || "{}"));
      }
      const nextVersion = bumpPatch(payload.version || detail.version);
      const xynGovernance = {
        ...(payload.applies_to_json?.xyn_governance as Record<string, unknown> || {}),
        stage: "canonical",
        promoted_at: new Date().toISOString(),
        promoted_from_draft_id: detail.id,
      };
      payload.version = nextVersion;
      payload.is_active = true;
      payload.applies_to_json = {
        ...(payload.applies_to_json || {}),
        xyn_governance: xynGovernance,
      };
      await updateContextPack(detail.id, payload);
      await activateContextPack(detail.id);
      if (detail.artifact_id) {
        await updateArtifactRecord(detail.artifact_id, { artifact_state: "canonical" });
      }
      if (parentPackId) {
        await deactivateContextPack(parentPackId);
      }
      if (parentArtifactId) {
        await updateArtifactRecord(parentArtifactId, {
          artifact_state: "deprecated",
          reason: "superseded_by_context_pack_promotion",
        });
      }
      await load();
      setMessage(`Promoted to canonical v${nextVersion}.`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }, [buildPayload, contentFormat, detail, load, parentArtifactId, parentPackId]);

  const handleDiscard = useCallback(async () => {
    if (!detail?.artifact_id) return;
    try {
      setBusy(true);
      setError(null);
      await updateArtifactRecord(detail.artifact_id, {
        artifact_state: "deprecated",
        reason: "context_pack_draft_discarded",
      });
      await deactivateContextPack(detail.id);
      await load();
      setMessage("Draft discarded.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }, [detail?.artifact_id, detail?.id, load]);

  const siblingVersions = useMemo(() => {
    if (!parentPackId) return [];
    return allPacks.filter((entry) => {
      const root = parseGovernance(entry);
      return String(root.parent_pack_id || "").trim() === parentPackId || entry.id === parentPackId;
    });
  }, [allPacks, parentPackId]);

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Context Pack Draft Editor</h2>
          <p className="muted">Governed workflow: draft → review → canonical.</p>
        </div>
        <div className="inline-actions">
          <button className="ghost" type="button" onClick={() => navigate(`/app/context-packs${detail ? `?pack=${encodeURIComponent(detail.id)}` : ""}`)}>
            Back to index
          </button>
        </div>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {message && <InlineMessage tone="info" title="Update" body={message} />}

      <section className="card">
        <div className="card-header">
          <div>
            <h3>{detail?.name || "Draft"}</h3>
            <p className="muted small">
              {stage} · {artifact?.artifact_state || "provisional"} · {detail?.version || "-"}
            </p>
          </div>
          <div className="inline-actions">
            <button className="primary" type="button" onClick={() => void handleSave()} disabled={busy || !detail}>Save</button>
            <button className="ghost" type="button" onClick={() => void handleMarkReviewed()} disabled={busy || !detail || stage === "reviewed" || stage === "canonical"}>
              Mark reviewed
            </button>
            <button className="primary" type="button" onClick={() => void handlePromote()} disabled={busy || !detail || stage === "canonical"}>
              Promote to canonical
            </button>
            <button className="ghost" type="button" onClick={() => void handleDiscard()} disabled={busy || !detail || stage === "canonical"}>
              Discard draft
            </button>
          </div>
        </div>
      </section>

      <div className="layout">
        <section className="card">
          <div className="card-header">
            <h3>Editor</h3>
            <div className="inline-actions">
              <button className={`ghost sm ${activeTab === "editor" ? "active" : ""}`} type="button" onClick={() => setActiveTab("editor")}>Draft</button>
              <button className={`ghost sm ${activeTab === "activity" ? "active" : ""}`} type="button" onClick={() => setActiveTab("activity")}>Activity</button>
            </div>
          </div>

          {activeTab === "editor" && (
            <>
              <div className="form-grid">
                <label>
                  Name
                  <input
                    ref={nameFieldRef}
                    value={form.name ?? ""}
                    onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                  />
                </label>
                <label>
                  Content format
                  <select value={contentFormat} onChange={(event) => setContentFormat(event.target.value as "json" | "yaml" | "text")}>
                    <option value="json">json</option>
                    <option value="yaml">yaml</option>
                    <option value="text">text</option>
                  </select>
                </label>
                <label>
                  Purpose
                  <select value={form.purpose ?? "any"} onChange={(event) => setForm((current) => ({ ...current, purpose: event.target.value }))}>
                    {PURPOSE_OPTIONS.map((option) => (
                      <option key={option} value={option}>{option}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Scope
                  <select value={form.scope ?? "global"} onChange={(event) => setForm((current) => ({ ...current, scope: event.target.value }))}>
                    {SCOPE_OPTIONS.map((option) => (
                      <option key={option} value={option}>{option}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Namespace
                  <input value={form.namespace ?? ""} onChange={(event) => setForm((current) => ({ ...current, namespace: event.target.value }))} />
                </label>
                <label>
                  Project key
                  <input value={form.project_key ?? ""} onChange={(event) => setForm((current) => ({ ...current, project_key: event.target.value }))} />
                </label>
                <label>
                  Version
                  <input value={form.version ?? ""} readOnly />
                </label>
                <label>
                  Applies to (JSON)
                  <textarea
                    ref={appliesFieldRef}
                    rows={6}
                    value={appliesText}
                    onChange={(event) => setAppliesText(event.target.value)}
                    placeholder='{"task_type":"codegen"}'
                  />
                </label>
                <label className="span-full">
                  Content
                  <textarea
                    ref={contentFieldRef}
                    rows={18}
                    value={form.content_markdown ?? ""}
                    onChange={(event) => setForm((current) => ({ ...current, content_markdown: event.target.value }))}
                  />
                </label>
              </div>
            </>
          )}

          {activeTab === "activity" && (
            <div className="stack">
              {activity.length === 0 ? (
                <p className="muted">No governance activity yet.</p>
              ) : (
                activity.map((entry) => (
                  <div key={entry.ledger_event_id} className="item-row">
                    <div>
                      <strong>{entry.summary || entry.action}</strong>
                      <div className="muted small">{entry.action} · {entry.actor?.display_name || entry.actor?.email || entry.actor?.id || "unknown"}</div>
                    </div>
                    <span className="muted small">{formatDate(entry.created_at)}</span>
                  </div>
                ))
              )}
            </div>
          )}
        </section>

        <section className="card">
          <div className="card-header">
            <h3>Provenance</h3>
          </div>
          <div className="form-grid">
            <div><strong>Artifact ID</strong><div className="muted">{detail?.artifact_id || "-"}</div></div>
            <div><strong>State</strong><div className="muted">{artifact?.artifact_state || "-"}</div></div>
            <div><strong>Family ID</strong><div className="muted">{artifact?.family_id || "-"}</div></div>
            <div><strong>Parent artifact</strong><div className="muted">{artifact?.parent_artifact_id || "-"}</div></div>
            <div><strong>Content hash</strong><div className="muted" style={{ wordBreak: "break-all" }}>{artifact?.content_hash || "-"}</div></div>
            <div><strong>Validation</strong><div className="muted">{artifact?.validation_status || "unknown"}</div></div>
            <div><strong>Created via</strong><div className="muted">{artifact?.created_via || "-"}</div></div>
            <div><strong>Updated</strong><div className="muted">{formatDate(artifact?.updated_at || detail?.updated_at)}</div></div>
          </div>
          {siblingVersions.length > 0 && (
            <div className="stack">
              <div className="label">Family chain</div>
              {siblingVersions.map((entry) => {
                const root = parseGovernance(entry);
                const entryStage = String(root.stage || "canonical");
                const isCurrent = entry.id === detail?.id;
                return (
                  <button
                    key={entry.id}
                    className={`item-row ${isCurrent ? "active" : ""}`}
                    type="button"
                    onClick={() => navigate(`/app/context-packs/drafts/${entry.id}`)}
                  >
                    <strong>{entry.name}</strong>
                    <span className={`status-pill ${entryStage === "canonical" ? "status-good" : entryStage === "reviewed" ? "status-info" : entryStage === "deprecated" ? "status-bad" : "status-warn"}`}>
                      {entryStage}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </>
  );
}
