import { MemoryRouter } from "react-router-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ArtifactsRegistryPage from "./ArtifactsRegistryPage";

const mockNavigate = vi.hoisted(() => vi.fn());
const apiMocks = vi.hoisted(() => ({
  listWorkspaceArtifacts: vi.fn(),
  uninstallWorkspaceArtifact: vi.fn(),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock("../../api/xyn", () => apiMocks);

describe("ArtifactsRegistryPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockNavigate.mockReset();
    apiMocks.listWorkspaceArtifacts.mockImplementation(async (workspaceId: string) => {
      if (workspaceId === "ws-1") {
        return {
          artifacts: [
            {
              binding_id: "b-1",
              artifact_id: "a-1",
              name: "Artifact A",
              title: "Artifact A",
              kind: "article",
              description: "First",
              enabled: true,
              installed_state: "installed",
              manifest_summary: { roles: ["article"], surfaces: { nav: [], manage: [], docs: [] } },
              updated_at: "2026-03-01T00:00:00Z",
            },
          ],
        };
      }
      return {
        artifacts: [
          {
            binding_id: "b-2",
            artifact_id: "a-2",
            name: "Artifact B",
            title: "Artifact B",
            kind: "workflow",
            description: "Second",
            enabled: true,
            installed_state: "installed",
            manifest_summary: {
              roles: ["module"],
              surfaces: { nav: [], manage: [{ label: "Settings", path: "/apps/hello/manage", order: 100 }], docs: [] },
            },
            updated_at: "2026-03-01T00:00:00Z",
          },
        ],
      };
    });
    apiMocks.uninstallWorkspaceArtifact.mockResolvedValue({
      deleted: true,
      artifact: {
        binding_id: "b-1",
        artifact_id: "a-1",
        name: "Artifact A",
        title: "Artifact A",
        kind: "article",
        enabled: true,
        installed_state: "installed",
      },
    });
  });

  it("updates list and workspace context when workspace changes", async () => {
    const { rerender } = render(
      <MemoryRouter>
        <ArtifactsRegistryPage workspaceId="ws-1" workspaceName="Workspace One" />
      </MemoryRouter>
    );

    expect(await screen.findByText("Artifact A")).toBeInTheDocument();
    expect(screen.queryByText("Artifact B")).not.toBeInTheDocument();
    expect(screen.getByText("Workspace: Workspace One")).toBeInTheDocument();
    expect(screen.getByText("Scope: Workspace")).toBeInTheDocument();

    rerender(
      <MemoryRouter>
        <ArtifactsRegistryPage workspaceId="ws-2" workspaceName="Workspace Two" />
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByText("Artifact B")).toBeInTheDocument());
    expect(screen.queryByText("Artifact A")).not.toBeInTheDocument();
    expect(screen.getByText("Workspace: Workspace Two")).toBeInTheDocument();
  });

  it("shows workspace empty state message", async () => {
    apiMocks.listWorkspaceArtifacts.mockResolvedValueOnce({ artifacts: [] });

    render(
      <MemoryRouter>
        <ArtifactsRegistryPage workspaceId="ws-empty" workspaceName="Empty Workspace" />
      </MemoryRouter>
    );

    expect(await screen.findByText("No artifacts installed in this workspace.")).toBeInTheDocument();
    expect(screen.getByText("Open Catalog to browse and install artifacts.")).toBeInTheDocument();
  });

  it("navigates to manage surface when one is declared", async () => {
    render(
      <MemoryRouter>
        <ArtifactsRegistryPage workspaceId="ws-2" workspaceName="Workspace Two" />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByText("Artifact B"));
    expect(mockNavigate).toHaveBeenCalledWith("/apps/hello/manage");
  });

  it("opens fallback details for non-article artifacts without manage surface", async () => {
    apiMocks.listWorkspaceArtifacts.mockResolvedValueOnce({
      artifacts: [
        {
          binding_id: "b-9",
          artifact_id: "a-9",
          name: "Artifact C",
          title: "Artifact C",
          kind: "module",
          description: "Third",
          enabled: true,
          installed_state: "installed",
          manifest_summary: { roles: ["module"], surfaces: { nav: [], manage: [], docs: [{ label: "Docs", path: "/apps/module/docs" }] } },
          updated_at: "2026-03-01T00:00:00Z",
        },
      ],
    });

    render(
      <MemoryRouter>
        <ArtifactsRegistryPage workspaceId="ws-3" workspaceName="Workspace Three" />
      </MemoryRouter>
    );

    fireEvent.click(await screen.findByText("Artifact C"));
    expect(await screen.findByText("No management UI provided.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Docs" })).toHaveAttribute("href", "/apps/module/docs");
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});
