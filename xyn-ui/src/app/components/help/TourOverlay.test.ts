import { describe, expect, it } from "vitest";
import { loadTourProgressForTest, saveTourProgressForTest } from "./TourOverlay";

describe("TourOverlay progress persistence", () => {
  it("persists and reloads per user and tour", () => {
    const user = "user-1";
    const slug = "deploy-subscriber-notes";
    saveTourProgressForTest(user, slug, { index: 3, dismissed: false, completed: false });
    const state = loadTourProgressForTest(user, slug);
    expect(state.index).toBe(3);
    expect(state.dismissed).toBe(false);
    expect(state.completed).toBe(false);
  });
});
