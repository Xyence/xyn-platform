import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { getWorkspaceLinkedChangeSession } from "../../../api/xyn";
import type { WorkspaceLinkedChangeSession } from "../../../api/types";
import { buildLinkedChangeSessionRoute, LINKED_SESSION_UPDATED_EVENT } from "./linkedChangeSessionRoute";

type Props = {
  workspaceId: string;
};

export default function LinkedDevSessionBanner({ workspaceId }: Props) {
  const navigate = useNavigate();
  const location = useLocation();
  const [linkedSession, setLinkedSession] = useState<WorkspaceLinkedChangeSession | null>(null);
  const [resumeMessage, setResumeMessage] = useState("");

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
    void refreshLinkedSession();
  }, [refreshLinkedSession]);

  useEffect(() => {
    const onLinkedSessionUpdated = () => {
      void refreshLinkedSession();
    };
    window.addEventListener(LINKED_SESSION_UPDATED_EVENT, onLinkedSessionUpdated);
    return () => window.removeEventListener(LINKED_SESSION_UPDATED_EVENT, onLinkedSessionUpdated);
  }, [refreshLinkedSession]);

  const targetRoute = useMemo(() => buildLinkedChangeSessionRoute(workspaceId, linkedSession), [workspaceId, linkedSession]);
  if (!linkedSession || !targetRoute) return null;
  const currentRoute = `${location.pathname}${location.search}`;

  const sessionTitle = String(linkedSession.session_title || "").trim();
  const applicationName = String(linkedSession.application_name || "").trim();
  const executionStatus = String(linkedSession.execution_status || "").trim();

  return (
    <section className="linked-dev-session-banner" role="status" aria-live="polite">
      <div className="linked-dev-session-banner-main">
        <p className="linked-dev-session-banner-title">This dev instance is linked to an in-flight change session.</p>
        <p className="muted small">
          {sessionTitle || "Active change session"}
          {applicationName ? ` · ${applicationName}` : ""}
          {executionStatus ? ` · ${executionStatus.replace(/_/g, " ")}` : ""}
        </p>
      </div>
      <button
        type="button"
        className="ghost sm"
        onClick={() => {
          if (targetRoute === currentRoute) {
            setResumeMessage("Already viewing linked session.");
            return;
          }
          setResumeMessage("");
          navigate(targetRoute);
        }}
      >
        Resume session
      </button>
      {resumeMessage ? <p className="muted small">{resumeMessage}</p> : null}
    </section>
  );
}
