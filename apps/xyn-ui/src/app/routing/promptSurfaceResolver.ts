import type { ArtifactSurface } from "../../api/types";

export type PromptSurfaceScope = "global" | "workspace";

export type PromptSurfaceTarget = {
  key: string;
  route: string;
  scope: PromptSurfaceScope;
  source: "core_surface" | "artifact_surface";
};

type CorePromptSurface = {
  key: string;
  label: string;
  scope: PromptSurfaceScope;
  routeFor: (workspaceId: string) => string;
  aliases: string[];
  requiredRoles?: string[];
  requiredPermissions?: string[];
};

const CORE_PROMPT_SURFACES: CorePromptSurface[] = [
  {
    key: "platform_settings",
    label: "Platform Settings",
    scope: "global",
    routeFor: (workspaceId: string) =>
      workspaceId ? `/w/${encodeURIComponent(workspaceId)}/workbench?panel=platform_settings` : "/app/platform/hub",
    aliases: [
      "platform settings",
      "open platform settings",
      "show platform settings",
      "go to platform settings",
      "configure platform",
      "open security settings",
      "open integrations settings",
    ],
  },
  {
    key: "access_control",
    label: "Access Control",
    scope: "global",
    routeFor: () => "/app/platform/access-control",
    aliases: ["open access control", "access control", "open users", "open roles", "open explorer"],
    requiredRoles: ["platform_owner", "platform_admin", "platform_architect", "platform_operator"],
  },
  {
    key: "users",
    label: "Users",
    scope: "global",
    routeFor: () => "/app/platform/access-control?tab=users",
    aliases: ["open platform users", "open users", "show users"],
    requiredRoles: ["platform_owner", "platform_admin", "platform_architect", "platform_operator"],
  },
  {
    key: "roles",
    label: "Roles",
    scope: "global",
    routeFor: () => "/app/platform/access-control?tab=roles",
    aliases: ["open platform roles", "open roles", "show roles"],
    requiredRoles: ["platform_owner", "platform_admin", "platform_architect", "platform_operator"],
  },
  {
    key: "access_explorer",
    label: "Explorer",
    scope: "global",
    routeFor: () => "/app/platform/access-control?tab=explorer",
    aliases: ["open access explorer", "open explorer", "show explorer"],
    requiredRoles: ["platform_owner", "platform_admin", "platform_architect", "platform_operator"],
  },
  {
    key: "identity_configuration",
    label: "Identity Configuration",
    scope: "global",
    routeFor: () => "/app/platform/identity-configuration",
    aliases: ["open identity configuration", "identity configuration", "open identity providers"],
    requiredRoles: ["platform_owner", "platform_admin", "platform_architect", "platform_operator"],
  },
  {
    key: "identity_providers",
    label: "Identity Providers",
    scope: "global",
    routeFor: () => "/app/platform/identity-configuration?tab=identity-providers",
    aliases: ["open identity providers", "show identity providers"],
    requiredRoles: ["platform_owner", "platform_admin", "platform_architect", "platform_operator"],
  },
  {
    key: "oidc_app_clients",
    label: "OIDC App Clients",
    scope: "global",
    routeFor: () => "/app/platform/identity-configuration?tab=oidc-app-clients",
    aliases: ["open oidc app clients", "oidc app clients", "open oidc clients"],
    requiredRoles: ["platform_owner", "platform_admin", "platform_architect", "platform_operator"],
  },
  {
    key: "secrets",
    label: "Secrets",
    scope: "global",
    routeFor: () => "/app/platform/secrets",
    aliases: ["open platform secrets", "open secrets", "platform secrets"],
    requiredRoles: ["platform_owner", "platform_admin", "platform_architect", "platform_operator"],
  },
  {
    key: "secret_stores",
    label: "Secret Stores",
    scope: "global",
    routeFor: () => "/app/platform/secrets?tab=stores",
    aliases: ["open secret stores", "secret stores"],
    requiredRoles: ["platform_owner", "platform_admin", "platform_architect", "platform_operator"],
  },
  {
    key: "secret_refs",
    label: "Secret Refs",
    scope: "global",
    routeFor: () => "/app/platform/secrets?tab=refs",
    aliases: ["open secret refs", "secret refs"],
    requiredRoles: ["platform_owner", "platform_admin", "platform_architect", "platform_operator"],
  },
  {
    key: "ai_agents",
    label: "AI Agents",
    scope: "global",
    routeFor: () => "/app/platform/ai-agents?tab=agents",
    aliases: ["open ai agents", "open agents", "ai agents"],
    requiredRoles: ["platform_owner", "platform_admin", "platform_architect", "platform_operator"],
  },
  {
    key: "ai_credentials",
    label: "AI Credentials",
    scope: "global",
    routeFor: () => "/app/platform/ai-agents?tab=credentials",
    aliases: ["open ai credentials", "ai credentials", "open credentials"],
    requiredRoles: ["platform_owner", "platform_admin", "platform_architect", "platform_operator"],
  },
  {
    key: "ai_model_configs",
    label: "AI Model Configs",
    scope: "global",
    routeFor: () => "/app/platform/ai-agents?tab=model-configs",
    aliases: ["open ai model configs", "open model configs", "model configs"],
    requiredRoles: ["platform_owner", "platform_admin", "platform_architect", "platform_operator"],
  },
  {
    key: "ai_purposes",
    label: "AI Purposes",
    scope: "global",
    routeFor: () => "/app/platform/ai-agents?tab=purposes",
    aliases: ["open ai purposes", "ai purposes", "open purposes"],
    requiredRoles: ["platform_owner", "platform_admin", "platform_architect", "platform_operator"],
  },
  {
    key: "rendering_settings",
    label: "Rendering Settings",
    scope: "global",
    routeFor: () => "/app/platform/rendering-settings",
    aliases: ["open rendering settings", "rendering settings", "open video adapter configs", "video adapter configs"],
    requiredRoles: ["platform_owner", "platform_admin", "platform_architect", "platform_operator"],
  },
  {
    key: "platform_activity",
    label: "Platform Activity",
    scope: "global",
    routeFor: () => "/app/platform/activity",
    aliases: ["open platform activity", "platform activity", "open activity"],
    requiredRoles: ["platform_owner", "platform_admin", "platform_architect", "platform_operator"],
  },
  {
    key: "deploy_settings",
    label: "Deploy Settings",
    scope: "global",
    routeFor: () => "/app/platform/deploy",
    aliases: ["open deploy settings", "deploy settings", "open platform deploy"],
    requiredRoles: ["platform_owner", "platform_admin", "platform_architect", "platform_operator"],
  },
  {
    key: "workspace_governance",
    label: "Workspaces",
    scope: "global",
    routeFor: () => "/app/platform/workspaces",
    aliases: ["open workspaces", "workspace governance", "open workspace governance"],
    requiredRoles: ["platform_owner", "platform_admin", "platform_architect", "platform_operator"],
  },
];

function normalizePrompt(value: string): string {
  return String(value || "").trim().toLowerCase().replace(/\s+/g, " ");
}

function normalizeRoutePath(route: string): string {
  const trimmed = String(route || "").trim();
  if (!trimmed) return "";
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
}

function isGlobalSurface(surface: ArtifactSurface): boolean {
  return String(surface.ui_mount_scope || "").trim().toLowerCase() === "global";
}

function isWorkspaceSurface(surface: ArtifactSurface): boolean {
  const scope = String(surface.ui_mount_scope || "").trim().toLowerCase();
  if (!scope) return true;
  return scope === "workspace";
}

function candidatePhrasesForSurfaceLabel(label: string): string[] {
  const normalized = normalizePrompt(label);
  if (!normalized) return [];
  return [normalized, `open ${normalized}`, `show ${normalized}`, `go to ${normalized}`];
}

function matchSurfaceByPrompt(prompt: string, surfaces: ArtifactSurface[]): ArtifactSurface | null {
  const normalizedPrompt = normalizePrompt(prompt);
  if (!normalizedPrompt) return null;
  const exactLabelMatch = surfaces.find((surface) => {
    const label = String(surface.nav_label || surface.title || "").trim();
    return candidatePhrasesForSurfaceLabel(label).includes(normalizedPrompt);
  });
  if (exactLabelMatch) return exactLabelMatch;
  return null;
}

function hasSurfaceAccess(
  surface: CorePromptSurface,
  user: {
    roles?: string[];
    permissions?: string[];
  }
): boolean {
  const roles = new Set((user.roles || []).map((entry) => String(entry || "").trim().toLowerCase()).filter(Boolean));
  const permissions = new Set((user.permissions || []).map((entry) => String(entry || "").trim().toLowerCase()).filter(Boolean));
  if (!surface.requiredRoles?.length && !surface.requiredPermissions?.length) return true;
  if (roles.has("platform_owner") || roles.has("platform_admin")) return true;
  if (surface.requiredRoles?.some((entry) => roles.has(String(entry || "").trim().toLowerCase()))) return true;
  if (surface.requiredPermissions?.some((entry) => permissions.has(String(entry || "").trim().toLowerCase()))) return true;
  return false;
}

export function resolvePromptSurfaceTarget(
  prompt: string,
  options: {
    globalSurfaces?: ArtifactSurface[];
    workspaceSurfaces?: ArtifactSurface[];
    workspaceId?: string;
    user?: {
      roles?: string[];
      permissions?: string[];
    };
  }
): PromptSurfaceTarget | null {
  const normalizedPrompt = normalizePrompt(prompt);
  if (!normalizedPrompt) return null;
  const workspaceId = String(options.workspaceId || "").trim();

  const coreGlobal = CORE_PROMPT_SURFACES.find(
    (surface) =>
      surface.scope === "global" &&
      hasSurfaceAccess(surface, options.user || {}) &&
      surface.aliases.some((alias) => normalizePrompt(alias) === normalizedPrompt)
  );
  if (coreGlobal) {
    return {
      key: coreGlobal.key,
      route: coreGlobal.routeFor(workspaceId),
      scope: "global",
      source: "core_surface",
    };
  }

  const globalSurfaces = (options.globalSurfaces || []).filter((surface) => isGlobalSurface(surface));
  const globalMatch = matchSurfaceByPrompt(prompt, globalSurfaces);
  if (globalMatch) {
    return {
      key: String(globalMatch.key || "surface"),
      route: normalizeRoutePath(String(globalMatch.route || "")),
      scope: "global",
      source: "artifact_surface",
    };
  }

  const workspaceSurfaces = (options.workspaceSurfaces || []).filter((surface) => isWorkspaceSurface(surface));
  const workspaceMatch = matchSurfaceByPrompt(prompt, workspaceSurfaces);
  if (workspaceMatch) {
    return {
      key: String(workspaceMatch.key || "surface"),
      route: normalizeRoutePath(String(workspaceMatch.route || "")),
      scope: "workspace",
      source: "artifact_surface",
    };
  }

  return null;
}

export function canonicalLegacyRouteForPlatformSettings(workspaceId: string): string | null {
  const surface = CORE_PROMPT_SURFACES.find((entry) => entry.key === "platform_settings");
  if (!surface) return null;
  return surface.routeFor(String(workspaceId || "").trim());
}
