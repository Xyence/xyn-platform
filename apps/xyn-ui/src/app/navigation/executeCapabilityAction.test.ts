import { describe, expect, it, vi } from "vitest";

import { executeCapabilityAction } from "./executeCapabilityAction";

describe("executeCapabilityAction", () => {
  it("inserts prompt text for prompt capabilities", () => {
    const navigate = vi.fn();
    const insertPrompt = vi.fn();

    const result = executeCapabilityAction({
      capability: {
        id: "build_application",
        name: "Build an application",
        description: "Create a new application.",
        prompt_template: "Build an application that...",
        visibility: "primary",
        action_type: "prompt",
      },
      navigate,
      workspaceId: "ws-1",
      insertPrompt,
    });

    expect(result).toBe("prompt");
    expect(insertPrompt).toHaveBeenCalledWith("Build an application that...");
    expect(navigate).not.toHaveBeenCalled();
  });

  it("opens the application workspace for descriptor capabilities", () => {
    const navigate = vi.fn();
    const insertPrompt = vi.fn();

    const result = executeCapabilityAction({
      capability: {
        id: "open_application_workspace",
        name: "Open Application Workspace",
        description: "Open workbench.",
        visibility: "secondary",
        action_type: "open_descriptor",
        action_target: "fromApplicationWorkspace",
      },
      navigate,
      workspaceId: "ws-1",
      insertPrompt,
    });

    expect(result).toBe("action");
    expect(navigate).toHaveBeenCalledWith("/w/ws-1/workbench");
    expect(insertPrompt).not.toHaveBeenCalled();
  });

  it("opens artifact detail for descriptor capabilities", () => {
    const navigate = vi.fn();
    const insertPrompt = vi.fn();

    const result = executeCapabilityAction({
      capability: {
        id: "view_artifact_details",
        name: "View Artifact Details",
        description: "Open the artifact.",
        visibility: "primary",
        action_type: "open_descriptor",
        action_target: "fromArtifactDetail",
      },
      navigate,
      workspaceId: "ws-1",
      entityId: "artifact-1",
      insertPrompt,
    });

    expect(result).toBe("action");
    expect(navigate).toHaveBeenCalledWith("/w/ws-1/build/artifacts/artifact-1");
  });

  it("opens workspace jobs for route capabilities", () => {
    const navigate = vi.fn();
    const insertPrompt = vi.fn();

    const result = executeCapabilityAction({
      capability: {
        id: "view_execution_status",
        name: "View Execution Status",
        description: "Open jobs.",
        visibility: "secondary",
        action_type: "route",
        action_target: "workspace_jobs",
      },
      navigate,
      workspaceId: "ws-1",
      entityId: "draft-1",
      insertPrompt,
    });

    expect(result).toBe("action");
    expect(navigate).toHaveBeenCalledWith("/w/ws-1/jobs");
  });
});
