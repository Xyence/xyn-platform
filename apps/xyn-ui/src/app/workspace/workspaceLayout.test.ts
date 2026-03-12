import { describe, expect, it } from "vitest";

import type { ConsolePanelState } from "../state/xynConsoleStore";
import { buildFlexLayoutModel, syncFlexLayoutModel } from "./workspaceLayout";

const SAMPLE_PANELS: ConsolePanelState[] = [
  {
    panel_id: "run_detail:run-1",
    panel_type: "detail",
    instance_key: "run:run-1",
    title: "Run",
    key: "run_detail",
    params: { run_id: "run-1" },
  },
  {
    panel_id: "artifact_view:artifact-1",
    panel_type: "detail",
    instance_key: "artifact:artifact-1",
    title: "Artifact",
    key: "artifact_detail",
    params: { slug: "artifact-1" },
  },
];

describe("workspaceLayout", () => {
  it("builds a flexlayout model from durable panels", () => {
    const model = buildFlexLayoutModel(SAMPLE_PANELS, "artifact_view:artifact-1");
    const tabset = (((model.layout as unknown as Record<string, unknown>).children as Array<Record<string, unknown>>)[0]);
    expect(tabset.selected).toBe(1);
    expect((tabset.children as Array<Record<string, unknown>>).map((entry) => entry.id)).toEqual([
      "run_detail:run-1",
      "artifact_view:artifact-1",
    ]);
  });

  it("preserves existing tabs while syncing new panels", () => {
    const current = buildFlexLayoutModel([SAMPLE_PANELS[0]], "run_detail:run-1");
    const next = syncFlexLayoutModel(current, SAMPLE_PANELS, "artifact_view:artifact-1");
    const tabset = (((next.layout as unknown as Record<string, unknown>).children as Array<Record<string, unknown>>)[0]);
    expect((tabset.children as Array<Record<string, unknown>>).map((entry) => entry.id)).toEqual([
      "run_detail:run-1",
      "artifact_view:artifact-1",
    ]);
  });
});
