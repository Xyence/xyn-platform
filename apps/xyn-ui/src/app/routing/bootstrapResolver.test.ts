import { describe, expect, it } from "vitest";
import { requiresPlatformInitialization, resolveDefaultWorkspaceForUser, resolvePostLoginDestination } from "./bootstrapResolver";

describe("bootstrapResolver", () => {
  const sample = {
    workspaces: [
      { id: "ws-1", slug: "development", name: "Development", role: "admin" },
      { id: "ws-2", slug: "customer", name: "Customer", role: "admin" },
    ],
    preferred_workspace_id: "ws-2",
  };

  it("prefers persisted workspace when valid", () => {
    expect(resolveDefaultWorkspaceForUser(sample, "ws-1")).toBe("ws-1");
  });

  it("falls back to server preferred workspace when persisted is stale", () => {
    expect(resolveDefaultWorkspaceForUser(sample, "ws-stale")).toBe("ws-2");
  });

  it("routes to setup when platform requires initialization", () => {
    const me = {
      workspaces: [],
      platform_initialization: {
        initialized: false,
        requires_setup: true,
        workspace_count: 0,
        auth_mode: "oidc",
      },
    };
    expect(requiresPlatformInitialization(me)).toBe(true);
    expect(resolvePostLoginDestination(me, "")).toBe("/app/setup/initialize");
  });

  it("routes to workspace workbench when available", () => {
    expect(resolvePostLoginDestination(sample, "ws-1")).toBe("/w/ws-1/workbench");
  });

  it("routes to global hub when no workspace exists", () => {
    expect(resolvePostLoginDestination({ workspaces: [] }, "")).toBe("/app/platform/hub");
  });
});

