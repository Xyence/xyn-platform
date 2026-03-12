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
