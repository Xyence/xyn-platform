import { MemoryRouter } from "react-router-dom";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import WorkspacesPage from "./WorkspacesPage";

const mockNavigate = vi.hoisted(() => vi.fn());
const apiMocks = vi.hoisted(() => ({
  listWorkspaces: vi.fn(),
  updateWorkspace: vi.fn(),
  createWorkspace: vi.fn(),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock("../../api/xyn", () => apiMocks);

describe("WorkspacesPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockNavigate.mockReset();
    apiMocks.listWorkspaces.mockResolvedValue({
      workspaces: [
        {
          id: "ws-operator",
          slug: "operator",
          name: "Operator",
          org_name: "Operator",
          kind: "operator",
          lifecycle_stage: "customer",
          parent_workspace_id: null,
          metadata: {},
          role: "admin",
          termination_authority: true,
          status: "active",
        },
        {
          id: "ws-customer",
          slug: "acme-grid",
          name: "Acme Grid",
          org_name: "Acme Grid",
          kind: "customer",
          lifecycle_stage: "prospect",
          parent_workspace_id: "ws-operator",
          metadata: { note: "seeded" },
          role: "admin",
          termination_authority: true,
          status: "active",
        },
      ],
    });
    apiMocks.updateWorkspace.mockResolvedValue({
      workspace: {
        id: "ws-customer",
        slug: "acme-grid",
        name: "Acme Grid",
        org_name: "Acme Grid Utilities",
        kind: "customer",
        lifecycle_stage: "customer",
        parent_workspace_id: "ws-operator",
        metadata: { note: "updated" },
        role: "admin",
        termination_authority: true,
        status: "active",
      },
    });
    apiMocks.createWorkspace.mockResolvedValue({
      workspace: {
        id: "ws-new",
        slug: "new-ws",
        name: "New Workspace",
        role: "admin",
        termination_authority: true,
      },
    });
  });

  it("renders and saves workspace lifecycle profile fields", async () => {
    render(
      <MemoryRouter initialEntries={["/app/workspaces?tab=management"]}>
        <WorkspacesPage activeWorkspaceId="ws-operator" activeWorkspaceName="Operator" canWorkspaceAdmin canManageWorkspaces />
      </MemoryRouter>
    );

    expect(await screen.findByText("Workspace profile")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Acme Grid/i }));

    const orgNameInput = await screen.findByLabelText("Org name");
    fireEvent.change(orgNameInput, { target: { value: "Acme Grid Utilities" } });
    const saveButton = screen.getByRole("button", { name: "Save workspace" });
    const profileForm = saveButton.closest("form");
    expect(profileForm).not.toBeNull();
    const formScope = within(profileForm as HTMLFormElement);
    fireEvent.change(formScope.getByLabelText("Lifecycle stage"), { target: { value: "customer" } });
    fireEvent.change(formScope.getByLabelText("Metadata (JSON)"), { target: { value: '{"note":"updated"}' } });
    fireEvent.click(screen.getByRole("button", { name: "Save workspace" }));

    await waitFor(() =>
      expect(apiMocks.updateWorkspace).toHaveBeenCalledWith(
        "ws-customer",
        expect.objectContaining({
          org_name: "Acme Grid Utilities",
          lifecycle_stage: "customer",
          kind: "customer",
          parent_workspace_id: "ws-operator",
          metadata: { note: "updated" },
        })
      )
    );
  });
});
