import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi, beforeEach } from "vitest";

import CampaignMapWorkflowPage from "./CampaignMapWorkflowPage";

const apiMocks = vi.hoisted(() => ({
  createCampaign: vi.fn(),
  getCampaign: vi.fn(),
  updateCampaign: vi.fn(),
}));

vi.mock("../../api/xyn", () => ({
  createCampaign: (...args: unknown[]) => apiMocks.createCampaign(...args),
  getCampaign: (...args: unknown[]) => apiMocks.getCampaign(...args),
  updateCampaign: (...args: unknown[]) => apiMocks.updateCampaign(...args),
}));

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname}</div>;
}

describe("CampaignMapWorkflowPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("creates a campaign with rectangle bounds persisted in metadata", async () => {
    apiMocks.createCampaign.mockResolvedValue({
      id: "camp-1",
      workspace_id: "ws-1",
      slug: "camp-1",
      name: "North STL Watch",
      campaign_type: "generic",
      status: "draft",
      description: "",
      archived: false,
      created_at: "2026-03-23T00:00:00Z",
      updated_at: "2026-03-23T00:00:00Z",
      metadata: {},
    });

    render(
      <MemoryRouter initialEntries={["/w/ws-1/a/campaigns/new"]}>
        <Routes>
          <Route path="/w/:workspaceId/a/campaigns/new" element={<CampaignMapWorkflowPage workspaceId="ws-1" />} />
          <Route path="/w/:workspaceId/a/campaigns/:id" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    );

    const canvas = await screen.findByTestId("campaign-map-canvas");
    Object.defineProperty(canvas, "getBoundingClientRect", {
      value: () => ({ left: 0, top: 0, width: 760, height: 440, right: 760, bottom: 440 }),
    });

    fireEvent.mouseDown(canvas, { clientX: 100, clientY: 120 });
    fireEvent.mouseMove(canvas, { clientX: 420, clientY: 300 });
    fireEvent.mouseUp(canvas);

    fireEvent.change(screen.getByLabelText("Campaign name"), { target: { value: "North STL Watch" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Campaign" }));

    await waitFor(() => expect(apiMocks.createCampaign).toHaveBeenCalledTimes(1));
    const payload = apiMocks.createCampaign.mock.calls[0][0];
    expect(payload.workspace_id).toBe("ws-1");
    expect(payload.name).toBe("North STL Watch");
    expect(payload.metadata.monitoring_mode).toBe("rectangle_box_selection");
    expect(payload.metadata.monitoring_bounds.min_lng).toBeTypeOf("number");
    expect(payload.metadata.monitoring_bounds.max_lng).toBeTypeOf("number");

    await waitFor(() => expect(screen.getByTestId("location-probe").textContent).toContain("/w/ws-1/a/campaigns/camp-1"));
  });

  it("reopens campaign and displays persisted rectangle bounds", async () => {
    apiMocks.getCampaign.mockResolvedValue({
      id: "camp-2",
      workspace_id: "ws-1",
      slug: "camp-2",
      name: "Reopen Test",
      campaign_type: "generic",
      status: "draft",
      description: "",
      archived: false,
      created_at: "2026-03-23T00:00:00Z",
      updated_at: "2026-03-23T00:00:00Z",
      metadata: {
        monitoring_bounds: {
          min_lng: -90.31,
          min_lat: 38.58,
          max_lng: -90.21,
          max_lat: 38.69,
        },
      },
    });

    render(
      <MemoryRouter initialEntries={["/w/ws-1/a/campaigns/camp-2"]}>
        <Routes>
          <Route path="/w/:workspaceId/a/campaigns/:id" element={<CampaignMapWorkflowPage workspaceId="ws-1" campaignId="camp-2" />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByTestId("campaign-map-selection-rect")).toBeInTheDocument();
    const readout = await screen.findByTestId("campaign-bounds-readout");
    expect(readout.textContent).toContain("-90.31");
    expect(readout.textContent).toContain("38.69");
  });
});
