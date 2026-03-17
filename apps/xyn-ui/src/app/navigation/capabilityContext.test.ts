import { describe, expect, it } from "vitest";

import { resolveCapabilityGraphContext } from "./capabilityContext";

describe("resolveCapabilityGraphContext", () => {
  it("resolves app intent draft routes", () => {
    expect(resolveCapabilityGraphContext({ pathname: "/w/ws-1/drafts/draft-1" })).toBe("app_intent_draft");
  });

  it("resolves artifact detail routes", () => {
    expect(resolveCapabilityGraphContext({ pathname: "/w/ws-1/build/artifacts/art-1" })).toBe("artifact_detail");
  });

  it("resolves artifact registry routes", () => {
    expect(resolveCapabilityGraphContext({ pathname: "/w/ws-1/build/artifacts" })).toBe("artifact_registry");
  });

  it("resolves plan review from composer panel search state", () => {
    expect(
      resolveCapabilityGraphContext({
        pathname: "/w/ws-1/workbench",
        search: "?application_plan_id=plan-1",
        panelKey: "composer_detail",
      }),
    ).toBe("plan_review");
  });
});
