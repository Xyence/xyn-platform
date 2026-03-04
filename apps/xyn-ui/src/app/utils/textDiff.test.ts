import { describe, expect, it } from "vitest";
import { computeLineDiff } from "./textDiff";

describe("computeLineDiff", () => {
  it("returns no changes for identical text", () => {
    const result = computeLineDiff("a\nb", "a\nb");
    expect(result.summary.changed).toBe(0);
    expect(result.ops.filter((op) => op.type !== "context")).toHaveLength(0);
  });

  it("tracks additions and removals", () => {
    const result = computeLineDiff("a\nb", "a\nc\nd");
    expect(result.summary.added).toBe(2);
    expect(result.summary.removed).toBe(1);
  });

  it("handles empty strings", () => {
    const result = computeLineDiff("", "");
    expect(result.summary.changed).toBe(0);
  });
});
