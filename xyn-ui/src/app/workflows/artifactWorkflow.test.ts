import { describe, expect, it } from "vitest";
import { resolveArtifactWorkflowActions } from "./artifactWorkflow";

function baseInput(overrides: Partial<Parameters<typeof resolveArtifactWorkflowActions>[0]> = {}) {
  return {
    artifactType: "article" as const,
    article: {
      status: "draft" as const,
      visibility_type: "private" as const,
      allowed_roles: [],
      published_to: [],
      summary: "Summary",
      title: "Article",
    },
    validation: {
      hasBodyMarkdown: true,
      hasSummary: true,
    },
    capabilities: {
      canManageLifecycle: true,
      canSaveRevision: true,
      canReact: true,
      canViewRevisions: true,
    },
    ...overrides,
  };
}

describe("resolveArtifactWorkflowActions", () => {
  it("uses mark reviewed as primary in draft", () => {
    const result = resolveArtifactWorkflowActions(baseInput());
    expect(result.primaryAction?.id).toBe("mark_reviewed");
    expect(result.primaryAction?.enabled).toBe(true);
  });

  it("disables primary action with blockers for missing body", () => {
    const result = resolveArtifactWorkflowActions(
      baseInput({
        validation: {
          hasBodyMarkdown: false,
          hasSummary: true,
        },
      })
    );
    expect(result.primaryAction?.id).toBe("mark_reviewed");
    expect(result.primaryAction?.enabled).toBe(false);
    expect(result.blockers.some((item) => item.includes("Body markdown"))).toBe(true);
  });

  it("moves to ratify primary in reviewed", () => {
    const result = resolveArtifactWorkflowActions(
      baseInput({
        article: {
          status: "reviewed",
          visibility_type: "private",
          allowed_roles: [],
          published_to: [],
          summary: "Summary",
          title: "Article",
        },
      })
    );
    expect(result.primaryAction?.id).toBe("mark_ratified");
  });

  it("hides impossible transitions in published", () => {
    const result = resolveArtifactWorkflowActions(
      baseInput({
        article: {
          status: "published",
          visibility_type: "public",
          allowed_roles: [],
          published_to: [{ source: "category", label: "Public Website", target_type: "public_web_path", target_value: "/articles" }],
          summary: "Summary",
          title: "Article",
        },
      })
    );
    const ids = result.secondaryActions.map((item) => item.id);
    expect(ids.includes("mark_reviewed")).toBe(false);
    expect(ids.includes("mark_ratified")).toBe(false);
    expect(ids.includes("deprecate")).toBe(true);
  });
});
