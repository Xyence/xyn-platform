import { MemoryRouter } from "react-router-dom";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import CapabilityPathPanel from "./CapabilityPathPanel";

const mockNavigate = vi.hoisted(() => vi.fn());

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

describe("CapabilityPathPanel", () => {
  it("executes step actions through the capability executor", async () => {
    const onInsertSuggestion = vi.fn();
    render(
      <MemoryRouter>
        <CapabilityPathPanel
          path={{
            id: "build_application",
            name: "Build an Application",
            description: "Guided flow",
            steps: [
              {
                capability_id: "open_application_workspace",
                name: "Open Application Workspace",
                description: "Open workbench.",
                visibility: "secondary",
                action_type: "open_descriptor",
                action_target: "fromApplicationWorkspace",
                status: "current",
              },
            ],
          }}
          workspaceId="ws-1"
          entityId="draft-1"
          onInsertSuggestion={onInsertSuggestion}
        />
      </MemoryRouter>,
    );

    await userEvent.click(screen.getByRole("button", { name: /Open Application Workspace/i }));
    expect(mockNavigate).toHaveBeenCalledWith("/w/ws-1/workbench");
    expect(onInsertSuggestion).not.toHaveBeenCalled();
  });

  it("renders progress markers for completed, current, and pending steps", () => {
    render(
      <MemoryRouter>
        <CapabilityPathPanel
          path={{
            id: "build_application",
            name: "Build an Application",
            description: "Guided flow",
            steps: [
              {
                capability_id: "build_application",
                name: "Build application",
                description: "Create draft.",
                visibility: "primary",
                action_type: "prompt",
                status: "completed",
              },
              {
                capability_id: "continue_application_draft",
                name: "Continue application draft",
                description: "Refine the draft.",
                visibility: "primary",
                action_type: "prompt",
                status: "current",
              },
              {
                capability_id: "open_application_workspace",
                name: "Open application workspace",
                description: "Open workbench.",
                visibility: "secondary",
                action_type: "open_descriptor",
                action_target: "fromApplicationWorkspace",
                status: "pending",
              },
            ],
          }}
          workspaceId="ws-1"
          entityId="draft-1"
          onInsertSuggestion={vi.fn()}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("✔ Build application")).toBeInTheDocument();
    expect(screen.getByText("→ Continue application draft")).toBeInTheDocument();
    expect(screen.getByText("Open application workspace")).toBeInTheDocument();
  });
});
