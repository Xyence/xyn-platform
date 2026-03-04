import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import {
  createContextPack,
  getArtifact,
  getContextPack,
  listArtifactActivity,
  listArtifacts,
  listContextPacks,
  updateArtifactRecord,
} from "../../api/xyn";
import type { ContextPackDetail, ContextPackSummary, LedgerEventSummary, UnifiedArtifact } from "../../api/types";

function formatDate(value?: string) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

function readGovernance(summary?: ContextPackSummary | null) {
  const root = (summary?.applies_to_json as Record<string, unknown> | null)?.xyn_governance;
  return root && typeof root === "object" ? (root as Record<string, unknown>) : null;
}

function workflowStage(summary: ContextPackSummary | null, artifact: UnifiedArtifact | null): "draft" | "reviewed" | "canonical" | "deprecated" {
  const fromGovernance = String(readGovernance(summary)?.stage || "").toLowerCase();
  if (fromGovernance === "reviewed") return "reviewed";
  const state = String(artifact?.artifact_state || "").toLowerCase();
  if (state === "canonical") return "canonical";
  if (state === "deprecated") return "deprecated";
  return "draft";
}

export default function ContextPacksPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [allItems, setAllItems] = useState<ContextPackSummary[]>([]);
  const [artifactById, setArtifactById] = useState<Record<string, UnifiedArtifact>>({});
  const [selected, setSelected] = useState<ContextPackDetail | null>(null);
  const [selectedArtifact, setSelectedArtifact] = useState<UnifiedArtifact | null>(null);
  const [activity, setActivity] = useState<LedgerEventSummary[]>([]);
  const [activeTab, setActiveTab] = useState<"overview" | "activity">("overview");
  const [showInactive, setShowInactive] = useState(false);
  const [loading, setLoading] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const packParam = useMemo(() => String(searchParams.get("pack") || "").trim(), [searchParams]);

  const visibleItems = useMemo(
    () => (showInactive ? allItems : allItems.filter((item) => item.is_active)),
    [allItems, showInactive]
  );

  const selectedSummary = useMemo(() => {
    if (!packParam) return null;
    return allItems.find((item) => item.id === packParam) || null;
  }, [allItems, packParam]);

  const selectedStage = useMemo(() => workflowStage(selectedSummary, selectedArtifact), [selectedSummary, selectedArtifact]);

  const existingDraft = useMemo(() => {
    if (!selectedSummary) return null;
    return allItems.find((item) => {
      const governance = readGovernance(item);
      if (!governance) return false;
      const parentPack = String(governance.parent_pack_id || "").trim();
      if (parentPack !== selectedSummary.id) return false;
      const artifact = item.artifact_id ? artifactById[item.artifact_id] : null;
      const stage = workflowStage(item, artifact || null);
      return stage === "draft" || stage === "reviewed";
    }) || null;
  }, [allItems, artifactById, selectedSummary]);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const [packsResponse, artifactsResponse] = await Promise.all([
        listContextPacks({}),
        listArtifacts({ type: "context_pack", limit: 500, offset: 0 }),
      ]);
      const rows = packsResponse.context_packs || [];
      const artifactMap: Record<string, UnifiedArtifact> = {};
      for (const artifact of artifactsResponse.artifacts || []) {
        artifactMap[artifact.artifact_id || artifact.id] = artifact;
      }
      setAllItems(rows);
      setArtifactById(artifactMap);

      const requested = packParam ? rows.find((entry) => entry.id === packParam) : null;
      if (!requested) {
        const firstVisible = (showInactive ? rows : rows.filter((entry) => entry.is_active))[0] || rows[0] || null;
        if (firstVisible) {
          const next = new URLSearchParams(searchParams);
          next.set("pack", firstVisible.id);
          setSearchParams(next, { replace: true });
        }
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [packParam, searchParams, setSearchParams, showInactive]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!packParam) {
      setSelected(null);
      setSelectedArtifact(null);
      setActivity([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const detail = await getContextPack(packParam);
        if (cancelled) return;
        setSelected(detail);
        if (detail.artifact_id) {
          const cached = artifactById[detail.artifact_id];
          const artifact = cached || (await getArtifact(detail.artifact_id));
          if (cancelled) return;
          setSelectedArtifact(artifact);
          const events = await listArtifactActivity(detail.artifact_id, { limit: 30 });
          if (cancelled) return;
          setActivity(events.events || []);
        } else {
          setSelectedArtifact(null);
          setActivity([]);
        }
      } catch (err) {
        if (!cancelled) {
          setError((err as Error).message);
          setSelected(null);
          setSelectedArtifact(null);
          setActivity([]);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [artifactById, packParam]);

  const selectPack = useCallback(
    (packId: string) => {
      const next = new URLSearchParams(searchParams);
      next.set("pack", packId);
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams]
  );

  const handleCreateDraft = useCallback(async () => {
    if (!selected) return;
    if (existingDraft) {
      navigate(`/app/context-packs/drafts/${existingDraft.id}`);
      return;
    }
    try {
      setActionBusy(true);
      setError(null);
      setMessage(null);
      const governance = {
        stage: "draft",
        parent_pack_id: selected.id,
        parent_artifact_id: selected.artifact_id || null,
        parent_version: selected.version,
        created_at: new Date().toISOString(),
      };
      const payload = {
        name: `${selected.name} draft`,
        purpose: selected.purpose,
        scope: selected.scope,
        namespace: selected.namespace || "",
        project_key: selected.project_key || "",
        version: selected.version,
        is_active: false,
        is_default: false,
        content_markdown: selected.content_markdown || "",
        applies_to_json: {
          ...(selected.applies_to_json || {}),
          xyn_governance: governance,
        },
      };
      const created = await createContextPack(payload);
      const createdDetail = await getContextPack(created.id);
      if (createdDetail.artifact_id) {
        await updateArtifactRecord(createdDetail.artifact_id, {
          artifact_state: "provisional",
          parent_artifact_id: selected.artifact_id || null,
          title: createdDetail.name,
          summary: `Draft derived from ${selected.name} v${selected.version}`,
        });
      }
      await load();
      setMessage("Draft created.");
      navigate(`/app/context-packs/drafts/${createdDetail.id}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setActionBusy(false);
    }
  }, [existingDraft, load, navigate, selected]);

  const copyValue = useCallback(async (value: string, success: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setMessage(success);
      window.setTimeout(() => setMessage((current) => (current === success ? null : current)), 1400);
    } catch {
      setError("Clipboard is unavailable.");
    }
  }, []);

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Context Packs</h2>
          <p className="muted">Manage reusable context with governed draft and promotion flow.</p>
        </div>
        <div className="inline-actions">
          <label className="muted small">
            <input
              type="checkbox"
              checked={showInactive}
              onChange={(event) => setShowInactive(event.target.checked)}
            />{" "}
            Show inactive
          </label>
          <button className="ghost" onClick={() => void load()} disabled={loading || actionBusy}>
            Refresh
          </button>
        </div>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      {message && <InlineMessage tone="info" title="Update" body={message} />}

      <div className="layout">
        <section className="card">
          <div className="card-header">
            <h3>Packs</h3>
          </div>
          <div className="instance-list">
            {visibleItems.map((item) => {
              const artifact = item.artifact_id ? artifactById[item.artifact_id] : null;
              const stage = workflowStage(item, artifact || null);
              return (
                <button
                  key={item.id}
                  className={`instance-row ${packParam === item.id ? "active" : ""}`}
                  onClick={() => selectPack(item.id)}
                  type="button"
                >
                  <div>
                    <strong>{item.name}</strong>
                    <span className="muted small">{item.scope}</span>
                  </div>
                  <div className="inline-actions">
                    <span className={`status-pill ${stage === "canonical" ? "status-good" : stage === "reviewed" ? "status-info" : stage === "deprecated" ? "status-bad" : "status-warn"}`}>
                      {stage}
                    </span>
                    <span className="muted small">
                      {item.purpose} · v{item.version}
                    </span>
                  </div>
                </button>
              );
            })}
            {visibleItems.length === 0 && <p className="muted">No context packs for this view.</p>}
          </div>
        </section>

        <section className="card">
          <div className="card-header">
            <h3>Context pack detail</h3>
            <div className="inline-actions">
              <button className={`ghost sm ${activeTab === "overview" ? "active" : ""}`} type="button" onClick={() => setActiveTab("overview")}>Overview</button>
              <button className={`ghost sm ${activeTab === "activity" ? "active" : ""}`} type="button" onClick={() => setActiveTab("activity")}>Activity</button>
            </div>
          </div>

          {!selected && <p className="muted">Select a context pack.</p>}

          {selected && activeTab === "overview" && (
            <>
              <div className="form-grid">
                <div><strong>Name</strong><div className="muted">{selected.name}</div></div>
                <div><strong>State</strong><div className="muted">{selectedStage}</div></div>
                <div><strong>Version</strong><div className="muted">{selected.version}</div></div>
                <div><strong>Purpose</strong><div className="muted">{selected.purpose}</div></div>
                <div><strong>Scope</strong><div className="muted">{selected.scope}</div></div>
                <div><strong>Namespace</strong><div className="muted">{selected.namespace || "-"}</div></div>
                <div><strong>Project key</strong><div className="muted">{selected.project_key || "-"}</div></div>
                <div><strong>Content hash</strong><div className="muted" style={{ wordBreak: "break-all" }}>{selectedArtifact?.content_hash || "-"}</div></div>
                <div><strong>Created via</strong><div className="muted">{selectedArtifact?.created_via || "-"}</div></div>
                <div><strong>Last touched by agent</strong><div className="muted">{selectedArtifact?.last_touched_by_agent || "-"}</div></div>
                <div><strong>Updated</strong><div className="muted">{formatDate(selected.updated_at)}</div></div>
                <div><strong>Derived from</strong><div className="muted">{selectedArtifact?.parent_artifact_id || "-"}</div></div>
              </div>

              <div className="inline-actions">
                <button className="ghost" type="button" onClick={() => navigate(`/app/context-packs/drafts/${selected.id}`)}>
                  Open in editor
                </button>
                {selectedStage === "canonical" && (
                  <button className="primary" type="button" onClick={() => void handleCreateDraft()} disabled={actionBusy}>
                    {existingDraft ? "Open draft" : "Create draft"}
                  </button>
                )}
                <button className="ghost" type="button" onClick={() => setActiveTab("activity")}>
                  View activity
                </button>
                <button
                  className="ghost"
                  type="button"
                  onClick={() => void copyValue(selected.name, "Slug copied.")}
                >
                  Copy slug
                </button>
                <button
                  className="ghost"
                  type="button"
                  onClick={() => void copyValue(selectedArtifact?.content_hash || "", "Content hash copied.")}
                  disabled={!selectedArtifact?.content_hash}
                >
                  Copy content hash
                </button>
              </div>

              <details>
                <summary>Content preview</summary>
                <pre className="draft-output-pre" style={{ marginTop: 8 }}>{selected.content_markdown || "(empty)"}</pre>
              </details>
            </>
          )}

          {selected && activeTab === "activity" && (
            <div className="stack">
              {activity.length === 0 ? (
                <p className="muted">No governance activity recorded yet.</p>
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
      </div>
    </>
  );
}
