import { useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { resolveArtifactSurface } from "../../api/xyn";
import type { ArtifactSurfaceResolveResponse } from "../../api/types";
import ArtifactsArticlesPage from "./ArtifactsArticlesPage";
import ArtifactsWorkflowsPage from "./ArtifactsWorkflowsPage";
import ArtifactDetailPage from "./ArtifactDetailPage";

type SurfaceRenderTarget =
  | { kind: "articles_index" }
  | { kind: "workflows_index" }
  | { kind: "artifact_detail" };

function resolveSurfaceRenderTarget(payload: ArtifactSurfaceResolveResponse): SurfaceRenderTarget | null {
  const surface = payload.surface || ({} as ArtifactSurfaceResolveResponse["surface"]);
  const renderer = (surface.renderer || {}) as Record<string, unknown>;
  const rendererType = String(renderer.type || "").trim().toLowerCase();
  const rendererPayload = (renderer.payload || {}) as Record<string, unknown>;
  const componentKey = String(rendererPayload.component_key || "").trim().toLowerCase();

  if (rendererType === "ui_component_ref") {
    if (componentKey === "articles.index") return { kind: "articles_index" };
    if (componentKey === "workflows.index") return { kind: "workflows_index" };
    if (componentKey === "articles.draft_editor") return { kind: "artifact_detail" };
    if (componentKey === "workflows.editor" || componentKey === "workflows.visualizer") return { kind: "artifact_detail" };
  }

  if (rendererType === "article_editor" || rendererType === "workflow_visualizer") return { kind: "artifact_detail" };
  return null;
}

export default function ArtifactSurfaceRoutePage({
  workspaceId,
  workspaceRole,
  canManageArticleLifecycle,
  canCreate,
}: {
  workspaceId: string;
  workspaceRole: string;
  canManageArticleLifecycle: boolean;
  canCreate: boolean;
}) {
  const location = useLocation();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resolved, setResolved] = useState<ArtifactSurfaceResolveResponse | null>(null);

  const requestPath = useMemo(() => location.pathname, [location.pathname]);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const payload = await resolveArtifactSurface(requestPath);
        if (!mounted) return;
        setResolved(payload);
      } catch (err) {
        if (!mounted) return;
        setError((err as Error).message || "Failed to resolve artifact surface.");
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [requestPath]);

  if (loading) {
    return (
      <div className="card stack">
        <h2>Loading surface</h2>
        <p className="muted">Resolving artifact surface route...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card stack">
        <h2>Surface unavailable</h2>
        <p className="danger">{error}</p>
      </div>
    );
  }

  const target = resolved ? resolveSurfaceRenderTarget(resolved) : null;
  if (target?.kind === "articles_index") {
    return <ArtifactsArticlesPage workspaceId={workspaceId} canCreate={canCreate} />;
  }
  if (target?.kind === "workflows_index") {
    return <ArtifactsWorkflowsPage workspaceId={workspaceId} canCreate={canCreate} />;
  }
  if (target?.kind === "artifact_detail") {
    return (
      <ArtifactDetailPage
        workspaceId={workspaceId}
        workspaceRole={workspaceRole}
        canManageArticleLifecycle={canManageArticleLifecycle}
      />
    );
  }

  return (
    <div className="card stack">
      <h2>{resolved?.surface?.title || "Artifact surface"}</h2>
      <p className="muted">Renderer is declared but no compatible UI mapping exists in this build.</p>
      <pre className="code-block">{JSON.stringify(resolved, null, 2)}</pre>
    </div>
  );
}
