import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CapabilityExplorerPage from "./CapabilityExplorerPage";

const apiMocks = vi.hoisted(() => ({
  getCapabilityGraph: vi.fn(),
}));

vi.mock("../../api/xyn", () => ({
  getCapabilityGraph: apiMocks.getCapabilityGraph,
}));

const mockGraph = {
  contexts: [
    { id: "landing", name: "Landing", description: "Top-level workspace landing guidance." },
    { id: "application_workspace", name: "Application Workspace", description: "Application workbench and composer context." },
  ],
  capabilities: [
    {
      id: "build_application",
      name: "Build an application",
      description: "Create a new software application.",
      contexts: ["landing"],
      action_type: "prompt",
      preconditions: [],
    },
    {
      id: "open_application_workspace",
      name: "Open application workspace",
      description: "Open the application workbench for this application context.",
      contexts: ["application_workspace"],
      action_type: "open_descriptor",
      preconditions: [],
    },
  ],
  paths: [
    {
      id: "build_application",
      name: "Build an Application",
      description: "Create and open an application.",
      contexts: ["landing"],
      steps: ["build_application", "open_application_workspace"],
    },
  ],
};

describe("CapabilityExplorerPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders contexts, capabilities, and workflows and switches context views", async () => {
    const user = userEvent.setup();
    let resolveGraph: ((value: typeof mockGraph) => void) | null = null;
    apiMocks.getCapabilityGraph.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveGraph = resolve;
        })
    );

    render(<CapabilityExplorerPage />);

    expect(screen.getByText("Loading capability graph…")).toBeInTheDocument();
    await act(async () => {
      resolveGraph?.(mockGraph);
    });
    expect(screen.queryByText("Loading capability graph…")).not.toBeInTheDocument();
    expect(screen.getByTestId("capability-explorer")).toBeInTheDocument();
    expect(apiMocks.getCapabilityGraph).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: /Landing/i })).toBeInTheDocument();

    const capabilitySection = screen.getByRole("heading", { name: "Landing Capabilities" }).closest("section");
    const workflowSection = screen.getByRole("heading", { name: "Landing Workflows" }).closest("section");
    expect(capabilitySection).not.toBeNull();
    expect(workflowSection).not.toBeNull();
    expect(within(capabilitySection as HTMLElement).getByText("Build an application")).toBeInTheDocument();
    expect(within(workflowSection as HTMLElement).getByText("Build an Application")).toBeInTheDocument();

    await act(async () => {
      await user.click(screen.getByRole("button", { name: /Application Workspace/i }));
    });
    const workspaceCapabilitySection = await screen.findByRole("heading", { name: "Application Workspace Capabilities" });
    expect(within(workspaceCapabilitySection.closest("section") as HTMLElement).getByText("Open application workspace")).toBeInTheDocument();
    expect(screen.getByText("No workflows are mapped to this context.")).toBeInTheDocument();
  });
});
