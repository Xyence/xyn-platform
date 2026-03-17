import { describe, expect, it } from "vitest";
import { deriveBuildToastEventKey } from "./buildToastEvents";

describe("deriveBuildToastEventKey", () => {
  it("returns null for non-terminal draft states", () => {
    expect(
      deriveBuildToastEventKey({
        overallState: "building",
        latestFailedJob: null,
        latestJob: null,
        executionNote: null,
      }),
    ).toBeNull();
  });

  it("derives a stable blocked-state key from the latest failed job", () => {
    expect(
      deriveBuildToastEventKey({
        overallState: "build_blocked",
        latestFailedJob: { id: "job-1", updated_at: "2026-03-16T14:00:00Z" },
        latestJob: { id: "job-2", updated_at: "2026-03-16T14:01:00Z" },
        executionNote: { id: "note-1", updated_at: "2026-03-16T14:02:00Z" },
      }),
    ).toBe("build_blocked:job-1:2026-03-16T14:00:00Z");
  });

  it("falls back to execution note timing when no job ids are available", () => {
    expect(
      deriveBuildToastEventKey({
        overallState: "needs_revision",
        latestFailedJob: null,
        latestJob: null,
        executionNote: { id: "note-2", timestamp: "2026-03-16T14:03:00Z" },
      }),
    ).toBe("needs_revision:note-2:2026-03-16T14:03:00Z");
  });

  it("uses the latest successful job for ready-state announcements", () => {
    expect(
      deriveBuildToastEventKey({
        overallState: "ready",
        latestFailedJob: null,
        latestJob: { id: "job-3", created_at: "2026-03-16T14:04:00Z" },
        executionNote: null,
      }),
    ).toBe("ready:job-3:2026-03-16T14:04:00Z");
  });
});
