import { describe, expect, it } from "vitest";
import { resolveCategoryActions } from "./articleCategoryActions";

describe("resolveCategoryActions", () => {
  it("disables permanent delete when referenced", () => {
    const view = resolveCategoryActions({ enabled: true, referencedArticleCount: 3 });
    expect(view.canDeletePermanently).toBe(false);
    expect(view.showDeprecate).toBe(true);
    expect(view.showReenable).toBe(false);
    expect(view.helperText).toContain("referenced by 3 articles");
  });

  it("allows permanent delete when never referenced", () => {
    const view = resolveCategoryActions({ enabled: true, referencedArticleCount: 0 });
    expect(view.canDeletePermanently).toBe(true);
    expect(view.showDeprecate).toBe(true);
    expect(view.showReenable).toBe(false);
  });

  it("shows re-enable for deprecated category", () => {
    const view = resolveCategoryActions({ enabled: false, referencedArticleCount: 7 });
    expect(view.canDeletePermanently).toBe(false);
    expect(view.showDeprecate).toBe(false);
    expect(view.showReenable).toBe(true);
  });
});
