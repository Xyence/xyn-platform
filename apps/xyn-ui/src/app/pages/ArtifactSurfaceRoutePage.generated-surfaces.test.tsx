import { describe, expect, it } from "vitest";

import { toSurfaceResolvePath } from "./ArtifactSurfaceRoutePage";

describe("artifact surface route path normalization", () => {
  it("normalizes workspace-scoped generated surface paths back to canonical /app routes", () => {
    expect(toSurfaceResolvePath("/w/ws-1/a/campaigns")).toBe("/app/campaigns");
    expect(toSurfaceResolvePath("/w/ws-1/a/campaigns/new")).toBe("/app/campaigns/new");
    expect(toSurfaceResolvePath("/w/ws-1/a")).toBe("/app");
  });

  it("keeps existing non-workspace paths unchanged", () => {
    expect(toSurfaceResolvePath("/app/signals")).toBe("/app/signals");
    expect(toSurfaceResolvePath("/w/ws-1/workbench")).toBe("/w/ws-1/workbench");
  });
});

