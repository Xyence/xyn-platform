import { describe, expect, it } from "vitest";
import type { ArtifactSurface } from "../../api/types";
import { canonicalLegacyRouteForPlatformSettings, resolvePromptSurfaceTarget } from "./promptSurfaceResolver";

function surface(input: Partial<ArtifactSurface> & Pick<ArtifactSurface, "id" | "artifact_id" | "key" | "title" | "surface_kind" | "route" | "nav_visibility">): ArtifactSurface {
  return {
    nav_label: input.title,
    nav_group: "admin",
    ...input,
  };
}

describe("resolvePromptSurfaceTarget", () => {
  it("prefers canonical global surface over workspace and legacy fallback routes", () => {
    const result = resolvePromptSurfaceTarget("open platform settings", {
      workspaceId: "ws-1",
      globalSurfaces: [
        surface({
          id: "global-artifact",
          artifact_id: "a1",
          key: "global-settings",
          title: "Platform Settings",
          surface_kind: "dashboard",
          route: "/app/platform/settings-legacy",
          nav_visibility: "always",
          ui_mount_scope: "global",
        }),
      ],
      workspaceSurfaces: [
        surface({
          id: "workspace-artifact",
          artifact_id: "a2",
          key: "workspace-settings",
          title: "Platform Settings",
          surface_kind: "dashboard",
          route: "/w/ws-1/platform/settings",
          nav_visibility: "always",
          ui_mount_scope: "workspace",
        }),
      ],
    });
    expect(result).toEqual({
      key: "platform_settings",
      route: "/app/platform/hub",
      scope: "global",
      source: "core_surface",
    });
  });

  it("does not resolve restricted global admin surfaces for unauthorized roles", () => {
    const result = resolvePromptSurfaceTarget("open access control", {
      user: { roles: ["app_user"], permissions: [] },
    });
    expect(result).toBeNull();
  });

  it("selects exact global artifact surface when prompt matches a surfaced label", () => {
    const result = resolvePromptSurfaceTarget("open tenant map", {
      globalSurfaces: [
        surface({
          id: "global-map",
          artifact_id: "a3",
          key: "tenant_map",
          title: "Tenant Map",
          surface_kind: "dashboard",
          route: "/app/a/tenant-map",
          nav_visibility: "always",
          ui_mount_scope: "global",
        }),
      ],
    });
    expect(result).toEqual({
      key: "tenant_map",
      route: "/app/a/tenant-map",
      scope: "global",
      source: "artifact_surface",
    });
  });

  it("falls back to workspace surfaced target when global surfaced target is absent", () => {
    const result = resolvePromptSurfaceTarget("open ops queue", {
      workspaceSurfaces: [
        surface({
          id: "workspace-ops",
          artifact_id: "a4",
          key: "ops_queue",
          title: "Ops Queue",
          surface_kind: "dashboard",
          route: "/w/ws-1/a/ops-queue",
          nav_visibility: "always",
          ui_mount_scope: "workspace",
        }),
      ],
    });
    expect(result).toEqual({
      key: "ops_queue",
      route: "/w/ws-1/a/ops-queue",
      scope: "workspace",
      source: "artifact_surface",
    });
  });

  it("resolves child global admin prompts to canonical child surfaces", () => {
    expect(
      resolvePromptSurfaceTarget("open oidc app clients", {
        user: { roles: ["platform_admin"] },
      })
    ).toEqual({
      key: "oidc_app_clients",
      route: "/app/platform/identity-configuration?tab=oidc-app-clients",
      scope: "global",
      source: "core_surface",
    });
    expect(
      resolvePromptSurfaceTarget("open ai agents", {
        user: { roles: ["platform_admin"] },
      })
    ).toEqual({
      key: "ai_agents",
      route: "/app/platform/ai-agents?tab=agents",
      scope: "global",
      source: "core_surface",
    });
  });
});

describe("canonicalLegacyRouteForPlatformSettings", () => {
  it("returns canonical platform settings hub route", () => {
    expect(canonicalLegacyRouteForPlatformSettings("ws-1")).toBe("/app/platform/hub");
  });
});
