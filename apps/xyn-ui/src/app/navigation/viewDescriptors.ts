export type ViewDescriptorKind =
  | "app_intent_draft"
  | "artifact_detail"
  | "draft_session"
  | "context_pack_draft"
  | "application_workspace";

export interface ViewDescriptor {
  kind: ViewDescriptorKind;
  entityId: string;
  route: string;
  title?: string;
  subtitle?: string;
  shell?: string;
  panelKey?: string;
  editorKey?: string;
}

export interface AppIntentDraftViewDescriptor extends ViewDescriptor {
  kind: "app_intent_draft";
  editorKey: "application_workbench";
}

export interface ArtifactDetailViewDescriptor extends ViewDescriptor {
  kind: "artifact_detail";
}

export interface ApplicationWorkspaceViewDescriptor extends ViewDescriptor {
  kind: "application_workspace";
  shell: "workbench";
  editorKey: "application_workbench";
}
