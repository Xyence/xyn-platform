import { Outlet, useLocation } from "react-router-dom";
import AppShell from "../AppShell";
import RootRedirect from "./RootRedirect";
import { isGlobalAppPath } from "./workspaceRouting";

function readFlag(value: unknown): boolean {
  return String(value || "").trim().toLowerCase() === "true";
}

const ENABLE_LEGACY_UI = readFlag(import.meta.env.VITE_ENABLE_LEGACY_UI);

export default function LegacyAppRedirect() {
  const location = useLocation();

  if (ENABLE_LEGACY_UI) {
    return <AppShell />;
  }

  if (isGlobalAppPath(location.pathname)) {
    return <AppShell />;
  }
  return <RootRedirect />;
}

export function LegacyAppOutlet() {
  if (!ENABLE_LEGACY_UI) return <LegacyAppRedirect />;
  return <Outlet />;
}
