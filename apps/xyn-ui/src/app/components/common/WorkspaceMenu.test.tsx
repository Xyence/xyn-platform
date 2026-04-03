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
});
