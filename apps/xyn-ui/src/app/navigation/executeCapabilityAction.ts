import type { NavigateFunction } from "react-router-dom";
import type { ContextualCapability } from "../../api/types";
import { openViewDescriptor } from "./openViewDescriptor";
import { fromApplicationWorkspace, fromArtifactDetail } from "./viewDescriptorBuilders";
import { toWorkspacePath } from "../routing/workspaceRouting";

type Params = {
  capability: ContextualCapability;
  navigate: NavigateFunction;
  workspaceId?: string | null;
  entityId?: string | null;
  insertPrompt: (text: string) => void;
};

export function executeCapabilityAction({ capability, navigate, workspaceId, entityId, insertPrompt }: Params): "prompt" | "action" {
  const actionType = String(capability.action_type || "prompt").trim().toLowerCase();
  const actionTarget = String(capability.action_target || "").trim();
  const normalizedWorkspaceId = String(workspaceId || "").trim();
  const normalizedEntityId = String(entityId || "").trim();

  if (actionType === "open_descriptor") {
    if (actionTarget === "fromApplicationWorkspace" && normalizedWorkspaceId) {
      openViewDescriptor(
        fromApplicationWorkspace({
          workspaceId: normalizedWorkspaceId,
          title: capability.name,
        }),
        navigate,
      );
      return "action";
    }
    if (actionTarget === "fromArtifactDetail" && normalizedWorkspaceId && normalizedEntityId) {
      openViewDescriptor(
        fromArtifactDetail({
          workspaceId: normalizedWorkspaceId,
          artifactId: normalizedEntityId,
          title: capability.name,
        }),
        navigate,
      );
      return "action";
    }
  }

  if (actionType === "route") {
    if (actionTarget === "workspace_jobs" && normalizedWorkspaceId) {
      navigate(toWorkspacePath(normalizedWorkspaceId, "jobs"));
      return "action";
    }
  }

  insertPrompt(String(capability.prompt_template || capability.name || "").trim());
  return "prompt";
}
