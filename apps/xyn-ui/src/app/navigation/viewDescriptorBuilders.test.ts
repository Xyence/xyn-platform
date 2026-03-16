import { describe, expect, it } from "vitest";

import { fromApplicationWorkspace, fromRecentArtifactItem, fromWorkspaceInstalledArtifact } from "./viewDescriptorBuilders";

describe("viewDescriptorBuilders", () => {
  it("builds a workspace installed artifact descriptor from the manage surface when present", () => {
    const descriptor = fromWorkspaceInstalledArtifact(
      {
        artifact_id: "artifact-1",
        binding_id: "binding-1",
        name: "hello",
        title: "Hello App",
        kind: "module",
        manifest_summary: {
          roles: [],
          suggestions: [],
          entities: [],
          surfaces: {
            nav: [],
            manage: [{ label: "Manage", path: "/apps/hello/manage", order: 100 }],
            docs: [],
          },
        },
      },
      "ws-1",
    );

    expect(descriptor).toMatchObject({
      kind: "artifact_detail",
      entityId: "artifact-1",
      route: "/apps/hello/manage",
      title: "Hello App",
      editorKey: "artifact_manage_surface",
    });
  });

  it("builds a recent artifact descriptor from the recorded route", () => {
    const descriptor = fromRecentArtifactItem(
      {
        artifact_id: "artifact-22",
        artifact_type: "article",
        artifact_state: "canonical",
        title: "Launch Notes",
        route: "/w/ws-1/build/artifacts/artifact-22",
        updated_at: "2026-03-15T12:00:00Z",
      },
      "ws-1",
    );

    expect(descriptor).toMatchObject({
      kind: "artifact_detail",
      entityId: "artifact-22",
      route: "/w/ws-1/build/artifacts/artifact-22",
      title: "Launch Notes",
      panelKey: "artifact_detail",
    });
  });

  it("builds an application workspace descriptor with workbench shell metadata", () => {
    const descriptor = fromApplicationWorkspace({
      workspaceId: "ws-1",
      applicationId: "app-9",
      title: "Team Lunch Poll",
    });

    expect(descriptor).toMatchObject({
      kind: "application_workspace",
      entityId: "app-9",
      route: "/w/ws-1/workbench",
      title: "Team Lunch Poll",
      shell: "workbench",
      panelKey: "application_detail",
      editorKey: "application_workbench",
    });
  });
});
