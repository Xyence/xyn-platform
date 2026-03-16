import type { AppIntentDraft } from "../../api/types";
import { fromAppIntentDraft } from "../navigation/viewDescriptorBuilders";
import type { AppIntentDraftViewDescriptor } from "../navigation/viewDescriptors";

export type AppDraftViewDescriptor = AppIntentDraftViewDescriptor;

export function getAppDraftViewDescriptor(draft: Pick<AppIntentDraft, "id" | "title">, workspaceId: string): AppDraftViewDescriptor {
  return fromAppIntentDraft(draft, workspaceId);
}
