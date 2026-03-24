export const DEFAULT_WORKSPACE_SUBPATH = "workbench";

const GLOBAL_APP_PATH_PREFIXES = [
  "/app/platform/hub",
  "/app/platform/settings",
  "/app/platform/activity",
  "/app/platform/deploy",
  "/app/platform/workspaces",
  "/app/platform/rendering-settings",
  "/app/platform/access-control",
  "/app/platform/identity-configuration",
  "/app/platform/secrets",
  "/app/platform/ai-agents",
  "/app/platform/branding",
  "/app/platform/seeds",
  "/app/platform/video-adapter-configs",
  "/app/setup/initialize",
];

export function isGlobalAppPath(pathname: string): boolean {
  const normalized = String(pathname || "").trim();
  return GLOBAL_APP_PATH_PREFIXES.some((prefix) => normalized === prefix || normalized.startsWith(`${prefix}/`));
}

export function toWorkspacePath(workspaceId: string, subpath: string): string {
  const token = String(workspaceId || "").trim();
  const rest = String(subpath || "").replace(/^\/+/, "");
  if (!token) return `/${rest}`;
  if (!rest) return `/w/${encodeURIComponent(token)}`;
  return `/w/${encodeURIComponent(token)}/${rest}`;
}

export function isWorkspaceScopedPath(pathname: string): boolean {
  return /^\/w\/[^/]+(?:\/|$)/.test(pathname);
}

export function swapWorkspaceInPath(pathname: string, workspaceId: string): string {
  const target = encodeURIComponent(String(workspaceId || "").trim());
  if (!target) return pathname;
  if (!isWorkspaceScopedPath(pathname)) return pathname;
  return pathname.replace(/^\/w\/[^/]+/, `/w/${target}`);
}

function mapLegacyAppRestToWorkspaceSubpath(rest: string): string {
  const normalized = String(rest || "").replace(/^\/+/, "");
  const [basePartRaw, queryPartRaw] = normalized.split("?", 2);
  const basePart = String(basePartRaw || "").trim();
  const queryPart = String(queryPartRaw || "").trim();
  const withQuery = (path: string): string => {
    if (!queryPart) return path;
    return path.includes("?") ? `${path}&${queryPart}` : `${path}?${queryPart}`;
  };
  if (!basePart || basePart === "home" || basePart === "workbench" || basePart === "console" || basePart === "initiate") {
    return withQuery(DEFAULT_WORKSPACE_SUBPATH);
  }

  if (basePart === "catalog") return withQuery("build/catalog");
  if (basePart === "artifacts") return withQuery("build/artifacts");
  if (basePart === "artifacts/all") return withQuery("build/artifacts");
  // Guardrail: route-like solution URLs should resolve to workbench panel state.
  // Keep /w/:workspaceId/solutions compatibility routes as thin redirect shims only.
  if (basePart === "solutions") return withQuery("workbench?panel=solution_list");
  if (basePart.startsWith("solutions/")) {
    const applicationId = String(basePart.replace(/^solutions\//, "") || "").trim();
    if (!applicationId) return withQuery("workbench?panel=solution_list");
    return withQuery(`workbench?panel=solution_detail&application_id=${encodeURIComponent(applicationId)}`);
  }
  if (basePart === "artifacts/library" || basePart === "build/artifacts/library") return withQuery("build/catalog");
  if (basePart.startsWith("artifacts/")) {
    const suffix = basePart.replace(/^artifacts\//, "");
    if (suffix === "library") return withQuery("build/catalog");
    if (suffix === "all") return withQuery("build/artifacts");
    return withQuery(`build/artifacts/${suffix}`);
  }

  if (
    basePart.startsWith("build/")
    || basePart.startsWith("run/")
    || basePart.startsWith("package/")
    || basePart.startsWith("govern/")
    || basePart.startsWith("platform/")
    || basePart.startsWith("settings")
    || basePart.startsWith("apps/")
    || basePart.startsWith("a/")
  ) {
    return withQuery(basePart);
  }

  return withQuery(`a/${basePart}`);
}

export function toWorkspaceScopedPath(pathname: string, workspaceId: string): string | null {
  const normalized = String(pathname || "").trim() || "/";
  if (!workspaceId) return null;
  if (isGlobalAppPath(normalized)) return null;

  if (isWorkspaceScopedPath(normalized)) return normalized;
  if (normalized === "/" || normalized === "/workspaces") return toWorkspacePath(workspaceId, DEFAULT_WORKSPACE_SUBPATH);

  if (normalized === "/app" || normalized === "/app/" || normalized.startsWith("/app/")) {
    const rest = normalized.replace(/^\/app\/?/, "");
    return toWorkspacePath(workspaceId, mapLegacyAppRestToWorkspaceSubpath(rest));
  }

  return null;
}

export function withWorkspaceInNavPath(path: string, workspaceId: string): string {
  const normalized = String(path || "").trim();
  if (!workspaceId) return normalized;
  if (normalized.startsWith("/w/")) return normalized;
  if (normalized === "/" || normalized === "/app" || normalized === "/app/") {
    return toWorkspacePath(workspaceId, DEFAULT_WORKSPACE_SUBPATH);
  }
  if (normalized.startsWith("/app/")) {
    const rest = normalized.replace(/^\/app\//, "");
    return toWorkspacePath(workspaceId, mapLegacyAppRestToWorkspaceSubpath(rest));
  }
  return normalized;
}
