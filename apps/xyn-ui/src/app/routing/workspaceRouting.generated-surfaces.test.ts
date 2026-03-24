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

  it("maps legacy solutions URLs into workbench panel deep links", () => {
    expect(toWorkspaceScopedPath("/app/solutions", "ws-1")).toBe("/w/ws-1/workbench?panel=solution_list");
    expect(toWorkspaceScopedPath("/app/solutions/app-1", "ws-1")).toBe("/w/ws-1/workbench?panel=solution_detail&application_id=app-1");
    expect(withWorkspaceInNavPath("/app/solutions", "ws-1")).toBe("/w/ws-1/workbench?panel=solution_list");
  });

  it("preserves workbench query params for panel-native deep links", () => {
    expect(toWorkspaceScopedPath("/app/workbench?panel=solution_list", "ws-1")).toBe("/w/ws-1/workbench?panel=solution_list");
    expect(toWorkspaceScopedPath("/app/workbench?panel=solution_detail&application_id=app-1", "ws-1")).toBe(
      "/w/ws-1/workbench?panel=solution_detail&application_id=app-1"
    );
    expect(withWorkspaceInNavPath("/app/workbench?panel=solution_list", "ws-1")).toBe("/w/ws-1/workbench?panel=solution_list");
  });
});
