export type DraftPageOverallState = "draft" | "building" | "build_blocked" | "ready" | "needs_revision" | "unavailable";

export type DraftActionId =
  | "review_failure"
  | "retry_validation"
  | "view_build_jobs"
  | "edit_definition"
  | "continue_in_workbench"
  | "open_generated_environment"
  | "open_application_workspace"
  | "save_draft"
  | "submit_draft";

export type DraftResolvedAction = {
  id: DraftActionId;
  title: string;
  description: string;
  badge: string;
  enabled: boolean;
  disabledReason?: string;
  emphasis?: "primary" | "secondary";
  priority: number;
};

type ResolveDraftActionsArgs = {
  overallState: DraftPageOverallState;
  currentStep: string;
  hasDraft: boolean;
  hasRelatedJobs: boolean;
  hasDeploymentEnvironment: boolean;
  hasThreadContext: boolean;
  hasApplicationWorkspaceRoute: boolean;
  workspaceRoutingConfirmed: boolean;
  applicationWorkspaceReason?: string;
  saving: boolean;
  submitting: boolean;
};

export function resolveDraftActions({
  overallState,
  currentStep,
  hasDraft,
  hasRelatedJobs,
  hasDeploymentEnvironment,
  hasThreadContext,
  hasApplicationWorkspaceRoute,
  workspaceRoutingConfirmed,
  applicationWorkspaceReason,
  saving,
  submitting,
}: ResolveDraftActionsArgs): DraftResolvedAction[] {
  const actions: DraftResolvedAction[] = [];

  if (overallState === "build_blocked" || overallState === "needs_revision") {
    actions.push({
      id: "review_failure",
      title: "Review build failure",
      description: `Recommended because the current blocked stage is ${currentStep.toLowerCase()}. Start here to understand what failed after the successful build steps.`,
      badge: "Recommended",
      enabled: true,
      emphasis: "primary",
      priority: 10,
    });
  }

  if (hasDraft && overallState !== "building" && overallState !== "unavailable") {
    actions.push({
      id: "retry_validation",
      title: overallState === "draft" ? "Submit draft" : "Retry validation",
      description:
        overallState === "draft"
          ? "Recommended because this draft is ready to enter the build workflow."
          : "Recommended after reviewing the failure so you can rerun verification with the latest draft state.",
      badge: submitting ? "Submitting" : overallState === "draft" ? "Primary" : "Next step",
      enabled: !submitting,
      disabledReason: "A build is already being submitted.",
      emphasis: "primary",
      priority: 20,
    });
  }

  if (hasThreadContext) {
    actions.push({
      id: "continue_in_workbench",
      title: "Continue in Workbench",
      description: "Open the linked application composer in the workbench with this draft's current build state and thread context.",
      badge: "Contextual",
      enabled: true,
      emphasis: "secondary",
      priority: 30,
    });
  }

  if (hasRelatedJobs) {
    actions.push({
      id: "view_build_jobs",
      title: "View build jobs",
      description:
        overallState === "build_blocked"
          ? "Recommended because the job history shows which build and verification steps succeeded before the failure."
          : "Open the recorded build jobs for this draft and inspect step-by-step execution.",
      badge: "Available",
      enabled: true,
      emphasis: "secondary",
      priority: 40,
    });
  }

  if (hasDraft) {
    actions.push({
      id: "edit_definition",
      title: "Edit app definition",
      description:
        overallState === "build_blocked" || overallState === "needs_revision"
          ? "Recommended if the failure points to a definition or configuration problem. Review the prompt and draft JSON before retrying."
          : "Review and update the prompt, title, and raw draft JSON for this application draft.",
      badge: saving ? "Saving" : "Available",
      enabled: !saving,
      disabledReason: "The draft is currently saving.",
      emphasis: "secondary",
      priority: 50,
    });
  }

  if (hasDeploymentEnvironment) {
    actions.push({
      id: "open_generated_environment",
      title: "Open generated app environment",
      description:
        overallState === "build_blocked"
          ? "Open the deployed runtime to compare the live environment against the failing smoke test result."
          : "Open the deployed runtime environment that was provisioned for this generated application.",
      badge: "Available",
      enabled: true,
      emphasis: "secondary",
      priority: 60,
    });
  }

  if (hasApplicationWorkspaceRoute) {
    actions.push({
      id: "open_application_workspace",
      title: "Open application workspace",
      description: "Open the durable application workspace view for this generated application.",
      badge: workspaceRoutingConfirmed ? "Available" : "Available",
      enabled: true,
      emphasis: "secondary",
      priority: 70,
    });
  } else if (workspaceRoutingConfirmed || applicationWorkspaceReason) {
    actions.push({
      id: "open_application_workspace",
      title: "Open application workspace",
      description: "Open the durable application workspace view for this generated application.",
      badge: "Unavailable",
      enabled: false,
      disabledReason: applicationWorkspaceReason || "A durable application workspace route is not available for this draft yet.",
      emphasis: "secondary",
      priority: 80,
    });
  }

  if ((overallState === "draft" || overallState === "needs_revision") && hasDraft) {
    actions.push({
      id: overallState === "draft" ? "submit_draft" : "save_draft",
      title: overallState === "draft" ? "Submit draft" : "Save draft",
      description:
        overallState === "draft"
          ? "Start the application build workflow for this draft."
          : "Persist the latest definition edits before running validation again.",
      badge: overallState === "draft" ? (submitting ? "Submitting" : "Primary") : saving ? "Saving" : "Available",
      enabled: overallState === "draft" ? !submitting : !saving,
      disabledReason: overallState === "draft" ? "The draft is currently being submitted." : "The draft is currently saving.",
      emphasis: overallState === "draft" ? "primary" : "secondary",
      priority: 90,
    });
  }

  return actions.sort((left, right) => left.priority - right.priority);
}
