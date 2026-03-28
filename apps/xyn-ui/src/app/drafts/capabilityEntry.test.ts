import { describe, expect, it } from "vitest";
import type { AppJob } from "../../api/types";
import { extractCapabilityEntry, resolveCapabilityOpenTarget } from "./capabilityEntry";

function jobWithOutput(output_json: Record<string, unknown>): AppJob {
  return {
    id: "job-1",
    workspace_id: "ws-1",
    type: "provision_sibling_xyn",
    status: "succeeded",
    input_json: {},
    output_json,
    created_at: "2026-03-28T00:00:00Z",
    updated_at: "2026-03-28T00:00:00Z",
  };
}

describe("capabilityEntry helpers", () => {
  it("uses artifact-first open semantics for installed capabilities", () => {
    const entry = extractCapabilityEntry([
      jobWithOutput({
        sibling_xyn: {
          capability_entry: {
            source_of_truth: "installed_artifact",
            state: "installed",
            installed_artifact: {
              artifact_id: "art-1",
              artifact_slug: "app.knowledge",
              workspace_id: "ws-target",
            },
            open_preference: {
              mode: "artifact_shell",
              runtime_public_url: "http://localhost:8080",
            },
          },
        },
      }),
    ]);

    const target = resolveCapabilityOpenTarget({
      workspaceId: "ws-current",
      capabilityEntry: entry,
      deploymentUrls: { appUrl: "", siblingUiUrl: "" },
    });

    expect(target).toBe("/w/ws-target/workbench?artifact_slug=app.knowledge");
  });

  it("uses runtime fallback semantics for generated-not-installed capabilities", () => {
    const entry = extractCapabilityEntry([
      jobWithOutput({
        capability_entry: {
          source_of_truth: "generated_artifact",
          state: "generated_not_installed",
          installed_artifact: {},
          open_preference: {
            mode: "runtime_url_fallback",
            runtime_public_url: "http://localhost:18010",
          },
        },
      }),
    ]);

    const target = resolveCapabilityOpenTarget({
      workspaceId: "ws-current",
      capabilityEntry: entry,
      deploymentUrls: { appUrl: "http://localhost:3000", siblingUiUrl: "" },
    });

    expect(target).toBe("http://localhost:18010");
  });

  it("remains backward-compatible when capability_entry is absent", () => {
    const target = resolveCapabilityOpenTarget({
      workspaceId: "ws-current",
      capabilityEntry: null,
      deploymentUrls: { appUrl: "http://localhost:3000", siblingUiUrl: "" },
    });

    expect(target).toBe("http://localhost:3000");
  });
});
