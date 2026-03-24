import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ArtifactSurfaceRoutePage from "./ArtifactSurfaceRoutePage";

const apiMocks = vi.hoisted(() => ({
  resolveArtifactSurface: vi.fn(),
  createCampaign: vi.fn(),
  getCampaign: vi.fn(),
  updateCampaign: vi.fn(),
}));

vi.mock("../../api/xyn", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/xyn")>();
  return {
    ...actual,
    resolveArtifactSurface: (...args: unknown[]) => apiMocks.resolveArtifactSurface(...args),
    createCampaign: (...args: unknown[]) => apiMocks.createCampaign(...args),
    getCampaign: (...args: unknown[]) => apiMocks.getCampaign(...args),
    updateCampaign: (...args: unknown[]) => apiMocks.updateCampaign(...args),
  };
});

describe("deal-finder metadata-driven shell workflow chain", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("resolves metadata-declared create/detail surfaces and persists + rehydrates campaign bounds", async () => {
    apiMocks.resolveArtifactSurface.mockImplementation(async (path: string) => {
      if (path === "/app/campaigns/new") {
        return {
          surface: {
            id: "surface-campaign-create",
            route: "/app/campaigns/new",
            title: "Create Campaign",
            renderer: { type: "generic_editor", payload: { shell_renderer_key: "campaign_map_workflow", mode: "create" } },
          },
          artifact: { id: "artifact-1", slug: "app.deal-finder" },
          params: {},
        };
      }
      if (path === "/app/campaigns/camp-1") {
        return {
          surface: {
            id: "surface-campaign-detail",
            route: "/app/campaigns/:id",
            title: "Campaign Detail",
            renderer: {
              type: "generic_dashboard",
              payload: { shell_renderer_key: "campaign_map_workflow", mode: "detail", campaign_id_param: "id" },
            },
          },
          artifact: { id: "artifact-1", slug: "app.deal-finder" },
          params: { id: "camp-1" },
        };
      }
      throw new Error(`unexpected resolve path ${path}`);
    });

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
    apiMocks.getCampaign.mockResolvedValue({
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
      metadata: {
        monitoring_mode: "rectangle_box_selection",
        monitoring_bounds: {
          min_lng: -90.31,
          min_lat: 38.58,
          max_lng: -90.21,
          max_lat: 38.69,
        },
      },
    });

    render(
      <MemoryRouter initialEntries={["/w/ws-1/a/campaigns/new"]}>
        <Routes>
          <Route
            path="/w/:workspaceId/a/*"
            element={
              <ArtifactSurfaceRoutePage
                workspaceId="ws-1"
                workspaceRole="admin"
                canManageArticleLifecycle
                canCreate
              />
            }
          />
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
    await waitFor(() =>
      expect(apiMocks.resolveArtifactSurface).toHaveBeenCalledWith("/app/campaigns/camp-1")
    );

    const savedPayload = apiMocks.createCampaign.mock.calls[0][0];
    expect(savedPayload.metadata.monitoring_mode).toBe("rectangle_box_selection");
    expect(savedPayload.metadata.monitoring_bounds.min_lng).toBeTypeOf("number");
    expect(savedPayload.metadata.monitoring_bounds.max_lng).toBeTypeOf("number");

    expect(await screen.findByTestId("campaign-map-selection-rect")).toBeInTheDocument();
    const readout = await screen.findByTestId("campaign-bounds-readout");
    expect(readout.textContent).toContain("-90.31");
    expect(readout.textContent).toContain("38.69");
  });
});

