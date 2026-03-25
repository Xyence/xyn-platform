import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SolutionDetailPanel, SolutionListPanel } from "./SolutionPanels";

const apiMocks = vi.hoisted(() => ({
  listApplications: vi.fn(),
  generateApplicationPlan: vi.fn(),
  applyApplicationPlan: vi.fn(),
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
  generateApplicationPlan: apiMocks.generateApplicationPlan,
  applyApplicationPlan: apiMocks.applyApplicationPlan,
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
  beforeEach(() => {
    vi.clearAllMocks();
  });

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

  it("creates a new solution via plan/apply and opens composer with an initialized planning session", async () => {
    const onOpenPanel = vi.fn();
    apiMocks.listApplications
      .mockResolvedValueOnce({ applications: [] })
      .mockResolvedValueOnce({
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
    apiMocks.generateApplicationPlan.mockResolvedValue({ id: "plan-1" });
    apiMocks.applyApplicationPlan.mockResolvedValue({
      status: "applied",
      application: { id: "app-1", name: "Deal Finder" },
      application_plan: { id: "plan-1" },
    });
    apiMocks.createSolutionChangeSession.mockResolvedValue({
      created: true,
      session: { id: "session-1", application_id: "app-1" },
    });

    render(<SolutionListPanel workspaceId="ws-1" workspaceName="Workspace 1" onOpenPanel={onOpenPanel} />);

    await waitFor(() => expect(apiMocks.listApplications).toHaveBeenCalledWith("ws-1"));
    await userEvent.click(screen.getByRole("button", { name: "New Solution" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Solution name" }), "Deal Finder");
    await userEvent.type(screen.getByRole("textbox", { name: "Objective / request" }), "Improve campaign creation UX");
    await userEvent.click(screen.getByRole("button", { name: "Create Solution" }));

    await waitFor(() =>
      expect(apiMocks.generateApplicationPlan).toHaveBeenCalledWith({
        workspace_id: "ws-1",
        objective: "Improve campaign creation UX",
        application_name: "Deal Finder",
      })
    );
    await waitFor(() => expect(apiMocks.applyApplicationPlan).toHaveBeenCalledWith("plan-1"));
    await waitFor(() =>
      expect(apiMocks.createSolutionChangeSession).toHaveBeenCalledWith("app-1", {
        request_text: "Improve campaign creation UX",
      })
    );
    expect(onOpenPanel).toHaveBeenCalledWith(
      "composer_detail",
      {
        workspace_id: "ws-1",
        application_id: "app-1",
        solution_change_session_id: "session-1",
      },
      { open_in: "new_panel" }
    );
  });

  it("prefills the new solution form when routed from create/build solution panel intent", async () => {
    apiMocks.listApplications.mockResolvedValue({ applications: [] });
    render(
      <SolutionListPanel
        workspaceId="ws-1"
        workspaceName="Workspace 1"
        createSolutionObjective="stabilize workspace selector placement"
        createSolutionName="UI polish"
        onOpenPanel={vi.fn()}
      />
    );
    await waitFor(() => expect(apiMocks.listApplications).toHaveBeenCalledWith("ws-1"));
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Solution name" })).toHaveValue("UI polish");
    expect(screen.getByRole("textbox", { name: "Objective / request" })).toHaveValue(
      "stabilize workspace selector placement"
    );
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
    expect(apiMocks.listArtifacts).toHaveBeenCalledWith({ limit: 200, scope: "solution" });
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

  it("renders session-built preview evidence when concrete launch details exist", async () => {
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
          preview: {
            status: "ready",
            mode: "coordinated_multi_artifact_preview",
            newly_built_for_session: true,
            session_build: {
              status: "succeeded",
              launched_containers: ["xyn-preview-deal-finder-runtime"],
            },
          },
          validation: {},
        },
      ],
    });

    render(<SolutionDetailPanel workspaceId="ws-1" applicationId="app-1" onOpenPanel={vi.fn()} />);

    await waitFor(() => expect(apiMocks.getApplication).toHaveBeenCalledWith("app-1"));
    expect(screen.getByText("Session preview build: newly built/deployed for this session")).toBeInTheDocument();
    expect(screen.getByText(/Launch evidence:/)).toBeInTheDocument();
  });

  it("renders preview reuse state when session-specific build evidence is unavailable", async () => {
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
          id: "scs-2",
          title: "Session 2",
          status: "planned",
          selected_artifact_ids: [],
          analysis: {},
          plan: {},
          staged_changes: {},
          preview: {
            status: "ready",
            mode: "coordinated_multi_artifact_preview",
            newly_built_for_session: false,
            session_build: {
              status: "reused",
              reason: "missing_app_container_bindings",
            },
          },
          validation: {},
        },
      ],
    });

    render(<SolutionDetailPanel workspaceId="ws-1" applicationId="app-1" onOpenPanel={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Session preview build: reused existing runtime")).toBeInTheDocument());
    expect(screen.getByText("Reuse reason: missing_app_container_bindings")).toBeInTheDocument();
  });

  it("allows broadening membership candidates beyond solution-scoped artifacts", async () => {
    apiMocks.getApplication.mockResolvedValue({
      id: "app-1",
      workspace_id: "ws-1",
      name: "Deal Finder",
      summary: "Summary",
    });
    apiMocks.listApplicationArtifactMemberships.mockResolvedValue({ memberships: [] });
    apiMocks.listArtifacts.mockResolvedValue({ artifacts: [] });
    apiMocks.listSolutionChangeSessions.mockResolvedValue({ sessions: [] });

    render(<SolutionDetailPanel workspaceId="ws-1" applicationId="app-1" onOpenPanel={vi.fn()} />);

    await waitFor(() => expect(apiMocks.listArtifacts).toHaveBeenCalledWith({ limit: 200, scope: "solution" }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Candidate scope" }), "all");
    await waitFor(() => expect(apiMocks.listArtifacts).toHaveBeenLastCalledWith({ limit: 200 }));
  });

  it("shows an unavailable state when a preserved solution detail does not exist in the current workspace", async () => {
    const onOpenPanel = vi.fn();
    apiMocks.getApplication.mockResolvedValue({
      id: "app-1",
      workspace_id: "ws-other",
      name: "Deal Finder",
      summary: "Summary",
    });

    render(<SolutionDetailPanel workspaceId="ws-1" applicationId="app-1" onOpenPanel={onOpenPanel} />);

    await waitFor(() => expect(apiMocks.getApplication).toHaveBeenCalledWith("app-1"));
    expect(screen.getByRole("heading", { name: "Solution unavailable" })).toBeInTheDocument();
    expect(screen.getByText("Solution was not found in workspace ws-1.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open Solutions" }));
    expect(onOpenPanel).toHaveBeenCalledWith("solution_list", { workspace_id: "ws-1" }, { open_in: "current_panel" });
  });
});
