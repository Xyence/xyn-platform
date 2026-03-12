import type { ConsolePanelKey } from "../components/console/WorkbenchPanelHost";
import { type Panel, type PanelType, isPanelType, validatePanel } from "./panelModel";
import type { PanelAffinity } from "./workspacePresentationPolicy";
import { panelAffinityForKey } from "./workspacePresentationPolicy";

export type RegisteredPanelDefinition = {
  panel_type: PanelType;
  console_key: ConsolePanelKey;
  title: string;
  affinity: PanelAffinity;
};

const registry = new Map<PanelType, RegisteredPanelDefinition>();

export function registerPanelType(definition: RegisteredPanelDefinition) {
  registry.set(definition.panel_type, definition);
}

export function getRegisteredPanel(panelType: PanelType): RegisteredPanelDefinition | null {
  return registry.get(panelType) || null;
}

export function resolvePanelComponent(panel: Panel): RegisteredPanelDefinition {
  validatePanel(panel);
  const definition = registry.get(panel.panel_type);
  if (!definition) {
    throw new Error(`Unregistered panel type: ${panel.panel_type}`);
  }
  return definition;
}

export function validatePanelObject(input: unknown): Panel {
  if (!input || typeof input !== "object") throw new Error("Panel object must be an object.");
  const candidate = input as Panel;
  if (!isPanelType(candidate.panel_type)) {
    throw new Error(`Unsupported panel type: ${String(candidate.panel_type || "")}`);
  }
  return validatePanel(candidate);
}

const DEFAULT_PANEL_DEFINITIONS = [
  { panel_type: "conversation", console_key: "palette_result", title: "Conversation", affinity: panelAffinityForKey("palette_result") },
  { panel_type: "thread_list", console_key: "thread_list", title: "Threads", affinity: panelAffinityForKey("thread_list") },
  { panel_type: "thread_detail", console_key: "thread_detail", title: "Thread", affinity: panelAffinityForKey("thread_detail") },
  { panel_type: "run_detail", console_key: "run_detail", title: "Run Detail", affinity: panelAffinityForKey("run_detail") },
  { panel_type: "run_list", console_key: "runs", title: "Active Runs", affinity: panelAffinityForKey("runs") },
  { panel_type: "work_item", console_key: "work_item_detail", title: "Work Item", affinity: panelAffinityForKey("work_item_detail") },
  { panel_type: "entity_list", console_key: "palette_result", title: "Entity List", affinity: panelAffinityForKey("palette_result") },
  { panel_type: "entity_record", console_key: "record_detail", title: "Record Detail", affinity: panelAffinityForKey("record_detail") },
  { panel_type: "artifact_view", console_key: "artifact_detail", title: "Artifact", affinity: panelAffinityForKey("artifact_detail") },
  { panel_type: "report_view", console_key: "palette_result", title: "Report", affinity: panelAffinityForKey("palette_result") },
  { panel_type: "log_view", console_key: "artifact_raw_json", title: "Log", affinity: panelAffinityForKey("artifact_raw_json") },
] satisfies RegisteredPanelDefinition[];

DEFAULT_PANEL_DEFINITIONS.forEach(registerPanelType);
