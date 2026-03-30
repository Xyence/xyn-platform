import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LinkedDevSessionBanner from "./LinkedDevSessionBanner";

const navigateMock = vi.hoisted(() => vi.fn());
const apiMocks = vi.hoisted(() => ({
  getWorkspaceLinkedChangeSession: vi.fn(),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock("../../../api/xyn", async () => {
  const actual = await vi.importActual<typeof import("../../../api/xyn")>("../../../api/xyn");
  return {
    ...actual,
    getWorkspaceLinkedChangeSession: apiMocks.getWorkspaceLinkedChangeSession,
  };
});

describe("LinkedDevSessionBanner", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    navigateMock.mockReset();
  });

  it("shows banner for active linked session and navigates to composer session route", async () => {
    apiMocks.getWorkspaceLinkedChangeSession.mockResolvedValue({
      linked_session: {
        workspace_id: "ws-1",
        application_id: "app-1",
        application_name: "Deal Finder",
        solution_change_session_id: "scs-1",
        session_title: "Campaign UX update",
        status: "planned",
        execution_status: "preview_ready",
      },
    });
    render(
      <MemoryRouter>
        <LinkedDevSessionBanner workspaceId="ws-1" />
      </MemoryRouter>,
    );
    expect(await screen.findByText(/linked to an in-flight change session/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Resume session/i }));
    expect(navigateMock).toHaveBeenCalledWith(
      "/w/ws-1/workbench?panel=composer_detail&application_id=app-1&solution_change_session_id=scs-1"
    );
  });

  it("hides banner when no linkage exists", async () => {
    apiMocks.getWorkspaceLinkedChangeSession.mockResolvedValue({ linked_session: null });
    render(
      <MemoryRouter>
        <LinkedDevSessionBanner workspaceId="ws-1" />
      </MemoryRouter>,
    );
    await waitFor(() => expect(apiMocks.getWorkspaceLinkedChangeSession).toHaveBeenCalled());
    expect(screen.queryByText(/linked to an in-flight change session/i)).not.toBeInTheDocument();
  });

  it("hides banner when linked session payload is incomplete", async () => {
    apiMocks.getWorkspaceLinkedChangeSession.mockResolvedValue({
      linked_session: {
        workspace_id: "ws-1",
        application_id: "",
        solution_change_session_id: "",
      },
    });
    render(
      <MemoryRouter>
        <LinkedDevSessionBanner workspaceId="ws-1" />
      </MemoryRouter>,
    );
    await waitFor(() => expect(apiMocks.getWorkspaceLinkedChangeSession).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: /Resume session/i })).not.toBeInTheDocument();
  });

  it("hides banner for finalized or archived sessions (API returns null)", async () => {
    apiMocks.getWorkspaceLinkedChangeSession.mockResolvedValue({ linked_session: null });
    render(
      <MemoryRouter>
        <LinkedDevSessionBanner workspaceId="ws-1" />
      </MemoryRouter>,
    );
    await waitFor(() => expect(apiMocks.getWorkspaceLinkedChangeSession).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: /Resume session/i })).not.toBeInTheDocument();
  });
});
