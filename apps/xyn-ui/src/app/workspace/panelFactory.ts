import type { ConsolePanelSpec } from "../components/console/WorkbenchPanelHost";
import { createPanel, type Panel, type PanelCreationSource, type PanelType } from "./panelModel";
import { resolvePanelComponent, validatePanelObject } from "./panelRegistry";

type CreatePanelInput = {
  panel_type: PanelType;
  object_id: string;
  workspace_id: string;
  thread_id?: string | null;
  creation_source: PanelCreationSource;
  title?: string;
  params?: Record<string, unknown>;
};

function panelToConsoleSpec(panel: Panel, params?: Record<string, unknown>, title?: string): ConsolePanelSpec {
  const registered = resolvePanelComponent(panel);
  const nextParams = { ...(params || {}) };
  if (panel.panel_type === "run_detail") nextParams.run_id = panel.object_id;
  if (panel.panel_type === "artifact_view" || panel.panel_type === "log_view") nextParams.slug = panel.object_id;
  if (panel.panel_type === "entity_record") nextParams.entity_id = panel.object_id;
  if (panel.panel_type === "entity_list" || panel.panel_type === "report_view" || panel.panel_type === "conversation") {
    nextParams.object_id = panel.object_id;
  }
  return {
    panel_id: panel.panel_id,
    title: title || registered.title,
    key: registered.console_key,
    params: nextParams,
    open_in: "new_panel",
  };
}

export function createWorkspacePanel(input: CreatePanelInput): Panel {
  const object_type =
    input.panel_type === "conversation"
      ? "conversation"
      : input.panel_type === "run_detail"
        ? "run"
        : input.panel_type === "run_list"
          ? "workspace"
          : input.panel_type === "work_item"
            ? "work_item"
            : input.panel_type === "entity_list"
              ? "entity_collection"
              : input.panel_type === "entity_record"
                ? "entity_record"
                : input.panel_type === "artifact_view"
                  ? "artifact"
                  : input.panel_type === "report_view"
                    ? "report"
                    : "log";
  return createPanel({
    panel_type: input.panel_type,
    object_type,
    object_id: input.object_id,
    thread_id: input.thread_id ?? null,
    workspace_id: input.workspace_id,
    creation_source: input.creation_source,
  });
}

export function openPanel(panel: Panel, params?: Record<string, unknown>, title?: string): ConsolePanelSpec {
  return panelToConsoleSpec(validatePanelObject(panel), params, title);
}

export function restorePanel(panel: Panel, params?: Record<string, unknown>, title?: string): ConsolePanelSpec {
  return panelToConsoleSpec(validatePanelObject(panel), params, title);
}
