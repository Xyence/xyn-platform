import { describe, expect, it } from "vitest";
import { shouldReuseExistingLayoutOnWorkspaceSwitch } from "./WorkbenchPage";

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

