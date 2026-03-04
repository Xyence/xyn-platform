import { useEffect } from "react";
import { Route, Routes, useParams } from "react-router-dom";
import AppShell from "./app/AppShell";
import LegacyAppRedirect from "./app/routing/LegacyAppRedirect";
import RootRedirect from "./app/routing/RootRedirect";
import PublicShell from "./public/PublicShell";
import PageRoute from "./public/pages/PageRoute";
import ArticlesIndex from "./public/pages/ArticlesIndex";
import ArticleDetail from "./public/pages/ArticleDetail";
import HomePage from "./public/pages/HomePage";
import { resolveApiBaseUrl } from "./api/client";

function WorkspaceAuthLoginBridge() {
  const params = useParams();
  const workspaceId = String(params.workspaceId || "").trim();
  useEffect(() => {
    if (!workspaceId) return;
    const apiBase = resolveApiBaseUrl();
    const returnTo = `${window.location.origin}/w/${workspaceId}/build/artifacts`;
    window.location.replace(
      `${apiBase}/xyn/api/workspaces/${workspaceId}/auth/login?returnTo=${encodeURIComponent(returnTo)}`
    );
  }, [workspaceId]);
  return <div style={{ padding: 24 }}>Starting workspace sign-in…</div>;
}

function WorkspaceAuthCallbackBridge() {
  const params = useParams();
  const workspaceId = String(params.workspaceId || "").trim();
  useEffect(() => {
    if (!workspaceId) return;
    const apiBase = resolveApiBaseUrl();
    const query = window.location.search || "";
    window.location.replace(`${apiBase}/xyn/api/workspaces/${workspaceId}/auth/callback${query}`);
  }, [workspaceId]);
  return <div style={{ padding: 24 }}>Completing workspace sign-in…</div>;
}

function WorkspacesEntry() {
  const workspaceId = String(window.localStorage.getItem("xyn.activeWorkspaceId") || "").trim();
  if (workspaceId) {
    return <RootRedirect />;
  }
  return <AppShell />;
}

function OpenConsoleBridge() {
  return <RootRedirect />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/w/:workspaceId/auth/login" element={<WorkspaceAuthLoginBridge />} />
      <Route path="/w/:workspaceId/auth/callback" element={<WorkspaceAuthCallbackBridge />} />
      <Route path="/w/:workspaceId/*" element={<AppShell />} />
      <Route path="/workspaces" element={<WorkspacesEntry />} />
      <Route path="/open-console" element={<OpenConsoleBridge />} />
      <Route path="/app/*" element={<LegacyAppRedirect />} />
      <Route path="/*" element={<PublicShell />}>
        <Route index element={<HomePage />} />
        <Route path="articles" element={<ArticlesIndex />} />
        <Route path="articles/:slug" element={<ArticleDetail />} />
        <Route path=":category/:slug" element={<ArticleDetail />} />
        <Route path="*" element={<PageRoute />} />
      </Route>
    </Routes>
  );
}
