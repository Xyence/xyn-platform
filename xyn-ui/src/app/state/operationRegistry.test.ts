import { describe, expect, it } from "vitest";
import { operationRegistryReducer } from "./operationRegistry";

describe("operationRegistry", () => {
  it("starts and finishes operations", () => {
    const started = operationRegistryReducer(
      { items: [] },
      {
        type: "START",
        payload: {
          id: "op-1",
          type: "ai",
          label: "AI propose edits",
          entityType: "article",
          entityId: "a-1",
        },
      }
    );

    expect(started.items).toHaveLength(1);
    expect(started.items[0].status).toBe("running");

    const finished = operationRegistryReducer(started, {
      type: "FINISH",
      payload: {
        id: "op-1",
        status: "succeeded",
        summary: "Ready",
      },
    });

    expect(finished.items[0].status).toBe("succeeded");
    expect(finished.items[0].summary).toBe("Ready");
    expect(finished.items[0].finishedAt).toBeTypeOf("number");
  });

  it("ignores finish for unknown operation", () => {
    const initial = { items: [] };
    const next = operationRegistryReducer(initial, {
      type: "FINISH",
      payload: { id: "missing", status: "failed" },
    });
    expect(next).toEqual(initial);
  });
});

