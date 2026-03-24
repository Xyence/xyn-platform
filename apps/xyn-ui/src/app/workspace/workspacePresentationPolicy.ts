import type { IJsonModel } from "flexlayout-react";
import type { ConsolePanelKey, ConsolePanelSpec } from "../components/console/WorkbenchPanelHost";
import type { ConsolePanelState } from "../state/xynConsoleStore";
import type { Panel, PanelType } from "./panelModel";

export const PANEL_AFFINITIES = ["conversation", "operations", "artifacts", "application", "generic"] as const;
export type PanelAffinity = (typeof PANEL_AFFINITIES)[number];

export const LAYOUT_LOCK_MODES = ["unlocked", "starting_layout_only", "partially_locked", "locked"] as const;
export type LayoutLockMode = (typeof LAYOUT_LOCK_MODES)[number];

export const SCOPE_SIGNAL_STRATEGIES = ["header_compact", "tab_compact", "panel_banner"] as const;
export type ScopeSignalStrategy = (typeof SCOPE_SIGNAL_STRATEGIES)[number];

export const OPEN_BEHAVIORS = ["focus_existing_or_open_new", "replace_current", "duplicate_allowed"] as const;
export type OpenBehavior = (typeof OPEN_BEHAVIORS)[number];

export type PanelSeedDefinition = {
  panel_type: PanelType;
  object_id: string;
  thread_id?: string | null;
  affinity?: PanelAffinity;
  title_override?: string;
  constraints?: Record<string, unknown>;
};

export type ApplicationViewPreset = {
  preset_id: string;
  app_id: string;
  name: string;
  description: string;
  layout_mode: "starting_layout" | "locked_layout";
  flexlayout_model: IJsonModel;
  panel_seed_definitions: PanelSeedDefinition[];
  allowed_panel_affinities: PanelAffinity[];
  lock_mode: LayoutLockMode;
  visibility: "workspace" | "application";
  is_default_landing_view: boolean;
};

export type WorkspacePresentationPolicy = {
  default_open_behavior: OpenBehavior;
  affinity_rules: Record<string, PanelAffinity>;
  title_rules: Record<string, string>;
  workspace_signal_strategy: ScopeSignalStrategy;
  application_view_presets: ApplicationViewPreset[];
  layout_lock_rules: {
    default_lock_mode: LayoutLockMode;
  };
};

export const DEFAULT_STACK_IDS: Record<PanelAffinity, string> = {
  conversation: "stack-conversation",
  operations: "stack-operations",
  artifacts: "stack-artifacts",
  application: "stack-application",
  generic: "stack-operations",
};

export const FRIENDLY_PANEL_TITLES: Record<string, string> = {
  platform_settings: "Platform Settings",
  workspaces: "Workspaces",
  composer_detail: "Composer",
  goal_list: "Goals",
  goal_detail: "Goal",
  campaign_list: "Campaigns",
  campaign_detail: "Campaign",
  application_plan_detail: "Application Plan",
  application_detail: "Application",
  solution_list: "Solutions",
  solution_detail: "Solution",
  thread_list: "Threads",
  thread_detail: "Thread",
  runs: "Active Runs",
  drafts_list: "Drafts",
  draft_detail: "Build Draft",
  jobs_list: "Jobs List",
  job_detail: "Pipeline Job",
  work_items: "Work Items",
  work_item_detail: "Work Item",
  palette_result: "Conversation",
  app_builder_artifact_list: "Artifacts",
  run_detail: "Run Detail",
  artifact_list: "Artifacts",
  artifact_detail: "Artifact Detail",
  artifact_raw_json: "Artifact JSON",
  artifact_files: "Artifact Files",
  ems_devices: "EMS Devices",
  ems_registrations: "EMS Registrations",
  ems_device_status_rollup: "Device Status Rollup",
  ems_registrations_timeseries: "Registrations Timeseries",
  ems_dataset_schema: "Dataset Schema",
  ems_unregistered_devices: "Unregistered Devices",
  ems_registrations_time: "Registrations",
  ems_device_statuses: "Device Statuses",
  record_detail: "Record Detail",
  local_provision_result: "Local Provision Result",
};

const AFFINITY_RULES: Record<string, PanelAffinity> = {
  conversation: "conversation",
  palette_result: "conversation",
  composer_detail: "application",
  goal_list: "operations",
  goal_detail: "operations",
  campaign_list: "operations",
  campaign_detail: "operations",
  application_plan_detail: "application",
  application_detail: "application",
  solution_list: "application",
  solution_detail: "application",
  thread_list: "operations",
  thread_detail: "operations",
  runs: "operations",
  run_detail: "operations",
  jobs_list: "operations",
  job_detail: "operations",
  work_items: "operations",
  work_item_detail: "operations",
  drafts_list: "operations",
  draft_detail: "operations",
  workspaces: "application",
  platform_settings: "application",
  artifact_list: "artifacts",
  app_builder_artifact_list: "artifacts",
  artifact_detail: "artifacts",
  artifact_raw_json: "artifacts",
  artifact_files: "artifacts",
  report_view: "application",
  record_detail: "generic",
  work_item: "operations",
  entity_list: "application",
  entity_record: "application",
  artifact_view: "artifacts",
  log_view: "artifacts",
};

const DEFAULT_PRESETS: ApplicationViewPreset[] = [
  {
    preset_id: "workbench.default",
    app_id: "core.workbench",
    name: "Workbench Default",
    description: "Split operational workspace with conversation, operations, and artifact stacks.",
    layout_mode: "starting_layout",
    lock_mode: "starting_layout_only",
    visibility: "workspace",
    is_default_landing_view: true,
    allowed_panel_affinities: ["conversation", "operations", "artifacts", "application", "generic"],
    panel_seed_definitions: [],
    flexlayout_model: {
      global: {
        tabEnableClose: true,
        splitterSize: 8,
      },
      layout: {
        type: "row",
        id: "workspace-root",
        weight: 100,
        children: [
          {
            type: "tabset",
            id: DEFAULT_STACK_IDS.conversation,
            name: "Conversation",
            weight: 24,
            children: [],
          },
          {
            type: "tabset",
            id: DEFAULT_STACK_IDS.application,
            name: "Workspace",
            weight: 22,
            children: [],
          },
          {
            type: "tabset",
            id: DEFAULT_STACK_IDS.operations,
            name: "Operations",
            weight: 32,
            children: [],
          },
          {
            type: "tabset",
            id: DEFAULT_STACK_IDS.artifacts,
            name: "Artifacts",
            weight: 22,
            children: [],
          },
        ],
      },
    },
  },
];

export const DEFAULT_WORKSPACE_PRESENTATION_POLICY: WorkspacePresentationPolicy = {
  default_open_behavior: "focus_existing_or_open_new",
  affinity_rules: AFFINITY_RULES,
  title_rules: FRIENDLY_PANEL_TITLES,
  workspace_signal_strategy: "header_compact",
  application_view_presets: DEFAULT_PRESETS,
  layout_lock_rules: {
    default_lock_mode: "starting_layout_only",
  },
};

export function isLayoutLockMode(value: unknown): value is LayoutLockMode {
  return typeof value === "string" && (LAYOUT_LOCK_MODES as readonly string[]).includes(value);
}

export function panelAffinityForKey(key: string): PanelAffinity {
  return AFFINITY_RULES[String(key || "").trim()] || "generic";
}

export function panelAffinityForState(panel: Pick<ConsolePanelState, "key" | "panel_object">): PanelAffinity {
  return panel.panel_object?.panel_type ? panelAffinityForKey(panel.panel_object.panel_type) : panelAffinityForKey(panel.key);
}

function titleCaseToken(value: string): string {
  return String(value || "")
    .split(/[_\-\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function friendlyTitleForKey(key: string): string {
  return FRIENDLY_PANEL_TITLES[String(key || "").trim()] || titleCaseToken(String(key || "").trim()) || "Panel";
}

export function friendlyTitleForPanel(input: {
  key: string;
  panel_type?: string | null;
  title?: string | null;
  instance_key?: string | null;
  panel_object?: Panel | null;
}): string {
  const explicit = String(input.title || "").trim();
  if (explicit && explicit !== input.key) return explicit;
  const mapped = friendlyTitleForKey(input.key);
  if (mapped) return mapped;
  const instanceKey = String(input.instance_key || "").trim();
  if (instanceKey) {
    const token = instanceKey.includes(":") ? instanceKey.split(":", 1)[0] : instanceKey;
    const asTitle = titleCaseToken(token);
    if (asTitle) return asTitle;
  }
  if (input.panel_object?.panel_type) {
    return titleCaseToken(input.panel_object.panel_type);
  }
  return titleCaseToken(input.key);
}

export function panelStackIdForAffinity(affinity: PanelAffinity): string {
  return DEFAULT_STACK_IDS[affinity];
}

export function findOpenPanelForObject(
  panels: ConsolePanelState[],
  predicate: (panel: ConsolePanelState) => boolean
): ConsolePanelState | null {
  return panels.find(predicate) || null;
}

export function buildPresetTabs(
  preset: ApplicationViewPreset,
  panels: ConsolePanelState[],
  activePanelId: string | null
): IJsonModel {
  const model = JSON.parse(JSON.stringify(preset.flexlayout_model)) as IJsonModel;
  const layout = model.layout as unknown as Record<string, unknown>;
  const children = Array.isArray(layout.children) ? (layout.children as Array<Record<string, unknown>>) : [];
  const grouped = new Map<string, ConsolePanelState[]>();
  children.forEach((child) => {
    if (typeof child.id === "string") grouped.set(child.id, []);
  });
  panels.forEach((panel) => {
    const affinity = panel.active_group_id && grouped.has(panel.active_group_id) ? panel.active_group_id : panelStackIdForAffinity(panel.panel_affinity || panelAffinityForState(panel));
    const next = grouped.get(affinity) || [];
    next.push(panel);
    grouped.set(affinity, next);
  });
  children.forEach((child) => {
    const stackId = String(child.id || "");
    const stackPanels = grouped.get(stackId) || [];
    child.children = stackPanels.map((panel) => ({
      type: "tab",
      id: panel.panel_id,
      name: friendlyTitleForPanel(panel),
      component: "workspace-panel",
      enableClose: true,
      config: { panel_id: panel.panel_id },
    }));
    const selected = stackPanels.findIndex((panel) => panel.panel_id === activePanelId);
    child.selected = selected >= 0 ? selected : 0;
  });
  return model;
}

export function defaultWorkspacePreset(): ApplicationViewPreset {
  return DEFAULT_WORKSPACE_PRESENTATION_POLICY.application_view_presets.find((preset) => preset.is_default_landing_view) || DEFAULT_PRESETS[0];
}

export function titleForSeed(seed: PanelSeedDefinition): string {
  return FRIENDLY_PANEL_TITLES[seed.panel_type] || titleCaseToken(seed.panel_type);
}

export function shouldReplaceCurrentPanel(openIn?: "current_panel" | "new_panel" | "side_by_side"): boolean {
  return openIn === "current_panel";
}

export function shouldFocusExistingPanel(existing: ConsolePanelState | null): boolean {
  return Boolean(existing);
}

export function resolveTargetStackId(input: {
  panels: ConsolePanelState[];
  activePanel: ConsolePanelState | null;
  requestedAffinity: PanelAffinity;
  compatibleAffinities?: PanelAffinity[];
}): string {
  const compatible = new Set([input.requestedAffinity, ...(input.compatibleAffinities || [])]);
  if (input.activePanel && compatible.has(input.activePanel.panel_affinity || panelAffinityForState(input.activePanel))) {
    return input.activePanel.active_group_id || panelStackIdForAffinity(input.requestedAffinity);
  }
  const matching = input.panels.find((panel) => compatible.has(panel.panel_affinity || panelAffinityForState(panel)) && panel.active_group_id);
  if (matching?.active_group_id) return matching.active_group_id;
  return panelStackIdForAffinity(input.requestedAffinity);
}
