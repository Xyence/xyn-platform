import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SourceInspectionReviewPage from "./SourceInspectionReviewPage";

const apiMocks = vi.hoisted(() => ({
  listSourceConnectors: vi.fn(),
  listSourceInspections: vi.fn(),
  listSourceMappings: vi.fn(),
}));

vi.mock("../../api/xyn", () => apiMocks);

describe("SourceInspectionReviewPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.listSourceConnectors.mockResolvedValue({ workspace_id: "ws-1", sources: [] });
    apiMocks.listSourceInspections.mockResolvedValue({ source_id: "s-1", inspections: [] });
    apiMocks.listSourceMappings.mockResolvedValue({ source_id: "s-1", mappings: [] });
  });

  function renderPage(workspaceId = "ws-1") {
    return render(
      <MemoryRouter initialEntries={["/w/ws-1/sources"]}>
        <Routes>
          <Route path="/w/:workspaceId/sources" element={<SourceInspectionReviewPage workspaceId={workspaceId} workspaceName="Workspace" />} />
        </Routes>
      </MemoryRouter>
    );
  }

  it("renders empty state when no inspections", async () => {
    renderPage();
    await waitFor(() => expect(apiMocks.listSourceConnectors).toHaveBeenCalled());
    expect(await screen.findByText(/No inspections captured/i)).toBeInTheDocument();
  });
});
