import { MemoryRouter } from "react-router-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ArtifactsLibraryPage from "./ArtifactsLibraryPage";

const mockNavigate = vi.hoisted(() => vi.fn());
const apiMocks = vi.hoisted(() => ({
  listArtifactsCatalog: vi.fn(),
  installWorkspaceArtifact: vi.fn(),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock("../../api/xyn", () => apiMocks);

describe("ArtifactsLibraryPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockNavigate.mockReset();
    apiMocks.listArtifactsCatalog.mockResolvedValue({
      artifacts: [
        {
          id: "hello-id",
          slug: "hello-app",
          title: "Hello App",
          kind: "module",
          description: "Kernel-loaded artifact for Hello App",
          version: "1.0.0",
          updated_at: "2026-03-01T00:00:00Z",
          manifest_summary: {
            roles: ["api_router", "ui_mount"],
            surfaces: {
              nav: [{ label: "Hello", path: "/apps/hello", order: 900 }],
              manage: [{ label: "Settings", path: "/apps/hello/manage", order: 100 }],
              docs: [{ label: "Docs", path: "/apps/hello/docs", order: 1000 }],
            },
          },
        },
      ],
    });
    apiMocks.installWorkspaceArtifact.mockResolvedValue({
      artifact: {
        binding_id: "b-1",
        artifact_id: "hello-id",
        title: "Hello App",
      },
      created: true,
    });
  });

  it("renders catalog list and installs selected artifact to active workspace", async () => {
    render(
      <MemoryRouter>
        <ArtifactsLibraryPage workspaceId="ws-1" workspaceName="Platform Builder" />
      </MemoryRouter>
    );

    expect(await screen.findByRole("button", { name: /Install to Workspace: Platform Builder/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Install to Workspace: Platform Builder" }));

    await waitFor(() =>
      expect(apiMocks.installWorkspaceArtifact).toHaveBeenCalledWith("ws-1", {
        artifact_id: "hello-app",
        enabled: true,
      })
    );
    expect(screen.getByRole("link", { name: "Docs" })).toHaveAttribute("href", "/apps/hello/docs");
  });
});
