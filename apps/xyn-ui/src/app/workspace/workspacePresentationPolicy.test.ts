import { describe, expect, it } from "vitest";

import type { ConsolePanelState } from "../state/xynConsoleStore";
import {
  defaultWorkspacePreset,
  friendlyTitleForKey,
  panelAffinityForKey,
  resolveTargetStackId,
  shouldFocusExistingPanel,
  shouldReplaceCurrentPanel,
} from "./workspacePresentationPolicy";

const SAMPLE_PANEL = (overrides: Partial<ConsolePanelState> = {}): ConsolePanelState => ({
  panel_id: "panel-1",
  panel_type: "detail",
  instance_key: "run:run-1",
  title: "Run Detail",
  key: "run_detail",
  params: { run_id: "run-1" },
  active_group_id: "stack-operations",
  panel_affinity: "operations",
  workspace_id: "ws-1",
  thread_id: null,
  panel_object: null,
  ...overrides,
});

describe("workspacePresentationPolicy", () => {
  it("uses a default preset with distinct conversation, operations, and artifact stacks", () => {
    const preset = defaultWorkspacePreset();
    const children = ((preset.flexlayout_model.layout as unknown as Record<string, unknown>).children || []) as Array<Record<string, unknown>>;
    expect(children.map((child) => child.id)).toEqual(["stack-conversation", "stack-application", "stack-operations", "stack-artifacts"]);
    expect(preset.lock_mode).toBe("starting_layout_only");
  });

  it("prefers focusing an existing same-object panel", () => {
    expect(shouldFocusExistingPanel(SAMPLE_PANEL())).toBe(true);
    expect(shouldFocusExistingPanel(null)).toBe(false);
  });

  it("opens new tabs by default and only replaces when explicitly requested", () => {
    expect(shouldReplaceCurrentPanel("new_panel")).toBe(false);
    expect(shouldReplaceCurrentPanel(undefined)).toBe(false);
    expect(shouldReplaceCurrentPanel("current_panel")).toBe(true);
  });

  it("derives friendly titles and affinities from registered panel keys", () => {
    expect(friendlyTitleForKey("jobs_list")).toBe("Jobs List");
    expect(panelAffinityForKey("artifact_detail")).toBe("artifacts");
    expect(panelAffinityForKey("palette_result")).toBe("conversation");
    expect(friendlyTitleForKey("thread_detail")).toBe("Thread");
    expect(panelAffinityForKey("thread_list")).toBe("operations");
    expect(friendlyTitleForKey("goal_detail")).toBe("Goal");
    expect(panelAffinityForKey("goal_list")).toBe("operations");
  });

  it("routes new panels into the focused compatible stack when available", () => {
    const target = resolveTargetStackId({
      panels: [SAMPLE_PANEL()],
      activePanel: SAMPLE_PANEL(),
      requestedAffinity: "operations",
    });
    expect(target).toBe("stack-operations");
  });

  it("falls back to a matching affinity stack when the active stack is incompatible", () => {
    const target = resolveTargetStackId({
      panels: [
        SAMPLE_PANEL({
          panel_id: "conversation-1",
          key: "palette_result",
          title: "Conversation",
          instance_key: "conversation:thread-1",
          active_group_id: "stack-conversation",
          panel_affinity: "conversation",
        }),
        SAMPLE_PANEL({
          panel_id: "artifact-1",
          key: "artifact_detail",
          title: "Artifact Detail",
          instance_key: "artifact:artifact-1",
          active_group_id: "stack-artifacts",
          panel_affinity: "artifacts",
        }),
      ],
      activePanel: SAMPLE_PANEL({
        panel_id: "conversation-1",
        key: "palette_result",
        title: "Conversation",
        instance_key: "conversation:thread-1",
        active_group_id: "stack-conversation",
        panel_affinity: "conversation",
      }),
      requestedAffinity: "artifacts",
    });
    expect(target).toBe("stack-artifacts");
  });
});
