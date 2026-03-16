import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CapabilityExplorerPage from "./CapabilityExplorerPage";

const apiMocks = vi.hoisted(() => ({
  getCapabilityGraph: vi.fn(),
}));

vi.mock("../../api/xyn", () => ({
  getCapabilityGraph: apiMocks.getCapabilityGraph,
}));

describe("CapabilityExplorerPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.getCapabilityGraph.mockResolvedValue({
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
    });
  });

  it("renders contexts, capabilities, and workflows and switches context views", async () => {
    render(<CapabilityExplorerPage />);

    await waitFor(() => expect(screen.getByText("Capability Explorer")).toBeInTheDocument());
    expect(screen.getByText("Landing")).toBeInTheDocument();
    expect(screen.getAllByText("Build an application").length).toBeGreaterThan(0);
    expect(screen.getByText("Build an Application")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Application Workspace/i }));
    expect(await screen.findByText("Open application workspace")).toBeInTheDocument();
    expect(screen.getByText("No workflows are mapped to this context.")).toBeInTheDocument();
  });
});
