import { MemoryRouter, Route, Routes } from "react-router-dom";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ApplicationNotificationSettingsPage from "./ApplicationNotificationSettingsPage";

const apiMocks = vi.hoisted(() => ({
  listNotificationDeliveryTargets: vi.fn(),
  createNotificationDeliveryTarget: vi.fn(),
  setNotificationDeliveryTargetEnabled: vi.fn(),
  removeNotificationDeliveryTarget: vi.fn(),
  getNotificationDeliveryPreference: vi.fn(),
  setNotificationDeliveryPreference: vi.fn(),
}));

vi.mock("../../api/xyn", () => apiMocks);

describe("ApplicationNotificationSettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.listNotificationDeliveryTargets.mockResolvedValue({
      targets: [
        {
          id: "t1",
          owner_id: "u1",
          channel: "email",
          address: "one@example.com",
          enabled: true,
          verification_status: "verified",
          is_primary: true,
          created_at: "2026-03-18T10:00:00Z",
          updated_at: "2026-03-18T10:00:00Z",
        },
      ],
    });
    apiMocks.getNotificationDeliveryPreference.mockResolvedValue({
      preference: {
        source_app_key: "",
        in_app_enabled: true,
        email_enabled: true,
      },
    });
    apiMocks.createNotificationDeliveryTarget.mockResolvedValue({
      target: {
        id: "t2",
        owner_id: "u1",
        channel: "email",
        address: "two@example.com",
        enabled: true,
        verification_status: "pending",
        is_primary: false,
        created_at: "2026-03-18T11:00:00Z",
        updated_at: "2026-03-18T11:00:00Z",
      },
    });
    apiMocks.setNotificationDeliveryTargetEnabled.mockResolvedValue({
      target: {
        id: "t1",
        owner_id: "u1",
        channel: "email",
        address: "one@example.com",
        enabled: false,
        verification_status: "verified",
        is_primary: true,
        created_at: "2026-03-18T10:00:00Z",
        updated_at: "2026-03-18T10:01:00Z",
      },
    });
    apiMocks.removeNotificationDeliveryTarget.mockResolvedValue({ status: "deleted" });
    apiMocks.setNotificationDeliveryPreference.mockResolvedValue({
      preference: {
        source_app_key: "",
        in_app_enabled: false,
        email_enabled: false,
      },
    });
  });

  const workspaceId = "ws-1";
  const workspaceRole = "contributor";

  function renderPage(path = "/app/notifications/settings") {
    return render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route
            path="/app/notifications/settings"
            element={<ApplicationNotificationSettingsPage workspaceId={workspaceId} workspaceRole={workspaceRole} />}
          />
        </Routes>
      </MemoryRouter>
    );
  }

  async function waitForSettled() {
    await waitFor(() => expect(screen.getByRole("button", { name: "Refresh" })).not.toBeDisabled());
  }

  it("renders target list", async () => {
    renderPage();
    expect(await screen.findByText("one@example.com")).toBeInTheDocument();
    expect(screen.getByText(/Verification:\s*Verified/i)).toBeInTheDocument();
    await waitForSettled();
  });

  it("adds a target", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("one@example.com");
    await waitForSettled();
    await user.type(screen.getByLabelText("Email address"), "two@example.com");
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Add target" }));
    });
    await waitFor(() =>
      expect(apiMocks.createNotificationDeliveryTarget).toHaveBeenCalledWith({
        address: "two@example.com",
        enabled: true,
        is_primary: false,
        workspace_id: workspaceId,
      })
    );
    await waitForSettled();
  });

  it("enables or disables a target", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("one@example.com");
    await waitForSettled();
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Disable" }));
    });
    await waitFor(() => expect(apiMocks.setNotificationDeliveryTargetEnabled).toHaveBeenCalledWith("t1", false, workspaceId));
    await waitForSettled();
  });

  it("updates preferences via toggles", async () => {
    const user = userEvent.setup();
    renderPage();
    const inAppToggle = await screen.findByRole("checkbox", { name: "In-app notifications enabled" });
    await waitForSettled();
    await act(async () => {
      await user.click(inAppToggle);
    });
    await waitFor(() =>
      expect(apiMocks.setNotificationDeliveryPreference).toHaveBeenCalledWith({
        source_app_key: "",
        in_app_enabled: false,
        email_enabled: true,
        workspace_id: workspaceId,
      })
    );
    await waitForSettled();
  });

  it("shows empty state", async () => {
    apiMocks.listNotificationDeliveryTargets.mockResolvedValueOnce({ targets: [] });
    renderPage();
    expect(await screen.findByText("No notification targets configured yet.")).toBeInTheDocument();
  });

  it("shows error state", async () => {
    apiMocks.listNotificationDeliveryTargets.mockRejectedValueOnce(new Error("fetch failed"));
    renderPage();
    expect(await screen.findByText("Request failed")).toBeInTheDocument();
    expect(screen.getByText("fetch failed")).toBeInTheDocument();
  });

  it("shows missing workspace error and disables actions", async () => {
    render(
      <MemoryRouter initialEntries={["/app/notifications/settings"]}>
        <Routes>
          <Route path="/app/notifications/settings" element={<ApplicationNotificationSettingsPage workspaceId="" workspaceRole="admin" />} />
        </Routes>
      </MemoryRouter>
    );
    expect(await screen.findByText("Workspace context is required to manage notification settings.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add target" })).toBeDisabled();
  });

  it("disables mutation controls when read-only", async () => {
    render(
      <MemoryRouter initialEntries={["/app/notifications/settings"]}>
        <Routes>
          <Route
            path="/app/notifications/settings"
            element={<ApplicationNotificationSettingsPage workspaceId={workspaceId} workspaceRole="reader" />}
          />
        </Routes>
      </MemoryRouter>
    );
    await screen.findByText("one@example.com");
    await waitFor(() => expect(screen.getByRole("button", { name: "Refresh" })).not.toBeDisabled());
    expect(screen.getByRole("button", { name: "Add target" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Disable" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove" })).toBeDisabled();
  });
});
