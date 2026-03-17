import { describe, expect, it } from "vitest";

import { getAppDraftViewDescriptor } from "./appDraftView";

describe("getAppDraftViewDescriptor", () => {
  it("returns the application draft route and editor key", () => {
    const descriptor = getAppDraftViewDescriptor(
      {
        id: "draft-123",
        title: "Team Lunch Poll",
      },
      "ws-1",
    );

    expect(descriptor.kind).toBe("app_intent_draft");
    expect(descriptor.entityId).toBe("draft-123");
    expect(descriptor.route).toBe("/w/ws-1/drafts/draft-123");
    expect(descriptor.title).toBe("Team Lunch Poll");
    expect(descriptor.panelKey).toBe("draft_detail");
    expect(descriptor.editorKey).toBe("application_workbench");
  });
});
