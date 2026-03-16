import type { AppIntentDraft, RecentArtifactItem, WorkspaceInstalledArtifactSummary } from "../../api/types";
import { toWorkspacePath } from "../routing/workspaceRouting";
import type {
  AppIntentDraftViewDescriptor,
  ApplicationWorkspaceViewDescriptor,
  ArtifactDetailViewDescriptor,
} from "./viewDescriptors";

function normalizeTitle(value: string | undefined, fallback: string): string {
  const text = String(value || "").trim();
  return text || fallback;
}

export function fromAppIntentDraft(
  draft: Pick<AppIntentDraft, "id" | "title">,
  workspaceId: string,
): AppIntentDraftViewDescriptor {
  const draftId = String(draft.id || "").trim();
  return {
    kind: "app_intent_draft",
    entityId: draftId,
    route: `/w/${encodeURIComponent(String(workspaceId || "").trim())}/drafts/${encodeURIComponent(draftId)}`,
    title: normalizeTitle(draft.title, draftId || "Application Draft"),
    shell: "workspace",
    panelKey: "draft_detail",
    editorKey: "application_workbench",
  };
}

export function fromWorkspaceInstalledArtifact(
  artifact: Pick<WorkspaceInstalledArtifactSummary, "artifact_id" | "binding_id" | "kind" | "name" | "title" | "manifest_summary">,
  workspaceId: string,
): ArtifactDetailViewDescriptor | null {
  const manageSurface = artifact.manifest_summary?.surfaces?.manage?.[0];
  const title = normalizeTitle(artifact.title || artifact.name, "Artifact");
  if (manageSurface?.path) {
    return {
      kind: "artifact_detail",
      entityId: String(artifact.artifact_id || artifact.binding_id || "").trim(),
      route: manageSurface.path,
      title,
      subtitle: normalizeTitle(artifact.kind || undefined, "Artifact"),
      shell: "workspace",
      editorKey: "artifact_manage_surface",
    };
  }
  if (workspaceId && artifact.artifact_id && String(artifact.kind || "").trim().toLowerCase() === "article") {
    return {
      kind: "artifact_detail",
      entityId: String(artifact.artifact_id || artifact.binding_id || "").trim(),
      route: toWorkspacePath(workspaceId, `build/artifacts/${encodeURIComponent(String(artifact.artifact_id || "").trim())}`),
      title,
      subtitle: normalizeTitle(artifact.kind || undefined, "Artifact"),
      shell: "workspace",
      panelKey: "artifact_detail",
    };
  }
  return null;
}

export function fromRecentArtifactItem(item: RecentArtifactItem, workspaceId?: string): ArtifactDetailViewDescriptor {
  const artifactId = String(item.artifact_id || "").trim();
  const fallbackRoute =
    workspaceId && artifactId ? toWorkspacePath(workspaceId, `build/artifacts/${encodeURIComponent(artifactId)}`) : "/";
  return {
    kind: "artifact_detail",
    entityId: artifactId,
    route: String(item.route || "").trim() || fallbackRoute,
    title: normalizeTitle(item.title, artifactId || "Artifact"),
    subtitle: normalizeTitle(item.artifact_type, "Artifact"),
    shell: "workspace",
    panelKey: "artifact_detail",
  };
}

export function fromApplicationWorkspace(options: {
  workspaceId: string;
  applicationId?: string | null;
  title?: string;
  subtitle?: string;
}): ApplicationWorkspaceViewDescriptor {
  const workspaceId = String(options.workspaceId || "").trim();
  const applicationId = String(options.applicationId || "").trim();
  return {
    kind: "application_workspace",
    entityId: applicationId || workspaceId,
    route: toWorkspacePath(workspaceId, "workbench"),
    title: normalizeTitle(options.title, "Application Workbench"),
    subtitle: String(options.subtitle || "").trim() || undefined,
    shell: "workbench",
    panelKey: applicationId ? "application_detail" : "composer_detail",
    editorKey: "application_workbench",
  };
}
