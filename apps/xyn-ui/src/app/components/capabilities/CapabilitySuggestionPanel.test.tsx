import { MemoryRouter } from "react-router-dom";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import CapabilitySuggestionPanel from "./CapabilitySuggestionPanel";

const mockUseCapabilitiesForContext = vi.hoisted(() => vi.fn());
const mockExecuteCapabilityAction = vi.hoisted(() => vi.fn());

vi.mock("../../capabilities/useCapabilitiesForContext", () => ({
  useCapabilitiesForContext: mockUseCapabilitiesForContext,
}));

vi.mock("../../navigation/executeCapabilityAction", () => ({
  executeCapabilityAction: mockExecuteCapabilityAction,
}));

describe("CapabilitySuggestionPanel", () => {
  it("renders available and unavailable capabilities and only executes available ones", async () => {
    mockUseCapabilitiesForContext.mockReturnValue({
      loading: false,
      error: null,
      context: "artifact_detail",
      attributes: { artifact_type: "application" },
      capabilities: [
        {
          id: "open_application_workspace",
          name: "Open application workspace",
          description: "Open the application workbench for this application context.",
          visibility: "secondary",
          available: true,
          action_type: "open_descriptor",
          action_target: "fromApplicationWorkspace",
        },
        {
          id: "continue_application_draft",
          name: "Continue application design",
          description: "Continue shaping the current application draft in the workbench.",
          visibility: "primary",
          available: false,
          failure_message: "This draft is no longer in an editable state.",
        },
      ],
    });

    render(
      <MemoryRouter>
        <CapabilitySuggestionPanel
          context="artifact_detail"
          workspaceId="ws-1"
          artifactId="artifact-1"
          onInsertSuggestion={vi.fn()}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("Suggested Actions")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Open application workspace/i })).toBeInTheDocument();
    expect(screen.getByText("Unavailable Right Now")).toBeInTheDocument();
    expect(screen.getByText("Continue application design")).toBeInTheDocument();
    expect(screen.getByText("This draft is no longer in an editable state.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Continue application design/i })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Open application workspace/i }));
    expect(mockExecuteCapabilityAction).toHaveBeenCalledTimes(1);
  });
});
