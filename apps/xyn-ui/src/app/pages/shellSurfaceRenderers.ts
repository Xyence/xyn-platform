import type { ArtifactSurfaceResolveResponse } from "../../api/types";

export type ShellRendererResolution =
  | { kind: "articles_index" }
  | { kind: "workflows_index" }
  | { kind: "artifact_detail" }
  | {
      kind: "registered_shell_renderer";
      rendererKey: string;
      rendererConfig: Record<string, unknown>;
      params: Record<string, string>;
    }
  | { kind: "unknown_shell_renderer"; rendererKey: string };

const REGISTERED_SHELL_RENDERERS = new Set<string>(["campaign_map_workflow"]);

type SurfaceLike = {
  renderer?: Record<string, unknown> | null;
};

function surfaceRendererMeta(surface: SurfaceLike): {
  rendererType: string;
  shellRendererKey: string;
  componentKey: string;
} {
  const renderer = (surface.renderer || {}) as Record<string, unknown>;
  const rendererType = String(renderer.type || "").trim().toLowerCase();
  const rendererPayload = (renderer.payload || {}) as Record<string, unknown>;
  const shellRendererKey = String(rendererPayload.shell_renderer_key || "").trim().toLowerCase();
  const componentKey = String(rendererPayload.component_key || "").trim().toLowerCase();
  return { rendererType, shellRendererKey, componentKey };
}

export function isCompatibilityFallbackSurface(surface: SurfaceLike): boolean {
  const { rendererType, shellRendererKey, componentKey } = surfaceRendererMeta(surface);
  if (!rendererType) return false;
  if (shellRendererKey) return !REGISTERED_SHELL_RENDERERS.has(shellRendererKey);
  if (rendererType === "ui_component_ref") {
    return !["articles.index", "workflows.index", "articles.draft_editor", "workflows.editor", "workflows.visualizer"].includes(componentKey);
  }
  if (rendererType === "article_editor" || rendererType === "workflow_visualizer") return false;
  return rendererType === "generic_dashboard" || rendererType === "generic_editor";
}

export function resolveShellSurfaceRenderer(payload: ArtifactSurfaceResolveResponse): ShellRendererResolution | null {
  const surface = payload.surface || ({} as ArtifactSurfaceResolveResponse["surface"]);
  const renderer = (surface.renderer || {}) as Record<string, unknown>;
  const rendererPayload = (renderer.payload || {}) as Record<string, unknown>;
  const { rendererType, shellRendererKey, componentKey } = surfaceRendererMeta(surface);
  if (shellRendererKey) {
    if (!REGISTERED_SHELL_RENDERERS.has(shellRendererKey)) {
      return { kind: "unknown_shell_renderer", rendererKey: shellRendererKey };
    }
    return {
      kind: "registered_shell_renderer",
      rendererKey: shellRendererKey,
      rendererConfig: rendererPayload,
      params: (payload.params || {}) as Record<string, string>,
    };
  }

  if (rendererType === "ui_component_ref") {
    if (componentKey === "articles.index") return { kind: "articles_index" };
    if (componentKey === "workflows.index") return { kind: "workflows_index" };
    if (componentKey === "articles.draft_editor") return { kind: "artifact_detail" };
    if (componentKey === "workflows.editor" || componentKey === "workflows.visualizer") return { kind: "artifact_detail" };
  }

  if (rendererType === "article_editor" || rendererType === "workflow_visualizer") return { kind: "artifact_detail" };
  return null;
}
