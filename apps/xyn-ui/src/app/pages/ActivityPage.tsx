import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import { getLedgerSummaryByUser, listLedgerEvents } from "../../api/xyn";
import type { LedgerEventSummary, LedgerSummaryByUserRow } from "../../api/types";

type ActivityTab = "feed" | "contributions";
type DatePreset = "7d" | "30d" | "custom";

const ACTION_OPTIONS = ["", "artifact.create", "artifact.update", "artifact.canonize", "artifact.deprecate", "artifact.archive"];
const ARTIFACT_TYPE_OPTIONS = ["", "draft_session", "blueprint", "article", "workflow", "module", "context_pack"];

function humanizeAction(action: string): string {
  const value = action.replace(/^artifact\./, "").replace(/_/g, " ");
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function formatTimestamp(value?: string): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

function toIsoDateInput(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function resolveDateRange(preset: DatePreset, customSince: string, customUntil: string): { since?: string; until?: string } {
  if (preset === "custom") {
    return {
      since: customSince ? `${customSince}T00:00:00Z` : undefined,
      until: customUntil ? `${customUntil}T23:59:59Z` : undefined,
    };
  }
  const until = new Date();
  const since = new Date();
  since.setDate(until.getDate() - (preset === "7d" ? 7 : 30));
  return { since: since.toISOString(), until: until.toISOString() };
}

function artifactLink(event: LedgerEventSummary): string {
  const sourceType = String(event.source_ref_type || "").trim();
  const sourceId = String(event.source_ref_id || "").trim();
  if (sourceType === "Blueprint" && sourceId) return `/app/blueprints/${sourceId}`;
  if (sourceType === "BlueprintDraftSession" && sourceId) return `/app/drafts/${sourceId}`;
  return `/app/artifacts/${event.artifact_id}`;
}

function uniqueActors(events: LedgerEventSummary[]): Array<{ id: string; label: string }> {
  const seen = new Set<string>();
  const rows: Array<{ id: string; label: string }> = [];
  for (const event of events) {
    const id = String(event.actor?.id || event.actor_user_id || "").trim();
    if (!id || seen.has(id)) continue;
    seen.add(id);
    const label = String(event.actor?.display_name || event.actor?.email || id);
    rows.push({ id, label });
  }
  rows.sort((a, b) => a.label.localeCompare(b.label));
  return rows;
}

function detailsJson(event: LedgerEventSummary): string {
  const payload = event.metadata_json || {};
  return JSON.stringify(payload, null, 2);
}

export default function ActivityPage({
  workspaceId,
  defaultTab = "feed",
}: {
  workspaceId: string;
  defaultTab?: ActivityTab;
}) {
  const [activeTab, setActiveTab] = useState<ActivityTab>(defaultTab);
  const [events, setEvents] = useState<LedgerEventSummary[]>([]);
  const [summaryRows, setSummaryRows] = useState<LedgerSummaryByUserRow[]>([]);
  const [selectedActorId, setSelectedActorId] = useState("");
  const [actorTimeline, setActorTimeline] = useState<LedgerEventSummary[]>([]);
  const [actionFilter, setActionFilter] = useState("");
  const [artifactTypeFilter, setArtifactTypeFilter] = useState("");
  const [actorFilter, setActorFilter] = useState("");
  const [workspaceFilter, setWorkspaceFilter] = useState<"current" | "all">("current");
  const [datePreset, setDatePreset] = useState<DatePreset>("30d");
  const [customSince, setCustomSince] = useState(() => {
    const since = new Date();
    since.setDate(since.getDate() - 30);
    return toIsoDateInput(since);
  });
  const [customUntil, setCustomUntil] = useState(() => toIsoDateInput(new Date()));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setActiveTab(defaultTab);
  }, [defaultTab]);

  const range = useMemo(() => resolveDateRange(datePreset, customSince, customUntil), [datePreset, customSince, customUntil]);
  const workspaceParam = workspaceFilter === "current" && workspaceId ? workspaceId : undefined;
  const actorOptions = useMemo(() => uniqueActors(events), [events]);

  const loadFeed = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const payload = await listLedgerEvents({
        workspace: workspaceParam,
        actor: actorFilter || undefined,
        artifact_type: artifactTypeFilter || undefined,
        action: actionFilter || undefined,
        since: range.since,
        until: range.until,
        limit: 250,
      });
      setEvents(payload.events || []);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [workspaceParam, actorFilter, artifactTypeFilter, actionFilter, range.since, range.until]);

  const loadSummary = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const payload = await getLedgerSummaryByUser({
        workspace: workspaceParam,
        since: range.since,
        until: range.until,
      });
      setSummaryRows(payload.rows || []);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [workspaceParam, range.since, range.until]);

  const loadActorTimeline = useCallback(async () => {
    if (!selectedActorId) {
      setActorTimeline([]);
      return;
    }
    try {
      const payload = await listLedgerEvents({
        workspace: workspaceParam,
        actor: selectedActorId,
        since: range.since,
        until: range.until,
        limit: 200,
      });
      setActorTimeline(payload.events || []);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [selectedActorId, workspaceParam, range.since, range.until]);

  useEffect(() => {
    if (activeTab === "feed") {
      void loadFeed();
    } else {
      void loadSummary();
    }
  }, [activeTab, loadFeed, loadSummary]);

  useEffect(() => {
    if (activeTab === "contributions") {
      void loadActorTimeline();
    }
  }, [activeTab, loadActorTimeline]);

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Activity</h2>
          <p className="muted">Governance ledger for artifact lifecycle and accountability.</p>
        </div>
        <div className="inline-actions">
          <button
            type="button"
            className={`ghost sm ${activeTab === "feed" ? "active" : ""}`}
            onClick={() => setActiveTab("feed")}
          >
            Activity Feed
          </button>
          <button
            type="button"
            className={`ghost sm ${activeTab === "contributions" ? "active" : ""}`}
            onClick={() => setActiveTab("contributions")}
          >
            Contributions
          </button>
          <button className="ghost" onClick={activeTab === "feed" ? () => void loadFeed() : () => void loadSummary()} disabled={loading}>
            Refresh
          </button>
        </div>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}

      <section className="card">
        <div className="form-grid compact">
          <label>
            Workspace
            <select className="input" value={workspaceFilter} onChange={(event) => setWorkspaceFilter(event.target.value as "current" | "all")}>
              <option value="current">Current workspace</option>
              <option value="all">All workspaces</option>
            </select>
          </label>
          <label>
            Date range
            <select className="input" value={datePreset} onChange={(event) => setDatePreset(event.target.value as DatePreset)}>
              <option value="7d">Last 7 days</option>
              <option value="30d">Last 30 days</option>
              <option value="custom">Custom</option>
            </select>
          </label>
          {datePreset === "custom" && (
            <>
              <label>
                Since
                <input className="input" type="date" value={customSince} onChange={(event) => setCustomSince(event.target.value)} />
              </label>
              <label>
                Until
                <input className="input" type="date" value={customUntil} onChange={(event) => setCustomUntil(event.target.value)} />
              </label>
            </>
          )}
          {activeTab === "feed" && (
            <>
              <label>
                Actor
                <select className="input" value={actorFilter} onChange={(event) => setActorFilter(event.target.value)}>
                  <option value="">All actors</option>
                  {actorOptions.map((actor) => (
                    <option key={actor.id} value={actor.id}>
                      {actor.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Artifact type
                <select className="input" value={artifactTypeFilter} onChange={(event) => setArtifactTypeFilter(event.target.value)}>
                  {ARTIFACT_TYPE_OPTIONS.map((option) => (
                    <option key={option || "all"} value={option}>
                      {option ? option : "All artifact types"}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Action
                <select className="input" value={actionFilter} onChange={(event) => setActionFilter(event.target.value)}>
                  {ACTION_OPTIONS.map((option) => (
                    <option key={option || "all"} value={option}>
                      {option ? option : "All actions"}
                    </option>
                  ))}
                </select>
              </label>
            </>
          )}
        </div>
      </section>

      {activeTab === "feed" && (
        <section className="card" data-testid="activity-feed-card">
          <div className="instance-list">
            {events.map((event) => (
              <div className="instance-row" key={event.ledger_event_id}>
                <div>
                  <strong>{event.summary || humanizeAction(event.action)}</strong>
                  <span className="muted small">
                    {event.actor?.display_name || event.actor?.email || event.actor?.id || "unknown actor"} ·{" "}
                    <Link to={artifactLink(event)}>{event.artifact_title || event.artifact_id}</Link>
                  </span>
                  <details>
                    <summary className="muted small">Details</summary>
                    <pre className="xyn-ledger" style={{ marginTop: 8 }}>{detailsJson(event)}</pre>
                  </details>
                </div>
                <div className="stack" style={{ alignItems: "flex-end" }}>
                  <span className="status-pill">{humanizeAction(event.action)}</span>
                  <span className="muted small">{formatTimestamp(event.created_at)}</span>
                </div>
              </div>
            ))}
            {!loading && events.length === 0 && <p className="muted">No ledger activity for the selected filters.</p>}
          </div>
        </section>
      )}

      {activeTab === "contributions" && (
        <div className="layout">
          <section className="card">
            <div className="card-header">
              <h3>Contributions by user</h3>
            </div>
            <div className="instance-list" role="table" aria-label="Contributions table">
              <div className="instance-row" role="row">
                <div role="columnheader">
                  <strong>User</strong>
                </div>
                <div role="columnheader" className="muted small">
                  Create · Update · Publish · Canonize · Total
                </div>
              </div>
              {summaryRows.map((row) => (
                <button
                  key={row.actor_user_id}
                  className={`instance-row ${selectedActorId === row.actor_user_id ? "active" : ""}`}
                  type="button"
                  onClick={() => setSelectedActorId(row.actor_user_id)}
                >
                  <div>
                    <strong>{row.display_name || row.email || row.actor_user_id}</strong>
                    <span className="muted small">{row.email || row.actor_user_id}</span>
                    {row.top_artifacts.length > 0 && (
                      <span className="muted small">
                        Top artifacts:{" "}
                        {row.top_artifacts.slice(0, 3).map((entry) => entry.title).join(", ")}
                      </span>
                    )}
                  </div>
                  <div className="muted small">
                    {row.create_count} · {row.update_count} · {row.publish_count} · {row.canonize_count} · {row.total_count}
                  </div>
                </button>
              ))}
              {!loading && summaryRows.length === 0 && <p className="muted">No contribution data for this period.</p>}
            </div>
          </section>

          <section className="card">
            <div className="card-header">
              <h3>{selectedActorId ? "User timeline" : "User timeline"}</h3>
            </div>
            {!selectedActorId ? (
              <p className="muted">Select a user to view their activity timeline.</p>
            ) : (
              <div className="instance-list">
                {actorTimeline.map((event) => (
                  <div className="instance-row" key={event.ledger_event_id}>
                    <div>
                      <strong>{event.summary || humanizeAction(event.action)}</strong>
                      <span className="muted small">
                        <Link to={artifactLink(event)}>{event.artifact_title || event.artifact_id}</Link>
                      </span>
                      <details>
                        <summary className="muted small">Details</summary>
                        <pre className="xyn-ledger" style={{ marginTop: 8 }}>{detailsJson(event)}</pre>
                      </details>
                    </div>
                    <div className="stack" style={{ alignItems: "flex-end" }}>
                      <span className="status-pill">{humanizeAction(event.action)}</span>
                      <span className="muted small">{formatTimestamp(event.created_at)}</span>
                    </div>
                  </div>
                ))}
                {!loading && actorTimeline.length === 0 && <p className="muted">No events for the selected user and range.</p>}
              </div>
            )}
          </section>
        </div>
      )}
    </>
  );
}
