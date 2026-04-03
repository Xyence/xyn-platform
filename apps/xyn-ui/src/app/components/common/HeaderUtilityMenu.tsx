import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Compass, Settings2, Activity, Bot, ShieldCheck } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { getAiRoutingStatus, getSystemReadiness, getWorkspaceLinkedChangeSession } from "../../../api/xyn";
import type { AiAgentResolution, AiRoutingStatusResponse, SystemReadinessResponse, WorkspaceLinkedChangeSession } from "../../../api/types";
import { toWorkspacePath } from "../../routing/workspaceRouting";
import { useXynConsole } from "../../state/xynConsoleStore";
import HeaderPreviewControl from "../preview/HeaderPreviewControl";
import { type CapabilityEntry, useCapabilitySuggestions } from "../console/capabilitySuggestions";
import { buildLinkedChangeSessionRoute, LINKED_SESSION_UPDATED_EVENT } from "./linkedChangeSessionRoute";

const AI_ROUTING_UPDATED_EVENT = "xyn:ai-routing-updated";

type Props = {
  workspaceId: string;
  actorRoles: string[];
  actorLabel: string;
  onOpenAgentActivity: () => void;
  onMessage: (payload: { level: "success" | "error"; title: string; message?: string }) => void;
};

function routingPurposeRow(routing: AiAgentResolution[], purpose: string): AiAgentResolution | null {
  return routing.find((row) => String(row.purpose || "").trim().toLowerCase() === purpose) || null;
}

function routingStatusLabel(row: AiAgentResolution | null): string {
  if (!row || !row.resolved_agent_name) return "Missing";
  if (row.resolution_source === "explicit") return "Explicit";
  if (row.resolution_source === "default_fallback") return "Fallback";
  return "Missing";
}

function titleCaseToken(value: string): string {
  return String(value || "")
    .split(/[_\-\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function readinessTone(readiness: SystemReadinessResponse | null): "ok" | "warning" | "error" {
  if (!readiness) return "warning";
  if (readiness.ready) return "ok";
  return readiness.checks.some((check) => check.status === "error") ? "error" : "warning";
}

export default function HeaderUtilityMenu({ workspaceId, actorRoles, actorLabel, onOpenAgentActivity, onMessage }: Props) {
  const navigate = useNavigate();
  const location = useLocation();
  const rootRef = useRef<HTMLDivElement | null>(null);
  const { openPanel, setInputText, setOpen, requestSubmit } = useXynConsole();
  const [open, setOpenPopover] = useState(false);
  const [routingStatus, setRoutingStatus] = useState<AiRoutingStatusResponse | null>(null);
  const [systemReadiness, setSystemReadiness] = useState<SystemReadinessResponse | null>(null);
  const [linkedSession, setLinkedSession] = useState<WorkspaceLinkedChangeSession | null>(null);
  const { capabilities, platform } = useCapabilitySuggestions(workspaceId);

  const refreshAiRoutingStatus = useCallback(() => {
    getAiRoutingStatus()
      .then((next) => setRoutingStatus(next))
      .catch(() => setRoutingStatus(null));
  }, []);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current) return;
      if (!(event.target instanceof Node)) return;
      if (!rootRef.current.contains(event.target)) setOpenPopover(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  useEffect(() => {
    getSystemReadiness()
      .then((next) => setSystemReadiness(next))
      .catch(() => setSystemReadiness(null));
  }, [workspaceId]);

  const refreshLinkedSession = useCallback(() => {
    if (!workspaceId) {
      setLinkedSession(null);
      return Promise.resolve();
    }
    return getWorkspaceLinkedChangeSession(workspaceId, window.location.origin)
      .then((payload) => {
        const linked = payload?.linked_session;
        if (!linked || !linked.application_id || !linked.solution_change_session_id) {
          setLinkedSession(null);
          return;
        }
        setLinkedSession(linked);
      })
      .catch(() => setLinkedSession(null));
  }, [workspaceId]);

  useEffect(() => {
    if (!open) return;
    void refreshLinkedSession();
  }, [open, refreshLinkedSession]);

  useEffect(() => {
    refreshAiRoutingStatus();
  }, [refreshAiRoutingStatus, workspaceId]);

  useEffect(() => {
    const onRoutingUpdated = (event: Event) => {
      const detail = (event as CustomEvent<{ routing?: AiRoutingStatusResponse }>).detail;
      if (detail?.routing) {
        setRoutingStatus(detail.routing);
        return;
      }
      refreshAiRoutingStatus();
    };
    window.addEventListener(AI_ROUTING_UPDATED_EVENT, onRoutingUpdated as EventListener);
    return () => window.removeEventListener(AI_ROUTING_UPDATED_EVENT, onRoutingUpdated as EventListener);
  }, [refreshAiRoutingStatus]);

  useEffect(() => {
    const onLinkedSessionUpdated = () => {
      if (!open) return;
      void refreshLinkedSession();
    };
    window.addEventListener(LINKED_SESSION_UPDATED_EVENT, onLinkedSessionUpdated);
    return () => window.removeEventListener(LINKED_SESSION_UPDATED_EVENT, onLinkedSessionUpdated);
  }, [open, refreshLinkedSession]);

  const openCapability = (entry: CapabilityEntry) => {
    const target = entry.managePath || entry.docsPath;
    if (target) {
      if (/^https?:\/\//i.test(target)) {
        window.location.href = target;
        return;
      }
      const resolved = target.startsWith("/w/")
        ? target
        : target.startsWith("/")
          ? toWorkspacePath(workspaceId, target.replace(/^\/+/, ""))
          : toWorkspacePath(workspaceId, target);
      navigate(resolved);
      setOpenPopover(false);
      return;
    }
    openPanel({ key: "artifact_detail", params: { slug: entry.artifactSlug }, open_in: "current_panel" });
    setOpenPopover(false);
  };

  const runSuggestion = (prompt: string) => {
    const text = String(prompt || "").trim();
    if (!text) return;
    setInputText(text);
    setOpen(true);
    requestSubmit();
    setOpenPopover(false);
  };

  const topCapabilities = useMemo(() => [...capabilities, ...platform].slice(0, 5), [capabilities, platform]);
  const topSuggestions = useMemo(
    () =>
      [...capabilities, ...platform]
        .flatMap((entry) => entry.suggestions)
        .filter((entry) => entry.visibility.map((value) => value.toLowerCase()).includes("capability"))
        .slice(0, 4),
    [capabilities, platform],
  );

  const routingRows = useMemo(
    () => [
      { purpose: "Default", row: routingPurposeRow(routingStatus?.routing || [], "default") },
      { purpose: "Planning", row: routingPurposeRow(routingStatus?.routing || [], "planning") },
      { purpose: "Coding", row: routingPurposeRow(routingStatus?.routing || [], "coding") },
      { purpose: "Palette", row: routingPurposeRow(routingStatus?.routing || [], "palette") },
    ],
    [routingStatus?.routing],
  );

  const linkedSessionRoute = useMemo(() => {
    return buildLinkedChangeSessionRoute(workspaceId, linkedSession);
  }, [linkedSession, workspaceId]);

  return (
    <div className="header-utility-wrap" ref={rootRef}>
      <button
        type="button"
        className="ghost notification-bell header-utility-trigger"
        aria-label="Utilities"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpenPopover((value) => !value)}
      >
        <Settings2 size={16} />
      </button>
      {open ? (
        <section className="header-utility-popover" role="dialog" aria-label="Workbench utilities">
          <div className="header-utility-section">
            <h4><Compass size={14} /> Capabilities</h4>
            <div className="header-utility-capability-list">
              {topCapabilities.length ? (
                topCapabilities.map((entry) => (
                  <button key={entry.key} type="button" className="ghost sm" onClick={() => openCapability(entry)}>
                    {entry.title}
                  </button>
                ))
              ) : (
                <p className="muted small">No capabilities available.</p>
              )}
            </div>
            {topSuggestions.length ? (
              <div className="header-utility-suggestion-list">
                {topSuggestions.map((entry) => (
                  <button key={entry.key} type="button" className="ghost sm" onClick={() => runSuggestion(entry.prompt)}>
                    {entry.suggestionLabel || entry.prompt}
                  </button>
                ))}
              </div>
            ) : null}
          </div>

          <div className="header-utility-section">
            <h4><Activity size={14} /> Activity</h4>
            <button
              type="button"
              className="ghost sm"
              onClick={() => {
                onOpenAgentActivity();
                setOpenPopover(false);
              }}
            >
              Open Agent Activity
            </button>
            {linkedSession && linkedSessionRoute ? (
              <>
                <p className="muted small">Linked dev session</p>
                <button
                  type="button"
                  className="ghost sm"
                  onClick={() => {
                    const currentRoute = `${location.pathname}${location.search}`;
                    if (linkedSessionRoute === currentRoute) {
                      onMessage({ level: "success", title: "Already viewing linked session" });
                      setOpenPopover(false);
                      return;
                    }
                    navigate(linkedSessionRoute);
                    setOpenPopover(false);
                  }}
                >
                  Resume change session
                </button>
              </>
            ) : null}
          </div>

          <div className="header-utility-section">
            <h4><ShieldCheck size={14} /> Preview As Role</h4>
            <HeaderPreviewControl actorRoles={actorRoles} actorLabel={actorLabel} onMessage={onMessage} />
          </div>

          <div className="header-utility-section">
            <h4><Bot size={14} /> AI Agent Routing</h4>
            <div className="header-utility-summary-grid">
              {routingRows.map((entry) => {
                const status = routingStatusLabel(entry.row);
                return (
                  <div key={entry.purpose} className="header-utility-summary-row">
                    <span className="field-label">{entry.purpose}</span>
                    <span className="field-value">
                      {entry.row?.resolved_agent_name || "Not configured"}
                      <span className={`ai-routing-status ${status.toLowerCase()}`}>{status}</span>
                    </span>
                  </div>
                );
              })}
            </div>
            <button
              type="button"
              className="ghost sm"
              onClick={() => {
                navigate(toWorkspacePath(workspaceId, "workbench?panel=platform_settings&surface=ai_routing"));
                setOpenPopover(false);
              }}
            >
              Open AI Agent Routing Settings
            </button>
          </div>

          <div className="header-utility-section">
            <h4>System Readiness</h4>
            <p className={`muted small readiness-${readinessTone(systemReadiness)}`}>
              {systemReadiness?.summary || "Readiness status unavailable."}
            </p>
            <div className="header-utility-summary-grid">
              {(systemReadiness?.checks || []).slice(0, 4).map((check) => (
                <div key={check.component} className="header-utility-summary-row">
                  <span className="field-label">{titleCaseToken(check.component)}</span>
                  <span className="field-value">{check.message}</span>
                </div>
              ))}
            </div>
            <button
              type="button"
              className="ghost sm"
              onClick={() => {
                navigate(toWorkspacePath(workspaceId, "workbench?panel=platform_settings&surface=hub"));
                setOpenPopover(false);
              }}
            >
              Open Platform Settings
            </button>
          </div>
        </section>
      ) : null}
    </div>
  );
}
