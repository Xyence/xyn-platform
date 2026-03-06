import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { getMe } from "../../api/xyn";
import { resolvePostLoginDestination } from "./bootstrapResolver";

function preferredWorkspaceId(): string {
  if (typeof window === "undefined") return "";
  return String(window.localStorage.getItem("xyn.activeWorkspaceId") || "").trim();
}

export default function RootRedirect() {
  const [target, setTarget] = useState<string>("");

  useEffect(() => {
    let mounted = true;
    const persisted = preferredWorkspaceId();
    (async () => {
      try {
        const me = await getMe();
        if (!mounted) return;
        const destination = resolvePostLoginDestination(me, persisted);
        const workspaces = Array.isArray(me.workspaces) ? me.workspaces : [];
        const validIds = new Set(workspaces.map((workspace) => String(workspace.id || "").trim()).filter(Boolean));
        if (persisted && !validIds.has(persisted)) {
          window.localStorage.removeItem("xyn.activeWorkspaceId");
        }
        setTarget(destination);
      } catch {
        if (!mounted) return;
        if (persisted) {
          window.localStorage.removeItem("xyn.activeWorkspaceId");
        }
        setTarget("/app/platform/hub");
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  if (!target) return null;
  return <Navigate to={target} replace />;
}
