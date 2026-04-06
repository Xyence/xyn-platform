import { describe, expect, it } from "vitest";
import { shouldReopenComposerForRouteParams, shouldReuseExistingLayoutOnWorkspaceSwitch } from "./WorkbenchPage";

describe("shouldReuseExistingLayoutOnWorkspaceSwitch", () => {
  it("preserves active layout when switching between workspaces with open panels", () => {
    expect(
      shouldReuseExistingLayoutOnWorkspaceSwitch({
        previousWorkspaceId: "ws-1",
        nextWorkspaceId: "ws-2",
        panelCount: 3,
      })
    ).toBe(true);
  });

  it("does not preserve when there are no open panels", () => {
    expect(
      shouldReuseExistingLayoutOnWorkspaceSwitch({
        previousWorkspaceId: "ws-1",
        nextWorkspaceId: "ws-2",
        panelCount: 0,
      })
    ).toBe(false);
  });

  it("does not preserve when workspace did not change", () => {
    expect(
      shouldReuseExistingLayoutOnWorkspaceSwitch({
        previousWorkspaceId: "ws-1",
        nextWorkspaceId: "ws-1",
        panelCount: 2,
      })
    ).toBe(false);
  });
});

describe("shouldReopenComposerForRouteParams", () => {
  it("reopens when composer panel is not active", () => {
    expect(
      shouldReopenComposerForRouteParams({
        activePanel: null,
        routeParams: { application_id: "app-1", solution_change_session_id: "scs-1" },
      })
    ).toBe(true);
  });

  it("reopens when route session differs from active composer session", () => {
    expect(
      shouldReopenComposerForRouteParams({
        activePanel: {
          key: "composer_detail",
          params: { application_id: "app-1", solution_change_session_id: "scs-old" },
        },
        routeParams: { application_id: "app-1", solution_change_session_id: "scs-1" },
      })
    ).toBe(true);
  });

  it("does not reopen when active composer already matches route params", () => {
    expect(
      shouldReopenComposerForRouteParams({
        activePanel: {
          key: "composer_detail",
          params: { application_id: "app-1", solution_change_session_id: "scs-1" },
        },
        routeParams: { application_id: "app-1", solution_change_session_id: "scs-1" },
      })
    ).toBe(false);
  });
});
