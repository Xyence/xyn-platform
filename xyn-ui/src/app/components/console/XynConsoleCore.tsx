import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { AlertTriangle, CheckCircle2, CircleHelp, Wrench } from "lucide-react";
import { getRecentArtifacts } from "../../../api/xyn";
import { provisionLocalXynInstance } from "../../../api/xyn";
import type { RecentArtifactItem, XynIntentResolutionResult } from "../../../api/types";
import { getEntityTypeForDataset } from "../../../components/canvas/datasetEntityRegistry";
import { toWorkspacePath } from "../../routing/workspaceRouting";
import { useXynConsole } from "../../state/xynConsoleStore";
import RecentArtifactsMiniTable from "./RecentArtifactsMiniTable";
import ConsolePromptCard from "./ConsolePromptCard";
import ConsoleGuidancePanel from "./ConsoleGuidancePanel";
import ConsoleResultPanel from "./ConsoleResultPanel";

type ConsoleMode = "overlay" | "page";

type Props = {
  mode: ConsoleMode;
  onRequestClose?: () => void;
  onOpenPanel?: (panelKey: string, params?: Record<string, unknown>) => void;
};

type ArtifactStructuredQuery = {
  entity: "artifacts";
  filters: Array<{ field: string; op: "eq" | "neq" | "contains" | "in" | "gte" | "lte" | "gt" | "lt"; value: unknown }>;
  sort: Array<{ field: string; dir: "asc" | "desc" }>;
  limit: number;
  offset: number;
};

type ResolvedPanelCommand =
  | { panelKey: "artifact_list"; params: { namespace?: string; query?: ArtifactStructuredQuery; query_error?: string } }
  | { panelKey: "workspaces"; params: { query?: Record<string, unknown>; query_error?: string } }
  | { panelKey: "runs"; params: { query?: Record<string, unknown>; query_error?: string } }
  | { panelKey: "run_detail"; params: { run_id: string } }
  | { panelKey: "platform_settings"; params: { workspace_id?: string } }
  | { panelKey: "artifact_detail"; params: { slug: string } }
  | { panelKey: "artifact_raw_json"; params: { slug: string } }
  | { panelKey: "artifact_files"; params: { slug: string } }
  | { panelKey: "ems_devices"; params: { query?: Record<string, unknown>; query_error?: string } }
  | { panelKey: "ems_registrations"; params: { query?: Record<string, unknown>; query_error?: string } }
  | { panelKey: "ems_device_status_rollup"; params: Record<string, never> }
  | { panelKey: "ems_registrations_timeseries"; params: { hours: number } }
  | { panelKey: "ems_dataset_schema"; params: { dataset: string } };

type UiActionEnvelope = {
  type: "ui.action";
  action: {
    name:
      | "canvas.open_table"
      | "canvas.update_table_query"
      | "canvas.open_detail"
      | "canvas.select_rows"
      | "canvas.set_active_panel"
      | "canvas.close_panel";
    target?: {
      panel_id?: string;
      instance_key?: string;
    };
    params: Record<string, unknown>;
  };
};

type ConsoleCanvasContext = {
  view_type?: "table" | "detail";
  dataset?: {
    name?: string;
    primary_key?: string;
    columns?: Array<Record<string, unknown>>;
  };
  query?: Record<string, unknown>;
  selection?: {
    selected_row_ids?: string[];
    focused_row_id?: string | null;
    row_order_ids?: string[];
  };
  pagination?: {
    limit?: number;
    offset?: number;
    total_count?: number;
  };
  entity_type?: string;
  entity_id?: string;
  available_tabs?: string[];
  active_tab?: string;
  ui?: {
    active_panel_id?: string;
    panel_id?: string;
  };
};

function defaultArtifactStructuredQuery(): ArtifactStructuredQuery {
  return {
    entity: "artifacts",
    filters: [],
    sort: [{ field: "updated_at", dir: "desc" }],
    limit: 50,
    offset: 0,
  };
}

export function resolvePanelCommand(input: string): ResolvedPanelCommand | null {
  const raw = String(input || "").trim();
  if (!raw) return null;
  const normalized = raw.toLowerCase();

  let match = normalized.match(/^list\s+([a-z0-9_.-]+)\s+artifacts$/);
  if (match && match[1]) {
    return { panelKey: "artifact_list", params: { namespace: match[1] } };
  }
  if (/^list\s+artifacts$/.test(normalized) || /^show\s+artifacts$/.test(normalized)) {
    return { panelKey: "artifact_list", params: {} };
  }
  if (/^open\s+platform\s+settings$/.test(normalized)) {
    return { panelKey: "platform_settings", params: {} };
  }
  if (/^list\s+workspaces$/.test(normalized)) {
    return {
      panelKey: "workspaces",
      params: {
        query: {
          entity: "workspaces",
          filters: [],
          sort: [{ field: "name", dir: "asc" }],
          limit: 50,
          offset: 0,
        },
      },
    };
  }
  if (/^show\s+runs$/.test(normalized)) {
    return {
      panelKey: "runs",
      params: {
        query: {
          entity: "runs",
          filters: [],
          sort: [{ field: "created_at", dir: "desc" }],
          limit: 50,
          offset: 0,
        },
      },
    };
  }
  if (/^show\s+recent\s+runs$/.test(normalized)) {
    return {
      panelKey: "runs",
      params: {
        query: {
          entity: "runs",
          filters: [{ field: "created_at", op: "gte", value: "now-24h" }],
          sort: [{ field: "created_at", dir: "desc" }],
          limit: 50,
          offset: 0,
        },
      },
    };
  }
  if (/^show\s+failed\s+runs$/.test(normalized)) {
    return {
      panelKey: "runs",
      params: {
        query: {
          entity: "runs",
          filters: [{ field: "status", op: "eq", value: "failed" }],
          sort: [{ field: "created_at", dir: "desc" }],
          limit: 50,
          offset: 0,
        },
      },
    };
  }
  match = normalized.match(/^describe\s+run\s+([a-z0-9-]+)$/);
  if (match && match[1]) {
    return { panelKey: "run_detail", params: { run_id: match[1] } };
  }
  if (/^show\s+installed\s+artifacts$/.test(normalized)) {
    return {
      panelKey: "artifact_list",
      params: {
        query: {
          ...defaultArtifactStructuredQuery(),
          filters: [{ field: "installed", op: "eq", value: true }],
        },
      },
    };
  }
  if (/^show\s+artifacts\s+updated\s+in\s+the\s+last\s+hour$/.test(normalized)) {
    return {
      panelKey: "artifact_list",
      params: {
        query: {
          ...defaultArtifactStructuredQuery(),
          filters: [{ field: "updated_at", op: "gte", value: "now-1h" }],
          sort: [{ field: "updated_at", dir: "desc" }],
        },
      },
    };
  }
  match = normalized.match(/^show\s+artifacts\s+of\s+kind\s+([a-z0-9_.-]+)$/);
  if (match && match[1]) {
    return {
      panelKey: "artifact_list",
      params: {
        query: {
          ...defaultArtifactStructuredQuery(),
          filters: [{ field: "kind", op: "eq", value: match[1] }],
        },
      },
    };
  }
  match = normalized.match(/^show\s+artifacts\s+in\s+namespace\s+([a-z0-9_.-]+)$/);
  if (match && match[1]) {
    return {
      panelKey: "artifact_list",
      params: {
        query: {
          ...defaultArtifactStructuredQuery(),
          filters: [{ field: "namespace", op: "eq", value: match[1] }],
        },
      },
    };
  }
  if (/^show\s+artifacts\b/.test(normalized) && !/^show\s+artifacts$/.test(normalized)) {
    return {
      panelKey: "artifact_list",
      params: {
        query_error: "Unsupported filter field. Try: namespace, kind, updated_at, installed.",
      },
    };
  }
  match = normalized.match(/^open\s+artifact\s+([a-z0-9_.-]+)$/);
  if (match && match[1]) {
    return { panelKey: "artifact_detail", params: { slug: match[1] } };
  }
  match = normalized.match(/^edit\s+artifact\s+([a-z0-9_.-]+)\s+raw$/);
  if (match && match[1]) {
    return { panelKey: "artifact_raw_json", params: { slug: match[1] } };
  }
  match = normalized.match(/^edit\s+artifact\s+([a-z0-9_.-]+)\s+files$/);
  if (match && match[1]) {
    return { panelKey: "artifact_files", params: { slug: match[1] } };
  }
  if (/^show\s+unregistered\s+devices$/.test(normalized)) {
    return {
      panelKey: "ems_devices",
      params: {
        query: {
          entity: "ems_devices",
          filters: [{ field: "state", op: "eq", value: "unregistered" }],
          sort: [{ field: "created_at", dir: "desc" }],
          limit: 50,
          offset: 0,
        },
      },
    };
  }
  match = normalized.match(/^show\s+devices\s+with\s+state\s+([a-z0-9_-]+)$/);
  if (match && match[1]) {
    return {
      panelKey: "ems_devices",
      params: {
        query: {
          entity: "ems_devices",
          filters: [{ field: "state", op: "eq", value: match[1] }],
          sort: [{ field: "created_at", dir: "desc" }],
          limit: 50,
          offset: 0,
        },
      },
    };
  }
  match = raw.match(/^show\s+devices\s+for\s+customer\s+(.+)$/i);
  if (match && match[1]) {
    const customer = String(match[1]).trim();
    return {
      panelKey: "ems_devices",
      params: {
        query: {
          entity: "ems_devices",
          filters: [{ field: "customer", op: "contains", value: customer }],
          sort: [{ field: "updated_at", dir: "desc" }],
          limit: 50,
          offset: 0,
        },
      },
    };
  }
  match = normalized.match(/^show\s+devices\s+with\s+([a-z0-9_-]+)\s+(.+)$/);
  if (match && match[1]) {
    return {
      panelKey: "ems_devices",
      params: {
        query_error: "Unknown devices field. Valid fields: state, customer, workspace, model, serial, mac.",
      },
    };
  }
  match = normalized.match(/^show\s+registrations\s+in\s+the\s+past\s+(\d+)\s+hours?$/);
  if (match && match[1]) {
    const hours = Math.max(1, Math.min(Number(match[1]) || 24, 168));
    return {
      panelKey: "ems_registrations",
      params: {
        query: {
          entity: "ems_registrations",
          filters: [{ field: "registered_at", op: "gte", value: `now-${hours}h` }],
          sort: [{ field: "registered_at", dir: "desc" }],
          limit: 50,
          offset: 0,
        },
      },
    };
  }
  if (/^show\s+device\s+statuses$/.test(normalized)) {
    return { panelKey: "ems_device_status_rollup", params: {} };
  }
  match = normalized.match(/^show\s+registrations\s+timeseries\s+last\s+(\d+)\s+hours?$/);
  if (match && match[1]) {
    const hours = Math.max(1, Math.min(Number(match[1]) || 24, 168));
    return { panelKey: "ems_registrations_timeseries", params: { hours } };
  }
  match = normalized.match(/^describe\s+dataset\s+([a-z0-9_-]+)$/);
  if (match && match[1]) {
    return { panelKey: "ems_dataset_schema", params: { dataset: match[1] } };
  }
  return null;
}

function stringifyValue(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function shortArtifactId(id: string): string {
  if (!id) return "";
  return id.length > 12 ? id.slice(0, 12) : id;
}

function parseDurationToRelativeHours(input: string): number | null {
  const match = String(input || "")
    .trim()
    .toLowerCase()
    .match(/^(\d+)\s*(h|hr|hrs|hour|hours|d|day|days)$/);
  if (!match || !match[1] || !match[2]) return null;
  const amount = Number(match[1]);
  if (!Number.isFinite(amount) || amount <= 0) return null;
  if (match[2].startsWith("d")) return amount * 24;
  return amount;
}

function toLowerColumns(context: ConsoleCanvasContext): string[] {
  return (context.dataset?.columns || [])
    .map((column) => String(column.key || "").trim().toLowerCase())
    .filter(Boolean);
}

function inferSearchField(context: ConsoleCanvasContext): string {
  const cols = context.dataset?.columns || [];
  const preferred = ["name", "slug", "serial", "customer", "workspace", "model", "mac"];
  for (const key of preferred) {
    const hit = cols.find((entry) => String(entry.key || "").toLowerCase() === key && Boolean(entry.searchable));
    if (hit?.key) return String(hit.key);
  }
  const anySearchable = cols.find((entry) => Boolean(entry.searchable));
  if (anySearchable?.key) return String(anySearchable.key);
  return String(context.dataset?.primary_key || "slug");
}

function panelKeyForDataset(dataset: string): ResolvedPanelCommand["panelKey"] {
  if (dataset === "workspaces") return "workspaces";
  if (dataset === "runs") return "runs";
  if (dataset === "artifacts") return "artifact_list";
  if (dataset === "ems_devices") return "ems_devices";
  if (dataset === "ems_registrations") return "ems_registrations";
  if (dataset === "ems_device_status_rollup") return "ems_device_status_rollup";
  if (dataset === "ems_registrations_timeseries") return "ems_registrations_timeseries";
  return "artifact_list";
}

function parseProvisionLocalCommand(input: string): { name?: string; jobPrompt?: string; repoRef?: string } | null {
  const raw = String(input || "").trim();
  if (!raw) return null;
  const lower = raw.toLowerCase();
  if (!lower.startsWith("provision local xyn instance")) return null;
  const jobMatch = raw.match(/run\s+dev\.change\s+["']([^"']+)["']/i);
  const repoMatch = raw.match(/repo(?:_ref)?\s+["']?([^"']+)["']?$/i);
  const nameMatch = raw.match(/named\s+([a-zA-Z0-9._-]+)/i);
  return {
    name: nameMatch?.[1] ? String(nameMatch[1]) : undefined,
    jobPrompt: jobMatch?.[1] ? String(jobMatch[1]).trim() : undefined,
    repoRef: repoMatch?.[1] ? String(repoMatch[1]).trim() : undefined,
  };
}

function defaultQueryForDataset(dataset: string): Record<string, unknown> {
  if (dataset === "workspaces") {
    return { entity: "workspaces", filters: [], sort: [{ field: "name", dir: "asc" }], limit: 50, offset: 0 };
  }
  if (dataset === "runs") {
    return { entity: "runs", filters: [], sort: [{ field: "created_at", dir: "desc" }], limit: 50, offset: 0 };
  }
  if (dataset === "ems_devices") {
    return { entity: "ems_devices", filters: [], sort: [{ field: "updated_at", dir: "desc" }], limit: 50, offset: 0 };
  }
  if (dataset === "ems_registrations") {
    return { entity: "ems_registrations", filters: [], sort: [{ field: "registered_at", dir: "desc" }], limit: 50, offset: 0 };
  }
  if (dataset === "ems_device_status_rollup") {
    return { entity: "ems_device_status_rollup", filters: [], sort: [{ field: "bucket", dir: "asc" }], limit: 50, offset: 0 };
  }
  if (dataset === "ems_registrations_timeseries") {
    return { entity: "ems_registrations_timeseries", filters: [], sort: [{ field: "bucket_start", dir: "asc" }], limit: 50, offset: 0 };
  }
  return defaultArtifactStructuredQuery();
}

function applyArtifactNamespaceFilter(query: Record<string, unknown>, namespace?: string): Record<string, unknown> {
  const ns = String(namespace || "").trim().toLowerCase();
  if (!ns) return query;
  const currentFilters = Array.isArray(query.filters) ? [...(query.filters as Array<{ field: string; op: string; value: unknown }>)] : [];
  const nextFilters = currentFilters.filter((row) => String(row?.field || "").toLowerCase() !== "namespace");
  nextFilters.push({ field: "namespace", op: "eq", value: ns });
  return { ...query, filters: nextFilters, offset: 0 };
}

export function buildUiActionFromPrompt(rawPrompt: string, canvasContext: ConsoleCanvasContext | null): UiActionEnvelope | null {
  const prompt = String(rawPrompt || "").trim();
  if (!prompt) return null;
  const normalized = prompt.toLowerCase();
  const activePanelId = canvasContext?.ui?.active_panel_id || canvasContext?.ui?.panel_id;
  const activeDataset = String(canvasContext?.dataset?.name || "").trim();
  const viewType = canvasContext?.view_type;

  const directPanel = resolvePanelCommand(prompt);
  if (directPanel) {
      const dataset =
      directPanel.panelKey === "workspaces"
        ? "workspaces"
        : directPanel.panelKey === "runs"
          ? "runs"
          :
      directPanel.panelKey === "artifact_list"
        ? "artifacts"
        : directPanel.panelKey === "ems_devices"
          ? "ems_devices"
          : directPanel.panelKey === "ems_registrations"
            ? "ems_registrations"
            : directPanel.panelKey === "ems_device_status_rollup"
              ? "ems_device_status_rollup"
              : directPanel.panelKey === "ems_registrations_timeseries"
                ? "ems_registrations_timeseries"
                : "";
    if (dataset) {
      const paramsWithQuery =
        directPanel.params && typeof directPanel.params === "object" && "query" in directPanel.params
          ? (directPanel.params as { query?: Record<string, unknown> })
          : null;
      const panelNamespace =
        directPanel.params && typeof directPanel.params === "object" && "namespace" in directPanel.params
          ? String((directPanel.params as { namespace?: string }).namespace || "")
          : "";
      const baseQuery = paramsWithQuery?.query || defaultQueryForDataset(dataset);
      const nextQuery = dataset === "artifacts" ? applyArtifactNamespaceFilter(baseQuery, panelNamespace) : baseQuery;
      return {
        type: "ui.action",
        action: {
          name: "canvas.open_table",
          params: {
            dataset,
            query: nextQuery,
            title: dataset,
            open_in: "current_panel",
            placement: "center",
          },
        },
      };
    }
    if (directPanel.panelKey === "artifact_detail" && directPanel.params.slug) {
      return {
        type: "ui.action",
        action: {
          name: "canvas.open_detail",
          params: {
            entity_type: "artifact",
            entity_id: directPanel.params.slug,
            open_in: "new_panel",
            placement: "right",
          },
        },
      };
    }
    if (directPanel.panelKey === "run_detail" && directPanel.params.run_id) {
      return {
        type: "ui.action",
        action: {
          name: "canvas.open_detail",
          params: {
            entity_type: "run",
            entity_id: directPanel.params.run_id,
            open_in: "new_panel",
            placement: "right",
          },
        },
      };
    }
    if (directPanel.panelKey === "platform_settings") {
      return {
        type: "ui.action",
        action: {
          name: "canvas.open_detail",
          params: {
            entity_type: "platform_settings",
            entity_id: "current",
            open_in: "current_panel",
            placement: "center",
          },
        },
      };
    }
  }

  if (normalized === "back") {
    return {
      type: "ui.action",
      action: {
        name: "canvas.set_active_panel",
        params: { direction: "back" },
      },
    };
  }
  if (normalized === "forward") {
    return {
      type: "ui.action",
      action: {
        name: "canvas.set_active_panel",
        params: { direction: "forward" },
      },
    };
  }

  if (viewType === "detail") {
    if (normalized === "show raw") {
      return { type: "ui.action", action: { name: "canvas.open_detail", target: { panel_id: activePanelId }, params: { tab: "raw" } } };
    }
    if (normalized === "show files") {
      return { type: "ui.action", action: { name: "canvas.open_detail", target: { panel_id: activePanelId }, params: { tab: "files" } } };
    }
    if (normalized === "open manage") {
      return { type: "ui.action", action: { name: "canvas.open_detail", target: { panel_id: activePanelId }, params: { tab: "manage" } } };
    }
    if (normalized === "back to list") {
      return { type: "ui.action", action: { name: "canvas.set_active_panel", params: { direction: "back" } } };
    }
  }

  if (viewType !== "table" || !activePanelId) return null;

  const validColumns = toLowerColumns(canvasContext || {});

  let match = normalized.match(/^filter\s+([a-z0-9_]+)\s*=\s*(.+)$/);
  if (match && match[1] && match[2]) {
    const field = String(match[1]).trim();
    if (!validColumns.includes(field.toLowerCase())) return null;
    return {
      type: "ui.action",
      action: {
        name: "canvas.update_table_query",
        target: { panel_id: activePanelId },
        params: {
          mode: "patch",
          query_patch: {
            filters_add: [{ field, op: "eq", value: String(match[2]).trim() }],
          },
        },
      },
    };
  }

  match = normalized.match(/^show\s+updated\s+in\s+the\s+last\s+(.+)$/);
  if (match && match[1]) {
    const hours = parseDurationToRelativeHours(match[1]) || 1;
    const candidate = validColumns.includes("updated_at")
      ? "updated_at"
      : validColumns.includes("registered_at")
        ? "registered_at"
        : "";
    if (!candidate) return null;
    return {
      type: "ui.action",
      action: {
        name: "canvas.update_table_query",
        target: { panel_id: activePanelId },
        params: {
          mode: "patch",
          query_patch: {
            filters_add: [{ field: candidate, op: "gte", value: `now-${hours}h` }],
            sort_replace: [{ field: candidate, dir: "desc" }],
          },
        },
      },
    };
  }

  match = normalized.match(/^sort\s+by\s+([a-z0-9_]+)(?:\s+(asc|desc))?$/);
  if (match && match[1]) {
    const field = String(match[1]).trim();
    if (!validColumns.includes(field.toLowerCase())) return null;
    return {
      type: "ui.action",
      action: {
        name: "canvas.update_table_query",
        target: { panel_id: activePanelId },
        params: {
          mode: "patch",
          query_patch: {
            sort_replace: [{ field, dir: match[2] === "asc" ? "asc" : "desc" }],
          },
        },
      },
    };
  }

  match = normalized.match(/^limit\s+(\d+)$/);
  if (match && match[1]) {
    const limit = Math.max(1, Math.min(Number(match[1]) || 50, 200));
    return {
      type: "ui.action",
      action: {
        name: "canvas.update_table_query",
        target: { panel_id: activePanelId },
        params: {
          mode: "patch",
          query_patch: { limit, offset: 0 },
        },
      },
    };
  }

  if (normalized === "next page") {
    const limit = Number(canvasContext?.pagination?.limit || 50);
    const offset = Number(canvasContext?.pagination?.offset || 0);
    return {
      type: "ui.action",
      action: {
        name: "canvas.update_table_query",
        target: { panel_id: activePanelId },
        params: {
          mode: "patch",
          query_patch: { offset: offset + limit },
        },
      },
    };
  }

  if (normalized === "previous page") {
    const limit = Number(canvasContext?.pagination?.limit || 50);
    const offset = Number(canvasContext?.pagination?.offset || 0);
    return {
      type: "ui.action",
      action: {
        name: "canvas.update_table_query",
        target: { panel_id: activePanelId },
        params: {
          mode: "patch",
          query_patch: { offset: Math.max(0, offset - limit) },
        },
      },
    };
  }

  if (normalized === "clear filters") {
    return {
      type: "ui.action",
      action: {
        name: "canvas.update_table_query",
        target: { panel_id: activePanelId },
        params: {
          mode: "replace",
          query_patch: {
            filters_add: [],
            sort_replace: (canvasContext?.query?.sort as Array<{ field: string; dir: "asc" | "desc" }>) || [],
            limit: Number(canvasContext?.pagination?.limit || 50),
            offset: 0,
          },
        },
      },
    };
  }

  match = rawPrompt.match(/^search\s+(.+)$/i);
  if (match && match[1]) {
    const field = inferSearchField(canvasContext || {});
    return {
      type: "ui.action",
      action: {
        name: "canvas.update_table_query",
        target: { panel_id: activePanelId },
        params: {
          mode: "patch",
          query_patch: {
            filters_add: [{ field, op: "contains", value: String(match[1]).trim() }],
            offset: 0,
          },
        },
      },
    };
  }

  // Context-first fallback: keep follow-up prompts in the active table instead of
  // dropping to backend draft intent resolution.
  const tableLikePrefix = /^(show|list|find|only show|filter)\s+/i;
  if (tableLikePrefix.test(prompt)) {
    const stripped = prompt.replace(tableLikePrefix, "").trim();
    const value = stripped || prompt;
    if (value) {
      const field = inferSearchField(canvasContext || {});
      return {
        type: "ui.action",
        action: {
          name: "canvas.update_table_query",
          target: { panel_id: activePanelId },
          params: {
            mode: "patch",
            query_patch: {
              filters_add: [{ field, op: "contains", value }],
              offset: 0,
            },
          },
        },
      };
    }
  }

  match = normalized.match(/^open\s+row\s+(\d+)$/);
  if (match && match[1]) {
    const idx = Math.max(1, Number(match[1])) - 1;
    const rowOrder = canvasContext?.selection?.row_order_ids || [];
    const rowId = rowOrder[idx];
    if (!rowId) return null;
    const entityType = getEntityTypeForDataset(activeDataset) || "record";
    return {
      type: "ui.action",
      action: {
        name: "canvas.select_rows",
        target: { panel_id: activePanelId },
        params: {
          row_ids: [rowId],
          focused_row_id: rowId,
          open_detail: true,
          entity_type: entityType,
          entity_id: rowId,
          dataset: activeDataset,
        },
      },
    };
  }

  match = rawPrompt.match(/^open\s+([a-z0-9_.:-]+)$/i);
  if (match && match[1]) {
    const id = String(match[1]).trim();
    const entityType = getEntityTypeForDataset(activeDataset) || "record";
    return {
      type: "ui.action",
      action: {
        name: "canvas.open_detail",
        params: {
          entity_type: entityType,
          entity_id: id,
          dataset: activeDataset,
          open_in: "new_panel",
          placement: "right",
        },
      },
    };
  }

  return null;
}

function patchTableQuery(currentQuery: Record<string, unknown>, patch: Record<string, unknown>, mode: "patch" | "replace"): Record<string, unknown> {
  const currentFilters = (currentQuery.filters as Array<{ field: string; op: string; value: unknown }> | undefined) || [];
  const nextFiltersAdd = (patch.filters_add as Array<{ field: string; op: string; value: unknown }> | undefined) || [];
  const nextLimit = Number(patch.limit ?? currentQuery.limit ?? 50);
  const nextOffset = Number(patch.offset ?? currentQuery.offset ?? 0);
  const nextSort = (patch.sort_replace as Array<{ field: string; dir: "asc" | "desc" }> | undefined) || (currentQuery.sort as any) || [];

  if (mode === "replace") {
    return {
      ...currentQuery,
      filters: nextFiltersAdd,
      sort: nextSort,
      limit: nextLimit,
      offset: nextOffset,
    };
  }

  const dedupeMap = new Map<string, { field: string; op: string; value: unknown }>();
  for (const item of currentFilters) {
    const key = `${String(item.field)}::${String(item.op)}`;
    dedupeMap.set(key, item);
  }
  for (const item of nextFiltersAdd) {
    const key = `${String(item.field)}::${String(item.op)}`;
    dedupeMap.set(key, item);
  }

  return {
    ...currentQuery,
    filters: Array.from(dedupeMap.values()),
    sort: nextSort.length ? nextSort : currentQuery.sort || [],
    limit: nextLimit,
    offset: nextOffset,
  };
}

function humanizeIntentStatus(status?: string): string {
  const raw = String(status || "").trim();
  if (!raw) return "";
  return raw
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/_/g, " ")
    .trim();
}

function StatusIcon({ status }: { status?: string }) {
  if (status === "DraftReady") return <CheckCircle2 size={14} aria-hidden="true" />;
  if (status === "ValidationError" || status === "UnsupportedIntent") return <AlertTriangle size={14} aria-hidden="true" />;
  if (status === "ProposedPatch") return <Wrench size={14} aria-hidden="true" />;
  return <CircleHelp size={14} aria-hidden="true" />;
}

function MissingFieldsCard() {
  const { session, fetchOptions, focusMissingField, hasEditorBridge } = useXynConsole();
  if (!session.pendingMissingFields.length) return null;
  return (
    <section className="xyn-console-card" aria-label="Missing fields">
      <h4>Missing fields</h4>
      <ul className="xyn-console-list">
        {session.pendingMissingFields.map((field) => (
          <li key={field.field}>
            <span>
              <strong>{field.field}</strong> · <span className="muted">{field.reason}</span>
            </span>
            {field.options_available && ["category", "format", "duration"].includes(field.field) ? (
              <button type="button" className="ghost sm" onClick={() => void fetchOptions(field.field as "category" | "format" | "duration")}>
                Show options
              </button>
            ) : null}
            <button type="button" className="ghost sm" onClick={() => focusMissingField(field.field)}>
              {hasEditorBridge ? "Focus field" : "Add to prompt"}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function OptionsCard() {
  const { session, injectSuggestion, applyOptionValue, hasEditorBridge } = useXynConsole();
  const entries = Object.entries(session.optionsByField);
  if (!entries.length) return null;
  return (
    <section className="xyn-console-card" aria-label="Options">
      <h4>Options</h4>
      {entries.map(([field, payload]) => (
        <div key={field} className="xyn-console-options-block">
          <p className="small muted">{field}</p>
          <div className="xyn-console-options-list">
            {(payload?.options || []).map((option) => {
              const label =
                typeof option === "string"
                  ? option
                  : typeof option === "object" && option && "slug" in option
                  ? String((option as { slug?: string }).slug || "")
                  : stringifyValue(option);
              return (
                <button
                  key={`${field}:${label}`}
                  type="button"
                  className="ghost sm"
                  onClick={() =>
                    hasEditorBridge
                      ? applyOptionValue(field as "category" | "format" | "duration", option)
                      : injectSuggestion(`${field}: ${label}`)
                  }
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </section>
  );
}

function ProposedPatchCard() {
  const { session, applyPendingProposalAndSave, applyPendingProposalToForm, cancelPendingProposal, hasEditorBridge } = useXynConsole();
  if (!session.pendingProposal) return null;
  return (
    <section className="xyn-console-card" aria-label="Proposed patch">
      <h4>Proposed patch</h4>
      <div className="xyn-console-diff">
        {session.pendingProposal.changes.map((change) => (
          <div key={`${change.field}:${stringifyValue(change.to)}`} className="xyn-console-diff-row">
            <span className="xyn-console-diff-field">{change.field}</span>
            <span className="xyn-console-diff-from">{stringifyValue(change.from) || "∅"}</span>
            <span className="xyn-console-diff-to">{stringifyValue(change.to)}</span>
          </div>
        ))}
      </div>
      <div className="inline-actions">
        {hasEditorBridge ? (
          <button type="button" className="ghost sm" onClick={() => applyPendingProposalToForm()}>
            Apply to form
          </button>
        ) : null}
        <button type="button" className="primary sm" onClick={() => void applyPendingProposalAndSave()}>
          {hasEditorBridge ? "Apply & Save" : "Apply"}
        </button>
        <button type="button" className="ghost sm" onClick={() => cancelPendingProposal()}>
          Cancel
        </button>
      </div>
      {session.localMessage ? <p className="muted small">{session.localMessage}</p> : null}
      {session.ignoredFields.length ? (
        <p className="muted small">Ignored fields: {session.ignoredFields.join(", ")}</p>
      ) : null}
    </section>
  );
}

function ResolutionCard({
  resolution,
  onRevise,
  onOpenPanel,
}: {
  resolution: XynIntentResolutionResult;
  onRevise: () => void;
  onOpenPanel?: (panelKey: string, params?: Record<string, unknown>) => void;
}) {
  const { applyDraftPayload, setInputText, session } = useXynConsole();
  const navigate = useNavigate();
  const location = useLocation();
  const workspaceMatch = String(location.pathname || "").match(/^\/w\/([^/]+)(?:\/|$)/);
  const workspaceId = workspaceMatch?.[1] ? decodeURIComponent(workspaceMatch[1]) : "";
  const canCreate = resolution.status === "DraftReady" && resolution.action_type === "CreateDraft" && !!resolution.draft_payload;
  const canOpen = Boolean(resolution.artifact_id);
  const showRevise = resolution.status !== "UnsupportedIntent";
  const deepLinks = (resolution.next_actions || []).filter(
    (item) => item.action === "OpenPath" && typeof item.path === "string" && item.path.startsWith("/")
  );
  const panelLinks = (resolution.next_actions || []).filter(
    (item) => item.action === "OpenPanel" && typeof item.panel_key === "string" && item.panel_key.length > 0
  );

  return (
    <section className="xyn-console-card" aria-label="Resolution">
      <div className="xyn-console-card-head">
        <StatusIcon status={resolution.status} />
        <strong>{humanizeIntentStatus(resolution.status)}</strong>
      </div>
      <p>{resolution.summary}</p>
      {resolution.validation_errors?.length ? (
        <ul className="xyn-console-errors">
          {resolution.validation_errors.map((err) => (
            <li key={err}>{err}</li>
          ))}
        </ul>
      ) : null}
      <div className="inline-actions">
        {canCreate ? (
          <button type="button" className="primary sm" onClick={() => void applyDraftPayload()}>
            Create draft
          </button>
        ) : null}
        {canOpen ? (
          <button
            type="button"
            className="ghost sm"
            onClick={() =>
              navigate(workspaceId ? toWorkspacePath(workspaceId, `build/artifacts/${resolution.artifact_id}`) : "/")
            }
          >
            Open in editor
          </button>
        ) : null}
        {showRevise ? (
          <button
            type="button"
            className="ghost sm"
            onClick={() => {
              if (!session.inputText && session.lastMessage) {
                setInputText(session.lastMessage);
              }
              onRevise();
            }}
          >
            Revise
          </button>
        ) : null}
        {deepLinks.map((action) => (
          <button key={`${action.label}:${action.path}`} type="button" className="ghost sm" onClick={() => navigate(String(action.path || "/"))}>
            {action.label}
          </button>
        ))}
        {panelLinks.map((action) => (
          <button
            key={`${action.label}:${action.panel_key}`}
            type="button"
            className="ghost sm"
            onClick={() => onOpenPanel?.(String(action.panel_key || ""), action.params || {})}
          >
            {action.label}
          </button>
        ))}
      </div>
      {session.localMessage ? <p className="muted small">{session.localMessage}</p> : null}
    </section>
  );
}

export default function XynConsoleCore({ mode, onRequestClose, onOpenPanel }: Props) {
  const navigate = useNavigate();
  const location = useLocation();
  const {
    open,
    setOpen,
    context,
    inputText,
    setInputText,
    processing,
    processingStep,
    session,
    submitResolve,
    pendingCloseBlock,
    clearSessionResolution,
    lastArtifactHint,
    setLastArtifactHint,
    injectSuggestion,
    canvasContext,
    openPanel,
    updateActivePanelParams,
    activePanelId,
    setActivePanelId,
    closePanel,
    navigateBack,
    navigateForward,
    submitToken,
    openSuggestionSwitcher,
  } = useXynConsole();
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const [recentItems, setRecentItems] = useState<RecentArtifactItem[]>([]);
  const [showDeprecatedArticles, setShowDeprecatedArticles] = useState(false);
  const [recentLoading, setRecentLoading] = useState(false);
  const [recentFetchedAt, setRecentFetchedAt] = useState(0);
  const initialRecentCount = mode === "page" ? 8 : 6;
  const [recentLimit, setRecentLimit] = useState(initialRecentCount);
  const [recentVisibleCount, setRecentVisibleCount] = useState(initialRecentCount);
  const [recentExpanded, setRecentExpanded] = useState(false);

  const isOverlay = mode === "overlay";
  const isSurfaceVisible = isOverlay ? open : true;
  const isWorkbenchPath = /\/(?:w\/[^/]+\/)?workbench\/?$/.test(location.pathname);
  const hasContextArtifact = Boolean(context.artifact_id && context.artifact_type);
  const isGlobalContext = !hasContextArtifact;

  useEffect(() => {
    if (!isSurfaceVisible) return;
    inputRef.current?.focus();
  }, [isSurfaceVisible]);

  useEffect(() => {
    if (!isSurfaceVisible) return;
    if (session.lastResolution?.status !== "UnsupportedIntent") return;
    const target = inputRef.current;
    if (!target) return;
    target.focus();
    const end = target.value.length;
    target.setSelectionRange(end, end);
  }, [isSurfaceVisible, session.lastResolution?.status]);

  useEffect(() => {
    if (context.artifact_type && !context.artifact_id) {
      // eslint-disable-next-line no-console
      console.warn("[xyn-console] artifact_type without artifact_id; falling back to Global context");
    }
  }, [context.artifact_id, context.artifact_type]);

  useEffect(() => {
    if (!isOverlay || !isSurfaceVisible || !isWorkbenchPath) return;
    if (session.lastResolution?.status !== "DraftReady") return;
    clearSessionResolution();
  }, [clearSessionResolution, isOverlay, isSurfaceVisible, isWorkbenchPath, session.lastResolution]);

  const statusLine = useMemo(() => {
    if (!processingStep) return "";
    if (processingStep === "resolving") return "Resolving command...";
    if (processingStep === "classifying") return "Preparing response...";
    return "Checking requirements...";
  }, [processingStep]);

  const shouldShowRecent =
    isSurfaceVisible &&
    !isWorkbenchPath &&
    isGlobalContext &&
    !session.pendingProposal;

  useEffect(() => {
    if (!shouldShowRecent) return;
    const now = Date.now();
    if (recentItems.length && now - recentFetchedAt < 60_000) return;
    let active = true;
    (async () => {
      try {
        setRecentLoading(true);
        const payload = await getRecentArtifacts(recentLimit);
        if (!active) return;
        setRecentItems(payload.items || []);
        setRecentFetchedAt(Date.now());
      } finally {
        if (active) setRecentLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [isGlobalContext, lastArtifactHint, recentFetchedAt, recentItems.length, recentLimit, setLastArtifactHint, shouldShowRecent]);

  const contextualTitle =
    hasContextArtifact && lastArtifactHint?.artifact_id && String(lastArtifactHint.artifact_id) === String(context.artifact_id || "")
      ? String(lastArtifactHint.title || "").trim()
      : "";
  const contextLine = hasContextArtifact
    ? `Context: ${context.artifact_type} • ${contextualTitle || shortArtifactId(String(context.artifact_id || ""))}`
    : "Context: Global";
  const handleRevise = () => {
    const target = inputRef.current;
    if (!target) return;
    target.focus();
    const end = target.value.length;
    target.setSelectionRange(end, end);
  };

  const canSubmit = Boolean(inputText.trim()) && !processing;

  const submitPrompt = () => {
    const prompt = String(inputText || "").trim();
    if (!prompt) return;
    if (/^(suggest|show suggestions?)$/i.test(prompt)) {
      openSuggestionSwitcher();
      clearSessionResolution();
      if (isOverlay) setOpen(false);
      return;
    }
    const provisionRequest = parseProvisionLocalCommand(prompt);
    if (provisionRequest) {
      void (async () => {
        try {
          setOpen(true);
          const payload = await provisionLocalXynInstance({
            name: provisionRequest.name,
            job:
              provisionRequest.jobPrompt
                ? {
                    prompt: provisionRequest.jobPrompt,
                    repo_ref: provisionRequest.repoRef || String(import.meta.env.VITE_JOB_DEFAULT_REPO || "/home/ubuntu/src/xyn-ui"),
                  }
                : undefined,
          });
          openPanel({
            key: "local_provision_result",
            params: { payload },
            open_in: "new_panel",
          });
          clearSessionResolution();
          if (isOverlay) setOpen(false);
        } catch (error) {
          openPanel({
            key: "local_provision_result",
            params: {
              payload: {
                status: "failed",
                compose_project: "n/a",
                compose_path: "",
                deployment_id: "",
                deployment_artifact_id: "",
                ui_url: "",
                api_url: "",
                error: error instanceof Error ? error.message : "Unknown provisioning failure",
              },
            },
            open_in: "new_panel",
          });
        }
      })();
      return;
    }
    const envelope = buildUiActionFromPrompt(prompt, (canvasContext as ConsoleCanvasContext | null) || null);
    const activeContextPanelId = String(canvasContext?.ui?.active_panel_id || canvasContext?.ui?.panel_id || "").trim();
    const returnTarget = activeContextPanelId || undefined;
    if (envelope) {
      const action = envelope.action;
      if (action.name === "canvas.open_table") {
        const dataset = String(action.params.dataset || "artifacts");
        const query = (action.params.query as Record<string, unknown> | undefined) || defaultQueryForDataset(dataset);
        openPanel({
          key: panelKeyForDataset(dataset),
          params: { query },
          open_in: (action.params.open_in as "current_panel" | "new_panel" | "side_by_side" | undefined) || "current_panel",
        });
        clearSessionResolution();
        if (isOverlay) setOpen(false);
        return;
      }
      if (action.name === "canvas.open_detail") {
        if (String(action.params.entity_type || "") === "platform_settings") {
          openPanel({
            key: "platform_settings",
            params: { workspace_id: String(location.pathname.match(/^\/w\/([^/]+)(?:\/|$)/)?.[1] || "") },
            open_in: (action.params.open_in as "current_panel" | "new_panel" | "side_by_side" | undefined) || "current_panel",
          });
          clearSessionResolution();
          if (isOverlay) setOpen(false);
          return;
        }
        if (String(action.params.entity_type || "") === "run") {
          const runId = String(action.params.entity_id || "").trim();
          if (runId) {
          openPanel({
            key: "run_detail",
            params: { run_id: runId },
            open_in: (action.params.open_in as "current_panel" | "new_panel" | "side_by_side" | undefined) || "new_panel",
            return_to_panel_id: returnTarget,
          });
            clearSessionResolution();
            if (isOverlay) setOpen(false);
            return;
          }
        }
        if (String(action.params.entity_type || "") === "artifact") {
          const slug = String(action.params.entity_id || "").trim();
          if (slug) {
            openPanel({
              key: "artifact_detail",
              params: { slug, tab: String(action.params.tab || "overview") },
              open_in: (action.params.open_in as "current_panel" | "new_panel" | "side_by_side" | undefined) || "new_panel",
              return_to_panel_id: returnTarget,
            });
            clearSessionResolution();
            if (isOverlay) setOpen(false);
            return;
          }
        }
        if (String(action.params.entity_type || "") === "workspace") {
          const workspaceId = String(action.params.entity_id || "").trim();
          openPanel({
            key: "platform_settings",
            params: { workspace_id: workspaceId },
            open_in: (action.params.open_in as "current_panel" | "new_panel" | "side_by_side" | undefined) || "new_panel",
            return_to_panel_id: returnTarget,
          });
          clearSessionResolution();
          if (isOverlay) setOpen(false);
          return;
        }
        if (String(action.params.entity_type || "") === "record") {
          const entityId = String(action.params.entity_id || "").trim();
          if (entityId) {
            openPanel({
              key: "record_detail",
              params: {
                entity_type: "record",
                entity_id: entityId,
                dataset: String(action.params.dataset || ""),
              },
              open_in: (action.params.open_in as "current_panel" | "new_panel" | "side_by_side" | undefined) || "new_panel",
              return_to_panel_id: returnTarget,
            });
            clearSessionResolution();
            if (isOverlay) setOpen(false);
            return;
          }
        }
      }
      if (action.name === "canvas.update_table_query") {
        const mode = (action.params.mode as "patch" | "replace" | undefined) || "patch";
        const patch = (action.params.query_patch as Record<string, unknown> | undefined) || {};
        const current = (canvasContext?.query as Record<string, unknown> | undefined) || defaultArtifactStructuredQuery();
        updateActivePanelParams({ query: patchTableQuery(current, patch, mode) });
        clearSessionResolution();
        if (isOverlay) setOpen(false);
        return;
      }
      if (action.name === "canvas.select_rows") {
        const rowIds = (action.params.row_ids as string[] | undefined) || [];
        updateActivePanelParams({
          selected_row_ids: rowIds,
          focused_row_id: action.params.focused_row_id || null,
        });
        if (action.params.open_detail) {
          const entityId = String(action.params.entity_id || "").trim();
          const entityType = String(action.params.entity_type || "").trim();
          if (entityId && entityType === "artifact") {
            openPanel({ key: "artifact_detail", params: { slug: entityId }, open_in: "new_panel", return_to_panel_id: returnTarget });
          }
          if (entityId && entityType === "run") {
            openPanel({ key: "run_detail", params: { run_id: entityId }, open_in: "new_panel", return_to_panel_id: returnTarget });
          }
          if (entityId && entityType === "workspace") {
            openPanel({ key: "platform_settings", params: { workspace_id: entityId }, open_in: "new_panel", return_to_panel_id: returnTarget });
          }
          if (entityId && entityType === "record") {
            openPanel({
              key: "record_detail",
              params: {
                entity_type: "record",
                entity_id: entityId,
                dataset: String(action.params.dataset || ""),
              },
              open_in: "new_panel",
              return_to_panel_id: returnTarget,
            });
          }
        }
        clearSessionResolution();
        if (isOverlay) setOpen(false);
        return;
      }
      if (action.name === "canvas.set_active_panel") {
        const direction = String(action.params.direction || "").toLowerCase();
        if (direction === "back") {
          navigateBack();
        } else if (direction === "forward") {
          navigateForward();
        } else if (action.params.panel_id && typeof action.params.panel_id === "string") {
          setActivePanelId(action.params.panel_id);
        }
        clearSessionResolution();
        if (isOverlay) setOpen(false);
        return;
      }
      if (action.name === "canvas.close_panel") {
        const panelId = String(action.params.panel_id || activePanelId || "").trim();
        if (panelId) closePanel(panelId);
        clearSessionResolution();
        if (isOverlay) setOpen(false);
        return;
      }
    }

    const directPanel = resolvePanelCommand(prompt);
    if (directPanel && onOpenPanel) {
      onOpenPanel(directPanel.panelKey, directPanel.params);
      clearSessionResolution();
      if (isOverlay) setOpen(false);
      return;
    }

    void submitResolve();
  };

  const handleInputKeyDown = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter") return;
    if (event.altKey) return;
    if (event.shiftKey) return;
    const submitByHotkey = event.metaKey || event.ctrlKey || (!event.metaKey && !event.ctrlKey);
    if (submitByHotkey) {
      event.preventDefault();
      if (!canSubmit) return;
      submitPrompt();
    }
  };

  useEffect(() => {
    if (!submitToken) return;
    submitPrompt();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [submitToken]);

  const resolutionStack = (
    <>
      {pendingCloseBlock ? <div className="xyn-console-warning">You have a pending proposal. Apply or cancel.</div> : null}
      {session.lastResolution && !(isWorkbenchPath && session.lastResolution.status === "DraftReady") ? (
        <>
          <ResolutionCard resolution={session.lastResolution} onRevise={handleRevise} onOpenPanel={onOpenPanel} />
          {isGlobalContext ? (
            <div className="inline-actions">
              <button
                type="button"
                className="ghost sm"
                onClick={() => {
                  clearSessionResolution();
                  setInputText("");
                }}
              >
                Clear
              </button>
            </div>
          ) : null}
        </>
      ) : null}
      <ProposedPatchCard />
      <MissingFieldsCard />
      <OptionsCard />
    </>
  );
  const hasResolutionContent =
    pendingCloseBlock ||
    Boolean(session.lastResolution) ||
    Boolean(session.pendingProposal) ||
    session.pendingMissingFields.length > 0 ||
    Object.keys(session.optionsByField || {}).length > 0;

  const promptCard = (
    <ConsolePromptCard
      contextLine={contextLine}
      statusLine={statusLine || "Working..."}
      processing={processing}
      inputText={inputText}
      onInputChange={setInputText}
      onInputKeyDown={handleInputKeyDown}
      onSubmit={submitPrompt}
      onClear={() => {
        if (session.lastResolution || session.pendingProposal || session.pendingMissingFields.length) {
          clearSessionResolution();
        }
        setInputText("");
      }}
      canSubmit={canSubmit}
      textareaRef={inputRef}
      pendingCloseBlock={pendingCloseBlock}
    />
  );

  const recentSection = shouldShowRecent ? (
    <RecentArtifactsMiniTable
      items={recentItems.filter((item) => {
        if (showDeprecatedArticles) return true;
        return String(item.artifact_state || "").toLowerCase() !== "deprecated";
      })}
      loading={recentLoading}
      compact={!isOverlay && Boolean(inputText.trim()) && !recentExpanded}
      maxItems={recentVisibleCount}
      showDeprecatedArticles={showDeprecatedArticles}
      onRefresh={() => {
        setRecentFetchedAt(0);
        setRecentExpanded(false);
        setRecentVisibleCount(initialRecentCount);
        setRecentLimit(initialRecentCount);
      }}
      onToggleShowDeprecatedArticles={setShowDeprecatedArticles}
      onOpen={(item) => {
        setLastArtifactHint({
          artifact_id: item.artifact_id,
          artifact_type: item.artifact_type,
          artifact_state: item.artifact_state || null,
          title: item.title,
          route: item.route,
          updated_at: item.updated_at,
        });
        navigate(item.route);
        if (isOverlay) {
          if (onRequestClose) onRequestClose();
          else setOpen(false);
        }
      }}
      onShowMore={() => {
        setRecentExpanded(true);
        setRecentVisibleCount((current) => current + 10);
        const desired = recentVisibleCount + 10;
        if (desired > recentLimit) {
          setRecentLimit((current) => Math.min(Math.max(current + 10, desired), 100));
          setRecentFetchedAt(0);
        }
      }}
      onInsertSuggestion={injectSuggestion}
    />
  ) : null;

  if (!isOverlay) {
    return (
      <div className="xyn-console-core page">
        <div className="xyn-console-page-grid">
          <div className="xyn-console-page-main">
            {promptCard}
            {hasResolutionContent ? <ConsoleResultPanel>{resolutionStack}</ConsoleResultPanel> : null}
          </div>
          <ConsoleGuidancePanel onInsertSuggestion={injectSuggestion} dimmed={Boolean(inputText.trim())} />
        </div>
        {recentSection}
      </div>
    );
  }

  return (
    <div className="xyn-console-core overlay">
      <header className="xyn-console-header">
        <h3>Xyn</h3>
        <button
          type="button"
          className="ghost sm"
          onClick={() => {
            if (onRequestClose) onRequestClose();
            else setOpen(false);
          }}
          disabled={Boolean(session.pendingProposal)}
        >
          Close
        </button>
      </header>
      {promptCard}
      <ConsoleResultPanel>{resolutionStack}</ConsoleResultPanel>
      {recentSection}
      <footer className="xyn-console-footer muted small">
        <span>Esc to collapse (unless proposal pending)</span>
        <span>Submit: Enter or ⌘/Ctrl+Enter</span>
        <span>Shift+Enter newline</span>
      </footer>
    </div>
  );
}
