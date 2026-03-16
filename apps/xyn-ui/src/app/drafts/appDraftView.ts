import type { AppIntentDraft } from "../../api/types";

export type AppDraftViewDescriptor = {
  kind: "app_intent_draft";
  draftId: string;
  route: string;
  title: string;
  editorKey: "application_workbench";
};

export function getAppDraftViewDescriptor(draft: Pick<AppIntentDraft, "id" | "title">, workspaceId: string): AppDraftViewDescriptor {
  const draftId = String(draft.id || "").trim();
  const normalizedWorkspaceId = encodeURIComponent(String(workspaceId || "").trim());
  return {
    kind: "app_intent_draft",
    draftId,
    route: `/w/${normalizedWorkspaceId}/drafts/${encodeURIComponent(draftId)}`,
    title: String(draft.title || "").trim() || draftId || "Application Draft",
    editorKey: "application_workbench",
  };
}
