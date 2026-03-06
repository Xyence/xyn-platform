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
};

const CORE_PROMPT_SURFACES: CorePromptSurface[] = [
  {
    key: "platform_settings",
    label: "Platform Settings",
    scope: "global",
    routeFor: (workspaceId: string) => {
      const base = workspaceId ? `/w/${encodeURIComponent(workspaceId)}/workbench` : "/app/workbench";
      return `${base}?panel=platform_settings`;
    },
    aliases: [
      "platform settings",
      "open platform settings",
      "show platform settings",
      "go to platform settings",
    ],
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

export function resolvePromptSurfaceTarget(
  prompt: string,
  options: {
    globalSurfaces?: ArtifactSurface[];
    workspaceSurfaces?: ArtifactSurface[];
    workspaceId?: string;
  }
): PromptSurfaceTarget | null {
  const normalizedPrompt = normalizePrompt(prompt);
  if (!normalizedPrompt) return null;
  const workspaceId = String(options.workspaceId || "").trim();

  const coreGlobal = CORE_PROMPT_SURFACES.find(
    (surface) => surface.scope === "global" && surface.aliases.some((alias) => normalizePrompt(alias) === normalizedPrompt)
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

