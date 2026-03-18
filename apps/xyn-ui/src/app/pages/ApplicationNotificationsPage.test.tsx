import { MemoryRouter, Route, Routes } from "react-router-dom";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ApplicationNotificationsPage from "./ApplicationNotificationsPage";

const apiMocks = vi.hoisted(() => ({
  listApplicationNotifications: vi.fn(),
  getApplicationNotificationUnreadCount: vi.fn(),
  markApplicationNotificationRead: vi.fn(),
  markAllApplicationNotificationsRead: vi.fn(),
}));

vi.mock("../../api/xyn", () => apiMocks);

describe("ApplicationNotificationsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.listApplicationNotifications.mockResolvedValue({
      notifications: [
        {
          notification_id: "n1",
          recipient_row_id: "r1",
          source_app_key: "portfolio-ops",
          category: "application",
          notification_type_key: "status_update",
          title: "Run completed",
          summary: "Validation completed with warnings",
          payload: {},
          deep_link: "/app/runs/run-1",
          source_entity_type: "run",
          source_entity_id: "run-1",
          source_metadata: {},
          workspace_id: null,
          unread: true,
          read_at: null,
          created_at: "2026-03-18T12:00:00Z",
        },
      ],
      count: 1,
      limit: 100,
      offset: 0,
      unread_count: 1,
    });
    apiMocks.getApplicationNotificationUnreadCount.mockResolvedValue({ unread_count: 1 });
    apiMocks.markApplicationNotificationRead.mockResolvedValue({ notification_id: "n1", unread: false, unread_count: 0 });
    apiMocks.markAllApplicationNotificationsRead.mockResolvedValue({ updated: 1, unread_count: 0 });
  });

  function renderPage(path = "/app/notifications") {
    return render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/app/notifications" element={<ApplicationNotificationsPage />} />
          <Route path="/app/runs/run-1" element={<div data-testid="run-destination">Run Destination</div>} />
        </Routes>
      </MemoryRouter>
    );
  }

  it("renders backend feed rows and unread state", async () => {
    renderPage();
    expect(await screen.findByText("Run completed")).toBeInTheDocument();
    expect(screen.getByText("Unread 1")).toBeInTheDocument();
    expect(screen.getByText("Validation completed with warnings")).toBeInTheDocument();
  });

  it("marks one notification as read", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Run completed");
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Mark read" }));
    });
    await waitFor(() => expect(apiMocks.markApplicationNotificationRead).toHaveBeenCalledWith("n1"));
    expect(await screen.findByText("Unread 0")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Refresh" })).not.toBeDisabled());
  });

  it("marks all notifications as read", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Run completed");
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "Mark all read" }));
    });
    await waitFor(() => expect(apiMocks.markAllApplicationNotificationsRead).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("Unread 0")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Refresh" })).not.toBeDisabled());
  });

  it("shows empty state", async () => {
    apiMocks.listApplicationNotifications.mockResolvedValueOnce({
      notifications: [],
      count: 0,
      limit: 100,
      offset: 0,
      unread_count: 0,
    });
    apiMocks.getApplicationNotificationUnreadCount.mockResolvedValueOnce({ unread_count: 0 });
    renderPage();
    expect(await screen.findByText("No application notifications yet.")).toBeInTheDocument();
  });
});
