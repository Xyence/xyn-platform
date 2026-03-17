export const PANEL_TYPES = [
  "conversation",
  "composer_detail",
  "goal_list",
  "goal_detail",
  "application_plan_detail",
  "application_detail",
  "thread_list",
  "thread_detail",
  "run_detail",
  "run_list",
  "work_item",
  "entity_list",
  "entity_record",
  "artifact_view",
  "report_view",
  "log_view",
] as const;

export type PanelType = (typeof PANEL_TYPES)[number];

export const PANEL_OBJECT_TYPES = [
  "conversation",
  "goal",
  "application_plan",
  "application",
  "thread",
  "run",
  "work_item",
  "entity_collection",
  "entity_record",
  "artifact",
  "report",
  "log",
  "workspace",
] as const;

export type PanelObjectType = (typeof PANEL_OBJECT_TYPES)[number];

export type PanelCreationSource =
  | "route"
  | "intent"
  | "conversation_action"
  | "activity"
  | "runtime_event"
  | "user_navigation"
  | "restore";

export type Panel = {
  panel_id: string;
  panel_type: PanelType;
  object_type: PanelObjectType;
  object_id: string;
  thread_id: string | null;
  workspace_id: string;
  creation_source: PanelCreationSource;
  created_at: string;
};

export type WorkspaceLayout = {
  workspace_id: string;
  flexlayout_model: unknown;
  panel_ids: string[];
  preset_id?: string | null;
  lock_mode?: "unlocked" | "starting_layout_only" | "partially_locked" | "locked" | null;
  last_updated: string;
};

type PanelIdentityRule = {
  object_type: PanelObjectType;
  requires_thread: boolean;
};

const PANEL_IDENTITY_RULES: Record<PanelType, PanelIdentityRule> = {
  conversation: { object_type: "conversation", requires_thread: true },
  composer_detail: { object_type: "workspace", requires_thread: false },
  goal_list: { object_type: "workspace", requires_thread: false },
  goal_detail: { object_type: "goal", requires_thread: false },
  application_plan_detail: { object_type: "application_plan", requires_thread: false },
  application_detail: { object_type: "application", requires_thread: false },
  thread_list: { object_type: "workspace", requires_thread: false },
  thread_detail: { object_type: "thread", requires_thread: false },
  run_detail: { object_type: "run", requires_thread: false },
  run_list: { object_type: "workspace", requires_thread: false },
  work_item: { object_type: "work_item", requires_thread: false },
  entity_list: { object_type: "entity_collection", requires_thread: false },
  entity_record: { object_type: "entity_record", requires_thread: false },
  artifact_view: { object_type: "artifact", requires_thread: false },
  report_view: { object_type: "report", requires_thread: false },
  log_view: { object_type: "log", requires_thread: false },
};

export function isPanelType(value: unknown): value is PanelType {
  return typeof value === "string" && (PANEL_TYPES as readonly string[]).includes(value);
}

export function validatePanel(panel: Panel): Panel {
  if (!panel.panel_id.trim()) throw new Error("Panel requires panel_id.");
  if (!isPanelType(panel.panel_type)) throw new Error(`Unsupported panel type: ${String(panel.panel_type || "")}`);
  if (!(PANEL_OBJECT_TYPES as readonly string[]).includes(panel.object_type)) {
    throw new Error(`Unsupported panel object type: ${String(panel.object_type || "")}`);
  }
  if (!panel.object_id.trim()) throw new Error("Panel requires durable object_id.");
  if (!panel.workspace_id.trim()) throw new Error("Panel requires workspace_id.");
  const expected = PANEL_IDENTITY_RULES[panel.panel_type];
  if (panel.object_type !== expected.object_type) {
    throw new Error(`Panel type ${panel.panel_type} must target object type ${expected.object_type}.`);
  }
  if (expected.requires_thread && !String(panel.thread_id || "").trim()) {
    throw new Error(`Panel type ${panel.panel_type} requires thread_id.`);
  }
  return panel;
}

export function validateWorkspaceLayout(layout: WorkspaceLayout): WorkspaceLayout {
  if (!String(layout.workspace_id || "").trim()) throw new Error("WorkspaceLayout requires workspace_id.");
  if (!layout.flexlayout_model || typeof layout.flexlayout_model !== "object") {
    throw new Error("WorkspaceLayout requires serialized flexlayout_model.");
  }
  if (!Array.isArray(layout.panel_ids)) throw new Error("WorkspaceLayout requires panel_ids.");
  if (layout.lock_mode != null && !["unlocked", "starting_layout_only", "partially_locked", "locked"].includes(String(layout.lock_mode))) {
    throw new Error("WorkspaceLayout lock_mode is invalid.");
  }
  if (!String(layout.last_updated || "").trim()) throw new Error("WorkspaceLayout requires last_updated.");
  return layout;
}

export function buildPanelId(panel_type: PanelType, object_id: string, thread_id?: string | null): string {
  const base = [panel_type, String(object_id || "").trim(), String(thread_id || "").trim()].filter(Boolean).join(":");
  return base.replace(/[^a-zA-Z0-9:_-]+/g, "-");
}

export function createPanel(input: Omit<Panel, "panel_id" | "created_at"> & { panel_id?: string; created_at?: string }): Panel {
  const panel: Panel = {
    panel_id: input.panel_id || buildPanelId(input.panel_type, input.object_id, input.thread_id),
    panel_type: input.panel_type,
    object_type: input.object_type,
    object_id: input.object_id,
    thread_id: input.thread_id ?? null,
    workspace_id: input.workspace_id,
    creation_source: input.creation_source,
    created_at: input.created_at || new Date().toISOString(),
  };
  return validatePanel(panel);
}
