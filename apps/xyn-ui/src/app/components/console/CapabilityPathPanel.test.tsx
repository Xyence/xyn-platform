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
          paths={[
            {
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
            },
          ]}
          selectedPath={{
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
          selectedPathId="build_application"
          onSelectPath={vi.fn()}
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
          paths={[
            {
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
            },
          ]}
          selectedPath={{
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
          selectedPathId="build_application"
          onSelectPath={vi.fn()}
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

  it("renders a selector when multiple workflows are available and switches paths", async () => {
    const onSelectPath = vi.fn();
    render(
      <MemoryRouter>
        <CapabilityPathPanel
          paths={[
            {
              id: "build_application",
              name: "Build an Application",
              description: "Guided build flow",
              steps: [
                {
                  capability_id: "build_application",
                  name: "Build application",
                  description: "Create draft.",
                  visibility: "primary",
                  action_type: "prompt",
                  status: "current",
                },
              ],
            },
            {
              id: "workspace_exploration",
              name: "Explore the Workspace",
              description: "Inspect the workspace.",
              steps: [
                {
                  capability_id: "open_application_workspace",
                  name: "Open application workspace",
                  description: "Open workbench.",
                  visibility: "secondary",
                  action_type: "open_descriptor",
                  action_target: "fromApplicationWorkspace",
                  status: "current",
                },
              ],
            },
          ]}
          selectedPath={{
            id: "workspace_exploration",
            name: "Explore the Workspace",
            description: "Inspect the workspace.",
            steps: [
              {
                capability_id: "open_application_workspace",
                name: "Open application workspace",
                description: "Open workbench.",
                visibility: "secondary",
                action_type: "open_descriptor",
                action_target: "fromApplicationWorkspace",
                status: "current",
              },
            ],
          }}
          selectedPathId="workspace_exploration"
          onSelectPath={onSelectPath}
          workspaceId="ws-1"
          entityId="draft-1"
          onInsertSuggestion={vi.fn()}
        />
      </MemoryRouter>,
    );

    const selector = screen.getByLabelText("Select guided workflow") as HTMLSelectElement;
    expect(selector).toBeInTheDocument();
    expect(selector.value).toBe("workspace_exploration");

    await userEvent.selectOptions(selector, "build_application");
    expect(onSelectPath).toHaveBeenCalledWith("build_application");
  });
});
