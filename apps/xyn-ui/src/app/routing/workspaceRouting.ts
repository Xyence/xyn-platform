export const DEFAULT_WORKSPACE_SUBPATH = "workbench";

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
  if (!normalized || normalized === "home" || normalized === "workbench" || normalized === "console" || normalized === "initiate") {
    return DEFAULT_WORKSPACE_SUBPATH;
  }

  if (normalized === "catalog") return "build/catalog";
  if (normalized === "artifacts") return "build/artifacts";
  if (normalized === "artifacts/all") return "build/artifacts";
  if (normalized === "artifacts/library" || normalized === "build/artifacts/library") return "build/catalog";
  if (normalized.startsWith("artifacts/")) {
    const suffix = normalized.replace(/^artifacts\//, "");
    if (suffix === "library") return "build/catalog";
    if (suffix === "all") return "build/artifacts";
    return `build/artifacts/${suffix}`;
  }

  if (normalized.startsWith("build/") || normalized.startsWith("run/") || normalized.startsWith("package/") || normalized.startsWith("govern/") || normalized.startsWith("platform/") || normalized.startsWith("settings") || normalized.startsWith("apps/") || normalized.startsWith("a/")) {
    return normalized;
  }

  return DEFAULT_WORKSPACE_SUBPATH;
}

export function toWorkspaceScopedPath(pathname: string, workspaceId: string): string | null {
  const normalized = String(pathname || "").trim() || "/";
  if (!workspaceId) return null;

  if (isWorkspaceScopedPath(normalized)) return normalized;
  if (normalized === "/" || normalized === "/workspaces") return toWorkspacePath(workspaceId, DEFAULT_WORKSPACE_SUBPATH);

  if (normalized === "/app" || normalized === "/app/" || normalized.startsWith("/app/")) {
    return toWorkspacePath(workspaceId, DEFAULT_WORKSPACE_SUBPATH);
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
