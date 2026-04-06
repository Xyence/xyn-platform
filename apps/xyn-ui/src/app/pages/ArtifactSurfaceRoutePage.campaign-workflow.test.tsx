import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ArtifactSurfaceRoutePage from "./ArtifactSurfaceRoutePage";

const apiMocks = vi.hoisted(() => ({
  resolveArtifactSurface: vi.fn(),
}));

vi.mock("../../api/xyn", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/xyn")>();
  return {
    ...actual,
    resolveArtifactSurface: (...args: unknown[]) => apiMocks.resolveArtifactSurface(...args),
    createCampaign: vi.fn(),
    getCampaign: vi.fn(),
    updateCampaign: vi.fn(),
  };
});

describe("ArtifactSurfaceRoutePage campaign workflow binding", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders shell-hosted campaign map workflow for campaigns/new surface", async () => {
    apiMocks.resolveArtifactSurface.mockResolvedValue({
      surface: {
        id: "surface-campaign-create",
        route: "/app/campaigns/new",
        title: "Create Campaign",
        renderer: { type: "generic_editor", payload: { shell_renderer_key: "campaign_map_workflow", mode: "create" } },
      },
      artifact: { id: "artifact-1", slug: "app.deal-finder" },
      params: {},
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

    expect(await screen.findByText("Create Campaign")).toBeInTheDocument();
    expect(await screen.findByTestId("campaign-map-canvas")).toBeInTheDocument();
  });

  it("shows controlled error when surface declares unknown shell renderer key", async () => {
    apiMocks.resolveArtifactSurface.mockResolvedValue({
      surface: {
        id: "surface-unknown",
        route: "/app/campaigns/new",
        title: "Create Campaign",
        renderer: { type: "generic_editor", payload: { shell_renderer_key: "unknown_renderer" } },
      },
      artifact: { id: "artifact-1", slug: "app.deal-finder" },
      params: {},
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

    expect(await screen.findByText(/Unknown shell renderer key/i)).toBeInTheDocument();
    expect(screen.getByText(/unknown_renderer/i)).toBeInTheDocument();
  });

  it("redirects legacy campaign dashboard surfaces into modern campaign list workbench panel", async () => {
    apiMocks.resolveArtifactSurface.mockResolvedValue({
      surface: {
        id: "surface-campaign-list",
        route: "/app/campaigns",
        title: "Campaigns",
        renderer: { type: "generic_dashboard" },
      },
      artifact: { id: "artifact-1", slug: "app.deal-finder" },
      params: {},
    });

    render(
      <MemoryRouter initialEntries={["/w/ws-1/a/campaigns"]}>
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
          <Route path="/w/:workspaceId/workbench" element={<div>Workbench Route</div>} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText("Workbench Route")).toBeInTheDocument();
  });

  it("blocks unmapped compatibility dashboard surfaces with modern unsupported message", async () => {
    apiMocks.resolveArtifactSurface.mockResolvedValue({
      surface: {
        id: "surface-sources",
        route: "/app/sources",
        title: "Sources",
        renderer: { type: "generic_dashboard" },
      },
      artifact: { id: "artifact-1", slug: "app.deal-finder" },
      params: {},
    });

    render(
      <MemoryRouter initialEntries={["/w/ws-1/a/sources"]}>
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

    expect(await screen.findByText(/not supported in the current workbench ui/i)).toBeInTheDocument();
    expect(screen.queryByText(/Renderer is declared but no compatible UI mapping exists in this build\./i)).not.toBeInTheDocument();
  });
});
