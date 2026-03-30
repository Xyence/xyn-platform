import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getWorkspaceLinkedChangeSession } from "../../../api/xyn";
import type { WorkspaceLinkedChangeSession } from "../../../api/types";
import { buildLinkedChangeSessionRoute } from "./linkedChangeSessionRoute";

type Props = {
  workspaceId: string;
};

export default function LinkedDevSessionBanner({ workspaceId }: Props) {
  const navigate = useNavigate();
  const [linkedSession, setLinkedSession] = useState<WorkspaceLinkedChangeSession | null>(null);

  useEffect(() => {
    if (!workspaceId) {
      setLinkedSession(null);
      return;
    }
    getWorkspaceLinkedChangeSession(workspaceId, window.location.origin)
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

  const targetRoute = useMemo(() => buildLinkedChangeSessionRoute(workspaceId, linkedSession), [workspaceId, linkedSession]);
  if (!linkedSession || !targetRoute) return null;

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
          {executionStatus ? ` · ${executionStatus.replaceAll("_", " ")}` : ""}
        </p>
      </div>
      <button
        type="button"
        className="ghost sm"
        onClick={() => navigate(targetRoute)}
      >
        Resume session
      </button>
    </section>
  );
}
