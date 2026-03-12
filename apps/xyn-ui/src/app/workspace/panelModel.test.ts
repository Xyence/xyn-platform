import { describe, expect, it } from "vitest";

import { buildPanelId, createPanel, validatePanel, validateWorkspaceLayout } from "./panelModel";

describe("panelModel", () => {
  it("creates durable panel objects with minimal serializable metadata", () => {
    const panel = createPanel({
      panel_type: "run_detail",
      object_type: "run",
      object_id: "run-123",
      thread_id: null,
      workspace_id: "ws-1",
      creation_source: "intent",
    });

    expect(panel.panel_id).toBe(buildPanelId("run_detail", "run-123"));
    expect(panel.object_id).toBe("run-123");
    expect(panel.workspace_id).toBe("ws-1");
    expect(panel.created_at).toBeTruthy();
  });

  it("requires thread identity for conversation panels", () => {
    expect(() =>
      validatePanel({
        panel_id: "conversation:missing",
        panel_type: "conversation",
        object_type: "conversation",
        object_id: "thread-1",
        thread_id: null,
        workspace_id: "ws-1",
        creation_source: "restore",
        created_at: "2026-03-11T10:00:00Z",
      })
    ).toThrow(/requires thread_id/i);
  });

  it("rejects mismatched panel and object identity types", () => {
    expect(() =>
      createPanel({
        panel_type: "artifact_view",
        object_type: "run",
        object_id: "run-1",
        thread_id: null,
        workspace_id: "ws-1",
        creation_source: "route",
      })
    ).toThrow(/must target object type artifact/i);
  });

  it("validates persisted workspace layout shape", () => {
    expect(
      validateWorkspaceLayout({
        workspace_id: "ws-1",
        flexlayout_model: { global: {}, layout: {} },
        panel_ids: ["run_detail:run-1"],
        preset_id: "workbench.default",
        lock_mode: "starting_layout_only",
        last_updated: "2026-03-11T10:00:00Z",
      })
    ).toMatchObject({ workspace_id: "ws-1" });
  });
});
