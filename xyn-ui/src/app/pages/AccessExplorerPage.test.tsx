import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AccessExplorerPage from "./AccessExplorerPage";

const apiMocks = vi.hoisted(() => ({
  getAccessRegistry: vi.fn(),
  searchAccessUsers: vi.fn(),
  getAccessUserRoles: vi.fn(),
  getAccessUserEffective: vi.fn(),
  getAccessRoleDetail: vi.fn(),
}));

vi.mock("../../api/xyn", async () => {
  const actual = await vi.importActual<typeof import("../../api/xyn")>("../../api/xyn");
  return {
    ...actual,
    getAccessRegistry: apiMocks.getAccessRegistry,
    searchAccessUsers: apiMocks.searchAccessUsers,
    getAccessUserRoles: apiMocks.getAccessUserRoles,
    getAccessUserEffective: apiMocks.getAccessUserEffective,
    getAccessRoleDetail: apiMocks.getAccessRoleDetail,
  };
});

vi.mock("@xyflow/react", () => ({
  __esModule: true,
  default: ({ onNodeClick }: { onNodeClick?: (_event: unknown, node: unknown) => void }) => (
    <div>
      <button onClick={() => onNodeClick?.(null, { id: "perm:view_platform", data: { label: "view_platform" } })}>Mock Permission Node</button>
    </div>
  ),
  ReactFlow: ({ onNodeClick }: { onNodeClick?: (_event: unknown, node: unknown) => void }) => (
    <div>
      <button onClick={() => onNodeClick?.(null, { id: "perm:view_platform", data: { label: "view_platform" } })}>Mock Permission Node</button>
    </div>
  ),
  Background: () => <div />, 
  Controls: () => <div />,
  Panel: ({ children }: { children: unknown }) => <div>{children as any}</div>,
}));

describe("AccessExplorerPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.getAccessRegistry.mockResolvedValue({
      permissions: [
        { key: "view_platform", name: "View Platform", description: "desc", category: "platform", isDangerous: true },
        { key: "manage_users", name: "Manage Users", description: "desc", category: "access", isDangerous: true },
      ],
      roles: [
        { id: "platform_admin", name: "Platform Admin", tier: 1 },
        { id: "platform_operator", name: "Platform Operator", tier: 3 },
      ],
      rolePermissions: [
        { roleId: "platform_operator", permissionKey: "view_platform", scope: null, effect: "allow" },
      ],
    });
    apiMocks.searchAccessUsers.mockResolvedValue({
      users: [{ id: "u1", name: "Dev User", email: "dev@example.com" }],
    });
    apiMocks.getAccessUserRoles.mockResolvedValue({
      roles: [{ roleId: "platform_operator", roleName: "Platform Operator", scope: { scope_kind: "platform" } }],
    });
    apiMocks.getAccessUserEffective.mockResolvedValue({
      effective: [
        {
          permissionKey: "view_platform",
          scope: { scope_kind: "platform" },
          effect: "allow",
          sources: [
            {
              viaRoleId: "platform_operator",
              viaRoleName: "Platform Operator",
              roleScope: { scope_kind: "platform" },
              permScope: {},
              mergedScope: { scope_kind: "platform" },
            },
          ],
        },
      ],
      summary: { totalEffective: 1, categories: [{ category: "platform", count: 1 }] },
    });
    apiMocks.getAccessRoleDetail.mockResolvedValue({
      role: { id: "platform_operator", name: "Platform Operator", tier: 3 },
      permissions: [{ permissionKey: "view_platform", effect: "allow", scope: null }],
    });
  });

  it("selecting a user loads roles and effective permissions", async () => {
    render(<AccessExplorerPage />);

    await screen.findByText("Dev User");
    await userEvent.click(screen.getByRole("button", { name: /Dev User/i }));

    await waitFor(() => {
      expect(apiMocks.getAccessUserRoles).toHaveBeenCalledWith("u1");
      expect(apiMocks.getAccessUserEffective).toHaveBeenCalledWith("u1");
    });
    expect(await screen.findByText("view_platform")).toBeInTheDocument();
  });

  it("expand explain trace renders sources", async () => {
    render(<AccessExplorerPage />);

    await screen.findByText("Dev User");
    await userEvent.click(screen.getByRole("button", { name: /Dev User/i }));
    await screen.findByText("view_platform");

    await userEvent.click(screen.getByText("view_platform"));
    expect(await screen.findByText(/Role scope:/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Platform Operator/i).length).toBeGreaterThan(0);
  });

  it("graph permission click can jump to effective filter", async () => {
    render(<AccessExplorerPage />);

    await screen.findByText("Dev User");
    await userEvent.click(screen.getByRole("button", { name: /Dev User/i }));
    await userEvent.click(screen.getByRole("button", { name: "Graph" }));
    await userEvent.click(screen.getByRole("button", { name: "Mock Permission Node" }));
    await userEvent.click(screen.getByRole("button", { name: "Show effective traces" }));

    expect(screen.getByRole("button", { name: "Effective Permissions" })).toBeInTheDocument();
    expect((screen.getByPlaceholderText("filter permission") as HTMLInputElement).value).toBe("view_platform");
  });
});
