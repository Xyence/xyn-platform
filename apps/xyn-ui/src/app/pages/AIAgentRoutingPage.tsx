import { useCallback, useEffect, useMemo, useState } from "react";
import InlineMessage from "../../components/InlineMessage";
import { getAiRoutingStatus, listAiAgents, updateAiRouting } from "../../api/xyn";
import type { AiAgent, AiAgentResolution, AiRoutingStatusResponse } from "../../api/types";
import { useNotifications } from "../state/notificationsStore";

const AI_ROUTING_UPDATED_EVENT = "xyn:ai-routing-updated";

type RoutingPurpose = "default" | "planning" | "coding";

const PURPOSE_ROWS: Array<{ purpose: RoutingPurpose; label: string; helper: string }> = [
  {
    purpose: "default",
    label: "Default",
    helper: "Fallback for any purpose without an explicit assignment.",
  },
  {
    purpose: "planning",
    label: "Planning",
    helper: "Used for planning flows. Leave unset to inherit the default agent.",
  },
  {
    purpose: "coding",
    label: "Coding",
    helper: "Used for coding flows. Leave unset to inherit the default agent.",
  },
];

function resolutionBadge(route: AiAgentResolution): { label: string; tone: string } {
  const resolutionType = String(route.resolution_type || "").toLowerCase();
  if (resolutionType === "required_default" || route.purpose === "default") {
    return { label: "Required Default", tone: "info" };
  }
  if (resolutionType === "explicit" || route.resolution_source === "explicit") {
    return { label: "Explicit", tone: "success" };
  }
  return { label: "Falls Back To Default", tone: "warning" };
}

function assignedAgentName(route: AiAgentResolution): string {
  if (route.purpose === "default") {
    return String(route.resolved_agent_name || "Unassigned");
  }
  const badge = resolutionBadge(route);
  if (badge.label === "Explicit") {
    return String(route.explicit_agent_name || route.resolved_agent_name || "Unassigned");
  }
  return String(route.fallback_agent_name || route.resolved_agent_name || "Default agent");
}

function routeForPurpose(routing: AiRoutingStatusResponse | null, purpose: RoutingPurpose): AiAgentResolution {
  return (
    routing?.routing?.find((entry) => String(entry.purpose || "").toLowerCase() === purpose) || {
      purpose,
      resolution_source: "default_fallback",
      resolved_agent_name: "",
    }
  );
}

export default function AIAgentRoutingPage() {
  const { push } = useNotifications();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [routing, setRouting] = useState<AiRoutingStatusResponse | null>(null);
  const [agents, setAgents] = useState<AiAgent[]>([]);
  const [editPurpose, setEditPurpose] = useState<RoutingPurpose | null>(null);
  const [draftAgentId, setDraftAgentId] = useState<string>("");
  const [savingPurpose, setSavingPurpose] = useState<RoutingPurpose | null>(null);

  const emitRoutingUpdated = useCallback((nextRouting: AiRoutingStatusResponse) => {
    window.dispatchEvent(new CustomEvent(AI_ROUTING_UPDATED_EVENT, { detail: { routing: nextRouting } }));
  }, []);

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const [routingRes, agentsRes] = await Promise.all([getAiRoutingStatus(), listAiAgents({ enabled: true })]);
      setRouting(routingRes);
      emitRoutingUpdated(routingRes);
      setAgents((agentsRes.agents || []).filter((entry) => entry.enabled));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [emitRoutingUpdated]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const compatibleByPurpose = useMemo(() => {
    const byPurpose: Record<RoutingPurpose, AiAgent[]> = {
      default: [...agents],
      planning: agents.filter((agent) => (agent.purposes || []).includes("planning") || agent.is_default),
      coding: agents.filter((agent) => (agent.purposes || []).includes("coding") || agent.is_default),
    };
    return byPurpose;
  }, [agents]);

  const openEditor = (purpose: RoutingPurpose) => {
    const route = routeForPurpose(routing, purpose);
    const badge = resolutionBadge(route);
    const initialAgentId = purpose === "default" ? String(route.resolved_agent_id || "") : badge.label === "Explicit" ? String(route.explicit_agent_id || route.resolved_agent_id || "") : "";
    setDraftAgentId(initialAgentId);
    setEditPurpose(purpose);
  };

  const applyUpdate = async (purpose: RoutingPurpose, value: string | null) => {
    const payload: { default_agent_id?: string; planning_agent_id?: string | null; coding_agent_id?: string | null } = {};
    if (purpose === "default") {
      payload.default_agent_id = String(value || "").trim();
    } else if (purpose === "planning") {
      payload.planning_agent_id = value;
    } else {
      payload.coding_agent_id = value;
    }

    try {
      setSavingPurpose(purpose);
      setError(null);
      const next = await updateAiRouting(payload);
      setRouting(next);
      emitRoutingUpdated(next);
      push({ level: "success", title: "Routing updated", message: `${purpose[0].toUpperCase()}${purpose.slice(1)} assignment saved.` });
      setEditPurpose(null);
      setDraftAgentId("");
    } catch (err) {
      const message = (err as Error).message;
      setError(message);
      push({ level: "error", title: "Routing update failed", message });
    } finally {
      setSavingPurpose(null);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h2>AI Agent Routing</h2>
          <p className="muted">Inspect and manage persistent purpose-based agent routing.</p>
        </div>
        <div className="inline-actions">
          <button className="ghost" onClick={() => void refresh()} disabled={loading || Boolean(savingPurpose)}>
            {loading ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}

      <section className="card">
        <div className="canvas-table-wrap">
          <table className="canvas-table" aria-label="AI routing table">
            <thead>
              <tr>
                <th>Purpose</th>
                <th>Assigned Agent</th>
                <th>Resolution</th>
                <th>Details</th>
                <th style={{ width: 180 }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {PURPOSE_ROWS.map((row) => {
                const route = routeForPurpose(routing, row.purpose);
                const badge = resolutionBadge(route);
                const editing = editPurpose === row.purpose;
                const options = compatibleByPurpose[row.purpose];
                const isSaving = savingPurpose === row.purpose;
                return (
                  <tr key={row.purpose}>
                    <td><strong>{row.label}</strong></td>
                    <td>{assignedAgentName(route)}</td>
                    <td>
                      <span className={`chip ${badge.tone}`}>{badge.label}</span>
                    </td>
                    <td>
                      <span className="muted small">{row.helper}</span>
                    </td>
                    <td>
                      {!editing ? (
                        <button type="button" className="ghost sm" onClick={() => openEditor(row.purpose)} disabled={Boolean(savingPurpose)}>
                          Change
                        </button>
                      ) : (
                        <div style={{ display: "grid", gap: 8 }}>
                          <select
                            value={draftAgentId}
                            onChange={(event) => setDraftAgentId(event.target.value)}
                            disabled={isSaving}
                            aria-label={`${row.label} agent selector`}
                          >
                            {row.purpose !== "default" ? <option value="">Use default fallback</option> : null}
                            {options.map((agent) => (
                              <option key={agent.id} value={agent.id}>{agent.name}</option>
                            ))}
                          </select>
                          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                            <button
                              type="button"
                              className="primary sm"
                              onClick={() => void applyUpdate(row.purpose, draftAgentId || (row.purpose === "default" ? "" : null))}
                              disabled={isSaving || (row.purpose === "default" && !draftAgentId)}
                            >
                              {isSaving ? "Saving..." : "Save"}
                            </button>
                            {row.purpose !== "default" ? (
                              <button
                                type="button"
                                className="ghost sm"
                                onClick={() => void applyUpdate(row.purpose, null)}
                                disabled={isSaving}
                              >
                                Clear
                              </button>
                            ) : null}
                            <button
                              type="button"
                              className="ghost sm"
                              onClick={() => {
                                setEditPurpose(null);
                                setDraftAgentId("");
                              }}
                              disabled={isSaving}
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
