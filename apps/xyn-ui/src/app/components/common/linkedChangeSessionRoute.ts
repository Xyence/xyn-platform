import type { WorkspaceLinkedChangeSession } from "../../../api/types";
import { toWorkspacePath } from "../../routing/workspaceRouting";

export function buildLinkedChangeSessionRoute(workspaceId: string, linkedSession: WorkspaceLinkedChangeSession | null): string {
  if (!linkedSession) return "";
  const applicationId = String(linkedSession.application_id || "").trim();
  const sessionId = String(linkedSession.solution_change_session_id || "").trim();
  if (!applicationId || !sessionId) return "";
  const params = new URLSearchParams();
  params.set("panel", "composer_detail");
  params.set("application_id", applicationId);
  params.set("solution_change_session_id", sessionId);
  return toWorkspacePath(workspaceId, `workbench?${params.toString()}`);
}
