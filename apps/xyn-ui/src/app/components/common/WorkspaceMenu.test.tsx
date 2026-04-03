import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import WorkspaceMenu from "./WorkspaceMenu";

describe("WorkspaceMenu", () => {
  const workspaces = [
    { id: "ws-1", name: "Workspace One" },
    { id: "ws-2", name: "Workspace Two" },
    { id: "ws-3", name: "Workspace Three" },
  ];

  it("renders the active workspace as the trigger label", () => {
    render(<WorkspaceMenu activeWorkspaceId="ws-2" workspaces={workspaces} onWorkspaceChange={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Workspace" })).toHaveTextContent("Workspace Two");
  });

  it("opens popover menu and changes workspace on selection", () => {
    const onWorkspaceChange = vi.fn();
    render(<WorkspaceMenu activeWorkspaceId="ws-1" workspaces={workspaces} onWorkspaceChange={onWorkspaceChange} />);

    fireEvent.click(screen.getByRole("button", { name: "Workspace" }));
    expect(document.querySelector(".workspace-menu-popover")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Workspace Three" }));

    expect(onWorkspaceChange).toHaveBeenCalledWith("ws-3");
    expect(screen.queryByRole("button", { name: "Workspace Two" })).not.toBeInTheDocument();
  });

  it("applies truncation class to workspace option labels for long names", () => {
    const longName = "Workspace With An Extremely Long Name That Should Not Force The Dropdown Wider Than The Viewport";
    render(
      <WorkspaceMenu
        activeWorkspaceId="ws-1"
        workspaces={[
          { id: "ws-1", name: longName },
          { id: "ws-2", name: `${longName} 2` },
        ]}
        onWorkspaceChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Workspace" }));
    const labels = screen.getAllByText(longName);
    const optionLabel = labels.find((element) => element.classList.contains("workspace-menu-item-label"));
    expect(optionLabel).toBeDefined();
    expect(optionLabel).toHaveClass("workspace-menu-item-label");
  });
});
