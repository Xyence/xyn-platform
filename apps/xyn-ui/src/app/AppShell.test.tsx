import { describe, expect, it } from "vitest";

import type { ArtifactSurface } from "../api/types";
import { NAV_GROUPS, type NavUserContext } from "./nav/nav.config";
import { visibleNav } from "./nav/nav.utils";
import { withArtifactSurfaceNav } from "./nav/artifactSurfaceNav";

function surface(input: Partial<ArtifactSurface> & Pick<ArtifactSurface, "id" | "artifact_id" | "key" | "title" | "surface_kind" | "route" | "nav_visibility">): ArtifactSurface {
  return {
    nav_label: input.title,
    ...input,
  };
}

function appItemsFor(
  user: NavUserContext,
  surfaces: ArtifactSurface[],
  workspaceId = "ws-1",
): Array<{ label: string; path: string }> {
  const hydrated = withArtifactSurfaceNav(NAV_GROUPS, surfaces, workspaceId);
  const allowed = visibleNav(hydrated, user);
  const apps = allowed.find((group) => group.id === "apps");
  return (apps?.items || []).map((item) => ({ label: item.label, path: item.path }));
}

describe("AppShell metadata-driven nav composition", () => {
  it("renders Campaigns and Create Campaign affordances from surfaced metadata", () => {
    const items = appItemsFor(
      { roles: ["app_user"], permissions: [] },
      [
        surface({
          id: "campaigns-list",
          artifact_id: "artifact-deal-finder",
          key: "entity-campaigns-list",
          title: "Campaigns",
          surface_kind: "dashboard",
          route: "/app/campaigns",
          nav_visibility: "always",
          ui_mount_scope: "workspace",
          sort_order: 100,
        }),
        surface({
          id: "campaigns-create",
          artifact_id: "artifact-deal-finder",
          key: "entity-campaigns-create",
          title: "Create Campaign",
          surface_kind: "editor",
          route: "/app/campaigns/new",
          nav_visibility: "always",
          ui_mount_scope: "workspace",
          sort_order: 101,
        }),
      ],
      "ws-1",
    );

    expect(items).toEqual([
      { label: "Campaigns", path: "/w/ws-1/a/campaigns" },
      { label: "Create Campaign", path: "/w/ws-1/a/campaigns/new" },
    ]);
  });

  it("hides surfaced affordances when required roles are not granted", () => {
    const items = appItemsFor(
      { roles: ["app_user"], permissions: [] },
      [
        surface({
          id: "campaigns-list",
          artifact_id: "artifact-deal-finder",
          key: "entity-campaigns-list",
          title: "Campaigns",
          surface_kind: "dashboard",
          route: "/app/campaigns",
          nav_visibility: "always",
          ui_mount_scope: "workspace",
          permissions: { required_roles: ["app_admin"] },
        }),
      ],
      "ws-1",
    );

    expect(items).toEqual([]);
  });

  it("filters compatibility fallback surfaces from app nav", () => {
    const items = appItemsFor(
      { roles: ["app_user"], permissions: [] },
      [
        surface({
          id: "legacy-campaigns",
          artifact_id: "artifact-deal-finder",
          key: "legacy-campaigns",
          title: "Campaigns",
          surface_kind: "dashboard",
          route: "/app/campaigns",
          nav_visibility: "always",
          ui_mount_scope: "workspace",
          renderer: { type: "generic_dashboard" },
          sort_order: 100,
        }),
        surface({
          id: "modern-campaign-create",
          artifact_id: "artifact-deal-finder",
          key: "modern-campaign-create",
          title: "Create Campaign",
          surface_kind: "editor",
          route: "/app/campaigns/new",
          nav_visibility: "always",
          ui_mount_scope: "workspace",
          renderer: { type: "generic_editor", payload: { shell_renderer_key: "campaign_map_workflow" } },
          sort_order: 101,
        }),
      ],
      "ws-1",
    );

    expect(items).toEqual([{ label: "Create Campaign", path: "/w/ws-1/a/campaigns/new" }]);
  });

});
