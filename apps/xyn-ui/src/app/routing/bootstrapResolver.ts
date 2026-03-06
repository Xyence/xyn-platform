import { DEFAULT_WORKSPACE_SUBPATH, toWorkspacePath } from "./workspaceRouting";

export type MeBootstrapPayload = {
  auth_mode?: "dev" | "token" | "oidc" | string;
  workspaces?: Array<{ id: string; slug: string; name: string; role: string }>;
  preferred_workspace_id?: string;
  platform_initialization?: {
    initialized: boolean;
    requires_setup: boolean;
    workspace_count: number;
    auth_mode: string;
  };
};

export function requiresPlatformInitialization(me: MeBootstrapPayload | null | undefined): boolean {
  return Boolean(me?.platform_initialization?.requires_setup);
}

export function resolveDefaultWorkspaceForUser(
  me: MeBootstrapPayload | null | undefined,
  persistedWorkspaceId: string
): string {
  const workspaces = Array.isArray(me?.workspaces) ? me!.workspaces : [];
  const ids = new Set(workspaces.map((workspace) => String(workspace.id || "").trim()).filter(Boolean));
  const persisted = String(persistedWorkspaceId || "").trim();
  if (persisted && ids.has(persisted)) return persisted;
  const preferred = String(me?.preferred_workspace_id || "").trim();
  if (preferred && ids.has(preferred)) return preferred;
  return String(workspaces[0]?.id || "").trim();
}

export function resolvePostLoginDestination(
  me: MeBootstrapPayload | null | undefined,
  persistedWorkspaceId: string
): string {
  if (requiresPlatformInitialization(me)) return "/app/setup/initialize";
  const workspaceId = resolveDefaultWorkspaceForUser(me, persistedWorkspaceId);
  if (workspaceId) return toWorkspacePath(workspaceId, DEFAULT_WORKSPACE_SUBPATH);
  return "/app/platform/hub";
}

