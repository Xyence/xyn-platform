import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SolutionDetailPanel, SolutionListPanel } from "./SolutionPanels";

const apiMocks = vi.hoisted(() => ({
  listApplications: vi.fn(),
  getApplication: vi.fn(),
  listApplicationArtifactMemberships: vi.fn(),
  listArtifacts: vi.fn(),
  listSolutionChangeSessions: vi.fn(),
  createSolutionChangeSession: vi.fn(),
  updateSolutionChangeSession: vi.fn(),
  generateSolutionChangePlan: vi.fn(),
  stageSolutionChangeApply: vi.fn(),
  prepareSolutionChangePreview: vi.fn(),
  validateSolutionChangeSession: vi.fn(),
  upsertApplicationArtifactMembership: vi.fn(),
}));

vi.mock("../../../api/xyn", () => ({
  listApplications: apiMocks.listApplications,
  getApplication: apiMocks.getApplication,
  listApplicationArtifactMemberships: apiMocks.listApplicationArtifactMemberships,
  listArtifacts: apiMocks.listArtifacts,
  listSolutionChangeSessions: apiMocks.listSolutionChangeSessions,
  createSolutionChangeSession: apiMocks.createSolutionChangeSession,
  updateSolutionChangeSession: apiMocks.updateSolutionChangeSession,
  generateSolutionChangePlan: apiMocks.generateSolutionChangePlan,
  stageSolutionChangeApply: apiMocks.stageSolutionChangeApply,
  prepareSolutionChangePreview: apiMocks.prepareSolutionChangePreview,
  validateSolutionChangeSession: apiMocks.validateSolutionChangeSession,
  upsertApplicationArtifactMembership: apiMocks.upsertApplicationArtifactMembership,
}));

describe("Solution panels", () => {
  it("renders solution list in panel and opens solution detail panel", async () => {
    const onOpenPanel = vi.fn();
    apiMocks.listApplications.mockResolvedValue({
      applications: [
        {
          id: "app-1",
          workspace_id: "ws-1",
          name: "Deal Finder",
          status: "active",
          goal_count: 2,
          artifact_member_count: 3,
          updated_at: "2026-01-02T00:00:00Z",
        },
      ],
    });

    render(<SolutionListPanel workspaceId="ws-1" workspaceName="Workspace 1" onOpenPanel={onOpenPanel} />);

    await waitFor(() => expect(apiMocks.listApplications).toHaveBeenCalledWith("ws-1"));
    expect(screen.getByText("Deal Finder")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(onOpenPanel).toHaveBeenCalledWith("solution_detail", { application_id: "app-1" }, { open_in: "new_panel" });
  });

  it("runs staged apply from solution detail panel and keeps composer handoff panel-native", async () => {
    const onOpenPanel = vi.fn();
    apiMocks.getApplication.mockResolvedValue({
      id: "app-1",
      workspace_id: "ws-1",
      name: "Deal Finder",
      summary: "Summary",
    });
    apiMocks.listApplicationArtifactMemberships.mockResolvedValue({ memberships: [] });
    apiMocks.listArtifacts.mockResolvedValue({ artifacts: [] });
    apiMocks.listSolutionChangeSessions.mockResolvedValue({
      sessions: [
        {
          id: "scs-1",
          title: "Session 1",
          status: "planned",
          selected_artifact_ids: [],
          analysis: {},
          plan: {},
          staged_changes: {},
          preview: {},
          validation: {},
        },
      ],
    });
    apiMocks.stageSolutionChangeApply.mockResolvedValue({ staged: true, session: { id: "scs-1" } });

    render(<SolutionDetailPanel workspaceId="ws-1" applicationId="app-1" onOpenPanel={onOpenPanel} />);

    await waitFor(() => expect(apiMocks.getApplication).toHaveBeenCalledWith("app-1"));
    await userEvent.click(screen.getByRole("button", { name: "Stage Coordinated Apply" }));
    await waitFor(() => expect(apiMocks.stageSolutionChangeApply).toHaveBeenCalledWith("app-1", "scs-1"));
    await waitFor(() => expect(apiMocks.listSolutionChangeSessions).toHaveBeenCalledTimes(2));

    await userEvent.click(screen.getByRole("button", { name: "Open Session In Composer" }));
    expect(onOpenPanel).toHaveBeenCalledWith(
      "composer_detail",
      expect.objectContaining({
        workspace_id: "ws-1",
        application_id: "app-1",
        solution_change_session_id: "scs-1",
      }),
      { open_in: "new_panel" }
    );
  });
});
