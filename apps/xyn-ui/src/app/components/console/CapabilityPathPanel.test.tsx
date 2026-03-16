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
});
