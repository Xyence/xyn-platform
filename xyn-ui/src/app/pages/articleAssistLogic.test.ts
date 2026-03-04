import { describe, expect, it } from "vitest";
import { canRewriteSelection, resolveAssistPrimaryAction } from "./articleAssistLogic";

describe("articleAssistLogic", () => {
  it("uses generate draft when body is empty", () => {
    expect(resolveAssistPrimaryAction(false)).toBe("generate_draft");
  });

  it("uses propose edits when body exists", () => {
    expect(resolveAssistPrimaryAction(true)).toBe("propose_edits");
  });

  it("enables rewrite selection only with selected text", () => {
    expect(canRewriteSelection(0)).toBe(false);
    expect(canRewriteSelection(12)).toBe(true);
  });
});

