import { describe, expect, it } from "vitest";

import { openPanel, createWorkspacePanel } from "./panelFactory";
import { getRegisteredPanel } from "./panelRegistry";

describe("panelFactory", () => {
  it("requires explicit registration for known panel types", () => {
    expect(getRegisteredPanel("run_detail")).toMatchObject({ console_key: "run_detail" });
  });

  it("creates and restores run detail panels through the registry path", () => {
    const panel = createWorkspacePanel({
      panel_type: "run_detail",
      object_id: "run-123",
      workspace_id: "ws-1",
      creation_source: "intent",
    });

    const spec = openPanel(panel);
    expect(spec.panel_id).toBe(panel.panel_id);
    expect(spec.key).toBe("run_detail");
    expect(spec.title).toBe("Run Detail");
    expect(spec.params).toMatchObject({ run_id: "run-123" });
  });

  it("creates and restores work item panels through the registry path", () => {
    const panel = createWorkspacePanel({
      panel_type: "work_item",
      object_id: "wi-123",
      workspace_id: "ws-1",
      thread_id: "thread-1",
      creation_source: "conversation_action",
    });

    const spec = openPanel(panel);
    expect(spec.key).toBe("work_item_detail");
    expect(spec.title).toBe("Work Item");
    expect(spec.params).toMatchObject({ work_item_id: "wi-123" });
  });

  it("creates and restores thread detail panels through the registry path", () => {
    const panel = createWorkspacePanel({
      panel_type: "thread_detail",
      object_id: "thread-123",
      workspace_id: "ws-1",
      creation_source: "conversation_action",
    });

    const spec = openPanel(panel);
    expect(spec.key).toBe("thread_detail");
    expect(spec.title).toBe("Thread");
    expect(spec.params).toMatchObject({ thread_id: "thread-123" });
  });

  it("creates and restores goal detail panels through the registry path", () => {
    const panel = createWorkspacePanel({
      panel_type: "goal_detail",
      object_id: "goal-123",
      workspace_id: "ws-1",
      creation_source: "conversation_action",
    });

    const spec = openPanel(panel);
    expect(spec.key).toBe("goal_detail");
    expect(spec.title).toBe("Goal");
    expect(spec.params).toMatchObject({ goal_id: "goal-123" });
  });

  it("maps runtime artifact object ids into artifact detail params", () => {
    const panel = createWorkspacePanel({
      panel_type: "artifact_view",
      object_id: "runtime-run-artifact:run-1:artifact-1",
      workspace_id: "ws-1",
      creation_source: "runtime_event",
    });

    const spec = openPanel(panel);
    expect(spec.key).toBe("artifact_detail");
    expect(spec.params).toMatchObject({ runtime_run_id: "run-1", runtime_artifact_id: "artifact-1" });
  });

  it("rejects invalid panel objects instead of silently opening them", () => {
    expect(() =>
      openPanel({
        panel_id: "broken",
        panel_type: "artifact_view",
        object_type: "run",
        object_id: "run-1",
        thread_id: null,
        workspace_id: "ws-1",
        creation_source: "restore",
        created_at: "2026-03-11T10:00:00Z",
      } as never)
    ).toThrow(/must target object type artifact/i);
  });
});
