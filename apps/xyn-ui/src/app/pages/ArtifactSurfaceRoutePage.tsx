import { useEffect, useMemo, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { resolveArtifactSurface } from "../../api/xyn";
import type { ArtifactSurfaceResolveResponse } from "../../api/types";
import ArtifactsArticlesPage from "./ArtifactsArticlesPage";
import ArtifactsWorkflowsPage from "./ArtifactsWorkflowsPage";
import ArtifactDetailPage from "./ArtifactDetailPage";
import CampaignMapWorkflowPage from "./CampaignMapWorkflowPage";
import { isCompatibilityFallbackSurface, resolveShellSurfaceRenderer } from "./shellSurfaceRenderers";
import { toWorkspacePath } from "../routing/workspaceRouting";

export function toSurfaceResolvePath(pathname: string): string {
  const raw = String(pathname || "").trim();
  if (!raw) return "/";
  const workspaceScoped = raw.match(/^\/w\/[^/]+\/a(\/.*)?$/);
  if (workspaceScoped) {
    const rest = String(workspaceScoped[1] || "").trim();
    if (!rest) return "/app";
    return `/app${rest}`;
  }
  return raw;
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

  const requestPath = useMemo(() => toSurfaceResolvePath(location.pathname), [location.pathname]);

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

  const target = resolved ? resolveShellSurfaceRenderer(resolved) : null;
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
  if (target?.kind === "registered_shell_renderer") {
    if (target.rendererKey === "campaign_map_workflow") {
      const campaignParam = String(target.rendererConfig.campaign_id_param || "id").trim() || "id";
      const campaignId = String(target.params?.[campaignParam] || "").trim() || undefined;
      return <CampaignMapWorkflowPage workspaceId={workspaceId} campaignId={campaignId} />;
    }
  }
  if (target?.kind === "unknown_shell_renderer") {
    return (
      <div className="card stack">
        <h2>{resolved?.surface?.title || "Artifact surface"}</h2>
        <p className="danger">
          Unknown shell renderer key: <code>{target.rendererKey}</code>
        </p>
      </div>
    );
  }

  const resolvedSurfaceRoute = toSurfaceResolvePath(String(resolved?.surface?.route || requestPath));
  if (resolved && isCompatibilityFallbackSurface(resolved.surface || {})) {
    if (resolvedSurfaceRoute === "/app/campaigns") {
      return <Navigate to={toWorkspacePath(workspaceId, "workbench?panel=campaign_list")} replace />;
    }
    if (resolvedSurfaceRoute === "/app/campaigns/new") {
      return <Navigate to={toWorkspacePath(workspaceId, "workbench?panel=campaign_list&create=1")} replace />;
    }
    return (
      <div className="card stack">
        <h2>{resolved?.surface?.title || "Surface unavailable"}</h2>
        <p className="muted">
          This artifact surface is not supported in the current workbench UI.
        </p>
        <p className="small muted">
          Route: <code>{resolvedSurfaceRoute}</code>
        </p>
      </div>
    );
  }

  return (
    <div className="card stack">
      <h2>{resolved?.surface?.title || "Artifact surface"}</h2>
      <p className="muted">Surface renderer is not supported in this build.</p>
    </div>
  );
}
