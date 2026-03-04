import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PeopleRolesPage from "./PeopleRolesPage";

const apiMocks = vi.hoisted(() => ({
  listWorkspaceMemberships: vi.fn(),
  listIdentities: vi.fn(),
  createWorkspaceMembership: vi.fn(),
  updateWorkspaceMembership: vi.fn(),
}));

const pushMock = vi.hoisted(() => vi.fn());

vi.mock("../../api/xyn", () => apiMocks);
vi.mock("../state/notificationsStore", () => ({
  useNotifications: () => ({ push: pushMock }),
}));

describe("PeopleRolesPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.listWorkspaceMemberships.mockResolvedValue({ memberships: [] });
    apiMocks.listIdentities.mockResolvedValue({
      identities: [
        {
          id: "ident-1",
          provider: "oidc",
          issuer: "https://issuer",
          subject: "subject-1",
          email: "person@example.com",
          display_name: "Person One",
        },
      ],
    });
    apiMocks.createWorkspaceMembership.mockResolvedValue({ id: "membership-1" });
    apiMocks.updateWorkspaceMembership.mockResolvedValue(undefined);
  });

  it("opens and closes the add member modal", async () => {
    render(<PeopleRolesPage workspaceId="ws-1" canAdmin />);

    await screen.findByText("No members in workspace.");
    await userEvent.click(screen.getByRole("button", { name: "Add member" }));

    const dialog = screen.getByRole("dialog", { name: /add member/i });
    expect(dialog).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: /add member/i })).not.toBeInTheDocument();
    });
  });

  it("submits add member and closes modal", async () => {
    render(<PeopleRolesPage workspaceId="ws-1" canAdmin />);

    await screen.findByText("No members in workspace.");
    await userEvent.click(screen.getByRole("button", { name: "Add member" }));
    const dialog = screen.getByRole("dialog", { name: /add member/i });
    await userEvent.selectOptions(within(dialog).getByLabelText("Identity"), "ident-1");
    await userEvent.selectOptions(within(dialog).getByLabelText("Role"), "admin");
    await userEvent.click(within(dialog).getByRole("button", { name: "Add member" }));

    await waitFor(() => {
      expect(apiMocks.createWorkspaceMembership).toHaveBeenCalledWith(
        "ws-1",
        expect.objectContaining({ user_identity_id: "ident-1", role: "admin", termination_authority: false })
      );
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: /add member/i })).not.toBeInTheDocument();
    });
    expect(pushMock).toHaveBeenCalledWith(expect.objectContaining({ level: "success", title: "Member added" }));
  });

  it("keeps modal open when add member fails", async () => {
    apiMocks.createWorkspaceMembership.mockRejectedValue(new Error("already a member"));

    render(<PeopleRolesPage workspaceId="ws-1" canAdmin />);

    await screen.findByText("No members in workspace.");
    await userEvent.click(screen.getByRole("button", { name: "Add member" }));
    const dialog = screen.getByRole("dialog", { name: /add member/i });
    await userEvent.selectOptions(within(dialog).getByLabelText("Identity"), "ident-1");
    await userEvent.click(within(dialog).getByRole("button", { name: "Add member" }));

    expect(await screen.findByText("This identity is already a member of this workspace.")).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: /add member/i })).toBeInTheDocument();
    expect(pushMock).toHaveBeenCalledWith(expect.objectContaining({ level: "error", title: "Add member failed" }));
  });
});
