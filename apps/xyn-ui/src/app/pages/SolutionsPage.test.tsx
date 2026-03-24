import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import SolutionsPage from "./SolutionsPage";

const apiMocks = vi.hoisted(() => ({
  listApplications: vi.fn(),
}));

vi.mock("../../api/xyn", () => ({
  listApplications: apiMocks.listApplications,
}));

describe("SolutionsPage", () => {
  it("renders application-level grouped context with member counts", async () => {
    apiMocks.listApplications.mockResolvedValue({
      applications: [
        {
          id: "app-1",
          workspace_id: "ws-1",
          name: "Deal Finder",
          summary: "Real Estate",
          source_factory_key: "generic_application_mvp",
          status: "active",
          request_objective: "Build app",
          goal_count: 2,
          artifact_member_count: 3,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-02T00:00:00Z",
        },
      ],
    });

    render(
      <MemoryRouter initialEntries={["/w/ws-1/solutions"]}>
        <Routes>
          <Route path="/w/:workspaceId/solutions" element={<SolutionsPage workspaceId="ws-1" workspaceName="Workspace 1" />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => expect(apiMocks.listApplications).toHaveBeenCalledWith("ws-1"));
    expect(screen.getByText("Deal Finder")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open" })).toHaveAttribute("href", "/w/ws-1/solutions/app-1");
  });
});

