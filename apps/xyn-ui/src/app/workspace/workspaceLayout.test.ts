import { describe, expect, it } from "vitest";

import type { ConsolePanelState } from "../state/xynConsoleStore";
import { buildFlexLayoutModel, syncFlexLayoutModel } from "./workspaceLayout";

const SAMPLE_PANELS: ConsolePanelState[] = [
  {
    panel_id: "run_detail:run-1",
    panel_type: "detail",
    instance_key: "run:run-1",
    title: "Run Detail",
    key: "run_detail",
    params: { run_id: "run-1" },
    active_group_id: "stack-operations",
    panel_affinity: "operations",
    workspace_id: "ws-1",
    thread_id: null,
  },
  {
    panel_id: "artifact_view:artifact-1",
    panel_type: "detail",
    instance_key: "artifact:artifact-1",
    title: "Artifact Detail",
    key: "artifact_detail",
    params: { slug: "artifact-1" },
    active_group_id: "stack-artifacts",
    panel_affinity: "artifacts",
    workspace_id: "ws-1",
    thread_id: null,
  },
];

describe("workspaceLayout", () => {
  it("builds a flexlayout model from durable panels", () => {
    const model = buildFlexLayoutModel(SAMPLE_PANELS, "artifact_view:artifact-1");
    const tabsets = ((model.layout as unknown as Record<string, unknown>).children as Array<Record<string, unknown>>);
    expect(tabsets.map((entry) => entry.id)).toEqual(["stack-conversation", "stack-application", "stack-operations", "stack-artifacts"]);
    expect((tabsets[2].children as Array<Record<string, unknown>>).map((entry) => entry.id)).toEqual(["run_detail:run-1"]);
    expect((tabsets[3].children as Array<Record<string, unknown>>).map((entry) => entry.id)).toEqual(["artifact_view:artifact-1"]);
    expect(tabsets[3].selected).toBe(0);
  });

  it("preserves existing tabs while syncing new panels", () => {
    const current = buildFlexLayoutModel([SAMPLE_PANELS[0]], "run_detail:run-1");
    const next = syncFlexLayoutModel(current, SAMPLE_PANELS, "artifact_view:artifact-1");
    const tabsets = ((next.layout as unknown as Record<string, unknown>).children as Array<Record<string, unknown>>);
    expect((tabsets[2].children as Array<Record<string, unknown>>).map((entry) => entry.id)).toEqual(["run_detail:run-1"]);
    expect((tabsets[3].children as Array<Record<string, unknown>>).map((entry) => entry.id)).toEqual(["artifact_view:artifact-1"]);
  });
});
