import { Suspense, lazy, useEffect } from "react";
import { Route, Routes, useParams } from "react-router-dom";
const AppShell = lazy(() => import("./app/AppShell"));
const LegacyAppRedirect = lazy(() => import("./app/routing/LegacyAppRedirect"));
import RootRedirect from "./app/routing/RootRedirect";
const PublicShell = lazy(() => import("./public/PublicShell"));
const PageRoute = lazy(() => import("./public/pages/PageRoute"));
const ArticlesIndex = lazy(() => import("./public/pages/ArticlesIndex"));
const ArticleDetail = lazy(() => import("./public/pages/ArticleDetail"));
const HomePage = lazy(() => import("./public/pages/HomePage"));

function RouteLoadingShell() {
  return <div style={{ padding: 24 }}>Loading…</div>;
}

function WorkspaceAuthLoginBridge() {
  const params = useParams();
  const workspaceId = String(params.workspaceId || "").trim();
  useEffect(() => {
    if (!workspaceId) return;
    const returnTo = `${window.location.origin}/w/${workspaceId}/build/artifacts`;
    window.location.replace(
      `/xyn/api/workspaces/${workspaceId}/auth/login?returnTo=${encodeURIComponent(returnTo)}`
    );
  }, [workspaceId]);
  return <div style={{ padding: 24 }}>Starting workspace sign-in…</div>;
}

function WorkspaceAuthCallbackBridge() {
  const params = useParams();
  const workspaceId = String(params.workspaceId || "").trim();
  useEffect(() => {
    if (!workspaceId) return;
    const query = window.location.search || "";
    window.location.replace(`/xyn/api/workspaces/${workspaceId}/auth/callback${query}`);
  }, [workspaceId]);
  return <div style={{ padding: 24 }}>Completing workspace sign-in…</div>;
}

function WorkspacesEntry() {
  return <RootRedirect />;
}

function OpenConsoleBridge() {
  return <RootRedirect />;
}

export default function App() {
  return (
    <Suspense fallback={<RouteLoadingShell />}>
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
    </Suspense>
  );
}
