import { describe, expect, it } from "vitest";
import { applyPatchToFormSnapshot, buildArticleDraftSnapshot } from "./articleIntentForm";

describe("articleIntentForm", () => {
  it("applies whitelisted fields and ignores unknown keys", () => {
    const base = buildArticleDraftSnapshot({
      title: "Title",
      category: "demo",
      format: "standard",
      intent: null,
      duration: null,
      tags: ["one"],
      summary: "old",
      body: "body",
    });

    const result = applyPatchToFormSnapshot(base, {
      summary: "new summary",
      tags: ["governance", "access-control"],
      bogus: "x",
    });

    expect(result.next.summary).toBe("new summary");
    expect(result.next.tags).toEqual(["governance", "access-control"]);
    expect(result.appliedFields).toEqual(["summary", "tags"]);
    expect(result.ignoredFields).toEqual(["bogus"]);
  });

  it("supports format switch while preserving intent/duration payload", () => {
    const base = buildArticleDraftSnapshot({
      title: "Title",
      category: "demo",
      format: "standard",
      intent: "governance overview",
      duration: 150,
      tags: [],
      summary: "summary",
      body: "body",
    });

    const result = applyPatchToFormSnapshot(base, {
      format: "video_explainer",
      intent: "updated intent",
      duration: 300,
    });

    expect(result.next.format).toBe("video_explainer");
    expect(result.next.intent).toBe("updated intent");
    expect(result.next.duration).toBe(300);
    expect(result.ignoredFields).toEqual([]);
  });
});
