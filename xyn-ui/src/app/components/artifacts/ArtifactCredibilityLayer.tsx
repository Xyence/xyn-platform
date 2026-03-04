import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { generateIntentScript, getArtifact, listArtifactActivity, listArtifacts, updateIntentScript } from "../../../api/xyn";
import type { IntentScript, LedgerEventSummary, UnifiedArtifact } from "../../../api/types";
import IntentScriptModal from "./IntentScriptModal";

type Props = {
  artifactId?: string | null;
  titleFallback?: string;
  artifactType?: string;
  onPublish?: () => void;
  onDiscard?: () => void;
  onRevise?: () => void;
  onGoToBody?: () => void;
  busy?: boolean;
  showIntentScriptAction?: boolean;
};

function fmt(value?: string) {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

export default function ArtifactCredibilityLayer({
  artifactId,
  titleFallback,
  artifactType,
  onPublish,
  onDiscard,
  onRevise,
  onGoToBody,
  busy = false,
  showIntentScriptAction = true,
}: Props) {
  const [artifact, setArtifact] = useState<UnifiedArtifact | null>(null);
  const [activity, setActivity] = useState<LedgerEventSummary[]>([]);
  const [family, setFamily] = useState<UnifiedArtifact[]>([]);
  const [activeTab, setActiveTab] = useState<"header" | "activity">("header");
  const [intentScript, setIntentScript] = useState<IntentScript | null>(null);
  const [intentOpen, setIntentOpen] = useState(false);
  const [intentSaving, setIntentSaving] = useState(false);
  const [intentError, setIntentError] = useState<string | null>(null);
  const [shareMessage, setShareMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!artifactId) return;
    let cancelled = false;
    (async () => {
      try {
        const [item, events] = await Promise.all([getArtifact(artifactId), listArtifactActivity(artifactId, { limit: 25 })]);
        if (cancelled) return;
        setArtifact(item);
        setActivity(events.events || []);
        if (item.family_id && item.artifact_type === "blueprint") {
          const list = await listArtifacts({ type: "blueprint", limit: 300 });
          if (cancelled) return;
          const rows = (list.artifacts || []).filter((row) => row.family_id === item.family_id);
          rows.sort((a, b) => {
            const rank = (value?: string) => (value === "canonical" ? 0 : value === "provisional" ? 1 : value === "deprecated" ? 2 : 3);
            const r = rank(a.artifact_state) - rank(b.artifact_state);
            if (r !== 0) return r;
            return new Date(b.updated_at || 0).getTime() - new Date(a.updated_at || 0).getTime();
          });
          setFamily(rows);
        } else {
          setFamily([]);
        }
      } catch {
        if (!cancelled) {
          setArtifact(null);
          setActivity([]);
          setFamily([]);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [artifactId]);

  const state = String(artifact?.artifact_state || "").toLowerCase();
  const showPublish = state === "provisional" && Boolean(onPublish);
  const showDiscard = state === "provisional" && Boolean(onDiscard);
  const showRevise = state === "canonical" && Boolean(onRevise);

  const validationDetails = useMemo(() => {
    const rows = Array.isArray(artifact?.validation_errors) ? artifact?.validation_errors : [];
    return rows.filter((row): row is string => typeof row === "string" && row.trim().length > 0);
  }, [artifact?.validation_errors]);

  const permalink = useMemo(() => `${window.location.origin}/app/artifacts/${artifactId}`, [artifactId]);
  const snapshotSummary = useMemo(
    () =>
      [
        `type=${artifact?.artifact_type || "artifact"}`,
        `state=${artifact?.artifact_state || "unknown"}`,
        `hash=${artifact?.content_hash || "none"}`,
        `validation=${artifact?.validation_status || "unknown"}`,
      ].join(" | "),
    [artifact?.artifact_type, artifact?.artifact_state, artifact?.content_hash, artifact?.validation_status]
  );

  if (!artifactId) return null;

  return (
    <section className="card stack">
      <div className="inline-actions" style={{ justifyContent: "space-between" }}>
        <div>
          <h3>{artifact?.title || titleFallback || "Artifact"}</h3>
          <p className="muted small">
            {(artifact?.artifact_type || "artifact")} · {artifact?.schema_version || "schema n/a"}
          </p>
        </div>
        <div className="inline-actions">
          <button type="button" className={`ghost sm ${activeTab === "header" ? "active" : ""}`} onClick={() => setActiveTab("header")}>Overview</button>
          <button type="button" className={`ghost sm ${activeTab === "activity" ? "active" : ""}`} onClick={() => setActiveTab("activity")}>Activity</button>
        </div>
      </div>

      {activeTab === "header" && (
        <>
          <div className="form-grid">
            <div><strong>State</strong><div className="muted">{artifact?.artifact_state || "-"}</div></div>
            <div><strong>Owner</strong><div className="muted">{artifact?.owner?.display_name || artifact?.owner?.email || "-"}</div></div>
            <div><strong>Created</strong><div className="muted">{fmt(artifact?.created_at)}</div></div>
            <div><strong>Updated</strong><div className="muted">{fmt(artifact?.updated_at)}</div></div>
            <div><strong>Family ID</strong><div className="muted">{artifact?.family_id || "-"}</div></div>
            <div><strong>Content hash</strong><div className="muted" style={{ wordBreak: "break-all" }}>{artifact?.content_hash || "-"}</div></div>
            <div><strong>Validation</strong><div className="muted">{artifact?.validation_status || "unknown"}</div></div>
            <div><strong>Created via</strong><div className="muted">{artifact?.created_via || "-"}</div></div>
            <div><strong>Last touched by agent</strong><div className="muted">{artifact?.last_touched_by_agent || "-"}</div></div>
          </div>

          {validationDetails.length > 0 && (
            <details>
              <summary>View validation details</summary>
              <ul className="stack" style={{ marginTop: 8 }}>
                {validationDetails.map((entry, idx) => (
                  <li key={`${idx}:${entry}`}>{entry}</li>
                ))}
              </ul>
            </details>
          )}

          <div className="stack">
            <strong>Lineage</strong>
            {artifact?.parent_artifact_id ? (
              <Link to={`/app/artifacts/${artifact.parent_artifact_id}`}>Derived from {artifact.parent_artifact_id}</Link>
            ) : (
              <span className="muted">Derived from: -</span>
            )}
            {family.length > 0 && (
              <div className="stack">
                <span className="muted small">Family versions</span>
                {family.map((entry) => (
                  <div key={entry.id} className="item-row">
                    <Link to={entry.artifact_type === "blueprint" && entry.source?.id ? `/app/blueprints/${String(entry.source.id)}` : `/app/artifacts/${entry.id}`}>
                      {entry.title}
                    </Link>
                    <span className="status-pill">{entry.artifact_state}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="stack">
            <strong>Share</strong>
            <div className="inline-actions">
              <input className="input" readOnly value={permalink} />
              <button
                className="ghost sm"
                type="button"
                onClick={async () => {
                  await navigator.clipboard.writeText(permalink);
                  setShareMessage("Permalink copied.");
                  window.setTimeout(() => setShareMessage(null), 1500);
                }}
              >
                Copy link
              </button>
            </div>
            <div className="inline-actions">
              <input className="input" readOnly value={snapshotSummary} />
              <button
                className="ghost sm"
                type="button"
                onClick={async () => {
                  await navigator.clipboard.writeText(snapshotSummary);
                  setShareMessage("Snapshot summary copied.");
                  window.setTimeout(() => setShareMessage(null), 1500);
                }}
              >
                Copy summary
              </button>
            </div>
            {shareMessage && <span className="muted small">{shareMessage}</span>}
          </div>

          <div className="inline-actions">
              {showPublish && (
                <button className="primary" type="button" onClick={onPublish} disabled={busy}>Publish</button>
              )}
              {showDiscard && (
                <button className="ghost" type="button" onClick={onDiscard} disabled={busy}>Discard</button>
              )}
              {showRevise && (
                <button className="ghost" type="button" onClick={onRevise} disabled={busy}>Revise</button>
              )}
              {showIntentScriptAction && (
                <button
                  className="ghost"
                  type="button"
                  disabled={busy || intentSaving}
                  onClick={async () => {
                    if (!artifactId) return;
                    setIntentSaving(true);
                    setIntentError(null);
                    try {
                      const generated = await generateIntentScript({
                        scope_type: "artifact",
                        scope_ref_id: artifactId,
                        audience: "developer",
                        length_target: "short",
                      });
                      setIntentScript(generated.item);
                      setIntentOpen(true);
                    } catch (err) {
                      const message = err instanceof Error ? err.message : "Unable to generate intent script.";
                      setIntentError(message);
                      setIntentOpen(true);
                    } finally {
                      setIntentSaving(false);
                    }
                  }}
                >
                  Generate Intent Script
                </button>
              )}
          </div>
        </>
      )}

      {activeTab === "activity" && (
        <div className="stack">
          {activity.length === 0 ? (
            <p className="muted">No ledger activity recorded.</p>
          ) : (
            activity.map((entry) => (
              <div key={entry.ledger_event_id} className="item-row">
                <div>
                  <strong>{entry.summary || entry.action}</strong>
                  <div className="muted small">{entry.action} · {entry.actor?.display_name || entry.actor?.email || entry.actor?.id || "unknown"}</div>
                </div>
                <span className="muted small">{fmt(entry.created_at)}</span>
              </div>
            ))
          )}
          <Link to={`/app/activity?artifact=${artifactId}`}>View all activity for this artifact</Link>
        </div>
      )}
      <IntentScriptModal
        open={intentOpen}
        script={intentScript}
        saving={intentSaving}
        generationError={intentError}
        onGoToBody={artifactType === "article" ? onGoToBody : undefined}
        onClose={() => {
          setIntentOpen(false);
          setIntentError(null);
        }}
        onSave={async (next) => {
          setIntentSaving(true);
          try {
            const saved = await updateIntentScript(next.intent_script_id, {
              title: next.title,
              script_text: next.script_text,
              script_json: next.script_json as Record<string, unknown>,
            });
            setIntentScript(saved.item);
          } finally {
            setIntentSaving(false);
          }
        }}
      />
    </section>
  );
}
