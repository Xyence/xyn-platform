import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AccessControlPage from "./AccessControlPage";

const apiMocks = vi.hoisted(() => ({
  listIdentities: vi.fn(),
  listRoleBindings: vi.fn(),
  createRoleBinding: vi.fn(),
  deleteRoleBinding: vi.fn(),
}));

vi.mock("../../api/xyn", () => apiMocks);

describe("AccessControlPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.listIdentities.mockResolvedValue({
      identities: [
        {
          id: "u1",
          provider: "oidc",
          issuer: "https://issuer",
          subject: "sub-1",
          email: "user@example.com",
          display_name: "User One",
        },
      ],
    });
    apiMocks.listRoleBindings.mockResolvedValue({ role_bindings: [] });
    apiMocks.createRoleBinding.mockResolvedValue({ id: "rb1" });
    apiMocks.deleteRoleBinding.mockResolvedValue(undefined);
  });

  it("defaults to users tab when tab param is missing", async () => {
    render(
      <MemoryRouter initialEntries={["/app/platform/access-control"]}>
        <Routes>
          <Route path="/app/platform/access-control" element={<AccessControlPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByText("Access Control")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create role" })).not.toBeInTheDocument();
    expect(await screen.findByRole("tab", { name: "Users" })).toHaveAttribute("aria-selected", "true");
  });

  it("falls back to users for invalid tab param", async () => {
    render(
      <MemoryRouter initialEntries={["/app/platform/access-control?tab=invalid"]}>
        <Routes>
          <Route path="/app/platform/access-control" element={<AccessControlPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByRole("tab", { name: "Users" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("button", { name: "Create role" })).not.toBeInTheDocument();
  });

  it("shows create role button only when roles tab is active", async () => {
    render(
      <MemoryRouter initialEntries={["/app/platform/access-control?tab=users"]}>
        <Routes>
          <Route path="/app/platform/access-control" element={<AccessControlPage />} />
        </Routes>
      </MemoryRouter>
    );

    expect(await screen.findByRole("tab", { name: "Users" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("button", { name: "Create role" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: "Roles" }));
    expect(await screen.findByRole("button", { name: "Create role" })).toBeInTheDocument();
  });
});
