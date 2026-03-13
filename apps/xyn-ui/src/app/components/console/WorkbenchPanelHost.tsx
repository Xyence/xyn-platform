import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  executeAppPalettePrompt,
  getGoal,
  getArtifactConsoleDetailBySlug,
  getArtifactConsoleFilesBySlug,
  getCoordinationThread,
  getEmsDatasetSchemaTable,
  getEmsRegistrationsTimeseriesCanvasTable,
  getEmsStatusRollupCanvasTable,
  getRuntimeRunArtifactContent,
  getRuntimeRunCanvasApi,
  getWorkItem,
  getWorkQueue,
  listGoals,
  listCoordinationThreads,
  listWorkItems,
  listAppBuilderArtifacts,
  listRuntimeRunsCanvasApi,
  listWorkspacesCanvasApi,
  queryArtifactCanvasTable,
  queryEmsDevicesCanvasTable,
  queryEmsRegistrationsCanvasTable,
  reviewCoordinationThread,
  reviewGoal,
} from "../../../api/xyn";
import type {
  AppPaletteResult,
  AppBuilderArtifact,
  ArtifactCanvasTableResponse,
  ArtifactConsoleDetailResponse,
  ArtifactConsoleFileRow,
  ArtifactStructuredQuery,
  CanvasTableResponse,
  CoordinationThreadDetail,
  CoordinationThreadSummary,
  GoalDetail,
  GoalSummary,
  LocalProvisionResponse,
  RuntimeRunDetail,
  RuntimeRunArtifactContent,
  RuntimeRunSummary,
  WorkQueueResponse,
  WorkItemDetail,
  WorkItemSummary,
  WorkspaceSummary,
} from "../../../api/types";
import CanvasRenderer from "../../../components/canvas/CanvasRenderer";
import InlineMessage from "../../../components/InlineMessage";
import type { OpenDetailTarget } from "../../../components/canvas/datasetEntityRegistry";
import { XYN_ENTITY_CHANGE_EVENT, inferEntityListPrompt, type EntityChangeDetail } from "../../utils/entityChangeEvents";
import { applyRuntimeEventToRunDetail, applyRuntimeEventToRuns, refreshRuntimeRunDetail, refreshRuntimeRunSummary, subscribeRuntimeEventStream } from "../../utils/runtimeEventStream";
import DraftDetailPage from "../../pages/DraftDetailPage";
import DraftsListPage from "../../pages/DraftsListPage";
import JobDetailPage from "../../pages/JobDetailPage";
import JobsListPage from "../../pages/JobsListPage";
import PlatformSettingsHubPage from "../../pages/PlatformSettingsHubPage";
import { toWorkspacePath } from "../../routing/workspaceRouting";

export type ConsolePanelKey =
  | "platform_settings"
  | "goal_list"
  | "goal_detail"
  | "workspaces"
  | "thread_list"
  | "thread_detail"
  | "runs"
  | "drafts_list"
  | "draft_detail"
  | "jobs_list"
  | "job_detail"
  | "work_items"
  | "work_item_detail"
  | "palette_result"
  | "app_builder_artifact_list"
  | "run_detail"
  | "artifact_list"
  | "artifact_detail"
  | "artifact_raw_json"
  | "artifact_files"
  | "ems_devices"
  | "ems_registrations"
  | "ems_device_status_rollup"
  | "ems_registrations_timeseries"
  | "ems_dataset_schema"
  | "ems_unregistered_devices"
  | "ems_registrations_time"
  | "ems_device_statuses"
  | "record_detail"
  | "local_provision_result";

export type ConsolePanelSpec = {
  panel_id?: string;
  panel_type?: "table" | "detail" | "report";
  instance_key?: string;
  title?: string;
  active_group_id?: string | null;
  open_in?: "current_panel" | "new_panel" | "side_by_side";
  return_to_panel_id?: string;
  key: ConsolePanelKey;
  params?: Record<string, unknown>;
};

type PanelProps = {
  onOpenPanel: (panelKey: ConsolePanelKey, params?: Record<string, unknown>) => void;
};

type CanvasQuery = {
  entity: string;
  filters: Array<{ field: string; op: string; value: unknown }>;
  sort: Array<{ field: string; dir: "asc" | "desc" }>;
  limit: number;
  offset: number;
};

type ContextEmitter = (context: Record<string, unknown> | null) => void;

function PaletteResultPanel({
  result,
  prompt,
  error,
  workspaceId,
}: {
  result?: AppPaletteResult;
  prompt?: string;
  error?: string;
  workspaceId: string;
}) {
  const [liveResult, setLiveResult] = useState<AppPaletteResult | undefined>(result);
  const [refreshing, setRefreshing] = useState(false);
  const listPrompt = useMemo(() => inferEntityListPrompt(String(prompt || "")), [prompt]);

  useEffect(() => {
    setLiveResult(result);
  }, [result]);

  useEffect(() => {
    if (!workspaceId || !listPrompt) return;
    let active = true;
    const onEntityChange = async (event: Event) => {
      const detail = (event as CustomEvent<EntityChangeDetail>).detail;
      if (!detail || detail.entityKey !== listPrompt.entityKey) return;
      try {
        setRefreshing(true);
        const refreshed = await executeAppPalettePrompt(workspaceId, { prompt: listPrompt.prompt });
        if (!active || refreshed.kind !== "table") return;
        setLiveResult(refreshed);
      } finally {
        if (active) setRefreshing(false);
      }
    };
    window.addEventListener(XYN_ENTITY_CHANGE_EVENT, onEntityChange as EventListener);
    return () => {
      active = false;
      window.removeEventListener(XYN_ENTITY_CHANGE_EVENT, onEntityChange as EventListener);
    };
  }, [listPrompt, workspaceId]);

  const safeResult = liveResult || { kind: "table", columns: [], rows: [] };
  const columns = Array.isArray(safeResult.columns) ? safeResult.columns : [];
  const rows = Array.isArray(safeResult.rows) ? safeResult.rows : [];
  const labels = Array.isArray(safeResult.labels) ? safeResult.labels : [];
  const values = Array.isArray(safeResult.values) ? safeResult.values : [];
  const meta = safeResult.meta && typeof safeResult.meta === "object" ? safeResult.meta : {};
  const contextPackSlugs = Array.isArray(meta.context_pack_slugs)
    ? meta.context_pack_slugs.map((value) => String(value || "").trim()).filter(Boolean)
    : [];
  const warnings = Array.isArray(meta.context_warnings)
    ? meta.context_warnings.map((value) => String(value || "").trim()).filter(Boolean)
    : [];
  return (
    <>
      <div className="page-header">
        <div>
          <h2>Palette Result</h2>
          <p className="muted">{String(safeResult.text || error || "Command executed.")}</p>
        </div>
      </div>
      <section className="card">
        <div className="detail-grid">
          <div>
            <div className="field-label">Prompt</div>
            <div className="field-value">{String(prompt || "—")}</div>
          </div>
          <div>
            <div className="field-label">Result Kind</div>
            <div className="field-value">{String(safeResult.kind || "—")}</div>
          </div>
          <div>
            <div className="field-label">Resolved Context Packs</div>
            <div className="field-value">{contextPackSlugs.length ? contextPackSlugs.join(", ") : "—"}</div>
          </div>
          {listPrompt ? (
            <div>
              <div className="field-label">Auto Refresh</div>
              <div className="field-value">{refreshing ? "Refreshing…" : "Watching entity changes"}</div>
            </div>
          ) : null}
        </div>
        {error ? <InlineMessage tone="error" title="Palette request failed" body={error} /> : null}
        {warnings.length ? <InlineMessage tone="warn" title="Warnings" body={warnings.join(" ")} /> : null}
        {safeResult.kind === "bar_chart" && labels.length > 0 ? (
          <div className="card" style={{ marginTop: 12, marginBottom: 12 }}>
            <div className="card-header">
              <h3>{String(safeResult.title || "Report")}</h3>
            </div>
            <div className="chart-bars">
              {labels.map((label, index) => {
                const numeric = Number(values[index] ?? 0);
                const maxValue = Math.max(...values.map((value) => Number(value || 0)), 1);
                const width = `${Math.max((numeric / maxValue) * 100, 6)}%`;
                return (
                  <div className="chart-row" key={`${label}-${index}`}>
                    <div className="chart-label">{label}</div>
                    <div className="chart-track">
                      <div className="chart-bar" style={{ width }} />
                    </div>
                    <div className="chart-value">{numeric}</div>
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column}>{column}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={String(row.id || index)}>
                  {columns.map((column) => (
                    <td key={column}>{String(row[column] ?? "")}</td>
                  ))}
                </tr>
              ))}
              {!rows.length ? (
                <tr>
                  <td colSpan={Math.max(columns.length, 1)} className="muted">
                    No rows returned.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function AppBuilderArtifactListPanel({ workspaceId, kind }: { workspaceId: string; kind?: string }) {
  const [items, setItems] = useState<AppBuilderArtifact[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    if (!workspaceId) {
      setItems([]);
      setError("Workspace context is required.");
      return;
    }
    void (async () => {
      try {
        setLoading(true);
        setError(null);
        const payload = await listAppBuilderArtifacts(workspaceId, { kind, limit: 50 });
        if (!active) return;
        setItems(payload);
      } catch (err) {
        if (!active) return;
        setError((err as Error).message);
        setItems([]);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [kind, workspaceId]);

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Artifacts</h2>
          <p className="muted">
            {kind ? `Generated artifacts filtered by kind=${kind}.` : "Generated artifacts from the app-builder runtime."}
          </p>
        </div>
      </div>
      {error ? <InlineMessage tone="error" title="Request failed" body={error} /> : null}
      <section className="card">
        <p className="muted">Rows: {items.length}{loading ? " (loading...)" : ""}</p>
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Kind</th>
                <th>Scope</th>
                <th>Sync</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>{item.name}</td>
                  <td>{item.kind}</td>
                  <td>{String(item.storage_scope || "")}</td>
                  <td>{String(item.sync_state || "")}</td>
                  <td>{String(item.created_at || "")}</td>
                </tr>
              ))}
              {!loading && !items.length ? (
                <tr>
                  <td colSpan={5} className="muted">
                    No artifacts found.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

const WORKSPACES_DATASET_COLUMNS = [
  { key: "id", label: "ID", type: "string", filterable: true, sortable: true },
  { key: "slug", label: "Slug", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "name", label: "Name", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "org_name", label: "Org Name", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "kind", label: "Kind", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "lifecycle_stage", label: "Stage", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "auth_mode", label: "Auth Mode", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "parent_workspace_id", label: "Parent Workspace", type: "string", filterable: true, sortable: true, searchable: true },
] as const;

const RUNS_DATASET_COLUMNS = [
  { key: "id", label: "Run ID", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "work_item_id", label: "Work Item", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "worker_type", label: "Worker", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "status", label: "Status", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "elapsed_time", label: "Elapsed", type: "string", filterable: true, sortable: true },
  { key: "heartbeat_freshness", label: "Heartbeat", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "summary", label: "Summary", type: "string", filterable: true, sortable: true, searchable: true },
  { key: "started_at", label: "Started", type: "datetime", filterable: true, sortable: true },
  { key: "created_at", label: "Created", type: "datetime", filterable: true, sortable: true },
] as const;

function toIso(value?: string | null): string {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toISOString();
}

function formatDuration(totalSeconds?: number | null): string {
  if (totalSeconds == null || Number.isNaN(totalSeconds)) return "—";
  if (totalSeconds < 60) return `${Math.max(0, totalSeconds)}s`;
  if (totalSeconds < 3600) return `${Math.floor(totalSeconds / 60)}m ${totalSeconds % 60}s`;
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  return `${hours}h ${minutes}m`;
}

function resolveRelativeDate(raw: unknown): Date | null {
  const token = String(raw || "").trim().toLowerCase();
  if (!token) return null;
  const relative = token.match(/^now-(\d+)([mhd])$/);
  if (relative) {
    const amount = Math.max(0, Number(relative[1]) || 0);
    const unit = relative[2];
    const now = Date.now();
    if (unit === "m") return new Date(now - amount * 60_000);
    if (unit === "h") return new Date(now - amount * 3_600_000);
    return new Date(now - amount * 86_400_000);
  }
  const absolute = new Date(token);
  if (Number.isNaN(absolute.getTime())) return null;
  return absolute;
}

function compareValues(left: unknown, right: unknown, type?: string): number {
  if (type === "datetime") {
    const leftDate = resolveRelativeDate(left);
    const rightDate = resolveRelativeDate(right);
    const leftTime = leftDate ? leftDate.getTime() : 0;
    const rightTime = rightDate ? rightDate.getTime() : 0;
    return leftTime - rightTime;
  }
  const leftVal = typeof left === "string" ? left.toLowerCase() : left;
  const rightVal = typeof right === "string" ? right.toLowerCase() : right;
  if (leftVal == null && rightVal == null) return 0;
  if (leftVal == null) return -1;
  if (rightVal == null) return 1;
  if (leftVal < rightVal) return -1;
  if (leftVal > rightVal) return 1;
  return 0;
}

function rowMatches(row: Record<string, unknown>, filter: { field: string; op: string; value: unknown }, columns: ReadonlyArray<{ key: string; type: string }>): boolean {
  const field = String(filter.field || "").trim();
  const op = String(filter.op || "eq").trim().toLowerCase();
  const value = row[field];
  const schema = columns.find((entry) => entry.key === field);
  const type = schema?.type || "string";
  if (type === "datetime") {
    const left = resolveRelativeDate(value);
    const right = resolveRelativeDate(filter.value);
    if (!left || !right) return false;
    const cmp = left.getTime() - right.getTime();
    if (op === "eq") return cmp === 0;
    if (op === "neq") return cmp !== 0;
    if (op === "gte") return cmp >= 0;
    if (op === "lte") return cmp <= 0;
    if (op === "gt") return cmp > 0;
    if (op === "lt") return cmp < 0;
    return false;
  }
  const left = value == null ? "" : String(value).toLowerCase();
  const right = filter.value == null ? "" : String(filter.value).toLowerCase();
  if (op === "eq") return left === right;
  if (op === "neq") return left !== right;
  if (op === "contains") return left.includes(right);
  if (op === "in") {
    if (Array.isArray(filter.value)) return filter.value.map((entry) => String(entry).toLowerCase()).includes(left);
    return left === right;
  }
  if (op === "gte" || op === "lte" || op === "gt" || op === "lt") {
    const cmp = compareValues(value, filter.value, type);
    if (op === "gte") return cmp >= 0;
    if (op === "lte") return cmp <= 0;
    if (op === "gt") return cmp > 0;
    if (op === "lt") return cmp < 0;
  }
  return false;
}

function baseArtifactQuery(): ArtifactStructuredQuery {
  return { entity: "artifacts", filters: [], sort: [{ field: "updated_at", dir: "desc" }], limit: 50, offset: 0 };
}

function emitTableContext({
  onContextChange,
  panel,
  payload,
  query,
  selectedRowIds,
  focusedRowId,
  rowOrderIds,
}: {
  onContextChange?: ContextEmitter;
  panel: ConsolePanelSpec | null;
  payload: CanvasTableResponse | ArtifactCanvasTableResponse | null;
  query: CanvasQuery | ArtifactStructuredQuery;
  selectedRowIds: string[];
  focusedRowId: string | null;
  rowOrderIds: string[];
}) {
  if (!onContextChange || !panel?.panel_id || !payload) return;
  onContextChange({
    view_type: "table",
    dataset: {
      name: payload.dataset.name,
      primary_key: payload.dataset.primary_key,
      columns: payload.dataset.columns,
    },
    query,
    selection: {
      selected_row_ids: selectedRowIds,
      focused_row_id: focusedRowId,
      row_order_ids: rowOrderIds,
    },
    pagination: {
      limit: Number(query.limit || 50),
      offset: Number(query.offset || 0),
      total_count: Number(payload.dataset.total_count || 0),
    },
    ui: {
      active_panel_id: panel.panel_id,
      panel_id: panel.panel_id,
      panel_type: panel.panel_type || "table",
      instance_key: panel.instance_key || payload.dataset.name,
      active_group_id: panel.active_group_id || null,
      layout_engine: "simple",
    },
  });
}

function WorkspacesPanel({
  query,
  queryError,
  panel,
  onContextChange,
  onOpenDetail,
  onTitleChange,
}: {
  query?: CanvasQuery;
  queryError?: string;
  panel: ConsolePanelSpec | null;
  onContextChange?: ContextEmitter;
  onOpenDetail: (target: OpenDetailTarget, row: Record<string, unknown>) => void;
  onTitleChange?: (title: string) => void;
}) {
  const [payload, setPayload] = useState<CanvasTableResponse | null>(null);
  const [runs, setRuns] = useState<RuntimeRunSummary[]>([]);
  const [activeQuery, setActiveQuery] = useState<CanvasQuery>({
    entity: "workspaces",
    filters: [],
    sort: [{ field: "name", dir: "asc" }],
    limit: 50,
    offset: 0,
  });
  const [selectedRowIds, setSelectedRowIds] = useState<string[]>([]);
  const [focusedRowId, setFocusedRowId] = useState<string | null>(null);
  const [rowOrderIds, setRowOrderIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [degradedMode, setDegradedMode] = useState(false);
  const [, setClockTick] = useState(0);

  useEffect(() => {
    if (query) {
      setActiveQuery(query);
      return;
    }
    setActiveQuery({ entity: "workspaces", filters: [], sort: [{ field: "name", dir: "asc" }], limit: 50, offset: 0 });
  }, [query]);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const response = await listWorkspacesCanvasApi();
        if (!active) return;
        const baseRows: Array<Record<string, unknown>> = (response.workspaces || []).map((workspace: WorkspaceSummary) => ({
          id: workspace.id,
          slug: workspace.slug,
          name: workspace.name,
          org_name: workspace.org_name || workspace.name,
          kind: workspace.kind || "",
          lifecycle_stage: workspace.lifecycle_stage || "",
          auth_mode: workspace.auth_mode || "",
          parent_workspace_id: workspace.parent_workspace_id || "",
        }));
        let rows = [...baseRows];
        for (const filter of activeQuery.filters || []) {
          rows = rows.filter((row) => rowMatches(row, filter, WORKSPACES_DATASET_COLUMNS as unknown as Array<{ key: string; type: string }>));
        }
        for (const sortRow of [...(activeQuery.sort || [])].reverse()) {
          const field = String(sortRow.field || "");
          const dir = sortRow.dir === "asc" ? "asc" : "desc";
          rows.sort((left, right) => {
            const column = WORKSPACES_DATASET_COLUMNS.find((entry) => entry.key === field);
            const cmp = compareValues(left[field], right[field], column?.type);
            return dir === "asc" ? cmp : -cmp;
          });
        }
        const offset = Math.max(0, Number(activeQuery.offset || 0));
        const limit = Math.max(1, Number(activeQuery.limit || 50));
        const paged = rows.slice(offset, offset + limit);
        const nextPayload: CanvasTableResponse = {
          type: "canvas.table",
          title: "Workspaces",
          dataset: {
            name: "workspaces",
            primary_key: "id",
            columns: [...WORKSPACES_DATASET_COLUMNS],
            rows: paged,
            total_count: rows.length,
          },
          query: activeQuery,
        };
        setPayload(nextPayload);
        setRowOrderIds(paged.map((row) => String(row.id || "")));
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load workspaces");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [activeQuery]);

  useEffect(() => {
    emitTableContext({ onContextChange, panel, payload, query: activeQuery, selectedRowIds, focusedRowId, rowOrderIds });
  }, [activeQuery, focusedRowId, onContextChange, panel, payload, rowOrderIds, selectedRowIds]);

  useEffect(() => {
    if (!onTitleChange) return;
    if (!payload?.title) return;
    onTitleChange(String(payload.title));
  }, [onTitleChange, payload?.title]);

  if (loading) return <p className="muted">Loading workspaces…</p>;
  if (queryError) return <p className="muted">{queryError}</p>;
  if (error) return <p className="danger-text">{error}</p>;
  if (!payload) return <p className="muted">No workspaces found.</p>;

  return (
    <CanvasRenderer
      payload={payload}
      query={activeQuery}
      onSort={(field, sortable) => {
        if (!sortable) return;
        const same = activeQuery.sort?.[0]?.field === field;
        const dir = same && activeQuery.sort?.[0]?.dir === "asc" ? "desc" : "asc";
        setActiveQuery((current) => ({ ...current, sort: [{ field, dir }] }));
      }}
      onRowActivate={(rowId) => {
        setSelectedRowIds([rowId]);
        setFocusedRowId(rowId);
      }}
      onOpenDetail={onOpenDetail}
    />
  );
}

function WorkItemsPanel({
  panel,
  workspaceId,
  onContextChange,
  onOpenDetail,
  onTitleChange,
}: {
  panel: ConsolePanelSpec | null;
  workspaceId?: string;
  onContextChange?: ContextEmitter;
  onOpenDetail: (target: OpenDetailTarget, row: Record<string, unknown>) => void;
  onTitleChange?: (title: string) => void;
}) {
  const [items, setItems] = useState<WorkItemSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const next = await listWorkItems(undefined, undefined, undefined, undefined, workspaceId);
        if (!active) return;
        setItems(next.work_items || []);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load work items");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const payload = useMemo<CanvasTableResponse>(() => ({
    type: "canvas.table",
    title: "Work Items",
    dataset: {
      name: "work_items",
      primary_key: "id",
      columns: [
        { key: "title", label: "Title", type: "string", sortable: true, searchable: true, filterable: true },
        { key: "status", label: "Status", type: "string", sortable: true, filterable: true, searchable: true },
        { key: "work_item_id", label: "Work Item", type: "string", sortable: true, searchable: true, filterable: true },
        { key: "target_repo", label: "Repo", type: "string", sortable: true, searchable: true, filterable: true },
        { key: "updated_at", label: "Updated", type: "datetime", sortable: true, filterable: true },
      ],
      rows: items.map((item) => ({
        id: item.id,
        title: item.title,
        status: item.status,
        work_item_id: item.work_item_id || "",
        target_repo: item.target_repo || "",
        updated_at: item.updated_at || "",
      })),
      total_count: items.length,
    },
    query: { entity: "work_items", filters: [], sort: [{ field: "updated_at", dir: "desc" }], limit: 50, offset: 0 },
  }), [items]);

  useEffect(() => {
    if (!onContextChange || !panel?.panel_id) return;
    onContextChange({
      view_type: "table",
      dataset: payload.dataset,
      pagination: { limit: 50, offset: 0, total_count: items.length },
      ui: {
        active_panel_id: panel.panel_id,
        panel_id: panel.panel_id,
        panel_type: panel.panel_type || "table",
        instance_key: panel.instance_key || "work_items",
        active_group_id: panel.active_group_id || null,
        layout_engine: "simple",
      },
    });
  }, [items.length, onContextChange, panel, payload.dataset]);

  useEffect(() => {
    if (!onTitleChange) return;
    onTitleChange("Work Items");
  }, [onTitleChange]);

  if (loading) return <p className="muted">Loading work items…</p>;
  if (error) return <p className="danger-text">{error}</p>;
  return (
    <CanvasRenderer
      payload={payload}
      query={payload.query}
      onOpenDetail={onOpenDetail}
      onRowActivate={() => {
        // selection is informational only for now
      }}
    />
  );
}

function GoalListPanel({
  workspaceId,
  onOpenPanel,
  onTitleChange,
}: {
  workspaceId: string;
  onTitleChange?: (title: string) => void;
} & PanelProps) {
  const [goals, setGoals] = useState<GoalSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const next = await listGoals(workspaceId);
        if (!active) return;
        setGoals(next.goals || []);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load goals");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [workspaceId]);

  useEffect(() => {
    onTitleChange?.("Goals");
  }, [onTitleChange]);

  if (loading) return <p className="muted">Loading goals…</p>;
  if (error) return <p className="danger-text">{error}</p>;
  return (
    <section className="card">
      <div className="canvas-table-wrap">
        <table className="canvas-table">
          <thead>
            <tr>
              <th>Title</th>
              <th>Status</th>
              <th>Priority</th>
              <th>Threads</th>
              <th>Work Items</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {goals.map((goal) => (
              <tr key={goal.id}>
                <td>{goal.title}</td>
                <td>{goal.planning_status}</td>
                <td>{goal.priority}</td>
                <td>{goal.thread_count}</td>
                <td>{goal.work_item_count}</td>
                <td>
                  <button type="button" className="ghost sm" onClick={() => onOpenPanel("goal_detail", { goal_id: goal.id })}>
                    Open
                  </button>
                </td>
              </tr>
            ))}
            {!goals.length ? (
              <tr>
                <td colSpan={6} className="muted">No goals found.</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function GoalDetailPanel({
  goalId,
  workspaceId,
  onOpenPanel,
  onTitleChange,
}: {
  goalId: string;
  workspaceId: string;
  onTitleChange?: (title: string) => void;
} & PanelProps) {
  const [payload, setPayload] = useState<GoalDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionState, setActionState] = useState<{ status: "idle" | "submitting"; message: string | null }>({
    status: "idle",
    message: null,
  });

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const next = await getGoal(goalId);
        if (!active) return;
        setPayload(next);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load goal");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [goalId]);

  useEffect(() => {
    onTitleChange?.(payload?.title || "Goal");
  }, [onTitleChange, payload?.title]);

  if (loading) return <p className="muted">Loading goal…</p>;
  if (error) return <p className="danger-text">{error}</p>;
  if (!payload) return <p className="muted">Goal not found.</p>;

  const recommendationActions = Array.isArray(payload.recommendation?.actions) ? payload.recommendation?.actions : [];
  const queueableAction = recommendationActions.find((action) => action.type === "approve_and_queue");
  const reviewThreadAction = recommendationActions.find((action) => action.type === "review_thread");
  const recommendationId = payload.recommendation?.recommendation_id || null;
  const reviewWorkItemId =
    payload.recommendation?.work_item_id ||
    payload.recommendation?.recommended_work_items?.[0]?.id ||
    null;

  async function handleApproveAndQueue() {
    try {
      setActionState({ status: "submitting", message: null });
      const response = await reviewGoal(goalId, "approve_and_queue", recommendationId);
      setPayload(response.goal);
      setActionState({
        status: "idle",
        message:
          response.status === "approved"
            ? "Approved and queued the recommended slice."
            : response.status === "already_queued"
              ? "The recommended slice is already queued."
              : response.status === "no_recommendation"
                ? "No queueable recommendation is available right now."
                : response.status === "stale_recommendation"
                  ? "That recommendation is no longer current. Refresh the goal and review the latest next slice."
                  : null,
      });
    } catch (err) {
      setActionState({ status: "idle", message: err instanceof Error ? err.message : "Failed to approve recommendation" });
    }
  }

  return (
    <div className="panel-section-stack">
      <section className="card">
        <div className="detail-grid">
          <div><div className="field-label">Title</div><div className="field-value">{payload.title}</div></div>
          <div><div className="field-label">Status</div><div className="field-value">{payload.planning_status}</div></div>
          <div><div className="field-label">Priority</div><div className="field-value">{payload.priority}</div></div>
          <div><div className="field-label">Workspace</div><div className="field-value">{workspaceId}</div></div>
          <div><div className="field-label">Goal Type</div><div className="field-value">{payload.goal_type}</div></div>
          <div><div className="field-label">Conversation</div><div className="field-value">{payload.source_conversation_id || "—"}</div></div>
        </div>
        {payload.description ? <p className="muted" style={{ marginTop: 12 }}>{payload.description}</p> : null}
        {payload.planning_summary ? <InlineMessage tone="info" title="Planning Summary" body={payload.planning_summary} /> : null}
      </section>
      {payload.development_loop_summary ? (
        <section className="card">
          <div className="card-header"><div><p className="muted">Development Loop</p></div></div>
          <div className="detail-grid">
            <div><div className="field-label">Goal Status</div><div className="field-value">{payload.development_loop_summary.goal_status}</div></div>
            <div><div className="field-label">Active Threads</div><div className="field-value">{payload.metrics?.active_threads ?? payload.goal_progress?.active_threads ?? 0}</div></div>
            <div><div className="field-label">Blocked Threads</div><div className="field-value">{payload.metrics?.blocked_threads ?? payload.goal_progress?.blocked_threads ?? 0}</div></div>
            <div><div className="field-label">Artifacts Produced</div><div className="field-value">{payload.metrics?.artifact_production_count ?? payload.goal_progress?.artifact_production_count ?? 0}</div></div>
          </div>
          {actionState.message ? <p className="muted" style={{ marginTop: 12 }}>{actionState.message}</p> : null}
          <div className="canvas-table-wrap" style={{ marginTop: 12 }}>
            <table className="canvas-table">
              <thead>
                <tr>
                  <th>Thread</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {payload.development_loop_summary.threads.map((thread) => (
                  <tr key={thread.thread_id}>
                    <td>{thread.title}</td>
                    <td>{thread.thread_status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="canvas-table-wrap" style={{ marginTop: 12 }}>
            <table className="canvas-table">
              <thead>
                <tr>
                  <th>Recent Work</th>
                  <th>Status</th>
                  <th>Artifacts</th>
                  <th>Run</th>
                </tr>
              </thead>
              <tbody>
                {payload.development_loop_summary.recent_work_results.map((result) => (
                  <tr key={result.work_item_id}>
                    <td>{result.title}</td>
                    <td>{result.status}</td>
                    <td>{result.artifact_count ? `${result.artifact_count}` : "0"}</td>
                    <td>{result.run_id || "—"}</td>
                  </tr>
                ))}
                {!payload.development_loop_summary.recent_work_results.length ? (
                  <tr><td colSpan={4} className="muted">No recent work results yet.</td></tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
      {payload.goal_health ? (
        <section className="card">
          <div className="card-header"><div><p className="muted">Goal Health</p></div></div>
          <div className="detail-grid">
            <div><div className="field-label">Progress</div><div className="field-value">{payload.goal_health.progress_percent}%</div></div>
            <div><div className="field-label">Active Threads</div><div className="field-value">{payload.goal_health.active_threads}</div></div>
            <div><div className="field-label">Blocked Threads</div><div className="field-value">{payload.goal_health.blocked_threads}</div></div>
            <div><div className="field-label">Recent Artifacts</div><div className="field-value">{payload.goal_health.recent_artifacts}</div></div>
          </div>
        </section>
      ) : null}
      {payload.development_insights?.length ? (
        <section className="card">
          <div className="card-header"><div><p className="muted">Development Insights</p></div></div>
          <div className="detail-list">
            {payload.development_insights.map((insight) => (
              <div key={insight.key} style={{ marginBottom: 12 }}>
                <div className="field-value">{insight.summary}</div>
                {insight.evidence.length ? (
                  <ul className="detail-list">
                    {insight.evidence.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ))}
          </div>
        </section>
      ) : null}
      <section className="card">
        <div className="card-header"><div><p className="muted">Threads</p></div></div>
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Status</th>
                <th>Priority</th>
                <th>Queued</th>
                <th>Running</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {payload.threads.map((thread) => (
                <tr key={thread.id}>
                  <td>{thread.title}</td>
                  <td>{thread.status}</td>
                  <td>{thread.priority}</td>
                  <td>{thread.queued_work_items}</td>
                  <td>{thread.running_work_items}</td>
                  <td><button type="button" className="ghost sm" onClick={() => onOpenPanel("thread_detail", { thread_id: thread.id })}>Thread</button></td>
                </tr>
              ))}
              {!payload.threads.length ? <tr><td colSpan={6} className="muted">No threads planned yet.</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>
      <section className="card">
        <div className="card-header"><div><p className="muted">Work Items</p></div></div>
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Status</th>
                <th>Thread</th>
                <th>Repo</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {payload.work_items.map((item) => (
                <tr key={item.id}>
                  <td>{item.title}</td>
                  <td>{item.status}</td>
                  <td>{item.thread_title || "—"}</td>
                  <td>{item.target_repo || "—"}</td>
                  <td><button type="button" className="ghost sm" onClick={() => onOpenPanel("work_item_detail", { work_item_id: item.id })}>Work Item</button></td>
                </tr>
              ))}
              {!payload.work_items.length ? <tr><td colSpan={5} className="muted">No work items planned yet.</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>
      {payload.recommendation?.summary ? (
        <section className="card">
          <InlineMessage tone="info" title="Recommended Next Slice" body={payload.recommendation.summary} />
          {payload.recommendation.reasoning_summary ? <p className="muted" style={{ marginTop: 10 }}>{payload.recommendation.reasoning_summary}</p> : null}
          <div className="inline-action-row" style={{ marginTop: 12 }}>
            <button type="button" className="ghost sm" disabled={!queueableAction || actionState.status === "submitting"} onClick={handleApproveAndQueue}>
              Approve and Queue
            </button>
            <button
              type="button"
              className="ghost sm"
              disabled={!reviewThreadAction?.target_thread}
              onClick={() => reviewThreadAction?.target_thread && onOpenPanel("thread_detail", { thread_id: reviewThreadAction.target_thread })}
            >
              View Thread
            </button>
            <button
              type="button"
              className="ghost sm"
              disabled={!reviewWorkItemId}
              onClick={() => reviewWorkItemId && onOpenPanel("work_item_detail", { work_item_id: reviewWorkItemId })}
            >
              Review Work Items
            </button>
          </div>
        </section>
      ) : null}
    </div>
  );
}

function ThreadListPanel({
  workspaceId,
  onOpenPanel,
  onTitleChange,
}: {
  workspaceId: string;
  onTitleChange?: (title: string) => void;
} & PanelProps) {
  const [threads, setThreads] = useState<CoordinationThreadSummary[]>([]);
  const [queue, setQueue] = useState<WorkQueueResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const [threadRows, queueRows] = await Promise.all([
          listCoordinationThreads(workspaceId),
          getWorkQueue(workspaceId),
        ]);
        if (!active) return;
        setThreads(threadRows.threads || []);
        setQueue(queueRows);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load threads");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [workspaceId]);

  useEffect(() => {
    onTitleChange?.("Threads");
  }, [onTitleChange]);

  if (loading) return <p className="muted">Loading XCO threads…</p>;
  if (error) return <p className="danger-text">{error}</p>;

  return (
    <div className="panel-section-stack">
      <section className="card">
        <div className="card-header">
          <div>
            <h3>Threads</h3>
            <p className="muted">Durable lines of effort coordinated by XCO.</p>
          </div>
        </div>
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Status</th>
                <th>Priority</th>
                <th>Queued</th>
                <th>Running</th>
                <th>Review</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {threads.map((thread) => (
                <tr key={thread.id}>
                  <td>{thread.title}</td>
                  <td>{thread.status}</td>
                  <td>{thread.priority}</td>
                  <td>{thread.queued_work_items}</td>
                  <td>{thread.running_work_items}</td>
                  <td>{thread.awaiting_review_work_items}</td>
                  <td>
                    <button type="button" className="ghost sm" onClick={() => onOpenPanel("thread_detail", { thread_id: thread.id })}>
                      Open
                    </button>
                  </td>
                </tr>
              ))}
              {!threads.length ? (
                <tr>
                  <td colSpan={7} className="muted">
                    No XCO threads found.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
      <section className="card">
        <div className="card-header">
          <div>
            <h3>Derived Queue</h3>
            <p className="muted">Next eligible work items in deterministic dispatch order.</p>
          </div>
        </div>
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Thread</th>
                <th>Priority</th>
                <th>Work Item</th>
                <th>Task ID</th>
              </tr>
            </thead>
            <tbody>
              {(queue?.items || []).map((entry) => (
                <tr key={`${entry.thread_id}:${entry.task_id}`}>
                  <td>{entry.thread_title}</td>
                  <td>{entry.thread_priority}</td>
                  <td>{entry.work_item_id}</td>
                  <td>{entry.task_id}</td>
                </tr>
              ))}
              {!queue?.items?.length ? (
                <tr>
                  <td colSpan={4} className="muted">
                    No eligible work items are currently queued.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function ThreadDetailPanel({
  threadId,
  workspaceId,
  onOpenPanel,
  onTitleChange,
}: {
  threadId: string;
  workspaceId: string;
  onTitleChange?: (title: string) => void;
} & PanelProps) {
  const [payload, setPayload] = useState<CoordinationThreadDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionState, setActionState] = useState<{ status: "idle" | "submitting"; message: string | null }>({
    status: "idle",
    message: null,
  });

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const detail = await getCoordinationThread(threadId);
        if (!active) return;
        setPayload(detail);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load thread");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [threadId]);

  useEffect(() => {
    onTitleChange?.(payload?.title || "Thread");
  }, [onTitleChange, payload?.title]);

  async function handleReviewAction(action: "resume_thread" | "queue_next_slice" | "mark_thread_completed") {
    try {
      setActionState({ status: "submitting", message: null });
      const response = await reviewCoordinationThread(threadId, action);
      setPayload(response.thread);
      setActionState({ status: "idle", message: response.summary || null });
    } catch (err) {
      setActionState({ status: "idle", message: err instanceof Error ? err.message : "Failed to update thread review state" });
    }
  }

  if (loading) return <p className="muted">Loading XCO thread…</p>;
  if (error) return <p className="danger-text">{error}</p>;
  if (!payload) return <p className="muted">Thread not found.</p>;

  return (
    <div className="panel-section-stack">
      <section className="card">
        <div className="detail-grid">
          <div><div className="field-label">Title</div><div className="field-value">{payload.title}</div></div>
          <div><div className="field-label">Status</div><div className="field-value">{payload.status}</div></div>
          <div><div className="field-label">Priority</div><div className="field-value">{payload.priority}</div></div>
          <div><div className="field-label">Workspace</div><div className="field-value">{workspaceId}</div></div>
          <div><div className="field-label">WIP limit</div><div className="field-value">{payload.work_in_progress_limit}</div></div>
          <div><div className="field-label">Owner</div><div className="field-value">{payload.owner || "—"}</div></div>
        </div>
        {payload.description ? <p className="muted" style={{ marginTop: 12 }}>{payload.description}</p> : null}
      </section>
      <section className="card">
        <div className="card-header">
          <div>
            <p className="muted">Thread Review</p>
          </div>
        </div>
        <div className="detail-grid">
          <div><div className="field-label">Progress</div><div className="field-value">{payload.thread_progress_status || payload.status}</div></div>
          <div><div className="field-label">Completed</div><div className="field-value">{payload.work_items_completed ?? payload.completed_work_items}</div></div>
          <div><div className="field-label">Ready</div><div className="field-value">{payload.work_items_ready ?? payload.queued_work_items}</div></div>
          <div><div className="field-label">Blocked</div><div className="field-value">{payload.work_items_blocked ?? payload.awaiting_review_work_items}</div></div>
          <div><div className="field-label">Avg Run Duration</div><div className="field-value">{payload.metrics?.average_run_duration_seconds ? `${payload.metrics.average_run_duration_seconds}s` : "—"}</div></div>
          <div><div className="field-label">Failed Work</div><div className="field-value">{payload.metrics?.failed_work_items ?? 0}</div></div>
        </div>
        {actionState.message ? <p className="muted" style={{ marginTop: 12 }}>{actionState.message}</p> : null}
        <div className="inline-action-row" style={{ marginTop: 12 }}>
          <button
            type="button"
            className="ghost sm"
            disabled={payload.status !== "paused" || actionState.status === "submitting"}
            onClick={() => handleReviewAction("resume_thread")}
          >
            Resume Thread
          </button>
          <button
            type="button"
            className="ghost sm"
            disabled={payload.status !== "active" || actionState.status === "submitting"}
            onClick={() => handleReviewAction("queue_next_slice")}
          >
            Queue Next Slice
          </button>
          <button
            type="button"
            className="ghost sm"
            disabled={payload.status === "completed" || actionState.status === "submitting"}
            onClick={() => handleReviewAction("mark_thread_completed")}
          >
            Mark Thread Completed
          </button>
        </div>
      </section>
      <section className="card">
        <div className="card-header">
          <div>
            <h3>Work Items</h3>
            <p className="muted">Durable work coordinated under this thread.</p>
          </div>
        </div>
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Status</th>
                <th>Repo</th>
                <th>Run</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {payload.work_items.map((item) => (
                <tr key={item.id}>
                  <td>{item.title}</td>
                  <td>{item.status}</td>
                  <td>{item.target_repo || "—"}</td>
                  <td>{item.runtime_run_id || "—"}</td>
                  <td>
                    <div className="inline-action-row">
                      <button type="button" className="ghost sm" onClick={() => onOpenPanel("work_item_detail", { work_item_id: item.id })}>
                        Work Item
                      </button>
                      {item.runtime_run_id ? (
                        <button type="button" className="ghost sm" onClick={() => onOpenPanel("run_detail", { run_id: item.runtime_run_id })}>
                          Run
                        </button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
              {!payload.work_items.length ? (
                <tr>
                  <td colSpan={5} className="muted">
                    No work items are attached to this thread yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
      <section className="card">
        <div className="card-header">
          <div>
            <h3>Recent Runs</h3>
            <p className="muted">Recent runtime results linked to this thread.</p>
          </div>
        </div>
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Run</th>
                <th>Status</th>
                <th>Summary</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {payload.recent_runs.map((run) => (
                <tr key={run.id}>
                  <td>{run.id}</td>
                  <td>{run.status || "—"}</td>
                  <td>{run.summary || run.error || "—"}</td>
                  <td>
                    <button type="button" className="ghost sm" onClick={() => onOpenPanel("run_detail", { run_id: run.id })}>
                      Run
                    </button>
                  </td>
                </tr>
              ))}
              {!payload.recent_runs.length ? (
                <tr>
                  <td colSpan={4} className="muted">
                    No recent run results are available for this thread yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
      <section className="card">
        <div className="card-header">
          <div>
            <h3>Recent Artifacts</h3>
            <p className="muted">Outputs produced by runs associated with this thread.</p>
          </div>
        </div>
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Label</th>
                <th>Type</th>
                <th>Run</th>
                <th>Work Item</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {payload.recent_artifacts.map((artifact) => (
                <tr key={`${artifact.run_id || "run"}:${artifact.id}`}>
                  <td>{artifact.label || artifact.uri || artifact.id}</td>
                  <td>{artifact.artifact_type}</td>
                  <td>{artifact.run_id || "—"}</td>
                  <td>{(artifact as Record<string, unknown>).work_item_id ? String((artifact as Record<string, unknown>).work_item_id) : "—"}</td>
                  <td>
                    {artifact.run_id && artifact.id ? (
                      <button
                        type="button"
                        className="ghost sm"
                        onClick={() =>
                          onOpenPanel("artifact_detail", {
                            runtime_run_id: artifact.run_id,
                            runtime_artifact_id: artifact.id,
                          })
                        }
                      >
                        Artifact
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
              {!payload.recent_artifacts.length ? (
                <tr>
                  <td colSpan={5} className="muted">
                    No artifacts have been registered for this thread yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
      <section className="card">
        <div className="card-header">
          <div>
            <h3>Activity Timeline</h3>
            <p className="muted">Ordered execution history reconstructed from durable work items, runs, and coordination events.</p>
          </div>
        </div>
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Event</th>
                <th>Source</th>
                <th>Run</th>
                <th>Work Item</th>
                <th>Summary</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {payload.timeline.map((event) => (
                <tr key={event.id}>
                  <td>{event.event_type}</td>
                  <td>{event.source || "—"}</td>
                  <td>{event.run_id || "—"}</td>
                  <td>{event.work_item_title || event.work_item_id || "—"}</td>
                  <td>{event.summary || event.status || "—"}</td>
                  <td>{String(event.created_at || "")}</td>
                </tr>
              ))}
              {!payload.timeline.length ? (
                <tr>
                  <td colSpan={6} className="muted">
                    No coordination events recorded yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function WorkItemDetailPanel({
  workItemId,
  workspaceId,
  onOpenPanel,
}: {
  workItemId: string;
  workspaceId?: string;
} & PanelProps) {
  const [payload, setPayload] = useState<WorkItemDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const next = await getWorkItem(workItemId);
        if (!active) return;
        setPayload(next);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load work item");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [workItemId]);

  if (loading) return <p className="muted">Loading work item…</p>;
  if (error) return <p className="danger-text">{error}</p>;
  if (!payload) return <p className="muted">Work item not found.</p>;

  return (
    <div className="ems-panel-body">
      <div className="detail-grid">
        <div><div className="field-label">Title</div><div className="field-value">{payload.title}</div></div>
        <div><div className="field-label">Status</div><div className="field-value">{payload.status}</div></div>
        <div><div className="field-label">Work Item</div><div className="field-value">{payload.work_item_id || payload.id}</div></div>
        <div><div className="field-label">Intent</div><div className="field-value">{payload.intent_type || "—"}</div></div>
        <div><div className="field-label">Repo</div><div className="field-value">{payload.target_repo || "—"}</div></div>
        <div><div className="field-label">Branch</div><div className="field-value">{payload.target_branch || "—"}</div></div>
        <div><div className="field-label">Requested By</div><div className="field-value">{payload.requested_by || "—"}</div></div>
        <div><div className="field-label">Conversation</div><div className="field-value">{payload.source_conversation_id || "—"}</div></div>
      </div>
      {payload.description ? <p>{payload.description}</p> : null}
      {payload.last_error ? <InlineMessage tone="warn" title="Last error" body={payload.last_error} /> : null}
      {payload.runtime_run_id ? (
        <div className="inline-actions" style={{ marginTop: 8 }}>
          {payload.thread_detail?.id ? (
            <button
              type="button"
              className="ghost sm"
              onClick={() => onOpenPanel("thread_detail", { thread_id: payload.thread_detail?.id })}
            >
              Open Thread
            </button>
          ) : null}
          <button
            type="button"
            className="ghost sm"
            onClick={() => onOpenPanel("run_detail", { run_id: payload.runtime_run_id })}
          >
            Open Run
          </button>
          <span className="muted small">
            Latest runtime run: {payload.runtime_run_id}{workspaceId ? ` · workspace ${workspaceId}` : ""}
          </span>
        </div>
      ) : null}
      {payload.result_run_artifacts?.length ? (
        <section className="card" style={{ marginTop: 12 }}>
          <div className="card-header"><h3>Artifacts</h3></div>
          <div className="canvas-table-wrap">
            <table className="canvas-table">
              <thead><tr><th>Label</th><th>Type</th><th>Created</th></tr></thead>
              <tbody>
                {payload.result_run_artifacts.map((artifact) => (
                  <tr key={artifact.id}>
                    <td>
                      <button
                        type="button"
                        className="ghost sm"
                        onClick={() => {
                          if (!payload.runtime_run_id) return;
                          onOpenPanel("artifact_detail", {
                            runtime_run_id: payload.runtime_run_id,
                            runtime_artifact_id: artifact.id,
                          });
                        }}
                      >
                        {artifact.name}
                      </button>
                    </td>
                    <td>{artifact.kind || "artifact"}</td>
                    <td>{artifact.created_at || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}

function RuntimeArtifactDetailPanel({
  runId,
  artifactId,
  workspaceId,
  onOpenPanel,
}: {
  runId: string;
  artifactId: string;
  workspaceId?: string;
} & PanelProps) {
  const [payload, setPayload] = useState<RuntimeRunArtifactContent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        if (!workspaceId) {
          setPayload(null);
          setError("Workspace context is required.");
          return;
        }
        setLoading(true);
        setError(null);
        const next = await getRuntimeRunArtifactContent(workspaceId, runId, artifactId);
        if (!active) return;
        setPayload(next);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load runtime artifact");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [artifactId, runId, workspaceId]);

  if (loading) return <p className="muted">Loading run artifact…</p>;
  if (error) return <p className="danger-text">{error}</p>;
  if (!payload) return <p className="muted">Run artifact not found.</p>;

  const contentType = String(payload.content_type || "").toLowerCase();
  const isJson = contentType.includes("json") || payload.label.endsWith(".json");
  let renderedContent = payload.content;
  if (isJson) {
    try {
      renderedContent = JSON.stringify(JSON.parse(payload.content || "{}"), null, 2);
    } catch {
      renderedContent = payload.content;
    }
  }

  return (
    <div className="ems-panel-body">
      <div className="inline-actions" style={{ marginBottom: 12 }}>
        <button type="button" className="ghost sm" onClick={() => onOpenPanel("run_detail", { run_id: runId })}>
          Open Run
        </button>
        <span className="muted small">Run {runId}</span>
      </div>
      <div className="detail-grid">
        <div><div className="field-label">Label</div><div className="field-value">{payload.label}</div></div>
        <div><div className="field-label">Type</div><div className="field-value">{payload.artifact_type}</div></div>
        <div><div className="field-label">URI</div><div className="field-value">{payload.uri}</div></div>
      </div>
      <section className="card" style={{ marginTop: 12 }}>
        <div className="card-header">
          <div>
            <p className="muted">Artifact Evolution</p>
          </div>
        </div>
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Label</th>
                <th>Run</th>
                <th>Created</th>
                <th>Current</th>
              </tr>
            </thead>
            <tbody>
              {(payload.evolution || []).map((entry) => (
                <tr key={`${entry.run_id}:${entry.artifact_id}`}>
                  <td>{entry.label}</td>
                  <td>{entry.run_id}</td>
                  <td>{String(entry.created_at || "—")}</td>
                  <td>{entry.is_current ? "yes" : "no"}</td>
                </tr>
              ))}
              {!payload.evolution?.length ? (
                <tr>
                  <td colSpan={4} className="muted">
                    No prior artifact versions were found for this logical artifact.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
      {payload.analysis ? (
        <section className="card" style={{ marginTop: 12 }}>
          <div className="card-header">
            <div>
              <p className="muted">Artifact Analysis</p>
            </div>
          </div>
          <div className="detail-grid">
            <div><div className="field-label">Status</div><div className="field-value">{payload.analysis.status}</div></div>
            <div><div className="field-label">Versions</div><div className="field-value">{payload.analysis.version_count}</div></div>
            <div><div className="field-label">Recent Activity</div><div className="field-value">{payload.analysis.recent_activity_count}</div></div>
            <div><div className="field-label">Provenance</div><div className="field-value">{payload.analysis.provenance.summary}</div></div>
          </div>
          {payload.analysis.observations.length ? (
            <div style={{ marginTop: 12 }}>
              <div className="field-label">Observations</div>
              <ul className="detail-list">
                {payload.analysis.observations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {payload.analysis.evidence.length ? (
            <div style={{ marginTop: 12 }}>
              <div className="field-label">Evidence</div>
              <ul className="detail-list">
                {payload.analysis.evidence.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {payload.analysis.suggested_human_review_focus ? (
            <div style={{ marginTop: 12 }}>
              <div className="field-label">Suggested Review Focus</div>
              <div className="field-value">{payload.analysis.suggested_human_review_focus}</div>
            </div>
          ) : null}
        </section>
      ) : null}
      <pre className="code-block">{renderedContent}</pre>
    </div>
  );
}

function RunsPanel({
  query,
  queryError,
  workspaceId,
  panel,
  onContextChange,
  onOpenDetail,
  onTitleChange,
}: {
  query?: CanvasQuery;
  queryError?: string;
  workspaceId?: string;
  panel: ConsolePanelSpec | null;
  onContextChange?: ContextEmitter;
  onOpenDetail: (target: OpenDetailTarget, row: Record<string, unknown>) => void;
  onTitleChange?: (title: string) => void;
}) {
  const [payload, setPayload] = useState<CanvasTableResponse | null>(null);
  const [runs, setRuns] = useState<RuntimeRunSummary[]>([]);
  const [activeQuery, setActiveQuery] = useState<CanvasQuery>({
    entity: "runs",
    filters: [],
    sort: [{ field: "created_at", dir: "desc" }],
    limit: 50,
    offset: 0,
  });
  const [selectedRowIds, setSelectedRowIds] = useState<string[]>([]);
  const [focusedRowId, setFocusedRowId] = useState<string | null>(null);
  const [rowOrderIds, setRowOrderIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [degradedMode, setDegradedMode] = useState(false);

  useEffect(() => {
    if (query) {
      setActiveQuery(query);
      return;
    }
    setActiveQuery({ entity: "runs", filters: [], sort: [{ field: "created_at", dir: "desc" }], limit: 50, offset: 0 });
  }, [query]);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        if (!workspaceId) {
          setPayload(null);
          setError("Workspace context is required.");
          return;
        }
        setLoading(true);
        setError(null);
        const statusEq = (activeQuery.filters || []).find((entry) => entry.field === "status" && entry.op === "eq");
        const response = await listRuntimeRunsCanvasApi(workspaceId, statusEq ? String(statusEq.value || "") : undefined);
        if (!active) return;
        setRuns(response.runs || []);
        setDegradedMode(false);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load runs");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [activeQuery, workspaceId]);

  useEffect(() => {
    const searchContains = (activeQuery.filters || []).find((entry) => entry.op === "contains" && ["summary", "work_item_id", "worker_type"].includes(entry.field));
    const baseRows: Array<Record<string, unknown>> = runs.map((run: RuntimeRunSummary) => ({
      id: run.id,
      work_item_id: run.work_item_id || "",
      worker_type: run.worker_type || "",
      status: run.status,
      elapsed_time: formatDuration(run.elapsed_time_seconds),
      elapsed_time_seconds: run.elapsed_time_seconds ?? 0,
      heartbeat_freshness: run.heartbeat_freshness || "missing",
      summary: run.summary || "",
      created_at: toIso(run.created_at),
      started_at: toIso(run.started_at),
      completed_at: toIso(run.completed_at),
    }));
    let rows = [...baseRows];
    for (const filter of activeQuery.filters || []) {
      rows = rows.filter((row) => rowMatches(row, filter, RUNS_DATASET_COLUMNS as unknown as Array<{ key: string; type: string }>));
    }
    if (searchContains) {
      const needle = String(searchContains.value || "").toLowerCase();
      rows = rows.filter((row) =>
        [row.summary, row.work_item_id, row.worker_type, row.id].some((value) => String(value || "").toLowerCase().includes(needle))
      );
    }
    for (const sortRow of [...(activeQuery.sort || [])].reverse()) {
      const field = String(sortRow.field || "");
      const dir = sortRow.dir === "asc" ? "asc" : "desc";
      rows.sort((left, right) => {
        const effectiveField = field === "elapsed_time" ? "elapsed_time_seconds" : field;
        const column = RUNS_DATASET_COLUMNS.find((entry) => entry.key === field);
        const cmp = compareValues(left[effectiveField], right[effectiveField], column?.type);
        return dir === "asc" ? cmp : -cmp;
      });
    }
    const offset = Math.max(0, Number(activeQuery.offset || 0));
    const limit = Math.max(1, Number(activeQuery.limit || 50));
    const paged = rows.slice(offset, offset + limit);
    setPayload({
      type: "canvas.table",
      title: "Runs",
      dataset: {
        name: "runs",
        primary_key: "id",
        columns: [...RUNS_DATASET_COLUMNS],
        rows: paged,
        total_count: rows.length,
      },
      query: activeQuery,
    });
    setRowOrderIds(paged.map((row) => String(row.id || "")));
  }, [activeQuery, runs]);

  useEffect(() => {
    if (!workspaceId) return;
    const subscription = subscribeRuntimeEventStream({
      workspaceId,
      onOpen: () => setDegradedMode(false),
      onError: () => setDegradedMode(true),
      onEvent: (event) => {
        setDegradedMode(false);
        setRuns((current) => applyRuntimeEventToRuns(current, event));
      },
    });
    return () => subscription.close();
  }, [workspaceId]);

  useEffect(() => {
    if (!degradedMode) return;
    const interval = window.setInterval(() => {
      setActiveQuery((current) => ({ ...current }));
    }, 30000);
    return () => window.clearInterval(interval);
  }, [degradedMode]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      setRuns((current) => current.map((run) => refreshRuntimeRunSummary(run)));
    }, 5000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    emitTableContext({ onContextChange, panel, payload, query: activeQuery, selectedRowIds, focusedRowId, rowOrderIds });
  }, [activeQuery, focusedRowId, onContextChange, panel, payload, rowOrderIds, selectedRowIds]);

  useEffect(() => {
    if (!onTitleChange) return;
    if (!payload?.title) return;
    onTitleChange(String(payload.title));
  }, [onTitleChange, payload?.title]);

  if (loading) return <p className="muted">Loading runs…</p>;
  if (queryError) return <p className="muted">{queryError}</p>;
  if (error) return <p className="danger-text">{error}</p>;
  if (!payload) return <p className="muted">No runs found.</p>;

  return (
    <>
      {degradedMode ? <p className="muted small">Live runtime stream unavailable. Falling back to periodic refresh.</p> : null}
      <CanvasRenderer
        payload={payload}
        query={activeQuery}
        onSort={(field, sortable) => {
          if (!sortable) return;
          const same = activeQuery.sort?.[0]?.field === field;
          const dir = same && activeQuery.sort?.[0]?.dir === "asc" ? "desc" : "asc";
          setActiveQuery((current) => ({ ...current, sort: [{ field, dir }] }));
        }}
        onRowActivate={(rowId) => {
          setSelectedRowIds([rowId]);
          setFocusedRowId(rowId);
        }}
        onOpenDetail={onOpenDetail}
      />
    </>
  );
}

function RunDetailPanel({
  runId,
  workspaceId,
  panel,
  onContextChange,
  onOpenPanel,
}: {
  runId: string;
  workspaceId?: string;
  panel: ConsolePanelSpec | null;
  onContextChange?: ContextEmitter;
} & PanelProps) {
  const [payload, setPayload] = useState<RuntimeRunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [degradedMode, setDegradedMode] = useState(false);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        if (!workspaceId) {
          setPayload(null);
          setError("Workspace context is required.");
          return;
        }
        setLoading(true);
        setError(null);
        const next = await getRuntimeRunCanvasApi(workspaceId, runId);
        if (!active) return;
        setPayload(next);
        setDegradedMode(false);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load run detail");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [runId, workspaceId]);

  useEffect(() => {
    if (!workspaceId || !runId) return;
    const subscription = subscribeRuntimeEventStream({
      workspaceId,
      onOpen: () => setDegradedMode(false),
      onError: () => setDegradedMode(true),
      onEvent: (event) => {
        if (event.run_id !== runId) return;
        setDegradedMode(false);
        setPayload((current) => (current ? applyRuntimeEventToRunDetail(current, event) : current));
      },
    });
    return () => subscription.close();
  }, [runId, workspaceId]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      setPayload((current) => (current ? refreshRuntimeRunDetail(current) : current));
    }, 5000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!degradedMode || !workspaceId || !runId) return;
    const interval = window.setInterval(async () => {
      try {
        const next = await getRuntimeRunCanvasApi(workspaceId, runId);
        setPayload(next);
      } catch {
        // keep current state
      }
    }, 30000);
    return () => window.clearInterval(interval);
  }, [degradedMode, runId, workspaceId]);

  useEffect(() => {
    if (!onContextChange || !panel?.panel_id || !payload) return;
    onContextChange({
      view_type: "detail",
        entity_type: "run",
        entity_id: payload.id,
        available_tabs: ["overview", "timeline", "artifacts"],
        active_tab: "overview",
        ui: {
        active_panel_id: panel.panel_id,
        panel_id: panel.panel_id,
        panel_type: panel.panel_type || "detail",
        instance_key: panel.instance_key || `run:${payload.id}`,
        active_group_id: panel.active_group_id || null,
        layout_engine: "simple",
      },
    });
  }, [onContextChange, panel, payload]);

  if (loading) return <p className="muted">Loading run detail…</p>;
  if (error) return <p className="danger-text">{error}</p>;
  if (!payload) return <p className="muted">Run not found.</p>;

  return (
    <div className="ems-panel-body">
      {degradedMode ? <p className="muted small">Live runtime stream unavailable. Falling back to periodic refresh.</p> : null}
      <div className="detail-grid">
        <div>
          <div className="field-label">Run</div>
          <div className="field-value">{payload.id}</div>
        </div>
        <div>
          <div className="field-label">Status</div>
          <div className="field-value">{payload.status}</div>
        </div>
        <div>
          <div className="field-label">Worker</div>
          <div className="field-value">{payload.worker_id || payload.worker_type || "—"}</div>
        </div>
        <div>
          <div className="field-label">Elapsed</div>
          <div className="field-value">{formatDuration(payload.elapsed_time_seconds)}</div>
        </div>
        <div>
          <div className="field-label">Heartbeat</div>
          <div className="field-value">{payload.heartbeat_freshness || "missing"}</div>
        </div>
        <div>
          <div className="field-label">Work Item</div>
          <div className="field-value">{payload.work_item_id || "—"}</div>
        </div>
        <div>
          <div className="field-label">Target Repo</div>
          <div className="field-value">{payload.target.repo || "—"}</div>
        </div>
        <div>
          <div className="field-label">Target Branch</div>
          <div className="field-value">{payload.target.branch || "—"}</div>
        </div>
        <div>
          <div className="field-label">Policy</div>
          <div className="field-value">
            retries {payload.policy.max_retries} · human review {payload.policy.require_human_review_on_failure ? "required" : "optional"}
          </div>
        </div>
      </div>
      {payload.summary ? <p>{payload.summary}</p> : null}
      {payload.failure_reason ? <InlineMessage tone="error" title="Failure reason" body={payload.failure_reason} /> : null}
      {payload.escalation_reason ? <InlineMessage tone="warn" title="Escalation reason" body={payload.escalation_reason} /> : null}
      <section className="card" style={{ marginTop: 12 }}>
        <div className="card-header">
          <h3>Step Timeline</h3>
        </div>
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Step</th>
                <th>Status</th>
                <th>Started</th>
                <th>Completed</th>
                <th>Summary</th>
              </tr>
            </thead>
            <tbody>
              {payload.steps.map((step) => (
                <tr key={step.id}>
                  <td>{step.label || step.step_key}</td>
                  <td>{step.status}</td>
                  <td>{step.started_at || "—"}</td>
                  <td>{step.completed_at || "—"}</td>
                  <td>{step.summary || "—"}</td>
                </tr>
              ))}
              {!payload.steps.length ? (
                <tr>
                  <td colSpan={5} className="muted">No steps reported.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
      <section className="card" style={{ marginTop: 12 }}>
        <div className="card-header">
          <h3>Artifacts</h3>
        </div>
        <div className="canvas-table-wrap">
          <table className="canvas-table">
            <thead>
              <tr>
                <th>Label</th>
                <th>Type</th>
                <th>URI</th>
              </tr>
            </thead>
            <tbody>
              {payload.artifacts.map((artifact) => (
                <tr key={artifact.id}>
                  <td>
                    <button
                      type="button"
                      className="ghost sm"
                      onClick={() =>
                        onOpenPanel("artifact_detail", {
                          runtime_run_id: runId,
                          runtime_artifact_id: artifact.id,
                        })
                      }
                    >
                      {artifact.label}
                    </button>
                  </td>
                  <td>{artifact.artifact_type}</td>
                  <td>{artifact.uri || "—"}</td>
                </tr>
              ))}
              {!payload.artifacts.length ? (
                <tr>
                  <td colSpan={3} className="muted">No artifacts captured.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function PlatformSettingsPanel() {
  return <PlatformSettingsHubPage />;
}

function ArtifactListPanel({
  namespace,
  workspaceId,
  query,
  queryError,
  onOpenArtifactDetail,
  panel,
  onContextChange,
  onTitleChange,
}: {
  namespace?: string;
  workspaceId?: string;
  query?: ArtifactStructuredQuery;
  queryError?: string;
  onOpenArtifactDetail: (slug: string) => void;
  panel: ConsolePanelSpec | null;
  onContextChange?: ContextEmitter;
  onTitleChange?: (title: string) => void;
}) {
  const [payload, setPayload] = useState<ArtifactCanvasTableResponse | null>(null);
  const [activeQuery, setActiveQuery] = useState<ArtifactStructuredQuery>(baseArtifactQuery());
  const [selectedRowIds, setSelectedRowIds] = useState<string[]>([]);
  const [focusedRowId, setFocusedRowId] = useState<string | null>(null);
  const [rowOrderIds, setRowOrderIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (query) {
      setActiveQuery(query);
      return;
    }
    if (namespace) {
      setActiveQuery({
        ...baseArtifactQuery(),
        filters: [{ field: "namespace", op: "eq", value: namespace }],
      });
      return;
    }
    setActiveQuery(baseArtifactQuery());
  }, [namespace, query]);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const next = await queryArtifactCanvasTable({ workspaceId: workspaceId || undefined, query: activeQuery });
        if (!active) return;
        setPayload(next);
        setRowOrderIds((next.dataset.rows || []).map((row, index) => String(row[next.dataset.primary_key] || index)));
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load artifacts");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [activeQuery, workspaceId]);

  useEffect(() => {
    emitTableContext({ onContextChange, panel, payload, query: activeQuery, selectedRowIds, focusedRowId, rowOrderIds });
  }, [activeQuery, focusedRowId, onContextChange, panel, payload, rowOrderIds, selectedRowIds]);

  useEffect(() => {
    if (!onTitleChange) return;
    if (!payload?.title) return;
    onTitleChange(String(payload.title));
  }, [onTitleChange, payload?.title]);

  if (loading) return <p className="muted">Loading artifacts…</p>;
  if (queryError) return <p className="muted">{queryError}</p>;
  if (error) return <p className="danger-text">{error}</p>;
  if (!payload) return <p className="muted">No artifacts found.</p>;

  return (
    <CanvasRenderer
      payload={payload}
      query={activeQuery}
      onSort={(field, sortable) => {
        if (!sortable) return;
        const same = activeQuery.sort?.[0]?.field === field;
        const dir = same && activeQuery.sort?.[0]?.dir === "asc" ? "desc" : "asc";
        setActiveQuery((current) => ({ ...current, sort: [{ field, dir }] }));
      }}
      onRowActivate={(rowId) => {
        setSelectedRowIds([rowId]);
        setFocusedRowId(rowId);
      }}
      onOpenDetail={(target) => {
        if (target.entity_type === "artifact") {
          onOpenArtifactDetail(target.entity_id);
        }
      }}
    />
  );
}

function EmsCanvasPanel({
  fetcher,
  initialQuery,
  queryError,
  panel,
  onContextChange,
  onOpenDetail,
  onTitleChange,
}: {
  fetcher: (query: CanvasQuery) => Promise<CanvasTableResponse>;
  initialQuery: CanvasQuery;
  queryError?: string;
  panel: ConsolePanelSpec | null;
  onContextChange?: ContextEmitter;
  onOpenDetail: (target: OpenDetailTarget, row: Record<string, unknown>) => void;
  onTitleChange?: (title: string) => void;
}) {
  const [payload, setPayload] = useState<CanvasTableResponse | null>(null);
  const [query, setQuery] = useState<CanvasQuery>(initialQuery);
  const [selectedRowIds, setSelectedRowIds] = useState<string[]>([]);
  const [focusedRowId, setFocusedRowId] = useState<string | null>(null);
  const [rowOrderIds, setRowOrderIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setQuery(initialQuery), [initialQuery]);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const next = await fetcher(query);
        if (!active) return;
        setPayload(next);
        setRowOrderIds((next.dataset.rows || []).map((row, index) => String(row[next.dataset.primary_key] || index)));
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load panel");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [fetcher, query]);

  useEffect(() => {
    emitTableContext({ onContextChange, panel, payload, query, selectedRowIds, focusedRowId, rowOrderIds });
  }, [focusedRowId, onContextChange, panel, payload, query, rowOrderIds, selectedRowIds]);

  useEffect(() => {
    if (!onTitleChange) return;
    if (!payload?.title) return;
    onTitleChange(String(payload.title));
  }, [onTitleChange, payload?.title]);

  if (loading) return <p className="muted">Loading…</p>;
  if (queryError) return <p className="muted">{queryError}</p>;
  if (error) return <p className="danger-text">{error}</p>;
  if (!payload) return <p className="muted">No rows.</p>;

  return (
    <CanvasRenderer
      payload={payload}
      query={query}
      onSort={(field, sortable) => {
        if (!sortable) return;
        const same = query.sort?.[0]?.field === field;
        const dir = same && query.sort?.[0]?.dir === "asc" ? "desc" : "asc";
        setQuery((current) => ({ ...current, sort: [{ field, dir }] }));
      }}
      onRowActivate={(rowId) => {
        setSelectedRowIds([rowId]);
        setFocusedRowId(rowId);
      }}
      onOpenDetail={onOpenDetail}
    />
  );
}

function ArtifactDetailPanel({
  slug,
  onOpenPanel,
  panel,
  onContextChange,
}: { slug: string; panel: ConsolePanelSpec | null; onContextChange?: ContextEmitter } & PanelProps) {
  const params = useParams();
  const navigate = useNavigate();
  const workspaceId = String(params.workspaceId || "").trim();
  const [payload, setPayload] = useState<ArtifactConsoleDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const next = await getArtifactConsoleDetailBySlug(slug, { workspaceId: workspaceId || undefined });
        if (!active) return;
        setPayload(next);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load artifact detail");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [slug, workspaceId]);

  useEffect(() => {
    if (!onContextChange || !panel?.panel_id || !payload) return;
    onContextChange({
      view_type: "detail",
      entity_type: "artifact",
      entity_id: payload.artifact.slug,
      available_tabs: ["overview", "raw", "files", "manage", "docs"],
      active_tab: String(panel.params?.tab || "overview"),
      ui: {
        active_panel_id: panel.panel_id,
        panel_id: panel.panel_id,
        panel_type: panel.panel_type || "detail",
        instance_key: panel.instance_key || `artifact:${payload.artifact.slug}`,
        active_group_id: panel.active_group_id || null,
        layout_engine: "simple",
      },
    });
  }, [onContextChange, panel, payload]);

  if (loading) return <p className="muted">Loading artifact detail…</p>;
  if (error) return <p className="danger-text">{error}</p>;
  if (!payload) return <p className="muted">Artifact not found.</p>;

  const manage = payload.manifest_summary?.surfaces?.manage || [];
  const docs = payload.manifest_summary?.surfaces?.docs || [];

  const resolveSurfacePath = (path: string) => {
    const normalized = String(path || "").trim();
    if (!normalized) return "";
    if (/^https?:\/\//i.test(normalized)) return normalized;
    if (/^\/w\/[^/]+\/.+/.test(normalized)) return normalized;
    if (normalized.startsWith("/")) return workspaceId ? toWorkspacePath(workspaceId, normalized.replace(/^\/+/, "")) : normalized;
    return workspaceId ? toWorkspacePath(workspaceId, normalized) : `/${normalized}`;
  };

  const openSurfacePath = (path: string) => {
    const target = resolveSurfacePath(path);
    if (!target) return;
    if (/^https?:\/\//i.test(target)) {
      window.location.href = target;
      return;
    }
    navigate(target);
  };

  return (
    <div className="ems-panel-body">
      <p className="muted">
        {payload.artifact.slug} · {payload.artifact.kind} · v{payload.artifact.version}
      </p>
      <p className="muted small">Roles: {(payload.manifest_summary?.roles || []).join(", ") || "none"}</p>
      <div className="inline-actions">
        <button type="button" className="ghost sm" onClick={() => onOpenPanel("artifact_raw_json", { slug: payload.artifact.slug })}>
          Open Raw JSON
        </button>
        <button type="button" className="ghost sm" onClick={() => onOpenPanel("artifact_files", { slug: payload.artifact.slug })}>
          Open Files
        </button>
      </div>
      {manage.length ? (
        <div>
          <p className="small muted">Manage surfaces</p>
          <ul className="muted">
            {manage.map((entry) => (
              <li key={`${entry.path}:${entry.label}`}>
                <button type="button" className="ghost sm" onClick={() => openSurfacePath(entry.path)}>
                  {entry.label}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {docs.length ? (
        <div>
          <p className="small muted">Docs surfaces</p>
          <ul className="muted">
            {docs.map((entry) => (
              <li key={`${entry.path}:${entry.label}`}>
                <button type="button" className="ghost sm" onClick={() => openSurfacePath(entry.path)}>
                  {entry.label}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function ArtifactRawJsonPanel({ slug }: { slug: string }) {
  const params = useParams();
  const workspaceId = String(params.workspaceId || "").trim();
  const [payload, setPayload] = useState<ArtifactConsoleDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const next = await getArtifactConsoleDetailBySlug(slug, { workspaceId: workspaceId || undefined });
        if (!active) return;
        setPayload(next);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load raw JSON");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [slug, workspaceId]);

  if (loading) return <p className="muted">Loading raw JSON…</p>;
  if (error) return <p className="danger-text">{error}</p>;
  return <pre className="code-block">{JSON.stringify(payload?.raw_artifact_json || {}, null, 2)}</pre>;
}

function ArtifactFilesPanel({ slug }: { slug: string }) {
  const [rows, setRows] = useState<ArtifactConsoleFileRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const next = await getArtifactConsoleFilesBySlug(slug);
        if (!active) return;
        setRows(next.files || []);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load files");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [slug]);

  if (loading) return <p className="muted">Loading files…</p>;
  if (error) return <p className="danger-text">{error}</p>;

  return (
    <div className="ems-panel-body">
      <table className="canvas-table">
        <thead>
          <tr>
            <th>Path</th>
            <th>Size</th>
            <th>SHA256</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.path}>
              <td>{row.path}</td>
              <td>{row.size_bytes}</td>
              <td className="muted small">{row.sha256}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GenericRecordDetailPanel({
  entityType,
  entityId,
  dataset,
  row,
  panel,
  onContextChange,
}: {
  entityType: string;
  entityId: string;
  dataset?: string;
  row?: Record<string, unknown>;
  panel: ConsolePanelSpec | null;
  onContextChange?: ContextEmitter;
}) {
  useEffect(() => {
    if (!onContextChange || !panel?.panel_id) return;
    onContextChange({
      view_type: "detail",
      entity_type: entityType,
      entity_id: entityId,
      available_tabs: ["overview", "raw"],
      active_tab: "overview",
      ui: {
        active_panel_id: panel.panel_id,
        panel_id: panel.panel_id,
        panel_type: panel.panel_type || "detail",
        instance_key: panel.instance_key || `${entityType}:${entityId}`,
        active_group_id: panel.active_group_id || null,
        layout_engine: "simple",
      },
    });
  }, [entityId, entityType, onContextChange, panel]);

  return (
    <div className="ems-panel-body">
      <p className="muted">
        {entityType} · {entityId}
      </p>
      {dataset ? <p className="muted small">Dataset: {dataset}</p> : null}
      <pre className="code-block">{JSON.stringify(row || {}, null, 2)}</pre>
    </div>
  );
}

function LocalProvisionResultPanel({ payload }: { payload?: LocalProvisionResponse | null }) {
  if (!payload) return <p className="muted">No provisioning result available.</p>;
  return (
    <div className="ems-panel-body">
      <p className="muted">
        {payload.status} · {payload.compose_project}
      </p>
      <div className="inline-actions">
        {payload.ui_url ? (
          <a className="ghost sm" href={payload.ui_url} target="_blank" rel="noreferrer">
            Open UI
          </a>
        ) : null}
        {payload.api_url ? (
          <a className="ghost sm" href={payload.api_url} target="_blank" rel="noreferrer">
            Open API
          </a>
        ) : null}
      </div>
      <pre className="code-block">{JSON.stringify(payload, null, 2)}</pre>
    </div>
  );
}

const PANEL_TITLES: Record<ConsolePanelKey, string> = {
  platform_settings: "Platform Settings",
  workspaces: "Workspaces",
  goal_list: "Goals",
  goal_detail: "Goal",
  thread_list: "Threads",
  thread_detail: "Thread",
  runs: "Runs",
  drafts_list: "Drafts",
  draft_detail: "Build Draft",
  jobs_list: "Jobs",
  job_detail: "Pipeline Job",
  work_items: "Work Items",
  work_item_detail: "Work Item",
  palette_result: "Palette Result",
  app_builder_artifact_list: "Artifacts",
  run_detail: "Run Detail",
  artifact_list: "Artifact List",
  artifact_detail: "Artifact Detail",
  artifact_raw_json: "Artifact Raw JSON",
  artifact_files: "Artifact Files",
  ems_devices: "EMS Devices",
  ems_registrations: "EMS Registrations",
  ems_device_status_rollup: "EMS Device Status Rollup",
  ems_registrations_timeseries: "EMS Registrations Timeseries",
  ems_dataset_schema: "Dataset Schema",
  ems_unregistered_devices: "Unregistered Devices",
  ems_registrations_time: "Registrations (Past N Hours)",
  ems_device_statuses: "Device Statuses",
  record_detail: "Record Detail",
  local_provision_result: "Local Provision Result",
};

export function panelTitleFor(key: ConsolePanelKey): string {
  return PANEL_TITLES[key];
}

function titleCaseToken(value: string): string {
  return String(value || "")
    .split(/[_\-\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function humanizePanelTitle(panel: ConsolePanelSpec, resolvedTitle: string): string {
  const trimmedResolved = String(resolvedTitle || "").trim();
  if (trimmedResolved) return trimmedResolved;
  const trimmedPanelTitle = String(panel.title || "").trim();
  if (trimmedPanelTitle && trimmedPanelTitle !== panel.key) return trimmedPanelTitle;
  const instanceKey = String(panel.instance_key || "").trim();
  if (instanceKey) {
    const datasetToken = instanceKey.includes(":") ? instanceKey.split(":", 1)[0] : instanceKey;
    const asTitle = titleCaseToken(datasetToken);
    if (asTitle) {
      if (panel.panel_type === "table" && !/\b(List|Table)\b/i.test(asTitle)) return `${asTitle} List`;
      return asTitle;
    }
  }
  return panelTitleFor(panel.key);
}

export default function WorkbenchPanelHost({
  panel,
  workspaceId,
  workspaceName,
  workspaceColor,
  onOpenPanel,
  onClosePanel,
  onContextChange,
}: {
  panel: ConsolePanelSpec | null;
  workspaceId: string;
  workspaceName?: string;
  workspaceColor?: string;
  onOpenPanel: (panel: ConsolePanelSpec) => void;
  onClosePanel?: () => void;
  onContextChange?: ContextEmitter;
}) {
  const [resolvedTitle, setResolvedTitle] = useState("");
  useEffect(() => {
    setResolvedTitle("");
  }, [panel?.panel_id, panel?.key]);

  const content = useMemo(() => {
    if (!panel) return null;
    const openPanel = (
      panelKey: ConsolePanelKey,
      params?: Record<string, unknown>,
      options?: { open_in?: "current_panel" | "new_panel" | "side_by_side"; return_to_panel_id?: string }
    ) =>
      onOpenPanel({
        key: panelKey,
        params: params || {},
        open_in: options?.open_in,
        return_to_panel_id: options?.return_to_panel_id,
      });

    if (panel.key === "platform_settings") {
      return <PlatformSettingsPanel />;
    }

    if (panel.key === "workspaces") {
      return (
        <WorkspacesPanel
          query={(panel.params?.query as CanvasQuery | undefined) || undefined}
          queryError={String(panel.params?.query_error || "")}
          panel={panel}
          onContextChange={onContextChange}
          onTitleChange={setResolvedTitle}
          onOpenDetail={(target) => {
            if (target.entity_type === "workspace") {
              openPanel("record_detail", { ...target }, { open_in: "new_panel", return_to_panel_id: panel.panel_id });
              return;
            }
            openPanel("record_detail", { ...target }, { open_in: "new_panel", return_to_panel_id: panel.panel_id });
          }}
        />
      );
    }

    if (panel.key === "runs") {
      return (
        <RunsPanel
          workspaceId={workspaceId}
          query={(panel.params?.query as CanvasQuery | undefined) || undefined}
          queryError={String(panel.params?.query_error || "")}
          panel={panel}
          onContextChange={onContextChange}
          onTitleChange={setResolvedTitle}
          onOpenDetail={(target, row) => {
            if (target.entity_type === "run") {
              openPanel("run_detail", { run_id: target.entity_id }, { open_in: "new_panel", return_to_panel_id: panel.panel_id });
              return;
            }
            openPanel("record_detail", { ...target, row }, { open_in: "new_panel", return_to_panel_id: panel.panel_id });
          }}
        />
      );
    }

    if (panel.key === "drafts_list") {
      return (
        <DraftsListPage
          workspaceId={workspaceId}
          workspaceName={workspaceName || "Unknown"}
          workspaceColor={workspaceColor}
          workspaceBarVariant="compact"
          onSelectDraft={(draftId) => openPanel("draft_detail", { draft_id: draftId }, { open_in: "new_panel", return_to_panel_id: panel.panel_id })}
        />
      );
    }

    if (panel.key === "jobs_list") {
      return (
        <JobsListPage
          workspaceId={workspaceId}
          workspaceName={workspaceName || "Unknown"}
          workspaceColor={workspaceColor}
          workspaceBarVariant="compact"
          onSelectJob={(jobId) => openPanel("job_detail", { job_id: jobId }, { open_in: "new_panel", return_to_panel_id: panel.panel_id })}
        />
      );
    }

    if (panel.key === "work_items") {
      return (
        <WorkItemsPanel
          workspaceId={workspaceId}
          panel={panel}
          onContextChange={onContextChange}
          onTitleChange={setResolvedTitle}
          onOpenDetail={(target, row) => {
            if (target.entity_type === "work_item") {
              openPanel("work_item_detail", { work_item_id: target.entity_id }, { open_in: "new_panel", return_to_panel_id: panel.panel_id });
              return;
            }
            openPanel("record_detail", { ...target, row }, { open_in: "new_panel", return_to_panel_id: panel.panel_id });
          }}
        />
      );
    }

    if (panel.key === "goal_list") {
      return <GoalListPanel workspaceId={workspaceId} onOpenPanel={openPanel} onTitleChange={setResolvedTitle} />;
    }

    if (panel.key === "goal_detail") {
      return (
        <GoalDetailPanel
          goalId={String(panel.params?.goal_id || "")}
          workspaceId={workspaceId}
          onOpenPanel={openPanel}
          onTitleChange={setResolvedTitle}
        />
      );
    }

    if (panel.key === "thread_list") {
      return <ThreadListPanel workspaceId={workspaceId} onOpenPanel={openPanel} onTitleChange={setResolvedTitle} />;
    }

    if (panel.key === "thread_detail") {
      return (
        <ThreadDetailPanel
          threadId={String(panel.params?.thread_id || "")}
          workspaceId={workspaceId}
          onOpenPanel={openPanel}
          onTitleChange={setResolvedTitle}
        />
      );
    }

    if (panel.key === "draft_detail") {
      return (
        <DraftDetailPage
          workspaceId={workspaceId}
          workspaceName={workspaceName || "Unknown"}
          workspaceColor={workspaceColor}
          workspaceBarVariant="compact"
          draftId={String(panel.params?.draft_id || "")}
          linkedJobId={String(panel.params?.job_id || "")}
          onBack={() => {
            if (panel.return_to_panel_id) {
              onClosePanel?.();
            }
          }}
          onOpenJob={(jobId) => openPanel("job_detail", { job_id: jobId }, { open_in: "new_panel", return_to_panel_id: panel.panel_id })}
          onOpenArtifacts={(kind) =>
            openPanel("app_builder_artifact_list", { kind: String(kind || "") }, { open_in: "new_panel", return_to_panel_id: panel.panel_id })
          }
        />
      );
    }

    if (panel.key === "job_detail") {
      return (
        <JobDetailPage
          workspaceId={workspaceId}
          workspaceName={workspaceName || "Unknown"}
          workspaceColor={workspaceColor}
          workspaceBarVariant="compact"
          jobId={String(panel.params?.job_id || "")}
          onBack={() => {
            if (panel.return_to_panel_id) {
              onClosePanel?.();
            }
          }}
        />
      );
    }

    if (panel.key === "work_item_detail") {
      return (
        <WorkItemDetailPanel
          workItemId={String(panel.params?.work_item_id || panel.params?.job_id || "")}
          workspaceId={workspaceId}
          onOpenPanel={openPanel}
        />
      );
    }

    if (panel.key === "palette_result") {
      return (
        <PaletteResultPanel
          result={panel.params?.result as AppPaletteResult | undefined}
          prompt={String(panel.params?.prompt || "")}
          error={String(panel.params?.error || "")}
          workspaceId={workspaceId}
        />
      );
    }

    if (panel.key === "app_builder_artifact_list") {
      return <AppBuilderArtifactListPanel workspaceId={workspaceId} kind={String(panel.params?.kind || "")} />;
    }

    if (panel.key === "run_detail") {
      return (
        <RunDetailPanel
          runId={String(panel.params?.run_id || "")}
          workspaceId={workspaceId}
          panel={panel}
          onContextChange={onContextChange}
          onOpenPanel={openPanel}
        />
      );
    }

    if (panel.key === "artifact_list") {
      return (
        <ArtifactListPanel
          namespace={String(panel.params?.namespace || "")}
          workspaceId={workspaceId}
          query={(panel.params?.query as ArtifactStructuredQuery | undefined) || undefined}
          queryError={String(panel.params?.query_error || "")}
          onOpenArtifactDetail={(slug) => openPanel("artifact_detail", { slug }, { open_in: "new_panel", return_to_panel_id: panel.panel_id })}
          panel={panel}
          onContextChange={onContextChange}
          onTitleChange={setResolvedTitle}
        />
      );
    }

    if (panel.key === "artifact_detail") {
      const runtimeRunId = String(panel.params?.runtime_run_id || "").trim();
      const runtimeArtifactId = String(panel.params?.runtime_artifact_id || "").trim();
      if (runtimeRunId && runtimeArtifactId) {
        return <RuntimeArtifactDetailPanel runId={runtimeRunId} artifactId={runtimeArtifactId} workspaceId={workspaceId} onOpenPanel={openPanel} />;
      }
      return <ArtifactDetailPanel slug={String(panel.params?.slug || "")} panel={panel} onContextChange={onContextChange} onOpenPanel={openPanel} />;
    }
    if (panel.key === "artifact_raw_json") return <ArtifactRawJsonPanel slug={String(panel.params?.slug || "")} />;
    if (panel.key === "artifact_files") return <ArtifactFilesPanel slug={String(panel.params?.slug || "")} />;
    if (panel.key === "record_detail") {
      return (
        <GenericRecordDetailPanel
          entityType={String(panel.params?.entity_type || "record")}
          entityId={String(panel.params?.entity_id || "")}
          dataset={String(panel.params?.dataset || "") || undefined}
          row={(panel.params?.row as Record<string, unknown> | undefined) || undefined}
          panel={panel}
          onContextChange={onContextChange}
        />
      );
    }
    if (panel.key === "local_provision_result") {
      return <LocalProvisionResultPanel payload={(panel.params?.payload as LocalProvisionResponse | undefined) || null} />;
    }

    if (panel.key === "ems_devices" || panel.key === "ems_unregistered_devices") {
      const query = (panel.params?.query as CanvasQuery) || {
        entity: "ems_devices",
        filters: panel.key === "ems_unregistered_devices" ? [{ field: "state", op: "eq", value: "unregistered" }] : [],
        sort: [{ field: "created_at", dir: "desc" }],
        limit: 50,
        offset: 0,
      };
      return (
        <EmsCanvasPanel
          fetcher={(nextQuery) => queryEmsDevicesCanvasTable({ query: nextQuery as never })}
          initialQuery={query}
          queryError={String(panel.params?.query_error || "")}
          panel={panel}
          onContextChange={onContextChange}
          onTitleChange={setResolvedTitle}
          onOpenDetail={(target, row) => {
            openPanel("record_detail", { ...target, row }, { open_in: "new_panel", return_to_panel_id: panel.panel_id });
          }}
        />
      );
    }

    if (panel.key === "ems_registrations" || panel.key === "ems_registrations_time") {
      const hours = Number(panel.params?.hours || 24);
      const query = (panel.params?.query as CanvasQuery) || {
        entity: "ems_registrations",
        filters: [{ field: "registered_at", op: "gte", value: `now-${Math.max(1, Math.min(hours, 168))}h` }],
        sort: [{ field: "registered_at", dir: "desc" }],
        limit: 50,
        offset: 0,
      };
      return (
        <EmsCanvasPanel
          fetcher={(nextQuery) => queryEmsRegistrationsCanvasTable({ query: nextQuery as never })}
          initialQuery={query}
          queryError={String(panel.params?.query_error || "")}
          panel={panel}
          onContextChange={onContextChange}
          onTitleChange={setResolvedTitle}
          onOpenDetail={(target, row) => {
            openPanel("record_detail", { ...target, row }, { open_in: "new_panel", return_to_panel_id: panel.panel_id });
          }}
        />
      );
    }

    if (panel.key === "ems_device_status_rollup" || panel.key === "ems_device_statuses") {
      return (
        <EmsCanvasPanel
          fetcher={() => getEmsStatusRollupCanvasTable()}
          initialQuery={{ entity: "ems_device_status_rollup", filters: [], sort: [{ field: "bucket", dir: "asc" }], limit: 50, offset: 0 }}
          panel={panel}
          onContextChange={onContextChange}
          onTitleChange={setResolvedTitle}
          onOpenDetail={(target, row) => {
            openPanel("record_detail", { ...target, row }, { open_in: "new_panel", return_to_panel_id: panel.panel_id });
          }}
        />
      );
    }

    if (panel.key === "ems_registrations_timeseries") {
      const hours = Number(panel.params?.hours || 24);
      return (
        <EmsCanvasPanel
          fetcher={() => getEmsRegistrationsTimeseriesCanvasTable({ range: `now-${Math.max(1, Math.min(hours, 168))}h`, bucket: "1h" })}
          initialQuery={{
            entity: "ems_registrations_timeseries",
            filters: [{ field: "bucket_start", op: "gte", value: `now-${Math.max(1, Math.min(hours, 168))}h` }],
            sort: [{ field: "bucket_start", dir: "asc" }],
            limit: 50,
            offset: 0,
          }}
          panel={panel}
          onContextChange={onContextChange}
          onTitleChange={setResolvedTitle}
          onOpenDetail={(target, row) => {
            openPanel("record_detail", { ...target, row }, { open_in: "new_panel", return_to_panel_id: panel.panel_id });
          }}
        />
      );
    }

    if (panel.key === "ems_dataset_schema") {
      const dataset = String(panel.params?.dataset || "ems_devices");
      return (
        <EmsCanvasPanel
          fetcher={() => getEmsDatasetSchemaTable(dataset)}
          initialQuery={{ entity: "dataset_schema", filters: [], sort: [{ field: "key", dir: "asc" }], limit: 200, offset: 0 }}
          panel={panel}
          onContextChange={onContextChange}
          onTitleChange={setResolvedTitle}
          onOpenDetail={(target, row) => {
            openPanel("record_detail", { ...target, row }, { open_in: "new_panel", return_to_panel_id: panel.panel_id });
          }}
        />
      );
    }

    return null;
  }, [onContextChange, onOpenPanel, panel, workspaceId]);

  if (!panel) {
    return null;
  }

  return <div className="card ems-panel-host">{content || <p className="muted">Unknown panel.</p>}</div>;
}
