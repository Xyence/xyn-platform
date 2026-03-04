import { useMemo } from "react";
import { useParams } from "react-router-dom";

type WorkspaceRow = {
  id: string;
  slug?: string;
  name: string;
};

type WorkspaceRouteContext = {
  workspaceId: string;
  workspace: WorkspaceRow | null;
  workspaceName: string;
  workspaceColor: string;
};

function colorFromWorkspaceId(workspaceId: string): string {
  const token = String(workspaceId || "");
  if (!token) return "#6c7a89";
  let hash = 0;
  for (let i = 0; i < token.length; i += 1) {
    hash = (hash * 31 + token.charCodeAt(i)) >>> 0;
  }
  const hue = hash % 360;
  return `hsl(${hue} 62% 46%)`;
}

export default function useWorkspaceFromRoute(workspaces: WorkspaceRow[]): WorkspaceRouteContext {
  const params = useParams();
  const workspaceId = String(params.workspaceId || "").trim();

  const workspace = useMemo(() => workspaces.find((row) => row.id === workspaceId) || null, [workspaces, workspaceId]);
  const workspaceName = workspace?.name || "Unknown";
  const workspaceColor = colorFromWorkspaceId(workspaceId || workspace?.id || "");

  return { workspaceId, workspace, workspaceName, workspaceColor };
}
