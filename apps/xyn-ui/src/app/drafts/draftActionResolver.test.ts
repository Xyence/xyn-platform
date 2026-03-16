import { describe, expect, it } from "vitest";
import { resolveDraftActions } from "./draftActionResolver";

describe("resolveDraftActions", () => {
  it("returns only valid blocked-build actions when no durable application workspace route exists", () => {
    const actions = resolveDraftActions({
      overallState: "build_blocked",
      currentStep: "Smoke test failed after deploy",
      hasDraft: true,
      hasRelatedJobs: true,
      hasDeploymentEnvironment: true,
      hasThreadContext: true,
      hasApplicationWorkspaceRoute: false,
      workspaceRoutingConfirmed: false,
      applicationWorkspaceReason: "",
      saving: false,
      submitting: false,
    });

    expect(actions.map((entry) => entry.id)).toEqual([
      "review_failure",
      "retry_validation",
      "continue_in_workbench",
      "view_build_jobs",
      "edit_definition",
      "open_generated_environment",
    ]);
  });

  it("disables application workspace action with a clear reason when the app exists but no route can be opened", () => {
    const actions = resolveDraftActions({
      overallState: "ready",
      currentStep: "Verification completed",
      hasDraft: true,
      hasRelatedJobs: true,
      hasDeploymentEnvironment: true,
      hasThreadContext: true,
      hasApplicationWorkspaceRoute: false,
      workspaceRoutingConfirmed: true,
      applicationWorkspaceReason: "The application record exists, but no reachable workspace route was returned for it.",
      saving: false,
      submitting: false,
    });

    const workspaceAction = actions.find((entry) => entry.id === "open_application_workspace");
    expect(workspaceAction).toMatchObject({
      enabled: false,
      disabledReason: "The application record exists, but no reachable workspace route was returned for it.",
    });
  });

  it("enables the durable application workspace action when a real route is available", () => {
    const actions = resolveDraftActions({
      overallState: "ready",
      currentStep: "Verification completed",
      hasDraft: true,
      hasRelatedJobs: true,
      hasDeploymentEnvironment: true,
      hasThreadContext: true,
      hasApplicationWorkspaceRoute: true,
      workspaceRoutingConfirmed: true,
      applicationWorkspaceReason: "",
      saving: false,
      submitting: false,
    });

    expect(actions.find((entry) => entry.id === "open_application_workspace")).toMatchObject({
      enabled: true,
    });
  });
});
