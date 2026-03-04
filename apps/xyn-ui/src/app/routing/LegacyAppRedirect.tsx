import { Navigate, Outlet, useLocation } from "react-router-dom";
import AppShell from "../AppShell";
import { DEFAULT_WORKSPACE_SUBPATH, toWorkspacePath } from "./workspaceRouting";

function readFlag(value: unknown): boolean {
  return String(value || "").trim().toLowerCase() === "true";
}

const ENABLE_LEGACY_UI = readFlag(import.meta.env.VITE_ENABLE_LEGACY_UI);

function preferredWorkspaceId(): string {
  if (typeof window === "undefined") return "";
  return String(window.localStorage.getItem("xyn.activeWorkspaceId") || "").trim();
}

export default function LegacyAppRedirect() {
  const location = useLocation();

  if (ENABLE_LEGACY_UI) {
    return <AppShell />;
  }

  const workspaceId = preferredWorkspaceId();
  const target = workspaceId ? toWorkspacePath(workspaceId, DEFAULT_WORKSPACE_SUBPATH) : "/";

  if (import.meta.env.DEV) {
    // eslint-disable-next-line no-console
    console.info(
      `[legacy-ui] redirect ${location.pathname}${location.search || ""}${location.hash || ""} -> ${target}`
    );
  }

  return <Navigate to={target} replace />;
}

export function LegacyAppOutlet() {
  if (!ENABLE_LEGACY_UI) return <LegacyAppRedirect />;
  return <Outlet />;
}
