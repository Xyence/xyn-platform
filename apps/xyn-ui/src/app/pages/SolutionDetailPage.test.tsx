import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import SolutionDetailPage from "./SolutionDetailPage";

const apiMocks = vi.hoisted(() => ({
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

vi.mock("../../api/xyn", () => ({
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

describe("SolutionDetailPage", () => {
  it("shows member artifacts and exposes application-level composer entrypoint", async () => {
    apiMocks.getApplication.mockResolvedValue({
      id: "app-1",
      workspace_id: "ws-1",
      name: "Deal Finder",
      summary: "Solution context",
      source_factory_key: "generic_application_mvp",
      status: "active",
      request_objective: "Build app",
      goal_count: 0,
      artifact_member_count: 1,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-02T00:00:00Z",
      goals: [],
      artifact_memberships: [],
    });
    apiMocks.listApplicationArtifactMemberships.mockResolvedValue({
      application_id: "app-1",
      workspace_id: "ws-1",
      memberships: [
        {
          id: "m-1",
          workspace_id: "ws-1",
          application_id: "app-1",
          artifact_id: "a-1",
          role: "primary_ui",
          responsibility_summary: "Main shell UX",
          metadata: {},
          sort_order: 0,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-02T00:00:00Z",
          artifact: {
            id: "a-1",
            workspace_id: "ws-1",
            type: "generated_app",
            title: "Deal Finder UI",
            slug: "deal-finder-ui",
            status: "active",
            version: 1,
            updated_at: "2026-01-02T00:00:00Z",
          },
        },
      ],
    });
    apiMocks.listArtifacts.mockResolvedValue({
      count: 1,
      next: null,
      prev: null,
      artifacts: [
        {
          id: "a-1",
          workspace_id: "ws-1",
          type: "generated_app",
          title: "Deal Finder UI",
        },
      ],
    });
    apiMocks.upsertApplicationArtifactMembership.mockResolvedValue({
      created: true,
      membership: {
        id: "m-2",
      },
    });
    apiMocks.listSolutionChangeSessions.mockResolvedValue({
      application_id: "app-1",
      workspace_id: "ws-1",
      sessions: [
        {
          id: "scs-1",
          workspace_id: "ws-1",
          application_id: "app-1",
          title: "Add campaign analytics",
          request_text: "Extend UI and API for analytics",
          status: "draft",
          selected_artifact_ids: ["a-1"],
          analysis: { impacted_artifacts: [] },
          plan: {},
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-02T00:00:00Z",
        },
      ],
    });

    render(
      <MemoryRouter initialEntries={["/w/ws-1/solutions/app-1"]}>
        <Routes>
          <Route path="/w/:workspaceId/solutions/:applicationId" element={<SolutionDetailPage workspaceId="ws-1" />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => expect(apiMocks.getApplication).toHaveBeenCalledWith("app-1"));
    expect(screen.getByText("Deal Finder UI")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Composer" })).toHaveAttribute(
      "href",
      "/w/ws-1/workbench?panel=composer_detail&application_id=app-1&solution_change_session_id=scs-1"
    );

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Artifact"), "a-1");
    await user.click(screen.getByRole("button", { name: "Add Membership" }));
    await waitFor(() =>
      expect(apiMocks.upsertApplicationArtifactMembership).toHaveBeenCalledWith(
        "app-1",
        expect.objectContaining({ artifact_id: "a-1" })
      )
    );
  });

  it("creates a solution change session and generates a cross-artifact plan", async () => {
    apiMocks.getApplication.mockResolvedValue({
      id: "app-2",
      workspace_id: "ws-1",
      name: "Deal Finder",
      summary: "Solution context",
      source_factory_key: "generic_application_mvp",
      status: "active",
      request_objective: "Build app",
      goal_count: 0,
      artifact_member_count: 1,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-02T00:00:00Z",
      goals: [],
      artifact_memberships: [],
    });
    apiMocks.listApplicationArtifactMemberships.mockResolvedValue({
      application_id: "app-2",
      workspace_id: "ws-1",
      memberships: [],
    });
    apiMocks.listArtifacts.mockResolvedValue({ count: 0, next: null, prev: null, artifacts: [] });
    apiMocks.listSolutionChangeSessions
      .mockResolvedValueOnce({
        application_id: "app-2",
        workspace_id: "ws-1",
        sessions: [],
      })
      .mockResolvedValueOnce({
        application_id: "app-2",
        workspace_id: "ws-1",
        sessions: [
          {
            id: "scs-2",
            workspace_id: "ws-1",
            application_id: "app-2",
            title: "API + UI change",
            request_text: "Update API and UI",
            status: "draft",
            selected_artifact_ids: ["a-ui"],
            analysis: {
              impacted_artifacts: [
                {
                  membership_id: "m-ui",
                  artifact_id: "a-ui",
                  artifact_title: "Deal Finder UI",
                  role: "primary_ui",
                  score: 5,
                  reasons: ["request mentions primary ui concerns"],
                },
              ],
            },
            plan: {},
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-02T00:00:00Z",
          },
        ],
      })
      .mockResolvedValue({
        application_id: "app-2",
        workspace_id: "ws-1",
        sessions: [
          {
            id: "scs-2",
            workspace_id: "ws-1",
            application_id: "app-2",
            title: "API + UI change",
            request_text: "Update API and UI",
            status: "planned",
            selected_artifact_ids: ["a-ui"],
            analysis: { impacted_artifacts: [] },
            plan: { per_artifact_work: [] },
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-03T00:00:00Z",
          },
        ],
      });
    apiMocks.createSolutionChangeSession.mockResolvedValue({
      created: true,
      session: {
        id: "scs-2",
        selected_artifact_ids: ["a-ui"],
      },
    });
    apiMocks.updateSolutionChangeSession.mockResolvedValue({
      id: "scs-2",
      selected_artifact_ids: ["a-ui"],
    });
    apiMocks.generateSolutionChangePlan.mockResolvedValue({
      planned: true,
      session: {
        id: "scs-2",
        selected_artifact_ids: ["a-ui"],
      },
    });
    apiMocks.upsertApplicationArtifactMembership.mockResolvedValue({ created: false, membership: { id: "m-1" } });

    render(
      <MemoryRouter initialEntries={["/w/ws-1/solutions/app-2"]}>
        <Routes>
          <Route path="/w/:workspaceId/solutions/:applicationId" element={<SolutionDetailPage workspaceId="ws-1" />} />
        </Routes>
      </MemoryRouter>
    );

    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Requested change"), "Update API and UI contracts");
    await user.click(screen.getByRole("button", { name: "Create Change Session" }));

    await waitFor(() =>
      expect(apiMocks.createSolutionChangeSession).toHaveBeenCalledWith(
        "app-2",
        expect.objectContaining({ request_text: "Update API and UI contracts" })
      )
    );

    await user.click(await screen.findByRole("button", { name: "Generate Cross-Artifact Plan" }));
    await waitFor(() => expect(apiMocks.generateSolutionChangePlan).toHaveBeenCalledWith("app-2", "scs-2"));
  });

  it("supports staged apply, preview preparation, and validation status flow", async () => {
    apiMocks.getApplication.mockResolvedValue({
      id: "app-3",
      workspace_id: "ws-1",
      name: "Deal Finder",
      summary: "Solution context",
      source_factory_key: "generic_application_mvp",
      status: "active",
      request_objective: "Build app",
      goal_count: 0,
      artifact_member_count: 1,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-02T00:00:00Z",
      goals: [],
      artifact_memberships: [],
    });
    apiMocks.listApplicationArtifactMemberships.mockResolvedValue({
      application_id: "app-3",
      workspace_id: "ws-1",
      memberships: [],
    });
    apiMocks.listArtifacts.mockResolvedValue({ count: 0, next: null, prev: null, artifacts: [] });
    apiMocks.listSolutionChangeSessions
      .mockResolvedValueOnce({
        application_id: "app-3",
        workspace_id: "ws-1",
        sessions: [
          {
            id: "scs-3",
            workspace_id: "ws-1",
            application_id: "app-3",
            title: "Coordinated execution",
            request_text: "Ship coordinated updates",
            status: "planned",
            execution_status: "staged",
            selected_artifact_ids: ["a-ui"],
            analysis: { impacted_artifacts: [] },
            plan: { per_artifact_work: [{ artifact_id: "a-ui", planned_work: ["Update shell UX"] }] },
            staged_changes: {
              artifact_states: [
                {
                  artifact_id: "a-ui",
                  artifact_title: "Deal Finder UI",
                  role: "primary_ui",
                  apply_state: "proposed",
                  validation_state: "pending",
                },
              ],
            },
            preview: {},
            validation: {},
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-02T00:00:00Z",
          },
        ],
      })
      .mockResolvedValue({
        application_id: "app-3",
        workspace_id: "ws-1",
        sessions: [
          {
            id: "scs-3",
            workspace_id: "ws-1",
            application_id: "app-3",
            title: "Coordinated execution",
            request_text: "Ship coordinated updates",
            status: "planned",
            execution_status: "ready_for_promotion",
            selected_artifact_ids: ["a-ui"],
            analysis: { impacted_artifacts: [] },
            plan: { per_artifact_work: [{ artifact_id: "a-ui", planned_work: ["Update shell UX"] }] },
            staged_changes: {
              artifact_states: [
                {
                  artifact_id: "a-ui",
                  artifact_title: "Deal Finder UI",
                  role: "primary_ui",
                  apply_state: "proposed",
                  validation_state: "passed",
                },
              ],
            },
            preview: {
              status: "ready",
              mode: "coordinated_multi_artifact_preview",
              primary_url: "http://localhost:32822/app",
              preview_urls: ["http://localhost:32822/app"],
              artifacts: [
                {
                  artifact_id: "a-ui",
                  artifact_title: "Deal Finder UI",
                  status: "ready",
                  compose_project: "xyn-preview",
                  runtime_base_url: "http://deal-finder-runtime:8080",
                },
              ],
            },
            validation: {
              checks: [
                { key: "plan_generated", label: "Structured cross-artifact plan generated", status: "passed" },
              ],
            },
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-03T00:00:00Z",
          },
        ],
      });
    apiMocks.createSolutionChangeSession.mockResolvedValue({ created: false, session: { id: "scs-3", selected_artifact_ids: ["a-ui"] } });
    apiMocks.updateSolutionChangeSession.mockResolvedValue({ id: "scs-3", selected_artifact_ids: ["a-ui"] });
    apiMocks.generateSolutionChangePlan.mockResolvedValue({ planned: true, session: { id: "scs-3", selected_artifact_ids: ["a-ui"] } });
    apiMocks.stageSolutionChangeApply.mockResolvedValue({ staged: true, session: { id: "scs-3" } });
    apiMocks.prepareSolutionChangePreview.mockResolvedValue({ prepared: true, session: { id: "scs-3" } });
    apiMocks.validateSolutionChangeSession.mockResolvedValue({ validated: true, session: { id: "scs-3" } });
    apiMocks.upsertApplicationArtifactMembership.mockResolvedValue({ created: false, membership: { id: "m-1" } });

    render(
      <MemoryRouter initialEntries={["/w/ws-1/solutions/app-3"]}>
        <Routes>
          <Route path="/w/:workspaceId/solutions/:applicationId" element={<SolutionDetailPage workspaceId="ws-1" />} />
        </Routes>
      </MemoryRouter>
    );

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Stage Coordinated Apply" }));
    await waitFor(() => expect(apiMocks.stageSolutionChangeApply).toHaveBeenCalledWith("app-3", "scs-3"));

    await user.click(await screen.findByRole("button", { name: "Prepare Preview Handoff" }));
    await waitFor(() => expect(apiMocks.prepareSolutionChangePreview).toHaveBeenCalledWith("app-3", "scs-3"));

    await user.click(await screen.findByRole("button", { name: "Validate Staged Change" }));
    await waitFor(() => expect(apiMocks.validateSolutionChangeSession).toHaveBeenCalledWith("app-3", "scs-3"));
    expect(await screen.findByText("Primary preview URL:")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "http://localhost:32822/app" }).length).toBeGreaterThan(0);
  });
});
