export type AssistPrimaryAction = "generate_draft" | "propose_edits";

export function resolveAssistPrimaryAction(hasBodyContent: boolean): AssistPrimaryAction {
  return hasBodyContent ? "propose_edits" : "generate_draft";
}

export function canRewriteSelection(selectionLength: number): boolean {
  return selectionLength > 0;
}

