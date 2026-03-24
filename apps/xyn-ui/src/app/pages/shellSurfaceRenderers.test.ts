import { describe, expect, it } from "vitest";

import { resolveShellSurfaceRenderer } from "./shellSurfaceRenderers";

describe("resolveShellSurfaceRenderer", () => {
  it("resolves registered shell renderer keys from surface metadata", () => {
    const target = resolveShellSurfaceRenderer({
      surface: {
        id: "surface-campaign-create",
        route: "/app/campaigns/new",
        title: "Create Campaign",
        renderer: { type: "generic_editor", payload: { shell_renderer_key: "campaign_map_workflow", mode: "create" } },
      },
      artifact: { id: "artifact-1", slug: "app.deal-finder" },
      params: {},
    } as any);
    expect(target?.kind).toBe("registered_shell_renderer");
    expect((target as any).rendererKey).toBe("campaign_map_workflow");
  });

  it("keeps generic generated surfaces as unresolved when no shell renderer key is declared", () => {
    const target = resolveShellSurfaceRenderer({
      surface: {
        id: "surface-signals",
        route: "/app/signals",
        title: "Signals",
        renderer: { type: "generic_dashboard" },
      },
      artifact: { id: "artifact-1", slug: "app.deal-finder" },
      params: {},
    } as any);
    expect(target).toBeNull();
  });

  it("returns controlled unknown-shell-renderer target for invalid keys", () => {
    const target = resolveShellSurfaceRenderer({
      surface: {
        id: "surface-unknown",
        route: "/app/campaigns/new",
        title: "Create Campaign",
        renderer: { type: "generic_editor", payload: { shell_renderer_key: "unsupported_key" } },
      },
      artifact: { id: "artifact-1", slug: "app.deal-finder" },
      params: {},
    } as any);
    expect(target?.kind).toBe("unknown_shell_renderer");
    expect((target as any).rendererKey).toBe("unsupported_key");
  });
});

