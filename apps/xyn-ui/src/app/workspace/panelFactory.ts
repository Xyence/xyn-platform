import type { ConsolePanelSpec } from "../components/console/WorkbenchPanelHost";
import { createPanel, type Panel, type PanelCreationSource, type PanelType } from "./panelModel";
import { resolvePanelComponent, validatePanelObject } from "./panelRegistry";
import { friendlyTitleForPanel } from "./workspacePresentationPolicy";

type CreatePanelInput = {
  panel_type: PanelType;
  object_id: string;
  workspace_id: string;
  thread_id?: string | null;
  creation_source: PanelCreationSource;
  title?: string;
  params?: Record<string, unknown>;
};

function parseRuntimeArtifactObjectId(objectId: string): { run_id: string; artifact_id: string } | null {
  const match = String(objectId || "").match(/^runtime-run-artifact:([^:]+):([^:]+)$/);
  if (!match) return null;
  return { run_id: match[1], artifact_id: match[2] };
}

function panelToConsoleSpec(panel: Panel, params?: Record<string, unknown>, title?: string): ConsolePanelSpec {
  const registered = resolvePanelComponent(panel);
  const nextParams = { ...(params || {}) };
  if (panel.panel_type === "run_detail") nextParams.run_id = panel.object_id;
  if (panel.panel_type === "goal_detail") nextParams.goal_id = panel.object_id;
  if (panel.panel_type === "application_plan_detail") nextParams.application_plan_id = panel.object_id;
  if (panel.panel_type === "application_detail") nextParams.application_id = panel.object_id;
  if (panel.panel_type === "goal_list") nextParams.workspace_id = panel.workspace_id;
  if (panel.panel_type === "thread_detail") nextParams.thread_id = panel.object_id;
  if (panel.panel_type === "thread_list") nextParams.workspace_id = panel.workspace_id;
  if (panel.panel_type === "work_item") nextParams.work_item_id = panel.object_id;
  if (panel.panel_type === "artifact_view" || panel.panel_type === "log_view") {
    const runtimeArtifact = parseRuntimeArtifactObjectId(panel.object_id);
    if (runtimeArtifact) {
      nextParams.runtime_run_id = runtimeArtifact.run_id;
      nextParams.runtime_artifact_id = runtimeArtifact.artifact_id;
    } else {
      nextParams.slug = panel.object_id;
    }
  }
  if (panel.panel_type === "entity_record") nextParams.entity_id = panel.object_id;
  if (panel.panel_type === "entity_list" || panel.panel_type === "report_view" || panel.panel_type === "conversation") {
    nextParams.object_id = panel.object_id;
  }
  return {
    panel_id: panel.panel_id,
    title: friendlyTitleForPanel({
      key: registered.console_key,
      title: title || registered.title,
      panel_object: panel,
    }),
    key: registered.console_key,
    params: nextParams,
    open_in: "new_panel",
  };
}

export function createWorkspacePanel(input: CreatePanelInput): Panel {
  let object_type: Panel["object_type"] = "log";
  if (input.panel_type === "conversation") object_type = "conversation";
  else if (input.panel_type === "goal_list") object_type = "workspace";
  else if (input.panel_type === "goal_detail") object_type = "goal";
  else if (input.panel_type === "application_plan_detail") object_type = "application_plan";
  else if (input.panel_type === "application_detail") object_type = "application";
  else if (input.panel_type === "thread_list") object_type = "workspace";
  else if (input.panel_type === "thread_detail") object_type = "thread";
  else if (input.panel_type === "run_detail") object_type = "run";
  else if (input.panel_type === "run_list") object_type = "workspace";
  else if (input.panel_type === "work_item") object_type = "work_item";
  else if (input.panel_type === "entity_list") object_type = "entity_collection";
  else if (input.panel_type === "entity_record") object_type = "entity_record";
  else if (input.panel_type === "artifact_view") object_type = "artifact";
  else if (input.panel_type === "report_view") object_type = "report";
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
