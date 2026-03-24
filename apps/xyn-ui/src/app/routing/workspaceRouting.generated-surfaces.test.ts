import { describe, expect, it } from "vitest";

import { toWorkspaceScopedPath, withWorkspaceInNavPath } from "./workspaceRouting";

describe("workspace routing for generated app surfaces", () => {
  it("maps unknown /app paths into artifact surface routes", () => {
    expect(toWorkspaceScopedPath("/app/campaigns", "ws-1")).toBe("/w/ws-1/a/campaigns");
    expect(toWorkspaceScopedPath("/app/campaigns/new", "ws-1")).toBe("/w/ws-1/a/campaigns/new");
  });

  it("preserves canonical workspace workbench mapping for /app root", () => {
    expect(toWorkspaceScopedPath("/app", "ws-1")).toBe("/w/ws-1/workbench");
    expect(withWorkspaceInNavPath("/app", "ws-1")).toBe("/w/ws-1/workbench");
  });

  it("rewrites nav links for generated app routes into workspace artifact routes", () => {
    expect(withWorkspaceInNavPath("/app/signals", "ws-1")).toBe("/w/ws-1/a/signals");
    expect(withWorkspaceInNavPath("/app/sources", "ws-1")).toBe("/w/ws-1/a/sources");
  });

  it("keeps solution pages as shell-native workspace routes", () => {
    expect(toWorkspaceScopedPath("/app/solutions", "ws-1")).toBe("/w/ws-1/solutions");
    expect(toWorkspaceScopedPath("/app/solutions/app-1", "ws-1")).toBe("/w/ws-1/solutions/app-1");
    expect(withWorkspaceInNavPath("/app/solutions", "ws-1")).toBe("/w/ws-1/solutions");
  });
});
