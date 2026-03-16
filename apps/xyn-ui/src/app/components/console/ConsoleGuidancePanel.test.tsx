import { MemoryRouter } from "react-router-dom";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import ConsoleGuidancePanel from "./ConsoleGuidancePanel";

const mockUseContextualCapabilities = vi.hoisted(() => vi.fn());
const mockUseCapabilityPaths = vi.hoisted(() => vi.fn());
const mockUseExecutionPlan = vi.hoisted(() => vi.fn());
const mockExecuteCapabilityAction = vi.hoisted(() => vi.fn());

vi.mock("./contextualCapabilities", () => ({
  useContextualCapabilities: mockUseContextualCapabilities,
}));

vi.mock("./capabilityPaths", () => ({
  useCapabilityPaths: mockUseCapabilityPaths,
}));

vi.mock("./useExecutionPlan", () => ({
  useExecutionPlan: mockUseExecutionPlan,
}));

vi.mock("../../navigation/executeCapabilityAction", () => ({
  executeCapabilityAction: mockExecuteCapabilityAction,
}));

describe("ConsoleGuidancePanel", () => {
  it("renders unavailable capabilities with explanations and does not make them clickable", async () => {
    mockUseExecutionPlan.mockImplementation((capabilityId) => ({
      loading: false,
      error: null,
      plan: capabilityId
        ? {
            capability_id: String(capabilityId),
            architecture: {},
            defaults: {},
            dependencies: [],
            components: [],
            generated_commands: [],
            artifacts: [],
          }
        : null,
    }));
    mockUseContextualCapabilities.mockReturnValue({
      capabilities: [
        {
          id: "build_application",
          name: "Build an application",
          description: "Create a new software application.",
          prompt_template: "Build an application that...",
          visibility: "primary",
          available: true,
          action_type: "prompt",
        },
        {
          id: "open_application_workspace",
          name: "Open application workspace",
          description: "Open the application workbench for this application context.",
          visibility: "secondary",
          available: false,
          failure_code: "application_missing",
          failure_message: "The application has not been generated yet.",
          action_type: "open_descriptor",
          action_target: "fromApplicationWorkspace",
        },
      ],
    });
    mockUseCapabilityPaths.mockReturnValue({
      paths: [],
      selectedPath: null,
      selectedPathId: "",
      setSelectedPath: vi.fn(),
    });

    const onInsertSuggestion = vi.fn();
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <ConsoleGuidancePanel onInsertSuggestion={onInsertSuggestion} context="app_intent_draft" workspaceId="ws-1" entityId="draft-1" />
      </MemoryRouter>,
    );

    expect(screen.getByRole("button", { name: /Build an application/i })).toBeInTheDocument();
    expect(screen.getByText("Unavailable Right Now")).toBeInTheDocument();
    expect(screen.getByText("Open application workspace")).toBeInTheDocument();
    expect(screen.getByText("The application has not been generated yet.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Open application workspace/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Build an application/i }));
    expect(mockExecuteCapabilityAction).toHaveBeenCalledTimes(1);
    expect(onInsertSuggestion).not.toHaveBeenCalled();
    expect(mockUseExecutionPlan).not.toHaveBeenCalledWith("build_application");

    await act(async () => {
      await user.click(screen.getByRole("button", { name: /View plan/i }));
    });
    expect(mockUseExecutionPlan).toHaveBeenCalledWith("build_application");
  });
});
