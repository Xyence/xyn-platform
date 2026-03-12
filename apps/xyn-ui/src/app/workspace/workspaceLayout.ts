import type { IJsonModel } from "flexlayout-react";
import type { ConsolePanelState } from "../state/xynConsoleStore";
import type { WorkspaceLayout } from "./panelModel";
import { validateWorkspaceLayout } from "./panelModel";

const STORAGE_PREFIX = "xyn.workspace.layout.v1";

export function workspaceLayoutStorageKey(workspaceId: string): string {
  return `${STORAGE_PREFIX}:${workspaceId}`;
}

export function buildFlexLayoutModel(panels: ConsolePanelState[], activePanelId: string | null): IJsonModel {
  const tabs = panels.map((panel) => ({
    type: "tab",
    id: panel.panel_id,
    name: panel.title || panel.key,
    component: "workspace-panel",
    enableClose: true,
    config: {
      panel_id: panel.panel_id,
    },
  }));
  return {
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
          id: "workspace-main",
          weight: 100,
          selected: Math.max(
            0,
            tabs.findIndex((tab) => String(tab.id || "") === String(activePanelId || ""))
          ),
          children: tabs,
        },
      ],
    },
  };
}

export function buildWorkspaceLayout(workspaceId: string, panels: ConsolePanelState[], activePanelId: string | null): WorkspaceLayout {
  return validateWorkspaceLayout({
    workspace_id: workspaceId,
    flexlayout_model: buildFlexLayoutModel(panels, activePanelId),
    panel_ids: panels.map((panel) => panel.panel_id),
    last_updated: new Date().toISOString(),
  });
}

function collectTabIds(node: Record<string, unknown> | null | undefined, acc: string[] = []): string[] {
  if (!node || typeof node !== "object") return acc;
  if (node.type === "tab" && typeof node.id === "string") {
    acc.push(node.id);
  }
  const children = Array.isArray(node.children) ? (node.children as Record<string, unknown>[]) : [];
  children.forEach((child) => collectTabIds(child, acc));
  return acc;
}

function syncNode(
  node: Record<string, unknown>,
  panelsById: Map<string, ConsolePanelState>,
  activePanelId: string | null,
  added: { value: boolean }
): Record<string, unknown> {
  const children = Array.isArray(node.children) ? (node.children as Record<string, unknown>[]) : [];
  if (node.type === "tabset") {
    const nextChildren = children
      .map((child) => syncNode(child, panelsById, activePanelId, added))
      .filter((child) => child.type !== "tab" || panelsById.has(String(child.id || "")));
    if (!added.value) {
      const existing = new Set(nextChildren.map((child) => String(child.id || "")));
      panelsById.forEach((panel, panelId) => {
        if (existing.has(panelId)) return;
        nextChildren.push({
          type: "tab",
          id: panel.panel_id,
          name: panel.title || panel.key,
          component: "workspace-panel",
          enableClose: true,
          config: { panel_id: panel.panel_id },
        });
      });
      added.value = true;
    }
    const selected = nextChildren.findIndex((child) => String(child.id || "") === String(activePanelId || ""));
    return {
      ...node,
      selected: selected >= 0 ? selected : typeof node.selected === "number" ? node.selected : 0,
      children: nextChildren,
    };
  }
  return {
    ...node,
    children: children.map((child) => syncNode(child, panelsById, activePanelId, added)),
  };
}

export function syncFlexLayoutModel(
  currentModel: IJsonModel | null,
  panels: ConsolePanelState[],
  activePanelId: string | null
): IJsonModel {
  if (!currentModel || typeof currentModel !== "object") {
    return buildFlexLayoutModel(panels, activePanelId);
  }
  const panelsById = new Map(panels.map((panel) => [panel.panel_id, panel] as const));
  const root = currentModel.layout && typeof currentModel.layout === "object" ? (currentModel.layout as unknown as Record<string, unknown>) : null;
  if (!root) {
    return buildFlexLayoutModel(panels, activePanelId);
  }
  const nextLayout = syncNode(root, panelsById, activePanelId, { value: false });
  const nextIds = new Set(collectTabIds(nextLayout));
  const missing = panels.filter((panel) => !nextIds.has(panel.panel_id));
  if (missing.length) {
    return buildFlexLayoutModel(panels, activePanelId);
  }
  return {
    ...(currentModel || {}),
    global: typeof currentModel.global === "object" && currentModel.global ? currentModel.global : { tabEnableClose: true, splitterSize: 8 },
    layout: nextLayout,
  } as unknown as IJsonModel;
}

export function readWorkspaceLayout(workspaceId: string): WorkspaceLayout | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(workspaceLayoutStorageKey(workspaceId));
    if (!raw) return null;
    return validateWorkspaceLayout(JSON.parse(raw) as WorkspaceLayout);
  } catch {
    return null;
  }
}

export function writeWorkspaceLayout(layout: WorkspaceLayout) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(workspaceLayoutStorageKey(layout.workspace_id), JSON.stringify(layout));
}
