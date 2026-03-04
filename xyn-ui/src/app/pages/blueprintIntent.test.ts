import { describe, expect, it } from "vitest";
import type { BlueprintDetail } from "../../api/types";
import { extractBlueprintIntent } from "./blueprintIntent";

describe("extractBlueprintIntent", () => {
  it("extracts structured intent metadata from blueprint spec_json", () => {
    const detail = {
      id: "bp-1",
      name: "subscriber-notes",
      namespace: "core",
      spec_json: {
        intent: {
          sourceDraftSessionId: "draft-1",
          createdFrom: { type: "draft", id: "draft-1" },
          prompt: {
            text: "Create Subscriber Notes app",
            sha256: "abc123",
            createdAt: "2026-02-14T00:00:00Z",
          },
          requirements: {
            summary: "Subscriber Notes app",
            functional: ["create/list/delete", "health endpoint"],
            ui: ["Subscriber Notes - Dev Demo header", "table", "add form", "delete action"],
            dataModel: ["id", "subscriber_id", "note_text", "created_at"],
            operational: ["secrets", "logging", "migrations", "idempotent"],
            definitionOfDone: ["https://josh.xyence.io"],
          },
          transcripts: [{ id: "t1", text: "voice transcript" }],
        },
      },
    } as BlueprintDetail;

    const intent = extractBlueprintIntent(detail);
    expect(intent).not.toBeNull();
    expect(intent?.sourceDraftSessionId).toBe("draft-1");
    expect(intent?.requirements.ui.some((entry) => entry.includes("Subscriber Notes - Dev Demo"))).toBe(true);
    expect(intent?.requirements.dataModel).toContain("subscriber_id");
    expect(intent?.transcripts?.[0]?.id).toBe("t1");
    expect(intent?.prompt.text).toBe("Create Subscriber Notes app");
  });

  it("returns null for blueprints without intent", () => {
    const detail = {
      id: "bp-legacy",
      name: "legacy",
      namespace: "core",
      spec_json: { apiVersion: "xyn.blueprint/v1" },
    } as BlueprintDetail;
    expect(extractBlueprintIntent(detail)).toBeNull();
  });
});
