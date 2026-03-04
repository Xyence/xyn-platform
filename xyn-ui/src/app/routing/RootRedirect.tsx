import { Navigate } from "react-router-dom";
import { DEFAULT_WORKSPACE_SUBPATH, toWorkspacePath } from "./workspaceRouting";

function preferredWorkspaceId(): string {
  if (typeof window === "undefined") return "";
  return String(window.localStorage.getItem("xyn.activeWorkspaceId") || "").trim();
}

export default function RootRedirect() {
  const workspaceId = preferredWorkspaceId();
  if (workspaceId) {
    return <Navigate to={toWorkspacePath(workspaceId, DEFAULT_WORKSPACE_SUBPATH)} replace />;
  }
  return <Navigate to="/workspaces" replace />;
}
